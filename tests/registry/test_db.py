import sqlite3

import pytest

from eeweather.exceptions import UnrecognizedPlaceError, UnrecognizedStationError
from eeweather.registry.db import (
    metadata_db_connection_proxy,
    valid_place_or_raise,
    valid_station_id_or_raise,
)


def test_valid_station_id_or_raise():
    assert valid_station_id_or_raise("USW00023152") is True

    with pytest.raises(UnrecognizedStationError) as excinfo:
        valid_station_id_or_raise("INVALID")
    assert excinfo.value.value == "INVALID"


def test_valid_place_or_raise():
    assert valid_place_or_raise("zcta", "90210") is True

    with pytest.raises(UnrecognizedPlaceError) as excinfo:
        valid_place_or_raise("zcta", "INVALID")
    assert excinfo.value.code == "INVALID"


# attachment machinery and multi-catalog behavior


def test_register_attachment_ignores_duplicate_aliases():
    proxy = metadata_db_connection_proxy
    before = list(proxy._attachments)

    proxy.register_attachment("ghcnh", "/nonexistent/other.db", catalog=True)

    assert proxy._attachments == before


def test_attachment_role_properties():
    proxy = metadata_db_connection_proxy

    assert proxy.catalogs == ["ghcnh"]
    assert proxy.inventory_sources == ["ghcnh"]
    assert proxy.quality_sources == ["ghcnh"]
    assert set(proxy.availability_sources) == {"tmy3", "cz2010"}
    assert proxy.geography_aliases == ["geography_us"]


@pytest.fixture
def second_catalog(tmp_path):
    """A synthetic catalog registered after ghcnh: one station overlapping
    the packaged catalog (with conflicting facts) and one of its own."""
    from eeweather.registry.db import Attachment
    from eeweather.sources.matching import cached_data

    path = str(tmp_path / "fakecat.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "create table stations ("
        " station_id text primary key, name text, latitude real,"
        " longitude real, elevation real, country text, subdivision text"
        ") without rowid"
    )
    conn.execute(
        "create table station_zone ("
        " station_id text not null, system text not null,"
        " zone_id text not null, primary key (station_id, system)"
        ") without rowid"
    )
    conn.execute(
        "insert into stations values"
        " ('USW00023152', 'CONFLICTING NAME', 1.0, 2.0, 3.0, 'US', 'CA')"
    )
    conn.execute(
        "insert into stations values"
        " ('ZZFAKE00001', 'FAKE ONLY', 10.0, 20.0, 30.0, 'ZZ', null)"
    )
    conn.commit()
    conn.close()

    proxy = metadata_db_connection_proxy
    saved = list(proxy._attachments)
    proxy._attachments.append(
        Attachment("fakecat", path, True, False, False, False)
    )
    proxy.close()
    cached_data.__dict__.pop("all_station_metadata", None)

    yield

    proxy._attachments[:] = saved
    proxy.close()
    cached_data.__dict__.pop("all_station_metadata", None)


def test_multi_catalog_first_catalog_wins_for_facts(second_catalog):
    from eeweather.registry.metadata import get_station_metadata

    metadata = get_station_metadata("USW00023152")

    assert metadata["name"] == "BURBANK-GLENDALE-PASA ARPT"
    assert metadata["latitude"] == pytest.approx(34.2)


def test_multi_catalog_search_first_catalog_wins(second_catalog):
    from eeweather.registry.summaries import search_stations

    df = search_stations()

    assert df.loc["USW00023152", "name"] == "BURBANK-GLENDALE-PASA ARPT"
    assert df.loc["ZZFAKE00001", "name"] == "FAKE ONLY"
    assert len(df) == 5892


def test_multi_catalog_enumeration_is_a_union(second_catalog):
    from eeweather.registry.summaries import get_station_ids

    station_ids = get_station_ids()

    assert len(station_ids) == 5892
    assert "ZZFAKE00001" in station_ids


def test_multi_catalog_ranking_keeps_first_catalog_coordinates(second_catalog):
    from eeweather.sources.matching import cached_data

    df = cached_data.all_station_metadata

    assert df.loc["USW00023152", "latitude"] == pytest.approx(34.2)
    assert "ZZFAKE00001" in df.index
