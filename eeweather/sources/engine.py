"""The source-agnostic load engine.

Owns everything between an adapter's fetch and the frame a user receives:
variable routing, per-year caching with variable-union refresh,
typical-year tiling, range alignment, frequency aggregation, gap
warnings, and provenance. Frames for one request range and frequency
always share an identical UTC index regardless of source, so they join
safely.

Missing-data semantics: partial coverage (missing years, station gaps)
surfaces as NaN values plus warnings. A pinned source with nothing at all
for the request raises DataNotAvailableError; a routed request never
raises for missing data.
"""
from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pandas as pd

import eeweather.cache
from ..exceptions import DataNotAvailableError, EEWeatherWarning
from ..registry.identifiers import translate
from ..registry.update import maybe_update
from .cz2010 import CZ2010Source
from .ghcnh import GHCNhSource
from .tmy3 import TMY3Source
from .vocabulary import (
    aggregation_for,
    all_variables,
    register_variables,
    valid_variables_or_raise,
)



BUILTIN_SOURCES = {
    adapter.name: adapter
    for adapter in (GHCNhSource(), TMY3Source(), CZ2010Source())
}

_registered_sources = {}


def register(source, vocabulary=()):
    """Register a custom source under its name.

    Registration makes the source nameable everywhere a built-in name
    works — preference tuples, ``load_data(source=...)``, and location
    serialization (``to_dict``/``from_dict``) — without any change to
    this repository. Accepts station-keyed feeds (``fetch_year``),
    normals sources (``fetch``), and estimation/grid sources
    (``estimate``). Registering the same name again replaces the
    previous object; built-in names cannot be replaced. Returns the
    source.

    A source serving variables outside the vocabulary passes their
    definitions as ``vocabulary`` (an iterable of
    ``eeweather.sources.Variable``); they become requestable and
    routable like canonical entries. Canonical names are reserved, and
    definitions must agree across sources, so the first registration of
    a name freezes its unit.
    """
    name = getattr(source, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError("A source must declare a non-empty string name.")
    if name in BUILTIN_SOURCES:
        raise ValueError("'{}' is a built-in source name.".format(name))
    is_estimation = hasattr(source, "estimate")
    is_fetch_year = hasattr(source, "fetch_year")
    if not is_fetch_year and not hasattr(source, "fetch") and not is_estimation:
        raise ValueError(
            "A registered source must declare one of: fetch_year"
            " (station-keyed feeds), fetch (normals sources), or"
            " estimate (estimation/grid sources)."
        )
    if is_estimation:
        if not hasattr(source, "variables"):
            raise ValueError("An estimation source must declare 'variables'.")
        if not hasattr(source, "kind"):
            raise ValueError("An estimation source must declare 'kind'.")
    elif is_fetch_year:
        if not hasattr(source, "variables"):
            raise ValueError("A fetch_year source must declare 'variables'.")
        if not hasattr(source, "kind"):
            raise ValueError("A fetch_year source must declare 'kind'.")
        if not hasattr(source, "id_namespace"):
            raise ValueError("A fetch_year source must declare 'id_namespace'.")
    else:
        if not hasattr(source, "variables"):
            raise ValueError("A normals source must declare 'variables'.")
    register_variables(vocabulary)
    known = all_variables()
    undeclared = [v for v in source.variables if v not in known]
    if undeclared:
        raise ValueError(
            "Source '{}' serves variables the vocabulary lacks: {}. Pass"
            " their definitions via register(..., vocabulary=...).".format(
                name, ", ".join(undeclared)
            )
        )
    _registered_sources[name] = source

    return source


def known_source_names():
    """Names resolvable to a source: built-in plus registered."""
    return set(BUILTIN_SOURCES) | set(_registered_sources)


def resolve_source(source):
    """The adapter for a source name or source object."""
    if isinstance(source, str):
        if source in BUILTIN_SOURCES:
            return BUILTIN_SOURCES[source]
        if source in _registered_sources:
            return _registered_sources[source]

        raise ValueError(
            "Unknown source: '{}'. Known sources: {}.".format(
                source, ", ".join(sorted(known_source_names()))
            )
        )

    return source


def sources_serving(variable):
    """Names of built-in and registered sources that serve a canonical
    variable."""
    catalog = {**BUILTIN_SOURCES, **_registered_sources}
    names = [
        name
        for name, adapter in sorted(catalog.items())
        if variable in adapter.variables
    ]

    return names



TRAILING_GAP_WARNING_THRESHOLD = timedelta(days=1)
LEADING_GAP_WARNING_THRESHOLD = timedelta(days=1)
INTERNAL_GAP_WARNING_THRESHOLD = timedelta(days=7)

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


def _store():
    return eeweather.cache.key_value_store_proxy.get_store()


def _datetime_is_utc(dt):
    if dt.tzinfo is None:
        return False

    return dt.utcoffset().total_seconds() == 0


def _validate_range(start, end):
    if not _datetime_is_utc(start):
        raise ValueError(
            "start must be an explicit-UTC datetime, got: {}".format(start)
        )
    if not _datetime_is_utc(end):
        raise ValueError("end must be an explicit-UTC datetime, got: {}".format(end))
    if start > end:
        raise ValueError(
            "start must not be after end, got: {} > {}".format(start, end)
        )


def _validate_requested(variables):
    if len(variables) == 0:
        raise ValueError("At least one variable must be requested.")
    if len(set(variables)) != len(variables):
        raise ValueError(
            "Duplicate variables requested: {}".format(", ".join(variables))
        )


def _external_id(adapter, station_id):
    """The id the adapter fetches by, translated from the registry id."""
    namespace = adapter.id_namespace
    if namespace == "ghcn":
        return station_id
    mapping = translate([station_id], "ghcn", namespace)
    external_ids = mapping.get(station_id)
    if not external_ids:
        raise DataNotAvailableError(adapter.name, station_id=station_id)

    return external_ids[0]


def _data_gap_warnings(ts, source, variable):
    """EEWeatherWarnings for requested ranges the returned data does not
    cover: entirely empty series, late-starting or early-ending data, and
    long internal gaps."""
    warnings = []
    if len(ts) == 0:
        return warnings

    if ts.isna().all():
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.no_data_in_requested_range",
                description="No data was available within the requested range.",
                data={
                    "source": source,
                    "variable": variable,
                    "requested_start": ts.index[0].isoformat(),
                    "requested_end": ts.index[-1].isoformat(),
                },
            )
        )

        return warnings

    first_valid = ts.first_valid_index()
    leading_gap = first_valid - ts.index[0]
    if leading_gap > LEADING_GAP_WARNING_THRESHOLD:
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.data_starts_late",
                description=(
                    "Data begins {} after the start of the requested"
                    " range.".format(leading_gap)
                ),
                data={
                    "source": source,
                    "variable": variable,
                    "first_valid": first_valid.isoformat(),
                    "requested_start": ts.index[0].isoformat(),
                },
            )
        )

    last_valid = ts.last_valid_index()
    trailing_gap = ts.index[-1] - last_valid
    if trailing_gap > TRAILING_GAP_WARNING_THRESHOLD:
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.data_truncated",
                description=(
                    "Data ends {} before the end of the requested range.".format(
                        trailing_gap
                    )
                ),
                data={
                    "source": source,
                    "variable": variable,
                    "last_valid": last_valid.isoformat(),
                    "requested_end": ts.index[-1].isoformat(),
                },
            )
        )

    interior = ts.loc[first_valid:last_valid]
    if len(interior) > 1:
        period = interior.index[1] - interior.index[0]
        is_missing = interior.isna()
        max_gap_periods = int(is_missing.groupby((~is_missing).cumsum()).sum().max())
        max_gap = max_gap_periods * period
        if max_gap > INTERNAL_GAP_WARNING_THRESHOLD:
            warnings.append(
                EEWeatherWarning(
                    qualified_name="eeweather.data_gap",
                    description=(
                        "Data contains an internal gap of {}.".format(max_gap)
                    ),
                    data={
                        "source": source,
                        "variable": variable,
                        "max_gap_days": max_gap / timedelta(days=1),
                    },
                )
            )

    return warnings


