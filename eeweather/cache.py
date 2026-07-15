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
import contextlib
import datetime
import json
import os
import sqlite3

import pytz



SQLITE_URL_PREFIX = "sqlite:///"


def _sqlite_path_from_url(url):
    if not url.startswith(SQLITE_URL_PREFIX):
        raise ValueError(
            "EEweather cache urls must have the form sqlite:///path/to/cache.db,"
            " got: {}".format(url)
        )

    return url[len(SQLITE_URL_PREFIX) :]


class KeyValueStore(object):
    """JSON key-value store on a local sqlite database.

    The database location is taken from the url argument, the
    EEWEATHER_CACHE_URL environment variable, or ~/.eeweather/cache.db,
    in that order. Urls have the form sqlite:///path/to/cache.db.
    """

    def __init__(self, url=None):
        self._prepare_db(url)

    def __repr__(self):
        return 'KeyValueStore("{}")'.format(self.url)

    def _get_url(self):  # pragma: no cover (tests always provide url)
        url = os.environ.get("EEWEATHER_CACHE_URL")
        if url is None:
            directory = "{}/.eeweather".format(os.path.expanduser("~"))
            if not os.path.exists(directory):
                os.makedirs(directory)
            url = "sqlite:///{}/cache.db".format(directory)

        return url

    def _prepare_db(self, url=None):
        if url is None:  # pragma: no cover (tests always provide url)
            url = self._get_url()
        self.url = url

        self._path = _sqlite_path_from_url(url)
        with self._connect() as conn, conn:
            conn.execute(
                "create table if not exists items ("
                " key text unique,"
                " data text,"
                " updated text)"
            )
            conn.execute("create index if not exists ix_items_key on items (key)")

    def _connect(self):
        # closes the connection on exit; writes commit via the inner
        # transaction context in each caller
        return contextlib.closing(sqlite3.connect(self._path))

    def key_exists(self, key):
        with self._connect() as conn:
            row = conn.execute("select 1 from items where key = ?", (key,)).fetchone()

        return row is not None

    def save_json(self, key, data):
        data = json.dumps(data, separators=(",", ":"))
        updated = datetime.datetime.now(pytz.UTC).isoformat()
        with self._connect() as conn, conn:
            conn.execute(
                "insert into items (key, data, updated) values (?, ?, ?)"
                " on conflict (key) do update set data = ?, updated = ?",
                (key, data, updated, data, updated),
            )

    def retrieve_json(self, key):
        with self._connect() as conn:
            row = conn.execute(
                "select data from items where key = ?", (key,)
            ).fetchone()

        if row is None:
            return None

        return json.loads(row[0])

    def key_updated(self, key):
        with self._connect() as conn:
            row = conn.execute(
                "select updated from items where key = ?", (key,)
            ).fetchone()

        if row is None:
            return None

        return datetime.datetime.fromisoformat(row[0])

    def clear(self, key=None):
        with self._connect() as conn, conn:
            if key is None:
                conn.execute("delete from items")
            else:
                conn.execute("delete from items where key = ?", (key,))
