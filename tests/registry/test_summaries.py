import pytest

from eeweather.exceptions import UnrecognizedPlaceError
from eeweather.registry.summaries import get_place, get_station_ids, get_zcta_ids


def test_get_place():
    place = get_place("zcta", "90006")

    assert place["kind"] == "zcta"
    assert place["code"] == "90006"
    assert place["country"] == "US"
    assert place["subdivision"] == "CA"
    assert place["latitude"] == pytest.approx(34.048, abs=0.001)
    assert place["longitude"] == pytest.approx(-118.294, abs=0.001)
    assert place["zones"] == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
    }


def test_get_place_unrecognized():
    with pytest.raises(UnrecognizedPlaceError) as excinfo:
        get_place("zcta", "00000")
    assert excinfo.value.kind == "zcta"
    assert excinfo.value.code == "00000"


def test_get_station_ids():
    station_ids = get_station_ids()

    assert len(station_ids) == 5891
    assert station_ids[0] == "AQA00749401"


def test_get_station_ids_by_subdivision():
    station_ids = get_station_ids("IL")

    assert len(station_ids) == 69
    assert station_ids[0] == "USA00724394"


def test_get_zcta_ids():
    zcta_ids = get_zcta_ids()

    assert len(zcta_ids) == 33144


def test_get_zcta_ids_by_subdivision():
    zcta_ids = get_zcta_ids("CA")

    assert len(zcta_ids) == 1763
    assert zcta_ids[0] == "90001"

