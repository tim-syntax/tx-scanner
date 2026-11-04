"""Tron (TRX and TRC20 tokens) via a node's HTTP API."""

import hashlib

from .base import Chain
from .evm import decode_string
from .http import post_json

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAINNET_PREFIX = 0x41


def _address_to_bytes(address):
    """Decode a base58check T... address to its 20-byte hash. Raises ValueError if invalid."""
    number = 0
    for char in address:
        number = number * 58 + BASE58_ALPHABET.index(char)
    try:
        raw = number.to_bytes(25, "big")
    except OverflowError:
        raise ValueError("address too long")
    payload, checksum = raw[:21], raw[21:]
    if payload[0] != MAINNET_PREFIX:
        raise ValueError("not a Tron mainnet address")
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        raise ValueError("bad checksum")
    return payload[1:]


class TronChain(Chain):
    def __init__(self, name, tokens_file, api_url, native_usd_price=None):
        super().__init__(name, tokens_file)
        self.api_url = api_url
        self.native_usd_price = native_usd_price  # callable returning the TRX price in USD

    def _call(self, contract, function, owner=None, parameter=""):
        """Read from a TRC20 contract and return the result as a hex string."""
        result = post_json(
            f"{self.api_url}/wallet/triggerconstantcontract",
            {
                "owner_address": owner or contract,
                "contract_address": contract,
                "function_selector": function,
                "parameter": parameter,
                "visible": True,
            },
        )
        values = result.get("constant_result") or [""]
        if not result.get("result", {}).get("result") or not values[0]:
            raise RuntimeError("contract call failed (is this a TRC20 contract?)")
        return values[0]

    def is_valid_address(self, address):
        if not isinstance(address, str) or not address:
            return False
        try:
            _address_to_bytes(address)
        except ValueError:
            return False
        return True

    def native_balance_raw(self, address):
        account = post_json(f"{self.api_url}/wallet/getaccount", {"address": address, "visible": True})
        return account.get("balance", 0)  # the field is missing when the balance is 0

    def token_balance_raw(self, address, contract):
        parameter = _address_to_bytes(address).rjust(32, b"\x00").hex()
        return int(self._call(contract, "balanceOf(address)", owner=address, parameter=parameter), 16)

    def token_info(self, contract):
        decimals = int(self._call(contract, "decimals()"), 16)
        try:
            symbol = decode_string("0x" + self._call(contract, "symbol()"))
        except Exception:
            symbol = "TOKEN"
        return symbol, decimals

    def native_price_usd(self):
        return self.native_usd_price() if self.native_usd_price else None
