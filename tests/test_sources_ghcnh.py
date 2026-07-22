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
import gzip

from pathlib import Path

import pytest
import requests

from eeweather.sources.ghcnh import (
    API_REQUEST_TRIES,
    _get_api_request_params,
    fetch_ghcnh_hourly,
)



FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _fixture_text(name):
    with gzip.open(FIXTURE_DIR / name, "rb") as f:
        return f.read().decode()


class MockResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("eeweather.sources.ghcnh.time.sleep", sleeps.append)

    return sleeps


def test_get_api_request_params_includes_date():
    params = _get_api_request_params("USW00093134", 2007, ("temperature",))

    assert params["dataTypes"] == "DATE,temperature"
    assert params["stations"] == "USW00093134"
    assert params["startDate"] == "2007-01-01"
    assert params["endDate"] == "2007-12-31"


def test_fetch_retries_with_backoff_then_raises(monkeypatch, no_sleep):
    calls = []

    def failing_get(url, params=None):
        calls.append(url)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("eeweather.sources.ghcnh.requests.get", failing_get)

    with pytest.raises(requests.ConnectionError):
        fetch_ghcnh_hourly("USW00093134", 2007)

    assert len(calls) == API_REQUEST_TRIES
    # backs off between attempts, not after the final failure
    assert len(no_sleep) == API_REQUEST_TRIES - 1
    assert no_sleep[0] < no_sleep[1]


def test_fetch_succeeds_after_transient_failure(monkeypatch, no_sleep):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )
    calls = []

    def flaky_get(url, params=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("refused")

        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.requests.get", flaky_get)

    df = fetch_ghcnh_hourly("USW00093134", 2007)

    assert len(calls) == 2
    assert len(df) == 10884
    # first captured 2007 observation is 15.0 C at 00:47
    assert df.temperature.iloc[0] == pytest.approx(15.0, abs=1e-9)


def test_fetch_empty_year_returns_empty_frame(monkeypatch):
    def mock_get(url, params=None):
        return MockResponse("")

    monkeypatch.setattr("eeweather.sources.ghcnh.requests.get", mock_get)

    df = fetch_ghcnh_hourly("USW00093134", 1800)

    assert len(df) == 0
    assert list(df.columns) == ["temperature"]
    assert str(df.index.tz) == "UTC"


def test_fetch_unreported_variable_is_nan_column(monkeypatch):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.requests.get", mock_get)

    df = fetch_ghcnh_hourly(
        "USW00093134", 2007, ("temperature", "snow_depth")
    )

    assert list(df.columns) == ["temperature", "snow_depth"]
    assert df.snow_depth.isna().all()
    assert df.temperature.notna().sum() > 0


def test_fetch_averages_duplicate_timestamps(monkeypatch):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.requests.get", mock_get)

    df = fetch_ghcnh_hourly("USW00093134", 2007)

    assert df.index.is_unique
    assert df.index.is_monotonic_increasing