# observation caching: one JSON block per (source, station, year)


def observation_cache_key(source_name, station_id, year):
    return "{}-hourly-{}-{}".format(source_name, station_id, year)


def serialize_hourly_data(df):
    rows = [
        [index.strftime("%Y%m%d%H")] + values
        for index, values in zip(
            df.index, df.astype(object).where(df.notna(), None).values.tolist()
        )
    ]
    serialized = {"columns": list(df.columns), "rows": rows}

    return serialized


def deserialize_hourly_data(data):
    index = pd.to_datetime(
        [row[0] for row in data["rows"]], format="%Y%m%d%H", utc=True
    )
    df = pd.DataFrame(
        [row[1:] for row in data["rows"]],
        index=index,
        columns=data["columns"],
        dtype=float,
    )

    return df.sort_index().resample("h").mean()


def _read_cached_year(adapter, station_id, year):
    """The fresh cached block for a station-year, or None."""
    store = _store()
    key = observation_cache_key(adapter.name, station_id, year)
    if not store.key_exists(key):
        return None
    if eeweather.cache._expired(store.key_updated(key), year):
        store.clear(key)

        return None

    return deserialize_hourly_data(store.retrieve_json(key))


def _fetch_year(adapter, station_id, external_id, year, variables):
    """One year of observations resampled to an hourly frame.

    Raises DataNotAvailableError when the station has no observations at
    all for the year.
    """
    raw = adapter.fetch_year(external_id, year, variables)
    if len(raw) == 0:
        raise DataNotAvailableError(adapter.name, station_id=station_id, year=year)

    point = [c for c in raw.columns if aggregation_for(c) != "sum"]
    accumulation = [c for c in raw.columns if aggregation_for(c) == "sum"]
    parts = []
    if point:
        # CalTRACK 2.3.3
        parts.append(
            raw[point]
            .resample("min")
            .mean()
            .interpolate(method="linear", limit=60, limit_direction="both")
            .resample("h")
            .mean()
        )
    if accumulation:
        # accumulations add up within the hour and are never fabricated
        # by interpolation
        parts.append(raw[accumulation].resample("h").sum(min_count=1))
    df = pd.concat(parts, axis=1)[list(raw.columns)]

    return df


