"""GHCNh hourly observations served through the NCEI access API."""
from ...registry.db import GHCNH_DB_PATH, metadata_db_connection_proxy
from .source import GHCNhSource



__all__ = ("GHCNhSource", "DATA_PATH")

# packaged catalog: station facts and zone assignments as GHCNh's material
# claims them, observation inventory, and quality ratings
DATA_PATH = GHCNH_DB_PATH
metadata_db_connection_proxy.register_attachment(
    "ghcnh", DATA_PATH, catalog=True, inventory=True, quality=True
)
