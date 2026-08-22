Changelog
=========

Development
-----------

This release is a redesign; the public API is not compatible with 0.3.x.

* Observed weather data is served from NOAA GHCNh; ISD and GSOD stopped
  receiving data 2025-08-27. Overlap validation against ISD history
  showed a median hourly deviation of 0.0001 degrees C.
* The primary entry point is `WeatherLocation(latitude, longitude)`
  (construct from a ZIP code with `from_place("zcta", code)`): weather at
  a point, estimated by configurable sources. `location.candidates()`
  ranks nearby stations and `location.zones` gives its climate zones.
  Provenance is the reproducibility mechanism: a location pins itself to
  the stations resolved at first load, and `to_dict`/`to_json` with
  `from_dict`/`from_json` carry that state across processes, so later
  loads (e.g. a reporting period after a baseline) use the same station
  per source.
* `WeatherStation` is keyed by the station's GHCN id. Other identifier
  systems are aliases that translate to it: `from_usaf`,
  `from_wban` (most-recent mapping wins), `from_icao`, and the generic
  `from_id(namespace, external_id)`; `WeatherStation.translate(ids,
  from_namespace, to_namespace)` converts in bulk and
  `WeatherStation.search(country=, subdivision=, has_sources=)`
  enumerates the registry as a DataFrame.
* One loading verb: `load_data(start, end, frequency, variables,
  source=)` serves observations and typical years alike, returning
  `(DataFrame, warnings)` with per-source provenance on the frame's
  attrs and on the station/location object. Each requested variable
  routes to the first configured source that serves it; typical-year
  sources (`"tmy3"`, `"cz2010"`) are reachable only by explicit
  `source=` pin and tile onto requested calendar years by
  month-day-hour with NaN leap days. Partial coverage returns NaN plus
  warnings; a pinned source with nothing at all raises
  `DataNotAvailableError`.
* Variables have a canonical curated vocabulary with fixed units
  (temperature, dew point temperature [degC], relative humidity [%],
  wind speed [m/s], station-level pressure [hPa], visibility [km]) and
  a per-variable aggregation governing resampling. `load_data`'s
  `frequency` uses pandas' own offset nomenclature, bound by delegation
  (pandas parses the alias, so its spellings and deprecations apply
  automatically): coarser-than-hourly frequencies (`D`, `W`, `MS`,
  `YS`, ...) aggregate each variable by its declared aggregation —
  point-in-time variables average, accumulation variables
  (`aggregation="sum"`) add up within each period and are never
  gap-interpolated — and finer-than-hourly frequencies (`30min`,
  `20min`, ...; they must divide the hour evenly) interpolate
  point-in-time variables linearly between hourly values and spread
  accumulations evenly, never crossing a missing hour. `eeweather.sources.variables()` lists them
  and which sources serve each. Arbitrary native GHCNh dataTypes are no
  longer passed through.
* Custom data plugs in through public protocols: station-keyed feeds
  (`eeweather.sources.Feed` — keyed by any translatable id system, with
  opt-out caching), typical-year sources (`eeweather.sources.
  NormalsSource`), and location-keyed gridded sources
  (`eeweather.sources.Source`). `eeweather.sources.register(source)`
  makes a custom feed or normals source nameable — usable as a string
  in preference tuples and `source=` pins, and rebuildable by location
  serialization — and accepts vocabulary entries
  (`register(..., vocabulary=(Variable(name, unit, description,
  aggregation),))`)
  for variables the canonical vocabulary lacks, which then route and
  validate like canonical ones. Canonical names are reserved and
  definitions must agree across sources, so a registered variable's
  unit is frozen at first registration.
* Weather at a point can also be estimated from NASA POWER
  (`"nasa-power"`), a location-keyed grid source reached through
  `WeatherLocation` (station-keyed surfaces reject it with a clear
  error). Two independently-latent grids serve it: a meteorological grid
  (temperature, dew point, relative humidity, wind speed, specific
  humidity, skin and soil temperature, eastward/northward wind, surface
  roughness, surface pressure, precipitation, snowfall, snow cover;
  hourly since 2001, roughly two days behind real time) and a solar grid
  (ghi/dni/dhi/bhi and their clearsky counterparts, albedo, longwave up
  and down, airmass, aerosol optical depth at 550 and 840 nm,
  precipitable water, cloud cover; hourly since 2001, roughly three
  months behind real time). A load whose range runs past a grid's
  published edge raises the `eeweather.source_latency` warning.
