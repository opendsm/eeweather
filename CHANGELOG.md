Changelog
=========

Development
-----------

* Switched to https api over FTP for temperature data fetching
* Remove deprecated `typing` dependency
* Switch from snapshottest to syrupy for snapshot testing.
* Update internal database (2025-03-12).

0.3.29
------

* Add pypi publish action
* Update ftp host to reflect change from ftp.ncdc.noaa.gov to ftp.ncdc.noaa.gov.

0.3.28
------

* Copy shared station metadata dataframe when ranking for thread-safety

0.3.27
-------

* Check for UTC tzinfo datetimes in station functions without explicitly using pytz

0.3.26
------

* Update internal database (2024-07-03).
* Update documentation to match required dashes instead of underscores.

0.3.25
------

* Fix caching compatibility for sqlalchemy 2.0
* Update .iteritems() to .items() for pandas>=2.0.0.
* Update shapely containment method from cascaded_union to unary_union.
* Update db recreation code to first delete the old db.
* Update CA climate zone URL.
* Cache tmy-stations.html file.
* Update Pipfile and python/node versions in Dockerfile.
* Install rust based on new juptyerlab requirements.
* Update tests to deal with rounding that must be coming from new pandas.
* Update sphinx docs based on new signatures.
* Remove python 2.7 support.

0.3.24
------

* Change TMY3 source because original source is no longer supported. Using archive of
original source, data unchanged.

0.3.23
------

* Loosen pin on pyproj.

0.3.22
------

* Update internal database (2019-10-04).

0.3.21
------

* Remove thread-unsafe connection caching.

0.3.20
------

* Make cache insert / update more explicit. Prevents potential race condition in
  multi-threaded environment.

0.3.19
------

* Update pinned version of Pyproj to allow for Python 3.7 support
* Update to test / support Python 3.7

0.3.18
------

* Pin pyproj to 1.9.5.1 version.

0.3.17
------

* Blacken.
* Add dev requirements back in.
* Add FTP timeout of 60 seconds.
* Move Pipfile to requirements.txt.
* Update cartopy terrain.
* Add an FTP timeout.

0.3.16
------

* Remove buggy global CSVRequestProxy and replace with alternate mocking
  mechanism.

0.3.15
------

* Fix bugs around cache-only weather data pulling.

0.3.14
------

* Add an option to not fetch from NOAA and only use cache.

0.3.13
------

* Selects station with missing yearly data by default.

0.3.12
------

* Update internal database (2019-01-02).
* Bump requests version (and others).

0.3.11
------

* Bump version due to pypi mixup.

0.3.10
------

* Add `error_on_missing_years` parameter to the model as well.

0.3.9
-----

* Add `error_on_missing_years` parameter to `load_isd_hourly_temp_data`,
  if True, an ISDDataAvailableError exception is raised if there are years,
  within the requested dates that are unavailable. If False, the values in
  the missing years are set to nan.

0.3.8
-----

* Update internal database (2018-08-31).

0.3.7
-----

* Allow using non-normalized dates, (i.e., dates with non-zero minutes or
  seconds that do not fall exactly on an hour or a day boundary) to access
  `station.load_isd_hourly_temp_data`, `station.load_isd_daily_temp_data`,
  and `station.load_gsod_daily_temp_data`.

0.3.6
-----

* Bug fix in ISDStation initialization with handling of null fields.

0.3.5
-----

* Added the `rank` parameter in the data field for a station distance EEWeatherWarning.

0.3.4
-----

* Created an EEWeatherWarning object to capture distance warnings.

0.3.3
-----

* Update internal database (2018-08-03).

0.3.2
-----

* Bug fix in `select_stations`.
