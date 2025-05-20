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
from .connections import metadata_db_connection_proxy
from .exceptions import UnrecognizedZCTAError, UnrecognizedUSAFIDError


__all__ = ("valid_zcta_or_raise", "valid_usaf_id_or_raise")


def valid_zcta_or_raise(zcta):
    """Check if ZCTA is valid and raise eeweather.UnrecognizedZCTAError if not."""
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()

    cur.execute(
        """
      select exists (
        select
          zcta_id
        from
          zcta_metadata
        where
          zcta_id = ?
      )
    """,
        (zcta,),
    )
    (exists,) = cur.fetchone()
    if exists:
        return True
    else:
        raise UnrecognizedZCTAError(zcta)


def valid_usaf_id_or_raise(usaf_id):
    """Check if USAF ID is valid and raise eeweather.UnrecognizedUSAFIDError if not."""
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()

    cur.execute(
        """
      select exists (
        select
          usaf_id
        from
          isd_station_metadata
        where
          usaf_id = ?
      )
    """,
        (usaf_id,),
    )
    (exists,) = cur.fetchone()
    if exists:
        return True
    else:
        raise UnrecognizedUSAFIDError(usaf_id)
