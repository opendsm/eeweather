import contextlib
import functools
import sqlite3

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from eeweather.exceptions import FetchError
import pytz

from eeweather.cache import CacheVolatility
from eeweather.sources.engine import _fetch_year, observation_cache_key
from eeweather.sources.ghcnh import GHCNhSource
from eeweather.sources.pipeline import (
    _datetime_is_utc,
    align_to_range,
    collecting_stale,
    data_gap_warnings,
    deserialize_hourly_data,
    load_year,
    read_cached_year,
    requested_variables,
    resample_by_vocabulary,
    serialize_hourly_data,
)



GHCNH = GHCNhSource()
STATION = "USW00093134"
CACHE_KEY = observation_cache_key("ghcnh", STATION, 2007)

# a grid source's response header, as an adapter would record it
RESPONSE_METADATA = {
    "sources": ["SYN1DEG", "MERRA2", "GEOSIT"],
    "api_version": "v2.9.6",
}

# a source whose data year keeps arriving for four months and whose
# missing tail means "not published yet"
LATE_PUBLISHING = CacheVolatility(grace_days=120, missing_tail_is_volatile=True)


def _backdate_cache_key(store, key, updated):
    with contextlib.closing(sqlite3.connect(store._path)) as conn, conn:
        conn.execute(
            "update items set updated = ? where key = ?", (updated.isoformat(), key)
        )


def _load_2007(
    variables, read_from_cache=True, write_to_cache=True, fetch_from_web=True,
    volatility=CacheVolatility(),
):
    fetch = functools.partial(_fetch_year, GHCNH, STATION, STATION, 2007)
    block = load_year(
        CACHE_KEY, 2007, variables, fetch, GHCNH.cacheable,
        read_from_cache, write_to_cache, fetch_from_web, volatility,
    )

    return block


def _hourly_frame(start, end, value=1.0):
    index = pd.date_range(start, end, freq="h", tz="UTC")
    df = pd.DataFrame({"temperature": value}, index=index)

    return df


def _cache_block(store, df, days_ago, metadata=None):
    store.save_json(CACHE_KEY, serialize_hourly_data(df, metadata))
    _backdate_cache_key(
        store, CACHE_KEY, datetime.now(pytz.UTC) - timedelta(days=days_ago)
    )


# serialization round-trips


def test_serialize_deserialize_hourly_data_round_trip(mock_api_transport):
    df = _fetch_year(GHCNH, STATION, STATION, 2007, ("temperature",))

    serialized = serialize_hourly_data(df)

    assert serialized["columns"] == ["temperature"]
    assert serialized["rows"][0][0] == "2007010100"
    assert len(serialized["rows"]) == len(df)

    round_tripped, metadata = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)
    assert metadata is None


def test_serialize_hourly_data_nan_round_trips_as_null(mock_api_transport):
    df = _fetch_year(GHCNH, "USW00093194", "USW00093194", 2013, ("temperature",))  # ends 2013-11-04

    serialized = serialize_hourly_data(df)

    assert any(row[1] is None for row in serialized["rows"])

    round_tripped, _ = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_multivariable_round_trip(mock_api_transport):
    df = _fetch_year(GHCNH, STATION, STATION, 2007, ("temperature", "wind_speed"))

    round_tripped, _ = deserialize_hourly_data(serialize_hourly_data(df))

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_hourly_data_round_trips_response_metadata(mock_api_transport):
    df = _fetch_year(GHCNH, STATION, STATION, 2007, ("temperature",))

    serialized = serialize_hourly_data(df, RESPONSE_METADATA)

    assert serialized["metadata"] == RESPONSE_METADATA

    round_tripped, metadata = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)
    assert metadata == RESPONSE_METADATA


def test_deserialize_hourly_data_without_metadata_gives_none():
    # blocks a source wrote before it recorded response metadata
    block = {"columns": ["temperature"], "rows": [["2007010100", 1.0]]}

    df, metadata = deserialize_hourly_data(block)

    assert metadata is None
    assert len(df) == 1


# cache freshness


def test_read_cached_year_empty(monkeypatch_key_value_store):
    block, metadata, fresh = read_cached_year(CACHE_KEY, 2007)

    assert block is None
    assert metadata is None
    assert fresh is False


