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
import tempfile
from eeweather.cache import KeyValueStore, get_datetime_if_exists
from datetime import datetime
from datetime import UTC
import pytz

import pytest


@pytest.fixture
def s():
    return KeyValueStore("sqlite:///{}/cache.db".format(tempfile.mkdtemp()))


def test_key_value_store(s):
    # key 'a' does not exist yet
    assert s.key_exists("a") is False
    assert s.retrieve_json("a") is None
    assert s.key_updated("a") is None

    # create key 'a'
    s.save_json("a", {"b": [1, "two", 3.0]})
    assert s.key_exists("a") is True
    data = s.retrieve_json("a")
    assert len(data["b"]) == 3
    assert data["b"][0] == 1
    assert data["b"][1] == "two"
    assert data["b"][2] == 3.0
    dt1 = s.key_updated("a")
    assert dt1.date() == datetime.now(UTC).date()

    # update key 'a'
    s.save_json("a", ["updated"])
    data = s.retrieve_json("a")
    assert data[0] == "updated"

    # clear key 'a' (and everything)
    s.clear()
    assert s.key_exists("a") is False


def test_key_value_store_repr(s):
    assert repr(s) == 'KeyValueStore("{}")'.format(s.url)


def test_key_value_store_clear_single_key(s):
    # clear single key
    s.save_json("a", "b")
    s.save_json("b", "c")
    assert s.key_exists("a") is True
    assert s.key_exists("b") is True
    s.clear("b")
    assert s.key_exists("a") is True
    assert s.key_exists("b") is False


def test_get_datetime_if_exists(s):
    data = None
    result = get_datetime_if_exists(data)
    assert result == None

    data = [datetime(2018, 1, 1)]
    result = get_datetime_if_exists(data)
    assert result == pytz.utc.localize(datetime(2018, 1, 1))

    data = [pytz.utc.localize(datetime(2018, 1, 1))]
    result = get_datetime_if_exists(data)
    assert result == pytz.utc.localize(datetime(2018, 1, 1))