def _load_observation_year(
    adapter, station_id, external_id, year, variables,
    read_from_cache, write_to_cache, fetch_from_web,
):
    """One year of hourly data, from cache when it covers the request.

    A cache entry serves the request when it is fresh and holds every
    requested variable. Fetches request the union of the requested and
    already-cached variables so a cache refresh never drops columns.
    """
    cached = None
    if adapter.cacheable:
        cached = _read_cached_year(adapter, station_id, year)

    cache_covers_request = cached is not None and set(variables) <= set(cached.columns)
    if read_from_cache and cache_covers_request:
        return cached[list(variables)]

    if not fetch_from_web:
        raise DataNotAvailableError(adapter.name, station_id=station_id, year=year)

    if cached is None:
        cached_columns = ()
    else:
        cached_columns = tuple(cached.columns)
    fetch_variables = tuple(dict.fromkeys(variables + cached_columns))
    df = _fetch_year(adapter, station_id, external_id, year, fetch_variables)
    if adapter.cacheable and write_to_cache:
        _store().save_json(
            observation_cache_key(adapter.name, station_id, year),
            serialize_hourly_data(df),
        )

    return df.reindex(columns=list(variables))


def _load_observations(
    adapter, station_id, start, end, variables,
    read_from_cache, write_to_cache, fetch_from_web,
):
    """Hourly observations over the requested years; missing years surface
    as warnings, and NaN rows after alignment."""
    warnings = []
    data = []
    try:
        external_id = _external_id(adapter, station_id)
    except DataNotAvailableError:
        # station-level condition: the id has no alias in the adapter's
        # namespace; one warning, not one per year
        warnings.append(
            EEWeatherWarning(
                qualified_name="eeweather.data_not_available",
                description="Station has no {} identifier".format(
                    adapter.id_namespace
                ),
                data={"source": adapter.name, "station_id": station_id},
            )
        )
        external_id = None
    if external_id is None:
        years = []
    else:
        years = range(start.year, end.year + 1)
    for year in years:
        try:
            data.append(
                _load_observation_year(
                    adapter, station_id, external_id, year, variables,
                    read_from_cache, write_to_cache, fetch_from_web,
                )
            )
        except DataNotAvailableError:
            warnings.append(
                EEWeatherWarning(
                    qualified_name="eeweather.data_not_available",
                    description="Data not available",
                    data={
                        "source": adapter.name,
                        "station_id": station_id,
                        "year": year,
                    },
                )
            )

    if data:
        df = pd.concat(data)
    else:
        df = pd.DataFrame(
            columns=list(variables),
            index=pd.DatetimeIndex([], tz=timezone.utc),
            dtype=float,
        )

    return df, warnings


