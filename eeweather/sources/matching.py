"""Candidate-station ranking and data-sufficiency selection."""
from functools import cached_property

import numpy as np
import pandas as pd
import pyproj

from ..exceptions import DataNotAvailableError, EEWeatherWarning
from ..registry.db import metadata_db_connection_proxy
from ..registry.quality import get_station_qualities
from ..registry.update import maybe_update
from ..registry.zones import zones_at
from ..station import WeatherStation



__all__ = ("rank_stations", "combine_ranked_stations", "select_station")

def _ranking_columns():
    """Output columns: the fixed set plus one availability flag (and any
    class column) per registered archive source."""
    proxy = metadata_db_connection_proxy
    columns = [
        "rank",
        "distance_meters",
        "latitude",
        "longitude",
        "iecc_climate_zone",
        "iecc_moisture_regime",
        "ba_climate_zone",
        "ca_climate_zone",
        "quality",
        "elevation",
        "subdivision",
    ]
    frame_columns = cached_data.all_station_metadata.columns
    for avail in sorted(proxy.availability_sources):
        class_column = "{}_class".format(avail)
        if class_column in frame_columns:
            columns.append(class_column)
        columns.append("is_{}".format(avail))
    columns.append("difference_elevation_meters")

    return columns


class CachedData(object):
    @cached_property
    def all_station_metadata(self):
        proxy = metadata_db_connection_proxy
        conn = proxy.get_connection()
        frames = []
        for alias in proxy.catalogs:
            frames.append(self._catalog_frame(conn, proxy, alias))
        df = pd.concat(frames)
        df = df[~df.index.duplicated(keep="first")].sort_index()

        return df

    def _catalog_frame(self, conn, proxy, alias):
        availability_selects = "".join(
            """
            , max({avail}.station_id) is not null as is_{avail}
            , max({avail}.class) as {avail}_class""".format(avail=avail)
            if self._has_class(conn, avail) else
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
                "\n            left join {alias}.quality as q on"
                " s.station_id = q.station_id".format(alias=alias)
            )
        df = pd.read_sql_query(
            """
          select
            s.station_id
            , s.latitude
            , s.longitude
            , max(case when z.system = 'iecc_climate_zone' then z.zone_id end)
                as iecc_climate_zone
            , max(case when z.system = 'iecc_moisture_regime' then z.zone_id end)
                as iecc_moisture_regime
            , max(case when z.system = 'ba_climate_zone' then z.zone_id end)
                as ba_climate_zone
            , max(case when z.system = 'ca_climate_zone' then z.zone_id end)
                as ca_climate_zone
            {quality_select}
            , s.elevation
            , s.subdivision
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
            df["is_{}".format(avail)] = df["is_{}".format(avail)].astype(bool)

        return df

    @staticmethod
    def _has_class(conn, alias):
        columns = [
            row[1]
            for row in conn.execute("pragma {}.table_info(stations)".format(alias))
        ]

        return "class" in columns


cached_data = CachedData()


def source_availability_columns():
    """Availability filters served by the packaged data, by source name.

    Catalog sources map to None (every cataloged station serves them);
    archive sources map to their availability flag column.
    """
    proxy = metadata_db_connection_proxy
    columns = {alias: None for alias in proxy.catalogs}
    for alias in proxy.availability_sources:
        columns[alias] = "is_{}".format(alias)

    return columns


def _combine_filters(filters, index):
    combined_filters = pd.Series(True, index=index)
    for f in filters:
        combined_filters &= f

    return combined_filters


def rank_stations(
    site_latitude,
    site_longitude,
    site_elevation=None,
    site_subdivision=None,
    match_zones=(),
    match_subdivision=False,
    has_sources=(),
    minimum_quality=None,
    rating_period=None,
    quality_source="ghcnh",
    max_distance_meters=None,
    max_difference_elevation_meters=None,
):
    """Get a ranked, filtered set of candidate weather stations and metadata
    for a site.

    Parameters
    ----------
    site_latitude : float
        Latitude of the target site.
    site_longitude : float
        Longitude of the target site.
    site_elevation : float, optional
        Elevation of the target site in meters. Ignored unless
        ``max_difference_elevation_meters`` is set.
    site_subdivision : str, optional
        Country subdivision of the target site (e.g. a US state
        abbreviation). Ignored unless ``match_subdivision=True``.
    match_zones : tuple of str
        Zone systems the candidates must match the site in, e.g.
        ``('iecc_climate_zone',)``. Candidates match a system the site has
        no zone for only when they also have none.
    match_subdivision : bool
        If True, filter candidates to the site's subdivision.
    has_sources : tuple of str
        Sources the candidates must be able to serve, e.g. ``('tmy3',)``.
    minimum_quality : {'high', 'medium', 'low'}, optional
        Filter candidates to those meeting or exceeding this quality.
    rating_period : datetime, optional
        When given, quality is rated from observation counts over the five
        calendar years ending two years after this anchor date (sliding
        back to end no later than the last full year), and the ``quality``
        column and ``minimum_quality`` filter use that rating. When None,
        the build-time rating over the last five full years is used.
    quality_source : str
        Source whose observation counts rate quality for
        ``rating_period``.
    max_distance_meters : float, optional
        Filter candidates to those within this distance of the site.
    max_difference_elevation_meters : float, optional
        Filter candidates to those with elevations within this difference
        of ``site_elevation``.

    Returns
    -------
    pandas.DataFrame
        Indexed by station id, sorted by distance, one row per candidate:
        rank, distance_meters, latitude, longitude, one column per zone
        system, quality, elevation, subdivision, tmy3_class,
        is_tmy3/is_cz2010, difference_elevation_meters.
    """
    maybe_update()
    candidates = cached_data.all_station_metadata.copy()

    candidates_defined_lat_long = candidates[
        candidates.latitude.notnull() & candidates.longitude.notnull()
    ]
    candidates_latitude = candidates_defined_lat_long.latitude
    candidates_longitude = candidates_defined_lat_long.longitude
    tiled_site_latitude = np.tile(site_latitude, candidates_latitude.shape)
    tiled_site_longitude = np.tile(site_longitude, candidates_longitude.shape)
    geod = pyproj.Geod(ellps="WGS84")
    dists = geod.inv(
        tiled_site_longitude,
        tiled_site_latitude,
        candidates_longitude.values,
        candidates_latitude.values,
    )[2]
    distance_meters = pd.Series(
        dists, index=candidates_defined_lat_long.index
    ).reindex(candidates.index)
    candidates["distance_meters"] = distance_meters

    if site_elevation is not None:
        difference_elevation_meters = (candidates.elevation - site_elevation).abs()
    else:
        difference_elevation_meters = None
    candidates["difference_elevation_meters"] = difference_elevation_meters

    filters = []

    if match_zones:
        site_zones = zones_at(site_latitude, site_longitude)
        for system in match_zones:
            if system not in candidates.columns:
                raise ValueError("Unknown zone system: {}".format(system))
            site_zone = site_zones.get(system)
            if site_zone is None:
                filters.append(candidates[system].isnull())
            else:
                filters.append(candidates[system] == site_zone)

    if match_subdivision:
        if site_subdivision is None:
            filters.append(candidates.subdivision.isnull())
        else:
            filters.append(candidates.subdivision == site_subdivision)

    availability_columns = source_availability_columns()
    for source in has_sources:
        column = availability_columns.get(source, "unknown")
        if column == "unknown":
            raise ValueError("Unknown source: {}".format(source))
        if column is not None:
            filters.append(candidates[column])

    if rating_period is not None:
        period_qualities = get_station_qualities(rating_period, source=quality_source)
        candidates["quality"] = period_qualities.reindex(
            candidates.index, fill_value="low"
        )

    if minimum_quality is None:
        pass
    elif minimum_quality == "low":
        filters.append(candidates.quality.isin(["high", "medium", "low"]))
    elif minimum_quality == "medium":
        filters.append(candidates.quality.isin(["high", "medium"]))
    elif minimum_quality == "high":
        filters.append(candidates.quality.isin(["high"]))
    else:
        raise ValueError("Unknown minimum_quality: {}".format(minimum_quality))

    if max_distance_meters is not None:
        filters.append(candidates.distance_meters <= max_distance_meters)

    if max_difference_elevation_meters is not None and site_elevation is not None:
        filters.append(
            candidates.difference_elevation_meters <= max_difference_elevation_meters
        )

    combined_filters = _combine_filters(filters, candidates.index)
    filtered_candidates = candidates[combined_filters]
    ranked_filtered_candidates = filtered_candidates.sort_values(
        by=["distance_meters"]
    )

    ranks = range(1, 1 + len(ranked_filtered_candidates))
    ranked_filtered_candidates.insert(0, "rank", ranks)

    return ranked_filtered_candidates[_ranking_columns()]


def combine_ranked_stations(rankings):
    """Combine ranked candidate frames into one fallback-ordered ranking.

    Parameters
    ----------
    rankings : list of pandas.DataFrame
        Ranked candidate frames of the form given by rank_stations, each
        sorted by rank. Stations already present in an earlier frame are
        dropped from later ones.

    Returns
    -------
    pandas.DataFrame
        One frame with a recomputed rank column.
    """
    if len(rankings) == 0:
        raise ValueError("Requires at least one ranking.")

    combined_ranking = rankings[0]
    for ranking in rankings[1:]:
        filtered_ranking = ranking[~ranking.index.isin(combined_ranking.index)]
        combined_ranking = pd.concat([combined_ranking, filtered_ranking])

    combined_ranking["rank"] = range(1, 1 + len(combined_ranking))

    return combined_ranking


def load_hourly_temp_data(
    station, start_date, end_date, fetch_from_web, source=None
):  # pragma: no cover
    df, warnings = station.load_data(
        start_date, end_date, fetch_from_web=fetch_from_web, source=source
    )
    temps = df["temperature"]

    return temps, warnings


def select_station(
    candidates,
    coverage_range=None,
    min_fraction_coverage=0.9,
    distance_warnings=(50000, 200000),
    rank=1,
    fetch_from_web=True,
    coverage_source=None,
):
    """Select a station from ranked candidates that meets data-sufficiency
    criteria.

    Parameters
    ----------
    candidates : pandas.DataFrame
        A frame of the form given by rank_stations, having at least a
        station-id index and a ``distance_meters`` column.
    coverage_range : tuple of (datetime, datetime), optional
        When given, candidates must serve temperature data covering at
        least ``min_fraction_coverage`` of this period.
    coverage_source : str or source object, optional
        The source coverage is tested against; defaults to the
        candidate's default routing (the source actually being served
        should be passed, so a station rich in one source but absent
        from another cannot pass selection wrongly).

    Returns
    -------
    tuple of (WeatherStation or None, list of EEWeatherWarning)
        The first candidate passing the criteria; None if none passes.
    """

    def _test_station(station):
        no_warnings = []
        if coverage_range is None:
            return True, no_warnings

        start_date, end_date = coverage_range
        try:
            tempC, warnings = load_hourly_temp_data(
                station, start_date, end_date, fetch_from_web,
                source=coverage_source,
            )
        except DataNotAvailableError:
            return False, no_warnings

        if len(tempC) == 0:
            return False, no_warnings
        fraction_coverage = tempC.notnull().sum() / float(len(tempC))
        passed = fraction_coverage > min_fraction_coverage

        return passed, warnings

    def _station_warnings(station, distance_meters):
        warnings = [
            EEWeatherWarning(
                qualified_name="eeweather.exceeds_maximum_distance",
                description=(
                    "Distance from target to weather station is greater"
                    " than the specified km."
                ),
                data={
                    "distance_meters": distance_meters,
                    "max_distance_meters": d,
                    "rank": rank,
                },
            )
            for d in distance_warnings
            if distance_meters > d
        ]

        return warnings

    n_stations_passed = 0
    for station_id, row in candidates.iterrows():
        station = WeatherStation(station_id)
        test_result, warnings = _test_station(station)
        if test_result:
            n_stations_passed += 1
        if n_stations_passed == rank:
            warnings.extend(_station_warnings(station, row.distance_meters))

            return station, warnings

    no_station_warnings = [
        EEWeatherWarning(
            qualified_name="eeweather.no_weather_station_selected",
            description=(
                "No weather station found with the specified rank and"
                " minimum fractional coverage."
            ),
            data={"rank": rank, "min_fraction_coverage": min_fraction_coverage},
        )
    ]

    return None, no_station_warnings
