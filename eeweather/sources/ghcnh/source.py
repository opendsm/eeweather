"""The GHCNh observation source served through the NCEI access API."""
import io
import time

import pandas as pd
import requests

from ..base import Feed



API_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

API_REQUEST_TRIES = 3

API_RETRY_BACKOFF_SECONDS = 5

API_TIMEOUT_SECONDS = 120

DATASET = "global-historical-climatology-network-hourly"

# one session for connection reuse across the many per-station-year requests
_session = requests.Session()


def _get(url, params):  # pragma: no cover (mocked in tests via this seam)
    return _session.get(url=url, params=params, timeout=API_TIMEOUT_SECONDS)


class GHCNhSource(Feed):
    """Observation source for the GHCNh dataset.

    GHCNh's names and units for the canonical vocabulary are already
    canonical, so no translation is applied.
    """

    name = "ghcnh"
    id_namespace = "ghcn"
    variables = (
        "temperature",
        "dew_point_temperature",
        "relative_humidity",
        "wind_speed",
        "station_level_pressure",
        "visibility",
    )

    def fetch_year(self, external_id, year, variables):
        """Fetch one year of observations for a station.

        Retried on connection errors and server errors, which the api
        intermittently returns in bursts; client errors raise immediately.

        Returns
        -------
        pandas.DataFrame
            One column per requested variable, indexed by UTC observation
            time. Observations sharing a timestamp are averaged. Values
            the station did not report are NaN. Empty when the station
            has no data for the year.
        """
        params = {
            "dataset": DATASET,
            # DATE is only included in the response when explicitly requested
            "dataTypes": ",".join(("DATE",) + tuple(variables)),
            "stations": external_id,
            "startDate": "{}-01-01".format(year),
            "endDate": "{}-12-31".format(year),
        }

        for attempt in range(API_REQUEST_TRIES):
            try:
                resp = _get(API_URL, params)
                resp.raise_for_status()
            except requests.HTTPError:
                if resp.status_code < 500 or attempt == API_REQUEST_TRIES - 1:
                    raise
                time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            except requests.RequestException:
                if attempt == API_REQUEST_TRIES - 1:
                    raise
                time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            else:
                break

        empty_index = pd.DatetimeIndex([], tz="UTC")
        empty = pd.DataFrame(columns=list(variables), index=empty_index, dtype=float)
        if resp.text.strip() == "":
            return empty

        raw = pd.read_csv(io.StringIO(resp.text), dtype=str)
        if len(raw) == 0:
            return empty
        if "DATE" not in raw.columns:
            raise ValueError(
                "Malformed GHCNh response for station {} year {}: no DATE"
                " column (the api returned a non-csv body).".format(
                    external_id, year
                )
            )

        index = pd.to_datetime(raw["DATE"]).dt.tz_localize("UTC").rename(None)
        df = pd.DataFrame(index=index)
        for variable in variables:
            if variable in raw.columns:
                df[variable] = pd.to_numeric(raw[variable], errors="coerce").values
            else:
                df[variable] = float("nan")

        df = df.groupby(df.index).mean()
        df = df.sort_index()

        return df
