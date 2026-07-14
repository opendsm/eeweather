FROM python:3.12-bookworm

RUN apt-get update \
  && apt-get install -yqq \
    # sphinxcontrib-spelling dependency
    libenchant-2-dev \
    # geo libraries
    binutils libproj-dev gdal-bin libgeos-dev \
    # unzip for rebuilding metadata.db
    unzip \
    # node for mapshaper
    nodejs npm \
    # for access to metadata.db
    sqlite3 libsqlite3-dev

RUN npm install -g mapshaper

COPY pyproject.toml README.md LICENSE /app/
COPY eeweather/ /app/eeweather
RUN set -ex && pip install -e /app[dev]

WORKDIR /app
