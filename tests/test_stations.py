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
from datetime import datetime
import pandas as pd
import pytest
import pytz

from eeweather import (
    ISDStation,
    get_isd_station_metadata,
    get_isd_filenames,
    get_gsod_filenames,
    get_isd_file_metadata,
    fetch_isd_raw_temp_data,
    fetch_isd_hourly_temp_data,
    fetch_isd_daily_temp_data,
    fetch_gsod_raw_temp_data,
    fetch_gsod_daily_temp_data,
    fetch_tmy3_hourly_temp_data,
    fetch_cz2010_hourly_temp_data,
    get_isd_hourly_temp_data_cache_key,
    get_isd_daily_temp_data_cache_key,
    get_gsod_daily_temp_data_cache_key,
    get_tmy3_hourly_temp_data_cache_key,
    get_cz2010_hourly_temp_data_cache_key,
    cached_isd_hourly_temp_data_is_expired,
    cached_isd_daily_temp_data_is_expired,
    cached_gsod_daily_temp_data_is_expired,
    validate_isd_hourly_temp_data_cache,
    validate_isd_daily_temp_data_cache,
    validate_gsod_daily_temp_data_cache,
    validate_tmy3_hourly_temp_data_cache,
    validate_cz2010_hourly_temp_data_cache,
    serialize_isd_hourly_temp_data,
    serialize_isd_daily_temp_data,
    serialize_gsod_daily_temp_data,
    serialize_tmy3_hourly_temp_data,
    serialize_cz2010_hourly_temp_data,
    deserialize_isd_hourly_temp_data,
    deserialize_isd_daily_temp_data,
    deserialize_gsod_daily_temp_data,
    deserialize_tmy3_hourly_temp_data,
    deserialize_cz2010_hourly_temp_data,
    read_isd_hourly_temp_data_from_cache,
    read_isd_daily_temp_data_from_cache,
    read_gsod_daily_temp_data_from_cache,
    read_tmy3_hourly_temp_data_from_cache,
    read_cz2010_hourly_temp_data_from_cache,
    write_isd_hourly_temp_data_to_cache,
    write_isd_daily_temp_data_to_cache,
    write_gsod_daily_temp_data_to_cache,
    write_tmy3_hourly_temp_data_to_cache,
    write_cz2010_hourly_temp_data_to_cache,
    destroy_cached_isd_hourly_temp_data,
    destroy_cached_isd_daily_temp_data,
    destroy_cached_gsod_daily_temp_data,
    destroy_cached_tmy3_hourly_temp_data,
    destroy_cached_cz2010_hourly_temp_data,
    load_isd_hourly_temp_data_cached_proxy,
    load_isd_daily_temp_data_cached_proxy,
    load_gsod_daily_temp_data_cached_proxy,
    load_tmy3_hourly_temp_data_cached_proxy,
    load_cz2010_hourly_temp_data_cached_proxy,
    load_isd_hourly_temp_data,
    load_isd_daily_temp_data,
    load_gsod_daily_temp_data,
    load_tmy3_hourly_temp_data,
    load_cz2010_hourly_temp_data,
    load_cached_isd_hourly_temp_data,
    load_cached_isd_daily_temp_data,
    load_cached_gsod_daily_temp_data,
    load_cached_tmy3_hourly_temp_data,
    load_cached_cz2010_hourly_temp_data,
)
from eeweather.exceptions import (
    UnrecognizedUSAFIDError,
    ISDDataNotAvailableError,
    GSODDataNotAvailableError,
    TMY3DataNotAvailableError,
    CZ2010DataNotAvailableError,
    NonUTCTimezoneInfoError,
)
from eeweather.testing import (
    MockNOAAFTPConnectionProxy,
    MockKeyValueStoreProxy,
    mock_request_text_tmy3,
    mock_request_text_cz2010,
)
from sqlalchemy.orm import Session


@pytest.fixture
def monkeypatch_noaa_ftp(monkeypatch):
    monkeypatch.setattr(
        "eeweather.connections.noaa_ftp_connection_proxy", MockNOAAFTPConnectionProxy()
    )


@pytest.fixture
def monkeypatch_tmy3_request(monkeypatch):
    monkeypatch.setattr("eeweather.mockable.request_text", mock_request_text_tmy3)


@pytest.fixture
def monkeypatch_cz2010_request(monkeypatch):
    monkeypatch.setattr("eeweather.mockable.request_text", mock_request_text_cz2010)


@pytest.fixture
def monkeypatch_key_value_store(monkeypatch):
    key_value_store_proxy = MockKeyValueStoreProxy()
    monkeypatch.setattr(
        "eeweather.connections.key_value_store_proxy", key_value_store_proxy
    )

    return key_value_store_proxy.get_store()


def test_get_isd_station_metadata():
    assert get_isd_station_metadata("722874") == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_08",
        "elevation": "+0054.6",
        "icao_code": "KCQT",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
        "latitude": "+34.024",
        "longitude": "-118.291",
        "name": "DOWNTOWN L.A./USC CAMPUS",
        "quality": "low",
        "recent_wban_id": "93134",
        "state": "CA",
        "usaf_id": "722874",
        "wban_ids": "93134",
    }


def test_isd_station_no_load_metadata():
    station = ISDStation("722880", load_metadata=False)
    assert station.usaf_id == "722880"
    assert station.iecc_climate_zone is None
    assert station.iecc_moisture_regime is None
    assert station.ba_climate_zone is None
    assert station.ca_climate_zone is None
    assert station.elevation is None
    assert station.latitude is None
    assert station.longitude is None
    assert station.coords is None
    assert station.name is None
    assert station.quality is None
    assert station.wban_ids is None
    assert station.recent_wban_id is None
    assert station.climate_zones == {}

    assert str(station) == "722880"
    assert repr(station) == "ISDStation('722880')"


