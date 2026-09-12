"""A request's network work can be given a deadline.

Without one, every fetch path retries three times at a 120 second socket
timeout, per station-year, and nothing caps the total -- so a large run
against an unresponsive upstream does not fail in a way anyone can see, it
runs for days.
"""
import time
from datetime import datetime

import pytest
import pytz
import requests

from eeweather.exceptions import EEWeatherError, FetchDeadlineExceeded, FetchError
from eeweather.sources import base, budget
from eeweather.sources.engine import load_data


# the budget itself


def test_there_is_no_budget_by_default():
    assert budget.remaining() is None
    assert budget.timeout_for(120) == 120
    budget.check("nothing")  # does not raise


def test_a_budget_reports_what_is_left():
    with budget.fetch_budget(30):
        left = budget.remaining()

    assert 29 < left <= 30


def test_what_is_left_never_exceeds_the_budget():
    """deadline - now is floating point, and on a platform whose monotonic
    clock is coarser than the gap between two reads it can round above the
    budget. remaining() clamps; without that these comparisons are exact
    only by luck of where the clock happens to sit."""
    for seconds in (0.08, 1, 5, 30, 300):
        with budget.fetch_budget(seconds):
            assert budget.remaining() <= seconds
            assert budget.timeout_for(120) <= seconds


def test_a_budget_is_removed_on_the_way_out():
    with budget.fetch_budget(30):
        pass

    assert budget.remaining() is None


def test_a_budget_is_removed_even_when_the_block_raises():
    with pytest.raises(ValueError):
        with budget.fetch_budget(30):
            raise ValueError("boom")

    assert budget.remaining() is None


def test_budgets_nest():
    with budget.fetch_budget(300):
        with budget.fetch_budget(5):
            assert budget.remaining() <= 5
        assert budget.remaining() > 5


def test_a_nonpositive_budget_is_a_caller_error():
    with pytest.raises(ValueError):
        with budget.fetch_budget(0):
            pass


def test_a_socket_timeout_is_capped_at_what_is_left():
    with budget.fetch_budget(5):
        assert budget.timeout_for(120) <= 5


def test_a_socket_timeout_is_untouched_when_the_budget_is_generous():
    with budget.fetch_budget(600):
        assert budget.timeout_for(120) == 120


def test_a_spent_budget_raises_before_opening_a_socket():
    with budget.fetch_budget(0.01):
        time.sleep(0.02)
        with pytest.raises(FetchDeadlineExceeded) as excinfo:
            budget.check("USW00093134 2007")

    assert excinfo.value.seconds == 0.01
    assert excinfo.value.what == "USW00093134 2007"
    assert "USW00093134 2007" in str(excinfo.value)


def test_the_deadline_error_is_catchable_as_an_eeweather_error():
    """So a caller does not have to import requests, or know the submodule."""
    assert issubclass(FetchDeadlineExceeded, EEWeatherError)


def test_backoff_never_sleeps_past_the_deadline():
    with budget.fetch_budget(0.05):
        started = time.monotonic()
        budget.sleep_within(30)
        elapsed = time.monotonic() - started

    assert elapsed < 1


def test_backoff_is_skipped_entirely_when_the_budget_is_gone():
    with budget.fetch_budget(0.01):
        time.sleep(0.02)
        started = time.monotonic()
        budget.sleep_within(30)

    assert time.monotonic() - started < 0.5


# the retry loops honour it


def test_request_text_stops_retrying_when_the_budget_runs_out(monkeypatch):
    """Three retries at a 120s timeout is the shape this bounds."""
    attempts = []

    def never_answers(url, timeout=None):
        attempts.append(timeout)
        time.sleep(0.05)
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(base.requests, "get", never_answers)

    with pytest.raises(FetchDeadlineExceeded):
        with budget.fetch_budget(0.08):
            base.request_text("https://example.invalid/data")

    # it got at least one attempt, and stopped short of all three
    assert 1 <= len(attempts) < base.REQUEST_TRIES
    # and never asked a socket for longer than the budget could afford
    assert all(t <= 0.08 for t in attempts)


def test_request_text_names_the_source_and_station_in_its_error(monkeypatch):
    """A transport failure reads as the real fetch, not the generic
    "request data for station=None"."""
    def boom(url, timeout=None):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(base.requests, "get", boom)

    with pytest.raises(FetchError) as excinfo:
        base.request_text(
            "https://example.invalid/data", source="tmy3", station_id="USW00023152"
        )

    message = str(excinfo.value)
    assert "tmy3" in message
    assert "USW00023152" in message
    assert "station=None" not in message


def test_request_text_is_unbounded_without_a_budget(monkeypatch):
    monkeypatch.setattr(
        base.requests, "get",
        lambda url, timeout=None: _Response("body", timeout))

    assert base.request_text("https://example.invalid/data") == "body"


class _Response:
    def __init__(self, text, timeout):
        self.text = text
        self.timeout = timeout
        self.status_code = 200

    def raise_for_status(self):
        pass


def test_the_full_socket_timeout_is_used_without_a_budget(monkeypatch):
    seen = []

    def record(url, timeout=None):
        seen.append(timeout)
        return _Response("body", timeout)

    monkeypatch.setattr(base.requests, "get", record)
    base.request_text("https://example.invalid/data")

    assert seen == [base.REQUEST_TIMEOUT_SECONDS]


# through the public entry point


def test_load_data_accepts_a_deadline(mock_api_transport):
    df, _ = load_data(
        "USW00093134",
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 1, 2, tzinfo=pytz.UTC),
        deadline=600,
    )

    assert len(df) > 0


def test_load_data_leaves_no_budget_behind(mock_api_transport):
    load_data(
        "USW00093134",
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 1, 2, tzinfo=pytz.UTC),
        deadline=600,
    )

    assert budget.remaining() is None


def test_load_data_is_unbounded_by_default(mock_api_transport):
    df, _ = load_data(
        "USW00093134",
        datetime(2007, 1, 1, tzinfo=pytz.UTC),
        datetime(2007, 1, 2, tzinfo=pytz.UTC),
    )

    assert budget.remaining() is None
    assert len(df) > 0
