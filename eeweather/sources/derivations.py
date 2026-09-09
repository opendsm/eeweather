"""Post-aggregation derivations from canonical variables.

Some quantities are only meaningful once components have been aggregated,
not before, so they are not served as canonical variables. Callers derive
them explicitly after aggregating.
"""
import numpy as np
import pandas as pd



def wind_direction(eastward_wind, northward_wind):
    """Meteorological wind direction, in degrees, from wind components.

    Returns the direction the wind blows *from*, measured clockwise from
    north: 0/360 is a wind from the north, 90 is from the east, 180 is
    from the south, 270 is from the west. Computed with ``atan2`` as
    ``(270 - degrees(atan2(northward_wind, eastward_wind))) % 360``.

    ``eastward_wind`` and ``northward_wind`` must already be aggregated
    (e.g. daily or monthly means) before calling this function. Averaging
    directions directly is not meaningful, because direction is circular;
    the vector mean of the components taken first, then converted to a
    direction, is the correct order.

    A zero vector (both components zero, i.e. calm) has no defined
    direction; this returns NaN. NaN in either input returns NaN.

    Accepts scalars or array-likes (e.g. ``pandas.Series``); vectorises
    over array-likes without a Python loop.
    """
    eastward = np.asarray(eastward_wind, dtype=float)
    northward = np.asarray(northward_wind, dtype=float)

    calm = (eastward == 0) & (northward == 0)
    direction = (270 - np.degrees(np.arctan2(northward, eastward))) % 360
    direction = np.where(calm, np.nan, direction)

    if isinstance(eastward_wind, pd.Series):
        return pd.Series(direction, index=eastward_wind.index, name="wind_direction")

    if direction.ndim == 0:
        return direction.item()

    return direction
