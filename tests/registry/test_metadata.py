import pytest

from eeweather.exceptions import UnrecognizedStationError
from eeweather.registry.metadata import get_station_metadata


def test_get_station_metadata():
    metadata = get_station_metadata("USW00023152")

    assert metadata["station_id"] == "USW00023152"
    assert metadata["name"] == "BURBANK-GLENDALE-PASA ARPT"
    assert metadata["latitude"] == pytest.approx(34.2)
    assert metadata["longitude"] == pytest.approx(-118.365)
    assert metadata["elevation"] == pytest.approx(222.7)
    assert metadata["country"] == "US"
    assert metadata["subdivision"] == "CA"
    assert metadata["quality"] == "high"
    assert metadata["ids"] == {
        "ghcn": ["USW00023152"],
        "icao": ["KBUR"],
        "usaf": ["722880"],
        "wban": ["23152"],
        "wmo": ["72288"],
    }
    assert metadata["zones"] == {
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_09",
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
    }
    assert metadata["inventory_years"]["ghcnh"][0] == 1943
    assert metadata["inventory_years"]["ghcnh"][1] >= 2025


def test_get_station_metadata_unrecognized():
    with pytest.raises(UnrecognizedStationError) as excinfo:
        get_station_metadata("INVALID")
    assert excinfo.value.value == "INVALID"


def test_get_station_metadata_australian_station_has_no_subdivision():
    metadata = get_station_metadata("ASA00749455")

    assert metadata["country"] == "AU"
    assert metadata["subdivision"] is None
