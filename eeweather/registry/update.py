"""Keep the live registry data current without package releases.

The live packaged data (GHCNh station catalog, observation inventory,
quality ratings, identifier aliases) is updated into the platform user
data directory, where it takes precedence over the wheel's copies in new
processes. Updates prefer the repository's rolling-release channel — the
scheduled refresh publishes ready-made files served from GitHub's CDN,
so any number of clients updating costs NOAA nothing and no client
rebuilds locally. When the channel is unreachable, stale, or no newer
than the local data, the update falls back to rebuilding from the live
NOAA files directly, so updates keep working even if the repository goes
dormant. Geography packs are refreshed from Census on their own annual
cadence and a published pack may omit them; archive station lists are
static and are not part of the update. Implausible files from either
channel abort an update, leaving the previous data in place.

Updates run automatically: loading data or ranking stations starts a
background refresh when the live data is older than ``STALE_AFTER_DAYS``
(quality rating windows advance when a calendar year completes, so six
months caps the lag behind that yearly step). Set
``EEWEATHER_AUTO_UPDATE=0`` to disable. ``python -m
eeweather.registry.update`` refreshes on demand; ``--clear`` removes
updated copies, returning to the packaged data.
"""
import argparse
import os
import shutil
import sqlite3
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone

import requests

from ..build.refresh import refresh
from .db import (
    COMMIT_MARKER,
    GHCNH_DB_PATH,
    PACKAGED_GHCNH_DB_PATH,
    PACKAGED_IDENTIFIERS_DB_PATH,
    UPDATED_DATA_DIR,
    data_path,
    packaged_geography_packs,
)



UPDATABLE = {
    "ghcnh.db": PACKAGED_GHCNH_DB_PATH,
    "identifiers.db": PACKAGED_IDENTIFIERS_DB_PATH,
}

# geography is not static: Census republishes the Gazetteer annually
GEOGRAPHY_FILENAMES = tuple(
    os.path.basename(path) for _alias, path in packaged_geography_packs()
)
UPDATABLE.update(
    {os.path.basename(path): path for _alias, path in packaged_geography_packs()}
)

# omitted from a published pack when unchanged; refresh the rest, do not abort
OPTIONAL_IN_PACK = frozenset(GEOGRAPHY_FILENAMES)

# source dbs whose meta(refreshed_at) stamp drives staleness; a db not
# listed here (e.g. identifiers.db, which carries no meta table) never
# forces the registry stale
AUTO_UPDATING_SOURCES = {
    "ghcnh.db": GHCNH_DB_PATH,
}

RELEASE_URL = (
    "https://github.com/opendsm/eeweather/releases/download/registry-latest/{}"
)

DOWNLOAD_TIMEOUT_SECONDS = 300

# a downloaded pack must be at least this fraction as populated as the
# data it replaces
PLAUSIBILITY_FLOOR = 0.9

_FLOOR_TABLES = {
    "ghcnh.db": ("stations", "inventory"),
    "identifiers.db": ("station_identifier",),
}
_FLOOR_TABLES.update({filename: ("place",) for filename in GEOGRAPHY_FILENAMES})

STALE_AFTER_DAYS = 183

RETRY_AFTER_DAYS = 1

# the update thread waits before touching the network, so short-lived
# processes (pipeline workers) exit before generating any traffic
UPDATE_DELAY_SECONDS = 60

_ATTEMPT_STAMP = "last_attempt"

_process_checked = False


def refreshed_at(path=GHCNH_DB_PATH):
    """When the data at ``path`` was last refreshed, or None if unstamped."""
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "select value from meta where key = 'refreshed_at'"
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if row is None:
        return None

    return datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _stale(now):
    for path in AUTO_UPDATING_SOURCES.values():
        stamp = refreshed_at(path)
        if stamp is None or now - stamp > timedelta(days=STALE_AFTER_DAYS):
            return True

    return False


def _claim_attempt(now):
    """Atomically claim the machine-wide right to attempt an update.

    The claim file doubles as the attempt record: exclusive creation
    means exactly one process wins per retry window, however many
    workers race for it.
    """
    path = os.path.join(UPDATED_DATA_DIR, _ATTEMPT_STAMP)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            attempted = datetime.fromtimestamp(
                os.path.getmtime(path), tz=timezone.utc
            )
        except OSError:
            return False
        if now - attempted < timedelta(days=RETRY_AFTER_DAYS):
            return False
        try:
            os.remove(path)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    os.close(fd)

    return True


def maybe_update():
    """Start a background update when the live data is stale.

    Checks at most once per process; across processes on a machine, an
    atomic claim file limits attempts to one per ``RETRY_AFTER_DAYS``
    however many workers race for it, and the update thread waits
    ``UPDATE_DELAY_SECONDS`` before touching the network, so short-lived
    processes exit without generating traffic. Updates prefer the
    CDN-served published pack, so even uncoordinated fleets of ephemeral
    machines cost NOAA nothing; ``EEWEATHER_AUTO_UPDATE=0`` suppresses
    the traffic entirely. The running process keeps the data it
    imported; the updated copies serve subsequent processes. Returns the
    update thread, or None when no update starts.
    """
    global _process_checked
    if _process_checked:
        return None
    _process_checked = True
    if os.environ.get("EEWEATHER_AUTO_UPDATE", "1").lower() in ("0", "false"):
        return None
    now = datetime.now(timezone.utc)
    if not _stale(now):
        return None

    os.makedirs(UPDATED_DATA_DIR, exist_ok=True)
    if not _claim_attempt(now):
        return None
    thread = threading.Thread(target=_update_or_warn, daemon=True)
    thread.start()

    return thread