def test_read_cached_year_fresh(mock_api_transport, monkeypatch_key_value_store):
    _load_2007(("temperature",))

    block, _, fresh = read_cached_year(CACHE_KEY, 2007)

    assert block is not None
    assert fresh is True


def test_read_cached_year_reports_a_stale_entry_and_keeps_it(
    mock_api_transport, monkeypatch_key_value_store
):
    _load_2007(("temperature",))

    # a cache entry written during its own data year goes stale, but its
    # block is kept so a refresh can fetch the union of its columns
    _backdate_cache_key(
        monkeypatch_key_value_store, CACHE_KEY, pytz.UTC.localize(datetime(2007, 3, 3))
    )

    block, _, fresh = read_cached_year(CACHE_KEY, 2007)

    assert block is not None
    assert fresh is False
    assert monkeypatch_key_value_store.key_exists(CACHE_KEY) is True


def test_read_cached_year_returns_the_stored_response_metadata(
    monkeypatch_key_value_store
):
    _cache_block(
        monkeypatch_key_value_store,
        _hourly_frame("2007-01-01", "2007-01-02"),
        days_ago=2,
        metadata=RESPONSE_METADATA,
    )

    block, metadata, _ = read_cached_year(CACHE_KEY, 2007)

    assert len(block) == 25
    assert metadata == RESPONSE_METADATA


# per-source volatility: how long a cached year keeps being refetched


def test_read_cached_year_keeps_a_complete_block_for_a_late_publisher(
    monkeypatch_key_value_store
):
    # the tail rule fires on missing data, not on the source's identity
    _cache_block(
        monkeypatch_key_value_store,
        _hourly_frame("2007-01-01", "2007-12-31 23:00"),
        days_ago=2,
    )

    block, _, fresh = read_cached_year(CACHE_KEY, 2007, LATE_PUBLISHING)

    assert block is not None
    assert fresh is True


def test_read_cached_year_keeps_a_missing_tail_by_default(
    monkeypatch_key_value_store
):
    # a station that stopped reporting leaves a permanent missing tail:
    # settled data, not an unpublished one
    df = _hourly_frame("2007-12-01", "2007-12-31 23:00")
    df.iloc[-240:] = float("nan")
    _cache_block(monkeypatch_key_value_store, df, days_ago=2)

    block, _, fresh = read_cached_year(CACHE_KEY, 2007)

    assert block is not None
    assert fresh is True
    assert monkeypatch_key_value_store.key_exists(CACHE_KEY) is True


def test_read_cached_year_marks_a_missing_tail_stale_for_a_late_publisher(
    monkeypatch_key_value_store
):
    df = _hourly_frame("2007-12-01", "2007-12-31 23:00")
    df.iloc[-240:] = float("nan")
    _cache_block(monkeypatch_key_value_store, df, days_ago=2)

    block, _, fresh = read_cached_year(CACHE_KEY, 2007, LATE_PUBLISHING)

    assert block is not None
    assert fresh is False


def test_read_cached_year_serves_a_missing_tail_written_within_a_day(
    monkeypatch_key_value_store
):
    # volatile means refreshable daily, not refetched on every read
    df = _hourly_frame("2007-12-01", "2007-12-31 23:00")
    df.iloc[-240:] = float("nan")
    _cache_block(monkeypatch_key_value_store, df, days_ago=0)

    block, _, fresh = read_cached_year(CACHE_KEY, 2007, LATE_PUBLISHING)

    assert block is not None
    assert fresh is True


def test_read_cached_year_settles_a_block_that_never_published(
    monkeypatch_key_value_store
):
    # all fill is a coverage hole (an ocean point's land-only field),
    # not a tail still arriving; it must not be refetched forever
    df = _hourly_frame("2007-01-01", "2007-12-31 23:00")
    df.iloc[:] = float("nan")
    _cache_block(monkeypatch_key_value_store, df, days_ago=2)

    block, _, fresh = read_cached_year(CACHE_KEY, 2007, LATE_PUBLISHING)

    assert fresh is True


def test_read_cached_year_ignores_a_nightly_gap_at_the_year_end(
    monkeypatch_key_value_store
):
    # a field undefined at night ends every year with a short valueless
    # run; only a run longer than a day reads as an unpublished tail
    df = _hourly_frame("2007-12-01", "2007-12-31 23:00")
    df.iloc[-10:] = float("nan")
    _cache_block(monkeypatch_key_value_store, df, days_ago=2)

    block, _, fresh = read_cached_year(CACHE_KEY, 2007, LATE_PUBLISHING)

    assert fresh is True


