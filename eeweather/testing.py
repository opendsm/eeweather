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
from io import BytesIO
import re
import tempfile

import eeweather.access_api
from eeweather.cache import KeyValueStore



def _resource_bytes(name):
    return files("eeweather.resources").joinpath(name).read_bytes()


def write_isd_file(bytes_string):
    bytes_string.write(_resource_bytes("ISD.gz"))


def write_tmy3_file():
    return _resource_bytes("722880TYA.CSV").decode("ascii")


def write_cz2010_file():
    return _resource_bytes("722880_CZ2010.CSV").decode("ascii")


def write_missing_isd_file(bytes_string):
    bytes_string.write(_resource_bytes("ISD-MISSING.gz"))


def write_nan_isd_file(bytes_string):
    bytes_string.write(_resource_bytes("ISD-NAN.gz"))


def write_gsod_file(bytes_string):
    bytes_string.write(_resource_bytes("GSOD.op.gz"))


def write_missing_gsod_file(bytes_string):
    bytes_string.write(_resource_bytes("GSOD-MISSING.op.gz"))


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


class MockNOAAFTPConnectionProxy:
    def read_file_as_bytes(self, filename):
        bytes_string = BytesIO()

        if re.match("/pub/data/noaa/2007/722874-93134-2007.gz", filename):
            write_isd_file(bytes_string)
        elif re.match("/pub/data/noaa/2006/722874-93134-2006.gz", filename):
            write_missing_isd_file(bytes_string)
        elif re.match("/pub/data/noaa/2013/994035-99999-2013.gz", filename):
            write_nan_isd_file(bytes_string)
        elif re.match("/pub/data/gsod/2007/722874-93134-2007.op.gz", filename):
            write_gsod_file(bytes_string)
        elif re.match("/pub/data/gsod/2006/722874-93134-2006.op.gz", filename):
            write_missing_gsod_file(bytes_string)

        bytes_string.seek(0)

        return bytes_string


class MockKeyValueStoreProxy:
    def __init__(self):
        # create a new test store in a temporary folder
        self.store = KeyValueStore("sqlite:///{}/cache.db".format(tempfile.mkdtemp()))

    def get_store(self):
        return self.store


_original_make_api_request = eeweather.access_api.make_api_request


def monkey_patch_make_api_request_return_empty(
    dataset_type: str, usaf_id: str, wban_id: str, year: int
):
    if usaf_id == "722874" and year == 2006 and dataset_type == "GSOD":
        single_nan_day = (
            datetime.datetime(2006, 1, 4, 0, 0, 0, tzinfo=pytz.UTC),
            float("nan"),
        )

        return [single_nan_day]

    if usaf_id == "722874" and year == 2006:
        return []

    if usaf_id == "722874" and year == 2005:
        single_naive_nan_day = (datetime.datetime(2005, 1, 1, 0, 0, 0), float("nan"))

        return [single_naive_nan_day]

    result = _original_make_api_request(
        dataset_type=dataset_type, usaf_id=usaf_id, wban_id=wban_id, year=year
    )

    return result


def monkey_patch_make_api_request_return_empty_v2(
    dataset_type: str, usaf_id: str, wban_id: str, year: int
):
    if usaf_id == "722874" and year == 2006:
        single_nan_day = (
            datetime.datetime(2006, 1, 4, 0, 0, 0, tzinfo=pytz.UTC),
            float("nan"),
        )

        return [single_nan_day]

    if usaf_id == "722874" and year == 2005:
        single_naive_nan_day = (datetime.datetime(2005, 1, 1, 0, 0, 0), float("nan"))

        return [single_naive_nan_day]

    if usaf_id == "994035":
        start_date = datetime.datetime(2013, 1, 1, 0, 0, 0)
        nan_hours = [
            (start_date + datetime.timedelta(hours=1) * i, float("nan"))
            for i in range(8611)
        ]

        return nan_hours

    result = _original_make_api_request(
        dataset_type=dataset_type, usaf_id=usaf_id, wban_id=wban_id, year=year
    )

    return result
