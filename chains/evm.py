"""EVM-compatible chains (BNB Smart Chain, Ethereum, Polygon, ...) via JSON-RPC."""

import re
import time
from decimal import Decimal

from .base import Chain, HistoryUnavailable, Transaction, transfer_direction
from .http import post_json
from .settings import get_setting

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# ERC20/BEP20 function selectors
BALANCE_OF = "0x70a08231"
DECIMALS = "0x313ce567"
SYMBOL = "0x95d89b41"

# Chainlink price feed function selector
LATEST_ROUND_DATA = "0xfeaf968c"

MAX_PRICE_AGE_SECONDS = 3600

NATIVE_DECIMALS = 18
NODEREAL_KEY_NAME = "NODEREAL_API_KEY"
NODEREAL_KEY_PLACEHOLDER = "your_nodereal_api_key_here"
# nr_getAssetTransfers groups results by category, so each one is requested separately
# to find the newest transactions overall.
TRANSFER_CATEGORIES = ("external", "internal", "20")


def _hex_to_int(value):
    return int(value, 16) if value not in (None, "", "0x") else 0


def _token_decimals(value):
    """NodeReal's docs describe this field as hex, but responses contain plain numbers like '18'."""
    try:
        return int(str(value), 0)
    except ValueError:
        return None


def decode_string(hex_result):
    raw = bytes.fromhex(hex_result[2:])
    if len(raw) == 32:  # some old tokens return bytes32 instead of string
        return raw.rstrip(b"\x00").decode(errors="ignore")
    length = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + length].decode(errors="ignore")


class EvmChain(Chain):
    def __init__(self, name, tokens_file, rpc_url, native_usd_feed=None, nodereal_url=None, explorer_tx_url=None):
        super().__init__(name, tokens_file)
        self.rpc_url = rpc_url
        self.native_usd_feed = native_usd_feed  # Chainlink <native coin> / USD feed contract
        self.nodereal_url = nodereal_url  # NodeReal endpoint for history; the API key is added to it
        self.explorer_tx_url = explorer_tx_url

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
            symbol = decode_string(self._call(contract, SYMBOL))
        except Exception:
            symbol = "TOKEN"
        return symbol, decimals

    def native_price_usd(self):
        if self.native_usd_feed is None:
            return None
        return self.chainlink_price(self.native_usd_feed)

    def chainlink_price(self, feed):
        """Read the current price from a Chainlink feed contract on this chain."""
        decimals = int(self._call(feed, DECIMALS), 16)
        # latestRoundData() returns (roundId, answer, startedAt, updatedAt, answeredInRound)
        data = bytes.fromhex(self._call(feed, LATEST_ROUND_DATA)[2:])
        answer = int.from_bytes(data[32:64], "big", signed=True)
        updated_at = int.from_bytes(data[96:128], "big")
        if answer <= 0:
            raise RuntimeError("invalid price from feed")
        if time.time() - updated_at > MAX_PRICE_AGE_SECONDS:
            raise RuntimeError("price feed is out of date")
        return Decimal(answer).scaleb(-decimals)

    def tx_url(self, tx_id):
        return f"{self.explorer_tx_url}{tx_id}" if self.explorer_tx_url else tx_id

    def _fetch_transfers(self, api_key, category, side, address, count):
        """Fetch the newest transfers where address is the sender or receiver (side)."""
        params = {"category": [category], "order": "desc", "maxCount": hex(count), side: address}
        payload = {"jsonrpc": "2.0", "id": 1, "method": "nr_getAssetTransfers", "params": [params]}
        try:
            response = post_json(self.nodereal_url + api_key, payload, timeout=30)
        except Exception as e:
            # The key is part of the URL, so make sure it can never appear in an error message.
            raise RuntimeError(str(e).replace(api_key, "<api key>")) from None
        if "error" in response:
            message = str(response["error"].get("message", response["error"]))
            raise RuntimeError(message.replace(api_key, "<api key>"))
        return response["result"].get("transfers") or []

    def history(self, address, count):
        if self.nodereal_url is None:
            return super().history(address, count)
        api_key = get_setting(NODEREAL_KEY_NAME)
        if not api_key or api_key == NODEREAL_KEY_PLACEHOLDER:
            raise HistoryUnavailable(
                f"transaction history on {self.name} needs a NodeReal API key. "
                f"Add {NODEREAL_KEY_NAME}=<your key> to the .env file."
            )
        listed = {token.contract.lower() for token in self.load_tokens() if token.contract}

        rows = {}
        for category in TRANSFER_CATEGORIES:
            for side in ("fromAddress", "toAddress"):
                for row in self._fetch_transfers(api_key, category, side, address, count):
                    # A transfer to yourself comes back from both sides; keep it once.
                    rows[row["hash"], row["category"], row.get("logIndex"), row.get("traceIndex")] = row

        token_tx_hashes = {row["hash"] for row in rows.values() if row["category"] == "20"}
        transactions = []
        for row in rows.values():
            # A token transfer also appears as a 0 BNB call; keep only the token row.
            is_empty_call = row["category"] == "external" and _hex_to_int(row.get("value")) == 0
            if not (is_empty_call and row["hash"] in token_tx_hashes):
                transactions.append(self._parse_transfer(row, address.lower(), listed))
        transactions.sort(key=lambda tx: tx.timestamp, reverse=True)
        return transactions[:count]

    @staticmethod
    def _parse_transfer(row, address, listed):
        """Convert a NodeReal transfer. address must be lowercase, as NodeReal's addresses are."""
        sender, receiver = row["from"].lower(), row["to"].lower()
        direction = transfer_direction(address, sender, receiver)
        value = _hex_to_int(row.get("value"))

        unlisted = False
        if row["category"] == "20":
            kind = row.get("asset") or row.get("name") or "TOKEN"
            decimals = _token_decimals(row.get("decimal"))
            amount = None if decimals is None else Decimal(value).scaleb(-decimals)
            unlisted = (row.get("contractAddress") or "").lower() not in listed
        elif row["category"] == "external" and value == 0 and direction != "IN":
            kind, amount = "Contract call", None
        else:
            kind, amount = row.get("asset") or "Native coin", Decimal(value).scaleb(-NATIVE_DECIMALS)

        return Transaction(
            timestamp=row["blockTimeStamp"],
            direction=direction,
            kind=kind,
            tx_id=row["hash"],
            amount=amount,
            counterparty=receiver if sender == address else sender,
            success=row.get("receiptsStatus") != 0,
            unlisted=unlisted,
        )
