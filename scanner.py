"""Wallet checks shared by the command line (scan.py) and the web app (api/index.py).

Functions here return plain dicts (strings, numbers, booleans) so the web app can send them
as JSON and the command line can print them. Problems are raised as ScanError with a message
that can be shown to the user as is.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from chains import CHAINS, ConfigError, HistoryUnavailable, Token, detect_chain

DEFAULT_VIEW = 10
MAX_VIEW = 200
UNFINISHED_NOTE = "Stopped searching to limit requests, so older transactions may exist."
MAX_PARALLEL_REQUESTS = 8


class ScanError(Exception):
    """A problem with the input or setup, with a message meant for the user."""


class UpstreamError(ScanError):
    """A node or API the scanner depends on failed."""


def safe_text(text):
    """Token names are chosen by whoever created the token, so strip control characters."""
    return "".join(char if char.isprintable() else "?" for char in text)


def format_amount(amount):
    return f"{amount.normalize():f}"


def time_ago(timestamp, now):
    """Describe how long ago a Unix timestamp was, e.g. '12 min ago' or '3 h 5 min ago'."""
    minutes = max(0, int(now - timestamp)) // 60  # max: a slow local clock could give a negative age
    if minutes < 1:
        return "just now"
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} d {hours} h ago" if hours else f"{days} d ago"
    if hours:
        return f"{hours} h {minutes} min ago" if minutes else f"{hours} h ago"
    return f"{minutes} min ago"


def chain_key(chain):
    """Return the CHAINS key ('bsc', 'tron', ...) of a chain object."""
    for key, candidate in CHAINS.items():
        if candidate is chain:
            return key
    raise KeyError(chain.name)


def get_chain(key):
    chain = CHAINS.get(key.strip().lower())
    if chain is None:
        raise ScanError(f"unknown chain '{key}'. Supported: {', '.join(CHAINS)}")
    return chain


def resolve_chain(address, chain=None):
    """Return the chain to use for address: the given one, or the one detected from the address."""
    address = (address or "").strip()
    if not address:
        raise ScanError("enter a wallet address")
    if chain is None:
        chain = detect_chain(address)
        if chain is None:
            raise ScanError(f"not a valid address on any supported chain ({', '.join(CHAINS)}): {address}")
    if not chain.is_valid_address(address):
        raise ScanError(f"invalid {chain.name} address: {address}")
    return chain


def load_tokens(chain):
    try:
        return chain.load_tokens()
    except ConfigError as e:
        raise ScanError(str(e))


def parse_list(value, count):
    """'1,3,4' -> [1, 3, 4], each between 1 and count."""
    numbers = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= count:
            raise ScanError(f"invalid token number '{part}'. Use numbers from 1 to {count}.")
        if int(part) not in numbers:
            numbers.append(int(part))
    if not numbers:
        raise ScanError("no token numbers given. Example: 1,3,4")
    return numbers


def parse_view(value):
    value = str(value).strip()
    if not value.isdigit() or not 1 <= int(value) <= MAX_VIEW:
        raise ScanError(f"invalid number of transactions '{value}'. Use a number from 1 to {MAX_VIEW}.")
    return int(value)


def _select_tokens(chain, numbers, contract):
    """Return [(number or None, Token)] for the requested tokens."""
    if contract and numbers:
        raise ScanError("choose tokens from the list or enter one token contract, not both")
    if contract:
        contract = contract.strip()
        if not chain.is_valid_address(contract):
            raise ScanError(f"invalid token contract: {contract}")
        try:
            symbol, decimals = chain.token_info(contract)
        except Exception as e:
            raise UpstreamError(f"could not read token contract: {e}")
        return [(None, Token(safe_text(symbol), decimals, contract))]

    tokens = load_tokens(chain)
    for number in numbers or ():
        if not 1 <= number <= len(tokens):
            raise ScanError(f"invalid token number '{number}'. Use numbers from 1 to {len(tokens)}.")
    numbers = numbers or range(1, len(tokens) + 1)
    return [(n, tokens[n - 1]) for n in numbers]


def _native_price(chain):
    """Return (price or None, error message or None)."""
    try:
        return chain.native_price_usd(), None
    except Exception as e:
        return None, str(e)


def get_assets(chain, address, numbers=None, contract=None):
    """Return the balances of a wallet.

    numbers picks tokens from the chain's token list (1-based); contract checks one token
    that may not be listed. With neither, every token in the list is checked.
    """
    selected = _select_tokens(chain, numbers, contract)
    has_native = any(token.contract is None for _, token in selected)

    def fetch(token):
        try:
            return chain.balance(address, token), None
        except Exception as e:
            return None, str(e)

    # Each balance is a separate request, so send them at the same time.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
        price_job = pool.submit(_native_price, chain) if has_native else None
        results = list(pool.map(fetch, [token for _, token in selected]))
        price, price_error = price_job.result() if price_job else (None, None)

    balances = []
    for (number, token), (balance, error) in zip(selected, results):
        entry = {
            "number": number,
            "symbol": token.symbol,
            "contract": token.contract,
            "native": token.contract is None,
            "amount": None if balance is None else format_amount(balance),
            "error": error,
            "usd": None,
            "usd_error": None,
        }
        if token.contract is None and balance is not None:
            if price_error:
                entry["usd_error"] = price_error
            elif price is not None:
                entry["usd"] = f"{balance * price:.2f}"
        balances.append(entry)

    return {"chain": chain_key(chain), "chain_name": chain.name, "address": address, "balances": balances}


def get_history(chain, address, count=DEFAULT_VIEW):
    """Return the latest count transactions of a wallet, newest first."""
    try:
        transactions, finished = chain.history(address, count)
    except (ConfigError, HistoryUnavailable) as e:
        raise ScanError(str(e))
    except Exception as e:
        raise UpstreamError(f"could not fetch transaction history: {e}")

    now = time.time()
    rows = [
        {
            "timestamp": tx.timestamp,
            "time_utc": datetime.fromtimestamp(tx.timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "age": time_ago(tx.timestamp, now),
            "direction": tx.direction,
            "amount": None if tx.amount is None else format_amount(tx.amount),
            "kind": safe_text(tx.kind),
            "counterparty": tx.counterparty,
            "success": tx.success,
            "tx_id": tx.tx_id,
            "url": chain.tx_url(tx.tx_id),
        }
        for tx in transactions
    ]
    return {
        "chain": chain_key(chain),
        "chain_name": chain.name,
        "address": address,
        "transactions": rows,
        "finished": finished,
        "note": None if finished else UNFINISHED_NOTE,
    }
