"""Weather at a geographic location."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from .registry.summaries import get_place
from .registry.zones import zones_at
from .sources import StationSource
from .sources.budget import fetch_budget
from .sources.engine import known_source_names, resolve_source, _route
from .sources.pipeline import validate_requested
from .sources.matching import rank_stations



__all__ = ("WeatherLocation",)


def _normalize_sources(sources):
    if isinstance(sources, str):
        sources = (sources,)
    normalized = []
    for entry in sources:
        if isinstance(entry, str):
            resolved = resolve_source(entry)
            if not hasattr(resolved, "estimate"):
                resolved = StationSource(dataset=resolved)
            entry = resolved
        elif hasattr(entry, "fetch_year"):
            entry = StationSource(dataset=entry)
        normalized.append(entry)
    names = [source.name for source in normalized]
    if len(set(names)) != len(names):
        raise ValueError(
            "Duplicate source names in preference tuple: {}.".format(
                ", ".join(names)
            )
        )

    return tuple(normalized)


class WeatherLocation(object):
    """Weather at a latitude/longitude.

    The location is the primary abstraction; weather is estimated by the
    configured sources. Each requested variable routes to the first
    source in the preference tuple that serves it; by default station
    observations come from the nearest suitable GHCNh station and
    everything GHCNh does not serve — irradiance, and the rest of the
    NASA POWER vocabulary — comes from the grid cell containing the
    point. After a load, ``provenance`` records how each value was
    produced (which source, which station or cell, how far away).

    Parameters
    ----------
    latitude, longitude : float
    sources : str, source object, or tuple of these
        Ordered source preference. Strings name built-in sources; Feed
        objects and configured sources (e.g. ``StationSource``) are used
        as given.
    pins : dict of str to str, optional
        Station id to use per source name, bypassing matching. Pins are
        captured automatically from provenance at load time, so once a
        location has loaded data, later loads reuse the same station per
        source; :meth:`to_dict`/:meth:`to_json` carry them across
        processes for consistency between baseline and reporting
        periods.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        sources=("ghcnh", "nasa-power"),
        pins=None,
    ):
        self.latitude = latitude
        self.longitude = longitude
        self.pins = dict(pins or {})
        self.sources = _normalize_sources(sources)
        normals = [s.name for s in self.sources if getattr(s, "kind", None) == "normals"]
        if normals:
            raise ValueError(
                "Normals sources are not preference sources: {}. Pin one"
                " with load_data(source=...) instead.".format(", ".join(normals))
            )

        self.provenance = None

    @classmethod
    def from_place(
        cls, kind: str, code: str, sources=("ghcnh", "nasa-power")
    ) -> "WeatherLocation":
        """Construct a location from a coded place, e.g.
        ``from_place("zcta", "91104")`` for a ZIP code tabulation area."""
        place = get_place(kind, code)

        return cls(place["latitude"], place["longitude"], sources=sources)

    def to_dict(self) -> dict:
        """The location's replay state: coordinates, source names, and
        station pins. A location rebuilt with :meth:`from_dict` loads from
        the same station per source. Source configuration (rank/select
        kwargs) is not captured; pins bypass matching, so replay does not
        depend on it.

        To make replay faithful, any default :class:`StationSource`
        without a captured pin is resolved and pinned here (registry-only,
        no fetch) — so this mutates ``self.pins`` and, for a location with
        no station within the distance cap, may raise
        ``NoQualifiedStationError``. A source configured with
        ``coverage_range`` or ``rating_period`` is pinned at load, not
        here (resolving it depends on the request and may fetch), so
        serializing one before any load raises ``ValueError``. Grid and
        other non-station sources need no pin: coordinates plus source
        name already round-trip deterministically.
        """
        unrebuildable = [
            source.name for source in self.sources
            if source.name not in known_source_names()
        ]
        if unrebuildable:
            raise ValueError(
                "Custom sources cannot be serialized: {}. Register them"
                " with eeweather.sources.register to make them"
                " nameable.".format(", ".join(unrebuildable))
            )

        self._pin_unloaded_station_sources()
        state = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "sources": [source.name for source in self.sources],
            "pins": dict(self.pins),
        }

        return state

    def _pin_unloaded_station_sources(self) -> None:
        """Capture a station pin for each configured StationSource that
        lacks one, so serialized replay resolves to the same station."""
        for source in self.sources:
            if not isinstance(source, StationSource):
                continue
            if source.name in self.pins:
                continue
            if source.period_dependent:
                raise ValueError(
                    "Source {!r} is configured with coverage_range or"
                    " rating_period and has no captured pin; load once"
                    " before serializing it.".format(source.name)
                )
            station, _distance, _warnings = source.resolve(
                self.latitude, self.longitude
            )
            self.pins[source.name] = station.id

    @classmethod
    def from_dict(cls, data: dict) -> "WeatherLocation":
        """Rebuild a location from :meth:`to_dict` output."""
        return cls(
            data["latitude"],
            data["longitude"],
            sources=tuple(data["sources"]),
            pins=data.get("pins"),
        )

    def to_json(self) -> str:
        """:meth:`to_dict` as a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "WeatherLocation":
        """Rebuild a location from :meth:`to_json` output."""
        return cls.from_dict(json.loads(text))

    def __repr__(self) -> str:
        return "WeatherLocation({}, {})".format(self.latitude, self.longitude)

    @property
    def zones(self) -> dict[str, str | None]:
        """The zone containing this location, by zone system."""
        return zones_at(self.latitude, self.longitude)

    def candidates(self, **filters) -> pd.DataFrame:
        """Ranked candidate stations for this location.

        Filters are those of
        :func:`eeweather.sources.matching.rank_stations`: ``match_zones``,
        ``match_subdivision`` (with ``site_subdivision``), ``has_sources``,
        ``minimum_quality``, ``rating_period``, ``max_distance_meters``,
        and ``max_difference_elevation_meters`` (with ``site_elevation``).
        """
        return rank_stations(self.latitude, self.longitude, **filters)

    def _station_source(self, source=None):
        if source is not None:
            for candidate in self.sources:
                if isinstance(candidate, StationSource) and (
                    candidate is source
                    or candidate.name == source
                    or candidate.adapter is source
                ):
                    return candidate

            return _normalize_sources((source,))[0]
        for candidate in self.sources:
            if isinstance(candidate, StationSource):
                return candidate

        raise ValueError("No station-backed source is configured.")

    def _pinned_kwargs(self, estimation_source, load_kwargs):
        """Load kwargs with this source's station pin applied."""
        kwargs = dict(load_kwargs)
        if isinstance(estimation_source, StationSource):
            kwargs["station"] = self.pins.get(estimation_source.name)

        return kwargs

    def _capture_pins(self, provenance):
        """First resolution wins: record each source's station so later
        loads reuse it."""
        for name, record in provenance.items():
            if record.station_id is not None:
                self.pins.setdefault(name, record.station_id)

    def load_data(
        self,
        start: datetime,
        end: datetime,
        frequency="h",
        variables=None,
        source=None,
        ignore_disqualification: bool = False,
        deadline: float | None = None,
        **load_kwargs,
    ):
        """Weather at this location between two dates (inclusive).

        Each requested variable routes to the first source in the
        preference tuple that serves it; ``source=`` pins every variable
        to one source instead (typical-year sources are only reachable
        this way). Routed requests never raise for missing data (NaN
        values plus warnings); a pinned request with nothing at all for
        the dates raises DataNotAvailableError. Records provenance on
        ``self.provenance`` and the frame's ``attrs["provenance"]``,
        keyed by source name.

        ``deadline`` bounds the wall-clock seconds this request may spend
        on the network, after which it raises FetchDeadlineExceeded;
        unbounded by default. It applies to every source this load
        touches, station-based and grid alike.

        Returns
        -------
        tuple of (pandas.DataFrame, list of EEWeatherWarning)
        """
        if "sources" in load_kwargs:
            raise TypeError(
                "load_data() got an unexpected keyword argument 'sources'"
                " (did you mean the constructor's sources=, or source= to"
                " pin a single source for this load?)"
            )
        if source is not None:
            estimation_source = self._station_source(source)
            with fetch_budget(deadline):
                df, warnings, provenance = estimation_source.estimate(
                    self.latitude,
                    self.longitude,
                    start,
                    end,
                    frequency=frequency,
                    variables=variables,
                    raise_when_empty=True,
                    ignore_disqualification=ignore_disqualification,
                    **self._pinned_kwargs(estimation_source, load_kwargs),
                )
            df.attrs["provenance"] = provenance
            self.provenance = provenance
            self._capture_pins(provenance)

            return df, warnings

        # routed: the engine's routing groups variables by the first
        # source serving them; typical-year sources never route
        if variables is None:
            variables = ("temperature",)
        groups, requested = _route(variables, self.sources)
        validate_requested(requested)

        frames = []
        warnings = []
        provenance = {}
        with fetch_budget(deadline):
            for estimation_source, group_variables in groups.items():
                df, group_warnings, group_provenance = estimation_source.estimate(
                    self.latitude,
                    self.longitude,
                    start,
                    end,
                    frequency=frequency,
                    variables=tuple(group_variables),
                    raise_when_empty=False,
                    ignore_disqualification=ignore_disqualification,
                    **self._pinned_kwargs(estimation_source, load_kwargs),
                )
                frames.append(df)
                warnings.extend(group_warnings)
                provenance.update(group_provenance)

        df = pd.concat(frames, axis=1)[list(requested)]
        df.attrs["provenance"] = provenance
        self.provenance = provenance
        self._capture_pins(provenance)

        return df, warnings
