"""The NASA POWER grid source served through the POWER hourly point API."""
import math
import random

from collections import namedtuple
from datetime import date, datetime, timezone

import pandas as pd
import requests

from .. import budget

from ...__version__ import __version__
from ...cache import CacheVolatility
from ...exceptions import (
    DataNotAvailableError,
    EEWeatherWarning,
    FetchError,
)
from ..base import Provenance, Source
from ..pipeline import (
    align_to_range,
    data_gap_warnings,
    read_cached_year,
    requested_variables,
    resample_by_vocabulary,
    serialize_hourly_data,
    store,
    validate_range,
)



SOURCE_NAME = "nasa-power"

API_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"

# the api rejects a submission carrying more parameters than this
MAX_PARAMETERS = 20

API_REQUEST_TRIES = 4

API_RETRY_BACKOFF_SECONDS = 2

API_TIMEOUT_SECONDS = 120

USER_AGENT = "eeweather/{} (+https://github.com/opendsm/eeweather)".format(__version__)

KPA_TO_HPA = 10.0

# hourly precipitation fields are served as mm/day rates, not hourly depths
PER_DAY_TO_HOURLY = 1.0 / 24.0

# native_unit is checked against every response so a silent upstream unit
# change fails loudly; scale multiplies a native value into the canonical unit
Parameter = namedtuple("Parameter", ["native", "canonical", "native_unit", "scale"])

# the meteorological grid (MERRA-2, spliced with GEOS-IT near real time)
MET_PARAMETERS = (
    Parameter("T2M", "temperature", "C", 1.0),
    Parameter("T2MDEW", "dew_point_temperature", "C", 1.0),
    Parameter("RH2M", "relative_humidity", "%", 1.0),
    Parameter("WS10M", "wind_speed", "m/s", 1.0),
    Parameter("QV2M", "specific_humidity", "g/kg", 1.0),
    Parameter("TS", "skin_temperature", "C", 1.0),
    Parameter("TSOIL1", "soil_temperature", "C", 1.0),
    Parameter("U10M", "eastward_wind", "m/s", 1.0),
    Parameter("V10M", "northward_wind", "m/s", 1.0),
    Parameter("Z0M", "surface_roughness", "m", 1.0),
    Parameter("PS", "surface_pressure", "kPa", KPA_TO_HPA),
    Parameter("PRECTOTCORR", "precipitation", "mm/day", PER_DAY_TO_HOURLY),
    Parameter("PRECSNO", "snowfall", "mm/day", PER_DAY_TO_HOURLY),
    Parameter("FRSNO", "snow_cover", "1", 1.0),
)

# the solar grid (CERES SYN1deg); irradiance arrives as Wh/m^2 over the hour,
# numerically identical to the hourly mean W/m2, so no scaling applies
SOLAR_PARAMETERS = (
    Parameter("ALLSKY_SFC_SW_DWN", "ghi", "Wh/m^2", 1.0),
    Parameter("CLRSKY_SFC_SW_DWN", "clearsky_ghi", "Wh/m^2", 1.0),
    Parameter("ALLSKY_SFC_SW_DNI", "dni", "Wh/m^2", 1.0),
    Parameter("CLRSKY_SFC_SW_DNI", "clearsky_dni", "Wh/m^2", 1.0),
    Parameter("ORIGINAL_ALLSKY_SFC_SW_DIFF", "dhi", "Wh/m^2", 1.0),
    Parameter("CLRSKY_SFC_SW_DIFF", "clearsky_dhi", "Wh/m^2", 1.0),
    Parameter("ORIGINAL_ALLSKY_SFC_SW_DIRH", "bhi", "Wh/m^2", 1.0),
    Parameter("CLRSKY_SFC_SW_DIRH", "clearsky_bhi", "Wh/m^2", 1.0),
    Parameter("ALLSKY_SRF_ALB", "albedo", "dimensionless", 1.0),
    Parameter("ALLSKY_SFC_LW_DWN", "longwave_down", "Wh/m^2", 1.0),
    Parameter("ALLSKY_SFC_LW_UP", "longwave_up", "Wh/m^2", 1.0),
    Parameter("AIRMASS", "airmass", "dimensionless", 1.0),
    Parameter("AOD_55", "aerosol_optical_depth_550", "dimensionless", 1.0),
    Parameter("AOD_84", "aerosol_optical_depth_840", "dimensionless", 1.0),
    Parameter("PW", "precipitable_water", "cm", 1.0),
    Parameter("CLOUD_AMT", "cloud_cover", "%", 1.0),
)

