"""External identifier translation over the station_identifier table."""
from ..exceptions import AmbiguousIdentifierError, UnrecognizedStationError
from .db import metadata_db_connection_proxy



def translate(ids, from_namespace, to_namespace):
    """Translate external ids between identifier systems.

    Parameters
    ----------
    ids : iterable of str
        External ids in ``from_namespace``. Ids with no mapping are absent
        from the result.
    from_namespace, to_namespace : str
        Identifier systems, e.g. ``'usaf'``, ``'ghcn'``, ``'wban'``,
        ``'icao'``.

    Returns
    -------
    dict of str to tuple of str
        Target ids keyed by input id. Values are always tuples; mappings
        can be one-to-many in either direction.
    """
    ids = list(dict.fromkeys(ids))
    conn = metadata_db_connection_proxy.get_connection()
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        """
        select src.external_id, dst.external_id
        from station_identifier as src
        join station_identifier as dst on src.station_id = dst.station_id
        where src.namespace = ? and dst.namespace = ?
          and src.external_id in ({})
        order by src.external_id, dst.external_id
        """.format(placeholders),
        [from_namespace, to_namespace] + ids,
    ).fetchall()

    mapping = {}
    for source_id, target_id in rows:
        mapping.setdefault(source_id, [])
        if target_id not in mapping[source_id]:
            mapping[source_id].append(target_id)
    mapping = {key: tuple(values) for key, values in mapping.items()}

    return mapping


_NORMALIZERS = {
    "icao": lambda v: v.strip().upper(),
    "wban": lambda v: v.strip().zfill(5),
    "usaf": lambda v: v.strip().zfill(6),
    "wmo": lambda v: v.strip().zfill(5),
}


def resolve_station(namespace, external_id):
    """The registry station id an external id maps to.

    Ids are normalized to the registry's uniform forms (icao uppercased;
    wban/wmo zero-padded to 5, usaf to 6). When the id maps to several
    stations, the mapping marked recent wins; with no recent mapping,
    AmbiguousIdentifierError is raised.
    """
    if namespace in _NORMALIZERS:
        external_id = _NORMALIZERS[namespace](external_id)
    conn = metadata_db_connection_proxy.get_connection()
    rows = conn.execute(
        "select station_id, recent from station_identifier"
        " where namespace = ? and external_id = ?"
        " order by station_id",
        (namespace, external_id),
    ).fetchall()
    if not rows:
        raise UnrecognizedStationError(external_id)
    if len(rows) == 1:
        return rows[0][0]

    recent = [station_id for station_id, is_recent in rows if is_recent]
    if len(recent) == 1:
        return recent[0]

    raise AmbiguousIdentifierError(
        namespace, external_id, [station_id for station_id, _ in rows]
    )
