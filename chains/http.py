"""Shared HTTP helper used by every chain module."""

import json
import ssl
import urllib.request

# Start from the OS certificate store (Windows/Linux), then add certifi's bundle if installed
# (fixes CERTIFICATE_VERIFY_FAILED on macOS python.org builds without dropping system/corporate CAs).
SSL_CTX = ssl.create_default_context()
try:
    import certifi
    SSL_CTX.load_verify_locations(certifi.where())
except ImportError:
    pass


def post_json(url, payload, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "tx-scanner/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.load(resp)
