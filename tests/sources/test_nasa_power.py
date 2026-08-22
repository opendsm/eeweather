import gzip
import json
import os

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import requests

from eeweather.exceptions import DataNotAvailableError
from eeweather.sources.nasa_power import NASAPowerSource
from eeweather.sources.nasa_power.source import (
    API_REQUEST_TRIES,
    MAX_PARAMETERS,
    MET_PARAMETERS,
    SOLAR_PARAMETERS,
    _parse,
    cache_key,
    cell_for,
)
from eeweather.sources.pipeline import deserialize_hourly_data



FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"

MET_FIXTURE = "nasa_power_met_34.02_-118.29_2024.json.gz"

SOLAR_FIXTURE = "nasa_power_solar_34.02_-118.29_2024.json.gz"

MET_EDGE_FIXTURE = "nasa_power_met_edge_2026.json.gz"

SOLAR_EDGE_FIXTURE = "nasa_power_solar_edge_2026.json.gz"

GRID_FIXTURES = {
    ("met", "2024"): MET_FIXTURE,
    ("solar", "2024"): SOLAR_FIXTURE,
    ("met", "2026"): MET_EDGE_FIXTURE,
    ("solar", "2026"): SOLAR_EDGE_FIXTURE,
}

MET_NATIVE = tuple(parameter.native for parameter in MET_PARAMETERS)

SOLAR_NATIVE = tuple(parameter.native for parameter in SOLAR_PARAMETERS)

MET_CANONICAL = tuple(parameter.canonical for parameter in MET_PARAMETERS)

POINT = (34.02, -118.29)

START = date(2024, 6, 1)

END = date(2024, 6, 30)

# the captured month, as a request range
JUNE_START = datetime(2024, 6, 1, tzinfo=timezone.utc)

JUNE_END = datetime(2024, 6, 30, 23, tzinfo=timezone.utc)

# a clear June afternoon hour and a June night hour at the fixture point
NOON = pd.Timestamp("2024-06-15 20:00", tz="UTC")

NIGHT = pd.Timestamp("2024-06-15 10:00", tz="UTC")

_ERROR_BODY = json.loads(
    (FIXTURE_DIR / "nasa_power_error_too_many_parameters.json").read_text()
)


def _fixture_payload(name):
    with gzip.open(FIXTURE_DIR / name, "rb") as f:
        payload = json.loads(f.read().decode())

    return payload


class MockResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if self.payload is None:
            raise ValueError("no json body")

        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                "{} error".format(self.status_code), response=self
            )


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("eeweather.sources.budget.time.sleep", sleeps.append)

    return sleeps


@pytest.fixture
def responses(monkeypatch):
    """Serve a scripted response per attempt, recording each request."""
    scripted = []
    calls = []

    def mock_get(url, params=None):
        calls.append(params)

        return scripted[min(len(calls) - 1, len(scripted) - 1)]

    monkeypatch.setattr("eeweather.sources.nasa_power.source._get", mock_get)

    return scripted, calls


@pytest.fixture
def chunked_transport(monkeypatch):
    """Serve both captured families from one point-year as a single grid.

    The two fixtures cover the same point and range, so a request for
    any subset of the 30 parameters is served by slicing them; the
    fixture records the parameter list of each submission.
    """
    payload = _fixture_payload(MET_FIXTURE)
    solar = _fixture_payload(SOLAR_FIXTURE)
    payload["parameters"].update(solar["parameters"])
    payload["properties"]["parameter"].update(solar["properties"]["parameter"])
    requested = []

    def mock_get(url, params=None):
        names = params["parameters"].split(",")
        requested.append(names)
        served = dict(payload)
        served["parameters"] = {name: payload["parameters"][name] for name in names}
        served["properties"] = {
            "parameter": {
                name: payload["properties"]["parameter"][name] for name in names
            }
        }

        return MockResponse(served)

    monkeypatch.setattr("eeweather.sources.nasa_power.source._get", mock_get)

    return requested


def _served_family(names):
    if names[0] in MET_NATIVE:
        family = "met"
    elif names[0] in SOLAR_NATIVE:
        family = "solar"
    else:
        raise AssertionError("unknown POWER parameter: {}".format(names[0]))

    return family