# normals: one typical-year JSON block per (source, station), tiled onto
# the requested calendar years


def normals_cache_key(source_name, station_id):
    return "{}-hourly-{}".format(source_name, station_id)


def _load_normals_block(
    adapter, station_id, read_from_cache, write_to_cache, fetch_from_web
):
    store = _store()
    key = normals_cache_key(adapter.name, station_id)
    cached_ok = adapter.cacheable and store.key_exists(key)
    column = adapter.variables[0]

    if read_from_cache and cached_ok:
        cached = deserialize_hourly_data(store.retrieve_json(key))

        return cached[column]

    if not fetch_from_web:
        raise DataNotAvailableError(adapter.name, station_id=station_id)

    ts = adapter.fetch(station_id)
    if adapter.cacheable and write_to_cache:
        store.save_json(key, serialize_hourly_data(ts.to_frame(name=column)))

    return ts


def _load_normals(
    adapter, station_id, start, end, variables,
    read_from_cache, write_to_cache, fetch_from_web,
):
    """The typical year tiled onto each requested calendar year by
    month-day-hour; Feb 29 is NaN."""
    single_year = _load_normals_block(
        adapter, station_id, read_from_cache, write_to_cache, fetch_from_web
    )

    data = []
    for year in range(start.year, end.year + 1):
        tiled_index = single_year.index.map(lambda t: t.replace(year=year))
        data.append(pd.Series(single_year.values, index=tiled_index))
    ts = pd.concat(data).resample("h").mean()
    df = ts.to_frame(name=adapter.variables[0])
    no_warnings = []

    return df, no_warnings


# routing


def _route(variables, adapters):
    """Group requested variables by the first adapter declaring them.

    Normals adapters never participate; they are reachable only by
    explicit pin. Unroutable variables raise, naming the sources that do
    serve them.
    """
    routable = [a for a in adapters if a.kind == "observations"]
    if variables == "all":
        union = []
        for adapter in routable:
            for name in adapter.variables:
                if name not in union:
                    union.append(name)
        variables = tuple(union)
    valid_variables_or_raise(variables)

    groups = {}
    for variable in variables:
        chosen = None
        for adapter in routable:
            if variable in adapter.variables:
                chosen = adapter
                break
        if chosen is None:
            raise ValueError(
                "No configured source serves '{}'. Sources that serve it:"
                " {}.".format(variable, ", ".join(sources_serving(variable)) or "none")
            )
        groups.setdefault(chosen, []).append(variable)
    requested = tuple(variables)

    return groups, requested