* New canonical variables: `ghi`/`dni`/`dhi`/`bhi` and
  `clearsky_ghi`/`clearsky_dni`/`clearsky_dhi`/`clearsky_bhi` [W/m2]
  (dhi plus bhi closes to ghi to rounding at high sun and degrades near
  sunrise/sunset, and no component is ever derived from the other two;
  the clearsky fields are a computed clearsky model, jittery and not a
  ceiling on the all-sky value), `albedo` [1] and `airmass` [1] (both
  undefined at night), `longwave_down`/`longwave_up` [W/m2],
  `aerosol_optical_depth_550`/`aerosol_optical_depth_840` [1],
  `precipitable_water` [cm], `cloud_cover` [%], `specific_humidity`
  [g/kg], `skin_temperature` [degC], `soil_temperature` [degC, undefined
  over ocean], `eastward_wind`/`northward_wind` [m/s],
  `surface_roughness` [m], `surface_pressure` [hPa] (pressure at the
  grid cell's model topography, a different physical reference from
  `station_level_pressure`), `precipitation` [mm] (gauge-bias-corrected),
  `snowfall` [mm], and `snow_cover` [1, undefined over ocean].
  `eeweather.sources.wind_direction(eastward_wind, northward_wind)`
  derives meteorological wind direction from already-aggregated wind
  components.
* `WeatherLocation`'s default sources become `("ghcnh", "nasa-power")`;
  a default-constructed location's `variables="all"` load now expands to
  roughly thirty columns and reaches NASA POWER as well as GHCNh.
* Packaged data is split by ownership: the registry holds the
  identifier crosswalk (`identifiers.db`) and regional geography packs
  (`geography_us.db`: zone geometries, ZCTA places, zone assignments);
  each source packages its own facts beside its adapter (the GHCNh
  station catalog with zone assignments, observation inventory, and
  quality ratings; TMY3/CZ2010 archive station lists). 349 ISD
  stations with no GHCNh counterpart were removed during the migration.
* The live packaged data (station catalog, observation inventory,
  quality ratings, identifier aliases) keeps itself current without
  package releases: when it is more than six months old — quality
  rating windows advance when a calendar year completes, so six months
  caps the lag behind that yearly step — loading data starts a
  background update into the platform user data directory, which takes
  precedence over the wheel's copies in new processes
  (`EEWEATHER_AUTO_UPDATE=0` disables; `python -m
  eeweather.registry.update` updates on demand, `--clear` reverts).
  Updates prefer the ready-made pack a scheduled workflow publishes to
  the repository's rolling release — CDN-served, so fleets of any size
  cost NOAA nothing and clients skip the local rebuild — and fall back
  to rebuilding from the live NOAA files when the channel is
  unreachable, implausible, stale, or no newer than the local data.
  Concurrent workers coordinate through an atomic claim file (one
  attempt per machine per day) and the update thread defers network
  traffic for a minute, so short-lived pipeline workers exit without
  fetching anything.
  New stations must sit within 10 km of a known zone geometry and show
  recent observations to be appended; implausibly small upstream files
  abort an update, leaving the previous data in place. A scheduled
  workflow keeps the wheel's snapshot current via the same refresh.
* Station quality ratings come from the GHCNh inventory (every month of
  the rating window above 600 observations is high, above 360 medium);
  `rank_stations(..., rating_period=(start, end))` rates stations over
  the five calendar years ending two years after the period's last date
  (sliding back to the last full year), so historical requests rank
  stations by their reliability in that era.
* Exceptions live in `eeweather.exceptions` (not re-exported at the
  root), carry their messages through `str()`, and cover distinct
  recovery paths: `UnrecognizedStationError`, `UnrecognizedPlaceError`,
  `AmbiguousIdentifierError`, `DataNotAvailableError`,
  `NoQualifiedStationError`. Non-UTC datetimes raise `ValueError`.
* The GHCNh fetch reuses one session, retries only connection and
  server errors with backoff, and raises client errors immediately.
  Loads warn when data is empty, starts late, ends early, or contains a
  multi-day internal gap.
* The shared cache is a stdlib-sqlite store at the platform user cache
  dir by default (`EEWEATHER_CACHE_URL` env var and
  `eeweather.cache.set_path()` override; `eeweather.cache.clear()`
  empties it). ISD-era and 0.3.x cache entries are never served.
* Public type hints ship with a `py.typed` marker.
* Modernized packaging: pyproject.toml with hatchling replaces setup.py,
  Pipfile, and MANIFEST.in; python >=3.10; sqlalchemy, click, and pytz
  are no longer dependencies; platformdirs and shapely are. The CLI,
  plotting helpers, sphinx docs (documentation moves to opendsm.energy),
  and FTP-era fetch code are deleted.
* Tests run fully offline against captured NCEI access api payloads,
  with a python/os matrix workflow, tox environments, ruff lint, and a
  97% coverage floor.
* Timedeltas are constructed with an explicit unit. pandas builds a
  bare numpy timedelta64 from its keyword and string constructor forms,
  which numpy 2.5 deprecates; under ``filterwarnings = ["error"]`` that
  failed every coarser- and finer-than-hourly resample path. pandas 3.0
  fixes it upstream, so this only affects pandas 2.x.
* Transport failures raise ``FetchError`` rather than escaping as raw
  ``requests`` exceptions, distinguishing a network failure from absent
  data (``DataNotAvailableError``).
* A cached block is replaced only after a successful refetch, so a failed
  refresh no longer destroys usable data.
* ``load_data(deadline=)`` bounds the wall-clock time a request may spend
  on the network, raising ``FetchDeadlineExceeded``. Unbounded by default.
  Every fetch path retried three or four times at a 120 second socket
  timeout, per station-year, with nothing capping the total.

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
