"""Chain registry.

To add a chain, add an entry to CHAINS and create its token list in tokens/<file>.json.
EVM chains (Ethereum, Polygon, Arbitrum...) only need an EvmChain entry with an RPC URL.
Non-EVM chains need their own module that subclasses chains.base.Chain (see tron.py).

Order matters: an address that fits several chains is detected as the first one listed,
so 0x... addresses default to BSC. Use chain= to pick another chain.
"""

from .base import Chain, ConfigError, HistoryUnavailable, Token, Transaction
from .evm import EvmChain
from .tron import TronChain

_bsc = EvmChain(
    "BNB Smart Chain",
    "bsc.json",
    rpc_url="https://bsc-dataseed.bnbchain.org",
    native_usd_feed="0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE",  # Chainlink BNB / USD
    nodereal_url="https://bsc-mainnet.nodereal.io/v1/",
    explorer_tx_url="https://bscscan.com/tx/",
)

CHAINS = {
    "bsc": _bsc,
    "tron": TronChain(
        "Tron",
        "tron.json",
        api_url="https://tron-rpc.publicnode.com",
        # Chainlink TRX / USD feed, which lives on BSC
        native_usd_price=lambda: _bsc.chainlink_price("0xF4C5e535756D11994fCBB12Ba8adD0192D9b88be"),
    ),
}


def detect_chain(address):
    """Return the first chain the address is valid on, or None."""
    for chain in CHAINS.values():
        if chain.is_valid_address(address):
            return chain
    return None


__all__ = ["CHAINS", "detect_chain", "Chain", "ConfigError", "HistoryUnavailable", "Token", "Transaction"]
