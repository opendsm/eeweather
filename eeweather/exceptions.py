"""Exceptions and the warning type returned by data loads.

These are data-dependent conditions pipelines legitimately branch on.
Caller bugs (e.g. non-UTC datetimes) raise plain ValueError instead.
"""


class EEWeatherError(Exception):
    """Base class for exceptions in the eeweather package."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class UnrecognizedStationError(EEWeatherError):
    """Raised when a station id is not in the registry.

    Attributes
    ----------
    value : str
        the value which is not a recognized station id
    """

    def __init__(self, value):
        super().__init__(
            'The value "{}" was not recognized as a valid weather station'
            " identifier.".format(value)
        )
        self.value = value


class UnrecognizedPlaceError(EEWeatherError):
    """Raised when a place code is not in the registry.

    Attributes
    ----------
    kind : str
        the place kind, e.g. ``'zcta'``
    code : str
        the code which is not a recognized place of that kind
    """

    def __init__(self, kind, code):
        super().__init__(
            'The value "{}" was not recognized as a valid place of kind'
            ' "{}".'.format(code, kind)
        )
        self.kind = kind
        self.code = code


class AmbiguousIdentifierError(EEWeatherError):
    """Raised when an external identifier maps to multiple stations and no
    mapping is marked recent.

    Attributes
    ----------
    namespace : str
        the identifier system, e.g. ``'wban'``
    external_id : str
        the ambiguous identifier
    station_ids : tuple of str
        the registry stations the identifier maps to
    """

    def __init__(self, namespace, external_id, station_ids):
        super().__init__(
            'The {} id "{}" maps to multiple stations ({}) and cannot be'
            " resolved.".format(namespace, external_id, ", ".join(station_ids))
        )
        self.namespace = namespace
        self.external_id = external_id
        self.station_ids = tuple(station_ids)


class DataNotAvailableError(EEWeatherError):
    """Raised when a source has no data at all for a request.

    Partial coverage never raises; it surfaces as NaN values plus warnings.

    Attributes
    ----------
    source : str
        the source that had no data
    station_id : str or None
        the station requested; None for non-station sources
    year : int or None
        the year requested; None when the whole request had no data
    """

    def __init__(self, source, *, station_id=None, year=None):
        super().__init__(
            "No {} data available for station={} year={}.".format(
                source, station_id, year
            )
        )
        self.source = source
        self.station_id = station_id
        self.year = year


class FetchError(EEWeatherError):
    """Raised when a source could not retrieve data over the network.

    Transport failures used to escape as raw ``requests`` exceptions, so a
    caller had to import ``requests`` to catch them -- and no exception is
    exported at the top level, so it had to know the submodule too. This
    distinguishes "the network failed" from "the data does not exist"
    (:class:`DataNotAvailableError`), which is the difference between a
    request worth retrying and one that never will be.

    Attributes
    ----------
    source : str
        the source whose fetch failed
    station_id : str or None
        the station requested; None for non-station sources
    year : int or None
        the year requested; None when the failure was not year-scoped
    """

    def __init__(self, source, *, station_id=None, year=None, cause=None):
        super().__init__(
            "Could not fetch {} data for station={} year={}: {}".format(
                source, station_id, year, cause
            )
        )
        self.source = source
        self.station_id = station_id
        self.year = year
        self.cause = cause

    @property
    def status_code(self):
        """The HTTP status that caused this, or None if the request never
        got a response (a timeout or a connection error)."""
        response = getattr(self.cause, "response", None)

        return None if response is None else response.status_code


class NoQualifiedStationError(EEWeatherError):
    """Raised when no station in the registry qualifies to estimate weather
    at a location under the configured filters.

    Attributes
    ----------
    latitude, longitude : float
        the location that could not be served
    """

    def __init__(self, latitude, longitude):
        super().__init__(
            "No qualified station found for location ({}, {}).".format(
                latitude, longitude
            )
        )
        self.latitude = latitude
        self.longitude = longitude


class EEWeatherWarning(object):
    """A warning describing a data condition, returned alongside loaded data.

    Attributes
    ----------
    qualified_name : str
        Qualified name, e.g. ``'eeweather.data_gap'``.
    description : str
        Prose describing the nature of the warning.
    data : dict
        Data that reproducibly shows why the warning was issued.
    """

    def __init__(self, qualified_name, description, data):
        self.qualified_name = qualified_name
        self.description = description
        self.data = data

    def __repr__(self):
        return "EEWeatherWarning(qualified_name={})".format(self.qualified_name)

    def json(self):
        serialized = {
            "qualified_name": self.qualified_name,
            "description": self.description,
            "data": self.data,
        }

        return serialized
