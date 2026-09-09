"""Weather-data sources and estimation strategies.

A *source* is a provider of weather data. Strings name the built-in
sources (``"ghcnh"``, ``"nasa-power"``, ``"tmy3"``, ``"cz2010"``);
configured or custom sources are objects. Station-keyed external data plugs in through the
:class:`Feed` protocol; location-keyed (gridded) data implements
:class:`Source` directly.
"""
from .base import Feed, NormalsSource, Source
from .derivations import wind_direction
from .engine import register, variables
from .station_source import StationSource
from .vocabulary import Variable



__all__ = (
    "Source",
    "StationSource",
    "Feed",
    "NormalsSource",
    "Variable",
    "register",
    "variables",
    "wind_direction",
)
