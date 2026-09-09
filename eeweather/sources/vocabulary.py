"""The variable vocabulary.

Every variable a source can serve has exactly one name, unit, and
definition. The canonical entries are owned here; external sources add
entries at runtime through ``eeweather.sources.register``, with the same
one-definition rule (canonical names are reserved, and the first
registration of a name freezes its unit). Adapters translate their
native names and units into vocabulary forms at ingest; users never see
native forms. Columns ending in the reserved suffixes are
engine-produced companions of a variable and are exempt from vocabulary
validation.
"""
from collections import namedtuple



Variable = namedtuple(
    "Variable", ["name", "unit", "description", "aggregation"]
)

# how hourly values roll up to daily: point-in-time variables average;
# accumulation variables ("sum") add up and are never gap-interpolated
AGGREGATIONS = ("mean", "sum", "min", "max")

VARIABLES = {
    variable.name: variable
    for variable in (
        Variable("temperature", "degC", "Air temperature.", "mean"),
        Variable(
            "dew_point_temperature", "degC", "Dew point temperature.", "mean"
        ),
        Variable("relative_humidity", "%", "Relative humidity.", "mean"),
        Variable("wind_speed", "m/s", "Wind speed.", "mean"),
        Variable(
            "station_level_pressure",
            "hPa",
            "Atmospheric pressure at station level.",
            "mean",
        ),
        Variable("visibility", "km", "Horizontal visibility distance.", "mean"),
        Variable(
            "ghi",
            "W/m2",
            "Global horizontal irradiance.",
            "mean",
        ),
        Variable(
            "clearsky_ghi",
            "W/m2",
            "Computed Fu-Liou clearsky global horizontal irradiance, driven by hourly"
            " aerosol and water-vapor inputs. It is jittery and is not an upper bound on"
            " the all-sky value (cloud enhancement is real), and is not a substitute for"
            " a deterministic clearsky model.",
            "mean",
        ),
        Variable("dni", "W/m2", "Direct normal irradiance.", "mean"),
        Variable(
            "clearsky_dni",
            "W/m2",
            "Computed Fu-Liou clearsky direct normal irradiance, driven by hourly"
            " aerosol and water-vapor inputs. It is jittery and is not an upper bound on"
            " the all-sky value (cloud enhancement is real), and is not a substitute for"
            " a deterministic clearsky model.",
            "mean",
        ),
        Variable(
            "dhi",
            "W/m2",
            "Diffuse horizontal irradiance. ghi equals dhi plus bhi to rounding at high"
            " sun and degrades in the sunrise/sunset hour; no component may be derived"
            " from the other two.",
            "mean",
        ),
        Variable(
            "clearsky_dhi",
            "W/m2",
            "Computed Fu-Liou clearsky diffuse horizontal irradiance, driven by hourly"
            " aerosol and water-vapor inputs. It is jittery and is not an upper bound on"
            " the all-sky value (cloud enhancement is real), and is not a substitute for"
            " a deterministic clearsky model.",
            "mean",
        ),
        Variable(
            "bhi",
            "W/m2",
            "Direct horizontal irradiance. ghi equals dhi plus bhi to rounding at high"
            " sun and degrades in the sunrise/sunset hour; no component may be derived"
            " from the other two.",
            "mean",
        ),
        Variable(
            "clearsky_bhi",
            "W/m2",
            "Computed Fu-Liou clearsky direct horizontal irradiance, driven by hourly"
            " aerosol and water-vapor inputs. It is jittery and is not an upper bound on"
            " the all-sky value (cloud enhancement is real), and is not a substitute for"
            " a deterministic clearsky model.",
            "mean",
        ),
        Variable("longwave_down", "W/m2", "Downwelling longwave irradiance.", "mean"),
        Variable("longwave_up", "W/m2", "Upwelling longwave irradiance.", "mean"),
        Variable(
            "albedo",
            "1",
            "Surface albedo. Undefined at night; nightly gaps are normal, not errors.",
            "mean",
        ),
        Variable(
            "airmass",
            "1",
            "Kasten relative airmass. Not pressure-corrected, and undefined at night.",
            "mean",
        ),
        Variable(
            "aerosol_optical_depth_550",
            "1",
            "Aerosol optical depth at 550 nm.",
            "mean",
        ),
        Variable(
            "aerosol_optical_depth_840",
            "1",
            "Aerosol optical depth at 840 nm.",
            "mean",
        ),
        Variable(
            "snow_cover",
            "1",
            "Fractional snow cover. Undefined over ocean.",
            "mean",
        ),
        Variable("precipitable_water", "cm", "Total precipitable water.", "mean"),
        Variable("cloud_cover", "%", "Cloud cover.", "mean"),
        Variable("specific_humidity", "g/kg", "Specific humidity.", "mean"),
        Variable("skin_temperature", "degC", "Skin temperature.", "mean"),
        Variable(
            "soil_temperature",
            "degC",
            "Top soil layer temperature. Undefined over ocean.",
            "mean",
        ),
        Variable("eastward_wind", "m/s", "Eastward wind component.", "mean"),
        Variable("northward_wind", "m/s", "Northward wind component.", "mean"),
        Variable("surface_roughness", "m", "Surface roughness length.", "mean"),
        Variable(
            "surface_pressure",
            "hPa",
            "Atmospheric pressure at the model topography of the grid cell. This is a"
            " different physical reference from station_level_pressure (tens of hPa"
            " apart in terrain); the two are separate variables and must never be"
            " aliased.",
            "mean",
        ),
        Variable(
            "precipitation",
            "mm",
            "Gauge-bias-corrected precipitation depth.",
            "sum",
        ),
        Variable(
            "snowfall",
            "mm",
            "Snowfall as liquid water equivalent, not accumulated snow depth."
            " Produced independently of precipitation (which is gauge-bias"
            " corrected), so snowfall can exceed precipitation; never"
            " difference the two.",
            "sum",
        ),
    )
}

