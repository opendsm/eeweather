import pytest

from eeweather.exceptions import AmbiguousIdentifierError, UnrecognizedStationError
from eeweather.registry.identifiers import resolve_station, translate


def test_translate_usaf_to_ghcn():
    mapping = translate(["722880", "722874"], "usaf", "ghcn")

    assert mapping == {
        "722880": ("USW00023152",),
        "722874": ("USW00093134",),
    }


def test_translate_values_are_tuples_for_one_to_many():
    # this Australian station carries four historical USAF ids
    mapping = translate(["ASA00956720"], "ghcn", "usaf")

    assert len(mapping["ASA00956720"]) == 4


def test_translate_unrecognized_ids_are_absent():
    mapping = translate(["722880", "NOT_AN_ID"], "usaf", "ghcn")

    assert "NOT_AN_ID" not in mapping
    assert mapping["722880"] == ("USW00023152",)


def test_translate_deduplicates_input_ids():
    mapping = translate(["722880", "722880"], "usaf", "ghcn")

    assert mapping == {"722880": ("USW00023152",)}


def test_resolve_station_unique():
    assert resolve_station("usaf", "722880") == "USW00023152"
    assert resolve_station("icao", "KBUR") == "USW00023152"


def test_resolve_station_ambiguous_recent_wins():
    # wban 03935 was reused; only USW00003935 holds it recently
    assert resolve_station("wban", "03935") == "USW00003935"


@pytest.fixture
def identifiers_db_with_unresolvable_wban(tmp_path, monkeypatch):
    """A copy of the packaged crosswalk plus a synthetic wban mapping to
    two stations with no recent marker (no such case survives in the
    packaged data after the alias audit)."""
    import shutil
    import sqlite3

    from eeweather.registry.db import IDENTIFIERS_DB_PATH, metadata_db_connection_proxy

    path = str(tmp_path / "identifiers.db")
    shutil.copy(IDENTIFIERS_DB_PATH, path)
    conn = sqlite3.connect(path)
    conn.execute(
        "insert into station_identifier values ('wban', '90001', 'USW00023152', 0)"
    )
    conn.execute(
        "insert into station_identifier values ('wban', '90001', 'USW00093134', 0)"
    )
    conn.commit()
    conn.close()

    proxy = metadata_db_connection_proxy
    monkeypatch.setattr(proxy, "db_path", path)
    proxy.close()

    yield

    proxy.close()


def test_resolve_station_ambiguous_without_recent_raises(
    identifiers_db_with_unresolvable_wban,
):
    with pytest.raises(AmbiguousIdentifierError) as excinfo:
        resolve_station("wban", "90001")
    assert excinfo.value.station_ids == ("USW00023152", "USW00093134")


def test_resolve_station_unrecognized():
    with pytest.raises(UnrecognizedStationError):
        resolve_station("usaf", "000000")