def _serve(names, year):
    """The captured family response for a year, sliced to the parameters
    one submission asked for."""
    payload = _fixture_payload(GRID_FIXTURES[(_served_family(names), year)])
    served = dict(payload)
    served["parameters"] = {name: payload["parameters"][name] for name in names}
    served["properties"] = {
        "parameter": {
            name: payload["properties"]["parameter"][name] for name in names
        }
    }

    return MockResponse(served)


@pytest.fixture
def grid_transport(monkeypatch):
    """Serve the captured families for any cell and year, recording each
    submission.

    Unlike the point-keyed conftest fixture, this answers whichever cell
    centre the source addresses, so the cell arithmetic is free to vary
    across tests.
    """
    calls = []

    def mock_get(url, params=None):
        calls.append(params)

        return _serve(params["parameters"].split(","), params["start"][:4])

    monkeypatch.setattr("eeweather.sources.nasa_power.source._get", mock_get)

    return calls


def _fetch(parameters):
    source = NASAPowerSource()
    block = source.fetch(POINT[0], POINT[1], START, END, parameters)

    return block


def _estimate(point=POINT, start=JUNE_START, end=JUNE_END, **kwargs):
    source = NASAPowerSource()
    result = source.estimate(point[0], point[1], start, end, **kwargs)

    return result


def test_fetch_pins_the_submission_parameters(responses):
    scripted, calls = responses
    scripted.append(MockResponse(_fixture_payload(MET_FIXTURE)))

    _fetch(("T2M", "PS"))

    assert len(calls) == 1
    assert calls[0] == {
        "parameters": "T2M,PS",
        "community": "RE",
        "latitude": 34.02,
        "longitude": -118.29,
        "start": "20240601",
        "end": "20240630",
        "format": "JSON",
        "time-standard": "UTC",
    }


def test_fetch_indexes_hourly_values_in_utc(mock_nasa_power_transport):
    block = _fetch(MET_NATIVE)

    assert isinstance(block.data.index, pd.DatetimeIndex)
    assert str(block.data.index.tz) == "UTC"
    assert block.data.index[0] == pd.Timestamp("2024-06-01 00:00", tz="UTC")
    assert block.data.index[-1] == pd.Timestamp("2024-06-30 23:00", tz="UTC")
    assert len(block.data) == 720


def test_fetch_renames_met_parameters_to_canonical_columns(mock_nasa_power_transport):
    block = _fetch(MET_NATIVE)

    assert tuple(block.data.columns) == (
        "temperature",
        "dew_point_temperature",
        "relative_humidity",
        "wind_speed",
        "specific_humidity",
        "skin_temperature",
        "soil_temperature",
        "eastward_wind",
        "northward_wind",
        "surface_roughness",
        "surface_pressure",
        "precipitation",
        "snowfall",
        "snow_cover",
    )
    assert block.data.loc[NOON, "temperature"] == 30.11


def test_fetch_renames_solar_parameters_to_canonical_columns(mock_nasa_power_transport):
    block = _fetch(SOLAR_NATIVE)

    assert tuple(block.data.columns) == (
        "ghi",
        "clearsky_ghi",
        "dni",
        "clearsky_dni",
        "dhi",
        "clearsky_dhi",
        "bhi",
        "clearsky_bhi",
        "albedo",
        "longwave_down",
        "longwave_up",
        "airmass",
        "aerosol_optical_depth_550",
        "aerosol_optical_depth_840",
        "precipitable_water",
        "cloud_cover",
    )


def test_diffuse_and_direct_map_to_the_original_pair(mock_nasa_power_transport):
    block = _fetch(("ORIGINAL_ALLSKY_SFC_SW_DIFF", "ORIGINAL_ALLSKY_SFC_SW_DIRH"))

    assert tuple(block.data.columns) == ("dhi", "bhi")
    assert block.data.loc[NOON, "dhi"] == 134.05
    assert block.data.loc[NOON, "bhi"] == 876.20


def test_original_components_sum_to_ghi(mock_nasa_power_transport):
    block = _fetch(SOLAR_NATIVE)
    hour = block.data.loc[NOON]

    assert hour["ghi"] == 1010.25
    assert hour["dhi"] + hour["bhi"] == pytest.approx(1010.25, abs=1e-9)


