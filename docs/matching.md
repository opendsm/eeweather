# Station Matching and Quality

How EEweather decides which station represents a location, and how it judges
whether that station's data is good enough. Matching runs automatically inside
`WeatherLocation.load_data`; everything here is also inspectable directly
through `location.candidates()`.

## Ranking

Candidates are ranked by geodesic distance from the site (WGS84). The ranked
frame carries everything a reviewer needs to audit the choice: distance,
coordinates and elevation, climate-zone assignments (IECC zone and moisture
regime, Building America, California Building Climate Zone), subdivision,
quality rating, and per-source availability columns (`is_tmy3`, `is_cz2010`,
`tmy3_class`).

Filters restrict the pool before ranking:

- `match_zones=("iecc_climate_zone", ...)` — candidates must share the site's
  zone in the named systems (a site with no zone matches only stations with
  none).
- `match_subdivision=True` — restrict to the site's state/subdivision.
- `has_sources=("tmy3",)` — candidates must be able to serve the named
  sources. Station-backed sources apply this for their own dataset
  automatically.
- `minimum_quality="high"` — see quality, below.
- `max_distance_meters`, `max_difference_elevation_meters` — hard caps.

## The distance cap

**A station 150 km from a building is not a defensible temperature proxy**, so
station-backed sources apply `max_distance_meters=150_000` by default when
resolving a location. The cap is generous by construction: every US ZCTA has a
GHCNh station within 124 km (half are within 19 km), so no ordinary location is
stranded — the cap exists to catch the extraordinary ones (offshore
coordinates, geocoding errors, sites outside the station network) rather than
to constrain normal matching.

When no station qualifies, the load raises `NoQualifiedStationError` rather
than silently serving a bad proxy. To proceed anyway — mirroring OpenDSM's
disqualification pattern, the flag sits on the operation that would raise —
pass `ignore_disqualification=True` to `load_data`: the best available station
serves, and an `eeweather.station_disqualified` warning records which
qualifications it failed and by how much. `rank_stations` itself applies no
default cap; as the audit surface it shows the full field.

## Quality ratings

Quality is computed from the station's observation inventory — monthly
observation counts per station-year, packaged and refreshed from NOAA's
inventory file. A station rates **high** when every month of the rating window
has more than 600 observations (roughly ~20 per day), **medium** above 360,
and **low** otherwise.

Because networks change, quality is a function of *when*: a station that is
excellent today may have been sparse in 2012. The default `quality` column
rates the last five full calendar years; anchored ratings use the same
counts over a window matched to the request — the five calendar years ending
two years after the anchor date (sliding back so the window never ends
after the last full year). Two entry points expose it:

- `location.candidates(minimum_quality="high", rating_period=anchor)` —
  rank and filter by quality as of an era.
- `station.get_quality(anchor)` — one station's rating anchored to a date.

Ratings are computed at query time from the inventory, so registry updates
extend them to recent periods without ever changing what a historical period
rates.

## Coverage and selection

Ranking answers "which stations are plausible"; selection confirms the winner
can actually serve the request. When a coverage check is configured, the
selected station's data for the requested range is validated against a
minimum-fraction threshold before it is accepted, and selection falls through
to the next candidate when it fails. Custom feeds validate against their own
data, not the default source's.

## Memoization and pinning

Within a process, a source memoizes its resolution per location and period
year-span — repeated loads do not re-rank, and a different era re-resolves
(station suitability is era-dependent). Across periods and processes, the
guarantee is stronger: a location pins itself to the stations recorded in its
first load's provenance, and serialized locations
(`to_json`/`from_json`) replay those pins exactly. An explicit pin is its own
acceptance: pinned resolution skips qualification, exactly as loading through
`WeatherStation` directly does.
