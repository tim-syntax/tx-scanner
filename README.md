# tx-scanner

A small Python tool that shows wallet balances on a blockchain. **BNB Smart Chain (BSC / BEP20)** and **Tron (TRC20)** are supported, and the code is set up so Ethereum and other chains can be added.

It shows the native coin (BNB, TRX) and any tokens you list, such as USDT and USDC. You don't need an API key or extra packages; it reads directly from public nodes.

The chain is detected from the address: `0x...` is BSC and `T...` is Tron.

## Requirements

- Python 3.7 or newer
- Optional: [`certifi`](https://pypi.org/project/certifi/). Only needed if you get SSL certificate errors (see Troubleshooting).

## Usage

On **Windows**, use `py` (or `python`). On **macOS / Linux**, use `python3`.

### All tokens in the list

```bash
py scan.py 0x173f532daE51F93d8fAda21E8E5d50b01261ae83
```

```
Chain:   BNB Smart Chain
Address: 0x173f532daE51F93d8fAda21E8E5d50b01261ae83
  1. BNB    0.006683409659387566 (4.63 USD)
  2. USDT   591.0804911
  3. USDC   0
  4. BUSD   0
  5. FDUSD  0
  6. DAI    0
  7. ETH    0
  8. BTCB   0
  9. CAKE   0
```

The number next to each token is what you use with `list=`.

The USD value is shown for the native coin only (BNB, TRX). It uses the current price from Chainlink's BNB / USD and TRX / USD feeds on BSC, so it needs no API key. If the price can't be read or is more than an hour old, the balance still shows, with `(USD unavailable: <reason>)` next to it.

A Tron address works the same way:

```bash
py scan.py TF1rBJ1RRunsD1jtKenm9qQ9sovre7eWPE list=1,2
```

```
Chain:   Tron
Address: TF1rBJ1RRunsD1jtKenm9qQ9sovre7eWPE
  1. TRX   2403.112174 (774.43 USD)
  2. USDT  0.357138
```

### Only some tokens

```bash
py scan.py 0x173f532daE51F93d8fAda21E8E5d50b01261ae83 list=1,2
```

```
Chain:   BNB Smart Chain
Address: 0x173f532daE51F93d8fAda21E8E5d50b01261ae83
  1. BNB   0.006683409659387566 (4.63 USD)
  2. USDT  591.0804911
```

> **PowerShell:** commas have a special meaning there, so put quotes around it: `"list=1,2"`. Without quotes, the script also handles PowerShell's split form, but quoting is the safest.

### A token that isn't in the list

```bash
py scan.py 0xYourAddress token=0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE
```

The script reads the token's symbol and decimals from the contract.

### All options

| Option | Example | Meaning |
|--------|---------|---------|
| *(address)* | `0x173f...ae83` | Wallet to check. If you leave it out, the script asks for it. |
| `list=` | `list=1,3,4` | Only show these token numbers. |
| `token=` | `token=0x55d3...7955` | Show one token by contract address. |
| `chain=` | `chain=tron` | Which chain to use (`bsc` or `tron`). By default it's detected from the address. |

Run `py scan.py help` to see this from the command line.

## Editing the token list

Each chain has its own token list in [`tokens/`](tokens/): [`tokens/bsc.json`](tokens/bsc.json) and [`tokens/tron.json`](tokens/tron.json). For example:

```json
[
  { "symbol": "BNB",  "native": true, "decimals": 18 },
  { "symbol": "USDT", "contract": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18 }
]
```

- The order of the entries sets their numbers for `list=`. If you insert a token in the middle, the numbers after it shift.
- `"native": true` marks the chain's own coin (BNB, TRX), which has no contract.
- Decimals differ between chains: USDT has 18 on BSC and 6 on Tron.
- Get contract addresses from [bscscan.com](https://bscscan.com) or [tronscan.org](https://tronscan.org). Copy-cat tokens often use the same name, so make sure it's the official contract.

## Project layout

```
scan.py            command-line entry point
chains/
  __init__.py      chain registry (CHAINS) - add new chains here
  base.py          Chain interface + token list loading
  evm.py           EVM chains (BSC, Ethereum, Polygon, ...) via JSON-RPC
  tron.py          Tron via a node's HTTP API
  http.py          shared HTTPS helper
tokens/
  bsc.json         token list for BNB Smart Chain
  tron.json        token list for Tron
```

### Adding a chain

**Another EVM chain** (Ethereum, Polygon, Arbitrum, ...) uses the same code as BSC:

1. Create `tokens/eth.json`, with the native coin first.
2. Add one line to `CHAINS` in [`chains/__init__.py`](chains/__init__.py):
   ```python
   "eth": EvmChain("Ethereum", "eth.json", rpc_url="https://ethereum-rpc.publicnode.com"),
   ```
3. Run `py scan.py 0xYourAddress chain=eth`.

To show USD for the native coin, also pass `native_usd_feed=` with that chain's Chainlink feed address. Without it, the balance prints with no USD value.

`0x...` addresses are detected as BSC because it's listed first in `CHAINS`, so other EVM chains need `chain=`.

**A non-EVM chain** (Solana, ...) needs its own module:

1. Create a module like [`chains/tron.py`](chains/tron.py), with a class that subclasses `chains.base.Chain` and implements `is_valid_address`, `native_balance_raw`, `token_balance_raw` and `token_info`. You can use `chains.http.post_json` for HTTP requests.
2. Register it in `CHAINS` and add its token list to `tokens/`.

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED`** (mostly macOS with the python.org installer). Do one of these:

```bash
pip3 install certifi
```

or run `Install Certificates.command` from `/Applications/Python 3.x/`.

**`invalid ... address`** or **`not a valid address`**: BSC addresses are `0x` followed by 40 hexadecimal characters. Tron addresses start with `T` and are 34 characters long; a single wrong character fails the checksum.

**Timeouts or rate-limit errors**: the public node is sometimes busy. Wait and try again, or change `rpc_url` for the chain in [`chains/__init__.py`](chains/__init__.py) to another endpoint, e.g. `https://bsc-dataseed1.binance.org` or `https://bsc-rpc.publicnode.com`.
