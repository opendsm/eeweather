"""The geography rebuild, exercised against synthetic Census payloads.

The suite is offline, so the two Census downloads are built in-process: a
Gazetteer text archive (the ZCTA internal points) and a ZCTA-to-county
relationship file (each ZCTA's state), both in the real formats.
"""
import io
import json
import sqlite3
import zipfile

import pytest
from shapely.geometry import Polygon, mapping

from eeweather.build import geography
from eeweather.build.geography import (
    _assign,
    build_places,
    fetch_zcta_points,
    fetch_zcta_states,
    resolve_vintage,
)
from eeweather.build.schema import GEOGRAPHY_SCHEMA


YEAR = 2025

# a zone geometry the pack owns; the two points inside it get assigned
LEFT = Polygon([(-2, 0), (-1, 0), (-1, 1), (-2, 1)])

# the real relationship-file header; the parser finds its columns by name
REL_HEADER = (
    "OID_ZCTA5_20|GEOID_ZCTA5_20|NAMELSAD_ZCTA5_20|AREALAND_ZCTA5_20|"
    "AREAWATER_ZCTA5_20|MTFCC_ZCTA5_20|CLASSFP_ZCTA5_20|FUNCSTAT_ZCTA5_20|"
    "OID_COUNTY_20|GEOID_COUNTY_20|NAMELSAD_COUNTY_20|AREALAND_COUNTY_20|"
    "AREAWATER_COUNTY_20|MTFCC_COUNTY_20|CLASSFP_COUNTY_20|FUNCSTAT_COUNTY_20|"
    "AREALAND_PART|AREAWATER_PART"
)
_ZCTA_COL = 1
_COUNTY_COL = 9
_AREA_COL = 16


