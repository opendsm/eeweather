"""Refresh the live parts of the packaged data files in place.

Updates the GHCNh catalog (newly listed stations), its observation
inventory and quality ratings, identity rows for appended stations, and
WMO/ICAO alias rows the GHCNh station list carries. Geography packs,
archive station lists, and existing identifier rows are never touched.
Station ids are permanent: existing rows are never re-keyed or deleted.

Stations append only when they fall within the geography the package
serves (within APPEND_BUFFER_KM of a zone geometry of an attached
geography pack; offshore platforms self-exclude) and have observations
within the last APPEND_ACTIVITY_YEARS full years; appended stations
arrive with their zone assignments. Implausibly small upstream files
abort the refresh rather than wiping packaged content.
"""
import csv
import io
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

import requests
from shapely.geometry import Point, shape

from ..registry.db import (
    GHCNH_DB_PATH,
    IDENTIFIERS_DB_PATH,
    MONTH_COLUMNS,
    metadata_db_connection_proxy,
)
from ..registry.quality import QUALITY_WINDOW_YEARS, _quality_from_minimum
from .migrate import EXCLUDED_ALIASES, _country, _float_or_none, _stamp_refreshed



STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh-station-list.csv"
)
INVENTORY_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh-inventory.txt"
)

REQUEST_TIMEOUT_SECONDS = 120

# admission buffer around zone geometries: coastal stations sit just
# outside imprecise polygon edges; offshore platforms sit far outside
APPEND_BUFFER_KM = 10.0

APPEND_ACTIVITY_YEARS = 2


