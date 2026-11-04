"""Chain registry.

To add a chain, add an entry to CHAINS and create its token list in tokens/<file>.json.
EVM chains (Ethereum, Polygon, Arbitrum...) only need an EvmChain entry with an RPC URL.
Non-EVM chains (e.g. Tron) need their own module that subclasses chains.base.Chain.
"""

from .base import Chain, ConfigError, Token
from .evm import EvmChain

CHAINS = {
    "bsc": EvmChain(
        "BNB Smart Chain",
        "bsc.json",
        rpc_url="https://bsc-dataseed.bnbchain.org",
        native_usd_feed="0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE",  # Chainlink BNB / USD
    ),
}

DEFAULT_CHAIN = "bsc"

__all__ = ["CHAINS", "DEFAULT_CHAIN", "Chain", "ConfigError", "Token"]