def test_night_fill_becomes_nan_and_night_zero_irradiance_survives(
    mock_nasa_power_transport,
):
    block = _fetch(SOLAR_NATIVE)
    hour = block.data.loc[NIGHT]

    # genuinely zero at night, not fill
    assert hour["ghi"] == 0.0
    assert hour["dni"] == 0.0
    # undefined at night, served as the header's fill value
    assert pd.isna(hour["albedo"])
    assert pd.isna(hour["airmass"])
    # the same fields are defined by day
    assert block.data.loc[NOON, "albedo"] == 0.16
    assert block.data.loc[NOON, "airmass"] == 1.03


def test_fill_sentinel_comes_from_the_response_header(responses):
    # the sentinel is whatever the header declares, not a hardcoded -999
    scripted, _calls = responses
    payload = _fixture_payload(SOLAR_FIXTURE)
    payload["header"]["fill_value"] = -8888.0
    for name, values in payload["properties"]["parameter"].items():
        for stamp, value in values.items():
            if value == -999.0:
                values[stamp] = -8888.0
    scripted.append(MockResponse(payload))

    block = _fetch(SOLAR_NATIVE)

    assert pd.isna(block.data.loc[NIGHT, "albedo"])
    assert not (block.data == -8888.0).any().any()


def test_surface_pressure_converts_kpa_to_hpa(mock_nasa_power_transport):
    block = _fetch(("PS",))

    assert block.data.loc[NOON, "surface_pressure"] == pytest.approx(963.8, abs=1e-9)


def test_precipitation_rate_converts_to_hourly_depth(mock_nasa_power_transport):
    block = _fetch(("PRECTOTCORR",))

    # 0.89 mm/day over the hour beginning 2024-06-02 12Z
    assert block.data.loc[
        pd.Timestamp("2024-06-02 12:00", tz="UTC"), "precipitation"
    ] == pytest.approx(0.0370833333, abs=1e-9)


def test_snowfall_rate_converts_to_hourly_water_equivalent(responses):
    scripted, calls = responses
    scripted.append(
        MockResponse(_fixture_payload("nasa_power_snow_39.32_-120.14_2024-01.json.gz"))
    )
    source = NASAPowerSource()
    block = source.fetch(
        39.32,
        -120.14,
        date(2024, 1, 1),
        date(2024, 1, 31),
        ("T2M", "PRECTOTCORR", "PRECSNO", "FRSNO"),
    )

    # 32.61 mm/day water-equivalent rate over the hour beginning 2024-01-11 06Z
    hour = pd.Timestamp("2024-01-11 06:00", tz="UTC")
    assert block.data.loc[hour, "snowfall"] == pytest.approx(1.35875, abs=1e-9)
    # snow_cover is a fraction served unscaled
    assert block.data.loc[hour, "snow_cover"] == pytest.approx(0.65)


def test_fetch_reports_the_response_provenance(mock_nasa_power_transport):
    met = _fetch(MET_NATIVE)
    solar = _fetch(SOLAR_NATIVE)

    assert met.sources == ("MERRA2", "POWER")
    assert solar.sources == ("SYN1DEG", "POWER")
    assert met.api_version == "v2.9.6"
    # the met cell's mean elevation, carried on both families' responses
    assert met.elevation == 395.0
    assert solar.elevation == 395.0


def test_a_family_fits_in_one_submission(chunked_transport):
    _fetch(SOLAR_NATIVE)

    assert len(SOLAR_NATIVE) <= MAX_PARAMETERS
    assert chunked_transport == [list(SOLAR_NATIVE)]


def test_fetch_chunks_parameters_beyond_the_api_limit(chunked_transport):
    requested = chunked_transport
    parameters = MET_NATIVE + SOLAR_NATIVE

    block = _fetch(parameters)

    assert len(parameters) == 30
    assert [len(chunk) for chunk in requested] == [20, 10]
    assert requested[0] + requested[1] == list(parameters)
    assert tuple(block.data.columns) == tuple(
        parameter.canonical for parameter in MET_PARAMETERS + SOLAR_PARAMETERS
    )
    assert block.data.loc[NOON, "temperature"] == 30.11
    assert block.data.loc[NOON, "ghi"] == 1010.25
    assert len(block.data) == 720


