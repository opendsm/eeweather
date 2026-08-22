from pathlib import Path

import pytest
import requests

from eeweather.exceptions import DataNotAvailableError, FetchError
from eeweather.sources.cz2010 import CZ2010Source
from eeweather.sources.tmy3 import TMY3Source



FIXTURE_TMY3_TEXT = (
    Path(__file__).parent.parent / "fixtures" / "722880TYA.CSV"
).read_text(encoding="ascii")


def test_tmy3_source_fetch(monkeypatch_tmy3_request):
    ts = TMY3Source().fetch("USW00023152")

    assert ts.sum() == pytest.approx(156194.3, 0.00001)
    assert ts.shape == (8760,)


def test_tmy3_source_fetch_station_not_in_archive():
    with pytest.raises(DataNotAvailableError):
        TMY3Source().fetch("USW00093134")


def test_cz2010_source_fetch_station_not_in_archive():
    with pytest.raises(DataNotAvailableError):
        CZ2010Source().fetch("USW00014819")


def test_normals_source_fetch_unrecognized_station():
    with pytest.raises(DataNotAvailableError):
        TMY3Source().fetch("INVALID")


def test_archive_station():
    archive = TMY3Source().archive_station("USW00023152")

    assert archive == {
        "station_id": "USW00023152",
        "usaf_id": "722880",
        "class": "II",
    }


def test_archive_station_not_available():
    # a German station mapped from isd history has no US normals
    with pytest.raises(DataNotAvailableError) as excinfo:
        TMY3Source().archive_station("GMMU0010254")
    assert excinfo.value.source == "tmy3"
    assert excinfo.value.station_id == "GMMU0010254"


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("{} error".format(self.status_code))
            error.response = self
            raise error


def test_archive_miss_raises_data_not_available(monkeypatch):
    monkeypatch.setattr(
        "eeweather.sources.base.requests.get",
        lambda url, timeout=None: _Response(404),
    )

    with pytest.raises(DataNotAvailableError) as excinfo:
        TMY3Source().fetch("USW00023152")
    assert excinfo.value.source == "tmy3"
    assert excinfo.value.station_id == "USW00023152"


def test_archive_fetch_retries_server_errors(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr("eeweather.sources.budget.time.sleep", sleeps.append)

    def flaky_get(url, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            return _Response(503)

        return _Response(200, text=FIXTURE_TMY3_TEXT)

    monkeypatch.setattr("eeweather.sources.base.requests.get", flaky_get)

    ts = TMY3Source().fetch("USW00023152")

    assert len(calls) == 2
    assert len(sleeps) == 1
    assert ts.shape == (8760,)


def test_archive_fetch_client_error_raises_immediately(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "eeweather.sources.budget.time.sleep", lambda s: None
    )

    def forbidden_get(url, timeout=None):
        calls.append(url)

        return _Response(403)

    monkeypatch.setattr("eeweather.sources.base.requests.get", forbidden_get)

    # a non-404 transport failure surfaces as FetchError; only a 404 means
    # "this station has no archive file", i.e. DataNotAvailableError
    with pytest.raises(FetchError) as excinfo:
        TMY3Source().fetch("USW00023152")

    assert excinfo.value.status_code == 403

    assert len(calls) == 1
