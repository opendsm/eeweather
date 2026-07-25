import contextlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import pytz

from eeweather.exceptions import DataNotAvailableError
from eeweather.sources.engine import (
    _data_gap_warnings,
    _datetime_is_utc,
    _fetch_year,
    _load_normals_block,
    _load_observation_year,
    _read_cached_year,
    deserialize_hourly_data,
    load_cached_data,
    load_data,
    normals_cache_key,
    observation_cache_key,
    Provenance,
    serialize_hourly_data,
)
from eeweather.sources.ghcnh import GHCNhSource
from eeweather.sources.tmy3 import TMY3Source



GHCNH = GHCNhSource()
TMY3 = TMY3Source()


def _backdate_cache_key(store, key, updated):
    with contextlib.closing(sqlite3.connect(store._path)) as conn, conn:
        conn.execute(
            "update items set updated = ? where key = ?", (updated.isoformat(), key)
        )


# fetch


def test_fetch_year(mock_api_transport):
    df = _fetch_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",))

    assert list(df.columns) == ["temperature"]
    assert df.shape == (8760, 1)
    assert df.index[0] == datetime(2007, 1, 1, tzinfo=pytz.UTC)
    assert df.temperature.sum() == pytest.approx(156159.5455, abs=1e-3)


def test_fetch_year_multiple_variables(mock_api_transport):
    df = _fetch_year(
        GHCNH, "USW00093134", "USW00093134", 2007,
        ("temperature", "relative_humidity"),
    )

    assert list(df.columns) == ["temperature", "relative_humidity"]
    assert df.shape == (8760, 2)


def test_fetch_year_missing_year_raises(mock_api_transport):
    with pytest.raises(DataNotAvailableError) as excinfo:
        _fetch_year(GHCNH, "USW00093134", "USW00093134", 1800, ("temperature",))
    assert excinfo.value.source == "ghcnh"
    assert excinfo.value.year == 1800


# cache keys


def test_observation_cache_key():
    key = observation_cache_key("ghcnh", "USW00093134", 2007)

    assert key == "ghcnh-hourly-USW00093134-2007"


def test_normals_cache_key():
    assert normals_cache_key("tmy3", "USW00023152") == "tmy3-hourly-USW00023152"


# cache freshness


def test_read_cached_year_empty(monkeypatch_key_value_store):
    assert _read_cached_year(GHCNH, "USW00093134", 2007) is None


def test_read_cached_year_fresh(mock_api_transport, monkeypatch_key_value_store):
    _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                           True, True, True)

    assert _read_cached_year(GHCNH, "USW00093134", 2007) is not None


def test_read_cached_year_expired_entry_is_cleared(
    mock_api_transport, monkeypatch_key_value_store
):
    _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                           True, True, True)

    # a cache entry written during its own data year goes stale
    key = observation_cache_key("ghcnh", "USW00093134", 2007)
    _backdate_cache_key(
        monkeypatch_key_value_store, key, pytz.UTC.localize(datetime(2007, 3, 3))
    )

    assert _read_cached_year(GHCNH, "USW00093134", 2007) is None
    assert monkeypatch_key_value_store.key_exists(key) is False


def test_load_observation_year_no_cache_no_web_raises(monkeypatch_key_value_store):
    with pytest.raises(DataNotAvailableError):
        _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                               True, True, False)


# serialization round-trips


def test_serialize_deserialize_hourly_data_round_trip(mock_api_transport):
    df = _fetch_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",))

    serialized = serialize_hourly_data(df)

    assert serialized["columns"] == ["temperature"]
    assert serialized["rows"][0][0] == "2007010100"
    assert len(serialized["rows"]) == len(df)

    round_tripped = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_hourly_data_nan_round_trips_as_null(mock_api_transport):
    df = _fetch_year(GHCNH, "USW00093194", "USW00093194", 2013, ("temperature",))  # ends 2013-11-04

    serialized = serialize_hourly_data(df)

    assert any(row[1] is None for row in serialized["rows"])

    round_tripped = deserialize_hourly_data(serialized)

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_serialize_multivariable_round_trip(mock_api_transport):
    df = _fetch_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature", "wind_speed"))

    round_tripped = deserialize_hourly_data(serialize_hourly_data(df))

    pd.testing.assert_frame_equal(round_tripped, df, check_freq=False)