def test_rate_limit_is_retried(responses, no_sleep):
    scripted, calls = responses
    scripted.append(MockResponse(None, status_code=429))
    scripted.append(MockResponse(_fixture_payload(MET_FIXTURE)))

    block = _fetch(("T2M",))

    assert len(calls) == 2
    assert len(no_sleep) == 1
    assert block.data.loc[NOON, "temperature"] == 30.11


def test_server_error_is_retried_until_the_attempts_run_out(responses, no_sleep):
    scripted, calls = responses
    scripted.append(MockResponse(None, status_code=503))

    with pytest.raises(requests.HTTPError):
        _fetch(("T2M",))

    assert len(calls) == API_REQUEST_TRIES
    assert len(no_sleep) == API_REQUEST_TRIES - 1
    # exponential backoff with jitter: each wait falls in its own window
    assert 2 <= no_sleep[0] < 4
    assert 4 <= no_sleep[1] < 8
    assert 8 <= no_sleep[2] < 16


def test_client_error_is_not_retried(responses, no_sleep):
    scripted, calls = responses
    scripted.append(MockResponse(None, status_code=404))

    with pytest.raises(requests.HTTPError):
        _fetch(("T2M",))

    assert len(calls) == 1
    assert no_sleep == []


def test_retry_after_is_honored(responses, no_sleep):
    scripted, calls = responses
    scripted.append(
        MockResponse(None, status_code=429, headers={"Retry-After": "7"})
    )
    scripted.append(MockResponse(_fixture_payload(MET_FIXTURE)))

    _fetch(("T2M",))

    assert no_sleep == [7.0]


def test_rejected_submission_raises_with_the_api_messages(responses):
    scripted, calls = responses
    scripted.append(MockResponse(_ERROR_BODY, status_code=422))

    with pytest.raises(ValueError) as excinfo:
        _fetch(("T2M",))

    assert "maximum of 20 parameters" in str(excinfo.value)
    assert len(calls) == 1


def test_error_document_served_with_a_success_status_raises(responses):
    scripted, calls = responses
    scripted.append(MockResponse(_ERROR_BODY))

    with pytest.raises(ValueError) as excinfo:
        _fetch(("T2M",))

    assert "maximum of 20 parameters" in str(excinfo.value)


def test_unexpected_response_unit_raises(mock_nasa_power_transport):
    payload = _fixture_payload(MET_FIXTURE)
    payload["parameters"]["PS"]["units"] = "hPa"

    with pytest.raises(ValueError) as excinfo:
        _parse(payload, ("PS",))

    assert "PS" in str(excinfo.value)
    assert "hPa" in str(excinfo.value)


def test_transport_fixture_refuses_unknown_requests(mock_nasa_power_transport):
    source = NASAPowerSource()

    with pytest.raises(AssertionError):
        source.fetch(40.0, -80.0, START, END, ("T2M",))


# cell registration: the client-side arithmetic the api never confirms


def test_met_cell_centres_sit_on_multiples_of_the_grid_step():
    # observed: 34.02 and 34.06 return one series, 34.30 another, and
    # -118.60 another again
    assert cell_for("met", 34.02, -118.29) == (34.0, -118.125)
    assert cell_for("met", 34.06, -118.29) == (34.0, -118.125)
    assert cell_for("met", 34.30, -118.29) == (34.5, -118.125)
    assert cell_for("met", 34.02, -118.60) == (34.0, -118.75)


def test_met_cell_owns_its_low_edge():
    # the observed breaks fall exactly on the half-step boundaries, with
    # the boundary point itself in the higher-index cell
    assert cell_for("met", 33.749, -118.29).latitude == 33.5
    assert cell_for("met", 33.75, -118.29).latitude == 34.0
    assert cell_for("met", 34.02, -118.4376).longitude == -118.75
    assert cell_for("met", 34.02, -118.4375).longitude == -118.125


