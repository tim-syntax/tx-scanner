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
from decimal import Decimal

from scanner import (
    DEFAULT_VIEW,
    ScanError,
    get_assets,
    get_chain,
    get_history,
    load_tokens,
    parse_list,
    parse_view,
    resolve_chain,
)

OPTIONS = ("list", "token", "chain", "mode", "view")
MODES = ("default", "history")

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


def show_assets(chain, address, options):
    if "token" in options and "list" in options:
        fail("use either list= or token=, not both")
    numbers = parse_list(options["list"], len(load_tokens(chain))) if "list" in options else None
    result = get_assets(chain, address, numbers=numbers, contract=options.get("token"))

    print(f"Chain:   {result['chain_name']}")
    print(f"Address: {address}")
    balances = result["balances"]
    width = max(len(entry["symbol"]) for entry in balances)
    for entry in balances:
        label = f"{entry['number']:>3}. " if entry["number"] is not None else "     "
        if entry["error"]:
            amount = f"error: {entry['error']}"
        else:
            amount = entry["amount"]
            if entry["usd_error"]:
                amount += f" (USD unavailable: {entry['usd_error']})"
            elif entry["usd"] is not None:
                amount += f" ({Decimal(entry['usd']):,.2f} USD)"
        print(f"{label}{entry['symbol']:<{width}}  {amount}")


def show_history(chain, address, options):
    for option in ("list", "token"):
        if option in options:
            fail(f"{option}= only works with mode=default")
    result = get_history(chain, address, parse_view(options["view"]) if "view" in options else DEFAULT_VIEW)

    print(f"Chain:   {result['chain_name']}")
    print(f"Address: {address}")
    transactions = result["transactions"]
    if not transactions:
        print("No transactions found." if result["finished"] else f"No transactions found. {result['note']}")
        return
    print(f"Latest {len(transactions)} transactions (times in UTC):")

    amounts = [tx["amount"] or "" for tx in transactions]
    amount_width = max(len(amount) for amount in amounts)
    kind_width = max(len(tx["kind"]) for tx in transactions)
    ages = [f"({tx['age']})" for tx in transactions]
    age_width = max(len(age) for age in ages)
    for number, (tx, amount, age) in enumerate(zip(transactions, amounts, ages), 1):
        when = f"{tx['time_utc']} {age:<{age_width}}"
        preposition = "from" if tx["direction"] == "IN" else "to"
        party = f"{preposition} {tx['counterparty']}" if tx["counterparty"] else ""
        flags = "  FAILED" if not tx["success"] else ""
        print(f"{number:>3}. {when}  {tx['direction']:<4} {amount:>{amount_width}}  {tx['kind']:<{kind_width}}  {party}{flags}")
        print(f"     {tx['url']}")

    if not result["finished"]:
        print(f"\n{result['note']}")


def main():
    address, options = parse_args(sys.argv[1:])

    mode = options.get("mode", "default").lower()
    if mode not in MODES:
        fail(f"unknown mode '{mode}'. Valid modes: {', '.join(MODES)}")
    if mode == "default" and "view" in options:
        fail("view= only works with mode=history")

    try:
        chain = get_chain(options["chain"]) if "chain" in options else None
        if address is None:
            address = input(f"Enter {chain.name if chain else 'wallet'} address: ").strip()
        chain = resolve_chain(address, chain)
        if mode == "history":
            show_history(chain, address, options)
        else:
            show_assets(chain, address, options)
    except ScanError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
