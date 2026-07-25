"""Station quality ratings from per-source observation inventory."""
from datetime import datetime, timezone

import pandas as pd

from .db import MONTH_COLUMNS, metadata_db_connection_proxy



QUALITY_WINDOW_YEARS = 5

# every month of the rating window above these observation counts
HIGH_MONTHLY_OBSERVATIONS = 600
MEDIUM_MONTHLY_OBSERVATIONS = 360


def _quality_rating_window(anchor):
    """Calendar years rating a request: five years ending two years after
    the anchor date, sliding back to end no later than the last full
    year."""
    last_full_year = datetime.now(timezone.utc).year - 1
    window_end = min(anchor.year + 2, last_full_year)
    window_start = window_end - (QUALITY_WINDOW_YEARS - 1)

    return window_start, window_end


def _quality_from_minimum(minimum):
    if minimum > HIGH_MONTHLY_OBSERVATIONS:
        return "high"
    elif minimum > MEDIUM_MONTHLY_OBSERVATIONS:
        return "medium"

    return "low"


def _inventory_source_or_raise(source):
    proxy = metadata_db_connection_proxy
    if source is None:
        return proxy.inventory_sources[0]
    if source not in proxy.inventory_sources:
        raise ValueError(
            "Unknown inventory source: '{}'. Sources with inventory:"
            " {}.".format(source, ", ".join(proxy.inventory_sources))
        )

    return source


def get_station_quality(station_id, anchor, source=None):
    """Station quality anchored to a date, from a source's observation
    counts.

    Rates the five calendar years ending two years after the anchor date
    (sliding back so the window ends no later than the last full year):
    every month over 600 observations is high, over 360 is medium;
    anything less, including absent months or years, is low.
    """
    source = _inventory_source_or_raise(source)
    window_start, window_end = _quality_rating_window(anchor)
    conn = metadata_db_connection_proxy.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        select year, {}
        from {}.inventory
        where station_id = ? and year between ? and ?
        """.format(", ".join(MONTH_COLUMNS), source),
        (station_id, window_start, window_end),
    )
    counts_by_year = {row[0]: row[1:] for row in cur.fetchall()}

    minimum = None
    for year in range(window_start, window_end + 1):
        year_counts = counts_by_year.get(year, (0,) * 12)
        year_minimum = min(year_counts)
        if minimum is None or year_minimum < minimum:
            minimum = year_minimum

    return _quality_from_minimum(minimum)


def get_station_qualities(anchor, source=None):
    """Quality anchored to a date for every station, as a
    station_id-indexed Series. Same rating as get_station_quality, computed
    for the whole registry in one query."""
    source = _inventory_source_or_raise(source)
    window_start, window_end = _quality_rating_window(anchor)
    conn = metadata_db_connection_proxy.get_connection()
    inventory = pd.read_sql_query(
        """
        select station_id, year, {}
        from {}.inventory
        where year between ? and ?
        """.format(", ".join(MONTH_COLUMNS), source),
        conn,
        params=(window_start, window_end),
    )

    months = list(MONTH_COLUMNS)
    year_min = inventory[months].min(axis=1)
    observed_min = year_min.groupby(inventory.station_id).min()

    # a station must have a row for every year of the window
    n_years = window_end - window_start + 1
    year_counts = inventory.groupby("station_id").year.nunique()
    observed_min = observed_min.where(year_counts >= n_years, 0)

    qualities = pd.Series("low", index=observed_min.index)
    qualities[observed_min > MEDIUM_MONTHLY_OBSERVATIONS] = "medium"
    qualities[observed_min > HIGH_MONTHLY_OBSERVATIONS] = "high"

    return qualities
