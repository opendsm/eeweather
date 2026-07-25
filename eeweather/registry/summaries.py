"""Registry enumeration and place lookups."""
import pandas as pd

from ..exceptions import UnrecognizedPlaceError
from .db import metadata_db_connection_proxy



def get_station_ids(state=None):
    """Registry ids of all stations, optionally filtered by subdivision.

    Stations are enumerated from the registered source catalogs.
    """
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()
    station_ids = set()
    for alias in proxy.catalogs:
        if state is None:
            cur = conn.execute(
                "select station_id from {}.stations".format(alias)
            )
        else:
            cur = conn.execute(
                "select station_id from {}.stations where subdivision = ?".format(
                    alias
                ),
                (state,),
            )
        station_ids.update(row[0] for row in cur.fetchall())

    return sorted(station_ids)


def get_zcta_ids(state=None):
    """Codes of all ZCTA places, optionally filtered by subdivision."""
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()
    zcta_ids = set()
    for alias in proxy.geography_aliases:
        if state is None:
            cur = conn.execute(
                "select code from {}.place where kind = 'zcta'".format(alias)
            )
        else:
            cur = conn.execute(
                "select code from {}.place where kind = 'zcta'"
                " and subdivision = ?".format(alias),
                (state,),
            )
        zcta_ids.update(row[0] for row in cur.fetchall())

    return sorted(zcta_ids)


def get_place(kind, code):
    """Registry metadata for a place: the place row fields plus ``zones``."""
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()
    for alias in proxy.geography_aliases:
        cur = conn.cursor()
        cur.execute(
            "select * from {}.place where kind = ? and code = ?".format(alias),
            (kind, code),
        )
        row = cur.fetchone()
        if row is None:
            continue
        place = {col[0]: row[i] for i, col in enumerate(cur.description)}
        place["zones"] = dict(
            conn.execute(
                "select system, zone_id from {}.place_zone"
                " where kind = ? and code = ?".format(alias),
                (kind, code),
            ).fetchall()
        )

        return place

    raise UnrecognizedPlaceError(kind, code)


def search_stations(country=None, subdivision=None, has_sources=()):
    """Registry stations as a DataFrame indexed by station id.

    One row per station from the registered source catalogs (first
    catalog listing a station wins): name, latitude, longitude,
    elevation, country, subdivision, quality, one column per zone
    system, and per-source availability flags.
    """
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()

    frames = []
    for alias in proxy.catalogs:
        frames.append(_catalog_frame(conn, alias, proxy))
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()

    if country is not None:
        df = df[df.country == country]
    if subdivision is not None:
        df = df[df.subdivision == subdivision]
    for source in has_sources:
        if source in proxy.catalogs:
            continue
        column = "is_{}".format(source)
        if column not in df.columns:
            raise ValueError("Unknown source: {}".format(source))
        df = df[df[column]]

    return df


def _catalog_frame(conn, alias, proxy):
    availability_selects = "".join(
        """
        , max({avail}.station_id) is not null as is_{avail}""".format(avail=avail)
        for avail in proxy.availability_sources
    )
    availability_joins = "".join(
        """
        left join {avail}.stations as {avail} on
          s.station_id = {avail}.station_id""".format(avail=avail)
        for avail in proxy.availability_sources
    )
    quality_select = ", null as quality"
    quality_join = ""
    if alias in proxy.quality_sources:
        quality_select = ", max(q.quality) as quality"
        quality_join = (
            "\n        left join {alias}.quality as q on"
            " s.station_id = q.station_id".format(alias=alias)
        )

    df = pd.read_sql_query(
        """
      select
        s.station_id
        , s.name
        , s.latitude
        , s.longitude
        , s.elevation
        , s.country
        , s.subdivision
        {quality_select}
        , max(case when z.system = 'iecc_climate_zone' then z.zone_id end)
            as iecc_climate_zone
        , max(case when z.system = 'iecc_moisture_regime' then z.zone_id end)
            as iecc_moisture_regime
        , max(case when z.system = 'ba_climate_zone' then z.zone_id end)
            as ba_climate_zone
        , max(case when z.system = 'ca_climate_zone' then z.zone_id end)
            as ca_climate_zone
        {availability_selects}
      from
        {alias}.stations as s
        left join {alias}.station_zone as z on s.station_id = z.station_id
        {quality_join}
        {availability_joins}
      group by s.station_id
      order by s.station_id
    """.format(
            alias=alias,
            quality_select=quality_select,
            quality_join=quality_join,
            availability_selects=availability_selects,
            availability_joins=availability_joins,
        ),
        conn,
    ).set_index("station_id")
    for avail in proxy.availability_sources:
        column = "is_{}".format(avail)
        df[column] = df[column].astype(bool)

    return df
