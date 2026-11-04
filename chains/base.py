"""Common interface every chain implements."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

TOKENS_DIR = Path(__file__).resolve().parent.parent / "tokens"

# How many pages to read per history source, to bound requests on wallets full of spam.
MAX_HISTORY_PAGES = 10


class ConfigError(Exception):
    """A problem with a token list file."""


@dataclass
class Token:
    symbol: str
    decimals: int
    contract: Optional[str] = None  # None means the chain's native coin (BNB, ETH, TRX...)
    min_history_amount: Optional[Decimal] = None  # history hides transfers at or below this


class HistoryUnavailable(Exception):
    """This chain can't provide transaction history."""


class HistoryLimitReached(Exception):
    """A history source still had older rows after MAX_HISTORY_PAGES pages."""


@dataclass
class Transaction:
    timestamp: int  # Unix time in seconds
    direction: str  # IN, OUT or SELF
    kind: str  # what moved or happened: "USDT", "TRX", "Contract call"...
    tx_id: str
    amount: Optional[Decimal] = None  # None when the transaction isn't a simple transfer
    counterparty: Optional[str] = None
    success: bool = True
    hidden: bool = False  # filtered out: an unlisted token, or below the token's minimum amount
    is_token_transfer: bool = False
    is_bare_call: bool = False  # a call that's redundant if the same tx has a token transfer
    row_id: Optional[str] = None  # set when a source can return the same row twice


def transfer_direction(address, sender, receiver):
    """Return IN, OUT or SELF from the point of view of address."""
    if sender == receiver:
        return "SELF"
    return "OUT" if sender == address else "IN"


class Chain:
    """Subclass this to add a chain. Implement the four methods that raise NotImplementedError."""

    def __init__(self, name: str, tokens_file: str):
        self.name = name
        self.tokens_path = TOKENS_DIR / tokens_file

    # --- chain-specific -------------------------------------------------
    def is_valid_address(self, address: str) -> bool:
        raise NotImplementedError

    def native_balance_raw(self, address: str) -> int:
        raise NotImplementedError

    def token_balance_raw(self, address: str, contract: str) -> int:
        raise NotImplementedError

    def token_info(self, contract: str) -> tuple[str, int]:
        """Return (symbol, decimals) read from the token contract."""
        raise NotImplementedError

    def native_price_usd(self) -> Optional[Decimal]:
        """Return the native coin's USD price, or None if this chain has no price source."""
        return None

    def history(self, address: str, count: int) -> tuple[list[Transaction], bool]:
        """Return up to count visible transactions, newest first, and whether the search finished."""
        raise HistoryUnavailable(f"transaction history isn't supported on {self.name} yet")

    def contract_key(self, contract: str) -> str:
        """Return a contract address in the form used to compare it."""
        return contract

    def history_token_rules(self) -> dict:
        """Return {contract key: minimum amount or None} for the tokens in the token list."""
        return {
            self.contract_key(token.contract): token.min_history_amount
            for token in self.load_tokens()
            if token.contract
        }

    @staticmethod
    def is_hidden_token(rules: dict, contract: Optional[str], amount: Optional[Decimal]) -> bool:
        """Hide tokens that aren't listed, and listed tokens at or below their minimum amount."""
        if contract not in rules:
            return True
        minimum = rules[contract]
        return minimum is not None and amount is not None and amount <= minimum

    @staticmethod
    def collect_history(sources: list, count: int) -> tuple[list[Transaction], bool]:
        """Merge newest-first sources and return (visible transactions, whether the search finished).

        Pages are only requested when needed, so filtering can't leave fewer than count
        transactions while older ones exist. Put token sources first: on equal timestamps,
        merge keeps source order, so a token row is seen before the same tx's bare call.
        """
        visible, seen_rows, token_tx_ids = [], set(), set()
        try:
            for tx in heapq.merge(*sources, key=lambda tx: -tx.timestamp):
                if tx.row_id is not None:
                    if tx.row_id in seen_rows:
                        continue
                    seen_rows.add(tx.row_id)
                if tx.is_token_transfer:
                    token_tx_ids.add(tx.tx_id)
                if tx.hidden or (tx.is_bare_call and tx.tx_id in token_tx_ids):
                    continue
                visible.append(tx)
                if len(visible) == count:
                    break
        except HistoryLimitReached:
            return visible, False
        return visible, True

    def tx_url(self, tx_id: str) -> str:
        """Return a block explorer link for a transaction."""
        return tx_id

    # --- shared ---------------------------------------------------------
    def balance(self, address: str, token: Token) -> Decimal:
        if token.contract is None:
            raw = self.native_balance_raw(address)
        else:
            raw = self.token_balance_raw(address, token.contract)
        return Decimal(raw).scaleb(-token.decimals)

    def load_tokens(self) -> list[Token]:
        path = self.tokens_path
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except FileNotFoundError:
            raise ConfigError(f"Token list not found: {path}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path}: {e}")

        if not isinstance(entries, list):
            raise ConfigError(f"{path} must contain a JSON list of tokens")

        tokens = []
        for i, entry in enumerate(entries, 1):
            symbol = entry.get("symbol")
            decimals = entry.get("decimals")
            native = entry.get("native", False)
            contract = None if native else entry.get("contract", "")
            if (
                not symbol
                or not isinstance(decimals, int)
                or (not native and not self.is_valid_address(contract))
            ):
                raise ConfigError(
                    f"Bad token #{i} in {path}: needs 'symbol', integer 'decimals', "
                    f"and a valid 'contract' (or \"native\": true)"
                )
            minimum = entry.get("min_history_amount")
            if minimum is not None:
                try:
                    minimum = Decimal(str(minimum))
                except InvalidOperation:
                    raise ConfigError(f"Bad 'min_history_amount' for {symbol} in {path}: {minimum}")
            tokens.append(Token(symbol, decimals, contract, minimum))
        return tokens
