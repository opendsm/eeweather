"""The client-side registry update, against miniature copies of the
packaged data (full refreshes of the real files are far too slow for a
test suite)."""
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import requests

import eeweather.registry.db as registry_db
import eeweather.registry.update as registry_update
from eeweather.registry.db import data_path



N_STATIONS = 50


def _tables_with_station_id(conn):
    tables = [
        row[0]
        for row in conn.execute("select name from sqlite_master where type = 'table'")
    ]
    matched = []
    for table in tables:
        columns = [row[1] for row in conn.execute(f"pragma table_info({table})")]
        if "station_id" in columns:
            matched.append(table)

    return matched


@pytest.fixture(scope="module")
def mini_packaged(tmp_path_factory):
    """Copies of the packaged databases cut down to N_STATIONS stations."""
    directory = str(tmp_path_factory.mktemp("packaged"))
    paths = {}
    for filename, packaged in registry_update.UPDATABLE.items():
        dest = os.path.join(directory, filename)
        shutil.copy(packaged, dest)
        paths[filename] = dest

    ghcnh = sqlite3.connect(paths["ghcnh.db"])
    keep = [
        row[0]
        for row in ghcnh.execute(
            "select station_id from stations order by station_id limit ?",
            (N_STATIONS,),
        )
    ]
    ghcnh.close()
    marks = ", ".join("?" for _ in keep)
    for path in paths.values():
        conn = sqlite3.connect(path)
        for table in _tables_with_station_id(conn):
            conn.execute(
                f"delete from {table} where station_id not in ({marks})", keep
            )
        conn.commit()
        conn.execute("vacuum")
        conn.close()

    return paths, keep


@pytest.fixture
def patched_update(mini_packaged, tmp_path, monkeypatch):
    paths, keep = mini_packaged
    directory = str(tmp_path / "registry")
    monkeypatch.setattr(registry_db, "UPDATED_DATA_DIR", directory)
    monkeypatch.setattr(registry_update, "UPDATED_DATA_DIR", directory)
    monkeypatch.setattr(registry_update, "UPDATABLE", dict(paths))

    return directory, paths, keep


@pytest.fixture
def live_files_from_mini_catalog(patched_update, monkeypatch):
    """Synthetic NOAA responses covering the mini catalog, sized so the
    plausibility floors pass."""
    _, paths, keep = patched_update
    conn = sqlite3.connect(paths["ghcnh.db"])
    n_inventory = conn.execute("select count(*) from inventory").fetchone()[0]
    conn.close()

    station_list = {
        sid: ("NAME", "0.0", "0.0", "0.0", "", "", "") for sid in keep
    }
    years_per_station = int(0.9 * n_inventory / len(keep)) + 2
    inventory = [
        (sid, year) + (700,) * 12
        for sid in keep
        for year in range(2025 - years_per_station, 2025)
    ]
    monkeypatch.setattr(
        "eeweather.build.refresh._fetch_station_list", lambda: station_list
    )
    monkeypatch.setattr(
        "eeweather.build.refresh._fetch_inventory", lambda: inventory
    )

    return len(inventory)


@pytest.fixture
def no_release_channel(monkeypatch):
    def unreachable(url, dest):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(registry_update, "_download", unreachable)


@pytest.fixture
def published_pack(patched_update, tmp_path, monkeypatch):
    """A rolling-release pack: the mini databases restamped as freshly
    refreshed, served through the download seam."""
    _, paths, _ = patched_update
    pack_dir = tmp_path / "release"
    pack_dir.mkdir()
    published = {}
    for filename, mini in paths.items():
        dest = str(pack_dir / filename)
        shutil.copy(mini, dest)
        published[filename] = dest
    newer = registry_update.refreshed_at() + timedelta(days=1)
    _stamp(published["ghcnh.db"], newer.strftime("%Y-%m-%d"))

    def download_from_pack(url, dest):
        filename = url.rsplit("/", 1)[1]
        shutil.copy(published[filename], dest)

    monkeypatch.setattr(registry_update, "_download", download_from_pack)

    return published


def _stamp(path, value):
    conn = sqlite3.connect(path)
    conn.execute(
        "insert or replace into meta values ('refreshed_at', ?)", (value,)
    )
    conn.commit()
    conn.close()


def test_update_installs_published_pack_without_rebuilding(
    patched_update, published_pack, monkeypatch
):
    directory, _, keep = patched_update

    def no_rebuild(**kwargs):
        raise AssertionError("published channel must not rebuild from NOAA")

    monkeypatch.setattr(registry_update, "refresh", no_rebuild)

    summary = registry_update.update()

    assert summary["channel"] == "published"
    installed = os.path.join(directory, "ghcnh.db")
    assert registry_update.refreshed_at(installed) is not None
    conn = sqlite3.connect(installed)
    n_stations = conn.execute("select count(*) from stations").fetchone()[0]
    conn.close()
    assert n_stations == len(keep)
    assert not os.path.exists(installed + ".download")


