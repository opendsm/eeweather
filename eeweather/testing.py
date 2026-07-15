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
import datetime
import pytz

from importlib.resources import files
import re
import tempfile

from eeweather.cache import KeyValueStore



def _resource_bytes(name):
    return files("eeweather.resources").joinpath(name).read_bytes()


def write_tmy3_file():
    return _resource_bytes("722880TYA.CSV").decode("ascii")


def write_cz2010_file():
    return _resource_bytes("722880_CZ2010.CSV").decode("ascii")


def mock_request_text_tmy3(url):
    match_url = (
        "https://storage.googleapis.com/openeemeter-public-resources/"
        "tmy3_archive/722880TYA.CSV"
    )
    if re.match(match_url, url):
        return write_tmy3_file()


def mock_request_text_cz2010(url):
    match_url = "https://storage.googleapis.com/oee-cz2010/csv/722880_CZ2010.CSV"

    if re.match(match_url, url):
        return write_cz2010_file()


class MockKeyValueStoreProxy:
    def __init__(self):
        # create a new test store in a temporary folder
        self.store = KeyValueStore("sqlite:///{}/cache.db".format(tempfile.mkdtemp()))

    def get_store(self):
        return self.store
