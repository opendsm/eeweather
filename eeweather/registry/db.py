"""Access to the packaged data files.

Every connection opens the identifier crosswalk (identifiers.db) and
ATTACHes the regional geography packs (geography_*.db) plus the data
files source packages register at import, so identity, geography, fact,
availability, and quality queries can join across files. Connections are
cached per thread and reused; callers do not close them.
"""
import glob
import os
import sqlite3
import threading
from collections import namedtuple

import platformdirs

from ..exceptions import UnrecognizedStationError, UnrecognizedPlaceError



_REGISTRY_DIR = os.path.dirname(os.path.abspath(__file__))
_SOURCES_DIR = os.path.join(os.path.dirname(_REGISTRY_DIR), "sources")

UPDATED_DATA_DIR = os.path.join(platformdirs.user_data_dir("eeweather"), "registry")

# an update writes this marker only after both files swap in, so its
# presence certifies a complete (non-torn) updated pair
COMMIT_MARKER = ".committed"


def data_path(packaged_path):
    """The live path for a packaged data file: the downloaded update in
    the user data directory when a completed update is present, else the
    packaged copy. The updated copy is used only alongside the commit
    marker that certifies the swap finished, so a torn pair is ignored.
    Resolved at import, so an update applies to new processes."""
    updated = os.path.join(UPDATED_DATA_DIR, os.path.basename(packaged_path))
    marker = os.path.join(UPDATED_DATA_DIR, COMMIT_MARKER)
    if os.path.exists(marker) and os.path.exists(updated):
        return updated

    return packaged_path


PACKAGED_IDENTIFIERS_DB_PATH = os.path.join(_REGISTRY_DIR, "identifiers.db")
PACKAGED_GHCNH_DB_PATH = os.path.join(_SOURCES_DIR, "ghcnh", "ghcnh.db")

IDENTIFIERS_DB_PATH = data_path(PACKAGED_IDENTIFIERS_DB_PATH)
GHCNH_DB_PATH = data_path(PACKAGED_GHCNH_DB_PATH)

MONTH_COLUMNS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)

Attachment = namedtuple(
    "Attachment", ["alias", "path", "catalog", "inventory", "quality", "availability"]
)


def _geography_packs():
    packs = []
    for path in sorted(glob.glob(os.path.join(_REGISTRY_DIR, "geography_*.db"))):
        alias = os.path.splitext(os.path.basename(path))[0]
        packs.append((alias, path))

    return packs


class MetadataDBConnectionProxy(object):
    def __init__(self):
        self.db_path = IDENTIFIERS_DB_PATH
        self._local = threading.local()
        self._attachments = []
        self.geography_aliases = [alias for alias, _ in _geography_packs()]

    def register_attachment(
        self, alias, path,
        catalog=False, inventory=False, quality=False, availability=False,
    ):
        """Register a source database to attach to every connection.

        ``catalog`` marks a station catalog (facts and zone assignments);
        ``inventory``/``quality`` mark observation-count and rating
        tables; ``availability`` marks an archive station list. Sources
        register at import, before any connection is made.
        """
        if any(a.alias == alias for a in self._attachments):
            return
        self._attachments.append(
            Attachment(alias, path, catalog, inventory, quality, availability)
        )

    @property
    def catalogs(self):
        return [a.alias for a in self._attachments if a.catalog]

    @property
    def inventory_sources(self):
        return [a.alias for a in self._attachments if a.inventory]

    @property
    def quality_sources(self):
        return [a.alias for a in self._attachments if a.quality]

    @property
    def availability_sources(self):
        return [a.alias for a in self._attachments if a.availability]

    def get_connection(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.db_path)
            for alias, path in _geography_packs():
                connection.execute(
                    "attach database ? as {}".format(alias), (path,)
                )
            self._local.connection = connection
            self._local.attached = set()
        # attach any source registered since this thread's connection was
        # made, so late registration (e.g. importing a custom source
        # after a first query) is not silently missing
        for attachment in self._attachments:
            if attachment.alias not in self._local.attached:
                connection.execute(
                    "attach database ? as {}".format(attachment.alias),
                    (attachment.path,),
                )
                self._local.attached.add(attachment.alias)

        return connection

    def close(self):
        """Close and drop this thread's cached connection, if any; the next
        get_connection opens a fresh one. Attachments are re-applied then."""
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
        self._local.connection = None
        self._local.attached = set()


metadata_db_connection_proxy = MetadataDBConnectionProxy()


def valid_station_id_or_raise(station_id):
    """Raise UnrecognizedStationError unless the id is in the registry."""
    conn = metadata_db_connection_proxy.get_connection()
    row = conn.execute(
        "select exists (select 1 from station_identifier where station_id = ?)",
        (station_id,),
    ).fetchone()
    if not row[0]:
        raise UnrecognizedStationError(station_id)

    return True


def valid_place_or_raise(kind, code):
    """Raise UnrecognizedPlaceError unless the place code is in a geography
    pack."""
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()
    for alias in proxy.geography_aliases:
        row = conn.execute(
            "select exists (select 1 from {}.place where kind = ? and code = ?)".format(
                alias
            ),
            (kind, code),
        ).fetchone()
        if row[0]:
            return True

    raise UnrecognizedPlaceError(kind, code)