# per-year loads: cache reads, union refresh


def test_load_year_serves_from_cache(mock_api_transport, monkeypatch_key_value_store):
    df1 = _load_2007(("temperature",))
    df2 = _load_2007(("temperature",))

    pd.testing.assert_frame_equal(df1, df2, check_freq=False)


def test_load_year_refetches_a_missing_tail_for_a_late_publisher(
    mock_api_transport, monkeypatch_key_value_store
):
    partial = _hourly_frame("2007-12-01", "2007-12-31 23:00")
    partial.iloc[-240:] = float("nan")
    _cache_block(monkeypatch_key_value_store, partial, days_ago=2)

    df = _load_2007(("temperature",), volatility=LATE_PUBLISHING)

    assert len(df) == 8760
    assert df.temperature.notna().any()


def test_load_year_variable_superset_refetches(
    mock_api_transport, monkeypatch_key_value_store
):
    df1 = _load_2007(("temperature",))
    assert list(df1.columns) == ["temperature"]

    # cache holds temperature only, so requesting more refetches the union
    df2 = _load_2007(("temperature", "wind_speed"))
    assert list(df2.columns) == ["temperature", "wind_speed"]

    # the refreshed cache entry now covers both variables
    cached, _, _ = read_cached_year(CACHE_KEY, 2007)
    assert set(cached.columns) == {"temperature", "wind_speed"}

    # a temperature-only request serves the requested subset from cache
    df3 = _load_2007(("temperature",))
    assert list(df3.columns) == ["temperature"]


def test_load_year_refresh_keeps_cached_columns_the_request_omits(
    mock_api_transport, monkeypatch_key_value_store
):
    _load_2007(("temperature",))

    # wind_speed alone still fetches, and caches, the union with temperature
    df = _load_2007(("wind_speed",))
    assert list(df.columns) == ["wind_speed"]

    cached, _, _ = read_cached_year(CACHE_KEY, 2007)
    assert set(cached.columns) == {"temperature", "wind_speed"}


def test_load_year_refresh_of_a_stale_entry_keeps_its_columns(
    mock_api_transport, monkeypatch_key_value_store
):
    _load_2007(("temperature",))

    # the entry goes stale; a wind_speed-only request must still refetch
    # the union so the stale block's temperature column is not dropped
    _backdate_cache_key(
        monkeypatch_key_value_store, CACHE_KEY, pytz.UTC.localize(datetime(2007, 3, 3))
    )

    df = _load_2007(("wind_speed",))
    assert list(df.columns) == ["wind_speed"]

    cached, _, fresh = read_cached_year(CACHE_KEY, 2007)
    assert set(cached.columns) == {"temperature", "wind_speed"}
    assert fresh is True


def test_load_year_without_cache_or_web_returns_none(monkeypatch_key_value_store):
    assert _load_2007(("temperature",), fetch_from_web=False) is None


def test_load_year_without_write_leaves_the_cache_empty(
    mock_api_transport, monkeypatch_key_value_store
):
    df = _load_2007(("temperature",), write_to_cache=False)

    assert len(df) == 8760

    cached, _, _ = read_cached_year(CACHE_KEY, 2007)

    assert cached is None


# request validation: the checks every source path applies


def test_datetime_is_utc_accepts_utc():
    assert _datetime_is_utc(datetime(2020, 1, 1, tzinfo=pytz.UTC)) is True
    assert _datetime_is_utc(datetime(2020, 1, 1, tzinfo=timezone.utc)) is True


def test_datetime_is_utc_rejects_naive():
    assert _datetime_is_utc(datetime(2020, 1, 1)) is False


def test_datetime_is_utc_rejects_offsets():
    assert _datetime_is_utc(
        datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    ) is False
    assert _datetime_is_utc(
        datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=-8)))
    ) is False


def test_requested_variables_defaults_to_the_sources_defaults():
    assert requested_variables(GHCNH, None) == GHCNH.default_variables


def test_requested_variables_expands_all_to_the_whole_vocabulary():
    assert requested_variables(GHCNH, "all") == tuple(GHCNH.variables)


def test_requested_variables_rejects_a_variable_the_source_does_not_serve():
    with pytest.raises(ValueError, match="does not serve: ghi"):
        requested_variables(GHCNH, ("temperature", "ghi"))


