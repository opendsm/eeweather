"""Station metadata assembled from the crosswalk and source catalogs."""
from ..exceptions import UnrecognizedStationError
from .db import metadata_db_connection_proxy



def get_station_metadata(station_id):
    """Registry metadata for a station.

    Identity comes from the crosswalk; facts (name, coordinates,
    elevation, country, subdivision), zone assignments, and the quality
    rating come from the first registered source catalog that lists the
    station; first/last inventory years come from every source that
    keeps an observation inventory.
    """
    proxy = metadata_db_connection_proxy
    conn = proxy.get_connection()

    ids = {}
    for namespace, external_id in conn.execute(
        "select namespace, external_id from station_identifier"
        " where station_id = ? order by namespace, external_id",
        (station_id,),
    ):
        ids.setdefault(namespace, []).append(external_id)
    if not ids:
        raise UnrecognizedStationError(station_id)

    metadata = {"station_id": station_id, "ids": ids}
    for alias in proxy.catalogs:
        cur = conn.cursor()
        cur.execute(
            "select * from {}.stations where station_id = ?".format(alias),
            (station_id,),
        )
        row = cur.fetchone()
        if row is None:
            continue
        for column, value in zip(cur.description, row):
            metadata.setdefault(column[0], value)
        metadata.setdefault(
            "zones",
            dict(
                conn.execute(
                    "select system, zone_id from {}.station_zone"
                    " where station_id = ?".format(alias),
                    (station_id,),
                ).fetchall()
            ),
        )
    metadata.setdefault("zones", {})

    for alias in proxy.quality_sources:
        row = conn.execute(
            "select quality from {}.quality where station_id = ?".format(alias),
            (station_id,),
        ).fetchone()
        if row is not None:
            metadata.setdefault("quality", row[0])
    metadata.setdefault("quality", None)

    metadata["inventory_years"] = {}
    for alias in proxy.inventory_sources:
        row = conn.execute(
            "select min(year), max(year) from {}.inventory"
            " where station_id = ?".format(alias),
            (station_id,),
        ).fetchone()
        if row[0] is not None:
            metadata["inventory_years"][alias] = (row[0], row[1])

    return metadata
