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
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytz

import requests

from .exceptions import (
    UnrecognizedUSAFIDError,
    DataNotAvailableError,
    TMY3DataNotAvailableError,
    CZ2010DataNotAvailableError,
    NonUTCTimezoneInfoError,
)
from .validation import valid_usaf_id_or_raise
from .warnings import EEWeatherWarning
import eeweather.connections
from eeweather.connections import metadata_db_connection_proxy
import eeweather.mockable
from .sources.ghcnh import DEFAULT_VARIABLES, fetch_ghcnh_hourly

DATA_EXPIRATION_DAYS = 1

__all__ = (
    "WeatherStation",
    "get_ghcn_id",
    "get_isd_station_metadata",
    "get_station_quality",
    "get_station_qualities",
    "get_isd_file_metadata",
    "fetch_hourly_data",
    "get_hourly_data_cache_key",
    "get_tmy3_hourly_temp_data_cache_key",
    "get_cz2010_hourly_temp_data_cache_key",
    "cached_hourly_data_is_expired",
    "validate_hourly_data_cache",
    "validate_tmy3_hourly_temp_data_cache",
    "validate_cz2010_hourly_temp_data_cache",
    "serialize_hourly_data",
    "serialize_tmy3_hourly_temp_data",
    "serialize_cz2010_hourly_temp_data",
    "deserialize_hourly_data",
    "deserialize_tmy3_hourly_temp_data",
    "deserialize_cz2010_hourly_temp_data",
    "read_hourly_data_from_cache",
    "read_tmy3_hourly_temp_data_from_cache",
    "read_cz2010_hourly_temp_data_from_cache",
    "write_hourly_data_to_cache",
    "write_tmy3_hourly_temp_data_to_cache",
    "write_cz2010_hourly_temp_data_to_cache",
    "destroy_cached_hourly_data",
    "destroy_cached_tmy3_hourly_temp_data",
    "destroy_cached_cz2010_hourly_temp_data",
    "load_hourly_data_cached_proxy",
    "load_tmy3_hourly_temp_data_cached_proxy",
    "load_cz2010_hourly_temp_data_cached_proxy",
    "load_data",
    "load_tmy3_hourly_temp_data",
    "load_cz2010_hourly_temp_data",
    "load_cached_hourly_data",
    "load_cached_tmy3_hourly_temp_data",
    "load_cached_cz2010_hourly_temp_data",
)


def _datetime_is_utc(dt):
    orig_tzinfo = dt.tzinfo
    return False if orig_tzinfo is None else dt.utcoffset().seconds == 0


TRAILING_GAP_WARNING_THRESHOLD = timedelta(days=1)
INTERNAL_GAP_WARNING_THRESHOLD = timedelta(days=7)


def _data_gap_warnings(ts, variable):
    """EEWeatherWarnings for requested ranges the returned data does not cover.

    Emitted when the series is entirely empty, when it ends more than
    TRAILING_GAP_WARNING_THRESHOLD before the end of the requested range, or
    when it contains an internal gap longer than INTERNAL_GAP_WARNING_THRESHOLD.
    """
    warnings = []
    if len(ts) == 0:
        return warnings

    if ts.isna().all():
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.no_data_in_requested_range",
                description="No data was available within the requested range.",
                data={
                    "variable": variable,
                    "requested_start": ts.index[0].isoformat(),
                    "requested_end": ts.index[-1].isoformat(),
                },
            )
        )

        return warnings

    last_valid = ts.last_valid_index()
    trailing_gap = ts.index[-1] - last_valid
    if trailing_gap > TRAILING_GAP_WARNING_THRESHOLD:
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.data_truncated",
                description=(
                    "Data ends {} before the end of the requested range.".format(
                        trailing_gap
                    )
                ),
                data={
                    "variable": variable,
                    "last_valid": last_valid.isoformat(),
                    "requested_end": ts.index[-1].isoformat(),
                },
            )
        )

    interior = ts.loc[ts.first_valid_index() : last_valid]
    if len(interior) > 1:
        period = interior.index[1] - interior.index[0]
        is_missing = interior.isna()
        max_gap_periods = int(is_missing.groupby((~is_missing).cumsum()).sum().max())
        max_gap = max_gap_periods * period
        if max_gap > INTERNAL_GAP_WARNING_THRESHOLD:
            warnings.append(
                EEWeatherWarning(
                    qualified_name="eeweather.data_gap",
                    description=(
                        "Data contains an internal gap of {}.".format(max_gap)
                    ),
                    data={
                        "variable": variable,
                        "max_gap_days": max_gap / timedelta(days=1),
                    },
                )
            )

    return warnings


