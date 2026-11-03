#!/usr/bin/env python3
"""Show the current balance of a BEP20 (BNB Smart Chain) address.

Usage:
    python3 bep20_balance.py                      # prompts for an address
    python3 bep20_balance.py 0xYourAddress        # BNB balance
    python3 bep20_balance.py 0xYourAddress 0xTokenContract   # BEP20 token balance

No third-party packages needed; it talks to a public BSC JSON-RPC node.
"""

import json
import re
import ssl
import sys
import urllib.request
from decimal import Decimal

RPC_URL = "https://bsc-dataseed.bnbchain.org"

# Start from the OS certificate store (Windows/Linux), then add certifi's bundle if installed
# (fixes CERTIFICATE_VERIFY_FAILED on macOS python.org builds without dropping system/corporate CAs).
SSL_CTX = ssl.create_default_context()
try:
    import certifi
    SSL_CTX.load_verify_locations(certifi.where())
except ImportError:
    pass

# Avoid UnicodeEncodeError on Windows consoles/redirects when a token symbol has non-ASCII chars.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "bep20-balance/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
        result = json.load(resp)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", result["error"]))
    return result["result"]


def eth_call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


def get_bnb_balance(address):
    wei = int(rpc("eth_getBalance", [address, "latest"]), 16)
    return Decimal(wei) / Decimal(10**18)


def decode_string(hex_result):
    raw = bytes.fromhex(hex_result[2:])
    if len(raw) == 32:  # some old tokens return bytes32 instead of string
        return raw.rstrip(b"\x00").decode(errors="ignore")
    length = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + length].decode(errors="ignore")


def get_token_balance(address, token):
    padded = address[2:].lower().rjust(64, "0")
    raw = int(eth_call(token, "0x70a08231" + padded), 16)  # balanceOf(address)
    decimals = int(eth_call(token, "0x313ce567"), 16)      # decimals()
    try:
        symbol = decode_string(eth_call(token, "0x95d89b41"))  # symbol()
    except Exception:
        symbol = "TOKEN"
    return Decimal(raw) / Decimal(10**decimals), symbol


def main():
    address = sys.argv[1] if len(sys.argv) > 1 else input("Enter BEP20 address: ").strip()
    token = sys.argv[2] if len(sys.argv) > 2 else None

    for label, value in (("address", address), ("token contract", token)):
        if value is not None and not ADDRESS_RE.match(value):
            sys.exit(f"Invalid {label}: {value}")

    try:
        if token:
            balance, symbol = get_token_balance(address, token)
        else:
            balance, symbol = get_bnb_balance(address), "BNB"
    except Exception as e:
        sys.exit(f"Error fetching balance: {e}")

    print(f"Address: {address}")
    print(f"Balance: {balance.normalize():f} {symbol}")


if __name__ == "__main__":
    main()
