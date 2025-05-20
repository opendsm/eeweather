#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Copyright 2018-2023 OpenEEmeter contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""


class EEWeatherError(Exception):
    """Base class for exceptions in the eeweather package."""

    pass


class UnrecognizedUSAFIDError(EEWeatherError):
    """Raised when an unrecognized USAF station id is encountered.

    Attributes
    ----------
    value : str
        the value which is not a valid USAF ID
    message : str
        a message describing the error
    """

    def __init__(self, value):
        self.value = value
        self.message = (
            'The value "{}" was not recognized as a valid USAF weather station'
            " identifier.".format(value)
        )


class UnrecognizedZCTAError(EEWeatherError):
    """Raised when an unrecognized ZCTA is encountered.

    Attributes
    ----------
    value : str
        the value which is not a valid ZCTA
    message : str
        a message describing the error
    """

    def __init__(self, value):
        self.value = value
        self.message = (
            'The value "{}" was not recognized as a valid ZCTA identifier.'.format(
                value
            )
        )


class ISDDataNotAvailableError(EEWeatherError):
    """Raised when ISD data is not available for a particular station and year.

    Attributes
    ----------
    usaf_id : str
        the USAF ID for which ISD data does not exist.
    year : int
        the year for which ISD data does not exist.
    message : str
        a message describing the error
    """

    def __init__(self, usaf_id, year):
        self.usaf_id = usaf_id
        self.year = year
        self.message = 'ISD data does not exist for station "{}" in year {}.'.format(
            usaf_id, year
        )


class GSODDataNotAvailableError(EEWeatherError):
    """Raised when GSOD data is not available for a particular station and year.

    Attributes
    ----------
        usaf_id -- The USAF ID for which GSOD data does not exist.
        year -- The year for which GSOD data does not exist.
    """

    def __init__(self, usaf_id, year):
        self.usaf_id = usaf_id
        self.year = year
        self.message = 'GSOD data does not exist for station "{}" in year {}.'.format(
            usaf_id, year
        )


class TMY3DataNotAvailableError(EEWeatherError):
    """Raised when TMY3 data is not available for a particular station.

    Attributes
    ----------
    usaf_id : str
        the USAF ID for which TMY3 data does not exist.
    message : str
        a message describing the error
    """

    def __init__(self, usaf_id):
        self.usaf_id = usaf_id
        self.message = 'TMY3 data does not exist for station "{}".'.format(usaf_id)


class CZ2010DataNotAvailableError(EEWeatherError):
    """Raised when CZ2010 data is not available for a particular station.

    Attributes
    ----------
    usaf_id : str
        the USAF ID for which CZ2010 data does not exist.
    message : str
        a message describing the error
    """

    def __init__(self, usaf_id):
        self.usaf_id = usaf_id
        self.message = 'CZ2010 data does not exist for station "{}".'.format(usaf_id)


class NonUTCTimezoneInfoError(EEWeatherError):
    """Raised when input start and end date aren't explicitly defined
    to have a UTC timezone.

    Attributes
    ----------
    usaf_id : str
        the USAF ID for which CZ2010 data does not exist.
    message : str
        a message describing the error
    """

    def __init__(self, this_date):
        self.message = (
            '"{}" does not have a UTC timezone. If using the datetime package, it should be'
            " in the format datetime(1,1,1,tzinfo=pytz.UTC).".format(this_date)
        )
