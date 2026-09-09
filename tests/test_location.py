import gzip
import io
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from eeweather import WeatherLocation
from eeweather.exceptions import DataNotAvailableError
from eeweather.sources import Feed, Source, StationSource, Variable, register
from eeweather.sources import engine, vocabulary
from eeweather.sources.base import Provenance
from eeweather.sources.engine import (
    known_source_names,
    resolve_source,
    sources_serving,
)
from eeweather.sources.matching import rank_stations as real_rank_stations



# station USW00093134 (DOWNTOWN L.A./USC CAMPUS) is the nearest to these coords
USC_LATITUDE = 34.024
USC_LONGITUDE = -118.291


def test_location_resolves_nearest_station(mock_api_transport):
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    df, warnings = location.load_data(
        start, end, read_from_cache=False, write_to_cache=False
    )

    assert list(df.columns) == ["temperature"]
    assert int(df.temperature.notna().sum()) > 8000
    record = location.provenance["ghcnh"]
    assert record.kind == "observations"
    assert record.station_id == "USW00093134"
    assert record.distance_meters < 1000
    assert record.variables == ("temperature",)
    assert df.attrs["provenance"] == location.provenance


def test_location_default_sources():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)

    assert len(location.sources) == 1
    assert isinstance(location.sources[0], StationSource)
    assert location.sources[0].name == "ghcnh"
    assert location.provenance is None


def test_location_sources_accepts_single_string():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources="ghcnh")

    assert len(location.sources) == 1
    assert location.sources[0].name == "ghcnh"


def test_location_duplicate_source_names_raise():
    with pytest.raises(ValueError, match="Duplicate source names"):
        WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=("ghcnh", "ghcnh"))


def test_location_uses_custom_source():
    class StubSource(Source):
        name = "stub"
        kind = "observations"
        variables = ("temperature",)

        def estimate(self, latitude, longitude, start, end, **load_kwargs):
            frame = pd.DataFrame({"temperature": [1.0, 2.0]})
            provenance = {
                "stub": Provenance(
                    kind="observations",
                    source="stub",
                    station_id="USW00000117",
                    distance_meters=42.0,
                    variables=("temperature",),
                )
            }
            warnings = ["stub_warning"]

            return frame, warnings, provenance

    location = WeatherLocation(0.0, 0.0, sources=(StubSource(),))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 2, 1, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end)

    assert warnings == ["stub_warning"]
    assert location.provenance["stub"].station_id == "USW00000117"
    assert location.provenance["stub"].distance_meters == 42.0


def test_location_zones():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)

    assert location.zones == {
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_08",
    }


def test_location_candidates():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)

    candidates = location.candidates(minimum_quality="high")

    assert candidates.index[0] == "USW00003167"
    assert (candidates.quality == "high").all()
    assert candidates["rank"].iloc[0] == 1


def test_location_pins_bypass_matching(mock_api_transport, monkeypatch):
    rank_calls = []

    def counting_rank_stations(*args, **kwargs):
        rank_calls.append(args)

        return real_rank_stations(*args, **kwargs)

    monkeypatch.setattr(
        "eeweather.sources.station_source.rank_stations", counting_rank_stations
    )

    location = WeatherLocation(
        USC_LATITUDE, USC_LONGITUDE, pins={"ghcnh": "USW00093134"}
    )
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    df, warnings = location.load_data(
        start, end, read_from_cache=False, write_to_cache=False
    )

    assert rank_calls == []
    record = location.provenance["ghcnh"]
    assert record.station_id == "USW00093134"
    assert record.distance_meters < 1000


def test_location_load_data_rejects_sources_kwarg(mock_api_transport):
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    with pytest.raises(TypeError, match="sources"):
        location.load_data(start, end, sources=("ghcnh",))


def test_location_load_data_allows_cache_kwargs(mock_api_transport):
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    df, warnings = location.load_data(
        start,
        end,
        read_from_cache=False,
        write_to_cache=False,
        fetch_from_web=True,
    )

    assert list(df.columns) == ["temperature"]


