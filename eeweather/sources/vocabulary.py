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
