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
import io
import time

import pandas as pd
import requests



API_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

API_REQUEST_TRIES = 3

API_RETRY_BACKOFF_SECONDS = 5

DATASET = "global-historical-climatology-network-hourly"

DEFAULT_VARIABLES = ("temperature",)


def _get_api_request_params(ghcn_id, year, variables):
    params = {
        "dataset": DATASET,
        # DATE is only included in the response when explicitly requested
        "dataTypes": ",".join(("DATE",) + tuple(variables)),
        "stations": ghcn_id,
        "startDate": "{}-01-01".format(year),
        "endDate": "{}-12-31".format(year),
    }

    return params


def fetch_ghcnh_hourly(ghcn_id, year, variables=DEFAULT_VARIABLES):
    """Fetch one year of GHCNh observations for a station.

    The request is retried on connection and http errors, as the api has
    been shown to intermittently fail.

    Parameters
    ----------
    ghcn_id : str
        GHCNh station id, e.g. ``'USW00023234'``.
    year : int
        Calendar year to fetch.
    variables : tuple of str
        GHCNh variable names, e.g. ``('temperature', 'wind_speed')``.
        Temperatures are degrees Celsius; units for other variables follow
        the GHCNh documentation.

    Returns
    -------
    pandas.DataFrame
        One column per requested variable, indexed by UTC observation time.
        Observations sharing a timestamp are averaged. Values the station
        did not report are NaN. Empty when the station has no data for the
        year.
    """
    params = _get_api_request_params(ghcn_id, year, variables)

    for attempt in range(API_REQUEST_TRIES):
        try:
            resp = requests.get(url=API_URL, params=params)
            resp.raise_for_status()
        except requests.RequestException:
            if attempt == API_REQUEST_TRIES - 1:
                raise
            # the api intermittently returns 5xx bursts; immediate retries
            # land inside the burst
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
        else:
            break

    empty_index = pd.DatetimeIndex([], tz="UTC")
    if resp.text.strip() == "":
        return pd.DataFrame(columns=list(variables), index=empty_index, dtype=float)

    raw = pd.read_csv(io.StringIO(resp.text), dtype=str)
    if len(raw) == 0:
        return pd.DataFrame(columns=list(variables), index=empty_index, dtype=float)

    index = pd.to_datetime(raw["DATE"]).dt.tz_localize("UTC").rename(None)
    df = pd.DataFrame(index=index)
    for variable in variables:
        if variable in raw.columns:
            df[variable] = pd.to_numeric(raw[variable], errors="coerce").values
        else:
            df[variable] = float("nan")

    df = df.groupby(df.index).mean()
    df = df.sort_index()

    return df