def test_normals_block_round_trips_through_the_hourly_serializer(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    fresh = _load_normals_block(TMY3, "USW00023152", True, True, True)
    cached = _load_normals_block(TMY3, "USW00023152", True, True, True)

    pd.testing.assert_series_equal(
        cached, fresh, check_freq=False, check_names=False
    )


# cached proxy behavior


def test_load_observation_year_serves_from_cache(
    mock_api_transport, monkeypatch_key_value_store
):
    df1 = _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                                 True, True, True)
    df2 = _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                                 True, True, True)

    pd.testing.assert_frame_equal(df1, df2, check_freq=False)


def test_load_observation_year_variable_superset_refetches(
    mock_api_transport, monkeypatch_key_value_store
):
    df1 = _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                                 True, True, True)
    assert list(df1.columns) == ["temperature"]

    # cache holds temperature only, so requesting more refetches the union
    df2 = _load_observation_year(
        GHCNH, "USW00093134", "USW00093134", 2007, ("temperature", "wind_speed"),
        True, True, True,
    )
    assert list(df2.columns) == ["temperature", "wind_speed"]

    # the refreshed cache entry now covers both variables
    cached = _read_cached_year(GHCNH, "USW00093134", 2007)
    assert set(cached.columns) == {"temperature", "wind_speed"}

    # a temperature-only request serves the requested subset from cache
    df3 = _load_observation_year(GHCNH, "USW00093134", "USW00093134", 2007, ("temperature",),
                                 True, True, True)
    assert list(df3.columns) == ["temperature"]


