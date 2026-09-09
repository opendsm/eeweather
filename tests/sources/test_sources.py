import gzip
import io
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from eeweather.sources import Feed, Source, StationSource, Variable, register, variables
from eeweather.sources import engine
from eeweather.sources import vocabulary
from eeweather.sources.engine import (
    known_source_names,
    load_data,
    resolve_source,
    sources_serving,
)
from eeweather.sources.ghcnh import GHCNhSource



FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _fixture_text(name):
    with gzip.open(FIXTURE_DIR / name, "rb") as f:
        return f.read().decode()


def test_resolve_source_by_name():
    assert resolve_source("ghcnh").name == "ghcnh"
    assert resolve_source("tmy3").name == "tmy3"
    assert resolve_source("cz2010").name == "cz2010"


def test_resolve_source_passes_objects_through():
    feed = GHCNhSource()

    assert resolve_source(feed) is feed


def test_resolve_source_unknown_name():
    with pytest.raises(ValueError, match="Unknown source"):
        resolve_source("noaa_ftp")


def test_sources_serving():
    assert sources_serving("temperature") == ["cz2010", "ghcnh", "tmy3"]
    assert sources_serving("wind_speed") == ["ghcnh"]
    assert sources_serving("ghi") == []


def test_variables_accessor():
    df = variables()

    assert df.index.name == "variable"
    assert df.loc["temperature", "unit"] == "degC"
    assert df.loc["temperature", "sources"] == ("cz2010", "ghcnh", "tmy3")
    assert df.loc["wind_speed", "sources"] == ("ghcnh",)
    assert set(df.columns) == {"unit", "description", "aggregation", "sources"}
    assert df.loc["temperature", "aggregation"] == "mean"
    assert df.loc["precipitation", "aggregation"] == "sum"


@pytest.mark.parametrize(
    "name,unit,aggregation",
    [
        ("ghi", "W/m2", "mean"),
        ("clearsky_ghi", "W/m2", "mean"),
        ("dni", "W/m2", "mean"),
        ("clearsky_dni", "W/m2", "mean"),
        ("dhi", "W/m2", "mean"),
        ("clearsky_dhi", "W/m2", "mean"),
        ("bhi", "W/m2", "mean"),
        ("clearsky_bhi", "W/m2", "mean"),
        ("longwave_down", "W/m2", "mean"),
        ("longwave_up", "W/m2", "mean"),
        ("albedo", "1", "mean"),
        ("airmass", "1", "mean"),
        ("aerosol_optical_depth_550", "1", "mean"),
        ("aerosol_optical_depth_840", "1", "mean"),
        ("snow_cover", "1", "mean"),
        ("precipitable_water", "cm", "mean"),
        ("cloud_cover", "%", "mean"),
        ("specific_humidity", "g/kg", "mean"),
        ("skin_temperature", "degC", "mean"),
        ("soil_temperature", "degC", "mean"),
        ("eastward_wind", "m/s", "mean"),
        ("northward_wind", "m/s", "mean"),
        ("surface_roughness", "m", "mean"),
        ("surface_pressure", "hPa", "mean"),
        ("precipitation", "mm", "sum"),
        ("snowfall", "mm", "sum"),
    ],
)
def test_power_source_canonical_variables_resolve(name, unit, aggregation):
    entry = vocabulary.all_variables()[name]

    assert entry.unit == unit
    assert entry.aggregation == aggregation


def test_only_accumulations_aggregate_by_sum():
    sum_names = {
        name
        for name, entry in vocabulary.all_variables().items()
        if entry.aggregation == "sum"
    }

    assert sum_names == {"precipitation", "snowfall"}


@pytest.mark.parametrize(
    "name",
    [
        "ghi",
        "clearsky_ghi",
        "dni",
        "clearsky_dni",
        "dhi",
        "clearsky_dhi",
        "bhi",
        "clearsky_bhi",
        "longwave_down",
        "longwave_up",
        "albedo",
        "airmass",
        "aerosol_optical_depth_550",
        "aerosol_optical_depth_840",
        "snow_cover",
        "precipitable_water",
        "cloud_cover",
        "specific_humidity",
        "skin_temperature",
        "soil_temperature",
        "eastward_wind",
        "northward_wind",
        "surface_roughness",
        "surface_pressure",
        "precipitation",
        "snowfall",
    ],
)
def test_register_rejects_new_canonical_names(name, clean_registry):
    entry = Variable(name, "bogus-unit", "A bogus re-registration.", "mean")

    with pytest.raises(ValueError, match="canonical"):
        register(FixtureFeed(), vocabulary=(entry,))