def test_location_serialization_round_trips_pins(mock_api_transport, monkeypatch):
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)
    location.load_data(start, end, read_from_cache=False, write_to_cache=False)

    # pins are captured from provenance automatically
    assert location.pins == {"ghcnh": "USW00093134"}

    replay = WeatherLocation.from_json(location.to_json())
    rank_calls = []

    def counting_rank_stations(*args, **kwargs):
        rank_calls.append(args)

        return real_rank_stations(*args, **kwargs)

    monkeypatch.setattr(
        "eeweather.sources.station_source.rank_stations", counting_rank_stations
    )
    replay.load_data(start, end, read_from_cache=False, write_to_cache=False)

    assert rank_calls == []
    assert replay.provenance["ghcnh"].station_id == "USW00093134"
    assert replay.to_dict() == location.to_dict()


def test_location_serialization_with_registered_source(monkeypatch):
    class PrivateFeed(Feed):
        name = "private"
        id_namespace = "ghcn"
        variables = ("temperature",)

        def fetch_year(self, external_id, year, variables):
            raise NotImplementedError

    monkeypatch.setattr(engine, "_registered_sources", {})
    register(PrivateFeed())
    location = WeatherLocation(
        USC_LATITUDE, USC_LONGITUDE, sources=("ghcnh", "private")
    )

    replay = WeatherLocation.from_dict(location.to_dict())

    assert [s.name for s in replay.sources] == ["ghcnh", "private"]
    assert replay.sources[1].adapter.name == "private"


def test_location_to_dict_rejects_custom_sources():
    class StubSource(Source):
        name = "stub"
        kind = "observations"
        variables = ("temperature",)

    location = WeatherLocation(0.0, 0.0, sources=(StubSource(),))

    with pytest.raises(ValueError, match="Custom sources"):
        location.to_dict()


def test_source_resolution_is_memoized_per_period(monkeypatch):
    source = StationSource()
    rank_calls = []

    def counting_rank_stations(*args, **kwargs):
        rank_calls.append(args)

        return real_rank_stations(*args, **kwargs)

    monkeypatch.setattr(
        "eeweather.sources.station_source.rank_stations", counting_rank_stations
    )

    same_period = (
        datetime(2007, 1, 1, tzinfo=timezone.utc),
        datetime(2007, 12, 31, tzinfo=timezone.utc),
    )
    source.resolve(USC_LATITUDE, USC_LONGITUDE, period=same_period)
    source.resolve(USC_LATITUDE, USC_LONGITUDE, period=same_period)

    assert len(rank_calls) == 1

    # a different era re-resolves
    source.resolve(
        USC_LATITUDE,
        USC_LONGITUDE,
        period=(
            datetime(2013, 1, 1, tzinfo=timezone.utc),
            datetime(2013, 12, 31, tzinfo=timezone.utc),
        ),
    )

    assert len(rank_calls) == 2

    # reset drops the memo
    source.reset()
    source.resolve(USC_LATITUDE, USC_LONGITUDE, period=same_period)

    assert len(rank_calls) == 3


def test_location_from_place():
    location = WeatherLocation.from_place("zcta", "91104")

    assert location.latitude == pytest.approx(34.168, abs=0.001)
    assert location.longitude == pytest.approx(-118.123, abs=0.001)


def test_location_pinned_normals(
    monkeypatch_tmy3_request, monkeypatch_key_value_store
):
    # Burbank coordinates; the nearest tmy3-bearing station is USW00023152
    location = WeatherLocation(34.2, -118.365)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 4, 3, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end, source="tmy3")

    record = location.provenance["tmy3"]
    assert record.kind == "normals"
    assert record.station_id == "USW00023152"
    assert int(df.temperature.notna().sum()) == len(df)


def test_location_rejects_normals_in_preference_sources():
    # a normals source belongs in a source= pin, not the preference tuple;
    # WeatherStation rejects the same, so the two entry points now agree
    with pytest.raises(ValueError, match="not preference sources"):
        WeatherLocation(34.2, -118.365, sources=("tmy3",))


def test_location_unroutable_variable_raises():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 2, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="Unknown variables"):
        location.load_data(start, end, variables=("not_a_variable",))


def test_location_pinned_variables_all(mock_api_transport, monkeypatch_key_value_store):
    from eeweather.sources.ghcnh import GHCNhSource

    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 6, 1, tzinfo=timezone.utc)
    end = datetime(2007, 6, 2, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end, source="ghcnh", variables="all")

    assert list(df.columns) == list(GHCNhSource.variables)


