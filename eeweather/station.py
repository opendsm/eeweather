"""The pinned-station handle."""
from __future__ import annotations

from datetime import datetime

from .registry.db import valid_station_id_or_raise
from .registry.identifiers import resolve_station
from .registry.identifiers import translate as _translate
from .registry.metadata import get_station_metadata
from .registry.quality import get_station_quality
from .registry.summaries import search_stations
from .sources.engine import _station_keyed_or_raise
from .sources.engine import load_data as _engine_load_data
from .sources.engine import resolve_source



__all__ = ("WeatherStation",)


def _validate_sources(sources):
    """Reject a preference tuple with a duplicate, location-keyed, or
    non-observation source; a station routes only station-keyed
    observation sources."""
    adapters = [resolve_source(source) for source in sources]
    _station_keyed_or_raise(adapters)
    names = [adapter.name for adapter in adapters]
    if len(set(names)) != len(names):
        raise ValueError(
            "Duplicate source names in preference tuple: {}.".format(
                ", ".join(names)
            )
        )
    wrong_kind = [adapter.name for adapter in adapters if adapter.kind != "observations"]
    if wrong_kind:
        raise ValueError(
            "Sources preference only routes observation sources; pin"
            " normals sources (e.g. 'tmy3', 'cz2010') with load_data("
            "source=...) instead: {}.".format(", ".join(wrong_kind))
        )


