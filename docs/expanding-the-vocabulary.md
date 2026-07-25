# Expanding the variable vocabulary

> External sources do not need this document: a variable served only by
> a private source is declared at runtime via
> `eeweather.sources.register(source, vocabulary=...)`. This document
> covers adding a *canonical* entry — one built-in sources serve.

Every variable a source can serve has exactly one canonical name, unit,
definition, and aggregation, owned by `sources/vocabulary.py`. Users only ever see
canonical forms; sources translate their native names and units at
ingest. The vocabulary is curated: un-vetted native fields are never
passed through, so adding a variable is a deliberate, verified change.

## Rules

- **One canonical unit per variable, forever.** Pick it when the
  variable is added (SI-leaning, ascii-spelled: `degC`, `m/s`, `hPa`,
  `W/m2`) and never change it — downstream analyses depend on a column
  name implying its unit. There are no unit options in the API; sources
  convert at ingest, users convert downstream if they must.
- **Names are snake_case, owned by eeweather.** The initial set adopted
  GHCNh's spellings because they were sensible, but the name belongs to
  the vocabulary, not to any source.
- **Declare the aggregation.** A variable's `aggregation` ("mean",
  "sum", "min", or "max") governs its resampling to coarser frequencies,
  and is always stated explicitly — a silent default on an accumulation
  variable would produce wrong values with no error. Point-in-time
  quantities declare "mean"; accumulation variables (precipitation)
  declare "sum" — the engine adds them up within each period, spreads
  them evenly across sub-hourly slots, and never gap-interpolates them.
- **Reserved suffixes.** Columns ending in `_imputed_fraction` or
  `_is_imputed` are engine-produced companions of a canonical variable
  and are exempt from vocabulary validation; never name a variable to
  collide with them.

## Steps

1. Add the `Variable(name, unit, description, aggregation)` entry to
   `VARIABLES` in `sources/vocabulary.py`.
2. Declare it in the `variables` tuple of every source that serves it,
   with translation from the source's native name and conversion into
   the canonical unit inside that source's `fetch_year`/`fetch`.
3. Verify units against real payloads — capture a live response as a
   fixture and pin expected values with hardcoded numbers. Unit
   validation against real data is the acceptance bar for the
   declaration; a plausible-looking column in the wrong unit is worse
   than no column.
4. Update the pins in `tests/sources/test_sources.py`
   (`sources_serving`, the `variables()` accessor frame) and add
   fetch-level tests for the new variable in the serving sources' test
   modules.
5. CHANGELOG entry naming the variable, its unit, and which sources
   serve it.

## What routing does with it automatically

Nothing else is required: a requested variable routes to the first
source in the preference tuple that declares it, `variables="all"`
expands to the union of the configured sources' vocabularies, an
unroutable request raises a `ValueError` naming the sources that do
serve it, and provenance records which source supplied it.