def get_ghcn_id(usaf_id):
    """GHCNh station id mapped to this USAF id."""
    metadata = get_isd_station_metadata(usaf_id)

    return metadata["ghcn_id"]


def fetch_hourly_data(usaf_id, year, variables=DEFAULT_VARIABLES):
    """Fetch one year of GHCNh observations resampled to an hourly frame.

    Raises DataNotAvailableError when the station has no observations at
    all for the year.
    """
    ghcn_id = get_ghcn_id(usaf_id)
    raw = fetch_ghcnh_hourly(ghcn_id, year, variables)
    if len(raw) == 0:
        raise DataNotAvailableError(usaf_id, year)

    # CalTRACK 2.3.3
    df = (
        raw.resample("min")
        .mean()
        .interpolate(method="linear", limit=60, limit_direction="both")
        .resample("h")
        .mean()
    )

    return df


def get_hourly_data_cache_key(usaf_id, year):
    return "ghcnh-hourly-{}-{}".format(usaf_id, year)


def cached_hourly_data_is_expired(usaf_id, year):
    key = get_hourly_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    last_updated = store.key_updated(key)

    return _expired(last_updated, year)


def validate_hourly_data_cache(usaf_id, year):
    key = get_hourly_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    # check for expired data, fail if so
    if cached_hourly_data_is_expired(usaf_id, year):
        store.clear(key)
        return False

    return True


def serialize_hourly_data(df):
    rows = [
        [index.strftime("%Y%m%d%H")] + values
        for index, values in zip(
            df.index, df.astype(object).where(df.notna(), None).values.tolist()
        )
    ]

    return {"columns": list(df.columns), "rows": rows}


def deserialize_hourly_data(data):
    index = pd.to_datetime(
        [row[0] for row in data["rows"]], format="%Y%m%d%H", utc=True
    )
    df = pd.DataFrame(
        [row[1:] for row in data["rows"]],
        index=index,
        columns=data["columns"],
        dtype=float,
    )

    return df.sort_index().resample("h").mean()


def read_hourly_data_from_cache(usaf_id, year):
    key = get_hourly_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    return deserialize_hourly_data(store.retrieve_json(key))


def write_hourly_data_to_cache(usaf_id, year, df):
    key = get_hourly_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    return store.save_json(key, serialize_hourly_data(df))


def destroy_cached_hourly_data(usaf_id, year):
    key = get_hourly_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    return store.clear(key)


def load_hourly_data_cached_proxy(
    usaf_id,
    year,
    variables=DEFAULT_VARIABLES,
    read_from_cache=True,
    write_to_cache=True,
    fetch_from_web=True,
):
    """One year of hourly data, from cache when it covers the request.

    A cache entry serves the request when it is fresh and holds every
    requested variable. Fetches request the union of the requested and
    already-cached variables so a cache refresh never drops columns.
    """
    variables = tuple(variables)
    cached = None
    if validate_hourly_data_cache(usaf_id, year):
        cached = read_hourly_data_from_cache(usaf_id, year)

    cache_covers_request = cached is not None and set(variables) <= set(cached.columns)
    if read_from_cache and cache_covers_request:
        return cached[list(variables)]

    if not fetch_from_web:
        raise DataNotAvailableError(usaf_id, year)

    cached_columns = () if cached is None else tuple(cached.columns)
    fetch_variables = tuple(dict.fromkeys(variables + cached_columns))
    df = fetch_hourly_data(usaf_id, year, fetch_variables)
    if write_to_cache:
        write_hourly_data_to_cache(usaf_id, year, df)

    return df[list(variables)]


