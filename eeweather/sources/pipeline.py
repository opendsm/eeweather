"""Shared load machinery, independent of how a source is keyed.

Station feeds and gridded sources alike cache one hourly block per year,
refresh it by variable union, align it to the requested range, aggregate
it to the requested frequency, and report coverage gaps through this
module. Because every path aligns here, frames for one request range and
frequency share an identical UTC index and join safely.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

import eeweather.cache
from ..cache import CacheVolatility
from ..exceptions import EEWeatherWarning, FetchError
from .vocabulary import aggregation_for



TRAILING_GAP_WARNING_THRESHOLD = timedelta(days=1)
LEADING_GAP_WARNING_THRESHOLD = timedelta(days=1)
INTERNAL_GAP_WARNING_THRESHOLD = timedelta(days=7)


def _datetime_is_utc(dt):
    if dt.tzinfo is None:
        return False

    return dt.utcoffset().total_seconds() == 0


def validate_range(start, end):
    """Reject a request range that is not an ordered pair of explicit-UTC
    datetimes."""
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


def validate_requested(variables):
    """Reject a requested variable list that is empty or repeats a name."""
    if len(variables) == 0:
        raise ValueError("At least one variable must be requested.")
    if len(set(variables)) != len(variables):
        raise ValueError(
            "Duplicate variables requested: {}".format(", ".join(variables))
        )


def requested_variables(adapter, variables):
    """The variables one source is asked for when every variable is
    served by it: its defaults when unspecified, its whole vocabulary for
    'all', validated against what it serves."""
    if variables is None:
        variables = tuple(adapter.default_variables)
    elif variables == "all":
        variables = tuple(adapter.variables)
    variables = tuple(variables)
    validate_requested(variables)

    unservable = [v for v in variables if v not in adapter.variables]
    if unservable:
        raise ValueError(
            "Source '{}' does not serve: {}. It serves: {}.".format(
                adapter.name, ", ".join(unservable), ", ".join(adapter.variables)
            )
        )

    return variables


def store():
    return eeweather.cache.key_value_store_proxy.get_store()


def serialize_hourly_data(df, metadata=None):
    """The block written to the cache: the frame, plus whatever the
    source recorded about the response that produced it."""
    rows = [
        [index.strftime("%Y%m%d%H")] + values
        for index, values in zip(
            df.index, df.astype(object).where(df.notna(), None).values.tolist()
        )
    ]
    serialized = {"columns": list(df.columns), "rows": rows}
    if metadata is not None:
        serialized["metadata"] = metadata

    return serialized


def deserialize_hourly_data(data):
    """The frame a block holds and the response metadata it was written
    with; blocks written without metadata deserialize to None."""
    index = pd.to_datetime(
        [row[0] for row in data["rows"]], format="%Y%m%d%H", utc=True
    )
    df = pd.DataFrame(
        [row[1:] for row in data["rows"]],
        index=index,
        columns=data["columns"],
        dtype=float,
    )
    hourly = df.sort_index().resample("h").mean()
    metadata = data.get("metadata")

    return hourly, metadata


# longer than any night, so a field undefined at night never reads as an
# unpublished tail
MISSING_TAIL_MIN_HOURS = 25


def _missing_tail(df):
    """Whether the block ends in a run of valueless rows longer than a
    day — the shape a source leaves where it has not published a year's
    tail yet. Columns that never published anything are left out: a block
    that is all fill is a coverage hole, settled by the volatility
    window, not a tail still arriving. An empty block counts as missing
    its tail."""
    if len(df) == 0:
        return True

    published = df.loc[:, df.notna().any()]
    if published.shape[1] == 0:
        return False

    valued = published.notna().any(axis=1)
    last_valued = valued[valued].index[-1]
    trailing_hours = len(valued.loc[last_valued:]) - 1

    return trailing_hours >= MISSING_TAIL_MIN_HOURS


def read_cached_year(key, year, volatility=CacheVolatility()):
    """The cached block under a key, the response metadata it carries,
    and whether the entry is still fresh for its data year —
    (None, None, False) when nothing is cached.

    A stale block is returned rather than dropped so a refresh can fetch
    the union of its columns and the request's; serving it is the
    caller's decision, gated on ``fresh``."""
    cache = store()
    if not cache.key_exists(key):
        return None, None, False

    df, metadata = deserialize_hourly_data(cache.retrieve_json(key))
    still_arriving = volatility.missing_tail_is_volatile and _missing_tail(df)
    fresh = not eeweather.cache._expired(
        cache.key_updated(key), year, volatility.grace_days, still_arriving
    )

    return df, metadata, fresh


