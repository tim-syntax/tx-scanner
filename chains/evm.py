"""EVM-compatible chains (BNB Smart Chain, Ethereum, Polygon, ...) via JSON-RPC."""

import re

from .base import Chain
from .http import post_json

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# ERC20/BEP20 function selectors
BALANCE_OF = "0x70a08231"
DECIMALS = "0x313ce567"
SYMBOL = "0x95d89b41"


def _decode_string(hex_result):
    raw = bytes.fromhex(hex_result[2:])
    if len(raw) == 32:  # some old tokens return bytes32 instead of string
        return raw.rstrip(b"\x00").decode(errors="ignore")
    length = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + length].decode(errors="ignore")


class EvmChain(Chain):
    def __init__(self, name, tokens_file, rpc_url):
        super().__init__(name, tokens_file)
        self.rpc_url = rpc_url

    def _rpc(self, method, params):
        result = post_json(self.rpc_url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in result:
            raise RuntimeError(result["error"].get("message", result["error"]))
        return result["result"]

    def _call(self, to, data):
        return self._rpc("eth_call", [{"to": to, "data": data}, "latest"])

    def is_valid_address(self, address):
        return bool(address) and bool(ADDRESS_RE.match(address))

    def native_balance_raw(self, address):
        return int(self._rpc("eth_getBalance", [address, "latest"]), 16)

    def token_balance_raw(self, address, contract):
        padded = address[2:].lower().rjust(64, "0")
        return int(self._call(contract, BALANCE_OF + padded), 16)

    def token_info(self, contract):
        decimals = int(self._call(contract, DECIMALS), 16)
        try:
            symbol = _decode_string(self._call(contract, SYMBOL))
        except Exception:
            symbol = "TOKEN"
        return symbol, decimals
