#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Copyright 2018-2023 OpenEEmeter contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""
import numpy as np

from .connections import metadata_db_connection_proxy
from .exceptions import UnrecognizedUSAFIDError
from .stations import ISDStation

__all__ = ("plot_station_mapping", "plot_station_mappings")


def plot_station_mapping(
    target_latitude,
    target_longitude,
    isd_station,
    distance_meters,
    target_label="target",
):  # pragma: no cover
    """Plots this mapping on a map."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("Plotting requires matplotlib.")

    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        import cartopy.io.img_tiles as cimgt
    except ImportError:
        raise ImportError("Plotting requires cartopy.")

    lat, lng = isd_station.coords
    t_lat, t_lng = float(target_latitude), float(target_longitude)

    # fiture
    fig = plt.figure(figsize=(16, 8))

    # axes
    tiles = cimgt.Stamen("terrain-background")
    ax = plt.subplot(1, 1, 1, projection=tiles.crs)

    # offsets for labels
    x_max = max([lng, t_lng])
    x_min = min([lng, t_lng])
    x_diff = x_max - x_min

    y_max = max([lat, t_lat])
    y_min = min([lat, t_lat])
    y_diff = y_max - y_min

    xoffset = x_diff * 0.05
    yoffset = y_diff * 0.05

    # minimum
    left = x_min - x_diff * 0.5
    right = x_max + x_diff * 0.5
    bottom = y_min - y_diff * 0.3
    top = y_max + y_diff * 0.3

    width_ratio = 2.0
    height_ratio = 1.0

    if (right - left) / (top - bottom) > width_ratio / height_ratio:
        # too short
        goal = (right - left) * height_ratio / width_ratio
        diff = goal - (top - bottom)
        bottom = bottom - diff / 2.0
        top = top + diff / 2.0
    else:
        # too skinny
        goal = (top - bottom) * width_ratio / height_ratio
        diff = goal - (right - left)
        left = left - diff / 2.0
        right = right + diff / 2.0

    ax.set_extent([left, right, bottom, top])

    # determine zoom level
    # tile size at level 1 = 64 km
    # level 2 = 32 km, level 3 = 16 km, etc, i.e. 128/(2^n) km
    N_TILES = 600  # (how many tiles approximately fit in distance)
    km = distance_meters / 1000.0
    zoom_level = int(np.log2(128 * N_TILES / km))

    ax.add_image(tiles, zoom_level)

    # line between
    plt.plot(
        [lng, t_lng],
        [lat, t_lat],
        linestyle="-",
        dashes=[2, 2],
        transform=ccrs.Geodetic(),
    )

    # station
    ax.plot(lng, lat, "ko", markersize=7, transform=ccrs.Geodetic())

    # target
    ax.plot(t_lng, t_lat, "ro", markersize=7, transform=ccrs.Geodetic())

    # station label
    station_label = "{} ({})".format(isd_station.usaf_id, isd_station.name)
    ax.text(lng + xoffset, lat + yoffset, station_label, transform=ccrs.Geodetic())

    # target label
    ax.text(t_lng + xoffset, t_lat + yoffset, target_label, transform=ccrs.Geodetic())

    # distance labels
    mid_lng = (lng + t_lng) / 2
    mid_lat = (lat + t_lat) / 2
    dist_text = "{:.01f} km".format(km)
    ax.text(mid_lng + xoffset, mid_lat + yoffset, dist_text, transform=ccrs.Geodetic())

    plt.show()


def plot_station_mappings(mapping_results):  # pragma: no cover
    """Plot a list of mapping results on a map.

    Requires matplotlib and cartopy.

    Parameters
    ----------
    mapping_results : list of MappingResult objects
        Mapping results to plot
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("Plotting requires matplotlib.")

    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    except ImportError:
        raise ImportError("Plotting requires cartopy.")

    lats = []
    lngs = []
    t_lats = []
    t_lngs = []
    n_discards = 0
    for mapping_result in mapping_results:
        if not mapping_result.is_empty():
            lat, lng = mapping_result.isd_station.coords
            t_lat, t_lng = map(float, mapping_result.target_coords)
            lats.append(lat)
            lngs.append(lng)
            t_lats.append(t_lat)
            t_lngs.append(t_lng)
        else:
            n_discards += 1

    print("Discarded {} empty mappings".format(n_discards))

    # figure
    fig = plt.figure(figsize=(60, 60))

    # axes
    ax = plt.subplot(1, 1, 1, projection=ccrs.Mercator())

    # offsets for labels
    all_lngs = lngs + t_lngs
    all_lats = lats + t_lats
    x_max = max(all_lngs)  # lists
    x_min = min(all_lngs)
    x_diff = x_max - x_min

    y_max = max(all_lats)
    y_min = min(all_lats)
    y_diff = y_max - y_min

    # minimum
    x_pad = 0.1 * x_diff
    y_pad = 0.1 * y_diff
    left = x_min - x_pad
    right = x_max + x_pad
    bottom = y_min - y_pad
    top = y_max + y_pad

    width_ratio = 2.0
    height_ratio = 1.0

    if (right - left) / (top - bottom) > height_ratio / width_ratio:
        # too short
        goal = (right - left) * height_ratio / width_ratio
        diff = goal - (top - bottom)
        bottom = bottom - diff / 2.0
        top = top + diff / 2.0
    else:
        # too skinny
        goal = (top - bottom) * width_ratio / height_ratio
        diff = goal - (right - left)
        left = left - diff / 2.0
        right = right + diff / 2.0

    left = max(left, -179.9)
    right = min(right, 179.9)
    bottom = max([bottom, -89.9])
    top = min([top, 89.9])

    ax.set_extent([left, right, bottom, top])

    # OCEAN
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "physical",
            "ocean",
            "50m",
            edgecolor="face",
            facecolor=cfeature.COLORS["water"],
        )
    )

    # LAND
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "physical",
            "land",
            "50m",
            edgecolor="face",
            facecolor=cfeature.COLORS["land"],
        )
    )

    # BORDERS
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "cultural",
            "admin_0_boundary_lines_land",
            "50m",
            edgecolor="black",
            facecolor="none",
        )
    )

    # LAKES
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "physical",
            "lakes",
            "50m",
            edgecolor="face",
            facecolor=cfeature.COLORS["water"],
        )
    )

    # COASTLINE
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "physical", "coastline", "50m", edgecolor="black", facecolor="none"
        )
    )

    # lines between
    # for lat, t_lat, lng, t_lng in zip(lats, t_lats, lngs, t_lngs):
    ax.plot(
        [lngs, t_lngs],
        [lats, t_lats],
        color="k",
        linestyle="-",
        transform=ccrs.Geodetic(),
        linewidth=0.3,
    )

    # stations
    ax.plot(lngs, lats, "bo", markersize=1, transform=ccrs.Geodetic())

    plt.title("Location to weather station mapping")

    plt.show()
