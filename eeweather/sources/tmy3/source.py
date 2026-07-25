"""NREL TMY3 typical-year temperatures."""
from ..base import NormalsSource



class TMY3Source(NormalsSource):
    name = "tmy3"

    def _url(self, usaf_id):
        url = (
            "https://storage.googleapis.com/openeemeter-public-resources/"
            "tmy3_archive/{}TYA.CSV".format(usaf_id)
        )

        return url