def _gazetteer_zip(rows):
    text = "GEOID|GEOIDFQ|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
    for code, latitude, longitude in rows:
        text += "{}|860Z200US{}|1|0|1|0|{}|{}\n".format(
            code, code, latitude, longitude
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("{}_Gaz_zcta_national.txt".format(YEAR), text)

    return buffer.getvalue()


def _rel_row(zcta, county, area_part):
    cols = [""] * 18
    cols[_ZCTA_COL] = zcta
    cols[_COUNTY_COL] = county
    cols[_AREA_COL] = str(area_part)
    return "|".join(cols)


def _relationship_file(rows):
    lines = [REL_HEADER] + [_rel_row(*row) for row in rows]
    # served with the BOM Census writes, as bytes like the real download
    return ("﻿" + "\n".join(lines)).encode("utf-8")


# county FIPS -> the state the parser resolves it to
CA, NY, NV = "06037", "36061", "32003"


@pytest.fixture
def census(monkeypatch):
    """Both Census downloads served from memory."""
    payloads = {
        geography.GAZETTEER_URL.format(year=YEAR): _gazetteer_zip([
            ("00001", 0.5, -1.5),   # inside LEFT
            ("00002", 0.5, -0.5),   # outside LEFT
            ("00003", 0.5, -2.02),  # outside LEFT
        ]),
        geography.RELATIONSHIP_URL: _relationship_file([
            ("00001", CA, 100),
            ("00002", NY, 100),
            # 00003 spans two counties; the one holding more land wins
            ("00003", CA, 1),
            ("00003", NV, 9),
            # a county row with no ZCTA part, which the parser skips
            ("", "01003", 500),
        ]),
    }

    def fake_get(url):
        assert url in payloads, "tests must not hit the network: {}".format(url)

        return payloads[url]

    monkeypatch.setattr(geography, "_get", fake_get)
    monkeypatch.setattr(geography, "_available", lambda url: url in payloads)

    return payloads


@pytest.fixture
def geography_db(tmp_path):
    """A pack holding one zone system and an earlier geography vintage."""
    path = tmp_path / "geography_test.db"
    conn = sqlite3.connect(path)
    for statement in GEOGRAPHY_SCHEMA:
        conn.execute(statement)
    conn.execute(
        "insert into zone values ('test_zone', 'Z1', 'Zone One', ?)",
        (json.dumps(mapping(LEFT)),),
    )
    # an earlier vintage the rebuild must keep: one code it will also carry
    # forward (00001) and one it has since retired (09999)
    conn.executemany(
        "insert into place values (2010, 'zcta', ?, 'US', 'ZZ', ?, ?)",
        [("00001", 9.0, 9.0), ("09999", 9.0, 9.0)],
    )
    conn.commit()
    conn.close()

    return path


def test_fetch_zcta_points_reads_the_internal_point(census):
    points = fetch_zcta_points(YEAR)

    assert points["00001"] == (0.5, -1.5)
    assert len(points) == 3


def test_fetch_zcta_states_resolves_state_from_county_fips(census):
    states = fetch_zcta_states(YEAR)

    assert states["00001"] == "CA"
    assert states["00002"] == "NY"


def test_fetch_zcta_states_takes_the_county_with_the_most_land(census):
    # 00003 is mostly in the Nevada county, so it resolves to NV
    assert fetch_zcta_states(YEAR)["00003"] == "NV"


def test_fetch_zcta_states_skips_rows_with_no_zcta(census):
    # the county-only row carries no ZCTA code and must not appear
    assert "" not in fetch_zcta_states(YEAR)
    assert len(fetch_zcta_states(YEAR)) == 3


def test_resolve_vintage_prefers_the_newest_published_year(census, monkeypatch):
    monkeypatch.setattr(geography, "VINTAGE_LOOKBACK_YEARS", 50)

    assert resolve_vintage() == YEAR


def test_resolve_vintage_honors_an_explicit_year():
    assert resolve_vintage(2019) == 2019


def test_assign_places_a_point_inside_a_polygon():
    assigned = _assign({"a": (0.5, -1.5)}, [("Z1", LEFT)])

    assert assigned == {"a": "Z1"}


def test_assign_leaves_a_far_point_unplaced():
    assigned = _assign({"a": (50.0, 50.0)}, [("Z1", LEFT)])

    assert assigned == {}


def test_assign_falls_back_to_the_nearest_within_tolerance():
    """A point just outside a geometry can be pulled in with a tolerance."""
    just_outside = {"a": (0.5, -2.02)}

    assert _assign(just_outside, [("Z1", LEFT)]) == {}
    assert _assign(just_outside, [("Z1", LEFT)], tolerance=0.05) == {"a": "Z1"}


def test_build_places_adds_the_vintage_and_stamps_it(census, geography_db):
    counts = build_places(year=YEAR, geography_path=str(geography_db))

    assert counts["place"] == 3
    assert counts["without_subdivision"] == 0
    assert counts["vintage"] == YEAR

    conn = sqlite3.connect(geography_db)
    places = dict(
        conn.execute(
            "select code, subdivision from place where kind = 'zcta'"
            " and vintage = ?",
            (YEAR,),
        )
    )
    assert places == {"00001": "CA", "00002": "NY", "00003": "NV"}

    meta = dict(conn.execute("select key, value from meta"))
    assert meta["place_vintage"] == str(YEAR)
    assert meta["place_source"] == "census-gazetteer"


def test_build_places_retains_the_earlier_vintage(census, geography_db):
    build_places(year=YEAR, geography_path=str(geography_db))

    conn = sqlite3.connect(geography_db)
    vintages = {
        row[0] for row in conn.execute(
            "select distinct vintage from place where kind = 'zcta'"
        )
    }
    assert vintages == {2010, YEAR}

    # a code retired after 2010 is still resolvable at its own vintage
    retired = conn.execute(
        "select subdivision from place where kind = 'zcta' and code = '09999'"
    ).fetchall()
    assert retired == [("ZZ",)]

    # a code in both vintages keeps a row in each
    kept = conn.execute(
        "select vintage from place where kind = 'zcta' and code = '00001'"
        " order by vintage"
    ).fetchall()
    assert kept == [(2010,), (YEAR,)]


def test_build_places_is_idempotent_for_a_year(census, geography_db):
    build_places(year=YEAR, geography_path=str(geography_db))
    counts = build_places(year=YEAR, geography_path=str(geography_db))

    assert counts["place"] == 3
    conn = sqlite3.connect(geography_db)
    # rebuilding the same year does not duplicate its rows
    assert conn.execute(
        "select count(*) from place where kind = 'zcta' and vintage = ?",
        (YEAR,),
    ).fetchone()[0] == 3


def test_build_places_recomputes_zone_assignments(census, geography_db):
    build_places(year=YEAR, geography_path=str(geography_db))

    conn = sqlite3.connect(geography_db)
    zones = dict(
        conn.execute(
            "select code, zone_id from place_zone"
            " where system = 'test_zone' and vintage = ?",
            (YEAR,),
        )
    )
    # only the point inside the zone geometry is assigned
    assert zones == {"00001": "Z1"}


def test_build_places_leaves_zone_geometries_alone(census, geography_db):
    before = sqlite3.connect(geography_db).execute(
        "select count(*) from zone"
    ).fetchone()[0]

    build_places(year=YEAR, geography_path=str(geography_db))

    after = sqlite3.connect(geography_db).execute(
        "select count(*) from zone"
    ).fetchone()[0]
    assert before == after == 1


def test_build_places_refuses_a_partial_download(census, geography_db, monkeypatch):
    """A short Gazetteer is a bad download, not a real change."""
    conn = sqlite3.connect(geography_db)
    conn.executemany(
        "insert into place values (?, 'zcta', ?, 'US', 'CA', 0.5, -1.5)",
        [(YEAR, "1{:04d}".format(i)) for i in range(100)],
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="partial download"):
        build_places(year=YEAR, geography_path=str(geography_db))


def test_build_places_refuses_when_states_do_not_resolve(census, geography_db, monkeypatch):
    """If the join yields no state for most ZCTAs, the schema is wrong."""
    monkeypatch.setattr(geography, "fetch_zcta_states", lambda year: {})

    with pytest.raises(RuntimeError, match="no state"):
        build_places(year=YEAR, geography_path=str(geography_db))
