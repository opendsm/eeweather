"""DDL for the packaged data files.

The registry holds two kinds of files, each named for exactly what it
contains: the identifier crosswalk (identifiers.db — global; station ids
are GHCN ids, other id systems are aliases), and regional geography
packs (geography_us.db — zone geometries and coded places with their
zone assignments). Each source packages its own database beside its
adapter: the GHCNh catalog (station facts and their zone assignments,
as GHCNh's material claims them) with observation inventory and quality
ratings, and the TMY3/CZ2010 archive station lists. Connections ATTACH
geography packs and registered source databases so fact, availability,
and quality queries can join across files. Composite-key tables are WITHOUT ROWID so
the primary key is the storage order and no shadow index is needed.
"""
from ..registry.db import MONTH_COLUMNS



IDENTIFIERS_SCHEMA = (
    """
    create table station_identifier (
      namespace text not null,
      external_id text not null,
      station_id text not null,
      recent integer not null default 0,
      primary key (namespace, external_id, station_id)
    ) without rowid
    """,
    "create index ix_identifier_station on station_identifier (station_id)",
)

GEOGRAPHY_SCHEMA = (
    # ``vintage`` is the Census publication year the places were built from,
    # and it leads the primary key so more than one vintage coexists in a
    # pack: a rebuild appends the new year beside the rows earlier results
    # were resolved against, rather than overwriting them. Readers resolve
    # the newest vintage for a code (see registry.summaries.get_place).
    """
    create table place (
      vintage integer not null,
      kind text not null,
      code text not null,
      country text,
      subdivision text,
      latitude real,
      longitude real,
      primary key (vintage, kind, code)
    ) without rowid
    """,
    """
    create table place_zone (
      vintage integer not null,
      kind text not null,
      code text not null,
      system text not null,
      zone_id text not null,
      primary key (vintage, kind, code, system)
    ) without rowid
    """,
    """
    create table zone (
      system text not null,
      zone_id text not null,
      name text,
      geometry text,
      primary key (system, zone_id)
    ) without rowid
    """,
)

GHCNH_SCHEMA = (
    """
    create table stations (
      station_id text primary key,
      name text,
      latitude real,
      longitude real,
      elevation real,
      country text,
      subdivision text
    ) without rowid
    """,
    "create index ix_stations_country on stations (country, subdivision)",
    """
    create table station_zone (
      station_id text not null,
      system text not null,
      zone_id text not null,
      primary key (station_id, system)
    ) without rowid
    """,
    """
    create table inventory (
      station_id text not null,
      year integer not null,
      {},
      primary key (station_id, year)
    ) without rowid
    """.format(", ".join("{} integer".format(m) for m in MONTH_COLUMNS)),
    """
    create table quality (
      station_id text primary key,
      quality text not null
    ) without rowid
    """,
    """
    create table meta (
      key text primary key,
      value text
    ) without rowid
    """,
)

# normals sources: which stations have archives, and the USAF id naming
# each station's archive file
TMY3_SCHEMA = (
    """
    create table stations (
      station_id text primary key,
      usaf_id text not null,
      class text
    ) without rowid
    """,
)

CZ2010_SCHEMA = (
    """
    create table stations (
      station_id text primary key,
      usaf_id text not null
    ) without rowid
    """,
)


def create_schema(conn, statements):
    for statement in statements:
        conn.execute(statement)
