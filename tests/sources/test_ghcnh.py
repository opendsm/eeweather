import gzip
from pathlib import Path

import pytest

from eeweather.exceptions import FetchError
import requests

from eeweather.sources.ghcnh import GHCNhSource
from eeweather.sources.ghcnh.source import API_REQUEST_TRIES



FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _fixture_text(name):
    with gzip.open(FIXTURE_DIR / name, "rb") as f:
        return f.read().decode()


class MockResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                "{} error".format(self.status_code), response=self
            )


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("eeweather.sources.ghcnh.source.time.sleep", sleeps.append)

    return sleeps


def test_fetch_year_request_params_include_date(monkeypatch):
    seen = {}

    def mock_get(url, params=None):
        seen.update(params)

        return MockResponse("")

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", mock_get)

    GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert seen["dataTypes"] == "DATE,temperature"
    assert seen["stations"] == "USW00093134"
    assert seen["startDate"] == "2007-01-01"
    assert seen["endDate"] == "2007-12-31"


def test_fetch_year_retries_connection_errors_with_backoff(monkeypatch, no_sleep):
    calls = []

    def failing_get(url, params=None):
        calls.append(url)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", failing_get)

    # a transport failure surfaces as FetchError, not a raw requests error
    with pytest.raises(FetchError) as excinfo:
        GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert isinstance(excinfo.value.cause, requests.ConnectionError)
    assert excinfo.value.station_id == "USW00093134"
    assert excinfo.value.year == 2007
    assert excinfo.value.status_code is None
    assert len(calls) == API_REQUEST_TRIES
    # backs off between attempts, not after the final failure
    assert len(no_sleep) == API_REQUEST_TRIES - 1
    assert no_sleep[0] < no_sleep[1]


def test_fetch_year_retries_server_errors(monkeypatch, no_sleep):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )
    calls = []

    def flaky_get(url, params=None):
        calls.append(url)
        if len(calls) == 1:
            return MockResponse("oops", status_code=502)

        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", flaky_get)

    df = GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert len(calls) == 2
    assert len(df) == 10884


def test_fetch_year_client_errors_raise_immediately(monkeypatch, no_sleep):
    calls = []

    def not_found_get(url, params=None):
        calls.append(url)

        return MockResponse("nope", status_code=404)

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", not_found_get)

    with pytest.raises(FetchError) as excinfo:
        GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert excinfo.value.status_code == 404
    assert len(calls) == 1
    assert no_sleep == []


def test_fetch_year_succeeds_after_transient_failure(monkeypatch, no_sleep):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )
    calls = []

    def flaky_get(url, params=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("refused")

        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", flaky_get)

    df = GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert len(calls) == 2
    assert len(df) == 10884
    # first captured 2007 observation is 15.0 C at 00:47
    assert df.temperature.iloc[0] == pytest.approx(15.0, abs=1e-9)


def test_fetch_year_empty_year_returns_empty_frame(monkeypatch):
    def mock_get(url, params=None):
        return MockResponse("")

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", mock_get)

    df = GHCNhSource().fetch_year("USW00093134", 1800, ("temperature",))

    assert len(df) == 0
    assert list(df.columns) == ["temperature"]
    assert str(df.index.tz) == "UTC"


def test_fetch_year_unreported_variable_is_nan_column(monkeypatch):
    payload = _fixture_text(
        "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz"
    )

    def mock_get(url, params=None):
        return MockResponse(payload)

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", mock_get)

    df = GHCNhSource().fetch_year(
        "USW00093134", 2007, ("temperature", "visibility")
    )

    assert list(df.columns) == ["temperature", "visibility"]
    assert df.visibility.isna().all()
    assert df.temperature.notna().sum() > 0


def test_fetch_year_averages_duplicate_timestamps(mock_api_transport):
    df = GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))

    assert df.index.is_unique
    assert df.index.is_monotonic_increasing


def test_malformed_payload_raises_meaningful_error(monkeypatch):
    # NCEI's under-load failure mode: an error body with HTTP 200
    def mock_get(url, params=None):
        return MockResponse("<html>\n<body>service overloaded</body>\n</html>")

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", mock_get)

    with pytest.raises(ValueError, match="Malformed GHCNh response"):
        GHCNhSource().fetch_year("USW00093134", 2007, ("temperature",))
