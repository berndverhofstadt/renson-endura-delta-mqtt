"""HTTP client for the Renson Endura Delta local JSON API.

See shared/fields.py for the endpoint documentation and how it was established.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from shared.fields import DANGEROUS

LOGGER = logging.getLogger("renson.client")

# The device requires a wsn ("web service number") query parameter but does not
# care what it is, and returns the full field set every time regardless.
DEFAULT_WSN = "150324488709"


class RensonError(RuntimeError):
    pass


class ReadOnlyFieldError(RensonError):
    """The device answered 400, meaning the field does not accept writes."""


class RensonClient:
    def __init__(self, host, port=80, timeout=8, wsn=DEFAULT_WSN):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.wsn = wsn
        self.base_url = f"http://{host}:{port}"

    def _var_url(self, name, index):
        query = urllib.parse.urlencode({
            "index0": index[0],
            "index1": index[1],
            "index2": index[2],
        })
        # The field name is a path segment containing spaces, so quote it but
        # keep "/" unquoted-safe behaviour off - no field name contains one.
        return f"{self.base_url}/JSON/Vars/{urllib.parse.quote(name, safe='')}?{query}"

    def _request(self, request):
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                raise ReadOnlyFieldError(f"{request.get_full_url()} rejected the write (HTTP 400)") from exc
            raise RensonError(f"HTTP {exc.code} for {request.get_full_url()}") from exc
        except urllib.error.URLError as exc:
            raise RensonError(f"cannot reach {self.host}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RensonError(f"malformed JSON from {request.get_full_url()}") from exc

    def read_all(self):
        """Return {(name, index_tuple): value} for every field the device reports."""
        url = f"{self.base_url}/JSON/ModifiedItems?wsn={self.wsn}"
        payload = self._request(urllib.request.Request(url))
        items = payload.get("ModifiedItems")
        if not isinstance(items, list) or not items:
            raise RensonError("ModifiedItems response contained no items")

        readings = {}
        for item in items:
            try:
                key = (item["Name"], tuple(item["Index"]))
            except (KeyError, TypeError):
                LOGGER.warning("skipping_malformed_item item=%s", item)
                continue
            readings[key] = item.get("Value")
        return readings

    def read_field(self, name, index=(0, 0, 0)):
        return self._request(urllib.request.Request(self._var_url(name, index))).get("Value")

    def write_field(self, name, value, index=(0, 0, 0)):
        """Write a single field and return the value the device echoed back.

        Refuses the fields that latch fan tacho errors even if a caller asks -
        recovering from those needs physical access to the unit.
        """
        if name in DANGEROUS:
            raise RensonError(
                f"refusing to write '{name}': it stops the fans and latches error 35/36, "
                "which needs a power cycle to clear (see shared/fields.py DANGEROUS)"
            )

        request = urllib.request.Request(
            self._var_url(name, index),
            data=json.dumps({"Value": str(value)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        echoed = self._request(request).get("Value")
        LOGGER.info("write_success name=%s requested=%s echoed=%s", name, value, echoed)
        return echoed
