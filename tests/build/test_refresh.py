"""The refresh's safety behaviors, exercised against temporary databases."""
import sqlite3
from datetime import datetime, timezone

import pytest

from eeweather.build.refresh import (
    _append_new_stations,
    _fetch_inventory,
    _plausible_or_raise,
    _refresh_aliases,
    _replace_inventory,
)
from eeweather.build.schema import GHCNH_SCHEMA, IDENTIFIERS_SCHEMA, create_schema



LAST_FULL_YEAR = datetime.now(timezone.utc).year - 1


def _listed(name, lat, lon, wmo="", icao="", iso=""):
    listing = (name, str(lat), str(lon), "10.0", wmo, icao, iso)

    return listing


def _inventory_row(station_id, year, count=700):
    return (station_id, year) + (count,) * 12


@pytest.fixture
def dbs(tmp_path):
    ghcnh = sqlite3.connect(tmp_path / "ghcnh.db")
    create_schema(ghcnh, GHCNH_SCHEMA)
    identifiers = sqlite3.connect(tmp_path / "identifiers.db")
    create_schema(identifiers, IDENTIFIERS_SCHEMA)
    # one existing cataloged station (Burbank)
    ghcnh.execute(
        "insert into stations values"
        " ('USW00023152', 'BURBANK', 34.2, -118.365, 236.0, 'US', 'CA')"
    )
    identifiers.execute(
        "insert into station_identifier values ('ghcn', 'USW00023152', 'USW00023152', 1)"
    )
    identifiers.execute(
        "insert into station_identifier values ('icao', 'KBUR', 'USW00023152', 1)"
    )

    yield ghcnh, identifiers

    ghcnh.close()
    identifiers.close()


def test_fetch_inventory_parses_current_noaa_format(monkeypatch):
    inventory_text = (
        "GHCNh_ID YEAR JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC\n"
        "AFA00409951 1979 0 45 36 34 28 35 47 15 11 0 0 0\n"
        "USW00023152 2024 700 700 700 700 700 700 700 700 700 700 700 700\n"
    )

    class _Response:
        text = inventory_text

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "eeweather.build.refresh.requests.get", lambda *args, **kwargs: _Response()
    )

    rows = _fetch_inventory()

    assert rows == [
        ("AFA00409951", 1979, 0, 45, 36, 34, 28, 35, 47, 15, 11, 0, 0, 0),
        ("USW00023152", 2024, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700, 700),
    ]


def test_append_admits_active_station_inside_geography_with_zones(dbs):
    ghcnh, identifiers = dbs
    station_list = {"USW00099901": _listed("PASADENA TEST", 34.15, -118.14)}
    inventory = [_inventory_row("USW00099901", LAST_FULL_YEAR)]

    added = _append_new_stations(ghcnh, identifiers, station_list, inventory)

    assert added == 1
    zones = dict(ghcnh.execute(
        "select system, zone_id from station_zone where station_id='USW00099901'"
    ).fetchall())
    assert zones["ca_climate_zone"] == "CA_09"
    assert identifiers.execute(
        "select count(*) from station_identifier"
        " where namespace='ghcn' and station_id='USW00099901'"
    ).fetchone()[0] == 1


def test_append_uses_iso_code_for_country(dbs):
    ghcnh, identifiers = dbs
    # a "CA" id prefix has no FIPS_TO_ISO entry, so country would be null;
    # the station list's ISO_CODE supplies it
    station_list = {"CAN01013998": _listed("KELP REEF", 34.15, -118.14, iso="CA")}
    inventory = [_inventory_row("CAN01013998", LAST_FULL_YEAR)]

    added = _append_new_stations(ghcnh, identifiers, station_list, inventory)

    assert added == 1
    country = ghcnh.execute(
        "select country from stations where station_id = 'CAN01013998'"
    ).fetchone()[0]
    assert country == "CA"


def test_append_rejects_station_outside_served_geography(dbs):
    ghcnh, identifiers = dbs
    # Hamburg: active, but no geography pack covers Germany
    station_list = {"GME00099902": _listed("HAMBURG TEST", 53.55, 9.99)}
    inventory = [_inventory_row("GME00099902", LAST_FULL_YEAR)]

    added = _append_new_stations(ghcnh, identifiers, station_list, inventory)

    assert added == 0


def test_append_rejects_offshore_platform(dbs):
    ghcnh, identifiers = dbs
    # Gulf of Mexico, ~200 km off the Louisiana coast
    station_list = {"USW00099903": _listed("PLATFORM TEST", 27.2, -90.0)}
    inventory = [_inventory_row("USW00099903", LAST_FULL_YEAR)]

    added = _append_new_stations(ghcnh, identifiers, station_list, inventory)

    assert added == 0


def test_append_rejects_inactive_station(dbs):
    ghcnh, identifiers = dbs
    station_list = {"USW00099904": _listed("DEAD TEST", 34.15, -118.14)}
    inventory = [_inventory_row("USW00099904", 2015)]

    added = _append_new_stations(ghcnh, identifiers, station_list, inventory)

    assert added == 0


def test_alias_refresh_never_claims_an_id_with_another_recent_holder(dbs):
    ghcnh, identifiers = dbs
    # a second cataloged station whose list row claims Burbank's icao
    ghcnh.execute(
        "insert into stations values"
        " ('USW00099905', 'IMPOSTER', 34.0, -118.0, 10.0, 'US', 'CA')"
    )
    station_list = {
        "USW00099905": _listed("IMPOSTER", 34.0, -118.0, icao="KBUR"),
    }

    added = _refresh_aliases(ghcnh, identifiers, station_list)

    assert added == 0
    holders = identifiers.execute(
        "select station_id from station_identifier"
        " where namespace='icao' and external_id='KBUR'"
    ).fetchall()
    assert holders == [("USW00023152",)]


def test_alias_refresh_adds_unclaimed_aliases(dbs):
    ghcnh, identifiers = dbs
    station_list = {
        "USW00023152": _listed("BURBANK", 34.2, -118.365, wmo="72288", icao="KBUR"),
    }

    added = _refresh_aliases(ghcnh, identifiers, station_list)

    assert added == 1  # wmo added; icao already present
    assert identifiers.execute(
        "select station_id from station_identifier"
        " where namespace='wmo' and external_id='72288'"
    ).fetchone() == ("USW00023152",)


def test_implausibly_small_station_list_aborts(dbs):
    ghcnh, _ = dbs
    with pytest.raises(RuntimeError, match="Implausible station list"):
        _plausible_or_raise(ghcnh, {}, [_inventory_row("USW00023152", 2024)])


def test_implausibly_small_inventory_aborts(dbs):
    ghcnh, _ = dbs
    placeholders = ", ".join("?" for _ in range(14))
    ghcnh.executemany(
        "insert into inventory values ({})".format(placeholders),
        [_inventory_row("USW00023152", y) for y in (2022, 2023, 2024)],
    )
    station_list = {"USW00023152": _listed("BURBANK", 34.2, -118.365)}

    with pytest.raises(RuntimeError, match="Implausible inventory"):
        _plausible_or_raise(ghcnh, station_list, [])


def test_replace_inventory_keeps_only_cataloged_stations(dbs):
    ghcnh, _ = dbs
    inventory = [
        _inventory_row("USW00023152", 2024),
        _inventory_row("ZZNOTINCAT1", 2024),
    ]

    n = _replace_inventory(ghcnh, inventory)

    assert n == 1
