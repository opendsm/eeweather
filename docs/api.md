# API Reference

The public surface is deliberately small: two classes at the root, plus the
`eeweather.sources`, `eeweather.cache`, and `eeweather.exceptions` namespaces.
Anything not documented here is internal and may change without notice.

---

## `eeweather.WeatherLocation`

Weather at a latitude/longitude. The location is the primary abstraction;
weather is estimated by the configured sources, and each requested variable
routes to the first source in the preference tuple that serves it.

```python
WeatherLocation(latitude, longitude, sources=("ghcnh",), pins=None)
```

- `sources` — ordered source preference: built-in names (`"ghcnh"`), custom
  source objects, or registered names.
- `pins` — station id per source name, bypassing matching. Normally not
  written by hand: pins are captured automatically from provenance at load
  time and round-trip through `to_dict`/`from_dict`.

**`from_place(kind, code, sources=("ghcnh",))`** — construct from a coded
place, e.g. `from_place("zcta", "91104")` for a ZIP code tabulation area.

**`load_data(start, end, frequency="h", variables=None, source=None,
ignore_disqualification=False, **load_kwargs)`** — weather between two
explicit-UTC datetimes (inclusive). Returns `(DataFrame, warnings)`.

- `frequency` — any pandas offset alias (`"30min"`, `"h"`, `"D"`, `"W"`,
  `"MS"`, `"YS"`). Coarser-than-hourly aggregates by each variable's
  vocabulary aggregation; finer-than-hourly (must divide the hour evenly)
  interpolates.
- `variables` — canonical names; defaults to `("temperature",)`; `"all"` is
  every variable the configured sources serve.
- `source` — pin every variable to one source, bypassing routing.
  Typical-year sources (`"tmy3"`, `"cz2010"`) are reachable only this way.
- `ignore_disqualification` — serve the best available station with a warning
  instead of raising when none qualifies (see
  [matching.md](matching.md)).
- `load_kwargs` — cache and network controls: `read_from_cache`,
  `write_to_cache`, `fetch_from_web` (all default `True`).

Routed loads never raise for missing data (NaN plus warnings); a pinned load
with nothing at all for the dates raises `DataNotAvailableError`. Records
provenance on the frame's `attrs["provenance"]` and on `self.provenance`, and
pins the location to the resolved stations.

**`candidates(**filters)`** — ranked candidate stations as a DataFrame.
Filters: `match_zones`, `match_subdivision` (with `site_subdivision`),
`has_sources`, `minimum_quality`, `rating_period`, `max_distance_meters`,
`max_difference_elevation_meters` (with `site_elevation`).

**`zones`** — `{system: zone_id}` for the point, e.g.
`{"iecc_climate_zone": "3", "ba_climate_zone": "Hot-Dry", ...}`.

**`provenance`** — `{source_name: Provenance}` from the most recent load;
`None` before any load. Each `Provenance` records `kind`
(`"observations"`/`"normals"`), `source`, `variables`, `station_id`,
`distance_meters`, and a `payload` dict (empty unless a source adds
source-specific detail; the station fields are `None` for non-station
sources).

**`pins`** — `{source_name: station_id}` the location replays.

**`to_dict()` / `from_dict(data)` / `to_json()` / `from_json(text)`** — the
location's replay state (coordinates, source names, pins). A location rebuilt
from this state loads from the same station per source. Custom source objects
must be registered (`eeweather.sources.register`) to serialize.

---

## `eeweather.WeatherStation`

Weather at a known station, keyed by its registry id. All other identifier
systems are aliases that translate to it.

```python
WeatherStation(station_id, sources=("ghcnh",), load_metadata=True)
```

- `sources` — ordered source preference for routing; every entry must be an
  observation source (built-in name, custom source object, or registered
  name). Duplicate names or a normals source (e.g. `"tmy3"`) raise at
  construction — pin a normals source through `load_data(source=...)` instead.

**Constructors** — `from_id(namespace, external_id)` plus the conveniences
`from_usaf(usaf_id)`, `from_wban(wban_id)`, `from_icao(icao_code)`.
Identifiers are normalized (case, zero-padding); a historically reused
identifier resolves to its most recent holder, and raises
`AmbiguousIdentifierError` only when genuinely unresolvable.

**`search(country=None, subdivision=None, has_sources=())`** *(classmethod)* —
the station registry as a metadata DataFrame indexed by station id.

