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
import gzip
import pandas as pd
import pytz

# this import allows monkeypatching noaa_ftp_connection_proxy in tests because
# the fully qualified package path name is preserved
import requests

from .exceptions import (
    UnrecognizedUSAFIDError,
    ISDDataNotAvailableError,
    GSODDataNotAvailableError,
    TMY3DataNotAvailableError,
    CZ2010DataNotAvailableError,
    NonUTCTimezoneInfoError,
)
from .validation import valid_usaf_id_or_raise
from .warnings import EEWeatherWarning
import eeweather.connections
from eeweather.connections import metadata_db_connection_proxy
import eeweather.mockable
import eeweather.access_api

DATA_EXPIRATION_DAYS = 1

__all__ = (
    "ISDStation",
    "get_isd_filenames",
    "get_gsod_filenames",
    "get_isd_station_metadata",
    "get_isd_file_metadata",
    "get_isd_raw_temp_data",  # Not currently written
    "get_isd_hourly_temp_data",  # Not currently written
    "get_isd_daily_temp_data",  # Not currently written
    "get_gsod_raw_temp_data",  # Not currently written
    "get_gsod_daily_temp_data",  # Not currently written
    "get_isd_hourly_temp_data_cache_key",
    "get_isd_daily_temp_data_cache_key",
    "get_gsod_daily_temp_data_cache_key",
    "get_tmy3_hourly_temp_data_cache_key",
    "get_cz2010_hourly_temp_data_cache_key",
    "cached_isd_hourly_temp_data_is_expired",
    "cached_isd_daily_temp_data_is_expired",
    "cached_gsod_daily_temp_data_is_expired",
    "validate_isd_hourly_temp_data_cache",
    "validate_isd_daily_temp_data_cache",
    "validate_gsod_daily_temp_data_cache",
    "validate_tmy3_hourly_temp_data_cache",
    "validate_cz2010_hourly_temp_data_cache",
    "serialize_isd_hourly_temp_data",
    "serialize_isd_daily_temp_data",
    "serialize_gsod_daily_temp_data",
    "serialize_tmy3_hourly_temp_data",
    "serialize_cz2010_hourly_temp_data",
    "deserialize_isd_hourly_temp_data",
    "deserialize_isd_daily_temp_data",
    "deserialize_gsod_daily_temp_data",
    "deserialize_tmy3_daily_temp_data",
    "deserialize_cz2010_daily_temp_data",
    "read_isd_hourly_temp_data_from_cache",
    "read_isd_daily_temp_data_from_cache",
    "read_gsod_daily_temp_data_from_cache",
    "read_tmy3_hourly_temp_data_from_cache",
    "read_cz2010_hourly_temp_data_from_cache",
    "write_isd_hourly_temp_data_to_cache",
    "write_isd_daily_temp_data_to_cache",
    "write_gsod_daily_temp_data_to_cache",
    "write_tmy3_hourly_temp_data_to_cache",
    "write_cz2010_hourly_temp_data_to_cache",
    "destroy_cached_isd_hourly_temp_data",
    "destroy_cached_isd_daily_temp_data",
    "destroy_cached_gsod_daily_temp_data",
    "destroy_cached_tmy3_hourly_temp_data",
    "destroy_cached_cz2010_hourly_temp_data",
    "load_isd_hourly_temp_data_cached_proxy",
    "load_isd_daily_temp_data_cached_proxy",
    "load_gsod_daily_temp_data_cached_proxy",
    "load_tmy3_hourly_temp_data_cached_proxy",
    "load_cz2010_hourly_temp_data_cached_proxy",
    "load_isd_hourly_temp_data",
    "load_isd_daily_temp_data",
    "load_gsod_daily_temp_data",
    "load_tmy3_hourly_temp_data",
    "load_cz2010_hourly_temp_data",
    "load_cached_isd_hourly_temp_data",
    "load_cached_isd_daily_temp_data",
    "load_cached_gsod_daily_temp_data",
    "load_cached_tmy3_hourly_temp_data",
    "load_cached_cz2010_hourly_temp_data",
)


def _datetime_is_utc(dt):
    orig_tzinfo = dt.tzinfo
    return False if orig_tzinfo is None else dt.utcoffset().seconds == 0


