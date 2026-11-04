"""EVM-compatible chains (BNB Smart Chain, Ethereum, Polygon, ...) via JSON-RPC."""

import re
import time
from decimal import Decimal

from .base import (
    MAX_HISTORY_PAGES,
    Chain,
    HistoryLimitReached,
    HistoryUnavailable,
    Transaction,
    transfer_direction,
)
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
HISTORY_PAGE_SIZE = 100
# nr_getAssetTransfers groups results by category, so each one is requested separately
# to find the newest transactions overall. Tokens go first: see Chain.collect_history.
TRANSFER_CATEGORIES = ("20", "external", "internal")


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

    def contract_key(self, contract):
        return contract.lower()  # EVM addresses aren't case-sensitive

    def _transfer_rows(self, api_key, category, side, address):
        """Yield transfers newest first where address is the sender or receiver (side).

        Further pages are requested only as they're needed.
        """
        params = {"category": [category], "order": "desc", "maxCount": hex(HISTORY_PAGE_SIZE), side: address}
        for _ in range(MAX_HISTORY_PAGES):
            payload = {"jsonrpc": "2.0", "id": 1, "method": "nr_getAssetTransfers", "params": [params]}
            try:
                response = post_json(self.nodereal_url + api_key, payload, timeout=30)
            except Exception as e:
                # The key is part of the URL, so make sure it can never appear in an error message.
                raise RuntimeError(str(e).replace(api_key, "<api key>")) from None
            if "error" in response:
                message = str(response["error"].get("message", response["error"]))
                raise RuntimeError(message.replace(api_key, "<api key>"))
            transfers = response["result"].get("transfers") or []
            yield from transfers
            page_key = response["result"].get("pageKey")
            if not transfers or not page_key:
                return
            params["pageKey"] = page_key
        raise HistoryLimitReached()

    def history(self, address, count):
        if self.nodereal_url is None:
            return super().history(address, count)
        api_key = get_setting(NODEREAL_KEY_NAME)
        if not api_key or api_key == NODEREAL_KEY_PLACEHOLDER:
            raise HistoryUnavailable(
                f"transaction history on {self.name} needs a NodeReal API key. "
                f"Add {NODEREAL_KEY_NAME}=<your key> to the .env file."
            )
        rules = self.history_token_rules()
        sources = [
            (
                self._parse_transfer(row, address.lower(), rules)
                for row in self._transfer_rows(api_key, category, side, address)
            )
            for category in TRANSFER_CATEGORIES
            for side in ("fromAddress", "toAddress")
        ]
        return self.collect_history(sources, count)

    def _parse_transfer(self, row, address, rules):
        """Convert a NodeReal transfer. address must be lowercase, as NodeReal's addresses are."""
        sender, receiver = row["from"].lower(), row["to"].lower()
        direction = transfer_direction(address, sender, receiver)
        value = _hex_to_int(row.get("value"))
        is_token = row["category"] == "20"

        hidden = False
        if is_token:
            kind = row.get("asset") or row.get("name") or "TOKEN"
            decimals = _token_decimals(row.get("decimal"))
            amount = None if decimals is None else Decimal(value).scaleb(-decimals)
            hidden = self.is_hidden_token(rules, self.contract_key(row.get("contractAddress") or ""), amount)
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
            hidden=hidden,
            is_token_transfer=is_token,
            # A token transfer also appears as a 0 BNB call; only the token row is kept.
            is_bare_call=row["category"] == "external" and value == 0,
            # A transfer to yourself comes back from both sides; it's kept once.
            row_id=f"{row['hash']}:{row['category']}:{row.get('logIndex')}:{row.get('traceIndex')}",
        )