def load_data(
    usaf_id,
    start,
    end,
    frequency="hourly",
    variables=DEFAULT_VARIABLES,
    read_from_cache=True,
    write_to_cache=True,
    fetch_from_web=True,
    error_on_missing_years=True,
):
    """Load a station's weather data between two dates (inclusive).

    This is the primary interface for loading observed weather data.

    Parameters
    ----------
    usaf_id : str
        Station USAF id.
    start : datetime.datetime
        The earliest date from which to load data. Must be UTC.
    end : datetime.datetime
        The latest date until which to load data. Must be UTC.
    frequency : str
        ``'hourly'`` or ``'daily'``. Daily values are means of the hourly
        values within each day.
    variables : tuple of str
        GHCNh variable names. Temperatures are degrees Celsius; units for
        other variables follow the GHCNh documentation.
    read_from_cache : bool
        Whether or not to load data from cache.
    write_to_cache : bool
        Whether or not to write newly loaded data to cache.
    fetch_from_web : bool
        Whether or not to fetch data from the web.
    error_on_missing_years : bool
        Whether to raise when data is unavailable for a year in the range,
        or to warn and fill that year with NaN.

    Returns
    -------
    tuple of (pandas.DataFrame, list of EEWeatherWarning)
        One column per requested variable, indexed over the full requested
        range at the requested frequency; periods without data are NaN.
        Warnings describe years with no data and gaps in the returned data.
    """
    # CalTRACK 2.3.3
    if not _datetime_is_utc(start):
        raise NonUTCTimezoneInfoError(start)
    if not _datetime_is_utc(end):
        raise NonUTCTimezoneInfoError(end)

    if frequency == "hourly":
        freq = "h"
    elif frequency == "daily":
        freq = "D"
    else:
        raise ValueError(
            "frequency must be 'hourly' or 'daily', got: {}".format(frequency)
        )

    variables = tuple(variables)
    warnings = []
    data = []
    for year in range(start.year, end.year + 1):
        try:
            data.append(
                load_hourly_data_cached_proxy(
                    usaf_id,
                    year,
                    variables=variables,
                    read_from_cache=read_from_cache,
                    write_to_cache=write_to_cache,
                    fetch_from_web=fetch_from_web,
                )
            )
        except DataNotAvailableError:
            if error_on_missing_years:
                raise
            warnings.append(
                EEWeatherWarning(
                    qualified_name="eeweather.data_not_available",
                    description="Data not available",
                    data={"usaf_id": usaf_id, "year": year},
                )
            )

    if data:
        df = pd.concat(data)
        if frequency == "daily":
            df = df.resample("D").mean()
        df = df[start:end]
    else:
        empty_index = pd.DatetimeIndex([], tz=pytz.UTC)
        df = pd.DataFrame(columns=list(variables), index=empty_index, dtype=float)

    # because start and end dates need to fall exactly on period boundaries
    if frequency == "hourly":
        range_start = datetime(
            start.year, start.month, start.day, start.hour, tzinfo=pytz.UTC
        )
        if range_start < start:
            range_start += timedelta(hours=1)
        range_end = datetime(end.year, end.month, end.day, end.hour, tzinfo=pytz.UTC)
    else:
        range_start = datetime(start.year, start.month, start.day, tzinfo=pytz.UTC)
        if range_start < start:
            range_start += timedelta(days=1)
        range_end = datetime(end.year, end.month, end.day, tzinfo=pytz.UTC)

    # fill in gaps, covering the full requested range even when no data loaded
    df = df.reindex(pd.date_range(range_start, range_end, freq=freq, tz=pytz.UTC))
    for variable in variables:
        warnings.extend(_data_gap_warnings(df[variable], variable))

    return df, warnings


def load_cached_hourly_data(usaf_id):
    """All cached hourly data for a station, or None when none is cached."""
    store = eeweather.connections.key_value_store_proxy.get_store()

    data = [
        read_hourly_data_from_cache(usaf_id, year)
        for year in range(2000, datetime.now().year + 1)
        if store.key_exists(get_hourly_data_cache_key(usaf_id, year))
    ]
    if data == []:
        return None

    return pd.concat(data).resample("h").mean()


def get_isd_station_metadata(usaf_id):
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
      select
        *
      from
        isd_station_metadata
      where
        usaf_id = ?
    """,
        (usaf_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise UnrecognizedUSAFIDError(usaf_id)
    return {col[0]: row[i] for i, col in enumerate(cur.description)}


GHCN_INVENTORY_MONTH_COLUMNS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)


QUALITY_WINDOW_YEARS = 5

# every month of the rating window above these observation counts
HIGH_MONTHLY_OBSERVATIONS = 600
MEDIUM_MONTHLY_OBSERVATIONS = 360


def _quality_rating_window(start, end):
    """Calendar years rating a request: five years ending two years after
    the request's last date, sliding back to end no later than the last
    full year."""
    last_full_year = datetime.now().year - 1
    window_end = min(end.year + 2, last_full_year)
    window_start = window_end - (QUALITY_WINDOW_YEARS - 1)

    return window_start, window_end


def _quality_from_minimum(minimum):
    if minimum > HIGH_MONTHLY_OBSERVATIONS:
        return "high"
    elif minimum > MEDIUM_MONTHLY_OBSERVATIONS:
        return "medium"

    return "low"


def get_station_quality(usaf_id, start, end):
    """Station quality for a request period, from GHCNh observation counts.

    Rates the five calendar years ending two years after the request's
    last date (sliding back so the window ends no later than the last
    full year): every month over 600 observations is high, over 360 is
    medium; anything less, including absent months or years, is low.
    """
    window_start, window_end = _quality_rating_window(start, end)
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
      select year, {}
      from ghcn_inventory
      where usaf_id = ? and year between ? and ?
    """.format(
            ", ".join(GHCN_INVENTORY_MONTH_COLUMNS)
        ),
        (usaf_id, window_start, window_end),
    )
    counts_by_year = {row[0]: row[1:] for row in cur.fetchall()}

    minimum = None
    for year in range(window_start, window_end + 1):
        year_counts = counts_by_year.get(year, (0,) * 12)
        year_minimum = min(year_counts)
        if minimum is None or year_minimum < minimum:
            minimum = year_minimum

    return _quality_from_minimum(minimum)


