#!/bin/bash

# requires mapshaper (npm install -g mapshaper)
# requires ogr2ogr (brew install gdal)

# Reference materials
# http://energy.gov/sites/prod/files/2015/02/f19/ba_climate_guide_2013.pdf
# http://www2.census.gov/geo/docs/reference/codes/files/national_county.txt


# make script work independent of working directory
PARENT_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$PARENT_PATH"

DATA_DIR=${1:-data}
mkdir -p $DATA_DIR

echo Downloading primary source files to $DATA_DIR

echo Downloading cb_2016_us_zcta510_500k.json
./create_zipcode_geojson.sh $DATA_DIR

echo Downloading cb_2016_us_county_500k.json
./create_county_geojson.sh $DATA_DIR

echo Downloading CA_Building_Standards_Climate_Zones.json
./create_ca_climate_zone_geojson.sh $DATA_DIR

# IECC/Building America climate zone csv. Custom; assembled and corrected from primary source
echo Downloading climate_zones.csv
wget -N https://gist.githubusercontent.com/philngo/d3e251040569dba67942/raw/0c98f906f452b9c80d42aec3c8c3e1aafab9add8/climate_zones.csv -P $DATA_DIR -q --show-progress

# NCEI station lat lngs and metadata
echo Downloading isd-history.csv
wget -N https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv -P $DATA_DIR -q --show-progress

# NCEI weather data quality
echo Downloading isd-inventory.csv
wget -N https://www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv -P $DATA_DIR -q --show-progress

# Scrape-friendly TMY3 station list
echo Downloading tmy3-stations.html
cp /app/eeweather/resources/tmy3-stations.html $DATA_DIR

# Add ZIP code prefix mapping
echo Downloading state zipcode prefixes
wget -N https://gist.githubusercontent.com/philngo/247226aa89e5abf5869b981b9b841245/raw/56e25d8d590c001a18a1c0bab3ac69c53c09117c/zipcode_prefixes.json -P $DATA_DIR -q --show-progress

echo Finished downloading primary source files

# GHCNh station list for the usaf -> ghcn id mapping
echo Downloading ghcnh-station-list.csv
wget -N https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.csv -P $DATA_DIR -q --show-progress

# GHCNh inventory for per-station data availability years
echo Downloading ghcnh-inventory.txt
wget -N https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-inventory.txt -P $DATA_DIR -q --show-progress
