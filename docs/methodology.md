# Methodology

EEweather answers one question for energy-efficiency measurement: **what was the
weather at this building?** Meters are at buildings; weather is observed at
stations. Between the two sit every problem this library exists to solve —
finding a defensible station for a location, judging whether its data is good
enough, fetching and aligning the observations, and being able to prove, years
later, exactly where every value came from.

## Motivation

Savings measurement compares energy use across periods that can be years apart,
normalized for weather. That places demands on weather data that general-purpose
weather APIs do not meet:

- **Defensible attribution.** A weather-normalized savings number is only as
  credible as its weather. The station serving a site must be near enough to be
  a valid proxy, its data quality must be assessable, and the choice must be
  explainable.
- **Reproducibility across periods.** A baseline fit in one year and a
  reporting-period prediction in another must use the *same* station. A silent
  switch to a different station between periods contaminates the comparison.
- **Analysis-ready alignment.** Models want complete, regular, UTC-indexed
  frames with honest missing-data semantics — not raw observation streams with
  duplicate timestamps, gaps, and native units.
- **Longevity.** Programs run for decades. Station networks change, identifier
  systems come and go, and data products are retired (EEweather itself
  migrated when the ISD feed stopped receiving data in 2025). The library must
  absorb that churn without breaking the analyses built on it.

## The two abstractions

The public API is two classes and a handful of namespaces.

**`WeatherLocation`** is weather at a latitude/longitude — the common case,
since analysts have building coordinates, not station ids. A location resolves
itself to the nearest suitable station per source, loads data, and records how.

**`WeatherStation`** is weather at a known station — the pinned case, keyed by
the station's registry id, with constructors that translate historical
identifier systems (USAF, WBAN, ICAO, WMO).

Both share one loading verb: `load_data(start, end, frequency, variables,
source=)` returns `(DataFrame, warnings)` for observed data and typical years
alike. There are no per-product methods to learn.

## Station identity

Every station has exactly one registry id (its GHCN id — the broadest station
identifier system in use, covering roughly ten times as many stations as USAF
or WMO numbering). Every other identifier is an *alias* recorded in a packaged
crosswalk, so `WeatherStation.from_usaf("722880")`,
`from_wban("23152")`, `from_icao("KBUR")`, and
`WeatherStation("USW00023152")` all reach the same station. Aliases carry a
recency marker: when an identifier was reused over history (retired WBAN
numbers were), the most recent holder wins, and a genuinely unresolvable
identifier raises rather than guessing. Id formats are never parsed; ids are
opaque keys into the registry.

## Sources and routing

A *source* is a provider of weather data. Built-ins: **GHCNh** (NOAA's hourly
observation network — the default), **TMY3** and **CZ2010** (typical-year
products, for normals-based analysis). Custom sources — a BigQuery mirror, an
internal archive — implement small public protocols and participate as equals
(see [adding-a-source.md](adding-a-source.md)).

Locations and stations carry an ordered source preference
(`sources=("ghcnh",)` by default). Each requested variable routes to the
first source in the preference that serves it, and the results join into one
frame — a user asking for temperature from observations and irradiance from a
gridded product names variables, not plumbing. Two rules keep routing honest:

- **One variable, one source, per call.** Values from different sources are
  never stitched together inside a single column.
- **Typical years never route.** Measured and synthetic data are never mixed
  silently; TMY3/CZ2010 are reachable only by an explicit `source=` pin.

## The variable vocabulary

Every variable has exactly one canonical name, unit, definition, and
aggregation, owned by the vocabulary. Sources translate their native fields
and units at ingest; users never see native forms, and un-vetted fields are
never passed through. The 1.0 set is temperature, dew point temperature
[degC], relative humidity [%], wind speed [m/s], station-level pressure
[hPa], and visibility [km]; `eeweather.sources.variables()` lists the current
vocabulary and which sources serve each entry. External sources may register
additional variables at runtime under the same one-definition rules.

## Frequencies and aggregation

Data is fetched hourly and served at any pandas frequency —
`load_data(frequency=...)` takes a pandas offset alias (`"30min"`, `"h"`,
`"D"`, `"W"`, `"MS"`, `"YS"`), parsed and validated by pandas itself.
Resampling honors each variable's declared aggregation: point-in-time
variables (temperature) average into coarser periods, while accumulation
variables sum, are never gap-interpolated, and report NaN (never a silent
zero) for periods with no data. Frequencies finer than hourly interpolate
point-in-time variables linearly between hourly values and spread
accumulations evenly, never crossing a missing hour. Frames for one request
range and frequency share an identical UTC index regardless of source, so
multi-source results join safely by construction.

## Missing data

Partial coverage surfaces as NaN values plus structured warnings (late starts,
early ends, internal gaps) — routed requests never raise for missing data. A
source explicitly pinned with `source=` that has nothing at all for the
requested dates raises `DataNotAvailableError`. Sub-hourly gaps up to an hour
are filled by linear interpolation at the minute level (the CalTRACK 2.3.3
rule) for point-in-time variables.

## Provenance and reproducibility

Every load records provenance — per source: what kind of data, which station,
how far from the site, which variables — on the returned frame's
`attrs["provenance"]` and on the location or station object. Provenance is
also the reproducibility mechanism: a location **pins itself to the stations
resolved at its first load**, so later loads on the same location reuse them,
and `to_dict`/`to_json` (with `from_dict`/`from_json`) carry that state across
processes. A baseline load, a saved JSON blob, and a reporting-period load a
year later are guaranteed the same station per source. See
[matching.md](matching.md) for how the station is chosen in the first place.

## The packaged registry, and keeping it current

EEweather ships its registry — station catalog, identifier crosswalk,
climate-zone geometries and assignments, ZCTA places, observation inventory,
quality ratings — as packaged data, so matching and metadata work offline and
identically for everyone on a given install. Weather data itself is always
fetched live (and cached locally; see `eeweather.cache`).

The live parts of the registry (inventory, quality, newly commissioned
stations, identifier aliases) decay on a yearly timescale. EEweather keeps
them current automatically: when the installed data is more than six months
old, a load starts a background update into the platform user data directory,
preferring ready-made files published by the repository's scheduled refresh
(CDN-served, so fleets of any size cost the upstream agencies nothing) and
falling back to rebuilding directly from the live NOAA files. Updates are
atomic, abort on implausible upstream content, and take effect in new
processes. `EEWEATHER_AUTO_UPDATE=0` disables them;
`python -m eeweather.registry.update` runs one on demand.