def test_requested_variables_rejects_duplicates():
    with pytest.raises(ValueError, match="Duplicate variables"):
        requested_variables(GHCNH, ("temperature", "temperature"))


# range alignment: the shared index every source path produces


def test_resample_bins_land_on_the_epoch_anchored_alignment_grid():
    # an offset that does not divide a day evenly must still fill the
    # grid align_to_range reindexes to, or the frame comes back all NaN
    df = _hourly_frame("2024-03-15", "2024-03-25")
    offset = pd.tseries.frequencies.to_offset("5h")

    aligned = align_to_range(
        resample_by_vocabulary(df, offset),
        pd.Timestamp("2024-03-15", tz="UTC"),
        pd.Timestamp("2024-03-25", tz="UTC"),
        offset,
    )

    assert len(aligned) == 48
    assert aligned.temperature.notna().all()


def test_align_to_range_tick_ceils_start_and_floors_end():
    df = _hourly_frame("2020-01-01", "2020-01-02")
    offset = pd.tseries.frequencies.to_offset("h")

    aligned = align_to_range(
        df,
        pd.Timestamp("2020-01-01 00:20", tz="UTC"),
        pd.Timestamp("2020-01-01 05:40", tz="UTC"),
        offset,
    )

    assert aligned.index[0] == pd.Timestamp("2020-01-01 01:00", tz="UTC")
    assert aligned.index[-1] == pd.Timestamp("2020-01-01 05:00", tz="UTC")
    assert len(aligned) == 5


def test_align_to_range_non_tick_rolls_start_forward_and_end_back():
    df = _hourly_frame("2020-01-01", "2020-06-30")
    offset = pd.tseries.frequencies.to_offset("MS")

    aligned = align_to_range(
        df,
        pd.Timestamp("2020-01-15", tz="UTC"),
        pd.Timestamp("2020-05-20", tz="UTC"),
        offset,
    )

    assert aligned.index[0] == pd.Timestamp("2020-02-01", tz="UTC")
    assert aligned.index[-1] == pd.Timestamp("2020-05-01", tz="UTC")


def test_align_to_range_non_tick_start_inside_a_period_skips_that_period():
    # normalizing 2020-01-01 06:00 rolls forward onto a boundary before
    # start, so the partial first period is dropped
    df = _hourly_frame("2020-01-01", "2020-03-31")
    offset = pd.tseries.frequencies.to_offset("MS")

    aligned = align_to_range(
        df,
        pd.Timestamp("2020-01-01 06:00", tz="UTC"),
        pd.Timestamp("2020-03-31", tz="UTC"),
        offset,
    )

    assert aligned.index[0] == pd.Timestamp("2020-02-01", tz="UTC")
    assert aligned.index[-1] == pd.Timestamp("2020-03-01", tz="UTC")


def test_align_to_range_empty_frame_covers_the_whole_range():
    empty = pd.DataFrame(
        columns=["temperature"],
        index=pd.DatetimeIndex([], tz="UTC"),
        dtype=float,
    )
    offset = pd.tseries.frequencies.to_offset("h")

    aligned = align_to_range(
        empty,
        pd.Timestamp("2020-01-01", tz="UTC"),
        pd.Timestamp("2020-01-02", tz="UTC"),
        offset,
    )

    assert len(aligned) == 25
    assert aligned.temperature.isna().all()


def test_align_to_range_gives_partial_frames_identical_indexes():
    start = pd.Timestamp("2020-01-01 00:30", tz="UTC")
    end = pd.Timestamp("2020-01-03 12:30", tz="UTC")
    offset = pd.tseries.frequencies.to_offset("h")
    early = _hourly_frame("2020-01-01", "2020-01-02")
    late = _hourly_frame("2020-01-02", "2020-01-05")

    aligned_early = align_to_range(early, start, end, offset)
    aligned_late = align_to_range(late, start, end, offset)

    assert aligned_early.index.equals(aligned_late.index)

    joined = pd.concat([aligned_early, aligned_late], axis=1)

    assert len(joined) == len(aligned_early)
    assert int(joined.iloc[:, 0].notna().sum()) == 24
    assert int(joined.iloc[:, 1].notna().sum()) == 37


# gap warnings