def load_data(
    station_id: str,
    start: datetime,
    end: datetime,
    frequency="h",
    variables=None,
    source=None,
    sources=("ghcnh",),
    read_from_cache: bool = True,
    write_to_cache: bool = True,
    fetch_from_web: bool = True,
    raise_when_empty: bool | None = None,
):
    """Load a station's weather data between two dates (inclusive).

    Parameters
    ----------
    station_id : str
        Registry station id.
    start, end : datetime.datetime
        Request range; must be explicit UTC.
    frequency : str or pandas offset
        A pandas offset alias, parsed and validated by pandas itself
        (e.g. '30min', 'h', 'D', 'W', 'MS', 'YS'). Frequencies coarser
        than hourly aggregate the hourly values within each UTC period
        by each variable's vocabulary aggregation: means for
        point-in-time variables, sums (never gap-interpolated) for
        accumulations. Frequencies finer than hourly (they must divide
        the hour evenly) interpolate point-in-time variables linearly
        between hourly values and spread accumulations evenly, never
        crossing a missing hour.
    variables : tuple of str, or 'all'
        Canonical variable names; 'all' is every variable the configured
        sources serve (or, pinned, the pinned source's full vocabulary).
    source : str or source object, optional
        Pin every requested variable to this source, bypassing routing.
        Typical-year sources (tmy3, cz2010) are only reachable this way.
    sources : tuple of (str or source object)
        Ordered source preference for routing; per variable, the first
        source declaring it wins.
    read_from_cache, write_to_cache, fetch_from_web : bool
        Cache and network controls.
    raise_when_empty : bool, optional
        Whether a request yielding no data at all raises
        DataNotAvailableError; defaults to True for pinned requests and
        False for routed ones (partial coverage never raises either way).

    Returns
    -------
    tuple of (pandas.DataFrame, list of EEWeatherWarning)
        One column per requested variable, indexed over the full
        requested range at the requested frequency in UTC; periods
        without data are NaN. The frame's ``attrs["provenance"]`` maps
        each source used to a Provenance record.
    """
    maybe_update()
    _validate_range(start, end)

    # the frequency vocabulary is pandas', bound by delegation: pandas
    # parses the alias, so its spellings, deprecations, and renames apply
    # here automatically
    offset = pd.tseries.frequencies.to_offset(frequency)

    pinned = source is not None
    if raise_when_empty is None:
        raise_when_empty = pinned
    if pinned:
        adapter = resolve_source(source)
        if variables is None:
            variables = tuple(adapter.default_variables)
        elif variables == "all":
            variables = tuple(adapter.variables)
        _validate_requested(tuple(variables))
        unservable = [v for v in variables if v not in adapter.variables]
        if unservable:
            raise ValueError(
                "Source '{}' does not serve: {}. It serves: {}.".format(
                    adapter.name,
                    ", ".join(unservable),
                    ", ".join(adapter.variables),
                )
            )
        groups = {adapter: list(variables)}
        requested = tuple(variables)
    else:
        if variables is None:
            variables = ("temperature",)
        adapters = [resolve_source(entry) for entry in sources]
        groups, requested = _route(variables, adapters)
        _validate_requested(requested)

    warnings = []
    frames = []
    provenance = {}
    for adapter, group_variables in groups.items():
        if adapter.kind == "observations":
            loader = _load_observations
        elif adapter.kind == "normals":
            loader = _load_normals
        else:
            raise ValueError("Unknown source kind: {}".format(adapter.kind))
        group_df, group_warnings = loader(
            adapter, station_id, start, end, tuple(group_variables),
            read_from_cache, write_to_cache, fetch_from_web,
        )
        warnings.extend(group_warnings)
        frames.append(group_df)
        provenance[adapter.name] = Provenance(
            kind=adapter.kind,
            source=adapter.name,
            variables=tuple(group_variables),
            station_id=station_id,
            distance_meters=None,
            payload={},
        )

    df = pd.concat(frames, axis=1)[list(requested)]
    if offset != pd.tseries.frequencies.to_offset("h"):
        df = _resample_by_vocabulary(df, offset)
    df = df[start:end]

    # start and end dates need to fall exactly on period boundaries; a
    # period partially before start is excluded, end's period is included
    if isinstance(offset, pd.tseries.offsets.Tick):
        range_start = pd.Timestamp(start).ceil(offset)
        range_end = pd.Timestamp(end).floor(offset)
    else:
        range_start = offset.rollforward(pd.Timestamp(start).normalize())
        if range_start < pd.Timestamp(start):
            range_start = range_start + offset
        range_end = offset.rollback(pd.Timestamp(end).normalize())

    # cover the full requested range even when no data loaded
    df = df.reindex(pd.date_range(range_start, range_end, freq=offset))

    # nothing at all for the requested dates (not merely the requested
    # calendar years) raises for pinned requests
    if raise_when_empty and len(df) > 0 and df.isna().all().all():
        source_name = ", ".join(sorted(a.name for a in groups))
        raise DataNotAvailableError(source_name, station_id=station_id)

    for adapter, group_variables in groups.items():
        for variable in group_variables:
            warnings.extend(_data_gap_warnings(df[variable], adapter.name, variable))

    df.attrs["provenance"] = provenance

    return df, warnings