def get_station_qualities(start, end):
    """Quality for a request period for every station, as a usaf_id-indexed
    Series.

    Same rating as get_station_quality, computed for the whole registry in
    one query.
    """
    window_start, window_end = _quality_rating_window(start, end)
    conn = metadata_db_connection_proxy.get_connection()
    inventory = pd.read_sql_query(
        """
      select usaf_id, year, {}
      from ghcn_inventory
      where year between ? and ?
    """.format(
            ", ".join(GHCN_INVENTORY_MONTH_COLUMNS)
        ),
        conn,
        params=(window_start, window_end),
    )

    months = list(GHCN_INVENTORY_MONTH_COLUMNS)
    year_min = inventory[months].min(axis=1)
    observed_min = year_min.groupby(inventory.usaf_id).min()

    # a station must have a row for every year of the window
    n_years = window_end - window_start + 1
    year_counts = inventory.groupby("usaf_id").year.nunique()
    observed_min = observed_min.where(year_counts >= n_years, 0)

    qualities = pd.Series("low", index=observed_min.index)
    qualities[observed_min > MEDIUM_MONTHLY_OBSERVATIONS] = "medium"
    qualities[observed_min > HIGH_MONTHLY_OBSERVATIONS] = "high"

    return qualities


def get_isd_file_metadata(usaf_id):
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
      select
        *
      from
        isd_file_metadata
      where
        usaf_id = ?
    """,
        (usaf_id,),
    )
    rows = cur.fetchall()
    if rows == []:
        raise UnrecognizedUSAFIDError(usaf_id)
    return [{col[0]: row[i] for i, col in enumerate(cur.description)} for row in rows]


def get_tmy3_station_metadata(usaf_id):
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
      select
        *
      from
        tmy3_station_metadata
      where
        usaf_id = ?
    """,
        (usaf_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise TMY3DataNotAvailableError(usaf_id)
    return {col[0]: row[i] for i, col in enumerate(cur.description)}


def get_cz2010_station_metadata(usaf_id):
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
      select
        *
      from
        cz2010_station_metadata
      where
        usaf_id = ?
    """,
        (usaf_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise CZ2010DataNotAvailableError(usaf_id)
    return {col[0]: row[i] for i, col in enumerate(cur.description)}


def fetch_tmy3_hourly_temp_data(usaf_id):
    url = (
        "https://storage.googleapis.com/openeemeter-public-resources/"
        "tmy3_archive/{}TYA.CSV".format(usaf_id)
    )

    # checks that the station has TMY3 data associated with it.
    tmy3_metadata = get_tmy3_station_metadata(usaf_id)

    return fetch_hourly_normalized_temp_data(usaf_id, url, "TMY3")


def fetch_cz2010_hourly_temp_data(usaf_id):
    url = "https://storage.googleapis.com/oee-cz2010/csv/{}_CZ2010.CSV".format(usaf_id)

    # checks that the station has CZ2010 data associated with it.
    cz2010_metadata = get_cz2010_station_metadata(usaf_id)

    return fetch_hourly_normalized_temp_data(usaf_id, url, "CZ2010")


@eeweather.mockable.mockable()
def request_text(url):  # pragma: no cover
    response = requests.get(url)
    if response.ok:
        return response.text
    else:
        raise RuntimeError("Could not find {}.".format(url))


def fetch_hourly_normalized_temp_data(usaf_id, url, source_name):
    index = pd.date_range("1900-01-01 00:00", "1900-12-31 23:00", freq="h", tz=pytz.UTC)
    ts = pd.Series(None, index=index, dtype=float)

    lines = eeweather.mockable.request_text(url).splitlines()

    utc_offset_str = lines[0].split(",")[3]
    utc_offset = timedelta(seconds=3600 * float(utc_offset_str))

    for line in lines[2:]:
        row = line.split(",")
        month = row[0][0:2]
        day = row[0][3:5]
        hour = int(row[1][0:2]) - 1

        # YYYYMMDDHH
        date_string = "1900{}{}{:02d}".format(month, day, hour)

        dt = datetime.strptime(date_string, "%Y%m%d%H") - utc_offset

        # Only a little redundant to make year 1900 again - matters for
        # first or last few hours of the year depending UTC on offset
        dt = pytz.UTC.localize(dt.replace(year=1900))
        temp_C = float(row[31])

        ts[dt] = temp_C

    return ts


def get_tmy3_hourly_temp_data_cache_key(usaf_id):
    return "tmy3-hourly-{}".format(usaf_id)


def get_cz2010_hourly_temp_data_cache_key(usaf_id):
    return "cz2010-hourly-{}".format(usaf_id)


def _expired(last_updated, year):
    if last_updated is None:
        return True
    expiration_limit = pytz.UTC.localize(
        datetime.now() - timedelta(days=DATA_EXPIRATION_DAYS)
    )
    updated_during_data_year = year == last_updated.year
    return expiration_limit > last_updated and updated_during_data_year


def validate_tmy3_hourly_temp_data_cache(usaf_id):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    return True


def validate_cz2010_hourly_temp_data_cache(usaf_id):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    return True


def _serialize(ts, freq):
    if freq == "h":
        dt_format = "%Y%m%d%H"
    elif freq == "D":
        dt_format = "%Y%m%d"
    else:  # pragma: no cover
        raise ValueError('Unrecognized frequency "{}"'.format(freq))

    return [
        [d.strftime(dt_format), round(temp, 4) if pd.notnull(temp) else None]
        for d, temp in ts.items()
    ]


def serialize_tmy3_hourly_temp_data(ts):
    return _serialize(ts, "h")


def serialize_cz2010_hourly_temp_data(ts):
    return _serialize(ts, "h")


def _deserialize(data, freq):
    if freq == "h":
        dt_format = "%Y%m%d%H"
    elif freq == "D":
        dt_format = "%Y%m%d"
    else:  # pragma: no cover
        raise ValueError('Unrecognized frequency "{}"'.format(freq))

    dates, values = zip(*data)
    index = pd.to_datetime(dates, format=dt_format, utc=True)
    return (
        pd.Series(values, index=index, dtype=float).sort_index().resample(freq).mean()
    )


def deserialize_tmy3_hourly_temp_data(data):
    return _deserialize(data, "h")


def deserialize_cz2010_hourly_temp_data(data):
    return _deserialize(data, "h")


def read_tmy3_hourly_temp_data_from_cache(usaf_id):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_tmy3_hourly_temp_data(store.retrieve_json(key))


def read_cz2010_hourly_temp_data_from_cache(usaf_id):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_cz2010_hourly_temp_data(store.retrieve_json(key))


def write_tmy3_hourly_temp_data_to_cache(usaf_id, ts):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_tmy3_hourly_temp_data(ts))


def write_cz2010_hourly_temp_data_to_cache(usaf_id, ts):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_cz2010_hourly_temp_data(ts))


def destroy_cached_tmy3_hourly_temp_data(usaf_id):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def destroy_cached_cz2010_hourly_temp_data(usaf_id):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def load_tmy3_hourly_temp_data_cached_proxy(
    usaf_id, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # take from cache?
    data_ok = validate_tmy3_hourly_temp_data_cache(usaf_id)

    if not fetch_from_web and not data_ok:
        raise TMY3DataNotAvailableError(usaf_id)
    elif fetch_from_web and (not read_from_cache or not data_ok):
        # need to actually fetch the data
        ts = fetch_tmy3_hourly_temp_data(usaf_id)
        if write_to_cache:
            write_tmy3_hourly_temp_data_to_cache(usaf_id, ts)
    else:
        # read_from_cache=True and data_ok=True
        ts = read_tmy3_hourly_temp_data_from_cache(usaf_id)
    return ts


def load_cz2010_hourly_temp_data_cached_proxy(
    usaf_id, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # take from cache?
    data_ok = validate_cz2010_hourly_temp_data_cache(usaf_id)

    if not fetch_from_web and not data_ok:
        raise CZ2010DataNotAvailableError(usaf_id)
    elif fetch_from_web and (not read_from_cache or not data_ok):
        # need to actually fetch the data
        ts = fetch_cz2010_hourly_temp_data(usaf_id)
        if write_to_cache:
            write_cz2010_hourly_temp_data_to_cache(usaf_id, ts)
    else:
        # read_from_cache=True and data_ok=True
        ts = read_cz2010_hourly_temp_data_from_cache(usaf_id)
    return ts


def load_tmy3_hourly_temp_data(
    usaf_id, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # CalTRACK 2.3.3
    if not _datetime_is_utc(start):
        raise NonUTCTimezoneInfoError(start)
    if not _datetime_is_utc(end):
        raise NonUTCTimezoneInfoError(end)
    single_year_data = load_tmy3_hourly_temp_data_cached_proxy(
        usaf_id,
        read_from_cache=read_from_cache,
        write_to_cache=write_to_cache,
        fetch_from_web=fetch_from_web,
    )

    # dealing with year replacement
    data = []
    for year in range(start.year, end.year + 1):
        single_year_index = single_year_data.index.map(lambda t: t.replace(year=year))

        data.append(pd.Series(single_year_data.values, index=single_year_index))

    # get raw data
    ts = pd.concat(data).resample("h").mean()

    # whittle down
    ts = ts[start:end]

    # fill in gaps
    ts = ts.reindex(pd.date_range(start, end, freq="h", tz=pytz.UTC))
    return ts


def load_cz2010_hourly_temp_data(
    usaf_id, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # CalTRACK 2.3.3
    if not _datetime_is_utc(start):
        raise NonUTCTimezoneInfoError(start)
    if not _datetime_is_utc(end):
        raise NonUTCTimezoneInfoError(end)
    single_year_data = load_cz2010_hourly_temp_data_cached_proxy(
        usaf_id,
        read_from_cache=read_from_cache,
        write_to_cache=write_to_cache,
        fetch_from_web=fetch_from_web,
    )

    # dealing with year replacement
    data = []
    for year in range(start.year, end.year + 1):
        single_year_index = single_year_data.index.map(lambda t: t.replace(year=year))

        data.append(pd.Series(single_year_data.values, index=single_year_index))

    # get raw data
    ts = pd.concat(data).resample("h").mean()

    # whittle down
    ts = ts[start:end]

    # fill in gaps
    ts = ts.reindex(pd.date_range(start, end, freq="h", tz=pytz.UTC))
    return ts


def load_cached_tmy3_hourly_temp_data(usaf_id):
    store = eeweather.connections.key_value_store_proxy.get_store()

    if store.key_exists(get_tmy3_hourly_temp_data_cache_key(usaf_id)):
        return read_tmy3_hourly_temp_data_from_cache(usaf_id)
    else:
        return None


def load_cached_cz2010_hourly_temp_data(usaf_id):
    store = eeweather.connections.key_value_store_proxy.get_store()

    if store.key_exists(get_cz2010_hourly_temp_data_cache_key(usaf_id)):
        return read_cz2010_hourly_temp_data_from_cache(usaf_id)
    else:
        return None


class WeatherStation(object):
    """A representation of a weather station.

    Contains data about a particular weather station, as well as methods to
    pull data for this station. Stations are keyed by their ISD-registry
    USAF id; observed data is served from the station's GHCNh record.

    Parameters
    ----------
    usaf_id : str
        Station USAF ID
    load_metatdata : bool, optional
        Whether or not to auto-load metadata for this station

    Attributes
    ----------
    usaf_id : str
        Station USAF ID
    ghcn_id : str
        GHCNh station id observed data is fetched with
    iecc_climate_zone : str
        IECC Climate Zone
    iecc_moisture_regime : str
        IECC Moisture Regime
    ba_climate_zone : str
        Building America Climate Zone
    ca_climate_zone : str
        California Building Climate Zone
    elevation : float
        elevation of station
    latitude : float
        latitude of station
    longitude : float
        longitude of station
    coords : tuple of (float, float)
        lat/long coordinates of station
    name : str
        name of the station
    quality : str
        "high", "medium", "low"
    wban_ids : list of str
        list of WBAN IDs, or "99999" which have been used to identify the station.
    recent_wban_id = None
        WBAN ID most recently used to identify the station.
    climate_zones = {}
        dict of all climate zones.
    """

    def __init__(self, usaf_id, load_metadata=True):
        self.usaf_id = usaf_id

        if load_metadata:
            self._load_metadata()
        else:
            valid_usaf_id_or_raise(usaf_id)
            self.iecc_climate_zone = None
            self.iecc_moisture_regime = None
            self.ba_climate_zone = None
            self.ca_climate_zone = None
            self.elevation = None
            self.latitude = None
            self.longitude = None
            self.coords = None
            self.name = None
            self.quality = None
            self.wban_ids = None
            self.recent_wban_id = None
            self.ghcn_id = None
            self.ghcn_first_year = None
            self.ghcn_last_year = None
            self.climate_zones = {}

    def __str__(self):
        return self.usaf_id

    def __repr__(self):
        return "WeatherStation('{}')".format(self.usaf_id)

    def _load_metadata(self):
        metadata = get_isd_station_metadata(self.usaf_id)

        def _float_or_none(field):
            value = metadata.get(field)
            return None if value is None else float(value)

        self.iecc_climate_zone = metadata.get("iecc_climate_zone")
        self.iecc_moisture_regime = metadata.get("iecc_moisture_regime")
        self.ba_climate_zone = metadata.get("ba_climate_zone")
        self.ca_climate_zone = metadata.get("ca_climate_zone")
        self.icao_code = metadata.get("icao_code")
        self.elevation = _float_or_none("elevation")  # meters
        self.latitude = _float_or_none("latitude")
        self.longitude = _float_or_none("longitude")
        self.coords = (self.latitude, self.longitude)
        self.name = metadata.get("name")
        self.quality = metadata.get("quality")
        self.wban_ids = metadata.get("wban_ids", "").split(",")
        self.recent_wban_id = metadata.get("recent_wban_id")
        self.ghcn_id = metadata.get("ghcn_id")
        self.ghcn_first_year = metadata.get("ghcn_first_year")
        self.ghcn_last_year = metadata.get("ghcn_last_year")
        self.climate_zones = {
            "iecc_climate_zone": metadata.get("iecc_climate_zone"),
            "iecc_moisture_regime": metadata.get("iecc_moisture_regime"),
            "ba_climate_zone": metadata.get("ba_climate_zone"),
            "ca_climate_zone": metadata.get("ca_climate_zone"),
        }

    def json(self):
        """Return a JSON-serializeable object containing station metadata."""
        return {
            "elevation": self.elevation,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "icao_code": self.icao_code,
            "name": self.name,
            "quality": self.quality,
            "wban_ids": self.wban_ids,
            "recent_wban_id": self.recent_wban_id,
            "ghcn_id": self.ghcn_id,
            "ghcn_first_year": self.ghcn_first_year,
            "ghcn_last_year": self.ghcn_last_year,
            "climate_zones": {
                "iecc_climate_zone": self.iecc_climate_zone,
                "iecc_moisture_regime": self.iecc_moisture_regime,
                "ba_climate_zone": self.ba_climate_zone,
                "ca_climate_zone": self.ca_climate_zone,
            },
        }

    def load_data(
        self,
        start,
        end,
        frequency="hourly",
        variables=DEFAULT_VARIABLES,
        read_from_cache=True,
        write_to_cache=True,
        fetch_from_web=True,
        error_on_missing_years=True,
    ):
        """Load this station's weather data between two dates (inclusive).

        This is the primary interface for loading observed weather data.

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data. Must be UTC.
        end : datetime.datetime
            The latest date until which to load data. Must be UTC.
        frequency : str
            ``'hourly'`` or ``'daily'``. Daily values are means of the
            hourly values within each day.
        variables : tuple of str
            GHCNh variable names. Temperatures are degrees Celsius; units
            for other variables follow the GHCNh documentation.
        read_from_cache : bool
            Whether or not to load data from cache.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        fetch_from_web : bool
            Whether or not to fetch data from the web.
        error_on_missing_years : bool
            Whether to raise when data is unavailable for a year in the
            range, or to warn and fill that year with NaN.

        Returns
        -------
        tuple of (pandas.DataFrame, list of EEWeatherWarning)
            One column per requested variable, indexed over the full
            requested range at the requested frequency; periods without
            data are NaN.
        """
        return load_data(
            self.usaf_id,
            start,
            end,
            frequency=frequency,
            variables=variables,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
            error_on_missing_years=error_on_missing_years,
        )

    def get_quality(self, start, end):
        """Station quality over a period, from GHCNh observation counts."""
        return get_station_quality(self.usaf_id, start, end)

    def load_cached_data(self):
        """Load all cached hourly data for this station."""
        return load_cached_hourly_data(self.usaf_id)

    def destroy_cached_hourly_data(self, year):
        """Remove cached hourly data for this station for the given year."""
        return destroy_cached_hourly_data(self.usaf_id, year)

    def get_isd_file_metadata(self):
        """Get raw file metadata for the station."""
        return get_isd_file_metadata(self.usaf_id)

    # fetch raw data
    # fetch raw data then frequency-normalize
    def fetch_tmy3_hourly_temp_data(self):
        """Pull hourly TMY3 temperature hourly time series directly from NREL."""
        return fetch_tmy3_hourly_temp_data(self.usaf_id)

    def fetch_cz2010_hourly_temp_data(self):
        """Pull hourly CZ2010 temperature hourly time series from URL."""
        return fetch_cz2010_hourly_temp_data(self.usaf_id)

    # get key-value store key
    def get_tmy3_hourly_temp_data_cache_key(self):
        """Get key used to cache TMY3 weather-normalized temperature data."""
        return get_tmy3_hourly_temp_data_cache_key(self.usaf_id)

    def get_cz2010_hourly_temp_data_cache_key(self):
        """Get key used to cache CZ2010 weather-normalized temperature data."""
        return get_cz2010_hourly_temp_data_cache_key(self.usaf_id)

    # is cached data expired? boolean. true if expired or not in cache
    # check if data is available and delete data in the cache if it's expired
    def validate_tmy3_hourly_temp_data_cache(self):
        """Check if TMY3 data exists in cache."""
        return validate_tmy3_hourly_temp_data_cache(self.usaf_id)

    def validate_cz2010_hourly_temp_data_cache(self):
        """Check if CZ2010 data exists in cache."""
        return validate_cz2010_hourly_temp_data_cache(self.usaf_id)

    # pandas time series to json
    def serialize_tmy3_hourly_temp_data(self, ts):
        """Serialize hourly TMY3 pandas time series as JSON for caching."""
        return serialize_tmy3_hourly_temp_data(ts)

    def serialize_cz2010_hourly_temp_data(self, ts):
        """Serialize hourly CZ2010 pandas time series as JSON for caching."""
        return serialize_cz2010_hourly_temp_data(ts)

    # json to pandas time series
    def deserialize_tmy3_hourly_temp_data(self, data):
        """Deserialize JSON representation of hourly TMY3 into pandas time series."""
        return deserialize_tmy3_hourly_temp_data(data)

    def deserialize_cz2010_hourly_temp_data(self, data):
        """Deserialize JSON representation of hourly CZ2010 into pandas time series."""
        return deserialize_cz2010_hourly_temp_data(data)

    # return pandas time series of data from cache
    def read_tmy3_hourly_temp_data_from_cache(self):
        """Get cached version of hourly TMY3 temperature data."""
        return read_tmy3_hourly_temp_data_from_cache(self.usaf_id)

    def read_cz2010_hourly_temp_data_from_cache(self):
        """Get cached version of hourly TMY3 temperature data."""
        return read_cz2010_hourly_temp_data_from_cache(self.usaf_id)

    # write pandas time series of data to cache for a particular year
    def write_tmy3_hourly_temp_data_to_cache(self, ts):
        """Write hourly TMY3 temperature data to cache for given year."""
        return write_tmy3_hourly_temp_data_to_cache(self.usaf_id, ts)

    def write_cz2010_hourly_temp_data_to_cache(self, ts):
        """Write hourly CZ2010 temperature data to cache for given year."""
        return write_cz2010_hourly_temp_data_to_cache(self.usaf_id, ts)

    # delete cached data for a particular year
    def destroy_cached_tmy3_hourly_temp_data(self):
        """Remove cached hourly TMY3 temperature data to cache."""
        return destroy_cached_tmy3_hourly_temp_data(self.usaf_id)

    def destroy_cached_cz2010_hourly_temp_data(self):
        """Remove cached hourly CZ2010 temperature data to cache."""
        return destroy_cached_cz2010_hourly_temp_data(self.usaf_id)

    # load data either from cache if valid or directly from source
    def load_tmy3_hourly_temp_data_cached_proxy(self, fetch_from_web=True):
        """Load hourly TMY3 temperature data from cache, or if it is expired or hadn't been cached, fetch from NREL."""
        return load_tmy3_hourly_temp_data_cached_proxy(self.usaf_id, fetch_from_web)

    def load_cz2010_hourly_temp_data_cached_proxy(self, fetch_from_web=True):
        """Load hourly CZ2010 temperature data from cache, or if it is expired or hadn't been cached, fetch from URL."""
        return load_cz2010_hourly_temp_data_cached_proxy(self.usaf_id, fetch_from_web)

    # main interface: load data from start date to end date
    def load_tmy3_hourly_temp_data(
        self, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
    ):
        """Load hourly TMY3 temperature data from start date to end date (inclusive).

        This is the primary convenience method for loading hourly TMY3 temperature data.

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data.
        end : datetime.datetime
            The latest date until which to load data.
        read_from_cache : bool
            Whether or not to load data from cache.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        fetch_from_web : bool
            Whether or not to fetch data from ftp.
        """
        return load_tmy3_hourly_temp_data(
            self.usaf_id,
            start,
            end,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )

    def load_cz2010_hourly_temp_data(
        self, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
    ):
        """Load hourly CZ2010 temperature data from start date to end date (inclusive).

        This is the primary convenience method for loading hourly CZ2010 temperature data.

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data.
        end : datetime.datetime
            The latest date until which to load data.
        read_from_cache : bool
            Whether or not to load data from cache.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        fetch_from_web : bool
            Whether or not to fetch data from ftp.
        """
        return load_cz2010_hourly_temp_data(
            self.usaf_id,
            start,
            end,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )

    # load all cached data for this station
    def load_cached_tmy3_hourly_temp_data(self):
        """Load all cached hourly TMY3 temperature data (the year is set to 1900)"""
        return load_cached_tmy3_hourly_temp_data(self.usaf_id)

    def load_cached_cz2010_hourly_temp_data(self):
        """Load all cached hourly TMY3 temperature data (the year is set to 1900)"""
        return load_cached_cz2010_hourly_temp_data(self.usaf_id)
