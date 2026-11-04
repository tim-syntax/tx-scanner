"""Common interface every chain implements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

TOKENS_DIR = Path(__file__).resolve().parent.parent / "tokens"


class ConfigError(Exception):
    """A problem with a token list file."""


@dataclass
class Token:
    symbol: str
    decimals: int
    contract: Optional[str] = None  # None means the chain's native coin (BNB, ETH, TRX...)


class HistoryUnavailable(Exception):
    """This chain can't provide transaction history."""


@dataclass
class Transaction:
    timestamp: int  # Unix time in seconds
    direction: str  # IN, OUT or SELF
    kind: str  # what moved or happened: "USDT", "TRX", "Contract call"...
    tx_id: str
    amount: Optional[Decimal] = None  # None when the transaction isn't a simple transfer
    counterparty: Optional[str] = None
    success: bool = True
    unlisted: bool = False  # a token that isn't in this chain's token list, so possibly fake


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

    def history(self, address: str, count: int) -> list[Transaction]:
        """Return up to count transactions, newest first."""
        raise HistoryUnavailable(f"transaction history isn't supported on {self.name} yet")

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
            tokens.append(Token(symbol, decimals, contract))
        return tokens