def load_cached_data(station_id, source_name="ghcnh"):
    """All fresh cached hourly observations for a station from one
    source, or None when nothing is cached. Applies the same staleness
    rule as loads."""
    store = _store()
    prefix = "{}-hourly-{}-".format(source_name, station_id)
    data = []
    for key in store.keys(prefix):
        year = int(key.rsplit("-", 1)[1])
        if eeweather.cache._expired(store.key_updated(key), year):
            continue
        data.append(deserialize_hourly_data(store.retrieve_json(key)))
    if not data:
        return None
    df = pd.concat(data).resample("h").mean()

    return df


def _resample_by_vocabulary(df, offset):
    """Hourly values at the requested frequency, column by column.

    Coarser periods roll up by the column's vocabulary aggregation; a
    period with no data at all is NaN regardless of aggregation. Every
    label is its period's start. Sub-hourly slots interpolate
    point-in-time columns linearly between hourly values and spread
    accumulations evenly, never crossing a missing hour.
    """
    if isinstance(offset, pd.tseries.offsets.Tick) and (
        pd.Timedelta(offset) < pd.Timedelta(hours=1)
    ):
        return _upsample(df, offset)

    resampled = df.resample(offset, label="left", closed="left")
    columns = {}
    for column in df.columns:
        aggregation = aggregation_for(column)
        if aggregation == "sum":
            columns[column] = resampled[column].sum(min_count=1)
        else:
            columns[column] = getattr(resampled[column], aggregation)()
    aggregated = pd.DataFrame(columns)

    return aggregated


def _upsample(df, offset):
    """Hourly values at a finer frequency; the offset must divide the
    hour evenly."""
    step = pd.Timedelta(offset)
    if pd.Timedelta(hours=1) % step != pd.Timedelta(0):
        raise ValueError(
            "A sub-hourly frequency must divide the hour evenly,"
            " got: {}".format(offset.freqstr)
        )
    slots = int(pd.Timedelta(hours=1) / step)

    up = df.resample(offset).asfreq()
    columns = {}
    for column in df.columns:
        if aggregation_for(column) == "sum":
            spread = df[column].reindex(up.index, method="ffill", limit=slots - 1)
            columns[column] = spread / slots
        else:
            filled = up[column].interpolate(method="linear", limit_area="inside")
            valid = df[column].notna()
            left_valid = valid.reindex(up.index, method="ffill")
            right_valid = valid.reindex(up.index, method="bfill")
            columns[column] = filled.where(left_valid & right_valid)
    upsampled = pd.DataFrame(columns)

    return upsampled


def variables() -> pd.DataFrame:
    """The canonical variable vocabulary and which sources serve each
    entry, as a DataFrame indexed by variable name."""
    catalog = all_variables()
    rows = []
    for name, variable in sorted(catalog.items()):
        rows.append(
            {
                "unit": variable.unit,
                "description": variable.description,
                "aggregation": variable.aggregation,
                "sources": tuple(sources_serving(name)),
            }
        )
    df = pd.DataFrame(rows, index=sorted(catalog))
    df.index.name = "variable"

    return df