def test_location_routed_missing_data_warns_instead_of_raising(
    mock_api_transport, monkeypatch_key_value_store
):
    # station USW00093134 has no observations at all in 2050
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2050, 1, 1, tzinfo=timezone.utc)
    end = datetime(2050, 6, 1, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end)

    assert df.temperature.isna().all()
    assert "eeweather.data_not_available" in {w.qualified_name for w in warnings}


def test_location_memoized_resolution_repeats_selection_warnings():
    # a memo hit must return the same warnings the first resolution did;
    # downtown LA sits a few km from the USC station, past the 1 m
    # threshold configured here
    source = StationSource(select_kwargs={"distance_warnings": (1,)})

    first = source.resolve(34.05, -118.25)[2]
    second = source.resolve(34.05, -118.25)[2]

    assert [w.qualified_name for w in first] == [
        "eeweather.exceeds_maximum_distance"
    ]
    assert [w.qualified_name for w in second] == [
        w.qualified_name for w in first
    ]


# distance qualification: no station within 150 km of this mid-Pacific
# point; the nearest US station is over 1000 km away
MID_PACIFIC = (30.0, -140.0)


def test_default_distance_cap_disqualifies_remote_locations():
    from eeweather.exceptions import NoQualifiedStationError
    from eeweather.sources.station_source import DEFAULT_MAX_DISTANCE_METERS

    assert StationSource().rank_kwargs["max_distance_meters"] == (
        DEFAULT_MAX_DISTANCE_METERS
    )

    location = WeatherLocation(*MID_PACIFIC)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(NoQualifiedStationError):
        location.load_data(start, end)


def test_ignore_disqualification_serves_best_available_with_warning():
    source = StationSource()

    station, distance, warnings = source.resolve(
        *MID_PACIFIC, ignore_disqualification=True
    )

    names = [w.qualified_name for w in warnings]
    assert "eeweather.station_disqualified" in names
    disqualified = next(
        w for w in warnings
        if w.qualified_name == "eeweather.station_disqualified"
    )
    assert disqualified.data["failed"] == ["distance"]
    assert disqualified.data["distance_meters"] > 150_000
    assert disqualified.data["station_id"] == station.id


def test_waived_resolution_is_not_reused_by_unwaived_calls():
    from eeweather.exceptions import NoQualifiedStationError

    source = StationSource()
    source.resolve(*MID_PACIFIC, ignore_disqualification=True)

    with pytest.raises(NoQualifiedStationError):
        source.resolve(*MID_PACIFIC)


def test_distance_cap_can_be_disabled_explicitly():
    source = StationSource(rank_kwargs={"max_distance_meters": None})

    station, distance, warnings = source.resolve(*MID_PACIFIC)

    assert station is not None


class StubGridSource(Source):
    name = "stub_grid"
    kind = "gridded"
    variables = ("temperature",)

    def estimate(self, latitude, longitude, start, end, **load_kwargs):
        frame = pd.DataFrame({"temperature": [1.0, 2.0]})
        provenance = {
            "stub_grid": Provenance(
                kind="gridded",
                source="stub_grid",
                station_id=None,
                distance_meters=None,
                variables=("temperature",),
            )
        }
        no_warnings = []

        return frame, no_warnings, provenance


def test_location_resolves_registered_estimation_source_by_name(monkeypatch):
    monkeypatch.setattr(engine, "_registered_sources", {})
    grid_source = register(StubGridSource())

    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=("stub_grid",))

    assert location.sources[0] is grid_source
    assert not isinstance(location.sources[0], StationSource)


def test_capture_pins_skips_sources_without_a_station_id():
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    provenance = {
        "ghcnh": Provenance(
            kind="observations",
            source="ghcnh",
            station_id="USW00093134",
            distance_meters=42.0,
            variables=("temperature",),
        ),
        "stub_grid": Provenance(
            kind="gridded",
            source="stub_grid",
            station_id=None,
            distance_meters=None,
            variables=("temperature",),
        ),
    }

    location._capture_pins(provenance)

    assert location.pins == {"ghcnh": "USW00093134"}


