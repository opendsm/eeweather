from datetime import datetime

import pandas as pd
import pytest
import pytz

from eeweather.exceptions import DataNotAvailableError
from eeweather.sources.matching import (
    combine_ranked_stations,
    rank_stations,
    select_station,
)



@pytest.fixture
def lat_long_fresno():
    return 36.7378, -119.7871


@pytest.fixture
def lat_long_africa():
    return 0, 0


def test_rank_stations_no_filter(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno
    df = rank_stations(lat, lng)
    assert snapshot == df.shape
    assert list(df.columns) == [
        "rank",
        "distance_meters",
        "latitude",
        "longitude",
        "iecc_climate_zone",
        "iecc_moisture_regime",
        "ba_climate_zone",
        "ca_climate_zone",
        "quality",
        "elevation",
        "subdivision",
        "is_cz2010",
        "tmy3_class",
        "is_tmy3",
        "difference_elevation_meters",
    ]
    assert round(df.distance_meters.iloc[0]) == 2723
    assert round(df.distance_meters.iloc[-10]) == 15046116
    # every station in the registry has coordinates, so every distance is real
    assert pd.notnull(df.distance_meters.iloc[-1])


def test_rank_stations_match_zones_not_null(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno
    for system in (
        "iecc_climate_zone",
        "iecc_moisture_regime",
        "ba_climate_zone",
        "ca_climate_zone",
    ):
        df = rank_stations(lat, lng, match_zones=(system,))
        assert df.shape == snapshot(name="match_zones={}".format(system))


def test_rank_stations_match_zones_null(lat_long_africa, snapshot):
    # the site has no zones, so matching candidates have none either
    lat, lng = lat_long_africa
    df = rank_stations(
        lat, lng, match_zones=("iecc_climate_zone", "iecc_moisture_regime")
    )
    assert df.shape == snapshot(name="match_zones without site zones")
    assert df.iecc_climate_zone.isnull().all()


def test_rank_stations_match_zones_unknown_system(lat_long_fresno):
    lat, lng = lat_long_fresno
    with pytest.raises(ValueError):
        rank_stations(lat, lng, match_zones=("not_a_system",))


def test_rank_stations_match_subdivision(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno
    df = rank_stations(lat, lng, site_subdivision="CA")
    assert df.shape == snapshot(name="site_subdivision only, no filter")

    df = rank_stations(
        lat, lng, site_subdivision="CA", match_subdivision=True
    )
    assert df.shape == snapshot(name="match_subdivision=True")
    assert (df.subdivision == "CA").all()

    df = rank_stations(lat, lng, site_subdivision=None, match_subdivision=True)
    assert df.shape == snapshot(name="match_subdivision without subdivision")
    assert df.subdivision.isnull().all()


def test_rank_stations_has_sources(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno
    df = rank_stations(lat, lng, has_sources=("tmy3",))
    assert df.shape == snapshot(name="has_sources=tmy3")
    assert df.is_tmy3.all()

    df = rank_stations(lat, lng, has_sources=("cz2010",))
    assert df.shape == snapshot(name="has_sources=cz2010")
    assert df.is_cz2010.all()

    # every registry station serves ghcnh, so this filters nothing
    df_ghcnh = rank_stations(lat, lng, has_sources=("ghcnh",))
    df_all = rank_stations(lat, lng)
    assert df_ghcnh.shape == df_all.shape


def test_rank_stations_has_sources_unknown_source(lat_long_fresno):
    lat, lng = lat_long_fresno
    with pytest.raises(ValueError):
        rank_stations(lat, lng, has_sources=("not_a_source",))


def test_rank_stations_minimum_quality(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno
    df = rank_stations(lat, lng, minimum_quality="low")
    assert df.shape == snapshot(name="minimum_quality=low")
    assert df.quality.isin(("low", "medium", "high")).all()

    df = rank_stations(lat, lng, minimum_quality="medium")
    assert df.shape == snapshot(name="minimum_quality=medium")
    assert df.quality.isin(("medium", "high")).all()

    df = rank_stations(lat, lng, minimum_quality="high")
    assert df.shape == snapshot(name="minimum_quality=high")
    assert (df.quality == "high").all()


def test_rank_stations_minimum_quality_unknown_value(lat_long_fresno):
    lat, lng = lat_long_fresno
    with pytest.raises(ValueError):
        rank_stations(lat, lng, minimum_quality="excellent")


def test_rank_stations_max_distance_meters(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno

    df = rank_stations(lat, lng, max_distance_meters=200000)
    assert df.shape == snapshot(name="max_distance_meters=200000")
    assert (df.distance_meters <= 200000).all()

    df = rank_stations(lat, lng, max_distance_meters=50000)
    assert df.shape == snapshot(name="max_distance_meters=50000")
    assert (df.distance_meters <= 50000).all()


def test_rank_stations_max_difference_elevation_meters(lat_long_fresno, snapshot):
    lat, lng = lat_long_fresno

    # no site_elevation, so the filter is inert
    df = rank_stations(lat, lng, max_difference_elevation_meters=200)
    assert df.shape == snapshot(name="max_difference_elevation_meters=200")

    df = rank_stations(lat, lng, site_elevation=0, max_difference_elevation_meters=200)
    assert df.shape == snapshot(
        name="site_elevation=0, max_difference_elevation_meters=200"
    )
    assert (df.difference_elevation_meters <= 200).all()

    df = rank_stations(lat, lng, site_elevation=0, max_difference_elevation_meters=50)
    assert df.shape == snapshot(
        name="site_elevation=0, max_difference_elevation_meters=50"
    )
    assert (df.difference_elevation_meters <= 50).all()

    df = rank_stations(
        lat, lng, site_elevation=1000, max_difference_elevation_meters=50
    )
    assert df.shape == snapshot(
        name="site_elevation=1000, max_difference_elevation_meters=50"
    )
    assert (df.difference_elevation_meters <= 50).all()


@pytest.fixture
def cz_candidates(lat_long_fresno):
    lat, lng = lat_long_fresno
    candidates = rank_stations(
        lat,
        lng,
        match_zones=(
            "iecc_climate_zone",
            "iecc_moisture_regime",
            "ba_climate_zone",
            "ca_climate_zone",
        ),
        minimum_quality="high",
        has_sources=("tmy3", "cz2010"),
    )

    return candidates


@pytest.fixture
def naive_candidates(lat_long_fresno):
    lat, lng = lat_long_fresno
    candidates = rank_stations(
        lat, lng, minimum_quality="high", has_sources=("tmy3", "cz2010")
    ).head()

    return candidates


def test_combine_ranked_stations_empty():
    with pytest.raises(ValueError):
        combine_ranked_stations([])


def test_combine_ranked_stations(cz_candidates, naive_candidates):
    assert list(cz_candidates.index) == [
        "USW00093193",
        "USW00023110",
        "USW00023155",
    ]
    assert list(naive_candidates.index) == [
        "USW00093193",
        "USW00023110",
        "USW00023257",
        "USW00093209",
        "USW00023258",
    ]

    combined_candidates = combine_ranked_stations([cz_candidates, naive_candidates])

    assert combined_candidates.shape == (6, 15)
    assert combined_candidates["rank"].iloc[0] == 1
    assert combined_candidates["rank"].iloc[-1] == 6
    assert list(combined_candidates.index) == [
        "USW00093193",
        "USW00023110",
        "USW00023155",
        "USW00023257",
        "USW00093209",
        "USW00023258",
    ]


def test_select_station_no_coverage_check(cz_candidates):
    station, warnings = select_station(cz_candidates)
    assert station.id == "USW00093193"


def test_select_station_real_coverage_path(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    # exercises the real load_hourly_temp_data -> station.load_data -> tmy3
    # source path (no monkeypatch of load_hourly_temp_data itself), against
    # the recorded 722880TYA.CSV fixture for station USW00023152
    candidates = rank_stations(34.200, -118.350, has_sources=("tmy3",))
    assert candidates.index[0] == "USW00023152"

    start = datetime(2006, 1, 3, tzinfo=pytz.UTC)
    end = datetime(2007, 4, 3, tzinfo=pytz.UTC)

    station, warnings = select_station(
        candidates, coverage_range=(start, end), coverage_source="tmy3"
    )

    assert station.id == "USW00023152"
    assert warnings == []


@pytest.fixture
def monkeypatch_load_hourly_temp_data(monkeypatch):
    def load_hourly_temp_data(station, start, end, fetch_from_web=True, source=None):
        # because result datetimes should fall exactly on hours
        normalized_start = datetime(
            start.year, start.month, start.day, start.hour, tzinfo=pytz.UTC
        )
        normalized_end = datetime(
            end.year, end.month, end.day, end.hour, tzinfo=pytz.UTC
        )
        index = pd.date_range(normalized_start, normalized_end, freq="h", tz="UTC")

        # simulate missing data
        no_warnings = []
        if station.id in ("USW00093193", "USW00093144"):
            temps = pd.Series(1, index=index)[: -24 * 50].reindex(index)
        else:
            temps = pd.Series(1, index=index)[: -24 * 10].reindex(index)

        return temps, no_warnings

    monkeypatch.setattr(
        "eeweather.sources.matching.load_hourly_temp_data", load_hourly_temp_data
    )


def test_select_station_full_data(cz_candidates, monkeypatch_load_hourly_temp_data):
    start = datetime(2017, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2018, 1, 1, tzinfo=pytz.UTC)

    # 1st misses qualification
    station, warnings = select_station(cz_candidates, coverage_range=(start, end))
    assert station.id == "USW00023110"

    # 1st meets qualification
    station, warnings = select_station(
        cz_candidates, coverage_range=(start, end), min_fraction_coverage=0.8
    )
    assert station.id == "USW00093193"

    # none meet qualification
    station, warnings = select_station(
        cz_candidates, coverage_range=(start, end), min_fraction_coverage=0.99
    )
    assert station is None


@pytest.fixture
def monkeypatch_load_hourly_temp_data_with_error(monkeypatch):
    def load_hourly_temp_data(station, start, end, fetch_from_web=True, source=None):
        index = pd.date_range(start, end, freq="h", tz="UTC")
        if station.id == "USW00093193":
            # first choice not available
            raise DataNotAvailableError(
                "ghcnh", station_id="USW00093193", year=start.year
            )
        elif station.id == "USW00023110":
            temps = pd.Series(1, index=index)[: -24 * 10].reindex(index)
            no_warnings = []

            return temps, no_warnings
        else:  # pragma: no cover - only for helping to debug failing tests
            raise ValueError(
                "The requested station is not specified in the monkeypatched"
                " data: {}.".format(station)
            )

    monkeypatch.setattr(
        "eeweather.sources.matching.load_hourly_temp_data", load_hourly_temp_data
    )


def test_select_station_with_data_not_available_error(
    cz_candidates, monkeypatch_load_hourly_temp_data_with_error
):
    start = datetime(2017, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2018, 1, 1, tzinfo=pytz.UTC)

    # 1st misses qualification because data not available
    station, warnings = select_station(
        cz_candidates, coverage_range=(start, end), min_fraction_coverage=0.8
    )
    assert station.id == "USW00023110"


@pytest.fixture
def monkeypatch_load_hourly_temp_data_with_empty(monkeypatch):
    def load_hourly_temp_data(station, start, end, fetch_from_web=True, source=None):
        index = pd.date_range(start, end, freq="h", tz="UTC")
        no_warnings = []
        if station.id == "USW00093193":
            temps = pd.Series(1, index=index)[:0]

            return temps, no_warnings
        elif station.id == "USW00023110":
            temps = pd.Series(1, index=index)[: -24 * 10].reindex(index)

            return temps, no_warnings
        else:  # pragma: no cover - only for helping to debug failing tests
            raise ValueError(
                "The requested station is not specified in the monkeypatched"
                " data: {}.".format(station)
            )

    monkeypatch.setattr(
        "eeweather.sources.matching.load_hourly_temp_data", load_hourly_temp_data
    )


def test_select_station_with_empty_tempC(
    cz_candidates, monkeypatch_load_hourly_temp_data_with_empty, snapshot
):
    start = datetime(2017, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2018, 1, 1, tzinfo=pytz.UTC)

    # 1st misses qualification because data not available
    station, warnings = select_station(
        cz_candidates, coverage_range=(start, end), min_fraction_coverage=0.8
    )
    assert station.id == snapshot


def test_select_station_distance_warnings_check(lat_long_africa):
    lat, lng = lat_long_africa
    df = rank_stations(lat, lng)
    station, warnings = select_station(df)
    assert len(warnings) == 2
    assert warnings[0].qualified_name == "eeweather.exceeds_maximum_distance"
    assert warnings[1].qualified_name == "eeweather.exceeds_maximum_distance"
    assert warnings[0].data["max_distance_meters"] == 50000
    assert warnings[1].data["max_distance_meters"] == 200000


def test_select_station_no_station_warnings_check():
    df = pd.DataFrame()
    station, warnings = select_station(df)
    assert warnings[0].qualified_name == "eeweather.no_weather_station_selected"
    assert warnings[0].data == {"rank": 1, "min_fraction_coverage": 0.9}


def test_select_station_with_second_level_dates(
    cz_candidates, monkeypatch_load_hourly_temp_data, snapshot
):
    # dates don't fall exactly on the hour
    start = datetime(2017, 1, 1, 2, 3, 4, tzinfo=pytz.UTC)
    end = datetime(2018, 1, 1, 12, 13, 14, tzinfo=pytz.UTC)

    station, warnings = select_station(cz_candidates, coverage_range=(start, end))
    assert station.id == snapshot


def test_rank_stations_rating_period_uses_era_quality(lat_long_fresno):
    lat, lng = lat_long_fresno
    anchor = datetime(2014, 12, 31, tzinfo=pytz.UTC)

    df = rank_stations(
        lat, lng, minimum_quality="high", has_sources=("tmy3", "cz2010"),
        rating_period=anchor,
    )

    # 723895 and 723896 rate high in their active era despite being
    # medium or low today
    assert list(df.head().index) == [
        "USW00093193",
        "USW00023110",
        "USW00093144",
        "USW00023257",
        "USW00023149",
    ]
