"""Rebuild a geography pack's places from Census primary sources.

The packaged ZCTA places are the **2010** ZCTA definition. They came from
``cb_2016_us_zcta510_500k.zip`` -- ``zcta510`` is the vintage, GENZ2016 is
only the release year -- the ad-hoc scripts that downloaded it were removed,
and ``_migrate_places`` has copied the same rows forward ever since. Nothing
in the pack records which vintage it is, so a result cannot be tied to the
geography that produced it.

This appends a Census vintage to the ``place`` and ``place_zone`` tables --
beside any the pack already holds, never replacing them -- and stamps it.
Rebuilding the same year is idempotent; readers resolve the newest vintage
for a code (:func:`eeweather.registry.summaries.get_place`).

Two things make it smaller than it looks. eeweather stores **no ZCTA
geometry at all** -- a place is a point, a country, a subdivision and its
zone assignments -- so the rebuild does not need the ZCTA cartographic
boundary files, which Census stopped publishing after GENZ2020
(``cb_2021_us_zcta520_500k.zip`` is a 404). And the zone assignments are
recomputed from the pack's own ``zone`` geometries, the same geometries
:func:`eeweather.registry.zones.zones_at` answers from at runtime.

The one genuinely new piece is ``subdivision``: the Gazetteer has no state
column, so each ZCTA's state comes from the Census ZCTA-to-county
relationship file, whose county GEOID carries the state FIPS in its first
two digits. It is authoritative rather than a generalized boundary, so it
is exact at state lines, and every ZCTA it lists has a county; there is no
geometry to read and no shapefile dependency. ZCTA definitions change only
decennially, so one relationship file resolves every Gazetteer year in its
decade.

Census's internal point is also a better point than what the package
carries. Against the 2020 ZCTA polygons, 1,833 packaged points fall outside
their own ZCTA (median 0.46 km, worst 220 km; Ventura 93001 sits 19.18 km
offshore) versus 42 for the Gazetteer points (worst 5.18 km).
"""
import contextlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime, timezone

import requests
from shapely.geometry import Point, shape
from shapely.prepared import prep
from shapely.strtree import STRtree

from ..registry.db import _REGISTRY_DIR


GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_zcta_national.zip"
)
# County GEOID carries the state FIPS in its first two digits; ZCTA
# definitions are decennial, so the 2020 file resolves the 2020s.
RELATIONSHIP_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)

# State (and equivalent) FIPS -> USPS abbreviation, the form ``place``
# stores. Covers the 50 states, DC, and the territories Census codes.
STATE_FIPS_TO_USPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "74": "UM", "78": "VI",
}

REQUEST_TIMEOUT_SECONDS = 120

# how many years back to probe for the newest published vintage
VINTAGE_LOOKBACK_YEARS = 3

# losing this much of the packaged count is a bad download, not a real change
PLAUSIBILITY_FLOOR = 0.9

# the relationship file assigns a county, and so a state, to every ZCTA it
# lists; more than this fraction unresolved means the join, not the data,
# is wrong (a changed relationship-file schema, a wrong decade)
WITHOUT_SUBDIVISION_FLOOR = 0.01


def _get(url):
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    return response.content


def _available(url):
    response = requests.head(url, timeout=REQUEST_TIMEOUT_SECONDS)

    return response.status_code == 200


def resolve_vintage(year=None):
    """The newest year the Census Gazetteer is published for.

    The Gazetteer is published annually, so the vintage is the newest year
    it is available. The ZCTA-to-county relationship file is decennial and
    resolves every Gazetteer year in its decade, so it is not probed here.
    """
    if year is not None:
        return year

    this_year = datetime.now(timezone.utc).year
    for candidate in range(this_year, this_year - VINTAGE_LOOKBACK_YEARS - 1, -1):
        if _available(GAZETTEER_URL.format(year=candidate)):
            return candidate

    raise RuntimeError(
        "No Census Gazetteer published for {}-{}".format(
            this_year - VINTAGE_LOOKBACK_YEARS, this_year
        )
    )


def fetch_zcta_points(year):
    """{zcta: (latitude, longitude)} from the Census Gazetteer.

    The Gazetteer's INTPTLAT/INTPTLONG is an *internal* point, constructed
    to fall inside the area, not a geometric centroid.
    """
    archive = zipfile.ZipFile(io.BytesIO(_get(GAZETTEER_URL.format(year=year))))
    name = "{}_Gaz_zcta_national.txt".format(year)
    text = archive.read(name).decode("utf-8-sig")

    lines = text.splitlines()
    header = [field.strip() for field in lines[0].split("\t")]
    if len(header) == 1:
        header = [field.strip() for field in lines[0].split("|")]
        separator = "|"
    else:
        separator = "\t"

    geoid = header.index("GEOID")
    latitude = header.index("INTPTLAT")
    longitude = header.index("INTPTLONG")

    points = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(separator)]
        points[fields[geoid]] = (float(fields[latitude]), float(fields[longitude]))

    return points


def fetch_zcta_states(year):
    """{zcta: usps} from the Census ZCTA-to-county relationship file.

    A ZCTA can span counties and states; the state of the county holding
    the most of the ZCTA's land wins. County GEOID's first two digits are
    the state FIPS. The relationship file is decennial, so ``year`` selects
    nothing here -- one file serves its whole decade.
    """
    text = _get(RELATIONSHIP_URL).decode("utf-8-sig")
    lines = text.splitlines()
    header = lines[0].split("|")
    zcta_col = header.index("GEOID_ZCTA5_20")
    county_col = header.index("GEOID_COUNTY_20")
    area_col = header.index("AREALAND_PART")

    largest = {}
    states = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("|")
        code = fields[zcta_col]
        if not code:  # county rows carrying no ZCTA part
            continue
        usps = STATE_FIPS_TO_USPS.get(fields[county_col][:2])
        if usps is None:
            continue
        try:
            area = float(fields[area_col])
        except ValueError:
            area = 0.0
        if code not in largest or area > largest[code]:
            largest[code] = area
            states[code] = usps

    return states


