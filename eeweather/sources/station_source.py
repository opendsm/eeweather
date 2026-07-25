"""The nearest-suitable-station estimation strategy."""
from __future__ import annotations

from datetime import datetime

import pyproj

from ..exceptions import NoQualifiedStationError
from .base import Source
from .engine import load_data as _engine_load_data
from .engine import resolve_source
from ..exceptions import EEWeatherWarning
from .matching import rank_stations, select_station, source_availability_columns
from ..station import WeatherStation



# beyond this, a station is not a defensible temperature proxy for a
# location without explicit acknowledgment; every US ZCTA has a station
# within 124 km, so no ordinary location is stranded by the default
DEFAULT_MAX_DISTANCE_METERS = 150_000


class StationSource(Source):
    """Estimates weather at a point from the nearest suitable station.

    Parameters
    ----------
    dataset : str or Feed
        The observation source served: a built-in name or a Feed object.
    rank_kwargs, select_kwargs : dict, optional
        Forwarded to rank_stations and select_station to control
        filtering and coverage requirements.
    """

    def __init__(self, dataset="ghcnh", rank_kwargs=None, select_kwargs=None):
        self.adapter = resolve_source(dataset)
        self.name = self.adapter.name
        self.kind = self.adapter.kind
        self.variables = self.adapter.variables
        self.default_variables = self.adapter.default_variables
        rank_kwargs = dict(rank_kwargs or {})
        if self.name in source_availability_columns():
            # only consider stations that can serve this dataset
            rank_kwargs.setdefault("has_sources", (self.name,))
        rank_kwargs.setdefault("max_distance_meters", DEFAULT_MAX_DISTANCE_METERS)
        self.rank_kwargs = rank_kwargs
        self.select_kwargs = select_kwargs or {}
        self._resolutions = {}

    @property
    def period_dependent(self):
        """Whether a coverage or rating-period filter is configured, so
        resolution depends on more than coordinates. Such a source is
        pinned at load (where the request is known and any coverage fetch
        is expected), not at serialization."""
        configured = (
            "coverage_range" in self.select_kwargs
            or "rating_period" in self.rank_kwargs
        )

        return configured

    def resolve(
        self,
        latitude: float,
        longitude: float,
        period: tuple[datetime, datetime] | None = None,
        ignore_disqualification: bool = False,
        station: str | None = None,
    ):
        """The station serving this point, with its distance and any
        selection warnings.

        Resolutions (including their warnings) are memoized per location
        and period year-span; the same request reuses its station, a
        different era re-resolves. Call :meth:`reset` to force
        re-resolution.

        With ``ignore_disqualification``, a point no station qualifies
        for (distance cap, coverage test) gets the best available
        station anyway, plus an ``eeweather.station_disqualified``
        warning carrying what failed; NoQualifiedStationError then only
        remains for a point with no candidates at all.
        """
        if station is not None:
            return self._resolve_pinned(latitude, longitude, station)

        key = (round(latitude, 6), round(longitude, 6), ignore_disqualification)
        if period is not None:
            start, end = period
            key = key + (start.year, end.year)
        if key in self._resolutions:
            station, distance_meters, select_warnings = self._resolutions[key]

            return station, distance_meters, list(select_warnings)

        select_kwargs = dict(self.select_kwargs)
        if "coverage_range" in select_kwargs:
            select_kwargs.setdefault("coverage_source", self.adapter)
        candidates = rank_stations(latitude, longitude, **self.rank_kwargs)
        station, select_warnings = select_station(candidates, **select_kwargs)

        if station is None and ignore_disqualification:
            station, select_warnings, candidates = self._resolve_disqualified(
                latitude, longitude
            )
        if station is None:
            raise NoQualifiedStationError(latitude, longitude)
        distance_meters = float(candidates.loc[station.id, "distance_meters"])
        self._resolutions[key] = (station, distance_meters, list(select_warnings))

        return station, distance_meters, list(select_warnings)

    def _resolve_pinned(self, latitude, longitude, station_id):
        """The pinned station, with its true distance to the point; an
        explicit pin is its own acceptance, so qualification is skipped."""
        station = WeatherStation(station_id)
        geod = pyproj.Geod(ellps="WGS84")
        distance_meters = float(
            geod.inv(longitude, latitude, station.longitude, station.latitude)[2]
        )
        no_warnings = []

        return station, distance_meters, no_warnings

    def _resolve_disqualified(self, latitude, longitude):
        """The best station ignoring the distance cap and coverage test,
        with a warning stating which qualifications it failed."""
        rank_kwargs = dict(self.rank_kwargs)
        max_distance = rank_kwargs.pop("max_distance_meters", None)
        candidates = rank_stations(latitude, longitude, **rank_kwargs)
        select_kwargs = {
            k: v for k, v in self.select_kwargs.items()
            if k not in ("coverage_range", "min_fraction_coverage")
        }
        station, select_warnings = select_station(candidates, **select_kwargs)
        if station is not None:
            failed = []
            distance_meters = float(candidates.loc[station.id, "distance_meters"])
            if max_distance is not None and distance_meters > max_distance:
                failed.append("distance")
            if "coverage_range" in self.select_kwargs:
                failed.append("coverage")
            select_warnings = list(select_warnings)
            select_warnings.append(
                EEWeatherWarning(
                    qualified_name="eeweather.station_disqualified",
                    description=(
                        "No station qualified; using the best available"
                        " with qualification ignored."
                    ),
                    data={
                        "station_id": station.id,
                        "failed": failed,
                        "distance_meters": distance_meters,
                        "max_distance_meters": max_distance,
                    },
                )
            )

        return station, select_warnings, candidates

    def reset(self) -> None:
        """Drop memoized station resolutions."""
        self._resolutions = {}

    def estimate(
        self,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        frequency="h",
        variables=None,
        raise_when_empty=True,
        ignore_disqualification=False,
        station=None,
        **load_kwargs,
    ):
        station, distance_meters, select_warnings = self.resolve(
            latitude, longitude, period=(start, end),
            ignore_disqualification=ignore_disqualification,
            station=station,
        )

        df, load_warnings = _engine_load_data(
            station.id,
            start,
            end,
            frequency=frequency,
            variables=variables,
            source=self.adapter,
            raise_when_empty=raise_when_empty,
            **load_kwargs,
        )
        provenance = {
            name: record._replace(distance_meters=distance_meters)
            for name, record in df.attrs["provenance"].items()
        }
        df.attrs["provenance"] = provenance
        warnings = select_warnings + load_warnings

        return df, warnings, provenance
