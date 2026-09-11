"""The `python -m eeweather.build` dispatch.

The geography branch is kept explicit so an empty dispatch input -- what the
scheduled workflow expands ``--geography ${{ inputs.year }}`` to -- rebuilds
the newest vintage instead of silently falling through to a registry refresh.
"""
import sys

import pytest

from eeweather.build import __main__ as build_main


@pytest.fixture
def calls(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        build_main, "build_places",
        lambda year=None: recorded.setdefault("geography", []).append(year) or {},
    )
    monkeypatch.setattr(
        build_main, "migrate",
        lambda old, dest: recorded.setdefault("migrate", []).append((old, dest)) or {},
    )
    monkeypatch.setattr(
        build_main, "refresh",
        lambda: recorded.setdefault("refresh", []).append(True) or {},
    )
    return recorded


def _run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["python -m eeweather.build"] + argv)
    build_main.main()


def test_bare_geography_builds_the_newest_vintage(calls, monkeypatch):
    _run(["--geography"], monkeypatch)

    assert calls == {"geography": [None]}


def test_empty_geography_builds_the_newest_vintage(calls, monkeypatch):
    # the scheduled-run case: empty input must not become a registry refresh
    _run(["--geography", ""], monkeypatch)

    assert calls == {"geography": [None]}


def test_geography_with_a_year_pins_it(calls, monkeypatch):
    _run(["--geography", "2023"], monkeypatch)

    assert calls == {"geography": [2023]}


def test_no_args_refreshes_the_registry(calls, monkeypatch):
    _run([], monkeypatch)

    assert calls == {"refresh": [True]}
