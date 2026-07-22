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
import os
import sqlite3
import threading

from .cache import KeyValueStore

logger = logging.getLogger(__name__)

__all__ = ("metadata_db_connection_proxy",)


class MetadataDBConnectionProxy(object):
    """Serves a cached read connection to the packaged metadata database.

    Connections are cached per thread and reused, so callers do not close
    them.
    """

    def __init__(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root_dir, "eeweather", "resources")
        self.db_path = os.path.join(path, "metadata.db")
        self._local = threading.local()

    def get_connection(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.db_path)
            self._local.connection = connection

        return connection

    def reset_database(self):  # pragma: no cover
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
        os.remove(self.db_path)

        return self.get_connection()


class KeyValueStoreProxy(object):
    def __init__(self):
        self._store = None

    def get_store(self):  # pragma: no cover
        if self._store is None:
            self._store = KeyValueStore()
        return self._store


# Use proxies for lazy loading, abstraction
metadata_db_connection_proxy = MetadataDBConnectionProxy()
key_value_store_proxy = KeyValueStoreProxy()