def get_isd_filenames(usaf_id, target_year=None, filename_format=None, with_host=False):
    valid_usaf_id_or_raise(usaf_id)
    if filename_format is None:
        filename_format = "/pub/data/noaa/{year}/{usaf_id}-{wban_id}-{year}.gz"
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()

    if target_year is None:
        # all years
        cur.execute(
            """
          select
            wban_id
            , year
          from
            isd_file_metadata
          where
            usaf_id = ?
          order by
            year
        """,
            (usaf_id,),
        )
    else:
        # single year
        cur.execute(
            """
          select
            wban_id
            , year
          from
            isd_file_metadata
          where
            usaf_id = ? and year = ?
        """,
            (usaf_id, target_year),
        )

    filenames = []
    for wban_id, year in cur.fetchall():
        filenames.append(
            filename_format.format(usaf_id=usaf_id, wban_id=wban_id, year=year)
        )

    if len(filenames) == 0 and target_year is not None:
        # fallback - use most recent wban id
        cur.execute(
            """
          select
            recent_wban_id
          from
            isd_station_metadata
          where
            usaf_id = ?
        """,
            (usaf_id,),
        )
        row = cur.fetchone()
        if row is not None:
            filenames.append(
                filename_format.format(
                    usaf_id=usaf_id, wban_id=row[0], year=target_year
                )
            )

    if with_host:
        filenames = ["ftp://ftp.ncei.noaa.gov{}".format(f) for f in filenames]

    return filenames


def get_gsod_filenames(usaf_id, year=None, with_host=False):
    filename_format = "/pub/data/gsod/{year}/{usaf_id}-{wban_id}-{year}.op.gz"
    return get_isd_filenames(
        usaf_id, year, filename_format=filename_format, with_host=with_host
    )


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


def fetch_isd_raw_temp_data_old(usaf_id, year):
    # possible locations of this data, errors if station is not recognized
    filenames = get_isd_filenames(usaf_id, year)

    data = []
    for filename in filenames:
        # using fully-qualified name facilitates monkeypatching
        gzipped = eeweather.connections.noaa_ftp_connection_proxy.read_file_as_bytes(
            filename
        )

        if gzipped is not None:
            f = gzip.GzipFile(fileobj=gzipped)
            for line in f.readlines():
                if line[87:92].decode("utf-8") == "+9999":
                    tempC = float("nan")
                else:
                    tempC = float(line[87:92]) / 10.0
                date_str = line[15:27].decode("utf-8")
                dt = pytz.UTC.localize(datetime.strptime(date_str, "%Y%m%d%H%M"))
                data.append([dt, tempC])
            gzipped.close()

    if data == []:
        raise ISDDataNotAvailableError(usaf_id, year)

    dates, temps = zip(*sorted(data))
    ts = pd.Series(temps, index=dates)
    ts = ts.groupby(ts.index).mean()
    return ts


def fetch_isd_raw_temp_data(usaf_id, year):
    filenames = get_isd_filenames(usaf_id, year)

    file_parse_results = [eeweather.access_api.FileParseResult.from_file_path(file_name) for file_name in filenames]

    data = []
    for file_parse_result in file_parse_results:
        resp_data = eeweather.access_api.make_api_request(
            dataset_type=file_parse_result.dataset_type,
            usaf_id=file_parse_result.usaf_id,
            wban_id=file_parse_result.wban_id,
            year=file_parse_result.year
        )
        data.extend(resp_data)

    if data == []:
        raise ISDDataNotAvailableError(usaf_id, year)

    dates, temps = zip(*sorted(data))
    ts = pd.Series(temps, index=dates)
    ts = ts.groupby(ts.index).mean()
    return ts

def fetch_isd_hourly_temp_data(usaf_id, year):
    # TODO(philngo): allow swappable resample method
    # TODO(philngo): record data sufficiency warnings
    ts = fetch_isd_raw_temp_data(usaf_id, year)

    # CalTRACK 2.3.3
    return (
        ts.resample("Min")
        .mean()
        .interpolate(method="linear", limit=60, limit_direction="both")
        .resample("h")
        .mean()
    )


def fetch_isd_daily_temp_data(usaf_id, year):
    # TODO(philngo): allow swappable resample method
    # TODO(philngo): record data sufficiency warnings
    ts = fetch_isd_raw_temp_data(usaf_id, year)
    return (
        ts.resample("Min")
        .mean()
        .interpolate(method="linear", limit=60, limit_direction="both")
        .resample("D")
        .mean()
    )


def fetch_gsod_raw_temp_data(usaf_id, year):
    filenames = get_gsod_filenames(usaf_id, year)

    data = []
    for filename in filenames:
        # using fully-qualified name facilitates monkeypatching
        gzipped = eeweather.connections.noaa_ftp_connection_proxy.read_file_as_bytes(
            filename
        )

        if gzipped is not None:
            f = gzip.GzipFile(fileobj=gzipped)
            lines = f.readlines()
            for line in lines[1:]:
                columns = line.split()
                date_str = columns[2].decode("utf-8")
                tempF = float(columns[3])
                tempC = (5.0 / 9.0) * (tempF - 32.0)
                dt = pytz.UTC.localize(datetime.strptime(date_str, "%Y%m%d"))
                data.append([dt, tempC])
            gzipped.close()

    if data == []:
        raise GSODDataNotAvailableError(usaf_id, year)

    dates, temps = zip(*sorted(data))
    ts = pd.Series(temps, index=dates)
    ts = ts.groupby(ts.index).mean()
    return ts