def test_load_normals_block_cached(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    ts1 = _load_normals_block(TMY3, "USW00023152", True, True, True)
    ts2 = _load_normals_block(TMY3, "USW00023152", True, True, True)

    assert int(ts1.sum()) == int(ts2.sum()) == 156194
    assert monkeypatch_key_value_store.key_exists("tmy3-hourly-USW00023152")


def test_load_normals_block_no_cache_no_web_raises(monkeypatch_key_value_store):
    with pytest.raises(DataNotAvailableError):
        _load_normals_block(TMY3, "USW00023152", True, True, False)


# load_data: hourly and daily observed


def test_load_data_hourly(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert df.index[0] == start
    assert df.index[-1] == end
    assert len(df) == 10921
    assert int(df.temperature.notna().sum()) == 10893
    assert warnings == []


def test_load_data_hourly_non_normalized_dates(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert df.index[0] == datetime(2006, 1, 3, 12, tzinfo=pytz.UTC)
    assert df.index[-1] == datetime(2007, 4, 3, 12, tzinfo=pytz.UTC)


def test_load_data_daily(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end, frequency="D")

    assert df.index[0] == start
    assert df.index[-1] == end
    assert len(df) == 456
    assert int(df.temperature.notna().sum()) == 456
    assert warnings == []


def test_load_data_daily_non_normalized_dates(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, 11, 12, 13, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, 12, 13, 14, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end, frequency="D")

    assert df.index[0] == datetime(2006, 1, 4, tzinfo=pytz.UTC)
    assert df.index[-1] == datetime(2007, 4, 3, tzinfo=pytz.UTC)


def test_load_data_invalid_frequency(monkeypatch_key_value_store):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    with pytest.raises(ValueError, match="frequency"):
        load_data("USW00093134", start, end, frequency="fortnight")


def test_load_data_non_utc_datetimes_raise():
    with pytest.raises(ValueError, match="UTC"):
        load_data(
            "USW00093134",
            datetime(2007, 1, 1),
            datetime(2007, 4, 3, tzinfo=pytz.UTC),
        )

    with pytest.raises(ValueError, match="UTC"):
        load_data(
            "USW00093134",
            datetime(2007, 1, 1, tzinfo=pytz.UTC),
            datetime(2007, 4, 3),
        )


def test_load_data_multiple_variables(mock_api_transport, monkeypatch_key_value_store):
    start = datetime(2007, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 6, 30, tzinfo=pytz.UTC)

    df, warnings = load_data(
        "USW00093134",
        start,
        end,
        variables=("temperature", "relative_humidity", "wind_speed"),
    )

    assert df.shape == (697, 3)
    assert df.temperature.mean() == pytest.approx(19.304219, abs=1e-5)
    assert df.relative_humidity.mean() == pytest.approx(67.903771, abs=1e-5)
    assert df.wind_speed.mean() == pytest.approx(0.843799, abs=1e-5)
    assert warnings == []


def test_load_data_variables_all_is_source_union(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 6, 2, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end, variables="all")

    assert list(df.columns) == list(GHCNH.variables)


def test_load_data_unroutable_variable_raises():
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    with pytest.raises(ValueError, match="Unknown variables"):
        load_data("USW00093134", start, end, variables=("not_a_variable",))


def test_load_data_pinned_source_never_servable_variable_raises():
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    with pytest.raises(ValueError, match="does not serve"):
        load_data(
            "USW00093134", start, end, source="tmy3", variables=("wind_speed",)
        )


# provenance


def test_load_data_provenance_on_frame(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    record = df.attrs["provenance"]["ghcnh"]
    assert record.kind == "observations"
    assert record.source == "ghcnh"
    assert record.station_id == "USW00093134"
    assert record.distance_meters is None
    assert record.variables == ("temperature",)


def test_provenance_station_fields_and_payload_are_optional():
    record = Provenance(kind="observations", source="ghcnh", variables=("temperature",))

    assert record.station_id is None
    assert record.distance_meters is None
    assert record.payload == {}

    with_payload = record._replace(payload={"model_version": "v1"})

    assert with_payload.payload == {"model_version": "v1"}


def test_load_data_pinned_normals_provenance(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00023152", start, end, source="tmy3")

    record = df.attrs["provenance"]["tmy3"]
    assert record.kind == "normals"
    assert record.variables == ("temperature",)


# regression pins on real captured 2007 data


def test_load_data_hourly_2007_regression_values(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert len(df) == 8737
    assert int(df.temperature.notna().sum()) == 8732
    assert df.temperature.mean() == pytest.approx(17.851812, abs=1e-5)
    assert warnings == []


def test_load_data_daily_2007_regression_values(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end, frequency="D")

    assert len(df) == 365
    assert int(df.temperature.notna().sum()) == 365
    assert df.temperature.mean() == pytest.approx(17.835431, abs=1e-5)
    assert df.temperature.iloc[0] == pytest.approx(13.27734, abs=1e-5)


# typical-year loads through the one verb


def test_load_data_tmy3_pinned(monkeypatch_tmy3_request, monkeypatch_key_value_store):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00023152", start, end, source="tmy3")

    assert df.index[0] == start
    assert pd.notnull(df.temperature.iloc[0])
    assert df.index[-1] == end
    assert pd.notnull(df.temperature.iloc[-1])
    assert warnings == []


def test_load_data_cz2010_pinned(
    monkeypatch_cz2010_request, monkeypatch_key_value_store
):
    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00023152", start, end, source="cz2010")

    assert df.index[0] == start
    assert df.index[-1] == end
    assert int(df.temperature.notna().sum()) == len(df)


def test_load_data_normals_tile_by_month_day_hour_with_nan_leap_day(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2015, 2, 15, tzinfo=pytz.UTC)
    end = datetime(2016, 8, 12, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00023152", start, end, source="tmy3")
    ts_orig = TMY3.fetch("USW00023152")

    for i in df.index:
        if i.month == 2 and i.day == 29:
            assert pd.isnull(df.temperature[i])
        else:
            assert df.temperature[i] == ts_orig[i.replace(year=1900)]


def test_load_data_normals_excluded_from_routing(
    mock_api_transport, monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    # tmy3 leads the preference tuple but normals never route; temperature
    # must come from ghcnh
    df, warnings = load_data(
        "USW00093134", start, end, sources=("tmy3", "ghcnh")
    )

    assert list(df.attrs["provenance"]) == ["ghcnh"]
    assert df.attrs["provenance"]["ghcnh"].kind == "observations"


# warnings


def test_load_data_warns_on_truncated_data(
    mock_api_transport, monkeypatch_key_value_store
):
    # station 723826 was decommissioned 2013-11-04
    start = datetime(2013, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2013, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093194", start, end)

    assert len(df) == 5113
    assert int(df.temperature.notna().sum()) == 1619
    assert df.temperature.last_valid_index() == datetime(
        2013, 11, 4, 19, tzinfo=pytz.UTC
    )
    assert [w.qualified_name for w in warnings] == ["eeweather.data_truncated"]
    assert warnings[0].data["variable"] == "temperature"
    assert warnings[0].data["source"] == "ghcnh"
    assert warnings[0].data["last_valid"] == "2013-11-04T19:00:00+00:00"


def test_load_data_daily_warns_on_truncated_data(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2013, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2013, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093194", start, end, frequency="D")

    assert len(df) == 214
    assert int(df.temperature.notna().sum()) == 156
    assert [w.qualified_name for w in warnings] == ["eeweather.data_truncated"]


def test_load_data_warns_on_internal_gap(
    mock_api_transport, monkeypatch_key_value_store
):
    # station 720193's 2019 data has a real mid-year outage
    start = datetime(2019, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2019, 12, 31, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00000117", start, end)

    assert len(df) == 8737
    assert int(df.temperature.notna().sum()) == 8106
    assert [w.qualified_name for w in warnings] == ["eeweather.data_gap"]
    assert warnings[0].data["max_gap_days"] == pytest.approx(16.125, abs=1e-9)


def test_data_gap_warnings_leading_gap():
    # synthetic edge case: a series whose data begins three days late
    index = pd.date_range(
        "2020-01-01", "2020-01-31", freq="h", tz="UTC"
    )
    ts = pd.Series(20.0, index=index)
    ts.iloc[: 24 * 3] = float("nan")

    warnings = _data_gap_warnings(ts, "ghcnh", "temperature")

    assert [w.qualified_name for w in warnings] == ["eeweather.data_starts_late"]
    assert warnings[0].data["requested_start"] == "2020-01-01T00:00:00+00:00"
    assert warnings[0].data["first_valid"] == "2020-01-04T00:00:00+00:00"


def test_data_gap_warnings_empty_series_is_silent():
    ts = pd.Series([], dtype=float, index=pd.DatetimeIndex([], tz="UTC"))

    assert _data_gap_warnings(ts, "ghcnh", "temperature") == []


def test_load_data_2025_extends_past_isd_end_of_life(
    mock_api_transport, monkeypatch_key_value_store
):
    # GHCNh continues past the ISD end-of-life: station 724940's 2025 data
    # runs through the year while its ISD record stopped 2025-08-27
    start = datetime(2025, 6, 1, tzinfo=pytz.UTC)
    end = datetime(2025, 10, 1, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00023234", start, end)

    assert len(df) == 2929
    assert int(df.temperature.notna().sum()) == 2840
    assert df.temperature.last_valid_index() == end
    assert warnings == []


# missing data semantics: routed loads warn and return NaN; pinned loads
# with nothing at all raise


def test_load_data_routed_missing_year_returns_nan_range(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2050, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2050, 6, 1, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert df.index[0] == start
    assert df.index[-1] == end
    assert df.temperature.isna().all()
    assert [w.qualified_name for w in warnings] == [
        "eeweather.data_not_available",
        "eeweather.no_data_in_requested_range",
    ]
    assert warnings[0].data["station_id"] == "USW00093134"


def test_load_data_pinned_source_with_no_data_at_all_raises(
    mock_api_transport, monkeypatch_key_value_store
):
    start = datetime(2050, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2050, 6, 1, tzinfo=pytz.UTC)

    with pytest.raises(DataNotAvailableError) as excinfo:
        load_data("USW00093134", start, end, source="ghcnh")
    assert excinfo.value.source == "ghcnh"
    assert excinfo.value.station_id == "USW00093134"
    assert excinfo.value.year is None


def test_load_data_year_with_no_observations(
    mock_api_transport, monkeypatch_key_value_store
):
    # station 722874 has no GHCNh observations at all in 2025
    start = datetime(2025, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2025, 6, 1, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert len(df) == 3625
    assert df.temperature.isna().all()
    assert [w.qualified_name for w in warnings] == [
        "eeweather.data_not_available",
        "eeweather.no_data_in_requested_range",
    ]


def test_load_data_sub_hour_range_returns_empty(
    mock_api_transport, monkeypatch_key_value_store
):
    # a sub-hour range contains no aligned hours; returns empty without warning
    start = datetime(2007, 6, 1, 12, 30, tzinfo=pytz.UTC)
    end = datetime(2007, 6, 1, 12, 45, tzinfo=pytz.UTC)

    df, warnings = load_data("USW00093134", start, end)

    assert len(df) == 0
    assert warnings == []


# join-safety guarantee: same range and frequency means identical indexes
# across sources


def test_frames_from_different_sources_share_an_index(
    mock_api_transport, monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    start = datetime(2007, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    observed, _ = load_data("USW00093134", start, end)
    typical, _ = load_data("USW00023152", start, end, source="tmy3")

    assert observed.index.equals(typical.index)

    joined = observed.join(typical, rsuffix="_typical")

    assert list(joined.columns) == ["temperature", "temperature_typical"]
    assert len(joined) == len(observed)


# cached data access


def test_load_cached_data(mock_api_transport, monkeypatch_key_value_store):
    assert load_cached_data("USW00093134") is None

    load_data(
        "USW00093134",
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 4, 3, tzinfo=pytz.UTC),
    )
    cached = load_cached_data("USW00093134")

    assert cached is not None
    assert list(cached.columns) == ["temperature"]
    # the cache holds the full fetched year, not just the requested slice
    assert len(cached) == 8760

# request-range validation


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


def test_load_data_pinned_raises_when_requested_dates_are_empty(
    mock_api_transport, monkeypatch_key_value_store
):
    # station 723826 was decommissioned 2013-11-04: its calendar year has
    # data, the requested December does not
    start = datetime(2013, 12, 1, tzinfo=pytz.UTC)
    end = datetime(2013, 12, 31, tzinfo=pytz.UTC)

    with pytest.raises(DataNotAvailableError) as excinfo:
        load_data("USW00093194", start, end, source="ghcnh")
    assert excinfo.value.source == "ghcnh"

    # the routed equivalent warns and returns NaN
    df, warnings = load_data("USW00093194", start, end)
    assert df.temperature.isna().all()
    assert len(warnings) > 0


def test_load_data_start_after_end_raises():
    with pytest.raises(ValueError, match="start must not be after end"):
        load_data(
            "USW00093134",
            datetime(2007, 6, 1, tzinfo=pytz.UTC),
            datetime(2007, 1, 1, tzinfo=pytz.UTC),
        )


def test_load_data_duplicate_variables_raise():
    with pytest.raises(ValueError, match="Duplicate variables"):
        load_data(
            "USW00093134",
            datetime(2007, 1, 1, tzinfo=pytz.UTC),
            datetime(2007, 2, 1, tzinfo=pytz.UTC),
            variables=("temperature", "temperature"),
        )


def test_load_data_empty_variables_raise():
    with pytest.raises(ValueError, match="At least one variable"):
        load_data(
            "USW00093134",
            datetime(2007, 1, 1, tzinfo=pytz.UTC),
            datetime(2007, 2, 1, tzinfo=pytz.UTC),
            variables=(),
        )


def test_load_data_untranslatable_station_warns_once(
    mock_api_transport, monkeypatch_key_value_store
):
    # a fixture feed keyed by usaf, asked about a station with no usaf id,
    # warns once for the station-level condition, not once per year
    class UsafFeed(GHCNhSource):
        name = "usaf-feed"
        id_namespace = "usaf"
        cacheable = False

    # ASN00026044's usaf alias was removed in the alias audit
    df, warnings = load_data(
        "ASN00026044",
        datetime(2019, 1, 1, tzinfo=pytz.UTC),
        datetime(2021, 12, 31, tzinfo=pytz.UTC),
        sources=(UsafFeed(),),
    )

    assert df.temperature.isna().all()
    names = [w.qualified_name for w in warnings]
    assert names.count("eeweather.data_not_available") == 1