def test_isd_station_no_load_metadata_invalid():
    with pytest.raises(UnrecognizedUSAFIDError):
        station = ISDStation("FAKE", load_metadata=False)


def test_isd_station_with_load_metadata():
    station = ISDStation("722880", load_metadata=True)
    assert station.usaf_id == "722880"
    assert station.iecc_climate_zone == "3"
    assert station.iecc_moisture_regime == "B"
    assert station.ba_climate_zone == "Hot-Dry"
    assert station.ca_climate_zone == "CA_09"
    assert station.elevation == 222.7
    assert station.icao_code == "KBUR"
    assert station.latitude == 34.2
    assert station.longitude == -118.365
    assert station.coords == (34.2, -118.365)
    assert station.name == "BURBANK-GLENDALE-PASA ARPT"
    assert station.quality == "high"
    assert station.wban_ids == ["23152", "99999"]
    assert station.recent_wban_id == "23152"
    assert station.climate_zones == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
    }


def test_isd_station_json():
    station = ISDStation("722880", load_metadata=True)
    assert station.json() == {
        "elevation": 222.7,
        "icao_code": "KBUR",
        "latitude": 34.2,
        "longitude": -118.365,
        "name": "BURBANK-GLENDALE-PASA ARPT",
        "quality": "high",
        "recent_wban_id": "23152",
        "wban_ids": ["23152", "99999"],
        "climate_zones": {
            "ba_climate_zone": "Hot-Dry",
            "ca_climate_zone": "CA_09",
            "iecc_climate_zone": "3",
            "iecc_moisture_regime": "B",
        },
    }


def test_isd_station_unrecognized_usaf_id():
    with pytest.raises(UnrecognizedUSAFIDError):
        station = ISDStation("FAKE", load_metadata=True)


def test_get_isd_filenames_bad_usaf_id():
    with pytest.raises(UnrecognizedUSAFIDError) as excinfo:
        get_isd_filenames("000000", 2007)
    assert excinfo.value.value == "000000"


def test_get_isd_filenames_single_year(snapshot):
    filenames = get_isd_filenames("722860", 2007)
    assert snapshot == filenames


def test_get_isd_filenames_multiple_year(snapshot):
    filenames = get_isd_filenames("722860")
    assert snapshot == filenames


def test_get_isd_filenames_future_year():
    filenames = get_isd_filenames("722860", 2050)
    assert filenames == ["/pub/data/noaa/2050/722860-23119-2050.gz"]


def test_get_isd_filenames_with_host():
    filenames = get_isd_filenames("722860", 2017, with_host=True)
    assert filenames == [
        "ftp://ftp.ncei.noaa.gov/pub/data/noaa/2017/722860-23119-2017.gz"
    ]


def test_isd_station_get_isd_filenames(snapshot):
    station = ISDStation("722860")
    filenames = station.get_isd_filenames()
    assert snapshot == filenames


def test_isd_station_get_isd_filenames_with_year(snapshot):
    station = ISDStation("722860")
    filenames = station.get_isd_filenames(2007)
    assert snapshot == filenames


def test_isd_station_get_isd_filenames_with_host():
    station = ISDStation("722860")
    filenames = station.get_isd_filenames(2017, with_host=True)
    assert filenames == [
        "ftp://ftp.ncei.noaa.gov/pub/data/noaa/2017/722860-23119-2017.gz"
    ]


def test_get_gsod_filenames_bad_usaf_id():
    with pytest.raises(UnrecognizedUSAFIDError) as excinfo:
        get_gsod_filenames("000000", 2007)
    assert excinfo.value.value == "000000"


def test_get_gsod_filenames_single_year(snapshot):
    filenames = get_gsod_filenames("722860", 2007)
    assert snapshot == filenames


def test_get_gsod_filenames_multiple_year(snapshot):
    filenames = get_gsod_filenames("722860")
    assert snapshot == filenames


def test_get_gsod_filenames_future_year():
    filenames = get_gsod_filenames("722860", 2050)
    assert filenames == ["/pub/data/gsod/2050/722860-23119-2050.op.gz"]


def test_get_gsod_filenames_with_host():
    filenames = get_gsod_filenames("722860", 2017, with_host=True)
    assert filenames == [
        "ftp://ftp.ncei.noaa.gov/pub/data/gsod/2017/722860-23119-2017.op.gz"
    ]


def test_isd_station_get_gsod_filenames(snapshot):
    station = ISDStation("722860")
    filenames = station.get_gsod_filenames()
    assert snapshot == filenames


def test_isd_station_get_gsod_filenames_with_year(snapshot):
    station = ISDStation("722860")
    filenames = station.get_gsod_filenames(2007)
    assert snapshot == filenames


def test_isd_station_get_gsod_filenames_with_host():
    station = ISDStation("722860")
    filenames = station.get_gsod_filenames(2017, with_host=True)
    assert filenames == [
        "ftp://ftp.ncei.noaa.gov/pub/data/gsod/2017/722860-23119-2017.op.gz"
    ]


