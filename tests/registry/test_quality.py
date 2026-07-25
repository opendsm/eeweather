from datetime import datetime, timezone

from eeweather.registry.quality import (
    _quality_rating_window,
    get_station_quality,
    get_station_qualities,
)



def test_quality_rating_window_anchors_five_years_two_after_anchor():
    anchor = datetime(2012, 12, 31, tzinfo=timezone.utc)

    assert _quality_rating_window(anchor) == (2010, 2014)


def test_quality_rating_window_clamps_to_last_full_year():
    last_full_year = datetime.now(timezone.utc).year - 1
    # an anchor far past the last full year forces the clamp
    anchor = datetime(last_full_year + 5, 1, 1, tzinfo=timezone.utc)

    assert _quality_rating_window(anchor) == (last_full_year - 4, last_full_year)


def test_get_station_quality_high_during_active_era():
    anchor = datetime(2012, 12, 31, tzinfo=timezone.utc)

    assert get_station_quality("USW00093134", anchor) == "high"


def test_get_station_quality_low_after_station_went_quiet():
    anchor = datetime(2024, 12, 31, tzinfo=timezone.utc)

    assert get_station_quality("USW00093134", anchor) == "low"


def test_get_station_quality_low_before_any_data():
    anchor = datetime(1851, 1, 1, tzinfo=timezone.utc)

    assert get_station_quality("USW00093134", anchor) == "low"


def test_get_station_qualities_matches_single_station_rating():
    anchor = datetime(2014, 12, 31, tzinfo=timezone.utc)

    qualities = get_station_qualities(anchor)

    for station_id in ["USW00093134", "USW00023152", "USW00023149"]:
        assert qualities[station_id] == get_station_quality(station_id, anchor)