class FixtureFeed(Feed):
    """A user-style feed: keyed by usaf ids, serving captured payloads,
    declaring itself uncacheable."""

    name = "fixture-feed"
    id_namespace = "usaf"
    variables = ("temperature",)
    cacheable = False

    # ghcn fixtures keyed by the usaf ids this feed is asked for
    _files = {
        "722874": "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz",
    }

    def __init__(self):
        self.requested_ids = []

    def fetch_year(self, external_id, year, variables):
        self.requested_ids.append(external_id)
        payload = _fixture_text(self._files[external_id])
        raw = pd.read_csv(io.StringIO(payload), dtype=str)
        index = pd.to_datetime(raw["DATE"]).dt.tz_localize("UTC").rename(None)
        df = pd.DataFrame(index=index)
        for variable in variables:
            df[variable] = pd.to_numeric(raw[variable], errors="coerce").values
        df = df.groupby(df.index).mean().sort_index()

        return df


def test_custom_feed_through_engine(monkeypatch_key_value_store):
    feed = FixtureFeed()
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    df, warnings = load_data("USW00093134", start, end, source=feed)

    # the registry id was translated into the feed's usaf namespace
    assert feed.requested_ids == ["722874"]
    assert int(df.temperature.notna().sum()) == 8732
    assert df.attrs["provenance"]["fixture-feed"].station_id == "USW00093134"
    # cacheable=False feeds leave nothing in the store
    assert monkeypatch_key_value_store.keys("") == []


def test_custom_feed_through_station_source(monkeypatch_key_value_store):
    feed = FixtureFeed()
    source = StationSource(dataset=feed)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    # USC campus coordinates; USW00093134 is the nearest station
    df, warnings, provenance = source.estimate(34.024, -118.291, start, end)

    assert feed.requested_ids == ["722874"]
    assert provenance["fixture-feed"].kind == "observations"
    assert provenance["fixture-feed"].station_id == "USW00093134"
    assert provenance["fixture-feed"].distance_meters < 1000
    assert provenance["fixture-feed"].variables == ("temperature",)


class PartialFeed(Feed):
    """A feed that returns fewer columns than requested, e.g. an upstream
    API that has not backfilled a newer variable."""

    name = "partial-feed"
    id_namespace = "ghcn"
    variables = ("temperature", "relative_humidity")
    default_variables = ("temperature", "relative_humidity")
    cacheable = False

    def fetch_year(self, external_id, year, variables):
        index = pd.date_range(
            "{}-01-01".format(year), "{}-12-31 23:00".format(year),
            freq="h", tz="UTC",
        )
        df = pd.DataFrame({"temperature": 10.0}, index=index)

        return df


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(engine, "_registered_sources", {})
    monkeypatch.setattr(vocabulary, "_registered_variables", {})


def test_register_makes_source_nameable(
    clean_registry, monkeypatch_key_value_store
):
    feed = register(FixtureFeed())
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    df, warnings = load_data("USW00093134", start, end, source="fixture-feed")

    assert resolve_source("fixture-feed") is feed
    assert int(df.temperature.notna().sum()) == 8732


def test_register_rejects_builtin_names(clean_registry):
    class Impostor(Feed):
        name = "ghcnh"
        id_namespace = "ghcn"
        variables = ("temperature",)

        def fetch_year(self, external_id, year, variables):
            raise NotImplementedError

    with pytest.raises(ValueError, match="built-in source name"):
        register(Impostor())


def test_register_rejects_grid_sources(clean_registry):
    class GridSource(object):
        name = "era5"
        kind = "grid"
        variables = ("temperature",)

    with pytest.raises(ValueError, match="fetch_year"):
        register(GridSource())


GRID_VOCABULARY = (
    Variable("gridded_temperature", "degC", "Grid-cell temperature.", "mean"),
)


class GridEstimateSource(Source):
    name = "grid-source"
    kind = "grid"
    variables = ("gridded_temperature",)
    default_variables = ("gridded_temperature",)


def test_register_accepts_estimation_sources(clean_registry):
    source = register(GridEstimateSource(), vocabulary=GRID_VOCABULARY)

    assert source.name == "grid-source"
    assert "grid-source" in known_source_names()
    assert "grid-source" in sources_serving("gridded_temperature")


def test_register_rejects_estimation_source_without_variables(clean_registry):
    class NoVariables(Source):
        name = "no-variables"
        kind = "grid"

    with pytest.raises(ValueError, match="must declare 'variables'"):
        register(NoVariables())


def test_register_rejects_estimation_source_without_kind(clean_registry):
    class NoKind(Source):
        name = "no-kind"
        variables = ("temperature",)

    with pytest.raises(ValueError, match="must declare 'kind'"):
        register(NoKind())