def fetch_gsod_raw_temp_data_new(usaf_id, year):
    filenames = get_gsod_filenames(usaf_id, year)

    file_parse_results = [eeweather.access_api.FileParseResult.from_file_path(file_name) for file_name in filenames]

    data = []
    for file_parse_result in file_parse_results:
        resp_data = eeweather.access_api.make_api_request(
            dataset_type=file_parse_result.dataset_type,
            usaf_id=file_parse_result.usaf_id,
            wban_id=file_parse_result.wban_id,
            year=file_parse_result.year
        )
        data.extend(resp_data)

    if data == []:
        raise GSODDataNotAvailableError(usaf_id, year)

    dates, temps = zip(*sorted(data))
    ts = pd.Series(temps, index=dates)
    ts = ts.groupby(ts.index).mean()
    return ts

def fetch_gsod_daily_temp_data(usaf_id, year):
    ts = fetch_gsod_raw_temp_data(usaf_id, year)
    return ts.resample("D").mean()


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


def get_isd_hourly_temp_data_cache_key(usaf_id, year):
    return "isd-hourly-{}-{}".format(usaf_id, year)


def get_isd_daily_temp_data_cache_key(usaf_id, year):
    return "isd-daily-{}-{}".format(usaf_id, year)


def get_gsod_daily_temp_data_cache_key(usaf_id, year):
    return "gsod-daily-{}-{}".format(usaf_id, year)


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


def cached_isd_hourly_temp_data_is_expired(usaf_id, year):
    key = get_isd_hourly_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    last_updated = store.key_updated(key)
    return _expired(last_updated, year)


def cached_isd_daily_temp_data_is_expired(usaf_id, year):
    key = get_isd_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    last_updated = store.key_updated(key)
    return _expired(last_updated, year)


def cached_gsod_daily_temp_data_is_expired(usaf_id, year):
    key = get_gsod_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    last_updated = store.key_updated(key)
    return _expired(last_updated, year)


def validate_isd_hourly_temp_data_cache(usaf_id, year):
    key = get_isd_hourly_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    # check for expired data, fail if so
    if cached_isd_hourly_temp_data_is_expired(usaf_id, year):
        store.clear(key)
        return False

    return True


def validate_isd_daily_temp_data_cache(usaf_id, year):
    key = get_isd_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    # check for expired data, fail if so
    if cached_isd_daily_temp_data_is_expired(usaf_id, year):
        store.clear(key)
        return False

    return True


def validate_gsod_daily_temp_data_cache(usaf_id, year):
    key = get_gsod_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()

    # fail if no key
    if not store.key_exists(key):
        return False

    # check for expired data, fail if so
    if cached_gsod_daily_temp_data_is_expired(usaf_id, year):
        store.clear(key)
        return False

    return True


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


def serialize_isd_hourly_temp_data(ts):
    return _serialize(ts, "h")


def serialize_isd_daily_temp_data(ts):
    return _serialize(ts, "D")


def serialize_gsod_daily_temp_data(ts):
    return _serialize(ts, "D")


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


def deserialize_isd_hourly_temp_data(data):
    return _deserialize(data, "h")


def deserialize_isd_daily_temp_data(data):
    return _deserialize(data, "D")


def deserialize_gsod_daily_temp_data(data):
    return _deserialize(data, "D")


def deserialize_tmy3_hourly_temp_data(data):
    return _deserialize(data, "h")


def deserialize_cz2010_hourly_temp_data(data):
    return _deserialize(data, "h")


def read_isd_hourly_temp_data_from_cache(usaf_id, year):
    key = get_isd_hourly_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_isd_hourly_temp_data(store.retrieve_json(key))


def read_isd_daily_temp_data_from_cache(usaf_id, year):
    key = get_isd_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_isd_daily_temp_data(store.retrieve_json(key))


def read_gsod_daily_temp_data_from_cache(usaf_id, year):
    key = get_gsod_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_gsod_daily_temp_data(store.retrieve_json(key))


def read_tmy3_hourly_temp_data_from_cache(usaf_id):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_tmy3_hourly_temp_data(store.retrieve_json(key))


def read_cz2010_hourly_temp_data_from_cache(usaf_id):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return deserialize_cz2010_hourly_temp_data(store.retrieve_json(key))


def write_isd_hourly_temp_data_to_cache(usaf_id, year, ts):
    key = get_isd_hourly_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_isd_hourly_temp_data(ts))


def write_isd_daily_temp_data_to_cache(usaf_id, year, ts):
    key = get_isd_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_isd_daily_temp_data(ts))


def write_gsod_daily_temp_data_to_cache(usaf_id, year, ts):
    key = get_gsod_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_gsod_daily_temp_data(ts))


def write_tmy3_hourly_temp_data_to_cache(usaf_id, ts):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_tmy3_hourly_temp_data(ts))


