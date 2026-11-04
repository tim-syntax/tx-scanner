"""Shared HTTP helper used by every chain module."""

import json
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = "tx-scanner/1.0"
RETRY_DELAYS_SECONDS = (1, 2, 4)

# Start from the OS certificate store (Windows/Linux), then add certifi's bundle if installed
# (fixes CERTIFICATE_VERIFY_FAILED on macOS python.org builds without dropping system/corporate CAs).
SSL_CTX = ssl.create_default_context()
try:
    import certifi
    SSL_CTX.load_verify_locations(certifi.where())
except ImportError:
    pass


def _send(req, timeout):
    """Send a request, waiting and retrying if the server says we're rate-limited (HTTP 429)."""
    for delay in RETRY_DELAYS_SECONDS:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(delay)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.load(resp)


def post_json(url, payload, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    return _send(req, timeout)


def get_json(url, timeout=15):
    return _send(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout)