def load_year(
    key, year, variables, fetch, cacheable,
    read_from_cache, write_to_cache, fetch_from_web,
    volatility=CacheVolatility(),
):
    """One year of hourly data under a cache key, from cache when it
    covers the request.

    A cache entry serves the request when it is fresh under the source's
    ``volatility`` and holds every requested variable. Otherwise
    ``fetch`` is called with the union of the requested and
    already-cached variables, so a refresh never drops a column, and its
    frame is returned reindexed to the requested columns. Returns None
    when only a fetch could serve the request and fetching is disabled.

    If that fetch fails for transport reasons and a stale cached block
    holds every requested variable, the stale block is served rather than
    the failure propagating.
    """
    cached, fresh = None, False
    if cacheable:
        cached, _, fresh = read_cached_year(key, year, volatility)

    cache_covers_request = fresh and cached is not None and set(variables) <= set(cached.columns)
    if read_from_cache and cache_covers_request:
        return cached[list(variables)]

    if not fetch_from_web:
        return None

    if cached is None:
        cached_columns = ()
    else:
        cached_columns = tuple(cached.columns)
    fetch_variables = tuple(dict.fromkeys(variables + cached_columns))
    try:
        df = fetch(fetch_variables)
    except FetchError:
        # A stale entry that answers the request is better than nothing: the
        # data is real, only its freshness is in doubt, and the reason it was
        # being refreshed is that the year may still be receiving records.
        # Only a transport failure degrades this way -- DataNotAvailableError
        # and a malformed response still raise.
        if read_from_cache and cached is not None and set(variables) <= set(cached.columns):
            return cached[list(variables)]
        raise
    if cacheable and write_to_cache:
        store().save_json(key, serialize_hourly_data(df))

    return df.reindex(columns=list(variables))


def align_to_range(df, start, end, offset):
    """The frame on every period of the requested range at one frequency.

    Start and end fall exactly on period boundaries: a period partially
    before start is excluded, and end's own period is included. The full
    range is covered even when no data loaded, so periods without data
    are NaN and two frames aligned over the same range and frequency
    share an index.
    """
    df = df[start:end]
    if isinstance(offset, pd.tseries.offsets.Tick):
        range_start = pd.Timestamp(start).ceil(offset)
        range_end = pd.Timestamp(end).floor(offset)
    else:
        range_start = offset.rollforward(pd.Timestamp(start).normalize())
        if range_start < pd.Timestamp(start):
            range_start = range_start + offset
        range_end = offset.rollback(pd.Timestamp(end).normalize())

    return df.reindex(pd.date_range(range_start, range_end, freq=offset))


def resample_by_vocabulary(df, offset):
    """Hourly values at the requested frequency, column by column.

    Coarser periods roll up by the column's vocabulary aggregation; a
    period with no data at all is NaN regardless of aggregation. Every
    label is its period's start. Sub-hourly slots interpolate
    point-in-time columns linearly between hourly values and spread
    accumulations evenly, never crossing a missing hour.
    """
    if isinstance(offset, pd.tseries.offsets.Tick) and (
        pd.Timedelta(offset) < pd.Timedelta(1, unit="h")
    ):
        return _upsample(df, offset)

    resample_kwargs = {"label": "left", "closed": "left"}
    if isinstance(offset, pd.tseries.offsets.Tick):
        # anchor bins to the epoch so they land on the same grid
        # align_to_range builds with ceil()/floor(); pandas' default
        # anchors to the frame's first day and misses that grid for any
        # offset that does not divide a day evenly
        resample_kwargs["origin"] = "epoch"
    resampled = df.resample(offset, **resample_kwargs)
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
    if pd.Timedelta(1, unit="h") % step != pd.Timedelta(0):
        raise ValueError(
            "A sub-hourly frequency must divide the hour evenly,"
            " got: {}".format(offset.freqstr)
        )
    slots = int(pd.Timedelta(1, unit="h") / step)

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


def data_gap_warnings(ts, source, variable):
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
