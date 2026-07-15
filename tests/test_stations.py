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
import contextlib
import pytest
import sqlite3
import pytz

from eeweather import (
    WeatherStation,
    get_ghcn_id,
    get_isd_station_metadata,
    get_isd_file_metadata,
    fetch_hourly_data,
    fetch_tmy3_hourly_temp_data,
    fetch_cz2010_hourly_temp_data,
    get_hourly_data_cache_key,
    get_tmy3_hourly_temp_data_cache_key,
    get_cz2010_hourly_temp_data_cache_key,
    cached_hourly_data_is_expired,
    validate_hourly_data_cache,
    validate_tmy3_hourly_temp_data_cache,
    validate_cz2010_hourly_temp_data_cache,
    serialize_hourly_data,
    serialize_tmy3_hourly_temp_data,
    serialize_cz2010_hourly_temp_data,
    deserialize_hourly_data,
    deserialize_tmy3_hourly_temp_data,
    deserialize_cz2010_hourly_temp_data,
    read_hourly_data_from_cache,
    read_tmy3_hourly_temp_data_from_cache,
    read_cz2010_hourly_temp_data_from_cache,
    write_hourly_data_to_cache,
    write_tmy3_hourly_temp_data_to_cache,
    write_cz2010_hourly_temp_data_to_cache,
    destroy_cached_hourly_data,
    destroy_cached_tmy3_hourly_temp_data,
    destroy_cached_cz2010_hourly_temp_data,
    load_hourly_data_cached_proxy,
    load_tmy3_hourly_temp_data_cached_proxy,
    load_cz2010_hourly_temp_data_cached_proxy,
    load_data,
    load_tmy3_hourly_temp_data,
    load_cz2010_hourly_temp_data,
    load_cached_hourly_data,
    load_cached_tmy3_hourly_temp_data,
    load_cached_cz2010_hourly_temp_data,
)
from eeweather.exceptions import (
    UnrecognizedUSAFIDError,
    DataNotAvailableError,
    TMY3DataNotAvailableError,
    CZ2010DataNotAvailableError,
    NonUTCTimezoneInfoError,
)
from eeweather.testing import (
    MockKeyValueStoreProxy,
    mock_request_text_tmy3,
    mock_request_text_cz2010,
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


def _backdate_cache_key(store, key, updated):
    with contextlib.closing(sqlite3.connect(store._path)) as conn, conn:
        conn.execute(
            "update items set updated = ? where key = ?", (updated.isoformat(), key)
        )



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
        "ghcn_id": "USW00093134",
        "ghcn_map_method": "icao",
        "quality": "low",
        "recent_wban_id": "93134",
        "state": "CA",
        "usaf_id": "722874",
        "wban_ids": "93134",
    }


def test_isd_station_no_load_metadata():
    station = WeatherStation("722880", load_metadata=False)
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
    assert repr(station) == "WeatherStation('722880')"


def test_isd_station_no_load_metadata_invalid():
    with pytest.raises(UnrecognizedUSAFIDError):
        station = WeatherStation("FAKE", load_metadata=False)