def _fetch_station_list():
    """GHCNh station list as {ghcn_id: (name, lat, lon, elev, wmo, icao, iso_code)}."""
    response = requests.get(STATION_LIST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    stations = {}
    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        ghcn_id = (row.get("GHCN_ID") or "").strip()
        if not ghcn_id:
            continue
        stations[ghcn_id] = (
            (row.get("NAME") or "").strip(),
            row.get("LATITUDE"),
            row.get("LONGITUDE"),
            row.get("ELEVATION"),
            (row.get("WMO_ID") or "").strip(),
            (row.get("ICAO") or "").strip(),
            (row.get("ISO_CODE") or "").strip(),
        )

    return stations


def _fetch_inventory():
    """GHCNh inventory rows as (ghcn_id, year, jan..dec observation counts)."""
    response = requests.get(INVENTORY_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    rows = []
    for line in response.text.splitlines():
        parts = line.split()
        if len(parts) != 2 + len(MONTH_COLUMNS):
            continue
        ghcn_id, year = parts[0], parts[1]
        if not year.isdigit():  # skip the header row
            continue
        rows.append((ghcn_id, int(year)) + tuple(int(n) for n in parts[2:]))

    return rows


def _zone_geometries():
    """(system, zone_id, shape) triples from every attached geography pack."""
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()
    geometries = []
    for alias in proxy.geography_aliases:
        for system, zone_id, geometry in conn.execute(
            "select system, zone_id, geometry from {}.zone".format(alias)
        ):
            geometries.append((system, zone_id, shape(json.loads(geometry))))

    return geometries


def _recently_active_stations(inventory):
    """Station ids with any observations in the last full years."""
    last_full_year = datetime.now(timezone.utc).year - 1
    threshold = last_full_year - APPEND_ACTIVITY_YEARS + 1
    active = set()
    for row in inventory:
        if row[1] >= threshold and any(row[2:]):
            active.add(row[0])

    return active


def _append_new_stations(ghcnh, identifiers, station_list, inventory):
    """Insert stations newly present in the GHCNh list.

    A station appends only when its coordinates fall within
    APPEND_BUFFER_KM of a zone geometry of an attached geography pack and
    it has observations within the last APPEND_ACTIVITY_YEARS full years.
    Appended stations get their zone assignments (strict containment) and
    a ghcn identity row. Existing stations are never modified."""
    known = {row[0] for row in ghcnh.execute("select station_id from stations")}
    geometries = _zone_geometries()
    buffer_degrees = APPEND_BUFFER_KM / 111.0
    active = _recently_active_stations(inventory)
    added = 0
    for ghcn_id, (name, latitude, longitude, elevation, _wmo, _icao, iso_code) in station_list.items():
        if ghcn_id in known or ghcn_id not in active:
            continue
        lat = _float_or_none(latitude)
        lon = _float_or_none(longitude)
        if lat is None or lon is None:
            continue
        point = Point(lon, lat)
        if not any(
            geometry.distance(point) <= buffer_degrees
            for _, _, geometry in geometries
        ):
            continue
        country = iso_code or _country(ghcn_id)
        ghcnh.execute(
            "insert into stations values (?, ?, ?, ?, ?, ?, ?)",
            (
                ghcn_id,
                name,
                lat,
                lon,
                _float_or_none(elevation),
                country,
                None,
            ),
        )
        zones = {}
        for system, zone_id, geometry in geometries:
            if system not in zones and geometry.contains(point):
                zones[system] = zone_id
        ghcnh.executemany(
            "insert into station_zone values (?, ?, ?)",
            [(ghcn_id, system, zone_id) for system, zone_id in zones.items()],
        )
        identifiers.execute(
            "insert into station_identifier values (?, ?, ?, ?)",
            ("ghcn", ghcn_id, ghcn_id, 1),
        )
        added += 1

    return added


def _refresh_aliases(ghcnh, identifiers, station_list):
    """Insert WMO and ICAO alias rows the GHCNh list carries for cataloged
    stations. Existing rows are never modified, and an id that already
    has a recent holder on another station is never claimed (the upstream
    list disagreeing with the packaged crosswalk is a conflict to review,
    not to auto-resolve)."""
    known = {row[0] for row in ghcnh.execute("select station_id from stations")}
    existing = set()
    recent_holders = defaultdict(set)
    for namespace, external_id, station_id, recent in identifiers.execute(
        "select namespace, external_id, station_id, recent"
        " from station_identifier where namespace in ('wmo', 'icao')"
    ):
        existing.add((namespace, external_id, station_id))
        if recent:
            recent_holders[(namespace, external_id)].add(station_id)
    added = 0
    for ghcn_id, (_name, _lat, _lon, _elev, wmo, icao, _iso) in station_list.items():
        if ghcn_id not in known:
            continue
        for namespace, external_id in (("wmo", wmo), ("icao", icao)):
            if not external_id:
                continue
            if (namespace, external_id, ghcn_id) in existing:
                continue
            if (namespace, external_id, ghcn_id) in EXCLUDED_ALIASES:
                continue
            if recent_holders[(namespace, external_id)] - {ghcn_id}:
                continue
            identifiers.execute(
                "insert into station_identifier values (?, ?, ?, ?)",
                (namespace, external_id, ghcn_id, 1),
            )
            recent_holders[(namespace, external_id)].add(ghcn_id)
            added += 1

    return added


def _replace_inventory(ghcnh, inventory):
    """Replace inventory rows for cataloged stations."""
    known = {row[0] for row in ghcnh.execute("select station_id from stations")}
    ghcnh.execute("delete from inventory")
    placeholders = ", ".join("?" for _ in range(2 + len(MONTH_COLUMNS)))
    rows = [row for row in inventory if row[0] in known]
    ghcnh.executemany(
        "insert into inventory values ({})".format(placeholders), rows
    )

    return len(rows)


def _recompute_quality(ghcnh):
    """Recompute the quality ratings over the last full years."""
    last_full_year = datetime.now(timezone.utc).year - 1
    window_start = last_full_year - QUALITY_WINDOW_YEARS + 1
    months = ", ".join(MONTH_COLUMNS)
    counts_by_station = {}
    for row in ghcnh.execute(
        "select station_id, year, {} from inventory"
        " where year between ? and ?".format(months),
        (window_start, last_full_year),
    ):
        counts_by_station.setdefault(row[0], {})[row[1]] = row[2:]

    ghcnh.execute("delete from quality")
    for station_id, in ghcnh.execute("select station_id from stations").fetchall():
        years = counts_by_station.get(station_id, {})
        minimum = None
        for year in range(window_start, last_full_year + 1):
            year_minimum = min(years.get(year, (0,) * 12))
            if minimum is None or year_minimum < minimum:
                minimum = year_minimum
        ghcnh.execute(
            "insert into quality values (?, ?)",
            (station_id, _quality_from_minimum(minimum)),
        )


def _plausible_or_raise(ghcnh, station_list, inventory):
    """Abort when an upstream file is implausibly small: a renamed header
    or format change must fail the refresh, not wipe packaged content."""
    n_stations = ghcnh.execute("select count(*) from stations").fetchone()[0]
    n_inventory = ghcnh.execute("select count(*) from inventory").fetchone()[0]
    listed = sum(1 for row in ghcnh.execute("select station_id from stations")
                 if row[0] in station_list)
    if listed < 0.9 * n_stations:
        raise RuntimeError(
            "Implausible station list: covers {} of {} cataloged"
            " stations.".format(listed, n_stations)
        )
    covered = sum(1 for row in inventory if row[0] in
                  {r[0] for r in ghcnh.execute("select station_id from stations")})
    if covered < 0.9 * n_inventory:
        raise RuntimeError(
            "Implausible inventory: {} rows for cataloged stations,"
            " packaged has {}.".format(covered, n_inventory)
        )


def refresh(ghcnh_path=GHCNH_DB_PATH, identifiers_path=IDENTIFIERS_DB_PATH):
    """Refresh live packaged content in place; returns change counts."""
    station_list = _fetch_station_list()
    inventory = _fetch_inventory()

    ghcnh = sqlite3.connect(ghcnh_path)
    identifiers = sqlite3.connect(identifiers_path)
    try:
        _plausible_or_raise(ghcnh, station_list, inventory)
        added = _append_new_stations(ghcnh, identifiers, station_list, inventory)
        aliases_added = _refresh_aliases(ghcnh, identifiers, station_list)
        inventory_rows = _replace_inventory(ghcnh, inventory)
        _recompute_quality(ghcnh)
        _stamp_refreshed(ghcnh)
        for conn in (ghcnh, identifiers):
            conn.commit()
            conn.execute("vacuum")
    finally:
        ghcnh.close()
        identifiers.close()

    result = {
        "stations_added": added,
        "aliases_added": aliases_added,
        "inventory_rows": inventory_rows,
    }

    return result
