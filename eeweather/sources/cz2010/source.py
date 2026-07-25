"""California Energy Commission CZ2010 typical-year temperatures."""
from ..base import NormalsSource



class CZ2010Source(NormalsSource):
    name = "cz2010"

    def _url(self, usaf_id):
        url = "https://storage.googleapis.com/oee-cz2010/csv/{}_CZ2010.CSV".format(
            usaf_id
        )

        return url
