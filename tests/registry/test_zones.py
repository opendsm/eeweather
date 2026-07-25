from eeweather.registry.zones import zones_at


def test_zones_at():
    zones = zones_at(35.1, -119.2)

    assert zones == {
        "iecc_climate_zone": "3",
        "iecc_moisture_regime": "B",
        "ba_climate_zone": "Hot-Dry",
        "ca_climate_zone": "CA_13",
    }


def test_zones_at_point_outside_all_zones():
    zones = zones_at(0, 0)

    assert zones == {
        "iecc_climate_zone": None,
        "iecc_moisture_regime": None,
        "ba_climate_zone": None,
        "ca_climate_zone": None,
    }

