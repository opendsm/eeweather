FROM python:3.12-bookworm
# bullseye required for GEOS>3.7.1 which is needed for newest cartopy

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

COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
RUN pip install pipenv
RUN set -ex && pipenv install --system --deploy --dev
ENV PYTHONPATH=/app

COPY setup.py README.rst /app/
COPY eeweather/ /app/eeweather
RUN set -ex && cd /usr/local/lib/ && python /app/setup.py develop

WORKDIR /app
