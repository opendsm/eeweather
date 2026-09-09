# Adding a weather-data source

A *source* is a provider of weather data. This guide covers the three
kinds the engine understands, the package anatomy a built-in source
follows, and the contracts every source must honor. `sources/ghcnh/`,
`sources/tmy3/`, and `sources/cz2010/` are the reference
implementations.

## Pick the kind

| kind | contract (in `sources/base.py`) | when |
|---|---|---|
| observations | `Feed` — `fetch_year(external_id, year, variables)` | station-keyed time series (an API, a warehouse table, a file mirror) |
| normals | `NormalsSource` — `fetch(station_id)` returning one typical year | typical-year products; served only by explicit `source=` pin, never routed |
| grid | `Source` — `estimate(latitude, longitude, start, end, ...)` | gridded/reanalysis products sampled at a point; no station involved. A grid source declares `name`, `kind`, and `variables` and is registerable via `eeweather.sources.register`, making it nameable in preference tuples, `source=` pins, and `to_dict`/`from_dict`; it participates in routing when `kind == "observations"`. Its `Provenance` carries `kind`, `source`, and `variables` with an open `payload` dict and no `station_id`. `candidates()` remains station-only |

The engine supplies everything around the fetch: per-year caching with
variable-union refresh, typical-year tiling (Feb 29 is NaN), range
alignment to an identical UTC index per request, resampling to any
pandas frequency by each variable's declared aggregation, gap warnings,
provenance records, and variable routing. A source
implements transport and parsing, nothing else.

## The contracts every source honors

- **Canonical variables and units.** Users never see native names or
  units. Declare the canonical variables you serve (see
  `sources/vocabulary.py`: name, unit, definition, aggregation) and
  translate both
  directions at ingest — request canonical → your native names, response
  native → canonical columns in canonical units. If you serve a variable
  the vocabulary lacks, add the vocabulary entry (one `Variable` line)
  in the same change. Unit validation against real payloads is part of
  acceptance.
- **Station identity.** Station ids are GHCN ids; every other id system
  is an alias in the identifier crosswalk (`registry/identifiers.db`).
  Never parse an id's format. If your data is keyed by another system,
  declare `id_namespace` and the engine translates per fetch; if it uses
  a system the crosswalk lacks, add alias rows for it. A source's
  catalog, inventory, quality, and availability tables are keyed by
  station id alone, and enumeration unions every registered catalog, so
  a source covering a disjoint set of stations from the built-ins needs
  no repo change to integrate.
- **Frames** are indexed by UTC timestamps; values the station did not
  report are NaN; duplicate timestamps are averaged (accumulation
  variables are instead summed within the hour).

## Grid sources

A grid source can carry more than one underlying grid. A gridded product
often blends independent models with distinct geometries and publication
schedules, and each such **family** is served as a separate grid with its
own cell size, registration, and latency — `nasa_power` serves a
meteorological family (half-degree-ish cells, days of latency) alongside a
solar family (one-degree cells, months of latency), and a single load can
draw variables from both.

A **cell** is the client's own arithmetic, not something the api confirms:
the response echoes back whatever point it was asked about, so an adapter
derives which cell contains a coordinate from the family's registration
(cell size and edge convention) and requests that cell's centre, so every
point inside it shares one cache entry and one identical series.
Misregistering by half a cell silently aliases the cache to the wrong
location, so a family's registration is verified against evidence — not
assumed from documentation — and pinned in snapshot tests.

The engine caches a grid load per `(source, family, cell, year)` block,
mirroring the station path's per-`(source, station, year)` blocks. A block
is written only once every requested (and previously cached) variable has
arrived; a submission that fails partway through leaves no partial block
behind, since a partial one would read as complete on the next load.

A lagged product cannot reuse the station path's grace period. The station
path finalizes a year some fixed number of days after year-end, but a
family publishing months in arrears — or one whose recent tail is a
provisional product a slower one later replaces — would otherwise freeze a
permanent, unpublished-looking gap into the cache. A grid source instead
declares its own volatility window per family (how long after year-end
that family keeps rewriting its published tail, and whether a block ending
in fill counts as still-unsettled); the engine re-requests a cached block
still inside that window rather than treating it as final.

Provenance is keyed by family, since one load can span several grids:
`payload = {"met": {...}, "solar": {...}}`, each entry carrying that
family's cell and whatever the response said about itself (upstream
product versions, revision identifiers), so a value a later reprocessing
silently replaces is traceable back to the block that served it.

## Anatomy of a built-in source package

```
sources/<name>/
  __init__.py    docstring, DATA_PATH, one register_attachment call,
                 re-export of the class  (no classes or functions here)
  source.py      class <Name>Source(<Kind>)
  <name>.db      packaged sqlite data, if the source ships any
```

