from datetime import datetime, timezone

import pandas as pd
import pytest

from eeweather import WeatherLocation, WeatherStation
from eeweather.exceptions import UnrecognizedStationError
from eeweather.sources import Feed



def test_station_without_metadata():
    station = WeatherStation("USW00023152", load_metadata=False)

    assert station.id == "USW00023152"
    assert station.ids is None
    assert station.name is None
    assert station.latitude is None
    assert station.longitude is None
    assert station.elevation is None
    assert station.coords is None
    assert station.country is None
    assert station.subdivision is None
    assert station.quality is None
    assert station.zones == {}
    assert station.inventory_years == {}

    assert str(station) == "USW00023152"
    assert repr(station) == "WeatherStation('USW00023152')"


def test_station_without_metadata_still_validates_id():
    with pytest.raises(UnrecognizedStationError):
        WeatherStation("FAKE", load_metadata=False)


def test_station_with_metadata():
    station = WeatherStation("USW00023152")

    assert station.id == "USW00023152"
    assert station.ids == {
        "ghcn": ["USW00023152"],
        "icao": ["KBUR"],
        "usaf": ["722880"],
        "wban": ["23152"],
        "wmo": ["72288"],
    }
    assert station.name == "BURBANK-GLENDALE-PASA ARPT"
    assert station.latitude == 34.2
    assert station.longitude == -118.365
    assert station.elevation == 222.7
    assert station.coords == (34.2, -118.365)
    assert station.country == "US"
    assert station.subdivision == "CA"
    assert station.quality == "high"
    assert station.zones == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
    }
    assert station.inventory_years["ghcnh"][0] == 1943


def test_station_unrecognized_id():
    with pytest.raises(UnrecognizedStationError):
        WeatherStation("FAKE")


def test_station_json():
    station = WeatherStation("USW00023152")
    serialized = station.json()

    assert serialized["id"] == "USW00023152"
    assert serialized["ids"]["usaf"] == ["722880"]
    assert serialized["name"] == "BURBANK-GLENDALE-PASA ARPT"
    assert serialized["latitude"] == 34.2
    assert serialized["longitude"] == -118.365
    assert serialized["elevation"] == 222.7
    assert serialized["country"] == "US"
    assert serialized["subdivision"] == "CA"
    assert serialized["quality"] == "high"
    assert serialized["zones"]["ca_climate_zone"] == "CA_09"
    assert serialized["inventory_years"]["ghcnh"][0] == 1943


def test_station_from_id():
    station = WeatherStation.from_id("usaf", "722880")

    assert station.id == "USW00023152"


def test_station_from_usaf():
    station = WeatherStation.from_usaf("722874")

    assert station.id == "USW00093134"


def test_station_from_wban():
    station = WeatherStation.from_wban("23152")

    assert station.id == "USW00023152"


def test_station_from_wban_recent_mapping_wins():
    # wban 03935 was reused; only one station holds it recently
    station = WeatherStation.from_wban("03935")

    assert station.id == "USW00003935"


def test_station_from_icao():
    station = WeatherStation.from_icao("KBUR")

    assert station.id == "USW00023152"


def test_station_from_id_wmo():
    # WMO aliases come from the GHCNh station list
    station = WeatherStation.from_id("wmo", "72494")

    assert station.id == "USW00023234"


def test_station_from_id_unrecognized():
    with pytest.raises(UnrecognizedStationError):
        WeatherStation.from_id("usaf", "000000")


def test_station_with_null_elevation():
    # this station's isd history record carries no elevation
    station = WeatherStation("USI0000KEGI")

    assert station.elevation is None


def test_station_load_data(mock_api_transport, monkeypatch_key_value_store):
    station = WeatherStation("USW00093134")
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 4, 3, tzinfo=timezone.utc)

    df, warnings = station.load_data(start, end)

    assert df.index[0] == start
    assert df.index[-1] == end
    assert list(df.columns) == ["temperature"]


def test_station_load_data_records_provenance(
    mock_api_transport, monkeypatch_key_value_store
):
    station = WeatherStation("USW00093134")
    assert station.provenance is None

    df, warnings = station.load_data(
        datetime(2007, 1, 1, tzinfo=timezone.utc),
        datetime(2007, 4, 3, tzinfo=timezone.utc),
    )

    assert station.provenance == df.attrs["provenance"]
    record = station.provenance["ghcnh"]
    assert record.station_id == "USW00093134"
    assert record.variables == ("temperature",)


def test_station_sources_accepts_single_string():
    station = WeatherStation("USW00093134", sources="ghcnh")

    assert station.sources == ("ghcnh",)


def test_station_duplicate_source_names_raise():
    with pytest.raises(ValueError, match="Duplicate source names"):
        WeatherStation("USW00093134", sources=("ghcnh", "ghcnh"))


def test_station_wrong_kind_source_raises():
    with pytest.raises(ValueError, match="observation sources"):
        WeatherStation("USW00093134", sources=("tmy3",))


class _TwoVariableFeed(Feed):
    """A test double whose default is two variables, so a pinned load with
    variables=None must yield both columns."""

    name = "twovar-feed"
    id_namespace = "ghcn"
    variables = ("temperature", "relative_humidity")
    default_variables = ("temperature", "relative_humidity")
    cacheable = False

    def fetch_year(self, external_id, year, variables):
        index = pd.date_range(
            "{}-01-01".format(year), "{}-12-31 23:00".format(year),
            freq="h", tz="UTC",
        )
        df = pd.DataFrame(index=index)
        for variable in variables:
            df[variable] = 1.0

        return df


def test_station_load_data_default_variables_match_location(
    monkeypatch_key_value_store
):
    # both entry points must send variables=None through the same
    # None -> adapter.default_variables path; a source whose default is
    # NOT ("temperature",) makes the parity observable (a reverted
    # WeatherStation default would drop relative_humidity).
    feed = _TwoVariableFeed()
    station = WeatherStation("USW00023152")
    location = WeatherLocation(34.2, -118.365)
    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime(2007, 4, 3, tzinfo=timezone.utc)

    station_df, _ = station.load_data(start, end, source=feed)
    location_df, _ = location.load_data(start, end, source=feed)

    assert list(station_df.columns) == ["temperature", "relative_humidity"]
    assert list(location_df.columns) == ["temperature", "relative_humidity"]


def test_station_get_quality():
    station = WeatherStation("USW00093134")
    anchor = datetime(2012, 12, 31, tzinfo=timezone.utc)

    assert station.get_quality(anchor) == "high"


def test_station_search():
    df = WeatherStation.search()

    assert len(df) == 5891
    assert df.loc["USW00023152", "name"] == "BURBANK-GLENDALE-PASA ARPT"
    assert df.loc["USW00023152", "quality"] == "high"
    assert bool(df.loc["USW00023152", "is_tmy3"]) is True


def test_station_search_filters():
    df = WeatherStation.search(country="AU")

    assert len(df) == 937
    assert (df.country == "AU").all()

    df = WeatherStation.search(subdivision="CA", has_sources=("cz2010",))

    assert len(df) == 86
    assert df.is_cz2010.all()

    df = WeatherStation.search(has_sources=("ghcnh",))

    assert len(df) == 5891


def test_station_search_unknown_source():
    with pytest.raises(ValueError, match="Unknown source"):
        WeatherStation.search(has_sources=("not_a_source",))


def test_station_translate():
    mapping = WeatherStation.translate(["722880"], "usaf", "ghcn")

    assert mapping == {"722880": ("USW00023152",)}