def test_pinned_kwargs_omits_station_for_non_station_source(monkeypatch):
    monkeypatch.setattr(engine, "_registered_sources", {})
    grid_source = register(StubGridSource())
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, pins={"stub_grid": "irrelevant"})

    kwargs = location._pinned_kwargs(grid_source, {"frequency": "h"})

    assert "station" not in kwargs
    assert kwargs == {"frequency": "h"}


# Contract: an in-memory location-keyed ("field") source double drives the
# same routed/pinned/serialization seams a station source does, with no
# catalog and no station in its provenance.

FIXTURE_DIR = Path(__file__).parent / "fixtures"

FIELD_VOCABULARY = (
    Variable("field_temperature", "degC", "Point-estimated air temperature.", "mean"),
)

FIELD_VALUE = 21.5


class FieldDouble(Source):
    """A location-keyed source double: synthetic values for any point
    inside a small hard-coded box, DataNotAvailableError outside it, no
    catalog and no station in its provenance."""

    name = "field-double"
    kind = "observations"
    variables = ("field_temperature",)
    default_variables = ("field_temperature",)

    def _in_domain(self, latitude, longitude):
        return 33.0 <= latitude <= 35.0 and -119.0 <= longitude <= -117.0

    def estimate(
        self, latitude, longitude, start, end,
        frequency="h", variables=None, **load_kwargs,
    ):
        if not self._in_domain(latitude, longitude):
            raise DataNotAvailableError(self.name)
        if variables:
            columns = tuple(variables)
        else:
            columns = self.default_variables
        index = pd.date_range(start, end, freq="h")
        frame = pd.DataFrame({column: FIELD_VALUE for column in columns}, index=index)
        provenance = {
            self.name: Provenance(
                kind="observations",
                source=self.name,
                variables=columns,
                station_id=None,
                distance_meters=None,
                payload={"domain": "socal-box"},
            )
        }
        no_warnings = []

        return frame, no_warnings, provenance


class FieldFixtureFeed(Feed):
    """A hermetic station feed serving a captured GHCN payload as
    temperature, keyed by usaf id; declares itself uncacheable."""

    name = "field-fixture-feed"
    id_namespace = "usaf"
    variables = ("temperature",)
    cacheable = False

    _files = {
        "722874": "global-historical-climatology-network-hourly_USW00093134_2007.csv.gz",
    }

    def fetch_year(self, external_id, year, variables):
        with gzip.open(FIXTURE_DIR / self._files[external_id], "rb") as f:
            payload = f.read().decode()
        raw = pd.read_csv(io.StringIO(payload), dtype=str)
        index = pd.to_datetime(raw["DATE"]).dt.tz_localize("UTC").rename(None)
        df = pd.DataFrame(index=index)
        for variable in variables:
            df[variable] = pd.to_numeric(raw[variable], errors="coerce").values
        df = df.groupby(df.index).mean().sort_index()

        return df


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(engine, "_registered_sources", {})
    monkeypatch.setattr(vocabulary, "_registered_variables", {})


def test_field_double_is_nameable_after_register(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)

    assert resolve_source("field-double") is field
    assert "field-double" in known_source_names()
    assert "field-double" in sources_serving("field_temperature")


def test_field_double_routes_synthetic_data_by_object(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(field,))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end, variables=("field_temperature",))

    assert location.sources[0] is field
    assert not isinstance(location.sources[0], StationSource)
    assert list(df.columns) == ["field_temperature"]
    assert (df.field_temperature == FIELD_VALUE).all()


def test_field_double_routes_synthetic_data_by_name(clean_registry):
    register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=("field-double",))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = location.load_data(start, end, variables=("field_temperature",))

    assert not isinstance(location.sources[0], StationSource)
    assert (df.field_temperature == FIELD_VALUE).all()


def test_field_double_pinned_returns_synthetic_data(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(field,))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = location.load_data(
        start, end, source="field-double", variables=("field_temperature",)
    )

    assert (df.field_temperature == FIELD_VALUE).all()


def test_field_double_raises_outside_its_domain(clean_registry):
    register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(0.0, 0.0, sources=("field-double",))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    with pytest.raises(DataNotAvailableError):
        location.load_data(
            start, end, source="field-double", variables=("field_temperature",)
        )