def test_solar_cell_centres_sit_on_half_degrees():
    assert cell_for("solar", 34.02, -118.29) == (34.5, -118.5)
    # a point three met cells away shares this solar cell
    assert cell_for("solar", 34.99, -118.01) == (34.5, -118.5)


def test_solar_cell_owns_its_low_edge():
    assert cell_for("solar", 33.99, -118.29).latitude == 33.5
    assert cell_for("solar", 34.0, -118.29).latitude == 34.5
    assert cell_for("solar", 34.02, -118.01).longitude == -118.5
    assert cell_for("solar", 34.02, -118.0).longitude == -117.5


def test_cell_for_wraps_the_antimeridian_to_one_cell():
    # longitude 180 is the same meridian as -180, and the met centre that
    # lands on 180 is keyed as -180, so Fiji-adjacent points share one
    # cache key and every centre stays inside the api's accepted range
    assert cell_for("met", -16.5, 180.0) == cell_for("met", -16.5, -180.0)
    assert cell_for("met", -16.5, 179.9).longitude == -180.0
    assert cell_for("met", -16.5, -179.9).longitude == -180.0
    assert cell_for("solar", -16.5, 180.0).longitude == -179.5


def test_cell_for_caps_the_solar_top_row_at_its_last_centre():
    assert cell_for("solar", 90.0, -118.29).latitude == 89.5
    # the met grid has a true pole row
    assert cell_for("met", 90.0, -118.29).latitude == 90.0


def test_cell_for_unknown_family_raises():
    with pytest.raises(ValueError, match="Unknown NASA POWER grid family"):
        cell_for("ocean", 34.02, -118.29)


def test_points_in_one_met_cell_share_one_block(
    grid_transport, monkeypatch_key_value_store
):
    first, _warnings, _provenance = _estimate(variables=("temperature",))
    second, _warnings, _provenance = _estimate(
        point=(34.06, -118.29), variables=("temperature",)
    )

    assert len(grid_transport) == 1
    assert grid_transport[0]["latitude"] == 34.0
    assert grid_transport[0]["longitude"] == -118.125
    assert monkeypatch_key_value_store.keys("nasa-power") == [
        "nasa-power-hourly-met-34.0000_-118.1250-2024"
    ]
    pd.testing.assert_frame_equal(first, second)


def test_a_point_across_the_met_boundary_uses_another_block(
    grid_transport, monkeypatch_key_value_store
):
    _estimate(variables=("temperature",))
    _estimate(point=(34.30, -118.29), variables=("temperature",))

    assert len(grid_transport) == 2
    assert monkeypatch_key_value_store.keys("nasa-power") == [
        "nasa-power-hourly-met-34.0000_-118.1250-2024",
        "nasa-power-hourly-met-34.5000_-118.1250-2024",
    ]


def test_points_in_one_solar_cell_share_one_block(
    grid_transport, monkeypatch_key_value_store
):
    # the two points sit in different met cells and the same solar cell
    _estimate(variables=("ghi",))
    _estimate(point=(34.99, -118.01), variables=("ghi",))

    assert len(grid_transport) == 1
    assert grid_transport[0]["latitude"] == 34.5
    assert grid_transport[0]["longitude"] == -118.5
    assert monkeypatch_key_value_store.keys("nasa-power") == [
        "nasa-power-hourly-solar-34.5000_-118.5000-2024"
    ]


def test_a_point_across_the_solar_boundary_uses_another_block(
    grid_transport, monkeypatch_key_value_store
):
    _estimate(variables=("ghi",))
    _estimate(point=(35.0, -118.29), variables=("ghi",))

    assert len(grid_transport) == 2
    assert monkeypatch_key_value_store.keys("nasa-power") == [
        "nasa-power-hourly-solar-34.5000_-118.5000-2024",
        "nasa-power-hourly-solar-35.5000_-118.5000-2024",
    ]


# loading across both grids


def test_a_mixed_family_request_issues_one_submission_per_grid(
    grid_transport, monkeypatch_key_value_store
):
    df, warnings, _provenance = _estimate(variables=("temperature", "ghi"))

    assert [
        (call["latitude"], call["longitude"], call["parameters"])
        for call in grid_transport
    ] == [
        (34.0, -118.125, "T2M"),
        (34.5, -118.5, "ALLSKY_SFC_SW_DWN"),
    ]
    assert list(df.columns) == ["temperature", "ghi"]
    assert len(df) == 720
    assert df.notna().all().all()
    assert warnings == []


