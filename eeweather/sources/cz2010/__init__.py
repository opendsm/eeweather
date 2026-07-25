"""California Energy Commission CZ2010 typical-year temperatures."""
import os

from ...registry.db import metadata_db_connection_proxy
from .source import CZ2010Source



__all__ = ("CZ2010Source", "DATA_PATH")

# packaged archive station list
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cz2010.db")
metadata_db_connection_proxy.register_attachment(
    "cz2010", DATA_PATH, availability=True
)
