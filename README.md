# EEweather: Weather station wrangling for EEmeter

[![License](https://img.shields.io/github/license/opendsm/eeweather.svg)](https://github.com/opendsm/eeweather)
[![PyPI Version](https://img.shields.io/pypi/v/eeweather.svg)](https://pypi.python.org/pypi/eeweather)

---

**EEweather** — tools for matching to and fetching data from NCEI GHCNh, TMY3, or CZ2010 weather stations.

EEweather comes with a database of weather station metadata, ZCTA metadata, and GIS data that makes it easier to find the right weather station to use for a particular ZIP code or lat/long coordinate.

[Documentation lives at opendsm.energy.](https://opendsm.energy)

## Usage

```python
import datetime
import eeweather

station = eeweather.WeatherStation("722880")
df, warnings = station.load_data(
    datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    datetime.datetime(2024, 12, 31, tzinfo=datetime.timezone.utc),
    frequency="hourly",
    variables=("temperature",),
)
```

## Installation

EEweather is a python package and can be installed with pip.

```
$ pip install eeweather
```

## Supported Sources of Weather Data

- NOAA Global Historical Climatology Network hourly (GHCNh)
- NREL Typical Meteorological Year 3 (TMY3)
- California Energy Commission 1998-2009 Weather Normals (CZ2010)

## Features

- Match by ZIP code (ZCTA) or by lat/long coordinates
- Use user-supplied weather station mappings
- Match within climate zones
  - IECC Climate Zones
  - IECC Moisture Regimes
  - Building America Climate Zones
  - California Building Climate Zone Areas
- User-friendly SQLite database of metadata compiled from primary sources
  - US Census Bureau (ZCTAs, county shapefiles)
  - Building America climate zone county lists
  - NOAA NCEI Integrated Surface Database Station History
  - NOAA GHCNh station list
  - NREL TMY3 site
- Plot maps of outputs

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

## Use with Docker

To use with docker-compose, use the following:

Run a tutorial notebook (copy link w/ token, open tutorial.ipynb):

```
$ docker-compose up jupyter
```

Open a shell:

```
$ docker-compose run --rm shell
```

Run tests:

```
$ docker-compose run --rm test
```

Run the CLI:

```
$ docker-compose run --rm eeweather --help
```

## Notice Regarding CZ2010 Data

There may be conditions placed on their international commercial use.
They can be used within the U.S. or for non-commercial international activities without restriction.
The non-U.S. data cannot be redistributed for commercial purposes.
Re-distribution of these data by others must provide this same notification.

See [further explanation](http://weather.whiteboxtechnologies.com/faq#Q12/) here.

## Metadata Yearly Updates

Every year, the metadata database needs to be updated. This can be done by running:

```
docker-compose run --rm eeweather rebuild-db
```
