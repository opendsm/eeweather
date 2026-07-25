# Example

An end-to-end walkthrough: weather for a building, provenance, reproducible
reporting-period loads, station-level access, and typical years. Outputs shown
are real (Burbank, CA; calendar 2024), captured against live NOAA services.

## Weather at a location

Analysts have coordinates, not station ids, so the primary entry point is a
location:

```python
from datetime import datetime, timezone

import eeweather

location = eeweather.WeatherLocation(34.2, -118.365)
# or from a ZIP code tabulation area:
location = eeweather.WeatherLocation.from_place("zcta", "91505")

df, warnings = location.load_data(
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 12, 31, tzinfo=timezone.utc),
)
```

```
                           temperature
2024-01-01 00:00:00+00:00    13.890610
2024-01-01 01:00:00+00:00    13.240167
2024-01-01 02:00:00+00:00    13.098333
...
[8761 rows x 1 columns]
```

The frame covers the full requested range at the requested frequency (hourly
by default) in UTC; hours the station did not report are NaN, and `warnings`
lists anything worth knowing (late starts, gaps, truncation) as structured
`EEWeatherWarning` objects — this load returned none.

Everything about *how* the values were produced is on the provenance record,
stamped on both the frame (`df.attrs["provenance"]`) and the location:

```python
location.provenance
```

```
{'ghcnh': Provenance(kind='observations', source='ghcnh',
                     variables=('temperature',), station_id='USW00023152',
                     distance_meters=0.0, payload={})}
```

The location also knows its climate zones (from packaged geometries — no
network involved):

```python
location.zones
```

```
{'ba_climate_zone': 'Hot-Dry', 'ca_climate_zone': 'CA_09',
 'iecc_climate_zone': '3', 'iecc_moisture_regime': 'B'}
```

## Reproducibility across periods

The first load pinned the location to the station it resolved. Serialize that
state with the baseline, and the reporting-period load — months later, in a
different process — is guaranteed the same station per source:

```python
saved = location.to_json()
```

```
{"latitude": 34.2, "longitude": -118.365, "sources": ["ghcnh"],
 "pins": {"ghcnh": "USW00023152"}}
```

```python
location = eeweather.WeatherLocation.from_json(saved)
reporting, warnings = location.load_data(reporting_start, reporting_end)
```

## Auditing the match

The ranked candidate frame shows the full field the resolution chose from,
with the metadata to defend (or override) the choice:

```python
location.candidates(minimum_quality="high").head(4)
```

```
             distance_meters quality iecc_climate_zone  is_tmy3
station_id
USW00023152              0.0    high                 3     True
USC00041194           2159.8    high                 3    False
USW00023130          11688.4    high                 3     True
USW00093197          21761.5    high                 3     True
```

Stations more than 150 km away are disqualified by default (a station that far
is not a defensible temperature proxy); see
[matching.md](matching.md) for the cap, quality ratings, and the
`ignore_disqualification` escape hatch.

## Weather at a known station

When the station is already decided, key on it directly — by registry id or
through any historical identifier system:

```python
station = eeweather.WeatherStation("USW00023152")
station = eeweather.WeatherStation.from_usaf("722880")   # same station
station.ids
```

```
{'ghcn': ['USW00023152'], 'icao': ['KBUR'], 'usaf': ['722880'],
 'wban': ['23152'], 'wmo': ['72288']}
```

Multiple variables come back as columns of one aligned frame, each in its
canonical unit:

```python
df, warnings = station.load_data(
    start, end, variables=("temperature", "relative_humidity", "wind_speed")
)
df.describe().loc[["mean", "min", "max"]].round(1)
```

```
      temperature  relative_humidity  wind_speed
mean         17.7               59.9         2.3
min           2.8                4.0         0.0
max          44.8              100.0        17.6
```

`eeweather.sources.variables()` lists the full vocabulary — canonical names,
units, aggregations, and which sources serve each.

## Other frequencies

`frequency` takes any pandas offset alias. Coarser frequencies aggregate each
variable by its declared aggregation (temperature averages; an accumulation
variable would sum); finer-than-hourly frequencies interpolate:

```python
monthly, _ = location.load_data(start, end, frequency="MS")
```

```
                           temperature
2024-01-01 00:00:00+00:00         12.5
2024-02-01 00:00:00+00:00         12.4
2024-03-01 00:00:00+00:00         13.6
2024-04-01 00:00:00+00:00         15.5
...
```

```python
halfhourly, _ = station.load_data(july_1, july_2, frequency="30min")
```

```
                           temperature
2024-07-01 00:00:00+00:00    31.464583
2024-07-01 00:30:00+00:00    30.516958
2024-07-01 01:00:00+00:00    29.569333
2024-07-01 01:30:00+00:00    28.895125
```

## Typical years

Typical-year products (TMY3, CZ2010) are synthetic, so they never mix into
observed data implicitly — they are reachable only by an explicit `source=`
pin, and the typical year tiles onto the calendar years you request:

```python
typical, _ = station.load_data(start, end, source="tmy3")
station.provenance
```

```
{'tmy3': Provenance(kind='normals', source='tmy3',
                    variables=('temperature',), station_id='USW00023152',
                    distance_meters=None, payload={})}
```

## Caching

Observed data caches locally per station-year, so repeated loads (a portfolio
of sites sharing stations, re-runs of an analysis) do not refetch.
`eeweather.cache.set_path(...)` relocates the cache;
`EEWEATHER_CACHE_URL` does the same via the environment.