def test_update_falls_back_to_rebuild_when_channel_unreachable(
    patched_update, no_release_channel, live_files_from_mini_catalog
):
    counts = registry_update.update()

    assert counts["inventory_rows"] == live_files_from_mini_catalog


def test_update_falls_back_when_published_pack_is_stale(
    patched_update, published_pack, live_files_from_mini_catalog
):
    _stamp(published_pack["ghcnh.db"], "2020-01-01")

    counts = registry_update.update()

    assert counts["inventory_rows"] == live_files_from_mini_catalog


def test_update_falls_back_when_published_pack_is_not_newer(
    patched_update, published_pack, live_files_from_mini_catalog
):
    _stamp(
        published_pack["ghcnh.db"],
        registry_update.refreshed_at().strftime("%Y-%m-%d"),
    )

    counts = registry_update.update()

    assert counts["inventory_rows"] == live_files_from_mini_catalog


def test_update_falls_back_when_published_pack_is_implausible(
    patched_update, published_pack, live_files_from_mini_catalog
):
    conn = sqlite3.connect(published_pack["ghcnh.db"])
    conn.execute(
        "delete from stations where station_id not in"
        " (select station_id from stations limit 5)"
    )
    conn.commit()
    conn.close()

    counts = registry_update.update()

    assert counts["inventory_rows"] == live_files_from_mini_catalog


def test_update_copies_then_refreshes_in_user_data_dir(
    patched_update, no_release_channel, live_files_from_mini_catalog
):
    directory, paths, keep = patched_update

    counts = registry_update.update()

    assert counts["stations_added"] == 0
    assert counts["inventory_rows"] == live_files_from_mini_catalog
    updated_path = os.path.join(directory, "ghcnh.db")
    updated = sqlite3.connect(updated_path)
    n_rows = updated.execute("select count(*) from inventory").fetchone()[0]
    updated.close()
    assert n_rows == live_files_from_mini_catalog
    # the refresh restamps the updated copy
    assert registry_update.refreshed_at(updated_path) >= (
        registry_update.refreshed_at(paths["ghcnh.db"])
    )
    assert not os.path.exists(updated_path + ".staging")
    # the mini "packaged" copies are untouched
    packaged = sqlite3.connect(paths["ghcnh.db"])
    n_packaged = packaged.execute("select count(*) from inventory").fetchone()[0]
    packaged.close()
    assert n_packaged != n_rows


def test_data_path_prefers_updated_copy(patched_update):
    directory, _, _ = patched_update
    os.makedirs(directory, exist_ok=True)
    override = os.path.join(directory, "ghcnh.db")
    open(override, "w").close()

    # without the commit marker, an uncertified (possibly torn) copy is ignored
    assert data_path("/packaged/ghcnh.db") == "/packaged/ghcnh.db"

    open(os.path.join(directory, registry_db.COMMIT_MARKER), "w").close()
    assert data_path("/packaged/ghcnh.db") == override
    # geography packs never live in the updated dir, so they always resolve
    # to the packaged copy regardless of the marker
    assert data_path("/packaged/geography_us.db") == "/packaged/geography_us.db"


def test_partial_updated_dir_without_marker_is_ignored(patched_update):
    directory, paths, _ = patched_update
    os.makedirs(directory, exist_ok=True)
    for filename, packaged in paths.items():
        shutil.copy(packaged, os.path.join(directory, filename))

    assert data_path(paths["ghcnh.db"]) == paths["ghcnh.db"]
    assert data_path(paths["identifiers.db"]) == paths["identifiers.db"]


def test_completed_update_writes_marker_and_serves_updated_pair(
    patched_update, published_pack, monkeypatch
):
    directory, paths, _ = patched_update

    def no_rebuild(**kwargs):
        raise AssertionError("published channel must not rebuild from NOAA")

    monkeypatch.setattr(registry_update, "refresh", no_rebuild)

    registry_update.update()

    assert os.path.exists(os.path.join(directory, registry_db.COMMIT_MARKER))
    assert data_path(paths["ghcnh.db"]) == os.path.join(directory, "ghcnh.db")
    assert data_path(paths["identifiers.db"]) == os.path.join(
        directory, "identifiers.db"
    )


