"""The migrate step's GHCN id parsing lives in one helper only."""
import inspect
from pathlib import Path

import pytest

from eeweather.build import migrate, refresh
from eeweather.build.migrate import _country



@pytest.mark.parametrize(
    "ghcn_id, expected",
    [
        ("USW00023152", "US"),
        ("RQC00668814", "PR"),
        ("GME00099902", "DE"),
        ("ASN00099901", "AU"),
        ("ZZUNKNOWN01", None),
    ],
)
def test_country_maps_fips_prefix_to_iso(ghcn_id, expected):
    assert _country(ghcn_id) == expected


def test_country_is_sole_id_slice_site_in_migrate():
    source = Path(migrate.__file__).read_text()
    helper_source = inspect.getsource(_country)

    assert source.count("[:2]") == 1
    assert "[:2]" in helper_source


def test_refresh_does_not_parse_station_ids():
    source = Path(refresh.__file__).read_text()

    assert "[:2]" not in source
    assert "FIPS_TO_ISO" not in source
