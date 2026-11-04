#!/usr/bin/env python3
"""Show wallet balances on a blockchain (BNB Smart Chain and Tron; more chains via chains/).

Usage:
    py scan.py <address>                     all tokens in the chain's token list
    py scan.py <address> list=1,3,4          only tokens #1, #3 and #4 from that list
    py scan.py <address> token=<contract>    one token that isn't in the list
    py scan.py <address> chain=tron          pick the chain (default: detected from the address)
    py scan.py                               asks for the address

Token numbers are shown next to each balance in the default output.
"""

import sys

from chains import CHAINS, ConfigError, Token, detect_chain

OPTIONS = ("list", "token", "chain")

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


def usd_suffix(chain, balance):
    """' (4.63 USD)' for a native coin balance, or '' if the chain has no price source."""
    try:
        price = chain.native_price_usd()
    except Exception as e:
        return f" (USD unavailable: {e})"
    if price is None:
        return ""
    return f" ({balance * price:,.2f} USD)"


def main():
    address, options = parse_args(sys.argv[1:])

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
        selected = [(None, Token(symbol, decimals, contract))]
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


if __name__ == "__main__":
    main()
