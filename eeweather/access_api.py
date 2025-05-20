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
from __future__ import annotations

import pytz
import datetime
import csv
import io

import attrs
import requests
import retry


class DatasetType:
    ISD = "IDS"
    GSOD = "GSOD"


@attrs.define
class FileParseResult:
    """
    contains information about file that will be useful
    for api requests
    """

    dataset_type: str
    """ISD OR GSOD"""

    usaf_id: str
    wban_id: str
    year: int

    @classmethod
    def from_file_path(cls, file_path: str):
        """
        given a file path that refers to either an ISD or GSOD datafile,
        parse the relevant information needed to make the correct api request
        to retrieve the data.

        file formats should be similar to:

        GSOD -> '/pub/data/gsod/2025/690150-93121-2025.op.gz'
        ISD -> '/pub/data/noaa/2025/690150-93121-2025.gz'

        In both cases:
            - 690150 would refer to the usaf_id
            - 93121 would refer to the wban_id
            - 2025 would refer to the year

        File specific cases:
            - if gsod is found in the path its dataset type would be GSOD
            - if noaa is found in the path its dataset type would be ISD
        """

        dataset_type = None

        if "gsod" in file_path and "noaa" in file_path:
            raise ValueError(
                f"provided file_path contains both 'gsod' and 'noaa' making the dataset type to use ambiguous: {file_path}"
            )

        if "gsod" in file_path:
            dataset_type = DatasetType.GSOD

        if "noaa" in file_path:
            dataset_type = DatasetType.ISD

        if dataset_type is None:
            raise ValueError(
                f"provided file_path does not contain 'gsod' or 'noaa' so dataset_type cannot be determined: {file_path}"
            )

        file_name = file_path.split("/")[-1]
        file_name_no_ext = file_name.split(".")[0]

        file_name_dash_split = file_name_no_ext.split("-")
        usaf_id, wban_id, year = file_name_dash_split
        year = int(year)

        return FileParseResult(
            dataset_type=dataset_type, usaf_id=usaf_id, wban_id=wban_id, year=year
        )


def _get_api_request_params(dataset_type: str, usaf_id: str, wban_id: str, year: int):
    params = {}

    # DATE always seems to be included
    data_types = []
    if dataset_type == DatasetType.ISD:
        dataset = "global-hourly"
        data_types.append("TMP")
    elif dataset_type == DatasetType.GSOD:
        dataset = "global-summary-of-the-day"
        data_types.append("TEMP")
    else:
        raise ValueError("dataset_type not supported:", dataset_type)

    params["dataTypes"] = ",".join(data_types)
    params["dataset"] = dataset
    params["stations"] = f"{usaf_id}{wban_id}"
    params["startDate"] = f"{year}-01-01"
    params["endDate"] = f"{year}-12-31"

    return params


@retry.retry(tries=3)
def make_api_request(
    dataset_type: str, usaf_id: str, wban_id: str, year: int
) -> list[tuple[datetime.datetime, float]]:
    """
    makes api request to the access api when given the necessary information about
    the weather station to fetch data for.

    returns a list of tuples where the first element is the datetime and the second
    is the temperature that the datetime refers to
    """
    params = _get_api_request_params(
        dataset_type=dataset_type, usaf_id=usaf_id, wban_id=wban_id, year=year
    )

    resp = requests.get(
        url="https://www.ncei.noaa.gov/access/services/data/v1", params=params
    )

    resp.raise_for_status()

    csv_data = io.StringIO(resp.text)
    dict_reader = csv.DictReader(csv_data)

    elements: list[tuple[datetime.datetime, float]] = []
    for record in dict_reader:

        if dataset_type == DatasetType.GSOD:

            date, temp = record["DATE"], str(record["TEMP"]).strip()
            tempF = float(temp)
            tempC = (5.0 / 9.0) * (tempF - 32.0)
            parsed_dttm = pytz.UTC.localize(
                datetime.datetime.strptime(date, "%Y-%m-%d")
            )
            elements.append((parsed_dttm, tempC))

        if dataset_type == DatasetType.ISD:

            date, temp = record["DATE"], str(record["TMP"]).strip()
            temp_split = temp.split(",")

            parsed_dttm = pytz.UTC.localize(
                datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
            )

            if len(temp_split) != 2:
                raise ValueError("found unexpected temp value in ISD response", temp)

            temp_val, suffix = temp_split
            if suffix == "9" or temp_val == "+9999":
                parsed_temp = float("nan")
            else:
                parsed_temp = float(temp_val) / 10.0

            elements.append((parsed_dttm, parsed_temp))

    return elements