def test_isd_station_with_load_metadata():
    station = WeatherStation("722880", load_metadata=True)
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
    station = WeatherStation("722880", load_metadata=True)
    assert station.json() == {
        "elevation": 222.7,
        "icao_code": "KBUR",
        "latitude": 34.2,
        "longitude": -118.365,
        "name": "BURBANK-GLENDALE-PASA ARPT",
        "quality": "high",
        "recent_wban_id": "23152",
        "ghcn_id": "USW00023152",
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
        station = WeatherStation("FAKE", load_metadata=True)


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
    station = WeatherStation("722874")
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


def test_fetch_tmy3_hourly_temp_data(monkeypatch_tmy3_request):
    data = fetch_tmy3_hourly_temp_data("722880")
    assert data.sum() == pytest.approx(156194.3, 0.00001)
    assert data.shape == (8760,)


def test_fetch_cz2010_hourly_temp_data(monkeypatch_cz2010_request):
    data = fetch_cz2010_hourly_temp_data("722880")
    assert data.sum() == pytest.approx(153430.9, 0.00001)
    assert data.shape == (8760,)


def test_tmy3_station_hourly_temp_data(monkeypatch_tmy3_request):
    station = WeatherStation("722880")
    data = station.fetch_tmy3_hourly_temp_data()
    assert data.sum() == pytest.approx(156194.3, 0.00001)
    assert data.shape == (8760,)


def test_cz2010_station_hourly_temp_data(monkeypatch_cz2010_request):
    station = WeatherStation("722880")
    data = station.fetch_cz2010_hourly_temp_data()
    assert data.sum() == pytest.approx(153430.9, 0.00001)
    assert data.shape == (8760,)


def test_fetch_tmy3_hourly_temp_data_invalid():
    with pytest.raises(TMY3DataNotAvailableError):
        fetch_tmy3_hourly_temp_data("INVALID")


def test_fetch_cz2010_hourly_temp_data_invalid():
    with pytest.raises(CZ2010DataNotAvailableError):
        fetch_cz2010_hourly_temp_data("INVALID")


def test_fetch_tmy3_hourly_temp_data_not_in_tmy3_list():
    with pytest.raises(TMY3DataNotAvailableError):
        fetch_tmy3_hourly_temp_data("722874")


def test_fetch_cz2010_hourly_temp_data_not_in_cz2010_list(monkeypatch_cz2010_request):
    data = fetch_cz2010_hourly_temp_data("722880")
    assert data.sum() == 153430.90000000002
    assert data.shape == (8760,)
    with pytest.raises(CZ2010DataNotAvailableError):
        fetch_cz2010_hourly_temp_data("725340")


def test_get_tmy3_hourly_temp_data_cache_key():
    assert get_tmy3_hourly_temp_data_cache_key("722880") == "tmy3-hourly-722880"


def test_get_cz2010_hourly_temp_data_cache_key():
    assert get_cz2010_hourly_temp_data_cache_key("722880") == "cz2010-hourly-722880"


def test_tmy3_station_get_isd_hourly_temp_data_cache_key():
    station = WeatherStation("722880")
    assert station.get_tmy3_hourly_temp_data_cache_key() == "tmy3-hourly-722880"


def test_cz2010_station_get_isd_hourly_temp_data_cache_key():
    station = WeatherStation("722880")
    assert station.get_cz2010_hourly_temp_data_cache_key() == "cz2010-hourly-722880"


def test_validate_tmy3_hourly_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_tmy3_hourly_temp_data_cache("722880") is False


def test_validate_cz2010_hourly_temp_data_cache_empty(monkeypatch_key_value_store):
    assert validate_cz2010_hourly_temp_data_cache("722880") is False


def test_isd_station_validate_tmy3_hourly_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = WeatherStation("722880")
    assert station.validate_tmy3_hourly_temp_data_cache() is False


def test_isd_station_validate_cz2010_hourly_temp_data_cache_empty(
    monkeypatch_key_value_store,
):
    station = WeatherStation("722880")
    assert station.validate_cz2010_hourly_temp_data_cache() is False


def test_raise_on_missing_tmy3_hourly_temp_data_cache_data_no_web_fetch(
    mock_api_transport, monkeypatch_key_value_store
):
    with pytest.raises(TMY3DataNotAvailableError):
        load_tmy3_hourly_temp_data_cached_proxy("722874", fetch_from_web=False)


def test_raise_on_missing_cz2010_hourly_temp_data_cache_data_no_web_fetch(
    mock_api_transport, monkeypatch_key_value_store
):
    with pytest.raises(CZ2010DataNotAvailableError):
        load_cz2010_hourly_temp_data_cached_proxy("722874", fetch_from_web=False)


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


def test_serialize_tmy3_hourly_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_tmy3_hourly_temp_data(ts) == [["2017010100", 1]]


def test_serialize_cz2010_hourly_temp_data():
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert serialize_cz2010_hourly_temp_data(ts) == [["2017010100", 1]]


def test_isd_station_serialize_tmy3_hourly_temp_data():
    station = WeatherStation("722880")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_tmy3_hourly_temp_data(ts) == [["2017010100", 1]]


def test_isd_station_serialize_cz2010_hourly_temp_data():
    station = WeatherStation("722880")
    ts = pd.Series([1], index=[pytz.UTC.localize(datetime(2017, 1, 1))])
    assert station.serialize_cz2010_hourly_temp_data(ts) == [["2017010100", 1]]


def test_deserialize_tmy3_hourly_temp_data():
    ts = deserialize_tmy3_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_deserialize_cz2010_hourly_temp_data():
    ts = deserialize_cz2010_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_isd_station_deserialize_tmy3_hourly_temp_data():
    station = WeatherStation("722880")
    ts = station.deserialize_tmy3_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


def test_isd_station_deserialize_cz2010_hourly_temp_data():
    station = WeatherStation("722880")
    ts = station.deserialize_cz2010_hourly_temp_data([["2017010100", 1]])
    assert ts.sum() == 1
    assert ts.index.freq.name == "h"


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


def test_isd_station_write_read_destroy_tmy3_hourly_temp_data_to_from_cache(
    monkeypatch_key_value_store,
):
    station = WeatherStation("722880")
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
    station = WeatherStation("722880")
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


def test_isd_station_load_tmy3_hourly_temp_data_cached_proxy(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_tmy3_hourly_temp_data_cached_proxy()
    ts2 = station.load_tmy3_hourly_temp_data_cached_proxy()
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


def test_isd_station_load_cz2010_hourly_temp_data_cached_proxy(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")

    # doesn't yet guarantee that all code paths are taken,
    # except that coverage picks it up either here or elsewhere
    ts1 = station.load_cz2010_hourly_temp_data_cached_proxy()
    ts2 = station.load_cz2010_hourly_temp_data_cached_proxy()
    assert int(ts1.sum()) == int(ts2.sum())
    assert ts1.shape == ts2.shape


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
    assert pd.notnull(ts.iloc[1])
    assert ts.index[-1] == end
    assert pd.notnull(ts.iloc[-1])


def test_isd_station_load_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_tmy3_hourly_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


def test_isd_station_load_cz2010_hourly_temp_data(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")
    start = datetime(2007, 3, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)
    ts = station.load_cz2010_hourly_temp_data(start, end)
    assert ts.index[0] == start
    assert ts.index[-1] == end


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


def test_isd_station_load_cached_tmy3_hourly_temp_data(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")

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
    station = WeatherStation("722880")

    ts = station.load_cached_cz2010_hourly_temp_data()
    assert ts is None

    # load data
    ts = station.load_cz2010_hourly_temp_data_cached_proxy()
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)

    ts = station.load_cached_cz2010_hourly_temp_data()
    assert int(ts.sum()) == 153430
    assert ts.shape == (8760,)


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


def test_isd_station_load_tmy3_hourly_temp_data_tz_exception(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    station = WeatherStation("722880")
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
    station = WeatherStation("722880")
    start = datetime(2007, 4, 10)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_cz2010_hourly_temp_data(start, end)

    start = datetime(2007, 4, 10, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 12)
    with pytest.raises(NonUTCTimezoneInfoError):
        ts = station.load_cz2010_hourly_temp_data(start, end)


def test_isd_station_metadata_null_elevation():
    usaf_id = "722246"
    metadata = get_isd_station_metadata(usaf_id)
    assert metadata["elevation"] is None
    isd_station = WeatherStation(usaf_id)
    assert isd_station.elevation is None


# ghcn id lookup
def test_get_ghcn_id():
    assert get_ghcn_id("722874") == "USW00093134"


def test_get_ghcn_id_unrecognized():
    with pytest.raises(UnrecognizedUSAFIDError):
        get_ghcn_id("FAKE")


# fetch
def test_fetch_hourly_data(mock_api_transport):
    df = fetch_hourly_data("722874", 2007)

    assert list(df.columns) == ["temperature"]
    assert df.shape == (8760, 1)
    assert df.index[0] == datetime(2007, 1, 1, tzinfo=pytz.UTC)
    assert df.temperature.sum() == pytest.approx(156159.5455, abs=1e-3)


def test_fetch_hourly_data_multiple_variables(mock_api_transport):
    df = fetch_hourly_data(
        "722874", 2007, variables=("temperature", "relative_humidity")
    )

    assert list(df.columns) == ["temperature", "relative_humidity"]
    assert df.shape == (8760, 2)


def test_fetch_hourly_data_invalid_station():
    with pytest.raises(UnrecognizedUSAFIDError):
        fetch_hourly_data("FAKE", 2007)


def test_fetch_hourly_data_missing_year_raises(mock_api_transport):
    with pytest.raises(DataNotAvailableError):
        fetch_hourly_data("722874", 1800)


def test_weather_station_fetch_hourly_data(mock_api_transport):
    station = WeatherStation("722874")
    df = fetch_hourly_data(station.usaf_id, 2007)

    assert df.shape == (8760, 1)


# cache keys
def test_get_hourly_data_cache_key():
    assert get_hourly_data_cache_key("722874", 2007) == "ghcnh-hourly-722874-2007"


# cache expiry
def test_cached_hourly_data_is_expired_empty(monkeypatch_key_value_store):
    assert cached_hourly_data_is_expired("722874", 2007) is True


def test_cached_hourly_data_is_expired_false(
    mock_api_transport, monkeypatch_key_value_store
):
    load_hourly_data_cached_proxy("722874", 2007)

    assert cached_hourly_data_is_expired("722874", 2007) is False


def test_cached_hourly_data_is_expired_true(
    mock_api_transport, monkeypatch_key_value_store
):
    load_hourly_data_cached_proxy("722874", 2007)

    # manually expire key value item
    key = get_hourly_data_cache_key("722874", 2007)
    _backdate_cache_key(
        monkeypatch_key_value_store, key, pytz.UTC.localize(datetime(2007, 3, 3))
    )

    assert cached_hourly_data_is_expired("722874", 2007) is True


# validate cache
def test_validate_hourly_data_cache_empty(monkeypatch_key_value_store):
    assert validate_hourly_data_cache("722874", 2007) is False


def test_validate_hourly_data_cache_updated_recently(
    mock_api_transport, monkeypatch_key_value_store
):
    load_hourly_data_cached_proxy("722874", 2007)

    assert validate_hourly_data_cache("722874", 2007) is True


def test_validate_hourly_data_cache_expired(
    mock_api_transport, monkeypatch_key_value_store
):
    load_hourly_data_cached_proxy("722874", 2007)

    key = get_hourly_data_cache_key("722874", 2007)
    _backdate_cache_key(
        monkeypatch_key_value_store, key, pytz.UTC.localize(datetime(2007, 3, 3))
    )

    # expired cache entries are cleared on validation
    assert validate_hourly_data_cache("722874", 2007) is False
    assert monkeypatch_key_value_store.key_exists(key) is False


def test_raise_on_missing_hourly_data_cache_no_web_fetch(monkeypatch_key_value_store):
    with pytest.raises(DataNotAvailableError):
        load_hourly_data_cached_proxy("722874", 2007, fetch_from_web=False)


# serialization round-trips
def test_serialize_deserialize_hourly_data_round_trip(mock_api_transport):
    df = fetch_hourly_data("722874", 2007)

    serialized = serialize_hourly_data(df)

    assert serialized["columns"] == ["temperature"]
    assert serialized["rows"][0][0] == "2007010100"
    assert len(serialized["rows"]) == len(df)

    round_tripped = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_hourly_data_nan_round_trips_as_null(mock_api_transport):
    df = fetch_hourly_data("723826", 2013)  # data ends 2013-11-04

    serialized = serialize_hourly_data(df)

    assert any(row[1] is None for row in serialized["rows"])

    round_tripped = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_multivariable_round_trip(mock_api_transport):
    df = fetch_hourly_data(
        "722874", 2007, variables=("temperature", "wind_speed")
    )

    round_tripped = deserialize_hourly_data(serialize_hourly_data(df))

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


# write read destroy
def test_write_read_destroy_hourly_data_to_from_cache(
    mock_api_transport, monkeypatch_key_value_store
):
    store = monkeypatch_key_value_store
    key = get_hourly_data_cache_key("722874", 2007)
    assert store.key_exists(key) is False

    df = fetch_hourly_data("722874", 2007)
    write_hourly_data_to_cache("722874", 2007, df)
    assert store.key_exists(key) is True

    round_tripped = read_hourly_data_from_cache("722874", 2007)
    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)

    destroy_cached_hourly_data("722874", 2007)
    assert store.key_exists(key) is False


# cached proxy
def test_load_hourly_data_cached_proxy(mock_api_transport, monkeypatch_key_value_store):
    # doesn't yet exist in cache, so fetched
    df1 = load_hourly_data_cached_proxy("722874", 2007)

    # now exists in cache, so read
    df2 = load_hourly_data_cached_proxy("722874", 2007)

    pd.testing.assert_frame_equal(df1, df2, check_freq=False)


def test_load_hourly_data_cached_proxy_variable_superset_refetches(
    mock_api_transport, monkeypatch_key_value_store
):
    df1 = load_hourly_data_cached_proxy("722874", 2007)
    assert list(df1.columns) == ["temperature"]

    # cache holds temperature only, so requesting more refetches the union
    df2 = load_hourly_data_cached_proxy(
        "722874", 2007, variables=("temperature", "wind_speed")
    )
    assert list(df2.columns) == ["temperature", "wind_speed"]

    # the refreshed cache entry now covers both variables
    cached = read_hourly_data_from_cache("722874", 2007)
    assert set(cached.columns) == {"temperature", "wind_speed"}

    # a temperature-only request serves the requested subset from cache
    df3 = load_hourly_data_cached_proxy("722874", 2007)
    assert list(df3.columns) == ["temperature"]


# load data between dates
def test_load_data_hourly(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end)

    assert df.index[0] == start
    assert df.index[-1] == end
    assert len(df) == 10921
    assert int(df.temperature.notna().sum()) == 10893
    assert warnings == []


def test_load_data_hourly_non_normalized_dates(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end)

    assert df.index[0] == datetime(2006, 1, 3, 12, tzinfo=pytz.UTC)
    assert df.index[-1] == datetime(2007, 4, 3, 12, tzinfo=pytz.UTC)


def test_load_data_daily(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end, frequency="daily")

    assert df.index[0] == start
    assert df.index[-1] == end
    assert len(df) == 456
    assert int(df.temperature.notna().sum()) == 456
    assert warnings == []


def test_load_data_daily_non_normalized_dates(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end, frequency="daily")

    assert df.index[0] == datetime(2006, 1, 4, tzinfo=pytz.UTC)
    assert df.index[-1] == datetime(2007, 4, 3, tzinfo=pytz.UTC)


def test_load_data_invalid_frequency(monkeypatch_key_value_store):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    with pytest.raises(ValueError, match="frequency"):
        load_data("722874", start, end, frequency="weekly")


def test_load_data_tz_exception():
    start = datetime(2007, 1, 1)
    end = datetime(2007, 4, 3)

    with pytest.raises(NonUTCTimezoneInfoError):
        load_data("722874", start, end)


def test_load_data_multiple_variables(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2007, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 6, 30, tzinfo=pytz.UTC)

    df, warnings = load_data(
        "722874",
        start,
        end,
        variables=("temperature", "relative_humidity", "wind_speed"),
    )

    assert df.shape == (697, 3)
    assert df.temperature.mean() == pytest.approx(19.304219, abs=1e-5)
    assert df.relative_humidity.mean() == pytest.approx(67.903771, abs=1e-5)
    assert df.wind_speed.mean() == pytest.approx(0.843799, abs=1e-5)
    assert warnings == []


# regression pins on real captured 2007 data
def test_load_data_hourly_2007_regression_values(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end)

    assert len(df) == 8737
    assert int(df.temperature.notna().sum()) == 8732
    assert df.temperature.mean() == pytest.approx(17.851812, abs=1e-5)
    assert warnings == []


def test_load_data_daily_2007_regression_values(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end, frequency="daily")

    assert len(df) == 365
    assert int(df.temperature.notna().sum()) == 365
    assert df.temperature.mean() == pytest.approx(17.835431, abs=1e-5)
    assert df.temperature.iloc[0] == pytest.approx(13.27734, abs=1e-5)


# cross-source consistency: the same requests served identical station-years
# from ISD before the GHCNh migration; pinned ISD values are from captured
# 2007 payloads. Tolerance derived from the ISD/GHCNh overlap validation.
def test_load_data_2007_consistent_with_isd_values(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)

    df, _ = load_data("722874", start, end)
    daily, _ = load_data("722874", start, end, frequency="daily")

    isd_hourly_2007_mean = 17.851869
    isd_daily_2007_mean = 17.835623
    assert df.temperature.mean() == pytest.approx(isd_hourly_2007_mean, abs=0.01)
    assert daily.temperature.mean() == pytest.approx(isd_daily_2007_mean, abs=0.01)


# truncated data warns: station 723826 was decommissioned 2013-11-04
def test_load_data_warns_on_truncated_data(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2013, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2013, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("723826", start, end)

    assert len(df) == 5113
    assert int(df.temperature.notna().sum()) == 1619
    assert df.temperature.last_valid_index() == datetime(
        2013, 11, 4, 19, tzinfo=pytz.UTC
    )
    assert [w.qualified_name for w in warnings] == ["eeweather.data_truncated"]
    assert warnings[0].data["variable"] == "temperature"
    assert warnings[0].data["last_valid"] == "2013-11-04T19:00:00+00:00"


def test_load_data_daily_warns_on_truncated_data(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2013, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2013, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("723826", start, end, frequency="daily")

    assert len(df) == 214
    assert int(df.temperature.notna().sum()) == 156
    assert [w.qualified_name for w in warnings] == ["eeweather.data_truncated"]


# station 720193's 2019 data has a real mid-year outage
def test_load_data_warns_on_internal_gap(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2019, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2019, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("720193", start, end)

    assert len(df) == 8737
    assert int(df.temperature.notna().sum()) == 8106
    assert [w.qualified_name for w in warnings] == ["eeweather.data_gap"]
    assert warnings[0].data["max_gap_days"] == pytest.approx(16.125, abs=1e-9)


# GHCNh continues past the ISD end-of-life: station 724940's 2025 data runs
# through the year while its ISD record stopped 2025-08-27
def test_load_data_2025_extends_past_isd_end_of_life(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2025, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2025, 10, 1, tzinfo=pytz.UTC)

    df, warnings = load_data("724940", start, end)

    assert len(df) == 2929
    assert int(df.temperature.notna().sum()) == 2840
    assert df.temperature.last_valid_index() == end
    assert warnings == []


# missing years
def test_load_data_missing_year_strict_raises(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2050, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2050, 6, 1, tzinfo=pytz.UTC)

    with pytest.raises(DataNotAvailableError):
        load_data("722874", start, end)


def test_load_data_missing_year_tolerant_returns_nan_range(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2050, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2050, 6, 1, tzinfo=pytz.UTC)

    df, warnings = load_data(
        "722874", start, end, error_on_missing_years=False
    )

    assert df.index[0] == start
    assert df.index[-1] == end
    assert df.temperature.isna().all()
    assert [w.qualified_name for w in warnings] == [
        "eeweather.data_not_available",
        "eeweather.no_data_in_requested_range",
    ]


# station 722874 has no GHCNh observations at all in 2025
def test_load_data_year_with_no_observations(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2025, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2025, 6, 1, tzinfo=pytz.UTC)

    with pytest.raises(DataNotAvailableError):
        load_data("722874", start, end)

    df, warnings = load_data(
        "722874", start, end, error_on_missing_years=False
    )

    assert len(df) == 3625
    assert df.temperature.isna().all()
    assert [w.qualified_name for w in warnings] == [
        "eeweather.data_not_available",
        "eeweather.no_data_in_requested_range",
    ]


# a sub-hour range contains no aligned hours; returns empty without warning
def test_load_data_sub_hour_range_returns_empty(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 6, 1, 12, 30, tzinfo=pytz.UTC)
    end = datetime(2007, 6, 1, 12, 45, tzinfo=pytz.UTC)

    df, warnings = load_data("722874", start, end)

    assert len(df) == 0
    assert warnings == []


# station method
def test_weather_station_load_data(mock_api_transport, monkeypatch_key_value_store):
    station = WeatherStation("722874")
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = station.load_data(start, end)

    assert df.index[0] == start
    assert df.index[-1] == end
    assert list(df.columns) == ["temperature"]


# load cached
def test_load_cached_hourly_data(mock_api_transport, monkeypatch_key_value_store):
    assert load_cached_hourly_data("722874") is None

    df1, _ = load_data(
        "722874",
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 4, 3, tzinfo=pytz.UTC),
    )
    cached = load_cached_hourly_data("722874")

    assert cached is not None
    assert list(cached.columns) == ["temperature"]
    # the cache holds the full fetched year, not just the requested slice
    assert len(cached) == 8760


def test_weather_station_load_cached_data(
    mock_api_transport, monkeypatch_key_value_store
):
    station = WeatherStation("722874")
    station.load_data(
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 4, 3, tzinfo=pytz.UTC),
    )

    cached = station.load_cached_data()

    assert cached is not None
    assert len(cached) == 8760

    station.destroy_cached_hourly_data(2007)

    assert station.load_cached_data() is None