class WeatherStation(object):
    """A known weather station in the registry.

    Stations are keyed by their GHCN id; other identifier systems are
    aliases — use the ``from_id``, ``from_usaf``, ``from_wban``, or
    ``from_icao`` constructors to look a station up by one.

    Attributes
    ----------
    id : str
        The station's GHCN id, the registry key.
    ids : dict of str to list of str
        External identifiers by namespace, e.g.
        ``{"usaf": ["722880"], "wban": ["23152"], "icao": ["KBUR"]}``.
    name : str
        Station name.
    latitude, longitude, elevation : float
        Station location; elevation in meters.
    coords : tuple of (float, float)
        Latitude/longitude pair.
    country : str
        ISO 3166-1 alpha-2 country code.
    subdivision : str or None
        Country subdivision (e.g. a US state abbreviation); None where the
        registry has none.
    quality : str
        Build-time data-quality rating: "high", "medium", or "low".
    zones : dict of str to str
        Zone id by zone system, e.g. ``{"iecc_climate_zone": "3"}``.
    inventory_years : dict of str to tuple of (int, int)
        First and last inventory year by source.
    """

    def __init__(self, station_id: str, sources=("ghcnh",), load_metadata: bool = True):
        self.id = station_id
        if isinstance(sources, str):
            sources = (sources,)
        sources = tuple(sources)
        _validate_sources(sources)
        self.sources = sources
        self.provenance = None

        if load_metadata:
            self._load_metadata()
        else:
            valid_station_id_or_raise(station_id)
            self.ids = None
            self.name = None
            self.latitude = None
            self.longitude = None
            self.elevation = None
            self.coords = None
            self.country = None
            self.subdivision = None
            self.quality = None
            self.zones = {}
            self.inventory_years = {}

    @classmethod
    def from_id(cls, namespace: str, external_id: str, load_metadata: bool = True) -> "WeatherStation":
        """Construct a station from an external identifier.

        When the identifier maps to several stations, the mapping marked
        recent wins; unresolvable identifiers raise
        AmbiguousIdentifierError.
        """
        station_id = resolve_station(namespace, external_id)

        return cls(station_id, load_metadata=load_metadata)

    @classmethod
    def from_usaf(cls, usaf_id: str, load_metadata: bool = True) -> "WeatherStation":
        """Construct a station from a historical ISD USAF id."""
        return cls.from_id("usaf", usaf_id, load_metadata=load_metadata)

    @classmethod
    def from_wban(cls, wban_id: str, load_metadata: bool = True) -> "WeatherStation":
        """Construct a station from a historical WBAN id."""
        return cls.from_id("wban", wban_id, load_metadata=load_metadata)

    @classmethod
    def from_icao(cls, icao_code: str, load_metadata: bool = True) -> "WeatherStation":
        """Construct a station from an ICAO airport code."""
        return cls.from_id("icao", icao_code, load_metadata=load_metadata)

    @classmethod
    def search(cls, country: str | None = None, subdivision: str | None = None, has_sources=()):
        """Registry stations as a DataFrame indexed by station id.

        Parameters
        ----------
        country : str, optional
            ISO 3166-1 alpha-2 country code, e.g. ``'US'``.
        subdivision : str, optional
            Country subdivision, e.g. a US state abbreviation.
        has_sources : tuple of str
            Sources the stations must be able to serve, e.g.
            ``('tmy3',)``.
        """
        stations = search_stations(
            country=country, subdivision=subdivision, has_sources=has_sources
        )

        return stations

    @staticmethod
    def translate(ids, from_namespace: str, to_namespace: str) -> dict[str, tuple[str, ...]]:
        """Translate external station ids between identifier systems.

        Values are always tuples; mappings can be one-to-many in either
        direction. Ids with no mapping are absent from the result.
        """
        return _translate(ids, from_namespace, to_namespace)

    def __str__(self) -> str:
        return self.id

    def __repr__(self) -> str:
        return "WeatherStation('{}')".format(self.id)

    def _load_metadata(self):
        metadata = get_station_metadata(self.id)

        self.ids = metadata["ids"]
        self.name = metadata["name"]
        self.latitude = metadata["latitude"]
        self.longitude = metadata["longitude"]
        self.elevation = metadata["elevation"]
        self.coords = (self.latitude, self.longitude)
        self.country = metadata["country"]
        self.subdivision = metadata["subdivision"]
        self.quality = metadata["quality"]
        self.zones = metadata["zones"]
        self.inventory_years = metadata["inventory_years"]

    def json(self) -> dict:
        """Return a JSON-serializeable object containing station metadata."""
        serialized = {
            "id": self.id,
            "ids": self.ids,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "country": self.country,
            "subdivision": self.subdivision,
            "quality": self.quality,
            "zones": self.zones,
            "inventory_years": self.inventory_years,
        }

        return serialized

    def load_data(
        self,
        start: datetime,
        end: datetime,
        frequency="h",
        variables=None,
        source=None,
        read_from_cache: bool = True,
        write_to_cache: bool = True,
        fetch_from_web: bool = True,
        imputation: bool = False,
    ):
        """Load this station's weather data between two dates (inclusive).

        Parameters
        ----------
        start : datetime.datetime
            The earliest date from which to load data. Must be UTC.
        end : datetime.datetime
            The latest date until which to load data. Must be UTC.
        frequency : str or pandas offset
            A pandas offset alias (e.g. ``'30min'``, ``'h'``, ``'D'``,
            ``'W'``, ``'MS'``, ``'YS'``). Coarser-than-hourly
            frequencies aggregate the hourly values within each UTC
            period by each variable's vocabulary aggregation;
            finer-than-hourly frequencies interpolate.
        variables : tuple of str, or 'all'
            Canonical variable names; defaults to ``('temperature',)``.
            Each is routed to the first source in this station's
            ``sources`` preference that serves it; ``'all'`` is every
            variable those sources serve.
        source : str or source object, optional
            Pin every requested variable to this source, bypassing
            routing. Typical-year sources (``'tmy3'``, ``'cz2010'``) are
            only reachable this way. A pinned load with nothing at all
            for the requested dates raises ``DataNotAvailableError``; a
            routed load (``source`` unset) never raises for missing
            data, returning NaN plus warnings instead.
        read_from_cache : bool
            Whether or not to load data from cache.
        write_to_cache : bool
            Whether or not to write newly loaded data to cache.
        fetch_from_web : bool
            Whether or not to fetch data from the web.
        imputation : bool
            Also return a ``<variable>_imputed_fraction`` companion for
            each point-in-time variable, saying how much of each value
            was fabricated by gap interpolation rather than observed.

        Returns
        -------
        tuple of (pandas.DataFrame, list of EEWeatherWarning)
            One column per requested variable -- plus an
            imputed-fraction companion per point-in-time variable when
            ``imputation`` is set -- indexed over the full requested
            range at the requested frequency; periods without data are
            NaN. The frame's ``attrs["provenance"]`` (also
            recorded on ``self.provenance``) maps each source used to a
            Provenance record.
        """
        df, warnings = _engine_load_data(
            self.id,
            start,
            end,
            frequency=frequency,
            variables=variables,
            source=source,
            sources=self.sources,
            read_from_cache=read_from_cache,
            write_to_cache=write_to_cache,
            fetch_from_web=fetch_from_web,
            imputation=imputation,
        )
        self.provenance = df.attrs["provenance"]

        return df, warnings

    def get_quality(self, anchor: datetime, source: str | None = None) -> str:
        """Station quality anchored to a date, from a source's observation
        counts; defaults to the first registered source with inventory."""
        return get_station_quality(self.id, anchor, source=source)