def test_a_failed_submission_leaves_no_block_behind(
    monkeypatch, monkeypatch_key_value_store
):
    # a met load big enough to need two submissions, the second of which
    # the api refuses
    monkeypatch.setattr("eeweather.sources.nasa_power.source.MAX_PARAMETERS", 8)
    calls = []

    def mock_get(url, params=None):
        calls.append(params)
        if len(calls) > 1:
            return MockResponse(_ERROR_BODY, status_code=422)

        return _serve(params["parameters"].split(","), params["start"][:4])

    monkeypatch.setattr("eeweather.sources.nasa_power.source._get", mock_get)

    with pytest.raises(ValueError, match="maximum of 20 parameters"):
        _estimate(variables=MET_CANONICAL)

    assert len(calls) == 2
    assert monkeypatch_key_value_store.keys("nasa-power") == []


def test_a_refresh_refetches_the_union_and_keeps_the_cached_columns(
    grid_transport, monkeypatch_key_value_store
):
    _estimate(variables=("ghi",))
    _estimate(variables=("ghi", "dni"))

    assert [call["parameters"] for call in grid_transport] == [
        "ALLSKY_SFC_SW_DWN",
        "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DNI",
    ]

    key = cache_key("solar", cell_for("solar", *POINT), 2024)
    block, metadata = deserialize_hourly_data(
        monkeypatch_key_value_store.retrieve_json(key)
    )

    assert list(block.columns) == ["ghi", "dni"]
    assert metadata["sources"] == ["SYN1DEG", "POWER"]

    # the refreshed block serves the original variable without refetching
    _estimate(variables=("ghi",))

    assert len(grid_transport) == 2


def test_years_before_the_grid_began_are_not_requested(
    grid_transport, monkeypatch_key_value_store
):
    df, warnings, _provenance = _estimate(
        start=datetime(1999, 6, 1, tzinfo=timezone.utc),
        end=datetime(1999, 6, 30, 23, tzinfo=timezone.utc),
        variables=("temperature",),
    )

    assert grid_transport == []
    assert len(df) == 720
    assert df["temperature"].isna().all()
    assert [w.qualified_name for w in warnings] == [
        "eeweather.no_data_in_requested_range"
    ]


def test_a_pinned_request_with_nothing_at_all_raises(
    grid_transport, monkeypatch_key_value_store
):
    with pytest.raises(DataNotAvailableError) as excinfo:
        _estimate(
            start=datetime(1999, 6, 1, tzinfo=timezone.utc),
            end=datetime(1999, 6, 30, 23, tzinfo=timezone.utc),
            variables=("temperature",),
            raise_when_empty=True,
        )

    assert excinfo.value.source == "nasa-power"


# publication latency


def test_latency_warning_dates_the_met_edge_from_the_values(
    grid_transport, monkeypatch_key_value_store
):
    # the captured response reports end=20260730 and pads the last two
    # days of the range it does return with fill
    _df, warnings, _provenance = _estimate(
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 31, 23, tzinfo=timezone.utc),
        variables=("temperature",),
    )
    latency = [w for w in warnings if w.qualified_name == "eeweather.source_latency"]

    assert len(latency) == 1
    assert latency[0].data == {
        "source": "nasa-power",
        "family": "met",
        "requested_end": "2026-07-31T23:00:00+00:00",
        "published_through": "2026-07-28T23:00:00+00:00",
    }


def test_latency_warning_dates_the_solar_edge_from_the_values(
    grid_transport, monkeypatch_key_value_store
):
    _df, warnings, _provenance = _estimate(
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 31, 23, tzinfo=timezone.utc),
        variables=("ghi",),
    )
    latency = [w for w in warnings if w.qualified_name == "eeweather.source_latency"]

    assert len(latency) == 1
    assert latency[0].data["family"] == "solar"
    assert latency[0].data["published_through"] == "2026-04-30T23:00:00+00:00"