def test_partial_swap_falls_back_then_next_update_heals(
    patched_update, published_pack, monkeypatch
):
    directory, paths, _ = patched_update
    os.makedirs(directory, exist_ok=True)
    now = datetime.now(timezone.utc)

    real_replace = os.replace
    fail = {"active": True}

    def replace_failing_on_identifiers(src, dst):
        if fail["active"] and os.path.basename(dst) == "identifiers.db":
            raise OSError("disk full during swap")

        return real_replace(src, dst)

    monkeypatch.setattr(
        registry_update.os, "replace", replace_failing_on_identifiers
    )

    assert registry_update._install_published(now) is None
    # the second replace failed, so no marker was written and reads resolve
    # to the internally consistent packaged pair (no torn ghcnh/identifiers mix)
    assert not os.path.exists(os.path.join(directory, registry_db.COMMIT_MARKER))
    assert data_path(paths["ghcnh.db"]) == paths["ghcnh.db"]
    assert data_path(paths["identifiers.db"]) == paths["identifiers.db"]

    fail["active"] = False
    published = registry_update._install_published(now)

    assert published is not None
    assert os.path.exists(os.path.join(directory, registry_db.COMMIT_MARKER))
    assert data_path(paths["ghcnh.db"]) == os.path.join(directory, "ghcnh.db")
    assert data_path(paths["identifiers.db"]) == os.path.join(
        directory, "identifiers.db"
    )


def test_reupdate_partial_swap_does_not_serve_torn_pair(
    patched_update, published_pack, monkeypatch
):
    directory, paths, _ = patched_update
    os.makedirs(directory, exist_ok=True)
    now = datetime.now(timezone.utc)

    # first update completes: marker present, updated pair served
    assert registry_update._install_published(now) is not None
    assert os.path.exists(os.path.join(directory, registry_db.COMMIT_MARKER))

    # a re-update fails on the second file; the pre-existing marker must be
    # retracted before the swap so the torn pair is never certified
    real_replace = os.replace

    def replace_failing_on_identifiers(src, dst):
        if os.path.basename(dst) == "identifiers.db":
            raise OSError("disk full during re-update")

        return real_replace(src, dst)

    monkeypatch.setattr(
        registry_update.os, "replace", replace_failing_on_identifiers
    )

    assert registry_update._install_published(now) is None
    assert not os.path.exists(os.path.join(directory, registry_db.COMMIT_MARKER))
    assert data_path(paths["ghcnh.db"]) == paths["ghcnh.db"]
    assert data_path(paths["identifiers.db"]) == paths["identifiers.db"]


def test_clear_removes_updated_copies(patched_update):
    directory, paths, _ = patched_update
    os.makedirs(directory, exist_ok=True)
    for filename, packaged in paths.items():
        shutil.copy(packaged, os.path.join(directory, filename))

    removed = registry_update.clear()

    # every updatable file, whatever the set is -- geography packs joined it
    assert len(removed) == len(paths)
    assert os.listdir(directory) == []
    assert registry_update.clear() == []


def test_implausible_upstream_aborts_and_preserves_data(
    patched_update, no_release_channel, monkeypatch
):
    directory, _, keep = patched_update
    monkeypatch.setattr(
        "eeweather.build.refresh._fetch_station_list", lambda: {}
    )
    monkeypatch.setattr(
        "eeweather.build.refresh._fetch_inventory", lambda: []
    )

    with pytest.raises(RuntimeError, match="Implausible"):
        registry_update.update()

    # the staged copy is discarded; no partial state lands in the user dir
    assert not os.path.exists(os.path.join(directory, "ghcnh.db"))
    packaged = sqlite3.connect(registry_update.UPDATABLE["ghcnh.db"])
    n_stations = packaged.execute("select count(*) from stations").fetchone()[0]
    packaged.close()
    assert n_stations == len(keep)


def test_refreshed_at_none_when_unstamped(tmp_path):
    path = str(tmp_path / "unstamped.db")
    sqlite3.connect(path).close()

    assert registry_update.refreshed_at(path) is None


def _db_with_meta_table(path):
    conn = sqlite3.connect(path)
    conn.execute("create table meta (key text primary key, value text)")
    conn.commit()
    conn.close()


def test_auto_updating_sources_excludes_meta_less_dbs():
    """identifiers.db is refreshed alongside ghcnh.db but carries no meta
    table, and tmy3.db/cz2010.db carry none either; only ghcnh.db drives
    staleness."""
    assert set(registry_update.AUTO_UPDATING_SOURCES) == {"ghcnh.db"}


