"""NREL TMY3 typical-year temperatures."""
import os

from ...registry.db import metadata_db_connection_proxy
from .source import TMY3Source



__all__ = ("TMY3Source", "DATA_PATH")

# packaged archive station list
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmy3.db")
metadata_db_connection_proxy.register_attachment(
    "tmy3", DATA_PATH, availability=True
)
