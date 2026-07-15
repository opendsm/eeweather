#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compare GHCNh-served temperatures against the retired ISD dataset.

Fetches both datasets from the NCEI access api for a stratified station
sample over their overlap years, runs both through the library's hourly
resampling pipeline, and reports per-station-year deviation statistics.
ISD stopped receiving data 2025-08-27 but still serves its history, which
makes this comparison reproducible.

Run from the repository root:

    python scripts/validate_ghcnh_against_isd.py
"""
import csv
import io
import sqlite3
import sys

import pandas as pd
import pytz
import requests

from eeweather.sources.ghcnh import API_URL, fetch_ghcnh_hourly



YEARS = [2016, 2019, 2022, 2024]

STATIONS_PER_QUALITY = {"high": 6, "medium": 3, "low": 3}


def _sample_stations():
    """Deterministic stratified sample: spread across states within tiers."""
    conn = sqlite3.connect("eeweather/resources/metadata.db")
    cur = conn.cursor()
    stations = []
    for quality, n in STATIONS_PER_QUALITY.items():
        cur.execute(
            """
          select usaf_id, recent_wban_id, ghcn_id, state
          from isd_station_metadata
          where quality = ? and state is not null
          group by state having usaf_id = min(usaf_id)
          order by state
        """,
            (quality,),
        )
        rows = cur.fetchall()
        step = max(1, len(rows) // n)
        stations.extend([(quality,) + row for row in rows[::step][:n]])

    return stations


def _caltrack_hourly(ts):
    # CalTRACK 2.3.3
    resampled = (
        ts.resample("min")
        .mean()
        .interpolate(method="linear", limit=60, limit_direction="both")
        .resample("h")
        .mean()
    )

    return resampled


def _fetch_isd_hourly(usaf_id, wban_id, year):
    resp = requests.get(
        API_URL,
        params={
            "dataset": "global-hourly",
            "dataTypes": "TMP",
            "stations": "{}{}".format(usaf_id, wban_id),
            "startDate": "{}-01-01".format(year),
            "endDate": "{}-12-31".format(year),
        },
        timeout=120,
    )
    resp.raise_for_status()

    data = []
    for record in csv.DictReader(io.StringIO(resp.text)):
        date, temp = record["DATE"], str(record["TMP"]).strip()
        temp_val, suffix = temp.split(",")
        if suffix == "9" or temp_val == "+9999":
            parsed = float("nan")
        else:
            parsed = float(temp_val) / 10.0
        data.append((pd.Timestamp(date, tz=pytz.UTC), parsed))

    if not data:
        return None

    ts = pd.Series(dict(data)).sort_index()
    ts = ts.groupby(ts.index).mean()

    return _caltrack_hourly(ts)


def main():
    results = []
    for quality, usaf_id, wban_id, ghcn_id, state in _sample_stations():
        for year in YEARS:
            isd = _fetch_isd_hourly(usaf_id, wban_id, year)
            ghcnh_raw = fetch_ghcnh_hourly(ghcn_id, year)
            if isd is None or len(ghcnh_raw) == 0:
                if isd is None:
                    n_isd_obs = 0
                else:
                    n_isd_obs = len(isd)
                print(
                    "{} {} {}: skipped (isd={}, ghcnh={} obs)".format(
                        usaf_id, state, year, n_isd_obs, len(ghcnh_raw)
                    )
                )
                continue
            ghcnh = _caltrack_hourly(ghcnh_raw["temperature"])

            both = pd.DataFrame({"isd": isd, "ghcnh": ghcnh}).dropna()
            delta = (both.ghcnh - both.isd).abs()
            results.append(
                {
                    "usaf_id": usaf_id, "state": state, "quality": quality,
                    "year": year, "n_isd": int(isd.notna().sum()),
                    "n_ghcnh": int(ghcnh.notna().sum()), "n_both": len(both),
                    "mean_abs_delta": delta.mean(), "p99_abs_delta": delta.quantile(0.99),
                    "max_abs_delta": delta.max(),
                    "annual_mean_delta": abs(both.ghcnh.mean() - both.isd.mean()),
                }
            )
            r = results[-1]
            print(
                "{usaf_id} {state} {quality} {year}: n_isd={n_isd} n_ghcnh={n_ghcnh}"
                " mean|d|={mean_abs_delta:.4f} p99|d|={p99_abs_delta:.4f}"
                " max|d|={max_abs_delta:.2f} annual|d|={annual_mean_delta:.5f}".format(**r)
            )

    df = pd.DataFrame(results)
    print("\n=== summary over {} station-years ===".format(len(df)))
    for col in ["mean_abs_delta", "p99_abs_delta", "annual_mean_delta"]:
        print(
            "{}: median={:.5f} p90={:.5f} max={:.5f}".format(
                col, df[col].median(), df[col].quantile(0.9), df[col].max()
            )
        )
    print("hourly coverage ratio ghcnh/isd: median={:.4f} min={:.4f}".format(
        (df.n_ghcnh / df.n_isd).median(), (df.n_ghcnh / df.n_isd).min()
    ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
