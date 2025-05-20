#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Copyright 2018-2023 OpenEEmeter contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""
import pandas as pd
import numpy as np
import pyproj

import eeweather.mockable
from .exceptions import ISDDataNotAvailableError
from .connections import metadata_db_connection_proxy
from .geo import get_lat_long_climate_zones
from .stations import ISDStation
from .utils import lazy_property
from .warnings import EEWeatherWarning

__all__ = ("rank_stations", "combine_ranked_stations", "select_station")


class CachedData(object):
    @lazy_property
    def all_station_metadata(self):
        conn = metadata_db_connection_proxy.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
          select
            isd.usaf_id
            , isd.latitude
            , isd.longitude
            , isd.iecc_climate_zone
            , isd.iecc_moisture_regime
            , isd.ba_climate_zone
            , isd.ca_climate_zone
            , isd.quality as rough_quality
            , isd.elevation
            , isd.state
            , tmy3.class as tmy3_class
            , tmy3.usaf_id is not null as is_tmy3
            , cz2010.usaf_id is not null as is_cz2010
          from
            isd_station_metadata as isd
            left join cz2010_station_metadata as cz2010 on
              isd.usaf_id = cz2010.usaf_id
            left join tmy3_station_metadata as tmy3 on
              isd.usaf_id = tmy3.usaf_id
          order by
            isd.usaf_id
        """
        )

        df = pd.DataFrame(
            [
                {col[0]: val for col, val in zip(cur.description, row)}
                for row in cur.fetchall()
            ],
            columns=[
                "usaf_id",
                "latitude",
                "longitude",
                "iecc_climate_zone",
                "iecc_moisture_regime",
                "ba_climate_zone",
                "ca_climate_zone",
                "rough_quality",
                "elevation",
                "state",
                "tmy3_class",
                "is_tmy3",
                "is_cz2010",
            ],
        ).set_index("usaf_id")

        df["latitude"] = df.latitude.astype(float)
        df["longitude"] = df.longitude.astype(float)
        df["elevation"] = df.elevation.astype(float)
        df["is_tmy3"] = df.is_tmy3.astype(bool)
        df["is_cz2010"] = df.is_cz2010.astype(bool)
        return df


cached_data = CachedData()


def _combine_filters(filters, index):
    combined_filters = pd.Series(True, index=index)
    for f in filters:
        combined_filters &= f
    return combined_filters


def rank_stations(
    site_latitude,
    site_longitude,
    site_state=None,
    site_elevation=None,
    match_iecc_climate_zone=False,
    match_iecc_moisture_regime=False,
    match_ba_climate_zone=False,
    match_ca_climate_zone=False,
    match_state=False,
    minimum_quality=None,
    minimum_tmy3_class=None,
    max_distance_meters=None,
    max_difference_elevation_meters=None,
    is_tmy3=None,
    is_cz2010=None,
):
    """Get a ranked, filtered set of candidate weather stations and metadata
    for a particular site.

    Parameters
    ----------
    site_latitude : float
        Latitude of target site for which to find candidate weather stations.
    site_longitude : float
        Longitude of target site for which to find candidate weather stations.
    site_state : str, 2 letter abbreviation
        US state of target site, used optionally to filter potential candidate
        weather stations. Ignored unless ``match_state=True``.
    site_elevation : float
        Elevation of target site in meters, used optionally to filter potential
        candidate weather stations. Ignored unless
        ``max_difference_elevation_meters`` is set.
    match_iecc_climate_zone : bool
        If ``True``, filter candidate weather stations to those
        matching the IECC climate zone of the target site.
    match_iecc_moisture_regime : bool
        If ``True``, filter candidate weather stations to those
        matching the IECC moisture regime of the target site.
    match_ca_climate_zone : bool
        If ``True``, filter candidate weather stations to those
        matching the CA climate zone of the target site.
    match_ba_climate_zone : bool
        If ``True``, filter candidate weather stations to those
        matching the Building America climate zone of the target site.
    match_state : bool
        If ``True``, filter candidate weather stations to those
        matching the US state of the target site, as specified by
        ``site_state=True``.
    minimum_quality : str, ``'high'``, ``'medium'``, ``'low'``
        If given, filter candidate weather stations to those meeting or
        exceeding the given quality, as summarized by the frequency and
        availability of observations in the NOAA Integrated Surface Database.
    minimum_tmy3_class : str, ``'I'``, ``'II'``, ``'III'``
        If given, filter candidate weather stations to those meeting or
        exceeding the given class, as reported in the NREL TMY3 metadata.
    max_distance_meters : float
        If given, filter candidate weather stations to those within the
        ``max_distance_meters`` of the target site location.
    max_difference_elevation_meters : float
        If given, filter candidate weather stations to those with elevations
        within ``max_difference_elevation_meters`` of the target site elevation.
    is_tmy3 : bool
        If given, filter candidate weather stations to those for which TMY3
        normal year temperature data is available.
    is_cz2010 : bool
        If given, filter candidate weather stations to those for which CZ2010
        normal year temperature data is available.

    Returns
    -------
    ranked_filtered_candidates : :any:`pandas.DataFrame`
        Index is ``usaf_id``.  Each row contains a potential weather station
        match and metadata. Contains the following columns:

        - ``rank``: Rank of weather station match for the target site.
        - ``distance_meters``: Distance from target site to weather station site.
        - ``latitude``: Latitude of weather station site.
        - ``longitude``: Longitude of weather station site.
        - ``iecc_climate_zone``: IECC Climate Zone ID (1-8)
        - ``iecc_moisture_regime``: IECC Moisture Regime ID (A-C)
        - ``ba_climate_zone``: Building America climate zone name
        - ``ca_climate_zone``: Califoria climate zone number
        - ``rough_quality``: Approximate measure of frequency of ISD
          observations data at weather station.
        - ``elevation``: Elevation of weather station site, if available.
        - ``state``: US state of weather station site, if applicable.
        - ``tmy3_class``: Weather station class as reported by NREL TMY3, if
          available
        - ``is_tmy3``: Weather station has associated TMY3 data.
        - ``is_cz2010``: Weather station has associated CZ2010 data.
        - ``difference_elevation_meters``: Absolute difference in meters
          between target site elevation and weather station elevation, if
          available.

    """
    candidates = cached_data.all_station_metadata.copy()

    # compute distances
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
    distance_meters = pd.Series(dists, index=candidates_defined_lat_long.index).reindex(
        candidates.index
    )
    candidates["distance_meters"] = distance_meters

    if site_elevation is not None:
        difference_elevation_meters = (candidates.elevation - site_elevation).abs()
    else:
        difference_elevation_meters = None
    candidates["difference_elevation_meters"] = difference_elevation_meters

    site_climate_zones = get_lat_long_climate_zones(site_latitude, site_longitude)
    site_iecc_climate_zone = site_climate_zones["iecc_climate_zone"]
    site_iecc_moisture_regime = site_climate_zones["iecc_moisture_regime"]
    site_ca_climate_zone = site_climate_zones["ca_climate_zone"]
    site_ba_climate_zone = site_climate_zones["ba_climate_zone"]

    # create filters
    filters = []

    if match_iecc_climate_zone:
        if site_iecc_climate_zone is None:
            filters.append(candidates.iecc_climate_zone.isnull())
        else:
            filters.append(candidates.iecc_climate_zone == site_iecc_climate_zone)
    if match_iecc_moisture_regime:
        if site_iecc_moisture_regime is None:
            filters.append(candidates.iecc_moisture_regime.isnull())
        else:
            filters.append(candidates.iecc_moisture_regime == site_iecc_moisture_regime)
    if match_ba_climate_zone:
        if site_ba_climate_zone is None:
            filters.append(candidates.ba_climate_zone.isnull())
        else:
            filters.append(candidates.ba_climate_zone == site_ba_climate_zone)
    if match_ca_climate_zone:
        if site_ca_climate_zone is None:
            filters.append(candidates.ca_climate_zone.isnull())
        else:
            filters.append(candidates.ca_climate_zone == site_ca_climate_zone)

    if match_state:
        if site_state is None:
            filters.append(candidates.state.isnull())
        else:
            filters.append(candidates.state == site_state)

    if is_tmy3 is not None:
        filters.append(candidates.is_tmy3.isin([is_tmy3]))
    if is_cz2010 is not None:
        filters.append(candidates.is_cz2010.isin([is_cz2010]))

    if minimum_quality == "low":
        filters.append(candidates.rough_quality.isin(["high", "medium", "low"]))
    elif minimum_quality == "medium":
        filters.append(candidates.rough_quality.isin(["high", "medium"]))
    elif minimum_quality == "high":
        filters.append(candidates.rough_quality.isin(["high"]))

    if minimum_tmy3_class == "III":
        filters.append(candidates.tmy3_class.isin(["I", "II", "III"]))
    elif minimum_tmy3_class == "II":
        filters.append(candidates.tmy3_class.isin(["I", "II"]))
    elif minimum_tmy3_class == "I":
        filters.append(candidates.tmy3_class.isin(["I"]))

    if max_distance_meters is not None:
        filters.append(candidates.distance_meters <= max_distance_meters)

    if max_difference_elevation_meters is not None and site_elevation is not None:
        filters.append(
            candidates.difference_elevation_meters <= max_difference_elevation_meters
        )

    combined_filters = _combine_filters(filters, candidates.index)
    filtered_candidates = candidates[combined_filters]
    ranked_filtered_candidates = filtered_candidates.sort_values(by=["distance_meters"])

    # add rank column
    ranks = range(1, 1 + len(ranked_filtered_candidates))
    ranked_filtered_candidates.insert(0, "rank", ranks)

    return ranked_filtered_candidates[
        [
            "rank",
            "distance_meters",
            "latitude",
            "longitude",
            "iecc_climate_zone",
            "iecc_moisture_regime",
            "ba_climate_zone",
            "ca_climate_zone",
            "rough_quality",
            "elevation",
            "state",
            "tmy3_class",
            "is_tmy3",
            "is_cz2010",
            "difference_elevation_meters",
        ]
    ]


def combine_ranked_stations(rankings):
    """Combine :any:`pandas.DataFrame` s of candidate weather stations to form
    a hybrid ranking dataframe.

    Parameters
    ----------
    rankings : list of :any:`pandas.DataFrame`
        Dataframes of ranked weather station candidates and metadata.
        All ranking dataframes should have the same columns and must be
        sorted by rank.

    Returns
    -------
    ranked_filtered_candidates : :any:`pandas.DataFrame`
        Dataframe has a rank column and the same columns given in the source
        dataframes.
    """

    if len(rankings) == 0:
        raise ValueError("Requires at least one ranking.")

    combined_ranking = rankings[0]
    for ranking in rankings[1:]:
        filtered_ranking = ranking[~ranking.index.isin(combined_ranking.index)]
        combined_ranking = pd.concat([combined_ranking, filtered_ranking])

    combined_ranking["rank"] = range(1, 1 + len(combined_ranking))
    return combined_ranking


@eeweather.mockable.mockable()
def load_isd_hourly_temp_data(
    station, start_date, end_date, fetch_from_web
):  # pragma: no cover
    return station.load_isd_hourly_temp_data(
        start_date, end_date, fetch_from_web=fetch_from_web
    )


def select_station(
    candidates,
    coverage_range=None,
    min_fraction_coverage=0.9,
    distance_warnings=(50000, 200000),
    rank=1,
    fetch_from_web=True,
):
    """Select a station from a list of candidates that meets given data
    quality criteria.

    Parameters
    ----------
    candidates : :any:`pandas.DataFrame`
        A dataframe of the form given by :any:`eeweather.rank_stations` or
        :any:`eeweather.combine_ranked_stations`, specifically having at least
        an index with ``usaf_id`` values and the column ``distance_meters``.

    Returns
    -------
    isd_station, warnings : tuple of (:any:`eeweather.ISDStation`, list of str)
        A qualified weather station. ``None`` if no station meets criteria.
    """

    def _test_station(station):
        if coverage_range is None:
            return True, []
        else:
            start_date, end_date = coverage_range
            try:
                tempC, warnings = eeweather.mockable.load_isd_hourly_temp_data(
                    station, start_date, end_date, fetch_from_web
                )
            except ISDDataNotAvailableError:
                return False, []  # reject

            # TODO(philngo): also need to incorporate within-day limits
            if len(tempC) > 0:
                fraction_coverage = tempC.notnull().sum() / float(len(tempC))
                return (fraction_coverage > min_fraction_coverage), warnings
            else:
                return False, []  # reject

    def _station_warnings(station, distance_meters):
        return [
            EEWeatherWarning(
                qualified_name="eeweather.exceeds_maximum_distance",
                description=(
                    "Distance from target to weather station is greater"
                    "than the specified km."
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

    n_stations_passed = 0
    for usaf_id, row in candidates.iterrows():
        station = ISDStation(usaf_id)
        test_result, warnings = _test_station(station)
        if test_result:
            n_stations_passed += 1
        if n_stations_passed == rank:
            if not warnings:
                warnings = []
            warnings.extend(_station_warnings(station, row.distance_meters))
            return station, warnings

    no_station_warning = EEWeatherWarning(
        qualified_name="eeweather.no_weather_station_selected",
        description=(
            "No weather station found with the specified rank and"
            " minimum fracitional coverage."
        ),
        data={"rank": rank, "min_fraction_coverage": min_fraction_coverage},
    )
    return None, [no_station_warning]
