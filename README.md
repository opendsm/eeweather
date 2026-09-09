# EEweather: Weather for energy-efficiency modeling

[![License](https://img.shields.io/github/license/opendsm/eeweather.svg)](https://github.com/opendsm/eeweather)
[![PyPI Version](https://img.shields.io/pypi/v/eeweather.svg)](https://pypi.python.org/pypi/eeweather)

---

**EEweather** answers "what was the weather here?" — it matches locations to
weather stations, fetches observed and typical-year data, and returns
analysis-ready frames with warnings and provenance.

Documentation lives in [docs/](docs/) (publishing to
[opendsm.energy](https://opendsm.energy)).

## Usage

```python
from datetime import datetime, timezone

import eeweather

location = eeweather.WeatherLocation(34.2, -118.4)   # or .from_place("zcta", "91104")
df, warnings = location.load_data(
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 12, 31, tzinfo=timezone.utc),
)
location.provenance     # which station served each variable, and how far away

saved = location.to_json()  # coordinates, sources, and the stations resolved at load
location = eeweather.WeatherLocation.from_json(saved)  # later loads (e.g. a reporting
                                                       # period) reuse the same stations

station = eeweather.WeatherStation("USW00023152")     # or by registry id
station = eeweather.WeatherStation.from_usaf("722880")  # or by historical ids
df, warnings = station.load_data(
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 12, 31, tzinfo=timezone.utc),
    variables=("temperature", "relative_humidity"),
)
typical, _ = station.load_data(
    datetime(2024, 1, 1, tzinfo=timezone.utc),
    datetime(2024, 12, 31, tzinfo=timezone.utc),
    source="tmy3",                                    # typical-year data by explicit pin
)
```

## Installation

```
$ pip install eeweather
```

## Features

- One loading verb over pluggable sources: GHCNh observations (NOAA), NASA
  POWER gridded meteorological and solar data, TMY3 (NREL) and CZ2010 (CEC)
  typical years; every load returns an aligned UTC frame plus data-quality
  warnings and per-source provenance
- A packaged station registry with opaque ids and identifier translation
  (USAF, WBAN, ICAO), precomputed climate-zone assignments (IECC, Building
  America, California), ZCTA place codes, and per-source observation
  inventory
- Station matching: ranked candidates for any point with zone, quality,
  distance, and availability filters (`location.candidates()`), plus
  data-sufficiency selection
- Extension protocols for custom data: station-keyed feeds (e.g. a BigQuery
  table keyed by any translatable id system) and location-keyed gridded
  sources
- A shared sqlite weather cache (`eeweather.cache.set_path`/`clear`)

## Contributing

Dev installation:

```
$ python -m venv .venv
$ source .venv/bin/activate
$ pip install -e .[dev]
```

Run tests:

```
$ pytest
```

Run tests on multiple python versions:

```
$ tox
```

Or with Docker:

```
$ docker compose run --rm test
```

## Registry updates

The packaged registry (GHCNh station list, observation inventory, quality
ratings, identifier aliases) keeps itself current: when the live data is
more than six months old, loading data starts a background update into
the platform user data directory, and those copies take precedence over
the wheel's in new processes. Updates download the ready-made files a
scheduled workflow publishes to the repository's rolling release
(CDN-served, so any number of clients costs NOAA nothing and no client
rebuilds locally) and fall back to rebuilding directly from the live
NOAA files when that channel is unreachable or stale, so they keep
working even if the repository goes dormant. Concurrent workers on a
machine coordinate through an atomic claim file (one attempt per day,
however many race), and the update thread waits a minute before touching
the network, so short-lived pipeline workers exit without generating
traffic. Set `EEWEATHER_AUTO_UPDATE=0` to suppress the traffic entirely,
or manage it directly with:

```
$ python -m eeweather.registry.update           # refresh on demand
$ python -m eeweather.registry.update --clear   # revert to packaged data
```

A scheduled workflow runs the same refresh monthly and opens a pull
request so the wheel's snapshot stays current; maintainers can rebuild
all packaged data with `python -m eeweather.build`.

## Notice Regarding CZ2010 Data

There may be conditions placed on their international commercial use.
They can be used within the U.S. or for non-commercial international activities without restriction.
The non-U.S. data cannot be redistributed for commercial purposes.
Re-distribution of these data by others must provide this same notification.

See [further explanation](http://weather.whiteboxtechnologies.com/faq#Q12/) here.