def _assign(points, features, tolerance=None):
    """{code: value} for every point falling inside a feature's geometry.

    Point-in-polygon over tens of thousands of points needs an index and
    prepared geometries; without them this is minutes rather than seconds.

    With a ``tolerance``, a point inside nothing falls back to the nearest
    feature within that distance, in degrees.
    """
    if not features:
        return {}

    geometries = [geometry for _, geometry in features]
    values = [value for value, _ in features]
    prepared = [prep(geometry) for geometry in geometries]
    tree = STRtree(geometries)

    assigned = {}
    unplaced = []
    for code, (latitude, longitude) in points.items():
        point = Point(longitude, latitude)
        for index in tree.query(point):
            if prepared[index].contains(point):
                assigned[code] = values[index]
                break
        else:
            unplaced.append((code, point))

    if tolerance is not None:
        for code, point in unplaced:
            index = tree.nearest(point)
            if geometries[index].distance(point) <= tolerance:
                assigned[code] = values[index]

    return assigned


def _zone_features(geography):
    """[(system, zone_id, geometry)] from the pack's own zone table."""
    features = []
    for system, zone_id, geometry in geography.execute(
        "select system, zone_id, geometry from zone order by system, zone_id"
    ):
        features.append((system, zone_id, shape(json.loads(geometry))))

    return features


def _stamp_vintage(geography, year, source):
    geography.execute(
        "create table if not exists meta (key text primary key, value text)"
        " without rowid"
    )
    for key, value in (
        ("place_vintage", str(year)),
        ("place_source", source),
        # the key registry.update.refreshed_at reads; geography is part of
        # the updatable set, so it is stamped the same way the station
        # registry is rather than under a name only this module knows
        ("refreshed_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
    ):
        geography.execute("insert or replace into meta values (?, ?)", (key, value))


def _plausible_or_raise(geography, points):
    # against the newest vintage already held, not every retained vintage
    # summed, so retention does not inflate the baseline
    existing = geography.execute(
        "select count(*) from place where kind = 'zcta'"
        " and vintage = (select max(vintage) from place where kind = 'zcta')"
    ).fetchone()[0]
    if existing and len(points) < existing * PLAUSIBILITY_FLOOR:
        raise RuntimeError(
            "Census Gazetteer returned {} ZCTAs against {} in the newest"
            " packaged vintage; refusing to add a partial download.".format(
                len(points), existing
            )
        )


def build_places(year=None, geography_path=None):
    """Append a Census vintage's ZCTA places to a geography pack.

    Adds the ``place`` and ``place_zone`` rows for ``kind='zcta'`` at the
    resolved ``year`` beside any vintages the pack already holds, and stamps
    the vintage in ``meta``. Rebuilding the same year replaces only that
    year's rows. Zone geometries are never touched -- they are static
    content this does not have a primary source for.

    Returns a dict of row counts.
    """
    if geography_path is None:
        geography_path = os.path.join(_REGISTRY_DIR, "geography_us.db")

    year = resolve_vintage(year)
    points = fetch_zcta_points(year)
    subdivisions = fetch_zcta_states(year)

    # a bare `with sqlite3.connect(...) as` commits but never closes the handle;
    # closing() closes it, the inner `geography` keeps the transaction semantics
    with contextlib.closing(sqlite3.connect(geography_path)) as geography, geography:
        _plausible_or_raise(geography, points)

        zone_features = _zone_features(geography)
        by_system = {}
        for system, zone_id, geometry in zone_features:
            by_system.setdefault(system, []).append((zone_id, geometry))
        zones_by_code = {}
        for system, features in by_system.items():
            for code, zone_id in _assign(points, features).items():
                zones_by_code.setdefault(code, {})[system] = zone_id

        # scope the delete to this vintage so a rebuild of the same year is
        # idempotent while earlier vintages are retained
        geography.execute(
            "delete from place where kind = 'zcta' and vintage = ?", (year,)
        )
        geography.execute(
            "delete from place_zone where kind = 'zcta' and vintage = ?", (year,)
        )
        geography.executemany(
            "insert into place values (?, 'zcta', ?, 'US', ?, ?, ?)",
            [
                (year, code, subdivisions.get(code), latitude, longitude)
                for code, (latitude, longitude) in sorted(points.items())
            ],
        )
        geography.executemany(
            "insert into place_zone values (?, 'zcta', ?, ?, ?)",
            [
                (year, code, system, zone_id)
                for code in sorted(zones_by_code)
                for system, zone_id in sorted(zones_by_code[code].items())
            ],
        )
        _stamp_vintage(geography, year, "census-gazetteer")

        without_subdivision = sum(
            1 for code in points if subdivisions.get(code) is None
        )
        if points and without_subdivision > len(points) * WITHOUT_SUBDIVISION_FLOOR:
            raise RuntimeError(
                "{} of {} ZCTAs got no state from the relationship file;"
                " refusing to add a vintage the join could not resolve.".format(
                    without_subdivision, len(points)
                )
            )

        counts = {
            "vintage": year,
            "place": geography.execute(
                "select count(*) from place where kind = 'zcta' and vintage = ?",
                (year,),
            ).fetchone()[0],
            "place_zone": geography.execute(
                "select count(*) from place_zone where kind = 'zcta'"
                " and vintage = ?",
                (year,),
            ).fetchone()[0],
            "without_subdivision": without_subdivision,
        }

    return counts
