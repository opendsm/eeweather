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

import logging

from .__version__ import __title__, __description__, __url__, __version__
from .__version__ import __author__, __author_email__, __license__
from .__version__ import __copyright__
from .geo import get_lat_long_climate_zones, get_zcta_metadata, zcta_to_lat_long
from .database import build_metadata_db
from .exceptions import (
    EEWeatherError,
    UnrecognizedUSAFIDError,
    UnrecognizedZCTAError,
    ISDDataNotAvailableError,
    GSODDataNotAvailableError,
)
from .summaries import get_zcta_ids, get_isd_station_usaf_ids
from .ranking import rank_stations, combine_ranked_stations, select_station
from .stations import (
    ISDStation,
    get_isd_filenames,
    get_gsod_filenames,
    get_isd_station_metadata,
    get_isd_file_metadata,
    fetch_isd_raw_temp_data,
    fetch_isd_hourly_temp_data,
    fetch_isd_daily_temp_data,
    fetch_gsod_raw_temp_data,
    fetch_gsod_daily_temp_data,
    fetch_tmy3_hourly_temp_data,
    fetch_cz2010_hourly_temp_data,
    get_isd_hourly_temp_data_cache_key,
    get_isd_daily_temp_data_cache_key,
    get_gsod_daily_temp_data_cache_key,
    get_tmy3_hourly_temp_data_cache_key,
    get_cz2010_hourly_temp_data_cache_key,
    cached_isd_hourly_temp_data_is_expired,
    cached_isd_daily_temp_data_is_expired,
    cached_gsod_daily_temp_data_is_expired,
    validate_isd_hourly_temp_data_cache,
    validate_isd_daily_temp_data_cache,
    validate_gsod_daily_temp_data_cache,
    validate_tmy3_hourly_temp_data_cache,
    validate_cz2010_hourly_temp_data_cache,
    serialize_isd_hourly_temp_data,
    serialize_isd_daily_temp_data,
    serialize_gsod_daily_temp_data,
    serialize_tmy3_hourly_temp_data,
    serialize_cz2010_hourly_temp_data,
    deserialize_isd_hourly_temp_data,
    deserialize_isd_daily_temp_data,
    deserialize_gsod_daily_temp_data,
    deserialize_tmy3_hourly_temp_data,
    deserialize_cz2010_hourly_temp_data,
    read_isd_hourly_temp_data_from_cache,
    read_isd_daily_temp_data_from_cache,
    read_gsod_daily_temp_data_from_cache,
    read_tmy3_hourly_temp_data_from_cache,
    read_cz2010_hourly_temp_data_from_cache,
    write_isd_hourly_temp_data_to_cache,
    write_isd_daily_temp_data_to_cache,
    write_gsod_daily_temp_data_to_cache,
    write_tmy3_hourly_temp_data_to_cache,
    write_cz2010_hourly_temp_data_to_cache,
    destroy_cached_isd_hourly_temp_data,
    destroy_cached_isd_daily_temp_data,
    destroy_cached_gsod_daily_temp_data,
    destroy_cached_tmy3_hourly_temp_data,
    destroy_cached_cz2010_hourly_temp_data,
    load_isd_hourly_temp_data_cached_proxy,
    load_isd_daily_temp_data_cached_proxy,
    load_gsod_daily_temp_data_cached_proxy,
    load_tmy3_hourly_temp_data_cached_proxy,
    load_cz2010_hourly_temp_data_cached_proxy,
    load_isd_hourly_temp_data,
    load_isd_daily_temp_data,
    load_gsod_daily_temp_data,
    load_tmy3_hourly_temp_data,
    load_cz2010_hourly_temp_data,
    load_cached_isd_hourly_temp_data,
    load_cached_isd_daily_temp_data,
    load_cached_gsod_daily_temp_data,
    load_cached_tmy3_hourly_temp_data,
    load_cached_cz2010_hourly_temp_data,
)
from .visualization import plot_station_mapping, plot_station_mappings


def get_version():
    return __version__


# Set default logging handler to avoid "No handler found" warnings.
# will not work below py2.7
# workaround: https://docs.python.org/release/2.6/library/logging.html#configuring-logging-for-a-library
from logging import NullHandler

logging.getLogger(__name__).addHandler(NullHandler())