# each family is a distinct grid with its own geometry and publication latency
FAMILY_PARAMETERS = {"met": MET_PARAMETERS, "solar": SOLAR_PARAMETERS}

PARAMETERS = {
    parameter.native: parameter
    for parameter in MET_PARAMETERS + SOLAR_PARAMETERS
}

FAMILY_OF = {
    parameter.canonical: family
    for family, parameters in FAMILY_PARAMETERS.items()
    for parameter in parameters
}

NATIVE_OF = {
    parameter.canonical: parameter.native
    for parameter in MET_PARAMETERS + SOLAR_PARAMETERS
}

# the meteorological grid: cells are centre-registered on multiples of
# the step, latitude from the equator and longitude from the prime
# meridian, and each cell owns its low edge
MET_LATITUDE_STEP = 0.5

MET_LONGITUDE_STEP = 0.625

# the solar grid: cells are edge-registered on integer degrees, so their
# centres fall on half degrees; it is independent of the met grid
SOLAR_STEP = 1.0

Cell = namedtuple("Cell", ["latitude", "longitude"])

Coverage = namedtuple("Coverage", ["first_year", "latency_days", "volatility"])

# what each grid has published and how long it keeps rewriting it. The
# met tail is provisional GEOS-IT that MERRA-2 later replaces; the solar
# chain publishes a rolling window months in arrears at month
# granularity, so a cached year holds an unpublished tail for a season.
FAMILY_COVERAGE = {
    "met": Coverage(
        first_year=2001,
        latency_days=2,
        volatility=CacheVolatility(grace_days=60, missing_tail_is_volatile=True),
    ),
    "solar": Coverage(
        first_year=2001,
        latency_days=90,
        volatility=CacheVolatility(grace_days=120, missing_tail_is_volatile=True),
    ),
}

# undefined at night, so their fill is interior rather than trailing and
# cannot on its own say where a family's published data ends
NIGHT_UNDEFINED = ("albedo", "airmass")

Block = namedtuple("Block", ["data", "sources", "api_version", "elevation"])

# one session for connection reuse across the many per-point-year requests
_session = requests.Session()


def _get(url, params):  # pragma: no cover (mocked in tests via this seam)
    response = _session.get(
        url=url,
        params=params,
        timeout=budget.timeout_for(API_TIMEOUT_SECONDS),
        headers={"User-Agent": USER_AGENT},
    )

    return response


def _retryable(status_code):
    """Whether another attempt could succeed: the documented rate limit and
    server faults, never a client error."""
    retryable = status_code == 429 or status_code >= 500

    return retryable


def _retry_delay(response, attempt):
    """Seconds to wait before the next attempt, honoring a Retry-After delay
    when the api sends one and otherwise backing off exponentially with
    jitter."""
    retry_after = response.headers.get("Retry-After", "")
    if retry_after.strip().isdigit():
        return float(retry_after)

    delay = API_RETRY_BACKOFF_SECONDS * 2**attempt
    jittered = delay * (1 + random.random())

    return jittered


def _error_messages(response):
    """The api's complaints about a request, empty when the body is not its
    json error document."""
    try:
        payload = response.json()
    except ValueError:
        return ()

    return tuple(payload.get("messages", ()))


def _rejection(status_code, messages):
    """A submission the api would not serve, quoting its own explanation."""
    error = ValueError(
        "The NASA POWER api served no data with status {}: {}".format(
            status_code, "; ".join(messages) or "no explanation given"
        )
    )

    return error


