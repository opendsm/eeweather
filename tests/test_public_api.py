"""The package's top-level surface.

The fetch failure type and the budget context manager are part of the
robustness story, so a caller reaches them without knowing the submodule.
"""
import eeweather
from eeweather.exceptions import FetchDeadlineExceeded, FetchError
from eeweather.sources.budget import fetch_budget


def test_fetch_errors_and_budget_are_exported():
    for name in ("FetchError", "FetchDeadlineExceeded", "fetch_budget"):
        assert name in eeweather.__all__
        assert hasattr(eeweather, name)


def test_exports_are_the_real_objects():
    assert eeweather.FetchError is FetchError
    assert eeweather.FetchDeadlineExceeded is FetchDeadlineExceeded
    assert eeweather.fetch_budget is fetch_budget
