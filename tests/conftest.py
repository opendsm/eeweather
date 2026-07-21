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



FIXTURE_DIR = Path(__file__).parent / "fixtures"

ACCESS_API_URL = "https://www.ncei.noaa.gov/access/services/data/v1"


class MockAccessAPIResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def mock_api_transport(monkeypatch):
    """Serve captured NCEI access api payloads for all api requests.

    Fixture files are real responses recorded from the api, named
    {dataset}_{station}_{year}.csv.gz. A request with no matching fixture
    fails the test; no request reaches the network.
    """

    def mock_get(url, params=None, **kwargs):
        assert url == ACCESS_API_URL, "unexpected url: {}".format(url)
        name = "{}_{}_{}.csv.gz".format(
            params["dataset"], params["stations"], params["startDate"][:4]
        )
        path = FIXTURE_DIR / name
        if not path.exists():
            raise AssertionError(
                "no captured fixture for {}; tests must not hit the network".format(
                    name
                )
            )

        with gzip.open(path, "rb") as f:
            text = f.read().decode()

        return MockAccessAPIResponse(text)

    monkeypatch.setattr("eeweather.access_api.requests.get", mock_get)
