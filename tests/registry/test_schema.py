"""Integrity pins for the packaged data files."""
import pytest

from eeweather.registry.db import IDENTIFIERS_DB_PATH, metadata_db_connection_proxy



EXPECTED_TABLES = {
    "identifiers": {
        "station_identifier": ["namespace", "external_id", "station_id", "recent"],
    },
    "geography_us": {
        "place": ["kind", "code", "country", "subdivision", "latitude", "longitude"],
        "place_zone": ["kind", "code", "system", "zone_id"],
        "zone": ["system", "zone_id", "name", "geometry"],
    },
    "ghcnh": {
        "stations": [
            "station_id", "name", "latitude", "longitude", "elevation",
            "country", "subdivision",
        ],
        "station_zone": ["station_id", "system", "zone_id"],
        "meta": ["key", "value"],
        "inventory": [
            "station_id", "year",
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ],
        "quality": ["station_id", "quality"],
    },
    "tmy3": {
        "stations": ["station_id", "usaf_id", "class"],
    },
    "cz2010": {
        "stations": ["station_id", "usaf_id"],
    },
}


@pytest.fixture(scope="module")
def conn():
    # the shared proxy connection, with every packaged file attached
    return metadata_db_connection_proxy.get_connection()


def test_identifiers_db_is_the_connection_base():
    assert metadata_db_connection_proxy.db_path == IDENTIFIERS_DB_PATH


def test_packaged_files_match_expected_schemas(conn):
    for alias, tables in EXPECTED_TABLES.items():
        if alias == "identifiers":
            master = "sqlite_master"
            prefix = ""
        else:
            master = "{}.sqlite_master".format(alias)
            prefix = "{}.".format(alias)
        found = {
            row[0] for row in conn.execute(
                "select name from {} where type = 'table'".format(master)
            )
        }
        assert found == set(tables), "tables of {}".format(alias)

        for table, expected_columns in tables.items():
            columns = [row[1] for row in conn.execute(
                "pragma {}table_info({})".format(prefix, table)
            )]
            assert columns == expected_columns, "columns of {}.{}".format(
                alias, table
            )


def test_row_counts(conn):
    counts = {}
    for alias, tables in EXPECTED_TABLES.items():
        for table in tables:
            if alias == "identifiers":
                qualified = table
            else:
                qualified = "{}.{}".format(alias, table)
            counts["{}.{}".format(alias, table)] = conn.execute(
                "select count(*) from {}".format(qualified)
            ).fetchone()[0]

    # static tables pin exactly; refresh-mutable tables pin floors so a
    # legitimate refresh PR stays green
    assert counts["identifiers.station_identifier"] >= 14456
    assert counts["geography_us.zone"] == 35
    assert counts["geography_us.place"] == 33144
    assert counts["ghcnh.stations"] >= 3990
    assert counts["ghcnh.quality"] == counts["ghcnh.stations"]
    assert counts["ghcnh.inventory"] >= 154825
    assert counts["ghcnh.station_zone"] > 0
    assert counts["geography_us.place_zone"] > 0
    assert counts["tmy3.stations"] == 1015
    assert counts["cz2010.stations"] == 86


def test_identifier_namespaces(conn):
    namespaces = {
        row[0] for row in conn.execute(
            "select distinct namespace from station_identifier"
        )
    }

    assert namespaces == {"ghcn", "usaf", "wban", "icao", "wmo"}


def test_no_wban_sentinel_identifier_rows(conn):
    sentinel_rows = conn.execute(
        "select count(*) from station_identifier"
        " where namespace = 'wban' and external_id = '99999'"
    ).fetchone()[0]

    assert sentinel_rows == 0


def test_every_station_has_a_ghcn_identity_row(conn):
    orphans = conn.execute(
        """
        select count(*) from ghcnh.stations as s
        where not exists (
          select 1 from station_identifier as i
          where i.station_id = s.station_id and i.namespace = 'ghcn'
        )
        """
    ).fetchone()[0]

    assert orphans == 0


def test_every_identity_appears_in_a_catalog(conn):
    # the invariant that matters when non-catalog sources contribute
    # stations: every minted id must have facts somewhere
    homeless = conn.execute(
        """
        select count(distinct station_id) from station_identifier as i
        where not exists (
          select 1 from ghcnh.stations as s
          where s.station_id = i.station_id
        )
        """
    ).fetchone()[0]

    assert homeless == 0


def test_every_cataloged_station_has_a_country(conn):
    missing = conn.execute(
        "select count(*) from ghcnh.stations where country is null"
    ).fetchone()[0]

    assert missing == 0


def test_quality_values(conn):
    qualities = {
        row[0] for row in conn.execute("select distinct quality from ghcnh.quality")
    }

    assert qualities == {"high", "medium", "low"}


def test_archive_stations_reference_cataloged_stations(conn):
    for alias in ("tmy3", "cz2010"):
        dangling = conn.execute(
            """
            select count(*) from {}.stations as a
            where not exists (
              select 1 from ghcnh.stations as s
              where s.station_id = a.station_id
            )
            """.format(alias)
        ).fetchone()[0]

        assert dangling == 0, alias


def test_no_identifier_has_multiple_recent_holders(conn):
    # an id with two recent holders makes resolve_station raise; the
    # refresh must never mint one
    offenders = conn.execute(
        """
        select namespace, external_id, count(*) from station_identifier
        where recent = 1
        group by namespace, external_id
        having count(*) > 1
        """
    ).fetchall()

    assert offenders == []