def _update_or_warn():
    try:
        time.sleep(UPDATE_DELAY_SECONDS)
        update()
    except Exception as error:
        warnings.warn(
            "eeweather registry auto-update failed; using existing data:"
            " {}".format(error)
        )


def _download(url, dest):
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, stream=True)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=1 << 20):
            f.write(chunk)


def _plausible_pack_or_raise(staged):
    """Abort when a downloaded file is implausibly small next to the data
    it would replace."""
    for filename, stage in staged.items():
        live = data_path(UPDATABLE[filename])
        stage_conn = sqlite3.connect(stage)
        live_conn = sqlite3.connect(live)
        try:
            for table in _FLOOR_TABLES[filename]:
                query = "select count(*) from {}".format(table)
                staged_count = stage_conn.execute(query).fetchone()[0]
                live_count = live_conn.execute(query).fetchone()[0]
                if staged_count < PLAUSIBILITY_FLOOR * live_count:
                    raise RuntimeError(
                        "Implausible published {}: {} has {} rows, live data"
                        " has {}.".format(filename, table, staged_count, live_count)
                    )
        finally:
            stage_conn.close()
            live_conn.close()


def _write_marker():
    """Certify that a complete updated pair is installed. Written via an
    atomic rename so the marker only ever appears whole; data_path serves
    the updated pair only when it is present, so a torn swap is ignored.
    Only the marker's presence is consulted; its contents are unused."""
    marker = os.path.join(UPDATED_DATA_DIR, COMMIT_MARKER)
    stage = marker + ".staging"
    with open(stage, "w"):
        pass
    os.replace(stage, marker)


def _clear_marker():
    """Retract certification before a swap begins, so an interrupted swap
    (first update or any re-update) is never certified and reads fall back
    to the packaged pair until _write_marker completes."""
    marker = os.path.join(UPDATED_DATA_DIR, COMMIT_MARKER)
    if os.path.exists(marker):
        os.remove(marker)


def _install_published(now):
    """Install the published registry pack; returns its stamp, or None
    when the channel is unreachable, implausible, stale, or no newer
    than the live data (the NOAA rebuild is the fallback). A failed
    replace leaves no marker, so reads fall back to the packaged pair."""
    staged = {}
    try:
        for filename in UPDATABLE:
            stage = os.path.join(UPDATED_DATA_DIR, filename + ".download")
            try:
                _download(RELEASE_URL.format(filename), stage)
            except requests.HTTPError:
                # optional file absent: keep the existing copy, refresh the rest
                if filename not in OPTIONAL_IN_PACK:
                    raise
                if os.path.exists(stage):
                    os.remove(stage)
                continue
            staged[filename] = stage
        published = refreshed_at(staged["ghcnh.db"])
        if published is None or now - published > timedelta(days=STALE_AFTER_DAYS):
            return None
        current = refreshed_at()
        if current is not None and published <= current:
            return None
        _plausible_pack_or_raise(staged)
        _clear_marker()
        for filename, stage in staged.items():
            os.replace(stage, os.path.join(UPDATED_DATA_DIR, filename))
            staged[filename] = None
        _write_marker()
    except (requests.RequestException, sqlite3.Error, RuntimeError, OSError):
        return None
    finally:
        for stage in staged.values():
            if stage is not None and os.path.exists(stage):
                os.remove(stage)

    return published


def _rebuild():
    """Refresh staged copies of the live data from NOAA and swap them in."""
    staged = {}
    for filename, packaged in UPDATABLE.items():
        dest = os.path.join(UPDATED_DATA_DIR, filename)
        stage = dest + ".staging"
        if os.path.exists(dest):
            shutil.copy(dest, stage)
        else:
            shutil.copy(packaged, stage)
        staged[filename] = stage

    try:
        counts = refresh(
            ghcnh_path=staged["ghcnh.db"],
            identifiers_path=staged["identifiers.db"],
        )
        try:
            _clear_marker()
            for filename, stage in staged.items():
                os.replace(stage, os.path.join(UPDATED_DATA_DIR, filename))
            _write_marker()
        except OSError:
            return None
    finally:
        for stage in staged.values():
            if os.path.exists(stage):
                os.remove(stage)

    return counts


def update():
    """Update the registry data on this machine; returns a summary.

    Prefers the published rolling-release pack (CDN-served, no local
    rebuild); falls back to rebuilding from the live NOAA files when the
    channel is unreachable, implausible, stale, or no newer than the
    live data. Takes effect in new processes.

    Readers never observe a torn pair: the commit marker is retracted
    before the swap and rewritten only after both files are in place, so
    an interrupted swap falls back to the packaged pair. Concurrent
    updaters are not serialized across processes — the background path is
    gated once per process and per machine, and a manual update racing it
    is the unguarded case; readers stay consistent regardless.
    """
    os.makedirs(UPDATED_DATA_DIR, exist_ok=True)
    published = _install_published(datetime.now(timezone.utc))
    if published is not None:
        summary = {
            "channel": "published",
            "refreshed_at": published.strftime("%Y-%m-%d"),
        }

        return summary

    counts = _rebuild()

    return counts


def clear():
    """Remove updated registry data, returning to the packaged copies."""
    removed = []
    # retract the marker first so a partial clear is never certified
    for filename in [COMMIT_MARKER] + list(UPDATABLE) + [_ATTEMPT_STAMP]:
        path = os.path.join(UPDATED_DATA_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)

    return removed


def main():
    parser = argparse.ArgumentParser(prog="python -m eeweather.registry.update")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove updated registry data, returning to packaged copies",
    )
    args = parser.parse_args()

    if args.clear:
        print({"removed": clear()})
    else:
        print(update())


if __name__ == "__main__":
    main()
