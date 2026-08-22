"""The contracts weather-data sources implement.

``Source`` is the location-level estimation contract; ``Feed`` is the
station-keyed observation contract; ``NormalsSource`` is the
typical-year contract, including the machinery its implementations
share. The engine and location layers interpret these kinds; adapters
subclass them.
"""
from __future__ import annotations


from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from . import budget
from ..exceptions import DataNotAvailableError, FetchError
from ..registry.db import metadata_db_connection_proxy



_ProvenanceFields = namedtuple(
    "Provenance",
    ["kind", "source", "variables", "station_id", "distance_meters", "payload"],
)


class Provenance(_ProvenanceFields):
    """How a value was produced. Station fields are None for non-station
    sources; ``payload`` is always a dict, empty unless the source adds
    source-specific detail (e.g. a grid cell or interpolation method)."""
    __slots__ = ()

    def __new__(
        cls, kind, source, variables,
        station_id=None, distance_meters=None, payload=None,
    ):
        if payload is None:
            payload = {}

        record = super().__new__(
            cls, kind, source, variables, station_id, distance_meters, payload
        )

        return record


class Source(object):
    """Estimates weather at a geographic location.

    Subclasses implement ``estimate`` for one estimation strategy: a
    station-based source resolves the point to a nearby weather station,
    a grid-based source samples a gridded product at the point. All
    return the same ``(DataFrame, warnings, provenance)`` contract so the
    strategy is interchangeable behind a location; ``provenance`` maps
    each source name used to a Provenance record.
    """

    def estimate(
        self,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        frequency="h",
        variables=("temperature",),
        **load_kwargs,
    ):
        raise NotImplementedError


class Feed(object):
    """The protocol for station-keyed observation data.

    Implementations declare how their data is keyed and fetched; the
    engine supplies caching, alignment, warnings, and provenance, and the
    registry supplies station choice. Frames returned by ``fetch_year``
    carry canonical variable names and units.

    Attributes
    ----------
    name : str
        Unique source name; appears in provenance and cache keys.
    kind : str
        ``"observations"``.
    id_namespace : str
        The identifier system the data is keyed by (``"ghcn"``,
        ``"usaf"``, ...); translated from registry ids by the engine.
    variables : tuple of str
        Canonical variables the feed serves.
    default_variables : tuple of str
        Variables a bare load requests.
    cacheable : bool
        Whether the engine should cache fetched blocks; declare False
        for fast local backends.
    """

    kind = "observations"
    cacheable = True
    default_variables = ("temperature",)

    def fetch_year(self, external_id: str, year: int, variables) -> pd.DataFrame:
        raise NotImplementedError


REQUEST_TRIES = 3

REQUEST_RETRY_BACKOFF_SECONDS = 5

REQUEST_TIMEOUT_SECONDS = 120


def request_text(url):
    """Fetch a url's text, retrying connection errors and server errors
    with growing backoff; client errors raise immediately.

    Transport failures are raised as :class:`~eeweather.exceptions.FetchError`
    so callers need not import ``requests`` to catch them.

    Honours an ambient fetch budget: the attempt loop stops when the budget
    is spent, socket timeouts are capped at what is left, and backoff never
    sleeps past the deadline.
    """
    for attempt in range(REQUEST_TRIES):
        budget.check(url)
        try:
            response = requests.get(
                url, timeout=budget.timeout_for(REQUEST_TIMEOUT_SECONDS)
            )
            response.raise_for_status()
        except requests.HTTPError as error:
            if response.status_code < 500 or attempt == REQUEST_TRIES - 1:
                raise FetchError("request", cause=error) from error
            budget.sleep_within(REQUEST_RETRY_BACKOFF_SECONDS * (attempt + 1))
        except requests.RequestException as error:
            if attempt == REQUEST_TRIES - 1:
                raise FetchError("request", cause=error) from error
            budget.sleep_within(REQUEST_RETRY_BACKOFF_SECONDS * (attempt + 1))
        else:
            return response.text


def parse_normals_csv(text):
    """Parse a TMY-format CSV into an hourly temperature series over the
    year 1900 in UTC."""
    index = pd.date_range(
        "1900-01-01 00:00", "1900-12-31 23:00", freq="h", tz=timezone.utc
    )
    ts = pd.Series(None, index=index, dtype=float)

    lines = text.splitlines()

    utc_offset_str = lines[0].split(",")[3]
    utc_offset = timedelta(seconds=3600 * float(utc_offset_str))

    for line in lines[2:]:
        row = line.split(",")
        month = row[0][0:2]
        day = row[0][3:5]
        hour = int(row[1][0:2]) - 1

        # YYYYMMDDHH
        date_string = "1900{}{}{:02d}".format(month, day, hour)

        dt = datetime.strptime(date_string, "%Y%m%d%H") - utc_offset

        # The offset can push the first or last few hours of the year
        # into an adjacent year; fold them back into 1900.
        dt = dt.replace(year=1900, tzinfo=timezone.utc)
        temp_C = float(row[31])

        ts[dt] = temp_C

    return ts


class NormalsSource(object):
    """A typical-year (normals) source.

    One typical year per station, served from a USAF-named archive of
    TMY-format CSVs listed in the source's packaged station table. The
    engine tiles it onto requested calendar years (Feb 29 is NaN),
    caches it, and serves it through ``load_data(source=...)`` — never
    through routing, so typical values cannot silently mix with
    observations. Subclasses declare ``name`` and the archive
    ``_url(usaf_id)``.

    Attributes
    ----------
    name : str
        Unique source name; appears in provenance and cache keys.
    kind : str
        ``"normals"``.
    variables : tuple of str
        Canonical variables the source serves.
    cacheable : bool
        Whether the engine should cache fetched blocks.
    """

    kind = "normals"
    cacheable = True
    variables = ("temperature",)
    default_variables = ("temperature",)

    def _url(self, usaf_id):
        raise NotImplementedError

    def archive_station(self, station_id):
        """The archive row for a station, raising DataNotAvailableError
        when the station has no data in this normals source."""
        conn = metadata_db_connection_proxy.get_connection()
        cur = conn.cursor()
        cur.execute(
            "select * from {}.stations where station_id = ?".format(self.name),
            (station_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise DataNotAvailableError(self.name, station_id=station_id)
        archive = {col[0]: row[i] for i, col in enumerate(cur.description)}

        return archive

    def fetch(self, station_id):
        """The station's typical-year hourly temperature series (year 1900).

        Raises DataNotAvailableError when the station has no data in this
        normals source.
        """
        archive = self.archive_station(station_id)
        url = self._url(archive["usaf_id"])
        try:
            text = request_text(url)
        except FetchError as error:
            # a missing archive file is absent data, not a transport failure
            if error.status_code == 404:
                raise DataNotAvailableError(
                    self.name, station_id=station_id
                ) from error
            raise
        ts = parse_normals_csv(text)

        return ts