def _request(latitude, longitude, start, end, parameters):
    """Issue one POWER submission and return its parsed json body.

    Rate-limit and server responses are retried with growing backoff;
    client errors raise immediately, and a rejected submission raises a
    ValueError quoting the api's own messages rather than parsing an
    error document as data.
    """
    params = {
        "parameters": ",".join(parameters),
        "community": "RE",
        "latitude": latitude,
        "longitude": longitude,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
        # the api serves local solar time unless told otherwise
        "time-standard": "UTC",
    }

    for attempt in range(API_REQUEST_TRIES):
        budget.check("nasa_power {},{}".format(latitude, longitude))
        try:
            response = _get(API_URL, params)
        except requests.RequestException as error:
            if attempt == API_REQUEST_TRIES - 1:
                raise FetchError("nasa-power", cause=error) from error
            budget.sleep_within(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
        if not _retryable(response.status_code) or attempt == API_REQUEST_TRIES - 1:
            break
        budget.sleep_within(_retry_delay(response, attempt))

    if response.status_code >= 400:
        messages = _error_messages(response)
        if messages:
            raise _rejection(response.status_code, messages)
        response.raise_for_status()

    payload = response.json()
    # an error document carries messages in place of the data properties
    if "properties" not in payload:
        raise _rejection(response.status_code, payload.get("messages", ()))

    return payload


def _parse(payload, parameters):
    """Normalize a response into canonical columns on a UTC hourly index."""
    fill_value = payload["header"]["fill_value"]
    reported_units = payload["parameters"]
    values = payload["properties"]["parameter"]

    columns = {}
    for native in parameters:
        parameter = PARAMETERS[native]
        reported = reported_units[native]["units"]
        if reported != parameter.native_unit:
            raise ValueError(
                "The NASA POWER api served {} in '{}' where eeweather expects"
                " '{}'; the conversion to {} is no longer valid.".format(
                    native, reported, parameter.native_unit, parameter.canonical
                )
            )

        series = pd.Series(values[native], dtype=float)
        columns[parameter.canonical] = (
            series.mask(series == fill_value) * parameter.scale
        )

    df = pd.DataFrame(columns)
    df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
    df = df.sort_index()

    return df


def _chunks(parameters):
    """Split a parameter list into submissions the api will accept."""
    for start in range(0, len(parameters), MAX_PARAMETERS):
        yield parameters[start:start + MAX_PARAMETERS]


def cell_for(family, latitude, longitude):
    """The centre of the grid cell containing a point, on one family's
    grid.

    The api echoes whatever point it was asked about, so cell identity is
    entirely client-side arithmetic; requests go to the centre so every
    point inside a cell produces one cache key and one identical series.
    A cell owns its low edge, and every boundary is an exact binary
    fraction, so no tolerance is needed. The antimeridian is one cell —
    longitude 180 is the same meridian as -180, and a met centre that
    lands on 180 is keyed as -180 — and the solar grid's top row is
    capped at its 89.5 centre; the met grid has true pole rows.
    """
    if longitude == 180.0:
        longitude = -180.0

    if family == "met":
        latitude_steps = math.floor(
            (latitude + MET_LATITUDE_STEP / 2) / MET_LATITUDE_STEP
        )
        longitude_steps = math.floor(
            (longitude + MET_LONGITUDE_STEP / 2) / MET_LONGITUDE_STEP
        )
        longitude_centre = MET_LONGITUDE_STEP * longitude_steps
        if longitude_centre == 180.0:
            longitude_centre = -180.0
        cell = Cell(MET_LATITUDE_STEP * latitude_steps, longitude_centre)
    elif family == "solar":
        latitude_centre = math.floor(latitude / SOLAR_STEP) * SOLAR_STEP + SOLAR_STEP / 2
        if latitude_centre > 89.5:
            latitude_centre = 89.5
        cell = Cell(
            latitude_centre,
            math.floor(longitude / SOLAR_STEP) * SOLAR_STEP + SOLAR_STEP / 2,
        )
    else:
        raise ValueError("Unknown NASA POWER grid family: {}".format(family))

    return cell


def cache_key(family, cell, year):
    """The key of one cached block: one grid family, one cell, one
    year."""
    key = "{}-hourly-{}-{:.4f}_{:.4f}-{}".format(
        SOURCE_NAME, family, cell.latitude, cell.longitude, year
    )

    return key


def _by_family(variables):
    """Requested variables grouped by the grid family serving them, each
    group in the order requested."""
    grouped = {}
    for variable in variables:
        grouped.setdefault(FAMILY_OF[variable], []).append(variable)
    groups = {family: tuple(names) for family, names in grouped.items()}

    return groups


def _block_metadata(block):
    """What the response said about itself, stored with the block.
    Reprocessed CERES editions and near-real-time values replaced by
    final ones make cached values silently mutable without it."""
    metadata = {
        "sources": list(block.sources),
        "api_version": block.api_version,
        "elevation": block.elevation,
    }

    return metadata


def _published_through(df):
    """The last hour a family has published within a frame, read from the
    values rather than the response header: the api answers a request
    that runs past its published edge in full, padding the unpublished
    tail with fill.

    Fields undefined at night are left out: their last value dates the
    last daylight hour, not the last published one. None when nothing
    was published, and None when every loaded field is a night-undefined
    one, where the coverage gap is reported without dating an edge.
    """
    dated = [column for column in df.columns if column not in NIGHT_UNDEFINED]
    if not dated:
        return None

    published = df[dated].dropna(how="all")
    if len(published) == 0:
        return None

    return published.index[-1]


def _latency_warning(family, published_through, requested_end):
    if published_through is None:
        extent = "any of the requested range"
        published = None
    else:
        extent = "through the end of the requested range"
        published = published_through.isoformat()

    warning = EEWeatherWarning(
        qualified_name="eeweather.source_latency",
        description=(
            "The {} {} grid publishes about {} days in arrears and has not"
            " published {}.".format(
                SOURCE_NAME, family, FAMILY_COVERAGE[family].latency_days, extent
            )
        ),
        data={
            "source": SOURCE_NAME,
            "family": family,
            "requested_end": requested_end.isoformat(),
            "published_through": published,
        },
    )

    return warning


class NASAPowerSource(Source):
    """Gridded weather from NASA POWER's hourly point API.

    Two independent grids serve the variables: a meteorological family
    (MERRA-2/GEOS-IT) and a solar family (CERES SYN1deg), each with its
    own cell geometry and publication latency. The api serves the value
    of the cell containing the requested point, without interpolation, so
    a load is addressed to the cell rather than to the point: every point
    inside one cell shares one cached block and receives one identical
    series.

    The source is location-keyed and has no station identifiers, so it is
    reached through a :class:`~eeweather.WeatherLocation` and never
    through the station-keyed surfaces.
    """

    name = SOURCE_NAME
    kind = "observations"
    cacheable = True
    variables = tuple(
        parameter.canonical for parameter in MET_PARAMETERS + SOLAR_PARAMETERS
    )
    default_variables = ("temperature",)

    def estimate(
        self,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        frequency="h",
        variables=None,
        read_from_cache: bool = True,
        write_to_cache: bool = True,
        fetch_from_web: bool = True,
        raise_when_empty: bool = False,
        ignore_disqualification: bool = False,
        **load_kwargs,
    ):
        """Weather at a point between two dates (inclusive).

        Each requested variable is served from its family's grid cell,
        so one load can span both grids; the frame is aligned and
        aggregated by the shared pipeline, giving it the same index a
        station source produces for the same range and frequency.

        ``ignore_disqualification`` and any other station-selection
        keywords are accepted and ignored: a location calls every source
        through one call site, and a grid cell has nothing to qualify.

        Returns
        -------
        tuple of (pandas.DataFrame, list of EEWeatherWarning, dict)
            The provenance dict maps this source's name to a Provenance
            record whose payload is keyed by grid family, carrying each
            family's cell and the response header the values came with.
        """
        validate_range(start, end)
        offset = pd.tseries.frequencies.to_offset(frequency)
        variables = requested_variables(self, variables)

        frames = []
        warnings = []
        payload = {}
        for family, family_variables in _by_family(variables).items():
            family_df, family_warnings, family_payload = self._load_family(
                family, latitude, longitude, start, end, family_variables,
                read_from_cache, write_to_cache, fetch_from_web,
            )
            frames.append(family_df)
            warnings.extend(family_warnings)
            payload[family] = family_payload

        df = pd.concat(frames, axis=1)[list(variables)]
        if offset != pd.tseries.frequencies.to_offset("h"):
            df = resample_by_vocabulary(df, offset)
        df = align_to_range(df, start, end, offset)

        if raise_when_empty and len(df) > 0 and df.isna().all().all():
            raise DataNotAvailableError(self.name)

        for variable in variables:
            warnings.extend(data_gap_warnings(df[variable], self.name, variable))

        provenance = {
            self.name: Provenance(
                kind=self.kind,
                source=self.name,
                variables=variables,
                station_id=None,
                distance_meters=None,
                payload=payload,
            )
        }
        df.attrs["provenance"] = provenance

        return df, warnings, provenance

    def _load_family(
        self, family, latitude, longitude, start, end, variables,
        read_from_cache, write_to_cache, fetch_from_web,
    ):
        """One grid family's hourly variables over the requested years,
        with the cell and response header they came from.

        Years before the family began publishing are not requested;
        missing hours surface as NaN, and a range running past what the
        family has published draws a latency warning.
        """
        cell = cell_for(family, latitude, longitude)
        coverage = FAMILY_COVERAGE[family]
        blocks = []
        sources = []
        api_versions = []
        elevation = None
        for year in range(max(start.year, coverage.first_year), end.year + 1):
            block, metadata = self._load_year(
                family, cell, year, variables,
                read_from_cache, write_to_cache, fetch_from_web,
            )
            if block is None:
                continue
            blocks.append(block)
            for name in metadata["sources"]:
                if name not in sources:
                    sources.append(name)
            if metadata["api_version"] not in api_versions:
                api_versions.append(metadata["api_version"])
            elevation = metadata["elevation"]

        if blocks:
            df = pd.concat(blocks)
        else:
            df = pd.DataFrame(
                columns=list(variables),
                index=pd.DatetimeIndex([], tz=timezone.utc),
                dtype=float,
            )

        payload = {
            "cell_lat": cell.latitude,
            "cell_lon": cell.longitude,
            "sources": sources,
            "api_versions": api_versions,
        }
        if family == "met":
            # the elevation the response geometry carries is the mean
            # elevation of the met cell, served unchanged on solar-only
            # requests; the solar grid has no elevation of its own
            payload["cell_elevation"] = elevation

        warnings = []
        requested_end = pd.Timestamp(end).floor("h")
        # the edge is read from the whole fetched frame, not the
        # requested slice: a range that sits entirely past the edge has
        # an all-fill slice, which dates nothing but is exactly the case
        # the warning exists for
        published_through = _published_through(df)
        dated_requested = any(name not in NIGHT_UNDEFINED for name in variables)
        behind = published_through is None or published_through < requested_end
        if blocks and dated_requested and behind:
            warnings.append(
                _latency_warning(family, published_through, requested_end)
            )

        return df, warnings, payload

    def _load_year(
        self, family, cell, year, variables,
        read_from_cache, write_to_cache, fetch_from_web,
    ):
        """One year of one cell's block, from cache when it covers the
        request.

        A cache entry serves the request when it is fresh under the
        family's volatility window and holds every requested variable.
        Otherwise the api is asked for the union of the requested and
        already-cached variables, so a refresh never drops a column, and
        the block is written only once the whole frame is in hand — a
        submission that fails partway leaves no partial block behind.
        Returns (None, None) when only a fetch could serve the request
        and fetching is disabled.
        """
        key = cache_key(family, cell, year)
        cached, metadata, fresh = None, None, False
        if self.cacheable:
            cached, metadata, fresh = read_cached_year(
                key, year, FAMILY_COVERAGE[family].volatility
            )

        covers_request = (
            fresh and cached is not None and set(variables) <= set(cached.columns)
        )
        if read_from_cache and covers_request:
            requested = cached[list(variables)]

            return requested, metadata

        if not fetch_from_web:
            return None, None

        if cached is None:
            cached_columns = ()
        else:
            cached_columns = tuple(cached.columns)
        wanted = tuple(dict.fromkeys(variables + cached_columns))
        block = self.fetch(
            cell.latitude,
            cell.longitude,
            date(year, 1, 1),
            date(year, 12, 31),
            tuple(NATIVE_OF[name] for name in wanted),
        )
        metadata = _block_metadata(block)
        if self.cacheable and write_to_cache:
            store().save_json(key, serialize_hourly_data(block.data, metadata))
        requested = block.data.reindex(columns=list(variables))

        return requested, metadata

    def fetch(self, latitude, longitude, start, end, parameters):
        """Fetch native POWER parameters for one grid point and date range.

        Parameters
        ----------
        latitude, longitude : float
            The point the api samples; POWER serves the containing cell.
        start, end : datetime.date
            Inclusive UTC date bounds of the request.
        parameters : sequence of str
            Native POWER parameter names, requested serially in chunks
            the api accepts and reassembled in the order given.

        Returns
        -------
        Block
            ``data`` is one column per parameter under its canonical
            name, indexed by UTC hour, with fill values as NaN and
            values converted to canonical units. ``sources`` and
            ``api_version`` come from the response header and identify
            the upstream products the values were built from, and
            ``elevation`` is the met cell's mean elevation, which the
            response geometry carries whatever family was requested.
        """
        parameters = tuple(parameters)
        frames = []
        sources = []
        api_version = None
        elevation = None
        for chunk in _chunks(parameters):
            payload = _request(latitude, longitude, start, end, chunk)
            frames.append(_parse(payload, chunk))
            for source in payload["header"]["sources"]:
                if source not in sources:
                    sources.append(source)
            if api_version is None:
                api_version = payload["header"]["api"]["version"]
                elevation = payload["geometry"]["coordinates"][2]

        data = pd.concat(frames, axis=1)
        block = Block(data, tuple(sources), api_version, elevation)

        return block
