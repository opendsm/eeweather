# References

## Data sources

- **GHCNh — Global Historical Climatology Network, hourly** (NOAA NCEI).
  The observed-weather source: hourly surface observations, served through
  the [NCEI Access Data Service](https://www.ncei.noaa.gov/access/services/data/v1)
  and described on the
  [GHCNh product page](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly).
  The packaged station catalog and observation inventory derive from the
  GHCNh station list and inventory files under
  `https://www.ncei.noaa.gov/oa/global-historical-climatology-network/`.
  GHCNh supersedes the ISD/GSOD feeds earlier EEweather versions used (those
  stopped receiving data 2025-08-27); overlap validation against ISD history
  showed a median hourly deviation of 0.0001 °C.
- **TMY3 — Typical Meteorological Year 3** (NREL). Typical-year data for US
  stations, from the archived NREL TMY3 collection; EEweather serves a
  mirrored copy of the archive.
- **CZ2010** (California Energy Commission). Typical-year data for
  California's building-climate-zone reference stations, used in Title 24
  work; EEweather serves a mirrored copy.
- **Identifier crosswalk.** Station aliases (USAF, WBAN, ICAO, WMO) derive
  from the GHCNh station list and the historical ISD station history file,
  audited against both (every alias verified by coordinate agreement;
  catch-all and reused identifiers resolved by recency).
- **Geography.** ZCTA centroids from the US Census Bureau; IECC climate zones
  and moisture regimes and Building America climate zones from DOE/PNNL
  county assignments; California Building Climate Zone Areas from the CEC.

## Methods

- **Sub-hourly gap interpolation** follows CalTRACK 2.3.3: linear
  interpolation at the minute level, limited to 60 minutes, for
  point-in-time variables. See the
  [CalTRACK methods](https://docs.caltrack.org/) and their successor,
  maintained under [OpenDSM](https://opendsm.energy/).
- **Station matching** ranks by WGS84 geodesic distance with optional
  climate-zone, subdivision, quality, and availability constraints; see
  [matching.md](matching.md).

## Related projects

- [OpenDSM](https://opendsm.energy/) (formerly OpenEEmeter) — the
  measurement models EEweather was built to feed; its documentation site
  hosts the published version of these pages.
- [eemeter](https://github.com/opendsm/opendsm) — model implementations
  consuming EEweather frames.