def write_cz2010_hourly_temp_data_to_cache(usaf_id, ts):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.save_json(key, serialize_cz2010_hourly_temp_data(ts))


def destroy_cached_isd_hourly_temp_data(usaf_id, year):
    key = get_isd_hourly_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def destroy_cached_isd_daily_temp_data(usaf_id, year):
    key = get_isd_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def destroy_cached_gsod_daily_temp_data(usaf_id, year):
    key = get_gsod_daily_temp_data_cache_key(usaf_id, year)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def destroy_cached_tmy3_hourly_temp_data(usaf_id):
    key = get_tmy3_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def destroy_cached_cz2010_hourly_temp_data(usaf_id):
    key = get_cz2010_hourly_temp_data_cache_key(usaf_id)
    store = eeweather.connections.key_value_store_proxy.get_store()
    return store.clear(key)


def load_isd_hourly_temp_data_cached_proxy(
    usaf_id, year, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # take from cache?
    data_ok = validate_isd_hourly_temp_data_cache(usaf_id, year)

    if not fetch_from_web and not data_ok:
        raise ISDDataNotAvailableError(usaf_id, year)
    elif fetch_from_web and (not read_from_cache or not data_ok):
        # need to actually fetch the data
        ts = fetch_isd_hourly_temp_data(usaf_id, year)
        if write_to_cache:
            write_isd_hourly_temp_data_to_cache(usaf_id, year, ts)
    else:
        # read_from_cache=True and data_ok=True
        ts = read_isd_hourly_temp_data_from_cache(usaf_id, year)
    return ts


def load_isd_daily_temp_data_cached_proxy(
    usaf_id, year, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # take from cache?
    data_ok = validate_isd_daily_temp_data_cache(usaf_id, year)

    if not fetch_from_web and not data_ok:
        raise ISDDataNotAvailableError(usaf_id, year)
    elif fetch_from_web and (not read_from_cache or not data_ok):
        # need to actually fetch the data
        ts = fetch_isd_daily_temp_data(usaf_id, year)
        if write_to_cache:
            write_isd_daily_temp_data_to_cache(usaf_id, year, ts)
    else:
        # read_from_cache=True and data_ok=True
        ts = read_isd_daily_temp_data_from_cache(usaf_id, year)
    return ts


def load_gsod_daily_temp_data_cached_proxy(
    usaf_id, year, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # take from cache?
    data_ok = validate_gsod_daily_temp_data_cache(usaf_id, year)

    if not fetch_from_web and not data_ok:
        raise GSODDataNotAvailableError(usaf_id, year)
    elif fetch_from_web and (not read_from_cache or not data_ok):
        # need to actually fetch the data
        ts = fetch_gsod_daily_temp_data(usaf_id, year)
        if write_to_cache:
            write_gsod_daily_temp_data_to_cache(usaf_id, year, ts)
    else:
        # read_from_cache=True and data_ok=True
        ts = read_gsod_daily_temp_data_from_cache(usaf_id, year)
    return ts


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


def load_isd_hourly_temp_data(
    usaf_id,
    start,
    end,
    read_from_cache=True,
    write_to_cache=True,
    error_on_missing_years=False,
    fetch_from_web=True,
):
    warnings = []
    # CalTRACK 2.3.3
    if not _datetime_is_utc(start):
        raise NonUTCTimezoneInfoError(start)
    if not _datetime_is_utc(end):
        raise NonUTCTimezoneInfoError(end)
    if not error_on_missing_years:
        data = []
        for year in range(start.year, end.year + 1):
            try:
                data.append(
                    load_isd_hourly_temp_data_cached_proxy(
                        usaf_id,
                        year,
                        read_from_cache=read_from_cache,
                        write_to_cache=write_to_cache,
                        fetch_from_web=fetch_from_web,
                    )
                )
            except ISDDataNotAvailableError:
                warnings.append(
                    EEWeatherWarning(
                        qualified_name="eeweather.isd_data_not_available",
                        description=("ISD Data not available"),
                        data={"year": year},
                    )
                )
                pass
    else:
        data = [
            load_isd_hourly_temp_data_cached_proxy(
                usaf_id,
                year,
                read_from_cache=read_from_cache,
                write_to_cache=write_to_cache,
                fetch_from_web=fetch_from_web,
            )
            for year in range(start.year, end.year + 1)
        ]

    # get raw data from loaded years into hourly form
    ts = pd.concat(data).resample("h").mean()

    # whittle down to desired range
    ts = ts[start:end]

    if len(ts) > 0:
        # because start and end dates need.to fall exactly on hours
        ts_start = datetime(
            start.year, start.month, start.day, start.hour, tzinfo=pytz.UTC
        )
        # add an hour if not already exactly on an hour, which guarantees
        # that ts_start is greater than or equal to start.
        if ts_start < start:
            ts_start += timedelta(seconds=3600)
        ts_end = datetime(end.year, end.month, end.day, end.hour, tzinfo=pytz.UTC)
        # fill in gaps
        ts = ts.reindex(pd.date_range(ts_start, ts_end, freq="h", tz=pytz.UTC))
    return ts, warnings


def load_isd_daily_temp_data(
    usaf_id, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # CalTRACK 2.3.3
    if start.tzinfo != pytz.UTC:
        raise NonUTCTimezoneInfoError(start)
    if end.tzinfo != pytz.UTC:
        raise NonUTCTimezoneInfoError(end)
    data = [
        load_isd_daily_temp_data_cached_proxy(
            usaf_id,
            year,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )
        for year in range(start.year, end.year + 1)
    ]

    # get raw data
    ts = pd.concat(data).resample("D").mean()

    # whittle down
    ts = ts[start:end]

    if len(ts) > 0:
        # because start and end dates need.to fall exactly on days
        ts_start = datetime(start.year, start.month, start.day, tzinfo=pytz.UTC)
        # add a day if not already exactly on a day, which guarantees
        # that ts_start is greater than or equal to start.
        if ts_start < start:
            ts_start += timedelta(days=1)
        ts_end = datetime(end.year, end.month, end.day, tzinfo=pytz.UTC)
        # fill in gaps
        ts = ts.reindex(pd.date_range(ts_start, ts_end, freq="D", tz=pytz.UTC))
    return ts


def load_gsod_daily_temp_data(
    usaf_id, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
):
    # CalTRACK 2.3.3
    if start.tzinfo != pytz.UTC:
        raise NonUTCTimezoneInfoError(start)
    if end.tzinfo != pytz.UTC:
        raise NonUTCTimezoneInfoError(end)
    data = [
        load_gsod_daily_temp_data_cached_proxy(
            usaf_id,
            year,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )
        for year in range(start.year, end.year + 1)
    ]
    # get raw data
    ts = pd.concat(data).resample("D").mean()

    # whittle down
    ts = ts[start:end]

    if len(ts) > 0:
        # because start and end dates need.to fall exactly on days
        ts_start = datetime(start.year, start.month, start.day, tzinfo=pytz.UTC)
        # add a day if not already exactly on a day, which guarantees
        # that ts_start is greater than or equal to start.
        if ts_start < start:
            ts_start += timedelta(days=1)
        ts_end = datetime(end.year, end.month, end.day, tzinfo=pytz.UTC)
        # fill in gaps
        ts = ts.reindex(pd.date_range(ts_start, ts_end, freq="D", tz=pytz.UTC))
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


def load_cached_isd_hourly_temp_data(usaf_id):
    store = eeweather.connections.key_value_store_proxy.get_store()

    data = [
        read_isd_hourly_temp_data_from_cache(usaf_id, year)
        for year in range(2000, datetime.now().year + 1)
        if store.key_exists(get_isd_hourly_temp_data_cache_key(usaf_id, year))
    ]
    if data == []:
        return None
    return pd.concat(data).resample("h").mean()


def load_cached_isd_daily_temp_data(usaf_id):
    store = eeweather.connections.key_value_store_proxy.get_store()

    data = [
        read_isd_daily_temp_data_from_cache(usaf_id, year)
        for year in range(2000, datetime.now().year + 1)
        if store.key_exists(get_isd_daily_temp_data_cache_key(usaf_id, year))
    ]
    if data == []:
        return None
    return pd.concat(data).resample("D").mean()


def load_cached_gsod_daily_temp_data(usaf_id):
    store = eeweather.connections.key_value_store_proxy.get_store()

    data = [
        read_gsod_daily_temp_data_from_cache(usaf_id, year)
        for year in range(2000, datetime.now().year + 1)
        if store.key_exists(get_gsod_daily_temp_data_cache_key(usaf_id, year))
    ]
    if data == []:
        return None
    return pd.concat(data).resample("D").mean()


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


class ISDStation(object):
    """A representation of an Integrated Surface Database weather station.

    Contains data about a particular ISD station, as well as methods to pull
    data for this station.

    Parameters
    ----------
    usaf_id : str
        ISD station USAF ID
    load_metatdata : bool, optional
        Whether or not to auto-load metadata for this station

    Attributes
    ----------
    usaf_id : str
        ISD station USAF ID
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
            self.climate_zones = {}

    def __str__(self):
        return self.usaf_id

    def __repr__(self):
        return "ISDStation('{}')".format(self.usaf_id)

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
            "climate_zones": {
                "iecc_climate_zone": self.iecc_climate_zone,
                "iecc_moisture_regime": self.iecc_moisture_regime,
                "ba_climate_zone": self.ba_climate_zone,
                "ca_climate_zone": self.ca_climate_zone,
            },
        }

    def get_isd_filenames(self, year=None, with_host=False):
        """Get filenames of raw ISD station data."""
        return get_isd_filenames(self.usaf_id, year, with_host=with_host)

    def get_gsod_filenames(self, year=None, with_host=False):
        """Get filenames of raw GSOD station data."""
        return get_gsod_filenames(self.usaf_id, year, with_host=with_host)

    def get_isd_file_metadata(self):
        """Get raw file metadata for the station."""
        return get_isd_file_metadata(self.usaf_id)

    # fetch raw data
    def fetch_isd_raw_temp_data(self, year):
        """Pull raw ISD data for the given year directly from FTP."""
        return fetch_isd_raw_temp_data(self.usaf_id, year)

    def fetch_gsod_raw_temp_data(self, year):
        """Pull raw GSOD data for the given year directly from FTP."""
        return fetch_gsod_raw_temp_data(self.usaf_id, year)

    # fetch raw data then frequency-normalize
    def fetch_isd_hourly_temp_data(self, year):
        """Pull raw ISD temperature data for the given year directly from FTP and resample to hourly time series."""
        return fetch_isd_hourly_temp_data(self.usaf_id, year)

    def fetch_isd_daily_temp_data(self, year):
        """Pull raw ISD temperature data for the given year directly from FTP and resample to daily time series."""
        return fetch_isd_daily_temp_data(self.usaf_id, year)

    def fetch_gsod_daily_temp_data(self, year):
        """Pull raw GSOD temperature data for the given year directly from FTP and resample to daily time series."""
        return fetch_gsod_daily_temp_data(self.usaf_id, year)

    def fetch_tmy3_hourly_temp_data(self):
        """Pull hourly TMY3 temperature hourly time series directly from NREL."""
        return fetch_tmy3_hourly_temp_data(self.usaf_id)

    def fetch_cz2010_hourly_temp_data(self):
        """Pull hourly CZ2010 temperature hourly time series from URL."""
        return fetch_cz2010_hourly_temp_data(self.usaf_id)

    # get key-value store key
    def get_isd_hourly_temp_data_cache_key(self, year):
        """Get key used to cache resampled hourly ISD temperature data for the given year."""
        return get_isd_hourly_temp_data_cache_key(self.usaf_id, year)

    def get_isd_daily_temp_data_cache_key(self, year):
        """Get key used to cache resampled daily ISD temperature data for the given year."""
        return get_isd_daily_temp_data_cache_key(self.usaf_id, year)

    def get_gsod_daily_temp_data_cache_key(self, year):
        """Get key used to cache resampled daily GSOD temperature data for the given year."""
        return get_gsod_daily_temp_data_cache_key(self.usaf_id, year)

    def get_tmy3_hourly_temp_data_cache_key(self):
        """Get key used to cache TMY3 weather-normalized temperature data."""
        return get_tmy3_hourly_temp_data_cache_key(self.usaf_id)

    def get_cz2010_hourly_temp_data_cache_key(self):
        """Get key used to cache CZ2010 weather-normalized temperature data."""
        return get_cz2010_hourly_temp_data_cache_key(self.usaf_id)

    # is cached data expired? boolean. true if expired or not in cache
    def cached_isd_hourly_temp_data_is_expired(self, year):
        """Return True if cache of resampled hourly ISD temperature data has expired or does not exist for the given year."""
        return cached_isd_hourly_temp_data_is_expired(self.usaf_id, year)

    def cached_isd_daily_temp_data_is_expired(self, year):
        """Return True if cache of resampled daily ISD temperature data has expired or does not exist for the given year."""
        return cached_isd_daily_temp_data_is_expired(self.usaf_id, year)

    def cached_gsod_daily_temp_data_is_expired(self, year):
        """Return True if cache of resampled daily GSOD temperature data has expired or does not exist for the given year."""
        return cached_gsod_daily_temp_data_is_expired(self.usaf_id, year)

    # check if data is available and delete data in the cache if it's expired
    def validate_isd_hourly_temp_data_cache(self, year):
        """Delete cached resampled hourly ISD temperature data if it has expired for the given year."""
        return validate_isd_hourly_temp_data_cache(self.usaf_id, year)

    def validate_isd_daily_temp_data_cache(self, year):
        """Delete cached resampled daily ISD temperature data if it has expired for the given year."""
        return validate_isd_daily_temp_data_cache(self.usaf_id, year)

    def validate_gsod_daily_temp_data_cache(self, year):
        """Delete cached resampled daily GSOD temperature data if it has expired for the given year."""
        return validate_gsod_daily_temp_data_cache(self.usaf_id, year)

    def validate_tmy3_hourly_temp_data_cache(self):
        """Check if TMY3 data exists in cache."""
        return validate_tmy3_hourly_temp_data_cache(self.usaf_id)

    def validate_cz2010_hourly_temp_data_cache(self):
        """Check if CZ2010 data exists in cache."""
        return validate_cz2010_hourly_temp_data_cache(self.usaf_id)

    # pandas time series to json
    def serialize_isd_hourly_temp_data(self, ts):
        """Serialize resampled hourly ISD pandas time series as JSON for caching."""
        return serialize_isd_hourly_temp_data(ts)

    def serialize_isd_daily_temp_data(self, ts):
        """Serialize resampled daily ISD pandas time series as JSON for caching."""
        return serialize_isd_daily_temp_data(ts)

    def serialize_gsod_daily_temp_data(self, ts):
        """Serialize resampled daily GSOD pandas time series as JSON for caching."""
        return serialize_gsod_daily_temp_data(ts)

    def serialize_tmy3_hourly_temp_data(self, ts):
        """Serialize hourly TMY3 pandas time series as JSON for caching."""
        return serialize_tmy3_hourly_temp_data(ts)

    def serialize_cz2010_hourly_temp_data(self, ts):
        """Serialize hourly CZ2010 pandas time series as JSON for caching."""
        return serialize_cz2010_hourly_temp_data(ts)

    # json to pandas time series
    def deserialize_isd_hourly_temp_data(self, data):
        """Deserialize JSON representation of resampled hourly ISD into pandas time series."""
        return deserialize_isd_hourly_temp_data(data)

    def deserialize_isd_daily_temp_data(self, data):
        """Deserialize JSON representation of resampled daily ISD into pandas time series."""
        return deserialize_isd_daily_temp_data(data)

    def deserialize_gsod_daily_temp_data(self, data):
        """Deserialize JSON representation of resampled daily GSOD into pandas time series."""
        return deserialize_gsod_daily_temp_data(data)

    def deserialize_tmy3_hourly_temp_data(self, data):
        """Deserialize JSON representation of hourly TMY3 into pandas time series."""
        return deserialize_isd_hourly_temp_data(data)

    def deserialize_cz2010_hourly_temp_data(self, data):
        """Deserialize JSON representation of hourly CZ2010 into pandas time series."""
        return deserialize_cz2010_hourly_temp_data(data)

    # return pandas time series of data from cache
    def read_isd_hourly_temp_data_from_cache(self, year):
        """Get cached version of resampled hourly ISD temperature data for given year."""
        return read_isd_hourly_temp_data_from_cache(self.usaf_id, year)

    def read_isd_daily_temp_data_from_cache(self, year):
        """Get cached version of resampled daily ISD temperature data for given year."""
        return read_isd_daily_temp_data_from_cache(self.usaf_id, year)

    def read_gsod_daily_temp_data_from_cache(self, year):
        """Get cached version of resampled daily GSOD temperature data for given year."""
        return read_gsod_daily_temp_data_from_cache(self.usaf_id, year)

    def read_tmy3_hourly_temp_data_from_cache(self):
        """Get cached version of hourly TMY3 temperature data."""
        return read_tmy3_hourly_temp_data_from_cache(self.usaf_id)

    def read_cz2010_hourly_temp_data_from_cache(self):
        """Get cached version of hourly TMY3 temperature data."""
        return read_cz2010_hourly_temp_data_from_cache(self.usaf_id)

    # write pandas time series of data to cache for a particular year
    def write_isd_hourly_temp_data_to_cache(self, year, ts):
        """Write resampled hourly ISD temperature data to cache for given year."""
        return write_isd_hourly_temp_data_to_cache(self.usaf_id, year, ts)

    def write_isd_daily_temp_data_to_cache(self, year, ts):
        """Write resampled daily ISD temperature data to cache for given year."""
        return write_isd_daily_temp_data_to_cache(self.usaf_id, year, ts)

    def write_gsod_daily_temp_data_to_cache(self, year, ts):
        """Write resampled daily GSOD temperature data to cache for given year."""
        return write_gsod_daily_temp_data_to_cache(self.usaf_id, year, ts)

    def write_tmy3_hourly_temp_data_to_cache(self, ts):
        """Write hourly TMY3 temperature data to cache for given year."""
        return write_tmy3_hourly_temp_data_to_cache(self.usaf_id, ts)

    def write_cz2010_hourly_temp_data_to_cache(self, ts):
        """Write hourly CZ2010 temperature data to cache for given year."""
        return write_cz2010_hourly_temp_data_to_cache(self.usaf_id, ts)

    # delete cached data for a particular year
    def destroy_cached_isd_hourly_temp_data(self, year):
        """Remove cached resampled hourly ISD temperature data to cache for given year."""
        return destroy_cached_isd_hourly_temp_data(self.usaf_id, year)

    def destroy_cached_isd_daily_temp_data(self, year):
        """Remove cached resampled daily ISD temperature data to cache for given year."""
        return destroy_cached_isd_daily_temp_data(self.usaf_id, year)

    def destroy_cached_gsod_daily_temp_data(self, year):
        """Remove cached resampled daily GSOD temperature data to cache for given year."""
        return destroy_cached_gsod_daily_temp_data(self.usaf_id, year)

    def destroy_cached_tmy3_hourly_temp_data(self):
        """Remove cached hourly TMY3 temperature data to cache."""
        return destroy_cached_tmy3_hourly_temp_data(self.usaf_id)

    def destroy_cached_cz2010_hourly_temp_data(self):
        """Remove cached hourly CZ2010 temperature data to cache."""
        return destroy_cached_cz2010_hourly_temp_data(self.usaf_id)

    # load data either from cache if valid or directly from source
    def load_isd_hourly_temp_data_cached_proxy(self, year, fetch_from_web=True):
        """Load resampled hourly ISD temperature data from cache, or if it is expired or hadn't been cached, fetch from FTP for given year."""
        return load_isd_hourly_temp_data_cached_proxy(
            self.usaf_id, year, fetch_from_web
        )

    def load_isd_daily_temp_data_cached_proxy(self, year, fetch_from_web=True):
        """Load resampled daily ISD temperature data from cache, or if it is expired or hadn't been cached, fetch from FTP for given year."""
        return load_isd_daily_temp_data_cached_proxy(self.usaf_id, year, fetch_from_web)

    def load_gsod_daily_temp_data_cached_proxy(self, year, fetch_from_web=True):
        """Load resampled daily GSOD temperature data from cache, or if it is expired or hadn't been cached, fetch from FTP for given year."""
        return load_gsod_daily_temp_data_cached_proxy(
            self.usaf_id, year, fetch_from_web
        )

    def load_tmy3_hourly_temp_data_cached_proxy(self, fetch_from_web=True):
        """Load hourly TMY3 temperature data from cache, or if it is expired or hadn't been cached, fetch from NREL."""
        return load_tmy3_hourly_temp_data_cached_proxy(self.usaf_id, fetch_from_web)

    def load_cz2010_hourly_temp_data_cached_proxy(self, fetch_from_web=True):
        """Load hourly CZ2010 temperature data from cache, or if it is expired or hadn't been cached, fetch from URL."""
        return load_cz2010_hourly_temp_data_cached_proxy(self.usaf_id, fetch_from_web)

    # main interface: load data from start date to end date
    def load_isd_hourly_temp_data(
        self,
        start,
        end,
        read_from_cache=True,
        write_to_cache=True,
        fetch_from_web=True,
        error_on_missing_years=True,
    ):
        """Load resampled hourly ISD temperature data from start date to end date (inclusive).

        This is the primary convenience method for loading resampled hourly ISD temperature data.

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data.
        end : datetime.datetime
            The latest date until which to load data.
        read_from_cache : bool
            Whether or not to load data from cache.
        fetch_from_web : bool
            Whether or not to fetch data from ftp.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        """
        return load_isd_hourly_temp_data(
            self.usaf_id,
            start,
            end,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
            error_on_missing_years=error_on_missing_years,
        )

    def load_isd_daily_temp_data(
        self, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
    ):
        """Load resampled daily ISD temperature data from start date to end date (inclusive).

        This is the primary convenience method for loading resampled daily ISD temperature data.

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data.
        end : datetime.datetime
            The latest date until which to load data.
        read_from_cache : bool
            Whether or not to load data from cache.
        fetch_from_web : bool
            Whether or not to fetch data from ftp.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        """
        return load_isd_daily_temp_data(
            self.usaf_id,
            start,
            end,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )

    def load_gsod_daily_temp_data(
        self, start, end, read_from_cache=True, write_to_cache=True, fetch_from_web=True
    ):
        """Load resampled daily GSOD temperature data from start date to end date (inclusive).

        This is the primary convenience method for loading resampled daily GSOD temperature data.

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
        return load_gsod_daily_temp_data(
            self.usaf_id,
            start,
            end,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
        )

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
    def load_cached_isd_hourly_temp_data(self):
        """Load all cached resampled hourly ISD temperature data."""
        return load_cached_isd_hourly_temp_data(self.usaf_id)

    def load_cached_isd_daily_temp_data(self):
        """Load all cached resampled daily ISD temperature data."""
        return load_cached_isd_daily_temp_data(self.usaf_id)

    def load_cached_gsod_daily_temp_data(self):
        """Load all cached resampled daily GSOD temperature data."""
        return load_cached_gsod_daily_temp_data(self.usaf_id)

    def load_cached_tmy3_hourly_temp_data(self):
        """Load all cached hourly TMY3 temperature data (the year is set to 1900)"""
        return load_cached_tmy3_hourly_temp_data(self.usaf_id)

    def load_cached_cz2010_hourly_temp_data(self):
        """Load all cached hourly TMY3 temperature data (the year is set to 1900)"""
        return load_cached_cz2010_hourly_temp_data(self.usaf_id)
