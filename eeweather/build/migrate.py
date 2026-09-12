"""Migrate a single-file ghcn-keyed database to the packaged data files.

Produces the identifier crosswalk, the US geography pack, and one
database per built-in source (the GHCNh catalog with inventory and
quality; TMY3/CZ2010 station lists). Static content originates from
primary sources that are partly retired, so it is carried forward from
the existing packaged data rather than rebuilt; live content is updated
separately by ``refresh``.
"""
import os
import sqlite3
from datetime import datetime, timezone

from ..registry.db import MONTH_COLUMNS
from .schema import (
    CZ2010_SCHEMA,
    GEOGRAPHY_SCHEMA,
    GHCNH_SCHEMA,
    IDENTIFIERS_SCHEMA,
    TMY3_SCHEMA,
    create_schema,
)



# GHCNh ids begin with a FIPS 10-4 country code; the registry stores ISO
# 3166-1 alpha-2. Codes below are the full set present in the registry.
FIPS_TO_ISO = {
    "US": "US",
    "AS": "AU",
    "RQ": "PR",
    "AY": "AQ",
    "GM": "DE",
    "VQ": "VI",
    "CQ": "MP",
    "AQ": "AS",
    "GQ": "GU",
    "WQ": "UM",
    "MQ": "UM",
    "JQ": "UM",
    "LQ": "UM",
    "FQ": "UM",
    "DQ": "UM",
    "TT": "TT",
    "PP": "PG",
    "AV": "AI",
}

WBAN_SENTINEL = "99999"

# isd-history's catch-all id, reused for hundreds of distinct Australian
# sites; aliases derived from it reference no particular station
USAF_CATCHALL = "949999"

# alias rows that contradict station coordinates in other primary sources
# (e.g. the GHCNh list assigns Wasilla's ICAO to Yakataga, whose isd
# records say PACY); excluded on build and on refresh
EXCLUDED_ALIASES = {
    ("icao", "PAWS", "USW00026445"),
}

# recency demotions where two records legitimately reference one site
# (TJSJ: the San Juan airport's COOP record next to its airport record)
DEMOTED_ALIASES = {
    ("icao", "TJSJ", "RQC00668814"),
}

ZONE_SYSTEMS = (
    "iecc_climate_zone",
    "iecc_moisture_regime",
    "ba_climate_zone",
    "ca_climate_zone",
)

# The packaged ZCTA places are the 2010 ZCTA definition delivered by the
# GENZ2016 cartographic release (see build.geography); that release year is
# their vintage. A Census rebuild (build_places) appends a newer vintage
# beside them rather than replacing them, and readers resolve the newest.
LEGACY_PLACE_VINTAGE = 2016


def _connect_fresh(path, schema):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    create_schema(conn, schema)

    return conn


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# GHCN's id-encoding knowledge lives here: this is the only place a
# station id is sliced to derive an attribute. Generic row-insert code
# receives country as the value this returns, never by parsing the id.
def _country(ghcn_id):
    return FIPS_TO_ISO.get(ghcn_id[:2])


def _migrate_stations(src, identifiers, ghcnh):
    rows = src.execute(
        """
        select ghcn_id, name, latitude, longitude, elevation, state, quality,
               usaf_ids, wban_ids, recent_wban_id, icao_code,
               iecc_climate_zone, iecc_moisture_regime,
               ba_climate_zone, ca_climate_zone
        from station_metadata
        """
    ).fetchall()
    for (
        ghcn_id, name, latitude, longitude, elevation, state, quality,
        usaf_ids, wban_ids, recent_wban_id, icao_code, *zones
    ) in rows:
        ghcnh.execute(
            "insert into stations values (?, ?, ?, ?, ?, ?, ?)",
            (
                ghcn_id,
                name,
                _float_or_none(latitude),
                _float_or_none(longitude),
                _float_or_none(elevation),
                _country(ghcn_id),
                state,
            ),
        )
        ghcnh.execute(
            "insert into quality values (?, ?)", (ghcn_id, quality)
        )

        alias_rows = [("ghcn", ghcn_id, 1)]
        real_usafs = [
            u for u in (usaf_ids or "").split(",") if u and u != USAF_CATCHALL
        ]
        for usaf_id in real_usafs:
            alias_rows.append(("usaf", usaf_id, 0))
        # a station whose only usaf id is the catch-all inherited its wban
        # list from the catch-all's unrelated records
        if real_usafs:
            for wban_id in set((wban_ids or "").split(",")):
                if wban_id and wban_id != WBAN_SENTINEL:
                    alias_rows.append(
                        ("wban", wban_id, int(wban_id == recent_wban_id))
                    )
        if icao_code:
            alias_rows.append(("icao", icao_code, 1))
        rows = [
            (namespace, external_id, ghcn_id,
             0 if (namespace, external_id, ghcn_id) in DEMOTED_ALIASES else recent)
            for namespace, external_id, recent in alias_rows
            if (namespace, external_id, ghcn_id) not in EXCLUDED_ALIASES
        ]
        identifiers.executemany(
            "insert into station_identifier values (?, ?, ?, ?)", rows
        )

        for system, zone_id in zip(ZONE_SYSTEMS, zones):
            if zone_id is not None:
                ghcnh.execute(
                    "insert into station_zone values (?, ?, ?)",
                    (ghcn_id, system, str(zone_id)),
                )