def test_stamp_round_trips_through_refreshed_at_for_auto_updating_source(tmp_path):
    path = str(tmp_path / "ghcnh.db")
    _db_with_meta_table(path)
    _stamp(path, "2026-01-15")

    assert registry_update.refreshed_at(path) == datetime(
        2026, 1, 15, tzinfo=timezone.utc
    )


def test_stale_false_when_auto_updating_source_freshly_stamped(tmp_path, monkeypatch):
    path = str(tmp_path / "ghcnh.db")
    _db_with_meta_table(path)
    now = datetime.now(timezone.utc)
    _stamp(path, now.strftime("%Y-%m-%d"))
    monkeypatch.setattr(registry_update, "AUTO_UPDATING_SOURCES", {"ghcnh.db": path})

    assert registry_update._stale(now) is False


def test_stale_true_when_auto_updating_source_stamp_too_old(tmp_path, monkeypatch):
    path = str(tmp_path / "ghcnh.db")
    _db_with_meta_table(path)
    now = datetime.now(timezone.utc)
    too_old = now - timedelta(days=registry_update.STALE_AFTER_DAYS + 1)
    _stamp(path, too_old.strftime("%Y-%m-%d"))
    monkeypatch.setattr(registry_update, "AUTO_UPDATING_SOURCES", {"ghcnh.db": path})

    assert registry_update._stale(now) is True


def test_stale_true_when_auto_updating_source_unstamped(tmp_path, monkeypatch):
    path = str(tmp_path / "ghcnh.db")
    _db_with_meta_table(path)
    monkeypatch.setattr(registry_update, "AUTO_UPDATING_SOURCES", {"ghcnh.db": path})

    assert registry_update._stale(datetime.now(timezone.utc)) is True


def test_stale_ignores_source_db_without_meta_table(tmp_path, monkeypatch):
    """A source db lacking a meta table (representing tmy3.db/cz2010.db)
    is excluded from the auto-updating set, so its absence of a stamp
    neither forces staleness nor raises."""
    ghcnh = str(tmp_path / "ghcnh.db")
    _db_with_meta_table(ghcnh)
    now = datetime.now(timezone.utc)
    _stamp(ghcnh, now.strftime("%Y-%m-%d"))
    no_meta = str(tmp_path / "tmy3.db")
    sqlite3.connect(no_meta).close()
    monkeypatch.setattr(registry_update, "AUTO_UPDATING_SOURCES", {"ghcnh.db": ghcnh})

    assert registry_update._stale(now) is False
    assert registry_update.refreshed_at(no_meta) is None


@pytest.fixture
def auto_update(patched_update, monkeypatch):
    monkeypatch.setenv("EEWEATHER_AUTO_UPDATE", "1")
    monkeypatch.setattr(registry_update, "_process_checked", False)
    monkeypatch.setattr(registry_update, "UPDATE_DELAY_SECONDS", 0)

    return patched_update


