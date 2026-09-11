import sqlite3

import pytest

from eeweather.build.schema import GEOGRAPHY_SCHEMA
from eeweather.exceptions import UnrecognizedPlaceError
from eeweather.registry.db import metadata_db_connection_proxy
from eeweather.registry.summaries import get_place, get_station_ids, get_zcta_ids


def _two_vintage_pack(tmp_path, monkeypatch, rows, zone_rows=()):
    """Attach a synthetic geography pack and point the proxy at it."""
    path = tmp_path / "geo.db"
    build = sqlite3.connect(path)
    for statement in GEOGRAPHY_SCHEMA:
        build.execute(statement)
    build.executemany(
        "insert into place values (?, 'zcta', ?, 'US', ?, ?, ?)", rows
    )
    build.executemany("insert into place_zone values (?, 'zcta', ?, ?, ?)", zone_rows)
    build.commit()
    build.close()

    conn = sqlite3.connect(":memory:")
    conn.execute("attach database ? as geo", (str(path),))
    monkeypatch.setattr(metadata_db_connection_proxy, "get_connection", lambda: conn)
    monkeypatch.setattr(metadata_db_connection_proxy, "geography_aliases", ["geo"])


def test_get_place():
    place = get_place("zcta", "90006")

    assert place["kind"] == "zcta"
    assert place["code"] == "90006"
    assert place["country"] == "US"
    assert place["subdivision"] == "CA"
    assert place["latitude"] == pytest.approx(34.048, abs=0.001)
    assert place["longitude"] == pytest.approx(-118.294, abs=0.001)
    assert place["zones"] == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
    }


def test_get_place_unrecognized():
    with pytest.raises(UnrecognizedPlaceError) as excinfo:
        get_place("zcta", "00000")
    assert excinfo.value.kind == "zcta"
    assert excinfo.value.code == "00000"


def test_get_station_ids():
    station_ids = get_station_ids()

    assert len(station_ids) == 5891
    assert station_ids[0] == "AQA00749401"


def test_get_station_ids_by_subdivision():
    station_ids = get_station_ids("IL")

    assert len(station_ids) == 69
    assert station_ids[0] == "USA00724394"


def test_get_zcta_ids():
    zcta_ids = get_zcta_ids()

    assert len(zcta_ids) == 33144


def test_get_zcta_ids_by_subdivision():
    zcta_ids = get_zcta_ids("CA")

    assert len(zcta_ids) == 1763
    assert zcta_ids[0] == "90001"


def test_get_place_resolves_the_newest_vintage(tmp_path, monkeypatch):
    # the same code in two vintages: the newer centroid, subdivision and
    # zones win, and the zones are read at that vintage rather than mixed
    _two_vintage_pack(
        tmp_path,
        monkeypatch,
        rows=[
            (2010, "12345", "NY", 1.0, 1.0),
            (2025, "12345", "NJ", 2.0, 2.0),
        ],
        zone_rows=[
            (2010, "12345", "iecc_climate_zone", "OLD"),
            (2025, "12345", "iecc_climate_zone", "NEW"),
        ],
    )

    place = get_place("zcta", "12345")

    assert place["vintage"] == 2025
    assert place["subdivision"] == "NJ"
    assert place["latitude"] == 2.0
    assert place["zones"] == {"iecc_climate_zone": "NEW"}


def test_get_zcta_ids_lists_only_the_newest_vintage(tmp_path, monkeypatch):
    # a code retired after 2010 is not part of the current set
    _two_vintage_pack(
        tmp_path,
        monkeypatch,
        rows=[
            (2010, "00001", "NY", 1.0, 1.0),
            (2010, "09999", "NY", 1.0, 1.0),
            (2025, "00001", "NY", 1.0, 1.0),
            (2025, "00002", "NY", 1.0, 1.0),
        ],
    )

    assert get_zcta_ids() == ["00001", "00002"]