def test_register_rejects_fetch_year_source_without_kind(clean_registry):
    class NoKindFeed(object):
        name = "no-kind-feed"
        id_namespace = "ghcn"
        variables = ("temperature",)

        def fetch_year(self, external_id, year, variables):
            raise NotImplementedError

    with pytest.raises(ValueError, match="must declare 'kind'"):
        register(NoKindFeed())


def test_register_rejects_fetch_year_source_without_id_namespace(clean_registry):
    class NoNamespaceFeed(object):
        name = "no-namespace-feed"
        kind = "observations"
        variables = ("temperature",)

        def fetch_year(self, external_id, year, variables):
            raise NotImplementedError

    with pytest.raises(ValueError, match="must declare 'id_namespace'"):
        register(NoNamespaceFeed())


def test_register_requires_a_name(clean_registry):
    class Nameless(Feed):
        name = None
        id_namespace = "ghcn"
        variables = ("temperature",)

        def fetch_year(self, external_id, year, variables):
            raise NotImplementedError

    with pytest.raises(ValueError, match="non-empty string name"):
        register(Nameless())


def test_registered_source_appears_in_discovery(clean_registry):
    register(FixtureFeed())

    assert "fixture-feed" in sources_serving("temperature")
    assert "fixture-feed" in variables().loc["temperature", "sources"]


def test_missing_feed_column_fills_nan_instead_of_raising(clean_registry):
    register(PartialFeed())
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        source="partial-feed", variables=("temperature", "relative_humidity"),
    )

    assert (df.temperature == 10.0).all()
    assert df.relative_humidity.isna().all()


class SoilFeed(Feed):
    """A feed serving a variable the canonical vocabulary lacks.

    A private variable has no real payloads to capture, so the fetch is
    synthetic by necessity: a constant series over the requested year.
    """

    name = "soil-feed"
    id_namespace = "ghcn"
    variables = ("soil_moisture",)
    default_variables = ("soil_moisture",)
    cacheable = False

    def fetch_year(self, external_id, year, variables):
        index = pd.date_range(
            "{}-01-01".format(year), "{}-12-31 23:00".format(year),
            freq="h", tz="UTC",
        )
        df = pd.DataFrame({v: 10.0 for v in variables}, index=index)

        return df


SOIL_VOCABULARY = (
    Variable("soil_moisture", "degC", "Soil moisture at 10 cm depth.", "mean"),
)


def test_registered_vocabulary_serves_new_variable(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 2, 1, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        source="soil-feed", variables=("soil_moisture",),
    )

    assert list(df.columns) == ["soil_moisture"]
    assert (df.soil_moisture == 10.0).all()
    assert df.attrs["provenance"]["soil-feed"].variables == ("soil_moisture",)


def test_registered_variable_routes_to_its_source(clean_registry):
    # temperature would route to ghcnh; the private variable must route
    # to the private source without touching ghcnh at all
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 2, 1, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        sources=("ghcnh", "soil-feed"), variables=("soil_moisture",),
    )

    assert list(df.attrs["provenance"]) == ["soil-feed"]


def test_registered_variable_appears_in_discovery(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)

    df = variables()

    assert df.loc["soil_moisture", "unit"] == "degC"
    assert df.loc["soil_moisture", "sources"] == ("soil-feed",)


def test_register_vocabulary_rejects_canonical_names(clean_registry):
    entry = Variable("temperature", "K", "Air temperature in kelvin.", "mean")

    with pytest.raises(ValueError, match="canonical"):
        register(SoilFeed(), vocabulary=(entry,))


def test_register_vocabulary_requires_agreement_across_sources(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)

    class OtherSoilFeed(SoilFeed):
        name = "other-soil"

    disagreeing = (
        Variable("soil_moisture", "K", "Soil moisture at 10 cm depth.", "mean"),
    )
    with pytest.raises(ValueError, match="definitions must agree"):
        register(OtherSoilFeed(), vocabulary=disagreeing)

    # an identical definition is fine
    register(OtherSoilFeed(), vocabulary=SOIL_VOCABULARY)

    assert sources_serving("soil_moisture") == ["other-soil", "soil-feed"]


def test_register_rejects_undeclared_variables(clean_registry):
    with pytest.raises(ValueError, match="vocabulary lacks"):
        register(SoilFeed())