def test_auto_update_disabled_by_env(patched_update, monkeypatch):
    monkeypatch.setenv("EEWEATHER_AUTO_UPDATE", "0")
    monkeypatch.setattr(registry_update, "_process_checked", False)
    monkeypatch.setattr(
        registry_update, "refreshed_at",
        lambda path=None: datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    assert registry_update.maybe_update() is None


def test_auto_update_skips_fresh_data(auto_update, monkeypatch):
    monkeypatch.setattr(
        registry_update, "refreshed_at",
        lambda path=None: datetime.now(timezone.utc),
    )

    assert registry_update.maybe_update() is None


def test_auto_update_checks_once_per_process(auto_update, monkeypatch):
    calls = []
    monkeypatch.setattr(
        registry_update, "refreshed_at",
        lambda path=None: datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(registry_update, "update", lambda: calls.append(True))

    first = registry_update.maybe_update()
    first.join()
    second = registry_update.maybe_update()

    assert calls == [True]
    assert second is None


def test_auto_update_backs_off_after_recent_attempt(auto_update, monkeypatch):
    calls = []
    monkeypatch.setattr(
        registry_update, "refreshed_at",
        lambda path=None: datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(registry_update, "update", lambda: calls.append(True))

    registry_update.maybe_update().join()
    # a fresh process (checked flag reset) still respects the attempt stamp
    monkeypatch.setattr(registry_update, "_process_checked", False)

    assert registry_update.maybe_update() is None
    assert calls == [True]


def test_auto_update_failure_warns_and_keeps_data(auto_update, monkeypatch):
    def broken_update():
        raise RuntimeError("upstream offline")

    monkeypatch.setattr(registry_update, "update", broken_update)

    with pytest.warns(UserWarning, match="auto-update failed"):
        registry_update._update_or_warn()


def test_claim_attempt_admits_exactly_one_racer(auto_update):
    directory, _, _ = auto_update
    os.makedirs(directory, exist_ok=True)
    now = datetime.now(timezone.utc)

    claims = [registry_update._claim_attempt(now) for _ in range(5)]

    assert claims == [True, False, False, False, False]


def test_claim_attempt_reopens_after_retry_window(auto_update):
    directory, _, _ = auto_update
    os.makedirs(directory, exist_ok=True)
    now = datetime.now(timezone.utc)
    assert registry_update._claim_attempt(now)
    stamp = os.path.join(directory, registry_update._ATTEMPT_STAMP)
    two_days_ago = (now - timedelta(days=2)).timestamp()
    os.utime(stamp, (two_days_ago, two_days_ago))

    assert registry_update._claim_attempt(now)
    assert not registry_update._claim_attempt(now)


def test_update_thread_defers_network_for_short_lived_processes(
    auto_update, monkeypatch
):
    order = []
    monkeypatch.setattr(registry_update, "UPDATE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(
        registry_update, "refreshed_at",
        lambda path=None: datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        registry_update.time, "sleep", lambda s: order.append(("sleep", s))
    )
    monkeypatch.setattr(
        registry_update, "update", lambda: order.append(("update", None))
    )

    registry_update.maybe_update().join()

    assert order == [("sleep", 0.01), ("update", None)]


# --- geography packs are updatable -----------------------------------------
#
# They were excluded on the grounds that geography is static. Census redrew
# the ZCTA boundaries for 2020 and republishes the Gazetteer annually, so the
# packaged pack -- built from the 2010 definition -- drifted fifteen years
# without any refresh being able to correct it.


def test_geography_packs_are_in_the_updatable_set():
    assert registry_update.GEOGRAPHY_FILENAMES
    for filename in registry_update.GEOGRAPHY_FILENAMES:
        assert filename in registry_update.UPDATABLE
        # a truncated download must not be allowed to replace the geography
        assert registry_update._FLOOR_TABLES[filename] == ("place",)


def test_a_downloaded_geography_pack_is_the_one_read(patched_update):
    """The half that made geography updatable in name only.

    _geography_packs globbed the packaged directory directly, so a pack
    could be downloaded, committed, and then silently ignored on read.
    """
    directory, paths, _ = patched_update
    geography = registry_update.GEOGRAPHY_FILENAMES[0]
    os.makedirs(directory, exist_ok=True)
    for filename, packaged in paths.items():
        shutil.copy(packaged, os.path.join(directory, filename))
    registry_update._write_marker()

    live = dict(registry_db._geography_packs())
    alias = os.path.splitext(geography)[0]

    assert live[alias] == os.path.join(directory, geography)


def test_published_pack_may_omit_geography(
    patched_update, published_pack, monkeypatch
):
    """Geography moves annually, the station registry continuously.

    A pack published without geography must refresh the rest and leave the
    existing geography in place, rather than aborting the whole update.
    """
    directory, paths, _ = patched_update
    geography = registry_update.GEOGRAPHY_FILENAMES[0]

    def download_without_geography(url, dest):
        filename = url.rsplit("/", 1)[1]
        if filename == geography:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404 Not Found", response=response)
        shutil.copy(published_pack[filename], dest)

    monkeypatch.setattr(registry_update, "_download", download_without_geography)
    monkeypatch.setattr(
        registry_update, "refresh",
        lambda **kwargs: pytest.fail("rebuilt despite a usable published pack"),
    )

    summary = registry_update.update()

    assert summary["channel"] == "published"
    assert os.path.exists(os.path.join(directory, "ghcnh.db"))
    assert not os.path.exists(os.path.join(directory, geography))
    # nothing was installed for it, so reads fall back to the packaged pack
    # rather than to a hole -- a previously updated pack would likewise stay
    assert not dict(registry_db._geography_packs())[
        os.path.splitext(geography)[0]].startswith(directory)


def test_a_missing_required_file_still_aborts(
    patched_update, published_pack, monkeypatch
):
    """Only geography is optional; a pack missing ghcnh.db is broken."""
    def download_without_ghcnh(url, dest):
        filename = url.rsplit("/", 1)[1]
        if filename == "ghcnh.db":
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404 Not Found", response=response)
        shutil.copy(published_pack[filename], dest)

    monkeypatch.setattr(registry_update, "_download", download_without_ghcnh)
    rebuilt = []
    monkeypatch.setattr(
        registry_update, "refresh",
        lambda **kwargs: rebuilt.append(True) or {"stations": 1},
    )

    registry_update.update()

    assert rebuilt, "should have fallen back to rebuilding from NOAA"