def test_data_gap_warnings_leading_gap():
    # synthetic edge case: a series whose data begins three days late
    index = pd.date_range(
        "2020-01-01", "2020-01-31", freq="h", tz="UTC"
    )
    ts = pd.Series(20.0, index=index)
    ts.iloc[: 24 * 3] = float("nan")

    warnings = data_gap_warnings(ts, "ghcnh", "temperature")

    assert [w.qualified_name for w in warnings] == ["eeweather.data_starts_late"]
    assert warnings[0].data["requested_start"] == "2020-01-01T00:00:00+00:00"
    assert warnings[0].data["first_valid"] == "2020-01-04T00:00:00+00:00"


def test_data_gap_warnings_empty_series_is_silent():
    ts = pd.Series([], dtype=float, index=pd.DatetimeIndex([], tz="UTC"))

    assert data_gap_warnings(ts, "ghcnh", "temperature") == []


def _stale_2007_block(store):
    """A cached 2007 block old enough to want refreshing.

    A past year is only refreshable when the source says its tail may still
    be arriving, which is what LATE_PUBLISHING plus a missing tail means.
    """
    partial = _hourly_frame("2007-12-01", "2007-12-31 23:00", value=11.0)
    partial.iloc[-240:] = float("nan")
    _cache_block(store, partial, days_ago=2)


def test_load_year_serves_stale_data_when_the_fetch_fails(
    monkeypatch_key_value_store
):
    """A stale entry that answers the request beats no data at all: the
    values are real, only their freshness is in doubt."""
    _stale_2007_block(monkeypatch_key_value_store)

    def failing_fetch(variables):
        raise FetchError("ghcnh", station_id=STATION, year=2007)

    df = load_year(
        CACHE_KEY, 2007, ("temperature",), failing_fetch, True,
        True, True, True, LATE_PUBLISHING,
    )

    assert df is not None
    assert list(df.columns) == ["temperature"]
    assert df.temperature.notna().any()


def test_load_year_notes_the_year_it_served_stale(monkeypatch_key_value_store):
    """The stale serve is invisible in the returned frame, so load_year
    records the data year for the caller building provenance."""
    _stale_2007_block(monkeypatch_key_value_store)

    def failing_fetch(variables):
        raise FetchError("ghcnh", station_id=STATION, year=2007)

    with collecting_stale() as stale_years:
        df = load_year(
            CACHE_KEY, 2007, ("temperature",), failing_fetch, True,
            True, True, True, LATE_PUBLISHING,
        )

    assert df is not None
    assert stale_years == [2007]


def test_load_year_notes_nothing_on_a_successful_fetch(monkeypatch_key_value_store):
    _stale_2007_block(monkeypatch_key_value_store)

    def good_fetch(variables):
        frame = _hourly_frame("2007-01-01", "2007-12-31 23:00", value=11.0)
        return frame[list(variables)]

    with collecting_stale() as stale_years:
        load_year(
            CACHE_KEY, 2007, ("temperature",), good_fetch, True,
            True, True, True, LATE_PUBLISHING,
        )

    assert stale_years == []


def test_load_year_reraises_fetch_error_when_nothing_is_cached(
    monkeypatch_key_value_store
):
    def failing_fetch(variables):
        raise FetchError("ghcnh", station_id=STATION, year=2007)

    with pytest.raises(FetchError):
        load_year(
            CACHE_KEY, 2007, ("temperature",), failing_fetch, True,
            True, True, True, LATE_PUBLISHING,
        )


def test_load_year_reraises_when_the_stale_block_lacks_a_variable(
    monkeypatch_key_value_store
):
    _stale_2007_block(monkeypatch_key_value_store)

    def failing_fetch(variables):
        raise FetchError("ghcnh", station_id=STATION, year=2007)

    with pytest.raises(FetchError):
        load_year(
            CACHE_KEY, 2007, ("temperature", "wind_speed"), failing_fetch, True,
            True, True, True, LATE_PUBLISHING,
        )


def test_load_year_does_not_swallow_a_non_transport_failure(
    monkeypatch_key_value_store
):
    """Only FetchError degrades; a malformed response still raises."""
    _stale_2007_block(monkeypatch_key_value_store)

    def malformed_fetch(variables):
        raise ValueError("non-csv body")

    with pytest.raises(ValueError):
        load_year(
            CACHE_KEY, 2007, ("temperature",), malformed_fetch, True,
            True, True, True, LATE_PUBLISHING,
        )