def test_get_isd_file_metadata():
    assert get_isd_file_metadata("722874") == [
        {"usaf_id": "722874", "wban_id": "93134", "year": "2006"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2007"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2008"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2009"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2010"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2011"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2012"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2013"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2014"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2015"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2016"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2017"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2018"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2019"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2020"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2021"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2022"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2023"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2024"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2025"},
    ]

    with pytest.raises(UnrecognizedUSAFIDError) as excinfo:
        get_isd_file_metadata("000000")
    assert excinfo.value.value == "000000"


def test_isd_station_get_isd_file_metadata():
    station = ISDStation("722874")
    assert station.get_isd_file_metadata() == [
        {"usaf_id": "722874", "wban_id": "93134", "year": "2006"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2007"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2008"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2009"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2010"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2011"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2012"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2013"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2014"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2015"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2016"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2017"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2018"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2019"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2020"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2021"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2022"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2023"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2024"},
        {"usaf_id": "722874", "wban_id": "93134", "year": "2025"},
    ]


# fetch raw
def test_fetch_isd_raw_temp_data(monkeypatch_noaa_ftp):
    data = fetch_isd_raw_temp_data("722874", 2007)
    assert round(data.sum()) == pytest.approx(185945, 0.00001)
    assert data.shape == (11094,)


def test_fetch_gsod_raw_temp_data(monkeypatch_noaa_ftp):
    data = fetch_gsod_raw_temp_data("722874", 2007)
    assert data.sum() == pytest.approx(6509.5, 0.00001)
    assert data.shape == (365,)


# station fetch raw
def test_isd_station_fetch_isd_raw_temp_data(monkeypatch_noaa_ftp):
    station = ISDStation("722874")
    data = station.fetch_isd_raw_temp_data(2007)
    assert round(data.sum()) == pytest.approx(185945, 0.00001)
    assert data.shape == (11094,)


def test_isd_station_fetch_gsod_raw_temp_data(monkeypatch_noaa_ftp):
    station = ISDStation("722874")
    data = station.fetch_gsod_raw_temp_data(2007)
    assert data.sum() == pytest.approx(6509.5, 0.00001)
    assert data.shape == (365,)


# fetch raw invalid station
def test_fetch_isd_raw_temp_data_invalid_station():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_isd_raw_temp_data("INVALID", 2007)


def test_fetch_gsod_raw_temp_data_invalid_station():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_gsod_raw_temp_data("INVALID", 2007)


# fetch raw invalid year
def test_fetch_isd_raw_temp_data_invalid_year(monkeypatch_noaa_ftp):
    with pytest.raises(ISDDataNotAvailableError):
        fetch_isd_raw_temp_data("722874", 1800)


def test_fetch_gsod_raw_temp_data_invalid_year(monkeypatch_noaa_ftp):
    with pytest.raises(GSODDataNotAvailableError):
        fetch_gsod_raw_temp_data("722874", 1800)


# fetch file full of nans
def test_isd_station_fetch_isd_raw_temp_data_all_nan(monkeypatch_noaa_ftp):
    station = ISDStation("994035")
    data = station.fetch_isd_raw_temp_data(2013)
    assert round(data.sum()) == 0
    assert data.shape == (8611,)


# fetch
def test_fetch_isd_hourly_temp_data(monkeypatch_noaa_ftp):
    data = fetch_isd_hourly_temp_data("722874", 2007)
    assert data.sum() == pytest.approx(156160.0355, 0.00001)
    assert data.shape == (8760,)


def test_fetch_isd_daily_temp_data(monkeypatch_noaa_ftp):
    data = fetch_isd_daily_temp_data("722874", 2007)
    assert data.sum() == pytest.approx(6510.002260821784, 0.00001)
    assert data.shape == (365,)


def test_fetch_gsod_daily_temp_data(monkeypatch_noaa_ftp):
    data = fetch_gsod_daily_temp_data("722874", 2007)
    assert data.sum() == pytest.approx(6509.5, 0.00001)
    assert data.shape == (365,)


def test_fetch_tmy3_hourly_temp_data(monkeypatch_tmy3_request):
    data = fetch_tmy3_hourly_temp_data("722880")
    assert data.sum() == pytest.approx(156194.3, 0.00001)
    assert data.shape == (8760,)


def test_fetch_cz2010_hourly_temp_data(monkeypatch_cz2010_request):
    data = fetch_cz2010_hourly_temp_data("722880")
    assert data.sum() == pytest.approx(153430.9, 0.00001)
    assert data.shape == (8760,)


# station fetch
def test_isd_station_fetch_isd_hourly_temp_data(monkeypatch_noaa_ftp):
    station = ISDStation("722874")
    data = station.fetch_isd_hourly_temp_data(2007)
    assert data.sum() == pytest.approx(156160.0355, 0.00001)
    assert data.shape == (8760,)


def test_isd_station_fetch_isd_daily_temp_data(monkeypatch_noaa_ftp):
    station = ISDStation("722874")
    data = station.fetch_isd_daily_temp_data(2007)
    assert data.sum() == pytest.approx(6510, 0.00001)
    assert data.shape == (365,)


def test_isd_station_fetch_gsod_daily_temp_data(monkeypatch_noaa_ftp):
    station = ISDStation("722874")
    data = station.fetch_gsod_daily_temp_data(2007)
    assert data.sum() == pytest.approx(6509.5, 0.00001)
    assert data.shape == (365,)


def test_tmy3_station_hourly_temp_data(monkeypatch_tmy3_request):
    station = ISDStation("722880")
    data = station.fetch_tmy3_hourly_temp_data()
    assert data.sum() == pytest.approx(156194.3, 0.00001)
    assert data.shape == (8760,)


def test_cz2010_station_hourly_temp_data(monkeypatch_cz2010_request):
    station = ISDStation("722880")
    data = station.fetch_cz2010_hourly_temp_data()
    assert data.sum() == pytest.approx(153430.9, 0.00001)
    assert data.shape == (8760,)


# fetch invalid station
def test_fetch_isd_hourly_temp_data_invalid():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_isd_hourly_temp_data("INVALID", 2007)


def test_fetch_isd_daily_temp_data_invalid():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_isd_daily_temp_data("INVALID", 2007)


def test_fetch_gsod_daily_temp_data_invalid():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_gsod_daily_temp_data("INVALID", 2007)


def test_fetch_tmy3_hourly_temp_data_invalid():
    with pytest.raises(TMY3DataNotAvailableError):
        fetch_tmy3_hourly_temp_data("INVALID")


def test_fetch_cz2010_hourly_temp_data_invalid():
    with pytest.raises(CZ2010DataNotAvailableError):
        fetch_cz2010_hourly_temp_data("INVALID")


def test_fetch_tmy3_hourly_temp_data_not_in_tmy3_list(monkeypatch_noaa_ftp):
    data = fetch_isd_hourly_temp_data("722874", 2007)
    assert data.sum() == pytest.approx(156160.0355, 0.00001)
    assert data.shape == (8760,)
    with pytest.raises(TMY3DataNotAvailableError):
        fetch_tmy3_hourly_temp_data("722874")


def test_fetch_cz2010_hourly_temp_data_not_in_cz2010_list(monkeypatch_cz2010_request):
    data = fetch_cz2010_hourly_temp_data("722880")
    assert data.sum() == 153430.90000000002
    assert data.shape == (8760,)
    with pytest.raises(CZ2010DataNotAvailableError):
        fetch_cz2010_hourly_temp_data("725340")


# get cache key
def test_get_isd_hourly_temp_data_cache_key():
    assert (
        get_isd_hourly_temp_data_cache_key("722874", 2007) == "isd-hourly-722874-2007"
    )


def test_get_isd_daily_temp_data_cache_key():
    assert get_isd_daily_temp_data_cache_key("722874", 2007) == "isd-daily-722874-2007"


def test_get_gsod_daily_temp_data_cache_key():
    assert (
        get_gsod_daily_temp_data_cache_key("722874", 2007) == "gsod-daily-722874-2007"
    )


def test_get_tmy3_hourly_temp_data_cache_key():
    assert get_tmy3_hourly_temp_data_cache_key("722880") == "tmy3-hourly-722880"


def test_get_cz2010_hourly_temp_data_cache_key():
    assert get_cz2010_hourly_temp_data_cache_key("722880") == "cz2010-hourly-722880"


# station get cache key
def test_isd_station_get_isd_hourly_temp_data_cache_key():
    station = ISDStation("722874")
    assert station.get_isd_hourly_temp_data_cache_key(2007) == "isd-hourly-722874-2007"


def test_isd_station_get_isd_daily_temp_data_cache_key():
    station = ISDStation("722874")
    assert station.get_isd_daily_temp_data_cache_key(2007) == "isd-daily-722874-2007"


def test_isd_station_get_gsod_daily_temp_data_cache_key():
    station = ISDStation("722874")
    assert station.get_gsod_daily_temp_data_cache_key(2007) == "gsod-daily-722874-2007"


def test_tmy3_station_get_isd_hourly_temp_data_cache_key():
    station = ISDStation("722880")
    assert station.get_tmy3_hourly_temp_data_cache_key() == "tmy3-hourly-722880"


def test_cz2010_station_get_isd_hourly_temp_data_cache_key():
    station = ISDStation("722880")
    assert station.get_cz2010_hourly_temp_data_cache_key() == "cz2010-hourly-722880"


# cache expired empty
def test_cached_isd_hourly_temp_data_is_expired_empty(monkeypatch_key_value_store):
    assert cached_isd_hourly_temp_data_is_expired("722874", 2007) is True


def test_cached_isd_daily_temp_data_is_expired_empty(monkeypatch_key_value_store):
    assert cached_isd_daily_temp_data_is_expired("722874", 2007) is True


def test_cached_gsod_daily_temp_data_is_expired_empty(monkeypatch_key_value_store):
    assert cached_gsod_daily_temp_data_is_expired("722874", 2007) is True


# station cache expired empty
def test_isd_station_cached_isd_hourly_temp_data_is_expired_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.cached_isd_hourly_temp_data_is_expired(2007) is True


def test_isd_station_cached_isd_daily_temp_data_is_expired_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.cached_isd_daily_temp_data_is_expired(2007) is True


def test_isd_station_cached_gsod_daily_temp_data_is_expired_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.cached_gsod_daily_temp_data_is_expired(2007) is True


# cache expired false
def test_cached_isd_hourly_temp_data_is_expired_false(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_hourly_temp_data_cached_proxy("722874", 2007)
    assert cached_isd_hourly_temp_data_is_expired("722874", 2007) is False


def test_cached_isd_daily_temp_data_is_expired_false(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_daily_temp_data_cached_proxy("722874", 2007)
    assert cached_isd_daily_temp_data_is_expired("722874", 2007) is False


def test_cached_gsod_daily_temp_data_is_expired_false(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_gsod_daily_temp_data_cached_proxy("722874", 2007)
    assert cached_gsod_daily_temp_data_is_expired("722874", 2007) is False


# cache expired true
def test_cached_isd_hourly_temp_data_is_expired_true(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_hourly_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_isd_hourly_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )
    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert cached_isd_hourly_temp_data_is_expired("722874", 2007) is True


def test_cached_isd_daily_temp_data_is_expired_true(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_daily_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_isd_daily_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )
    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert cached_isd_daily_temp_data_is_expired("722874", 2007) is True


def test_cached_gsod_daily_temp_data_is_expired_true(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_gsod_daily_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_gsod_daily_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )
    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert cached_gsod_daily_temp_data_is_expired("722874", 2007) is True


# validate cache empty
def test_validate_isd_hourly_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_isd_hourly_temp_data_cache("722874", 2007) is False


def test_validate_isd_daily_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_isd_daily_temp_data_cache("722874", 2007) is False


def test_validate_gsod_daily_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_gsod_daily_temp_data_cache("722874", 2007) is False


def test_validate_tmy3_hourly_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_tmy3_hourly_temp_data_cache("722880") is False


def test_validate_cz2010_hourly_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_cz2010_hourly_temp_data_cache("722880") is False


# station validate cache empty
def test_isd_station_validate_isd_hourly_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.validate_isd_hourly_temp_data_cache(2007) is False


def test_isd_station_validate_isd_daily_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.validate_isd_daily_temp_data_cache(2007) is False


def test_isd_station_validate_gsod_daily_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    assert station.validate_gsod_daily_temp_data_cache(2007) is False


def test_isd_station_validate_tmy3_hourly_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722880")
    assert station.validate_tmy3_hourly_temp_data_cache() is False


def test_isd_station_validate_cz2010_hourly_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = ISDStation("722880")
    assert station.validate_cz2010_hourly_temp_data_cache() is False


# error on non-existent when relying on cache
def test_raise_on_missing_isd_hourly_temp_data_cache_data_no_web_fetch(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    with pytest.raises(ISDDataNotAvailableError):
        load_isd_hourly_temp_data_cached_proxy("722874", 1907, fetch_from_web=False)


def test_raise_on_missing_isd_daily_temp_data_cache_data_no_web_fetch(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    with pytest.raises(ISDDataNotAvailableError):
        load_isd_daily_temp_data_cached_proxy("722874", 1907, fetch_from_web=False)


def test_raise_on_missing_gsod_daily_temp_data_cache_data_no_web_fetch(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    with pytest.raises(GSODDataNotAvailableError):
        load_gsod_daily_temp_data_cached_proxy("722874", 1907, fetch_from_web=False)


def test_raise_on_missing_tmy3_hourly_temp_data_cache_data_no_web_fetch(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    with pytest.raises(TMY3DataNotAvailableError):
        load_tmy3_hourly_temp_data_cached_proxy("722874", fetch_from_web=False)


def test_raise_on_missing_cz2010_hourly_temp_data_cache_data_no_web_fetch(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    with pytest.raises(CZ2010DataNotAvailableError):
        load_cz2010_hourly_temp_data_cached_proxy("722874", fetch_from_web=False)


# validate updated recently
def test_validate_isd_hourly_temp_data_cache_updated_recently(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_hourly_temp_data_cached_proxy("722874", 2007)
    assert validate_isd_hourly_temp_data_cache("722874", 2007) is True


def test_validate_isd_daily_temp_data_cache_updated_recently(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_daily_temp_data_cached_proxy("722874", 2007)
    assert validate_isd_daily_temp_data_cache("722874", 2007) is True


def test_validate_gsod_daily_temp_data_cache_updated_recently(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_gsod_daily_temp_data_cached_proxy("722874", 2007)
    assert validate_gsod_daily_temp_data_cache("722874", 2007) is True


def test_validate_tmy3_hourly_temp_data_cache_updated_recently(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    load_tmy3_hourly_temp_data_cached_proxy("722880")
    assert validate_tmy3_hourly_temp_data_cache("722880") is True


def test_validate_cz2010_hourly_temp_data_cache_updated_recently(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    load_cz2010_hourly_temp_data_cached_proxy("722880")
    assert validate_cz2010_hourly_temp_data_cache("722880") is True


# validate expired
def test_validate_isd_hourly_temp_data_cache_expired(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_hourly_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_isd_hourly_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )
    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert validate_isd_hourly_temp_data_cache("722874", 2007) is False


def test_validate_isd_daily_temp_data_cache_expired(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_isd_daily_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_isd_daily_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )
    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert validate_isd_daily_temp_data_cache("722874", 2007) is False


def test_validate_gsod_daily_temp_data_cache_expired(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    load_gsod_daily_temp_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_gsod_daily_temp_data_cache_key("722874", 2007)
    store = monkeypatch_key_value_store
    s = (
        store.items.update()
        .where(store.items.c.key == key)
        .values(updated=pytz.UTC.localize(datetime(2007, 3, 3)))
    )

    with Session(store.eng) as session:
        session.execute(s)
        session.commit()

    assert validate_gsod_daily_temp_data_cache("722874", 2007) is False


# serialize
def test_serialize_isd_hourly_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_isd_hourly_temp_data(ts) == [["2017010100", 1]]


def test_serialize_isd_daily_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_isd_daily_temp_data(ts) == [["20170101", 1]]


def test_serialize_gsod_daily_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_gsod_daily_temp_data(ts) == [["20170101", 1]]


def test_serialize_tmy3_hourly_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_tmy3_hourly_temp_data(ts) == [["2017010100", 1]]


def test_serialize_cz2010_hourly_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_cz2010_hourly_temp_data(ts) == [["2017010100", 1]]


# station serialize
def test_isd_station_serialize_isd_hourly_temp_data():
    station = ISDStation("722874")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_isd_hourly_temp_data(ts) == [["2017010100", 1]]


def test_isd_station_serialize_isd_daily_temp_data():
    station = ISDStation("722874")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_isd_daily_temp_data(ts) == [["20170101", 1]]


def test_isd_station_serialize_gsod_daily_temp_data():
    station = ISDStation("722874")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_gsod_daily_temp_data(ts) == [["20170101", 1]]


def test_isd_station_serialize_tmy3_hourly_temp_data():
    station = ISDStation("722880")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_tmy3_hourly_temp_data(ts) == [["2017010100", 1]]


def test_isd_station_serialize_cz2010_hourly_temp_data():
    station = ISDStation("722880")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_cz2010_hourly_temp_data(ts) == [["2017010100", 1]]


# deserialize
def test_deserialize_isd_hourly_temp_data():
    ts = deserialize_isd_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_deserialize_isd_daily_temp_data():
    ts = deserialize_isd_daily_temp_data([["20170101", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "D"


def test_deserialize_gsod_daily_temp_data():
    ts = deserialize_gsod_daily_temp_data([["20170101", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "D"


def test_deserialize_tmy3_hourly_temp_data():
    ts = deserialize_tmy3_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_deserialize_cz2010_hourly_temp_data():
    ts = deserialize_cz2010_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


# station deserialize
def test_isd_station_deserialize_isd_hourly_temp_data():
    station = ISDStation("722874")
    ts = station.deserialize_isd_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_isd_station_deserialize_isd_daily_temp_data():
    station = ISDStation("722874")
    ts = station.deserialize_isd_daily_temp_data([["20170101", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "D"


def test_isd_station_deserialize_gsod_daily_temp_data():
    station = ISDStation("722874")
    ts = station.deserialize_gsod_daily_temp_data([["20170101", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "D"


def test_isd_station_deserialize_tmy3_hourly_temp_data():
    station = ISDStation("722880")
    ts = station.deserialize_tmy3_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_isd_station_deserialize_cz2010_hourly_temp_data():
    station = ISDStation("722880")
    ts = station.deserialize_cz2010_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


# write read destroy
def test_write_read_destroy_isd_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    store = monkeypatch_key_value_store
    key = get_isd_hourly_temp_data_cache_key("123456", 1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    write_isd_hourly_temp_data_to_cache("123456", 1990, ts1)
    assert store.key_exists(key) is True

    ts2 = read_isd_hourly_temp_data_from_cache("123456", 1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    destroy_cached_isd_hourly_temp_data("123456", 1990)
    assert store.key_exists(key) is False


def test_write_read_destroy_isd_daily_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    store = monkeypatch_key_value_store
    key = get_isd_daily_temp_data_cache_key("123456", 1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    write_isd_daily_temp_data_to_cache("123456", 1990, ts1)
    assert store.key_exists(key) is True

    ts2 = read_isd_daily_temp_data_from_cache("123456", 1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    destroy_cached_isd_daily_temp_data("123456", 1990)
    assert store.key_exists(key) is False


def test_write_read_destroy_gsod_daily_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    store = monkeypatch_key_value_store
    key = get_gsod_daily_temp_data_cache_key("123456", 1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    write_gsod_daily_temp_data_to_cache("123456", 1990, ts1)
    assert store.key_exists(key) is True

    ts2 = read_gsod_daily_temp_data_from_cache("123456", 1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    destroy_cached_gsod_daily_temp_data("123456", 1990)
    assert store.key_exists(key) is False


def test_write_read_destroy_tmy3_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    store = monkeypatch_key_value_store
    key = get_tmy3_hourly_temp_data_cache_key("123456")
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    write_tmy3_hourly_temp_data_to_cache("123456", ts1)
    assert store.key_exists(key) is True

    ts2 = read_tmy3_hourly_temp_data_from_cache("123456")
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    destroy_cached_tmy3_hourly_temp_data("123456")
    assert store.key_exists(key) is False


def test_write_read_destroy_cz2010_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    store = monkeypatch_key_value_store
    key = get_cz2010_hourly_temp_data_cache_key("123456")
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    write_cz2010_hourly_temp_data_to_cache("123456", ts1)
    assert store.key_exists(key) is True

    ts2 = read_cz2010_hourly_temp_data_from_cache("123456")
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    destroy_cached_cz2010_hourly_temp_data("123456")
    assert store.key_exists(key) is False


# station write read destroy
def test_isd_station_write_read_destroy_isd_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    store = monkeypatch_key_value_store
    key = station.get_isd_hourly_temp_data_cache_key(1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    station.write_isd_hourly_temp_data_to_cache(1990, ts1)
    assert store.key_exists(key) is True

    ts2 = station.read_isd_hourly_temp_data_from_cache(1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    station.destroy_cached_isd_hourly_temp_data(1990)
    assert store.key_exists(key) is False


def test_isd_station_write_read_destroy_isd_daily_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    store = monkeypatch_key_value_store
    key = station.get_isd_daily_temp_data_cache_key(1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    station.write_isd_daily_temp_data_to_cache(1990, ts1)
    assert store.key_exists(key) is True

    ts2 = station.read_isd_daily_temp_data_from_cache(1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    station.destroy_cached_isd_daily_temp_data(1990)
    assert store.key_exists(key) is False


def test_isd_station_write_read_destroy_gsod_daily_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = ISDStation("722874")
    store = monkeypatch_key_value_store
    key = station.get_gsod_daily_temp_data_cache_key(1990)
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    station.write_gsod_daily_temp_data_to_cache(1990, ts1)
    assert store.key_exists(key) is True

    ts2 = station.read_gsod_daily_temp_data_from_cache(1990)
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    station.destroy_cached_gsod_daily_temp_data(1990)
    assert store.key_exists(key) is False


def test_isd_station_write_read_destroy_tmy3_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = ISDStation("722880")
    store = monkeypatch_key_value_store
    key = station.get_tmy3_hourly_temp_data_cache_key()
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    station.write_tmy3_hourly_temp_data_to_cache(ts1)
    assert store.key_exists(key) is True

    ts2 = station.read_tmy3_hourly_temp_data_from_cache()
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    station.destroy_cached_tmy3_hourly_temp_data()
    assert store.key_exists(key) is False


def test_isd_station_write_read_destroy_cz2010_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = ISDStation("722880")
    store = monkeypatch_key_value_store
    key = station.get_cz2010_hourly_temp_data_cache_key()
    assert store.key_exists(key) is False

    ts1 = pd.Series([1], index=[pytz.UTC.localize(datetime(1990, 1, 1))])
    station.write_cz2010_hourly_temp_data_to_cache(ts1)
    assert store.key_exists(key) is True

    ts2 = station.read_cz2010_hourly_temp_data_from_cache()
    assert store.key_exists(key) is True
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape

    station.destroy_cached_cz2010_hourly_temp_data()
    assert store.key_exists(key) is False


# load cached proxy
def test_load_isd_hourly_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = load_isd_hourly_temp_data_cached_proxy("722874", 2007)
    ts2 = load_isd_hourly_temp_data_cached_proxy("722874", 2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_load_isd_daily_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = load_isd_daily_temp_data_cached_proxy("722874", 2007)
    ts2 = load_isd_daily_temp_data_cached_proxy("722874", 2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_load_gsod_daily_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = load_gsod_daily_temp_data_cached_proxy("722874", 2007)
    ts2 = load_gsod_daily_temp_data_cached_proxy("722874", 2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_load_tmy3_hourly_temp_data_cached_proxy(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = load_tmy3_hourly_temp_data_cached_proxy("722880", 2007)
    ts2 = load_tmy3_hourly_temp_data_cached_proxy("722880", 2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_load_cz2010_hourly_temp_data_cached_proxy(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = load_cz2010_hourly_temp_data_cached_proxy("722880", 2007)
    ts2 = load_cz2010_hourly_temp_data_cached_proxy("722880", 2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


# station load cached proxy
def test_isd_station_load_isd_hourly_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_isd_hourly_temp_data_cached_proxy(2007)
    ts2 = station.load_isd_hourly_temp_data_cached_proxy(2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_isd_station_load_isd_daily_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_isd_daily_temp_data_cached_proxy(2007)
    ts2 = station.load_isd_daily_temp_data_cached_proxy(2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_isd_station_load_gsod_daily_temp_data_cached_proxy(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_gsod_daily_temp_data_cached_proxy(2007)
    ts2 = station.load_gsod_daily_temp_data_cached_proxy(2007)
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_isd_station_load_tmy3_hourly_temp_data_cached_proxy(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_tmy3_hourly_temp_data_cached_proxy()
    ts2 = station.load_tmy3_hourly_temp_data_cached_proxy()
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_isd_station_load_cz2010_hourly_temp_data_cached_proxy(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_cz2010_hourly_temp_data_cached_proxy()
    ts2 = station.load_cz2010_hourly_temp_data_cached_proxy()
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


# load data between dates
def test_load_isd_hourly_temp_data(monkeypatch_noaa_ftp, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts, warnings = load_isd_hourly_temp_data("722874", start, end)
    assert ts.index[0] == start
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_load_isd_hourly_temp_data_non_normalized_dates(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)
    ts, warnings = load_isd_hourly_temp_data("722874", start, end)
    assert ts.index[0] == datetime(2006, 1, 3, 12, tzinfo=pytz.UTC)
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == datetime(2007, 4, 3, 12, tzinfo=pytz.UTC)
    assert pd.notnull(ts.iloc[-1])


def test_load_isd_daily_temp_data(monkeypatch_noaa_ftp, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = load_isd_daily_temp_data("722874", start, end)
    assert ts.index[0] == start
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_load_isd_daily_temp_data_non_normalized_dates(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)
    ts = load_isd_daily_temp_data("722874", start, end)
    assert ts.index[0] == datetime(2006, 1, 4, tzinfo=pytz.UTC)
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == datetime(2007, 4, 3, tzinfo=pytz.UTC)
    assert pd.notnull(ts.iloc[-1])


def test_load_gsod_daily_temp_data(monkeypatch_noaa_ftp, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = load_gsod_daily_temp_data("722874", start, end)
    assert ts.index[0] == start
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_load_gsod_daily_temp_data_non_normalized_dates(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)
    ts = load_gsod_daily_temp_data("722874", start, end)
    assert ts.index[0] == datetime(2006, 1, 4, tzinfo=pytz.UTC)
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == datetime(2007, 4, 3, tzinfo=pytz.UTC)
    assert pd.notnull(ts.iloc[-1])


def test_load_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = load_tmy3_hourly_temp_data("722880", start, end)
    assert ts.index[0] == start
    assert pd.notnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_load_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = load_cz2010_hourly_temp_data("722880", start, end)
    assert ts.index[0] == start
    assert pd.notnull(ts[1])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


# station load data between dates
def test_isd_station_load_isd_hourly_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts, warnings = station.load_isd_hourly_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


def test_isd_station_load_isd_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_isd_daily_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


def test_isd_station_load_gsod_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_gsod_daily_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


def test_isd_station_load_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_tmy3_hourly_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


def test_isd_station_load_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_cz2010_hourly_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


# load cached
def test_load_cached_isd_hourly_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    ts = load_cached_isd_hourly_temp_data("722874")
    assert ts is None

    # load data
    ts = load_isd_hourly_temp_data_cached_proxy("722874", 2007)
    assert int(ts.sum()) == 156160
    assert ts.shape == (8760,)

    ts = load_cached_isd_hourly_temp_data("722874")
    assert int(ts.sum()) == 156160
    assert ts.shape == (8760,)


def test_load_cached_isd_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    ts = load_cached_isd_daily_temp_data("722874")
    assert ts is None

    # load data
    ts = load_isd_daily_temp_data_cached_proxy("722874", 2007)
    assert int(ts.sum()) == 6510
    assert ts.shape == (365,)

    ts = load_cached_isd_daily_temp_data("722874")
    assert int(ts.sum()) == 6510
    assert ts.shape == (365,)


def test_load_cached_gsod_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    ts = load_cached_gsod_daily_temp_data("722874")
    assert ts is None

    # load data
    ts = load_gsod_daily_temp_data_cached_proxy("722874", 2007)
    assert int(ts.sum()) == 6509
    assert ts.shape == (365,)

    ts = load_cached_gsod_daily_temp_data("722874")
    assert int(ts.sum()) == 6509
    assert ts.shape == (365,)


def test_load_cached_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    ts = load_cached_tmy3_hourly_temp_data("722880")
    assert ts is None

    # load data
    ts = load_tmy3_hourly_temp_data_cached_proxy("722880")
    assert int(ts.sum()) == 156194
    assert ts.shape == (8760,)

    ts = load_cached_tmy3_hourly_temp_data("722880")
    assert int(ts.sum()) == 156194
    assert ts.shape == (8760,)


def test_load_cached_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    ts = load_cached_cz2010_hourly_temp_data("722880")
    assert ts is None

    # load data
    ts = load_cz2010_hourly_temp_data_cached_proxy("722880")
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)

    ts = load_cached_cz2010_hourly_temp_data("722880")
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)


# station load cached
def test_isd_station_load_cached_isd_hourly_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    ts = station.load_cached_isd_hourly_temp_data()
    assert ts is None

    # load data
    ts = station.load_isd_hourly_temp_data_cached_proxy(2007)
    assert int(ts.sum()) == 156160
    assert ts.shape == (8760,)

    ts = station.load_cached_isd_hourly_temp_data()
    assert int(ts.sum()) == 156160
    assert ts.shape == (8760,)


def test_isd_station_load_cached_isd_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    ts = station.load_cached_isd_daily_temp_data()
    assert ts is None

    # load data
    ts = station.load_isd_daily_temp_data_cached_proxy(2007)
    assert int(ts.sum()) == 6510
    assert ts.shape == (365,)

    ts = station.load_cached_isd_daily_temp_data()
    assert int(ts.sum()) == 6510
    assert ts.shape == (365,)


def test_isd_station_load_cached_gsod_daily_temp_data(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    station = ISDStation("722874")

    ts = station.load_cached_gsod_daily_temp_data()
    assert ts is None

    # load data
    ts = station.load_gsod_daily_temp_data_cached_proxy(2007)
    assert int(ts.sum()) == 6509
    assert ts.shape == (365,)

    ts = station.load_cached_gsod_daily_temp_data()
    assert int(ts.sum()) == 6509
    assert ts.shape == (365,)


def test_isd_station_load_cached_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")

    ts = station.load_cached_tmy3_hourly_temp_data()
    assert ts is None

    # load data
    ts = station.load_tmy3_hourly_temp_data_cached_proxy()
    assert int(ts.sum()) == 156194
    assert ts.shape == (8760,)

    ts = station.load_cached_tmy3_hourly_temp_data()
    assert int(ts.sum()) == 156194
    assert ts.shape == (8760,)


def test_isd_station_load_cached_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")

    ts = station.load_cached_cz2010_hourly_temp_data()
    assert ts is None

    # load data
    ts = station.load_cz2010_hourly_temp_data_cached_proxy()
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)

    ts = station.load_cached_cz2010_hourly_temp_data()
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)


# test slicing of normalized data
def test_load_correctly_sliced_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2015, 2, 15, tzinfo=pytz.UTC)
    end = datetime(2016, 8, 12, tzinfo=pytz.UTC)

    ts = load_tmy3_hourly_temp_data("722880", start, end)
    ts_orig = fetch_tmy3_hourly_temp_data("722880")

    for i in ts.index:
        # leap day is null
        if i.month == 2 and i.day == 29:
            assert pd.isnull(ts[i])
        else:
            assert ts[i] == ts_orig[i.replace(year=1900)]


def test_load_correctly_sliced_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    start = datetime(2015, 2, 15, tzinfo=pytz.UTC)
    end = datetime(2016, 8, 12, tzinfo=pytz.UTC)

    ts = load_cz2010_hourly_temp_data("722880", start, end)
    ts_orig = fetch_cz2010_hourly_temp_data("722880")

    for i in ts.index:
        # leap day is null
        if i.month == 2 and i.day == 29:
            assert pd.isnull(ts[i])
        else:
            assert ts[i] == ts_orig[i.replace(year=1900)]


def test_isd_station_load_isd_hourly_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_isd_hourly_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_isd_hourly_temp_data(start, end)


def test_isd_station_load_isd_daily_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_isd_daily_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_isd_daily_temp_data(start, end)


def test_isd_station_load_gsod_daily_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_gsod_daily_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_gsod_daily_temp_data(start, end)


def test_isd_station_load_tmy3_hourly_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_tmy3_hourly_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_tmy3_hourly_temp_data(start, end)


def test_isd_station_load_cz2010_hourly_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = ISDStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_cz2010_hourly_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_cz2010_hourly_temp_data(start, end)


def test_isd_station_metadata_null_elevation():
    usaf_id = "724953"
    metadata = get_isd_station_metadata(usaf_id)
    assert metadata["elevation"] is None
    isd_station = ISDStation(usaf_id)
    assert isd_station.elevation is None


def test_load_isd_hourly_temp_data_missing_years(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    usaf_id = "722874"
    start = datetime(2005, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)
    with pytest.raises(ISDDataNotAvailableError):
        ts = load_isd_hourly_temp_data(usaf_id, start, end, error_on_missing_years=True)
    ts, warnings = load_isd_hourly_temp_data(
        usaf_id, start, end, error_on_missing_years=False
    )
    assert ts.index[0] == start
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_isd_station_load_isd_hourly_temp_data_missing_years(
    monkeypatch_noaa_ftp, monkeypatch_key_value_store
):
    usaf_id = "722874"
    start = datetime(2005, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)
    isd_station = ISDStation(usaf_id)
    with pytest.raises(ISDDataNotAvailableError):
        isd_station.load_isd_hourly_temp_data(start, end, error_on_missing_years=True)
    ts, warnings = isd_station.load_isd_hourly_temp_data(
        start, end, error_on_missing_years=False
    )
    assert ts.index[0] == start
    assert pd.isnull(ts.iloc[0])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])
