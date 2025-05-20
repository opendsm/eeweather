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
""" Note about database tests.

    The database can be rebuilt from scratch using the command:

        $ eeweather rebuild_db

    The database can be inspected using the command (opens sqlite3 CLI):

        $ eeweather inspect_db

    These tests do not cover these main functions - instead, they test the
    content of the database. They can be thought of as integration tests.
"""
from eeweather.connections import metadata_db_connection_proxy


def test_database_tables():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select name from sqlite_master where type='table' """)
    tables = [name for (name,) in cur.fetchall()]
    assert tables == [
        "isd_station_metadata",
        "isd_file_metadata",
        "zcta_metadata",
        "iecc_climate_zone_metadata",
        "iecc_moisture_regime_metadata",
        "ba_climate_zone_metadata",
        "ca_climate_zone_metadata",
        "tmy3_station_metadata",
        "cz2010_station_metadata",
    ]


def test_isd_station_metadata_table_count(snapshot):
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from isd_station_metadata """)
    (count,) = cur.fetchone()
    assert snapshot == count


def test_isd_station_metadata_table_content(snapshot):
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select * from isd_station_metadata where quality='high' limit 1 """)
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert snapshot == data


def test_isd_file_metadata_table_count(snapshot):
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from isd_file_metadata """)
    (count,) = cur.fetchone()
    assert snapshot == count


def test_isd_file_metadata_table_content(snapshot):
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select * from isd_file_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert snapshot == data


def test_zcta_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from zcta_metadata """)
    (count,) = cur.fetchone()
    assert count == 33144


def test_zcta_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select * from zcta_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {
        "ba_climate_zone": "Hot-Humid",
        "ca_climate_zone": None,
        "geometry": None,
        "iecc_climate_zone": "1",
        "iecc_moisture_regime": "A",
        "latitude": "18.1800455429617",
        "longitude": "-66.7521781364081",
        "state": "PR",
        "zcta_id": "00601",
    }


def test_iecc_climate_zone_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from iecc_climate_zone_metadata """)
    (count,) = cur.fetchone()
    assert count == 8


def test_iecc_climate_zone_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select iecc_climate_zone from iecc_climate_zone_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {"iecc_climate_zone": "1"}


def test_iecc_moisture_regime_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from iecc_moisture_regime_metadata """)
    (count,) = cur.fetchone()
    assert count == 3


def test_iecc_moisture_regime_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(
        """ select iecc_moisture_regime from iecc_moisture_regime_metadata limit 1"""
    )
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {"iecc_moisture_regime": "A"}


def test_ba_climate_zone_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from ba_climate_zone_metadata """)
    (count,) = cur.fetchone()
    assert count == 8


def test_ba_climate_zone_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select ba_climate_zone from ba_climate_zone_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {"ba_climate_zone": "Cold"}


def test_ca_climate_zone_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from ca_climate_zone_metadata """)
    (count,) = cur.fetchone()
    assert count == 16


def test_ca_climate_zone_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(
        """ select ca_climate_zone, name from ca_climate_zone_metadata limit 1"""
    )
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {"ca_climate_zone": "CA_01", "name": "Arcata"}


def test_tmy3_station_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from tmy3_station_metadata """)
    (count,) = cur.fetchone()
    assert count == 1020


def test_tmy3_station_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select * from tmy3_station_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {
        "class": "I",
        "name": "Twentynine Palms",
        "state": "CA",
        "usaf_id": "690150",
    }


def test_cz2010_station_metadata_table_count():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select count(*) from cz2010_station_metadata """)
    (count,) = cur.fetchone()
    assert count == 86


def test_cz2010_station_metadata_table_content():
    conn = metadata_db_connection_proxy.get_connection()

    cur = conn.cursor()
    cur.execute(""" select * from cz2010_station_metadata limit 1""")
    row = cur.fetchone()
    data = {desc[0]: value for value, desc in zip(row, cur.description)}
    assert data == {"usaf_id": "690150"}
