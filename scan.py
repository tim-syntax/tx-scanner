#!/usr/bin/env python3
"""Show wallet balances and transaction history (BNB Smart Chain and Tron; more chains via chains/).

Usage:
    py scan.py <address>                     all tokens in the chain's token list
    py scan.py <address> list=1,3,4          only tokens #1, #3 and #4 from that list
    py scan.py <address> token=<contract>    one token that isn't in the list
    py scan.py <address> mode=history        latest 10 transactions
    py scan.py <address> mode=history view=20    latest 20 transactions (up to 200)
    py scan.py <address> chain=tron          pick the chain (default: detected from the address)
    py scan.py                               asks for the address

Token numbers are shown next to each balance in the default output.
"""

import sys
import time
from datetime import datetime, timezone

from chains import CHAINS, ConfigError, HistoryUnavailable, Token, detect_chain

OPTIONS = ("list", "token", "chain", "mode", "view")
MODES = ("default", "history")
DEFAULT_VIEW = 10
MAX_VIEW = 200

# Avoid UnicodeEncodeError on Windows consoles/redirects when a token symbol has non-ASCII chars.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


def fail(message):
    sys.exit(f"Error: {message}")


def parse_args(argv):
    address, options = None, {}
    for arg in argv:
        if arg in ("-h", "--help", "help"):
            print(__doc__)
            sys.exit(0)
        if "=" in arg:
            key, value = arg.split("=", 1)
            key = key.strip().lower()
            if key not in OPTIONS:
                fail(f"unknown option '{key}'. Valid options: {', '.join(OPTIONS)}")
            options[key] = value.strip()
        elif "list" in options and arg.replace(",", "").strip().isdigit():
            # PowerShell splits unquoted list=1,3,4 into 'list=1' '3' '4' - join them back.
            options["list"] += "," + arg.strip()
        elif address is None:
            address = arg.strip()
        else:
            fail(f"unexpected argument '{arg}'. Run 'py scan.py help' for usage.")
    return address, options


def parse_list(value, count):
    """'1,3,4' -> [1, 3, 4], each between 1 and count."""
    numbers = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= count:
            fail(f"invalid token number '{part}' in list=. Use numbers from 1 to {count}.")
        if int(part) not in numbers:
            numbers.append(int(part))
    if not numbers:
        fail("list= is empty. Example: list=1,3,4")
    return numbers


def parse_view(value):
    if not value.isdigit() or not 1 <= int(value) <= MAX_VIEW:
        fail(f"invalid view '{value}'. Use a number from 1 to {MAX_VIEW}.")
    return int(value)


def safe_text(text):
    """Token names are chosen by whoever created the token, so strip terminal control characters."""
    return "".join(char if char.isprintable() else "?" for char in text)


def usd_suffix(chain, balance):
    """' (4.63 USD)' for a native coin balance, or '' if the chain has no price source."""
    try:
        price = chain.native_price_usd()
    except Exception as e:
        return f" (USD unavailable: {e})"
    if price is None:
        return ""
    return f" ({balance * price:,.2f} USD)"


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


def show_assets(chain, address, options):
    if "token" in options and "list" in options:
        fail("use either list= or token=, not both")

    if "token" in options:
        contract = options["token"]
        if not chain.is_valid_address(contract):
            fail(f"invalid token contract: {contract}")
        try:
            symbol, decimals = chain.token_info(contract)
        except Exception as e:
            fail(f"could not read token contract: {e}")
        selected = [(None, Token(safe_text(symbol), decimals, contract))]
    else:
        try:
            tokens = chain.load_tokens()
        except ConfigError as e:
            fail(str(e))
        numbers = parse_list(options["list"], len(tokens)) if "list" in options else range(1, len(tokens) + 1)
        selected = [(n, tokens[n - 1]) for n in numbers]

    print(f"Chain:   {chain.name}")
    print(f"Address: {address}")
    width = max(len(t.symbol) for _, t in selected)
    for number, token in selected:
        label = f"{number:>3}. " if number is not None else "     "
        try:
            balance = chain.balance(address, token)
            amount = f"{balance.normalize():f}"
            if token.contract is None:
                amount += usd_suffix(chain, balance)
        except Exception as e:
            amount = f"error: {e}"
        print(f"{label}{token.symbol:<{width}}  {amount}")


def show_history(chain, address, options):
    for option in ("list", "token"):
        if option in options:
            fail(f"{option}= only works with mode=default")
    view = parse_view(options["view"]) if "view" in options else DEFAULT_VIEW

    try:
        transactions, finished = chain.history(address, view)
    except (ConfigError, HistoryUnavailable) as e:
        fail(str(e))
    except Exception as e:
        fail(f"could not fetch transaction history: {e}")

    print(f"Chain:   {chain.name}")
    print(f"Address: {address}")
    unfinished_note = "Stopped searching to limit requests, so older transactions may exist."
    if not transactions:
        print("No transactions found." if finished else f"No transactions found. {unfinished_note}")
        return
    print(f"Latest {len(transactions)} transactions (times in UTC):")

    rows = [
        (f"{tx.amount.normalize():f}" if tx.amount is not None else "", safe_text(tx.kind))
        for tx in transactions
    ]
    amount_width = max(len(amount) for amount, _ in rows)
    kind_width = max(len(kind) for _, kind in rows)
    now = time.time()
    ages = [f"({time_ago(tx.timestamp, now)})" for tx in transactions]
    age_width = max(len(age) for age in ages)
    for number, (tx, (amount, kind), age) in enumerate(zip(transactions, rows, ages), 1):
        when = datetime.fromtimestamp(tx.timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        when = f"{when} {age:<{age_width}}"
        preposition = "from" if tx.direction == "IN" else "to"
        party = f"{preposition} {tx.counterparty}" if tx.counterparty else ""
        flags = "  FAILED" if not tx.success else ""
        print(f"{number:>3}. {when}  {tx.direction:<4} {amount:>{amount_width}}  {kind:<{kind_width}}  {party}{flags}")
        print(f"     {chain.tx_url(tx.tx_id)}")

    if not finished:
        print(f"\n{unfinished_note}")


def main():
    address, options = parse_args(sys.argv[1:])

    mode = options.get("mode", "default").lower()
    if mode not in MODES:
        fail(f"unknown mode '{mode}'. Valid modes: {', '.join(MODES)}")
    if mode == "default" and "view" in options:
        fail("view= only works with mode=history")

    chain = None
    if "chain" in options:
        chain_key = options["chain"].lower()
        chain = CHAINS.get(chain_key)
        if chain is None:
            fail(f"unknown chain '{chain_key}'. Supported: {', '.join(CHAINS)}")

    if address is None:
        address = input(f"Enter {chain.name if chain else 'wallet'} address: ").strip()
    if chain is None:
        chain = detect_chain(address)
        if chain is None:
            fail(f"not a valid address on any supported chain ({', '.join(CHAINS)}): {address}")
    if not chain.is_valid_address(address):
        fail(f"invalid {chain.name} address: {address}")

    if mode == "history":
        show_history(chain, address, options)
    else:
        show_assets(chain, address, options)


if __name__ == "__main__":
    main()
