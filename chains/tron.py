"""Tron (TRX and TRC20 tokens) via a node's HTTP API."""

import hashlib
from decimal import Decimal
from urllib.parse import urlencode

from .base import Chain, Transaction, transfer_direction
from .evm import decode_string
from .http import get_json, post_json

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAINNET_PREFIX = 0x41
TRX_DECIMALS = 6

# Normal nodes don't index transactions by address, so history comes from TronGrid's API.
HISTORY_API_URL = "https://api.trongrid.io/v1/accounts"
EXPLORER_TX_URL = "https://tronscan.org/#/transaction/"


def _hex_to_address(hex_address):
    """Encode a 41... hex address as a base58check T... address."""
    payload = bytes.fromhex(hex_address)
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    return encoded


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

    def tx_url(self, tx_id):
        return EXPLORER_TX_URL + tx_id

    def _fetch_history(self, path, count, **extra):
        query = urlencode({"limit": count, "only_confirmed": "true", "order_by": "block_timestamp,desc", **extra})
        response = get_json(f"{HISTORY_API_URL}/{path}?{query}")
        if not response.get("success"):
            raise RuntimeError(response.get("error", "TronGrid request failed"))
        return response.get("data", [])

    def history(self, address, count):
        listed = {token.contract for token in self.load_tokens()}
        token_rows = self._fetch_history(f"{address}/transactions/trc20", count)
        # search_internal=false leaves out TRX moved by contracts, which has a different format.
        native_rows = self._fetch_history(f"{address}/transactions", count, search_internal="false")

        transactions = [self._parse_token_transfer(row, address, listed) for row in token_rows]
        # A token transfer also appears as a plain contract call; keep only the token row.
        token_tx_ids = {row["transaction_id"] for row in token_rows}
        transactions += [
            self._parse_native(row, address) for row in native_rows if row["txID"] not in token_tx_ids
        ]
        transactions.sort(key=lambda tx: tx.timestamp, reverse=True)
        return transactions[:count]

    @staticmethod
    def _parse_token_transfer(row, address, listed):
        info = row.get("token_info", {})
        sender, receiver = row["from"], row["to"]
        symbol = info.get("symbol", "TOKEN")
        return Transaction(
            timestamp=row["block_timestamp"] // 1000,
            direction=transfer_direction(address, sender, receiver),
            # An Approval's amount is a spending allowance, not money moved, so label it clearly.
            kind=symbol if row.get("type") == "Transfer" else f"{symbol} {row.get('type')}",
            tx_id=row["transaction_id"],
            amount=Decimal(row["value"]).scaleb(-info.get("decimals", 0)),
            counterparty=receiver if sender == address else sender,
            unlisted=info.get("address") not in listed,
        )

    @staticmethod
    def _parse_native(row, address):
        contract = row["raw_data"]["contract"][0]
        contract_type = contract["type"]
        value = contract["parameter"]["value"]
        sender = _hex_to_address(value["owner_address"])
        target = value.get("to_address") or value.get("receiver_address") or value.get("contract_address")
        receiver = _hex_to_address(target) if target else None

        amount, unlisted = None, False
        if contract_type == "TransferContract":
            kind, amount = "TRX", Decimal(value["amount"]).scaleb(-TRX_DECIMALS)
        elif contract_type == "TransferAssetContract":
            # TRC10 token: its decimals aren't in the response, so this is the raw amount.
            kind, amount, unlisted = f"TRC10 #{value['asset_name']}", Decimal(value["amount"]), True
        elif contract_type == "TriggerSmartContract":
            kind = "Contract call"
        else:
            kind = contract_type[: -len("Contract")] if contract_type.endswith("Contract") else contract_type

        status = (row.get("ret") or [{}])[0].get("contractRet")
        return Transaction(
            timestamp=row["block_timestamp"] // 1000,
            direction=transfer_direction(address, sender, receiver),
            kind=kind,
            tx_id=row["txID"],
            amount=amount,
            counterparty=receiver if sender == address else sender,
            success=status in (None, "SUCCESS"),
            unlisted=unlisted,
        )