RESERVED_SUFFIXES = ("_imputed_fraction", "_is_imputed")

_registered_variables = {}


def register_variables(entries):
    """Add external vocabulary entries; called through sources.register.

    All entries are validated before any is added: canonical names are
    reserved, every entry needs a name, unit, and description, and a
    name registered twice must carry an identical definition, so a
    variable's unit is frozen by whichever source registers it first.
    """
    validated = {}
    for entry in entries:
        entry = Variable(*entry)
        if not entry.name or not entry.unit or not entry.description:
            raise ValueError(
                "A variable needs a name, unit, description, and"
                " aggregation, got: {}.".format(tuple(entry))
            )
        if entry.aggregation not in AGGREGATIONS:
            raise ValueError(
                "Unknown aggregation '{}' for '{}'; one of: {}.".format(
                    entry.aggregation, entry.name, ", ".join(AGGREGATIONS)
                )
            )
        if entry.name in VARIABLES:
            raise ValueError(
                "'{}' is canonical; serve it in its canonical unit"
                " ({}).".format(entry.name, VARIABLES[entry.name].unit)
            )
        existing = _registered_variables.get(entry.name) or validated.get(entry.name)
        if existing is not None and existing != entry:
            raise ValueError(
                "'{}' is already registered as {}; definitions must"
                " agree.".format(entry.name, tuple(existing))
            )
        validated[entry.name] = entry
    _registered_variables.update(validated)


def all_variables():
    """The full vocabulary, canonical plus registered, by name."""
    return {**VARIABLES, **_registered_variables}


def valid_variables_or_raise(variables):
    """Raise ValueError when a requested variable is not in the
    vocabulary."""
    known = all_variables()
    unknown = [name for name in variables if name not in known]
    if unknown:
        raise ValueError(
            "Unknown variables: {}. Known variables: {}.".format(
                ", ".join(sorted(unknown)), ", ".join(sorted(known))
            )
        )


def aggregation_for(column):
    """The daily-rollup aggregation for a frame column; engine-produced
    companion columns and anything else outside the vocabulary average."""
    entry = all_variables().get(column)
    if entry is None:
        return "mean"

    return entry.aggregation
