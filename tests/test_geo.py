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
import pytest

from eeweather import get_version
from eeweather.geo import (
    get_lat_long_climate_zones,
    get_zcta_metadata,
    zcta_to_lat_long,
)
from eeweather.exceptions import UnrecognizedZCTAError, UnrecognizedUSAFIDError


def test_get_version():
    assert get_version() is not None


def test_get_zcta_metadata():
    metadata = get_zcta_metadata("90006")
    assert metadata == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "geometry": None,
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
        "latitude": "34.0480061236777",
        "longitude": "-118.294181179333",
        "state": "CA",
        "zcta_id": "90006",
    }

    with pytest.raises(UnrecognizedZCTAError) as excinfo:
        get_zcta_metadata("00000")
    assert excinfo.value.value == "00000"


def test_get_lat_long_climate_zones():
    climate_zones = get_lat_long_climate_zones(35.1, -119.2)
    assert climate_zones == {
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_13",
    }


def test_get_lat_long_climate_zones_out_of_range():
    climate_zones = get_lat_long_climate_zones(0, 0)
    assert climate_zones == {
        "iecc_climate_zone": None,
        "iecc_moisture_regime": None,
        "ba_climate_zone": None,
        "ca_climate_zone": None,
    }


def test_zcta_to_lat_long():
    with pytest.raises(UnrecognizedZCTAError) as excinfo:
        zcta_to_lat_long("00000")

    lat, lng = zcta_to_lat_long("70001")
    assert round(lat) == 30
    assert round(lng) == -90

    lat, lng = zcta_to_lat_long("94574")
    assert round(lat) == 39
    assert round(lng) == -122