Registration attaches the data file to every registry connection under
the source's name, with roles describing its tables:

- `catalog=True` — a `stations` table of station facts (station_id,
  name, latitude, longitude, elevation, country, subdivision) and a
  `station_zone` table of zone assignments. Facts for a station are
  read from the first registered catalog that lists it, and enumeration
  is the union across catalogs; both behaviors are pinned in
  `tests/registry/test_db.py`.
- `inventory=True` — an `inventory` table of monthly observation counts
  per (station_id, year); powers quality ratings.
- `quality=True` — a `quality` table of (station_id, rating).
- `availability=True` — a `stations` table listing which stations the
  source can serve (archive lists); powers the `has_sources` ranking
  filter, exposed as an `is_<name>` column.

Invariant (pinned in `tests/registry/test_schema.py`): every station id
in the crosswalk appears in at least one catalog. If your source
introduces stations the crosswalk lacks, its build step must insert
their identity rows and catalog facts together.

## Steps

1. Create the package with the anatomy above; subclass the kind's
   contract and declare only what is distinctive (compare
   `GHCNhSource`: `name`, `id_namespace`, `variables`; the normals
   classes: `name` and an archive `_url`).
2. Register the built-in: add the class to `BUILTIN_SOURCES` in
   `sources/engine.py` so the string name resolves.
3. Data: extend `build/schema.py` and `build/migrate.py` (or your own
   build step) to produce `<name>.db`; if its content decays, extend
   `build/refresh.py` and the `refresh-registry` workflow's `add-paths`.
4. Vocabulary: add any new canonical variables, with units and
   aggregation, to `sources/vocabulary.py`.
5. Tests, mirroring the package layout (`tests/sources/test_<name>.py`):
   transport-level tests against real captured payloads (fixtures in
   `tests/fixtures/`, recorded from the live service — never
   synthesized; synthetic data is for edge cases only), unit pins with
   hardcoded expected values, error paths (empty responses, unknown
   stations), and a schema entry in `tests/registry/test_schema.py` for
   your data file. Add the source's expected rows to the
   `sources_serving`/`variables()` pins in `tests/sources/test_sources.py`.
6. CHANGELOG entry describing the source and its variables.

## External sources (no repo changes)

Users plug in their own data without touching this repo:

- Station-keyed (e.g. a BigQuery table): implement the `Feed` protocol
  and pass the instance — `StationSource(dataset=my_feed)` or directly
  in a location's `sources=(...)` tuple. Declare `cacheable = False`
  for fast backends. The contract test pattern is `FixtureFeed` in
  `tests/sources/test_sources.py`.
- Gridded: implement `Source.estimate` returning
  `(DataFrame, warnings, provenance)` and declare `name`, `kind`, and
  `variables` on the object (routing reads them). Register the instance
  the same way as a feed to make it nameable in preference tuples,
  `source=` pins, and location serialization. `candidates()` remains
  station-only — a grid source is reached only through `WeatherLocation`.

To make an external source nameable — usable as a string in preference
tuples and `load_data(source=...)`, and rebuildable by
`WeatherLocation.from_dict`/`from_json` — register the instance once at
import of your package:

```python
eeweather.sources.register(MyFeed())
location = eeweather.WeatherLocation(lat, lon, sources=("ghcnh", "my-feed"))
```

Registration accepts feeds and normals sources; built-in names cannot
be replaced. Optionally, register a sqlite file of your own
(`eeweather.registry.db.metadata_db_connection_proxy.register_attachment`,
same roles as built-in sources) to give your source availability
filtering, inventory-based quality, and ranking columns.

A source serving variables the vocabulary lacks declares them at
registration; they become requestable, routable, and visible in
`eeweather.sources.variables()` like canonical entries:

```python
eeweather.sources.register(
    MyIrradianceFeed(),
    vocabulary=(
        eeweather.sources.Variable(
            "ghi", "W/m2", "Global horizontal irradiance.", "mean"
        ),
    ),
)
```

The one-definition rule still holds: canonical names are reserved, and
when several sources register the same variable their definitions must
agree, so the first registration freezes the unit and aggregation. A
variable's ``aggregation`` ("mean", "sum", "min", or "max") controls
its resampling to other frequencies;
accumulation variables (``aggregation="sum"``, e.g. precipitation
depth) add up within each period and are never gap-interpolated.

What an external source cannot do, by design:

- Serve stations the registry does not know. Station-keyed loads
  translate registry ids; a private sensor network enters as a
  location-keyed `Source`, not a feed.

Dependencies for external backends (cloud SDKs and the like) belong in
the user's package, never in eeweather's.