**`translate(ids, from_namespace, to_namespace)`** *(static)* — bulk
identifier translation; returns `{input_id: (target_ids, ...)}` (mappings can
be one-to-many; unmapped ids are absent).

**Attributes** — `id`, `ids` (`{namespace: [values]}`), `name`, `latitude`,
`longitude`, `elevation`, `country`, `subdivision`, `zones`, `quality`
(default-window rating), `inventory_years`; `json()` returns them as a dict.

**`load_data(start, end, frequency="h", variables=None, source=None,
read_from_cache=True, write_to_cache=True, fetch_from_web=True)`** — same
`frequency`, `variables`, `source`, and cache-control semantics as the
location's, minus resolution: there is no `ignore_disqualification` (the
station is already chosen) and no arbitrary `**load_kwargs` passthrough (a
pinned station has nothing further to configure). Sets `self.provenance`. A
pinned (`source=`) load with nothing at all for the requested dates raises
`DataNotAvailableError`; a routed load (`source` unset) never raises for
missing data, returning NaN plus warnings instead.

**`get_quality(anchor, source=None)`** — the station's data-quality
rating (`"high"`/`"medium"`/`"low"`) anchored to a date; see
[matching.md](matching.md) for the rating window.

---

## `eeweather.sources`

**`Source`** — the estimation protocol: `estimate(latitude, longitude, start,
end, frequency=, variables=, **load_kwargs)` returning
`(DataFrame, warnings, provenance)`. Implemented directly for location-keyed
(gridded) data.

**`Feed`** — the station-keyed data protocol: declare `name`, `id_namespace`,
`variables` (canonical names), optionally `default_variables` and
`cacheable`; implement `fetch_year(external_id, year, variables)`. The engine
supplies caching, id translation, alignment, warnings, and provenance.

**`NormalsSource`** — the typical-year protocol: `fetch(station_id)`
returning one typical year, tiled onto requested calendar years by
month-day-hour (leap days are NaN).

**`StationSource`** — the nearest-suitable-station strategy wrapping a feed:
`StationSource(dataset="ghcnh", rank_kwargs=None, select_kwargs=None)`.
Applies the 150 km distance cap and quality/coverage checks by default;
configure via `rank_kwargs`/`select_kwargs`.

**`Variable(name, unit, description, aggregation)`** — a vocabulary entry;
`aggregation` is one of `"mean"`, `"sum"`, `"min"`, `"max"`.

**`register(source, vocabulary=())`** — register a custom feed, normals
source, or estimation/grid source under its name, making it usable as a
string in preference tuples and `source=` pins and rebuildable by location
serialization. `vocabulary`
declares any variables the vocabulary lacks; canonical names are reserved and
definitions must agree across sources.

**`variables()`** — the vocabulary as a DataFrame: name, unit, description,
aggregation, and the sources serving each entry.

---

## `eeweather.cache`

Observed data caches locally per (source, station, year); current-year
entries refresh as new data arrives.

**`set_path(path)`** — relocate the cache database (the `EEWEATHER_CACHE_URL`
environment variable does the same). **`clear()`** — empty it.

---

## `eeweather.exceptions`

All errors subclass **`EEWeatherError`**:

- **`UnrecognizedStationError`** — an id no identifier system knows.
- **`UnrecognizedPlaceError`** — a place code missing from the geography.
- **`AmbiguousIdentifierError`** — an external id with multiple holders and
  no recent one to prefer.
- **`DataNotAvailableError`** — a pinned source with nothing at all for the
  requested dates (carries `source` and `station_id`).
- **`NoQualifiedStationError`** — no station passed qualification for a
  location (see `ignore_disqualification`).

**`EEWeatherWarning`** — the structured warning returned by loads (not a
Python `warnings` category): `qualified_name` (e.g.
`"eeweather.data_gap"`), human-readable `description`, and a `data` dict.

---

## Registry maintenance

Not an import surface, but part of the public contract:

```
python -m eeweather.registry.update           # refresh registry data on demand
python -m eeweather.registry.update --clear   # revert to packaged data
```

Updates also run automatically in the background when the installed registry
data is more than six months old; set `EEWEATHER_AUTO_UPDATE=0` to disable.
See [methodology.md](methodology.md) for the update channel's design.