def test_latency_warning_fires_when_the_whole_range_is_past_the_edge(
    grid_transport, monkeypatch_key_value_store
):
    # asking for last month's irradiance is the likeliest way to hit the
    # solar cliff: the requested slice is all fill, and the edge is dated
    # from the rest of the year's block
    _df, warnings, _provenance = _estimate(
        start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 15, 23, tzinfo=timezone.utc),
        variables=("ghi",),
    )
    latency = [w for w in warnings if w.qualified_name == "eeweather.source_latency"]

    assert len(latency) == 1
    assert latency[0].data["family"] == "solar"
    assert latency[0].data["published_through"] == "2026-04-30T23:00:00+00:00"


def test_no_latency_warning_on_a_fully_published_range(
    grid_transport, monkeypatch_key_value_store
):
    _df, warnings, _provenance = _estimate(variables=("temperature", "ghi"))

    assert warnings == []


def test_night_undefined_fields_alone_do_not_date_the_edge(
    grid_transport, monkeypatch_key_value_store
):
    # albedo is fill every night, so its last value dates the last
    # daylight hour rather than the solar grid's publication edge; the
    # load reports the coverage gap without claiming an edge
    _df, warnings, _provenance = _estimate(
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 31, 23, tzinfo=timezone.utc),
        variables=("albedo",),
    )

    assert [w.qualified_name for w in warnings] == ["eeweather.data_truncated"]


# provenance


def test_provenance_payload_carries_each_family_cell(
    grid_transport, monkeypatch_key_value_store
):
    _df, _warnings, provenance = _estimate(variables=("temperature", "ghi"))
    record = provenance["nasa-power"]

    assert record.kind == "observations"
    assert record.station_id is None
    assert record.distance_meters is None
    assert record.variables == ("temperature", "ghi")
    assert record.payload["met"] == {
        "cell_lat": 34.0,
        "cell_lon": -118.125,
        "sources": ["MERRA2", "POWER"],
        "api_versions": ["v2.9.6"],
        "cell_elevation": 395.0,
    }
    assert record.payload["solar"] == {
        "cell_lat": 34.5,
        "cell_lon": -118.5,
        "sources": ["SYN1DEG", "POWER"],
        "api_versions": ["v2.9.6"],
    }


def test_provenance_omits_a_family_that_was_not_loaded(
    grid_transport, monkeypatch_key_value_store
):
    _df, _warnings, provenance = _estimate(variables=("ghi",))

    assert list(provenance["nasa-power"].payload) == ["solar"]


def test_provenance_survives_a_cache_hit(
    grid_transport, monkeypatch_key_value_store
):
    _df, _warnings, first = _estimate(variables=("temperature",))
    _df, _warnings, second = _estimate(variables=("temperature",))

    assert len(grid_transport) == 1
    assert second["nasa-power"].payload == first["nasa-power"].payload
    assert second["nasa-power"].payload["met"]["cell_elevation"] == 395.0


# aggregation


def test_daily_aggregation_sums_precipitation_and_averages_irradiance(
    grid_transport, monkeypatch_key_value_store
):
    df, _warnings, _provenance = _estimate(
        frequency="D", variables=("precipitation", "ghi")
    )

    assert len(df) == 30
    assert df.index[0] == pd.Timestamp("2024-06-01", tz="UTC")
    # 24 hourly depths added; 24 hourly irradiances averaged
    assert df.loc["2024-06-02", "precipitation"] == pytest.approx(0.3675, abs=1e-9)
    assert df.loc["2024-06-02", "ghi"] == pytest.approx(284.38375, abs=1e-9)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("EEWEATHER_LIVE_TESTS") != "1",
    reason="hits the real NASA POWER API; set EEWEATHER_LIVE_TESTS=1 to run",
)
def test_live_fetch_serves_canonical_units():
    source = NASAPowerSource()
    block = source.fetch(
        POINT[0], POINT[1], date(2024, 6, 1), date(2024, 6, 2),
        ("T2M", "ALLSKY_SFC_SW_DWN"),
    )

    # a Los Angeles June day: degC air temperature, W/m2 midday irradiance
    assert 5 < block.data["temperature"].mean() < 45
    assert block.data["ghi"].max() > 400
    assert block.data.index.tz is not None
