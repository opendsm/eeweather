"""The shared weather-data cache.

One sqlite-backed JSON key-value store serves every station and source.
Its location is taken from ``set_path``, the EEWEATHER_CACHE_URL
environment variable, or the platform user cache directory, in that
order.
"""
import contextlib
import datetime
import json
import os
import sqlite3

import platformdirs



SQLITE_URL_PREFIX = "sqlite:///"

DATA_EXPIRATION_DAYS = 1

# a data year keeps arriving for a while after it ends (publication lag),
# so entries written shortly after year end stay refreshable
YEAR_END_GRACE_DAYS = 14


def _sqlite_path_from_url(url):
    if not url.startswith(SQLITE_URL_PREFIX):
        raise ValueError(
            "EEweather cache urls must have the form sqlite:///path/to/cache.db,"
            " got: {}".format(url)
        )

    return url[len(SQLITE_URL_PREFIX) :]


class KeyValueStore(object):
    """JSON key-value store on a local sqlite database."""

    def __init__(self, url=None):
        self._prepare_db(url)

    def __repr__(self):
        return 'KeyValueStore("{}")'.format(self.url)

    def _get_url(self):  # pragma: no cover (tests always provide url)
        url = os.environ.get("EEWEATHER_CACHE_URL")
        if url is None:
            directory = platformdirs.user_cache_dir("eeweather")
            os.makedirs(directory, exist_ok=True)
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
                " key text primary key,"
                " data text,"
                " updated text)"
            )

    def _connect(self):
        # closes the connection on exit; writes commit via the inner
        # transaction context in each caller
        return contextlib.closing(sqlite3.connect(self._path))

    def key_exists(self, key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("select 1 from items where key = ?", (key,)).fetchone()

        return row is not None

    def keys(self, prefix: str) -> list:
        """All keys beginning with a prefix, sorted."""
        escaped = (
            prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        with self._connect() as conn:
            rows = conn.execute(
                "select key from items where key like ? escape '\\' order by key",
                (escaped + "%",),
            ).fetchall()

        return [row[0] for row in rows]

    def save_json(self, key, data):
        data = json.dumps(data, separators=(",", ":"))
        updated = datetime.datetime.now(datetime.timezone.utc).isoformat()
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


class KeyValueStoreProxy(object):
    def __init__(self):
        self._store = None

    def get_store(self):  # pragma: no cover
        if self._store is None:
            self._store = KeyValueStore()

        return self._store

    def set_store(self, store):
        self._store = store


key_value_store_proxy = KeyValueStoreProxy()


def set_path(path: str) -> None:
    """Point the shared weather cache at a specific sqlite file, creating
    its directory if needed.

    All stations and sources share this one store; overrides the
    EEWEATHER_CACHE_URL environment variable and the default location.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    key_value_store_proxy.set_store(KeyValueStore("sqlite:///{}".format(path)))


def clear() -> None:
    """Drop all cached weather data from the shared store."""
    key_value_store_proxy.get_store().clear()


def _expired(last_updated, year):
    """Whether a cache entry for a data year is stale: entries written
    while the year's data was still arriving (during the year, or within
    YEAR_END_GRACE_DAYS after it ends) expire after
    DATA_EXPIRATION_DAYS."""
    if last_updated is None:
        return True
    expiration_limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=DATA_EXPIRATION_DAYS
    )
    volatile_until = datetime.datetime(
        year + 1, 1, 1, tzinfo=datetime.timezone.utc
    ) + datetime.timedelta(days=YEAR_END_GRACE_DAYS)
    still_volatile = last_updated < volatile_until

    return expiration_limit > last_updated and still_volatile