def _migrate_inventory(src, ghcnh):
    months = ", ".join(MONTH_COLUMNS)
    rows = src.execute(
        "select ghcn_id, year, {} from ghcn_inventory".format(months)
    ).fetchall()
    placeholders = ", ".join("?" for _ in range(2 + len(MONTH_COLUMNS)))
    ghcnh.executemany(
        "insert into inventory values ({})".format(placeholders), rows
    )


def _migrate_places(src, geography):
    rows = src.execute(
        """
        select zcta_id, state, latitude, longitude,
               iecc_climate_zone, iecc_moisture_regime,
               ba_climate_zone, ca_climate_zone
        from zcta_metadata
        """
    ).fetchall()
    for zcta_id, state, latitude, longitude, *zones in rows:
        geography.execute(
            "insert into place values (?, ?, ?, ?, ?, ?, ?)",
            (LEGACY_PLACE_VINTAGE, "zcta", zcta_id, "US", state,
             _float_or_none(latitude), _float_or_none(longitude)),
        )
        for system, zone_id in zip(ZONE_SYSTEMS, zones):
            if zone_id is not None:
                geography.execute(
                    "insert into place_zone values (?, ?, ?, ?, ?)",
                    (LEGACY_PLACE_VINTAGE, "zcta", zcta_id, system, str(zone_id)),
                )


def _migrate_zones(src, geography):
    for system in ZONE_SYSTEMS:
        if system == "ca_climate_zone":
            name_col = "name"
        else:
            name_col = "null"
        rows = src.execute(
            "select {}, {}, geometry from {}_metadata".format(system, name_col, system)
        ).fetchall()
        geography.executemany(
            "insert into zone values (?, ?, ?, ?)",
            [(system, str(zone_id), name, geometry)
             for zone_id, name, geometry in rows],
        )


def _migrate_normals(src, tmy3, cz2010):
    tmy3.executemany(
        "insert into stations values (?, ?, ?)",
        src.execute(
            "select ghcn_id, usaf_id, class from tmy3_station_metadata"
        ).fetchall(),
    )
    cz2010.executemany(
        "insert into stations values (?, ?)",
        src.execute(
            "select ghcn_id, usaf_id from cz2010_station_metadata"
        ).fetchall(),
    )


def _stamp_refreshed(ghcnh):
    ghcnh.execute(
        "create table if not exists meta (key text primary key, value text)"
        " without rowid"
    )
    ghcnh.execute(
        "insert or replace into meta values ('refreshed_at', ?)",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d"),),
    )


def _stamp_geography(geography, vintage):
    """Record the packaged pack's vintage, the same shape build_places stamps."""
    geography.execute(
        "create table if not exists meta (key text primary key, value text)"
        " without rowid"
    )
    for key, value in (
        ("place_vintage", str(vintage)),
        ("place_source", "census-genz2016"),
        ("refreshed_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
    ):
        geography.execute("insert or replace into meta values (?, ?)", (key, value))


def migrate(source_path, dest_dir):
    """Build the packaged data files from a single-file ghcn-keyed
    database, writing identifiers.db, geography_us.db, ghcnh.db, tmy3.db,
    and cz2010.db into ``dest_dir``."""
    src = sqlite3.connect(source_path)
    identifiers = _connect_fresh(
        os.path.join(dest_dir, "identifiers.db"), IDENTIFIERS_SCHEMA
    )
    geography = _connect_fresh(
        os.path.join(dest_dir, "geography_us.db"), GEOGRAPHY_SCHEMA
    )
    ghcnh = _connect_fresh(os.path.join(dest_dir, "ghcnh.db"), GHCNH_SCHEMA)
    tmy3 = _connect_fresh(os.path.join(dest_dir, "tmy3.db"), TMY3_SCHEMA)
    cz2010 = _connect_fresh(os.path.join(dest_dir, "cz2010.db"), CZ2010_SCHEMA)

    _migrate_stations(src, identifiers, ghcnh)
    _migrate_inventory(src, ghcnh)
    _migrate_places(src, geography)
    _migrate_zones(src, geography)
    _migrate_normals(src, tmy3, cz2010)
    _stamp_refreshed(ghcnh)
    _stamp_geography(geography, LEGACY_PLACE_VINTAGE)

    counts = {}
    for name, conn, tables in (
        ("identifiers", identifiers, ("station_identifier",)),
        ("geography_us", geography, ("place", "place_zone", "zone")),
        ("ghcnh", ghcnh, ("stations", "station_zone", "inventory", "quality")),
        ("tmy3", tmy3, ("stations",)),
        ("cz2010", cz2010, ("stations",)),
    ):
        for table in tables:
            counts["{}.{}".format(name, table)] = conn.execute(
                "select count(*) from {}".format(table)
            ).fetchone()[0]
        conn.commit()
        conn.execute("vacuum")
        conn.close()
    src.close()

    return counts