def test_field_double_provenance_has_no_station_id(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(field,))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    location.load_data(start, end, variables=("field_temperature",))

    record = location.provenance["field-double"]
    assert record.kind == "observations"
    assert record.source == "field-double"
    assert record.station_id is None
    assert record.distance_meters is None
    assert isinstance(record.payload, dict)
    assert record.payload


def test_heterogeneous_routing_joins_station_and_field_double(
    clean_registry, monkeypatch_key_value_store
):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    station = StationSource(dataset=FieldFixtureFeed())
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(station, field))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)

    df, warnings = location.load_data(
        start, end, variables=("temperature", "field_temperature")
    )

    assert list(df.columns) == ["temperature", "field_temperature"]
    # temperature comes from the station source; the custom variable from
    # the double, aligned onto the one shared UTC index (no NaN introduced
    # by the join)
    assert df.index.tz == timezone.utc
    assert df.temperature.notna().any()
    assert (df.field_temperature == FIELD_VALUE).all()
    assert location.provenance["field-fixture-feed"].station_id == "USW00093134"
    assert location.provenance["field-fixture-feed"].variables == ("temperature",)
    assert location.provenance["field-double"].station_id is None
    assert location.provenance["field-double"].variables == ("field_temperature",)


def test_field_double_location_round_trips_by_name(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=("field-double",))

    replay = WeatherLocation.from_dict(location.to_dict())

    assert [s.name for s in replay.sources] == ["field-double"]
    assert replay.sources[0] is field
    assert not isinstance(replay.sources[0], StationSource)
    assert replay.to_dict() == location.to_dict()

    replay_json = WeatherLocation.from_json(location.to_json())

    assert replay_json.sources[0] is field
    assert replay_json.to_dict() == location.to_dict()


def test_to_dict_pins_unloaded_default_matcher_and_replays_without_resolving(
    mock_api_transport, monkeypatch
):
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    # never loaded, yet to_dict captures the pin registry-only (no fetch)
    state = location.to_dict()

    assert state["pins"] == {"ghcnh": "USW00093134"}

    replay = WeatherLocation.from_dict(state)
    rank_calls = []

    def counting_rank_stations(*args, **kwargs):
        rank_calls.append(args)

        return real_rank_stations(*args, **kwargs)

    monkeypatch.setattr(
        "eeweather.sources.station_source.rank_stations", counting_rank_stations
    )
    replay.load_data(start, end, read_from_cache=False, write_to_cache=False)

    assert rank_calls == []
    assert replay.provenance["ghcnh"].station_id == "USW00093134"


def test_to_dict_needs_no_pin_for_field_double(clean_registry):
    field = register(FieldDouble(), vocabulary=FIELD_VOCABULARY)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=("field-double",))

    state = location.to_dict()

    assert state["pins"] == {}

    replay = WeatherLocation.from_dict(state)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 1, 2, tzinfo=timezone.utc)
    df, warnings = replay.load_data(start, end, variables=("field_temperature",))

    assert replay.sources[0] is field
    assert (df.field_temperature == FIELD_VALUE).all()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"select_kwargs": {"coverage_range": (
            datetime(2007, 1, 1, tzinfo=timezone.utc),
            datetime(2007, 12, 31, tzinfo=timezone.utc),
        )}},
        {"rank_kwargs": {"rating_period": datetime(2007, 12, 31, tzinfo=timezone.utc)}},
    ],
    ids=["coverage_range", "rating_period"],
)
def test_to_dict_raises_for_unloaded_coverage_gated_source(kwargs):
    source = StationSource(**kwargs)
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(source,))

    with pytest.raises(ValueError, match="load once before serializing"):
        location.to_dict()


def test_to_dict_round_trips_coverage_gated_source_after_load(
    mock_api_transport, monkeypatch_key_value_store
):
    coverage = (
        datetime(2007, 1, 1, tzinfo=timezone.utc),
        datetime(2007, 12, 31, tzinfo=timezone.utc),
    )
    source = StationSource(select_kwargs={"coverage_range": coverage})
    location = WeatherLocation(USC_LATITUDE, USC_LONGITUDE, sources=(source,))
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 12, 31, tzinfo=timezone.utc)

    location.load_data(start, end)

    assert location.pins == {"ghcnh": "USW00093134"}

    state = location.to_dict()

    assert state["pins"] == {"ghcnh": "USW00093134"}