class RainFeed(Feed):
    """A feed serving an accumulation variable; synthetic by necessity,
    like SoilFeed: constant 1.0 mm per hour, with hour 5 of Jan 1
    missing."""

    name = "rain-feed"
    id_namespace = "ghcn"
    variables = ("rainfall",)
    default_variables = ("rainfall",)
    cacheable = False

    def fetch_year(self, external_id, year, variables):
        index = pd.date_range(
            "{}-01-01".format(year), "{}-12-31 23:00".format(year),
            freq="h", tz="UTC",
        )
        df = pd.DataFrame({v: 1.0 for v in variables}, index=index)
        df.iloc[5] = float("nan")

        return df


RAIN_VOCABULARY = (
    Variable("rainfall", "mm", "Liquid precipitation depth.", "sum"),
)


def test_sum_variable_rolls_up_daily_by_sum(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 31, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        frequency="D", source="rain-feed", variables=("rainfall",),
    )

    # Jan 1 is missing one hour; every other day sums its 24 hours
    assert df.rainfall.iloc[0] == 23.0
    assert (df.rainfall.iloc[1:] == 24.0).all()


def test_sum_variable_hourly_gaps_are_not_interpolated(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end, source="rain-feed", variables=("rainfall",),
    )

    assert pd.isna(df.rainfall.iloc[5])
    assert df.rainfall.drop(df.index[5]).notna().all()


def test_monthly_frequency_aggregates_by_vocabulary(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    rain, _ = load_data(
        "USW00093134", start, end,
        frequency="MS", source="rain-feed", variables=("rainfall",),
    )
    soil, _ = load_data(
        "USW00093134", start, end,
        frequency="MS", source="soil-feed", variables=("soil_moisture",),
    )

    assert len(rain) == 12
    assert rain.index[1] == datetime(2007, 2, 1, tzinfo=timezone.utc)
    assert rain.rainfall.iloc[1] == 28 * 24.0
    assert (soil.soil_moisture == 10.0).all()


def test_annual_frequency_aggregates_by_vocabulary(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2008, 12, 31, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        frequency="YS", source="rain-feed", variables=("rainfall",),
    )

    # one missing hour in each year's Jan 1
    assert list(df.rainfall) == [365 * 24.0 - 1, 366 * 24.0 - 1]


def test_monthly_frequency_excludes_partial_start_month(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 15, tzinfo=timezone.utc)
    end = datetime(2007, 6, 30, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        frequency="MS", source="soil-feed", variables=("soil_moisture",),
    )

    assert df.index[0] == datetime(2007, 2, 1, tzinfo=timezone.utc)
    assert len(df) == 5


def test_register_vocabulary_rejects_unknown_aggregation(clean_registry):
    entry = Variable("rainfall", "mm", "Liquid precipitation depth.", "median")

    with pytest.raises(ValueError, match="Unknown aggregation"):
        register(RainFeed(), vocabulary=(entry,))


def test_weekly_frequency_sums_accumulations(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 3, 1, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        frequency="W", source="rain-feed", variables=("rainfall",),
    )

    # weeks label at their start; full weeks sum 168 hourly values
    assert (df.index.dayofweek == df.index.dayofweek[0]).all()
    assert (df.rainfall.iloc[1:] == 168.0).all()


def test_subhourly_interpolates_point_in_time_variables(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = load_data(
        "USW00093134", start, end,
        frequency="30min", source="soil-feed", variables=("soil_moisture",),
    )

    assert df.index.freqstr == "30min"
    assert (df.soil_moisture == 10.0).all()


def test_subhourly_never_crosses_a_missing_hour(clean_registry):
    register(RainFeed(), vocabulary=RAIN_VOCABULARY)
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    # RainFeed's hour 5 is missing: both 20-minute slots inside it stay
    # NaN, and each present hour's 1.0 mm spreads evenly
    rain, _ = load_data(
        "USW00093134", start, end,
        frequency="20min", source="rain-feed", variables=("rainfall",),
    )

    hour5 = rain.rainfall.loc["2007-01-01 05:00":"2007-01-01 05:59"]
    assert hour5.isna().all()
    hour6 = rain.rainfall.loc["2007-01-01 06:00":"2007-01-01 06:59"]
    assert (hour6 == 1.0 / 3).all()


def test_subhourly_frequency_must_divide_the_hour(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="divide the hour evenly"):
        load_data(
            "USW00093134", start, end,
            frequency="25min", source="soil-feed",
            variables=("soil_moisture",),
        )


def test_frequency_nomenclature_is_validated_by_pandas(clean_registry):
    register(SoilFeed(), vocabulary=SOIL_VOCABULARY)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="Invalid frequency"):
        load_data(
            "USW00093134", start, end,
            frequency="fortnightly", source="soil-feed",
            variables=("soil_moisture",),
        )
