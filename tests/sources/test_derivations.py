import numpy as np
import pandas as pd
import pytest

from eeweather.sources.derivations import wind_direction



def test_wind_direction_northerly_wind_blowing_toward_south():
    # wind blowing toward the south (negative northward_wind) comes FROM the north
    assert wind_direction(0, -1) == pytest.approx(0)


def test_wind_direction_southerly_wind_blowing_toward_north():
    # wind blowing toward the north (positive northward_wind) comes FROM the south
    assert wind_direction(0, 1) == pytest.approx(180)


def test_wind_direction_easterly_wind_blowing_toward_west():
    assert wind_direction(-1, 0) == pytest.approx(90)


def test_wind_direction_westerly_wind_blowing_toward_east():
    assert wind_direction(1, 0) == pytest.approx(270)


def test_wind_direction_diagonals():
    assert wind_direction(-1, -1) == pytest.approx(45)
    assert wind_direction(-1, 1) == pytest.approx(135)
    assert wind_direction(1, 1) == pytest.approx(225)
    assert wind_direction(1, -1) == pytest.approx(315)


def test_wind_direction_result_is_in_zero_to_360_range():
    for eastward, northward in [(1, -1), (-1, -1), (-1, 1), (1, 1), (0, -1)]:
        direction = wind_direction(eastward, northward)

        assert 0 <= direction < 360


def test_wind_direction_nan_eastward_gives_nan():
    assert np.isnan(wind_direction(np.nan, 1))


def test_wind_direction_nan_northward_gives_nan():
    assert np.isnan(wind_direction(1, np.nan))


def test_wind_direction_zero_vector_gives_nan():
    assert np.isnan(wind_direction(0, 0))


def test_wind_direction_vectorises_over_series():
    eastward = pd.Series([0.0, -1.0, 1.0, 0.0], index=[1, 2, 3, 4])
    northward = pd.Series([1.0, 0.0, 0.0, 0.0], index=[1, 2, 3, 4])

    result = wind_direction(eastward, northward)

    assert isinstance(result, pd.Series)
    assert list(result.index) == [1, 2, 3, 4]
    expected = pd.Series([180.0, 90.0, 270.0, np.nan], index=[1, 2, 3, 4])
    pd.testing.assert_series_equal(result, expected, check_names=False)
