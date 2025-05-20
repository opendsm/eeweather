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

from eeweather import (
    EEWeatherError,
    UnrecognizedUSAFIDError,
    UnrecognizedZCTAError,
    ISDDataNotAvailableError,
    GSODDataNotAvailableError,
)


def test_eeweather_error():
    with pytest.raises(EEWeatherError) as excinfo:
        raise EEWeatherError("message")
    assert excinfo.value.args[0] == "message"


def test_unrecognized_usaf_id_error():
    with pytest.raises(UnrecognizedUSAFIDError) as excinfo:
        raise UnrecognizedUSAFIDError("INVALID")
    assert excinfo.value.value == "INVALID"
    assert excinfo.value.message == (
        'The value "INVALID" was not recognized as a'
        " valid USAF weather station identifier."
    )


def test_unrecognized_zcta_error():
    with pytest.raises(UnrecognizedZCTAError) as excinfo:
        raise UnrecognizedZCTAError("INVALID")
    assert excinfo.value.value == "INVALID"
    assert excinfo.value.message == (
        'The value "INVALID" was not recognized as a valid ZCTA identifier.'
    )


def test_isd_data_does_not_exist_error():
    with pytest.raises(ISDDataNotAvailableError) as excinfo:
        raise ISDDataNotAvailableError("123456", 1800)
    assert excinfo.value.usaf_id == "123456"
    assert excinfo.value.year == 1800
    assert excinfo.value.message == (
        'ISD data does not exist for station "123456" in year 1800.'
    )


def test_gsod_data_does_not_exist_error():
    with pytest.raises(GSODDataNotAvailableError) as excinfo:
        raise GSODDataNotAvailableError("123456", 1800)
    assert excinfo.value.usaf_id == "123456"
    assert excinfo.value.year == 1800
    assert excinfo.value.message == (
        'GSOD data does not exist for station "123456" in year 1800.'
    )
