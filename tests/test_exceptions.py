import pytest

from eeweather.exceptions import (
    AmbiguousIdentifierError,
    DataNotAvailableError,
    EEWeatherError,
    EEWeatherWarning,
    NoQualifiedStationError,
    UnrecognizedPlaceError,
    UnrecognizedStationError,
)



def test_eeweather_error_message_reaches_str():
    error = EEWeatherError("message")

    assert str(error) == "message"
    assert error.message == "message"


def test_unrecognized_station_error():
    error = UnrecognizedStationError("INVALID")

    assert error.value == "INVALID"
    assert str(error) == (
        'The value "INVALID" was not recognized as a valid weather station'
        " identifier."
    )
    assert isinstance(error, EEWeatherError)


def test_unrecognized_place_error():
    error = UnrecognizedPlaceError("zcta", "00000")

    assert error.kind == "zcta"
    assert error.code == "00000"
    assert str(error) == (
        'The value "00000" was not recognized as a valid place of kind "zcta".'
    )


def test_ambiguous_identifier_error():
    error = AmbiguousIdentifierError("wban", "00102", ["ASN00026044", "USW00000102"])

    assert error.namespace == "wban"
    assert error.external_id == "00102"
    assert error.station_ids == ("ASN00026044", "USW00000102")
    assert str(error) == (
        'The wban id "00102" maps to multiple stations'
        " (ASN00026044, USW00000102) and cannot be resolved."
    )


def test_data_not_available_error():
    error = DataNotAvailableError("ghcnh", station_id="USW00023152", year=1800)

    assert error.source == "ghcnh"
    assert error.station_id == "USW00023152"
    assert error.year == 1800
    assert str(error) == (
        "No ghcnh data available for station=USW00023152 year=1800."
    )


def test_data_not_available_error_station_and_year_are_keyword_only():
    with pytest.raises(TypeError):
        DataNotAvailableError("ghcnh", "USW00023152", 1800)


def test_no_qualified_station_error():
    error = NoQualifiedStationError(34.0, -118.2)

    assert error.latitude == 34.0
    assert error.longitude == -118.2
    assert str(error) == (
        "No qualified station found for location (34.0, -118.2)."
    )


@pytest.fixture
def generic_eeweather_warning():
    warning = EEWeatherWarning(
        qualified_name="qualified_name", description="description", data={}
    )

    return warning


def test_warning_repr(generic_eeweather_warning):
    assert repr(generic_eeweather_warning) == (
        "EEWeatherWarning(qualified_name=qualified_name)"
    )


def test_warning_json(generic_eeweather_warning):
    assert generic_eeweather_warning.json() == {
        "qualified_name": "qualified_name",
        "description": "description",
        "data": {},
    }
