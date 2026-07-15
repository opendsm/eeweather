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
import pandas as pd

from .connections import metadata_db_connection_proxy



class lazy_property(object):
    """
    Meant to be used for lazy evaluation of an object attribute.
    Property should represent non-mutable data, as it replaces itself.

    e.g.,

    class Test(object):

        @lazy_property
        def results(self):
            calcs = 1  # Do a lot of calculation here
            return calcs

    from https://stackoverflow.com/a/6849299/1965736
    """

    def __init__(self, fget):
        self.fget = fget
        self.func_name = fget.__name__

    def __get__(self, obj, cls):
        value = self.fget(obj)
        setattr(obj, self.func_name, value)
        return value


def get_ghcn_ids(usaf_ids=None):
    """GHCNh station ids mapped to ISD USAF ids, as a usaf_id-indexed Series.

    Parameters
    ----------
    usaf_ids : list of str, optional
        USAF ids to map. When None, the whole registry is returned.
        Unrecognized ids are absent from the result.
    """
    conn = metadata_db_connection_proxy.get_connection()
    mapping = pd.read_sql_query(
        "select usaf_id, ghcn_id from isd_station_metadata", conn
    ).set_index("usaf_id")["ghcn_id"]
    if usaf_ids is not None:
        mapping = mapping[mapping.index.isin(list(usaf_ids))]

    return mapping
