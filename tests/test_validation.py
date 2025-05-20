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
from eeweather.validation import valid_zcta_or_raise, valid_usaf_id_or_raise
from eeweather.exceptions import UnrecognizedZCTAError, UnrecognizedUSAFIDError
import pytest


def test_valid_zcta_or_raise_valid():
    assert valid_zcta_or_raise("90210") is True


def test_valid_zcta_or_raise_raise_error():
    with pytest.raises(UnrecognizedZCTAError) as excinfo:
        valid_zcta_or_raise("INVALID")
    assert excinfo.value.value == "INVALID"


def test_valid_usaf_id_or_raise_valid():
    assert valid_usaf_id_or_raise("722880") is True


def test_valid_usaf_id_or_raise_raise_error():
    with pytest.raises(UnrecognizedUSAFIDError) as excinfo:
        valid_usaf_id_or_raise("INVALID")
    assert excinfo.value.value == "INVALID"
