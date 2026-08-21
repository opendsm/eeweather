"""The geography rebuild, exercised against synthetic Census payloads.

The suite is offline, so the two Census downloads are built in-process:
a Gazetteer text archive and a state shapefile archive, both in the real
formats.
"""
import io
import json
import sqlite3
import zipfile

import pytest
from shapely.geometry import Polygon, mapping

from eeweather.build import geography
from eeweather.build.geography import (
    NEAREST_TOLERANCE_DEGREES,
    _assign,
    build_places,
    fetch_state_geometries,
    fetch_zcta_points,
    resolve_vintage,
)
from eeweather.build.schema import GEOGRAPHY_SCHEMA


YEAR = 2025

# two unit squares side by side, standing in for adjacent states
LEFT = Polygon([(-2, 0), (-1, 0), (-1, 1), (-2, 1)])
RIGHT = Polygon([(-1, 0), (0, 0), (0, 1), (-1, 1)])


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


def _states_zip(states):
    shapefile = pytest.importorskip("shapefile")

    writer_buffers = {ext: io.BytesIO() for ext in ("shp", "shx", "dbf")}
    writer = shapefile.Writer(
        shp=writer_buffers["shp"],
        shx=writer_buffers["shx"],
        dbf=writer_buffers["dbf"],
    )
    writer.field("STATEFP", "C", 2)
    writer.field("STUSPS", "C", 2)
    writer.field("NAME", "C", 40)
    for index, (abbreviation, polygon) in enumerate(states):
        writer.poly([list(polygon.exterior.coords)])
        writer.record("{:02d}".format(index + 1), abbreviation, abbreviation)
    writer.close()

    base = "cb_{}_us_state_500k".format(YEAR)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for ext, data in writer_buffers.items():
            archive.writestr("{}.{}".format(base, ext), data.getvalue())

    return buffer.getvalue()


@pytest.fixture
def census(monkeypatch):
    """Both Census downloads served from memory."""
    payloads = {
        geography.GAZETTEER_URL.format(year=YEAR): _gazetteer_zip([
            ("00001", 0.5, -1.5),   # inside LEFT
            ("00002", 0.5, -0.5),   # inside RIGHT
            ("00003", 0.5, -2.02),  # just outside LEFT, within tolerance
        ]),
        geography.STATE_URL.format(year=YEAR): _states_zip(
            [("AA", LEFT), ("BB", RIGHT)]
        ),
    }

    def fake_get(url):
        assert url in payloads, "tests must not hit the network: {}".format(url)

        return payloads[url]

    monkeypatch.setattr(geography, "_get", fake_get)
    monkeypatch.setattr(geography, "_available", lambda url: url in payloads)

    return payloads


@pytest.fixture
def geography_db(tmp_path):
    """A geography pack holding one zone system and stale places."""
    path = tmp_path / "geography_test.db"
    conn = sqlite3.connect(path)
    for statement in GEOGRAPHY_SCHEMA:
        conn.execute(statement)
    conn.execute(
        "insert into zone values ('test_zone', 'Z1', 'Zone One', ?)",
        (json.dumps(mapping(LEFT)),),
    )
    # a stale place that the rebuild must remove, and one it must keep
    conn.execute("insert into place values ('zcta', '09999', 'US', 'ZZ', 9.0, 9.0)")
    conn.execute(
        "insert into place_zone values ('zcta', '09999', 'test_zone', 'Z1')"
    )
    conn.commit()
    conn.close()

    return path


def test_fetch_zcta_points_reads_the_internal_point(census):
    points = fetch_zcta_points(YEAR)

    assert points["00001"] == (0.5, -1.5)
    assert len(points) == 3


def test_fetch_state_geometries_reads_the_abbreviation(census):
    states = fetch_state_geometries(YEAR)

    assert sorted(abbreviation for abbreviation, _ in states) == ["AA", "BB"]


def test_resolve_vintage_prefers_the_newest_published_year(census, monkeypatch):
    monkeypatch.setattr(geography, "VINTAGE_LOOKBACK_YEARS", 50)

    assert resolve_vintage() == YEAR


def test_resolve_vintage_honors_an_explicit_year():
    assert resolve_vintage(2019) == 2019


def test_assign_places_a_point_inside_a_polygon():
    assigned = _assign({"a": (0.5, -1.5)}, [("AA", LEFT), ("BB", RIGHT)])

    assert assigned == {"a": "AA"}


def test_assign_leaves_a_far_point_unplaced():
    assigned = _assign({"a": (50.0, 50.0)}, [("AA", LEFT)])

    assert assigned == {}


def test_assign_falls_back_to_the_nearest_within_tolerance():
    """Generalized coastlines put island points just offshore."""
    just_outside = {"a": (0.5, -2.0 - NEAREST_TOLERANCE_DEGREES / 2)}

    assert _assign(just_outside, [("AA", LEFT)]) == {}
    assert _assign(
        just_outside, [("AA", LEFT)], tolerance=NEAREST_TOLERANCE_DEGREES
    ) == {"a": "AA"}


def test_build_places_replaces_places_and_stamps_the_vintage(census, geography_db):
    counts = build_places(year=YEAR, geography_path=str(geography_db))

    assert counts["place"] == 3
    assert counts["without_subdivision"] == 0
    assert counts["vintage"] == YEAR

    conn = sqlite3.connect(geography_db)
    places = dict(
        conn.execute("select code, subdivision from place where kind = 'zcta'")
    )
    assert places == {"00001": "AA", "00002": "BB", "00003": "AA"}
    # the stale row is gone, along with its zone assignment
    assert "09999" not in places
    assert conn.execute(
        "select count(*) from place_zone where code = '09999'"
    ).fetchone()[0] == 0

    meta = dict(conn.execute("select key, value from meta"))
    assert meta["place_vintage"] == str(YEAR)
    assert meta["place_source"] == "census-gazetteer"


def test_build_places_recomputes_zone_assignments(census, geography_db):
    build_places(year=YEAR, geography_path=str(geography_db))

    conn = sqlite3.connect(geography_db)
    zones = dict(
        conn.execute(
            "select code, zone_id from place_zone where system = 'test_zone'"
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
        "insert into place values ('zcta', ?, 'US', 'AA', 0.5, -1.5)",
        [("1{:04d}".format(i),) for i in range(100)],
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="partial download"):
        build_places(year=YEAR, geography_path=str(geography_db))
