import gzip
import json
import os
import re
import tempfile

from pathlib import Path

import pytest


os.environ["EEWEATHER_AUTO_UPDATE"] = "0"

from eeweather.cache import KeyValueStore
from eeweather.sources.nasa_power.source import API_URL as POWER_API_URL
from eeweather.sources.nasa_power.source import FAMILY_PARAMETERS



FIXTURE_DIR = Path(__file__).parent / "fixtures"

ACCESS_API_URL = "https://www.ncei.noaa.gov/access/services/data/v1"


class MockAccessAPIResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def mock_api_transport(monkeypatch):
    """Serve captured NCEI access api payloads for all api requests.

    Fixture files are real responses recorded from the api, named
    {dataset}_{station}_{year}.csv.gz. A request with no matching fixture
    fails the test; no request reaches the network.
    """

    def mock_get(url, params=None, **kwargs):
        assert url == ACCESS_API_URL, "unexpected url: {}".format(url)
        name = "{}_{}_{}.csv.gz".format(
            params["dataset"], params["stations"], params["startDate"][:4]
        )
        path = FIXTURE_DIR / name
        if not path.exists():
            raise AssertionError(
                "no captured fixture for {}; tests must not hit the network".format(
                    name
                )
            )

        with gzip.open(path, "rb") as f:
            text = f.read().decode()

        return MockAccessAPIResponse(text)

    def mock_session_get(url, params=None, **kwargs):
        return mock_get(url, params=params, **kwargs)

    monkeypatch.setattr("eeweather.sources.ghcnh.source._get", mock_session_get)


class MockPowerAPIResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.headers = {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def _power_family(names):
    for family, parameters in FAMILY_PARAMETERS.items():
        if names[0] in {parameter.native for parameter in parameters}:
            return family

    raise AssertionError("unknown POWER parameter: {}".format(names[0]))


@pytest.fixture
def mock_nasa_power_transport(monkeypatch):
    """Serve captured NASA POWER payloads for all POWER api requests.

    Fixture files are real responses recorded from the api, keyed by the
    parameter family, the requested point, and the requested year. A
    request with no matching fixture fails the test; no request reaches
    the network.
    """

    def mock_get(url, params=None, **kwargs):
        assert url == POWER_API_URL, "unexpected url: {}".format(url)
        family = _power_family(params["parameters"].split(","))
        year = params["start"][:4]
        names = (
            "nasa_power_{}_{}_{}_{}.json.gz".format(
                family, params["latitude"], params["longitude"], year
            ),
            "nasa_power_{}_edge_{}.json.gz".format(family, year),
        )
        for name in names:
            path = FIXTURE_DIR / name
            if path.exists():
                with gzip.open(path, "rb") as f:
                    payload = json.loads(f.read().decode())

                return MockPowerAPIResponse(payload)

        raise AssertionError(
            "no captured fixture for {}; tests must not hit the network".format(
                " or ".join(names)
            )
        )

    monkeypatch.setattr("eeweather.sources.nasa_power.source._get", mock_get)


def _fixture_ascii(name):
    return (FIXTURE_DIR / name).read_text(encoding="ascii")


def mock_request_text_tmy3(url, **kwargs):
    match_url = (
        "https://storage.googleapis.com/openeemeter-public-resources/"
        "tmy3_archive/722880TYA.CSV"
    )
    if re.match(match_url, url):
        return _fixture_ascii("722880TYA.CSV")


def mock_request_text_cz2010(url, **kwargs):
    match_url = "https://storage.googleapis.com/oee-cz2010/csv/722880_CZ2010.CSV"

    if re.match(match_url, url):
        return _fixture_ascii("722880_CZ2010.CSV")


class MockKeyValueStoreProxy:
    def __init__(self):
        # create a new test store in a temporary folder
        self.store = KeyValueStore("sqlite:///{}/cache.db".format(tempfile.mkdtemp()))

    def get_store(self):
        return self.store


@pytest.fixture
def monkeypatch_key_value_store(monkeypatch):
    """A fresh temporary cache store patched into the shared proxy."""
    key_value_store_proxy = MockKeyValueStoreProxy()
    monkeypatch.setattr(
        "eeweather.cache.key_value_store_proxy", key_value_store_proxy
    )

    return key_value_store_proxy.get_store()


@pytest.fixture
def monkeypatch_tmy3_request(monkeypatch):
    monkeypatch.setattr(
        "eeweather.sources.base.request_text", mock_request_text_tmy3
    )


@pytest.fixture
def monkeypatch_cz2010_request(monkeypatch):
    monkeypatch.setattr(
        "eeweather.sources.base.request_text", mock_request_text_cz2010
    )
