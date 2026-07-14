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

from eeweather.access_api import (
    API_REQUEST_TRIES,
    DatasetType,
    FileParseResult,
    _get_api_request_params,
    make_api_request,
)



FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _fixture_head(name, n_rows=1):
    """Header plus the first n_rows data rows of a captured api payload."""
    with gzip.open(FIXTURE_DIR / name, "rb") as f:
        lines = f.read().decode().strip().split("\n")

    return "\n".join(lines[: n_rows + 1]) + "\n"


class MockResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_file_parse_result_from_isd_file_path():
    result = FileParseResult.from_file_path("/pub/data/noaa/2007/722874-93134-2007.gz")

    assert result.dataset_type == DatasetType.ISD
    assert result.usaf_id == "722874"
    assert result.wban_id == "93134"
    assert result.year == 2007


def test_file_parse_result_from_gsod_file_path():
    result = FileParseResult.from_file_path(
        "/pub/data/gsod/2007/722874-93134-2007.op.gz"
    )

    assert result.dataset_type == DatasetType.GSOD
    assert result.usaf_id == "722874"
    assert result.wban_id == "93134"
    assert result.year == 2007


def test_file_parse_result_ambiguous_path_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        FileParseResult.from_file_path("/pub/data/gsod/noaa/722874-93134-2007.gz")


def test_file_parse_result_unrecognized_path_raises():
    with pytest.raises(ValueError, match="cannot be determined"):
        FileParseResult.from_file_path("/pub/data/other/722874-93134-2007.gz")


def test_get_api_request_params_unsupported_dataset_raises():
    with pytest.raises(ValueError, match="not supported"):
        _get_api_request_params("UNSUPPORTED", "722874", "93134", 2007)


def test_make_api_request_retries_then_raises(monkeypatch):
    calls = []

    def failing_get(url, params=None):
        calls.append(url)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("eeweather.access_api.requests.get", failing_get)

    with pytest.raises(requests.ConnectionError):
        make_api_request(DatasetType.ISD, "722874", "93134", 2007)

    assert len(calls) == API_REQUEST_TRIES


def test_make_api_request_succeeds_after_transient_failure(monkeypatch):
    # first captured 2007 observation for 722874 is +0150,5 -> 15.0 C
    payload = _fixture_head("global-hourly_72287493134_2007.csv.gz")
    calls = []

    def flaky_get(url, params=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("refused")

        return MockResponse(payload)

    monkeypatch.setattr("eeweather.access_api.requests.get", flaky_get)

    elements = make_api_request(DatasetType.ISD, "722874", "93134", 2007)

    assert len(calls) == 2
    assert len(elements) == 1
    assert elements[0][1] == pytest.approx(15.0, abs=1e-9)


def test_make_api_request_missing_isd_temp_parses_as_nan(monkeypatch):
    # 722874's 2025 observations report temperature as missing (+9999,9)
    payload = _fixture_head("global-hourly_72287493134_2025.csv.gz")

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.access_api.requests.get", mock_get)

    elements = make_api_request(DatasetType.ISD, "722874", "93134", 2025)

    assert len(elements) == 1
    assert elements[0][1] != elements[0][1]  # NaN


def test_make_api_request_gsod_converts_fahrenheit_to_celsius(monkeypatch):
    # first captured 2007 GSOD observation for 722874 is 56.0 F -> 13.333 C
    payload = _fixture_head("global-summary-of-the-day_72287493134_2007.csv.gz")

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.access_api.requests.get", mock_get)

    elements = make_api_request(DatasetType.GSOD, "722874", "93134", 2007)

    assert len(elements) == 1
    assert elements[0][1] == pytest.approx((56.0 - 32.0) * 5.0 / 9.0, abs=1e-9)


def test_make_api_request_malformed_isd_temp_raises(monkeypatch):
    # a captured observation with its scale suffix stripped; valid payloads
    # always carry a "value,quality" pair, so a bare value must be rejected
    payload = _fixture_head("global-hourly_72287493134_2007.csv.gz").replace(
        "+0150,5", "+0150"
    )

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.access_api.requests.get", mock_get)

    with pytest.raises(ValueError, match="unexpected temp value"):
        make_api_request(DatasetType.ISD, "722874", "93134", 2007)
