"""Point-in-zone lookups against the packaged geography packs."""
import json
from functools import cached_property

from shapely.geometry import Point, shape

from .db import metadata_db_connection_proxy



class _ZoneGeometries(object):
    @cached_property
    def by_system(self):
        proxy = metadata_db_connection_proxy
        conn = proxy.get_connection()
        geometries = {}
        for alias in proxy.geography_aliases:
            for system, zone_id, geometry in conn.execute(
                "select system, zone_id, geometry from {}.zone"
                " order by system, zone_id".format(alias)
            ):
                geometries.setdefault(system, []).append(
                    (zone_id, shape(json.loads(geometry)))
                )

        return geometries


_zone_geometries = _ZoneGeometries()


def zones_at(latitude, longitude):
    """The zone containing a point, by zone system.

    Returns a dict with one entry per zone system in the geography packs;
    the value is None when no zone of that system contains the point.
    """
    point = Point(longitude, latitude)
    zones = {}
    for system, geometries in _zone_geometries.by_system.items():
        zones[system] = None
        for zone_id, geometry in geometries:
            if geometry.contains(point):
                zones[system] = zone_id
                break

    return zones
