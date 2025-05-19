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

import ftplib
from io import BytesIO
import logging
import os
import sqlite3

from .cache import KeyValueStore

logger = logging.getLogger(__name__)

__all__ = ("noaa_ftp_connection_proxy", "metadata_db_connection_proxy")


def _get_noaa_ftp_connection(n_tries=5, timeout=60):  # pragma: no cover
    host = "ftp.ncei.noaa.gov"
    for i in range(n_tries):
        # attempt anonymous connection
        try:
            ftp = ftplib.FTP(host, timeout=timeout)
            ftp.login()  # default u='anonymous' p='anonymous@'
            logger.info("Connected to {}.".format(host))
            return ftp
        except ftplib.all_errors as e:
            logger.warn(
                "Failed attempt ({} of {}) to connect to {}:\n{}".format(
                    i + 1, n_tries, host, e
                )
            )

    raise RuntimeError("Could not connect to {}.".format(host))


class NOAAFTPConnectionProxy(object):
    def __init__(self):
        self._connection = None

    def get_connection(self):  # pragma: no cover
        if self._connection is None:
            self._connection = _get_noaa_ftp_connection()
        return self._connection

    def reconnect(self):  # pragma: no cover
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        return self.get_connection()

    def read_file_as_bytes(self, filename):  # pragma: no cover
        ftp = self.get_connection()

        bytes_string = BytesIO()
        try:
            try:
                ftp.retrbinary("RETR {}".format(filename), bytes_string.write)
            except (ftplib.error_temp, ftplib.error_perm, EOFError, IOError) as e:
                # Bad connection. attempt to reconnect.
                logger.warn(
                    "Failed RETR {}:\n{}\n" "Attempting reconnect.".format(filename, e)
                )
                ftp = self.reconnect()
                ftp.retrbinary("RETR {}".format(filename), bytes_string.write)
        except Exception as e:
            logger.warn(
                "Failed RETR {}:\n{}\n" "Not attempting reconnect.".format(filename, e)
            )
            return None

        bytes_string.seek(0)
        logger.info("Successfully retrieved ftp://ftp.ncei.noaa.gov{}".format(filename))
        return bytes_string


class MetadataDBConnectionProxy(object):
    def __init__(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root_dir, "eeweather", "resources")
        self.db_path = os.path.join(path, "metadata.db")

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def reset_database(self):  # pragma: no cover
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
noaa_ftp_connection_proxy = NOAAFTPConnectionProxy()
metadata_db_connection_proxy = MetadataDBConnectionProxy()
key_value_store_proxy = KeyValueStoreProxy()
