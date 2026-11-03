# tx-scanner

A small Python script that shows the current balance of an address on BNB Smart Chain (BSC / BEP20). It can show:

- the **BNB** balance of an address, or
- the balance of a single **BEP20 token** (USDT, BUSD, CAKE, ...) held by an address.

You don't need an API key or any extra packages. The script reads directly from the public BSC node at `https://bsc-dataseed.bnbchain.org`.

## Requirements

- Python 3.7 or newer
- Optional: [`certifi`](https://pypi.org/project/certifi/). Only needed if you get SSL certificate errors (see Troubleshooting).

## Usage

On **macOS / Linux**, the command is `python3`. On **Windows**, it is `python` or `py`.

### BNB balance

```bash
python3 bep20_balance.py 0x8894E0a0c962CB723c1976a4421c95949bE2D4E3
```

```
Address: 0x8894E0a0c962CB723c1976a4421c95949bE2D4E3
Balance: 2.998524679689695997 BNB
```

### BEP20 token balance

Put the token's contract address after the wallet address:

```bash
python3 bep20_balance.py 0x8894E0a0c962CB723c1976a4421c95949bE2D4E3 0x55d398326f99059fF775485246999027B3197955
```

```
Address: 0x8894E0a0c962CB723c1976a4421c95949bE2D4E3
Balance: 598.736736756852052811 USDT
```

The script reads the token's decimals and symbol from the contract, so you don't have to enter them.

Common token contracts on BSC:

| Token | Contract |
|-------|----------|
| USDT  | `0x55d398326f99059fF775485246999027B3197955` |
| USDC  | `0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d` |
| CAKE  | `0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` |

### Interactive mode

If you run it without arguments, it asks for an address:

```bash
python3 bep20_balance.py
Enter BEP20 address: 0x...
```

## Windows

1. Install Python from [python.org](https://www.python.org/downloads/) and check **"Add python.exe to PATH"** during setup.
2. Open **Command Prompt** or **PowerShell** in the project folder.
3. Run:

   ```powershell
   py bep20_balance.py 0xYourAddress
   ```

You can also double-click `bep20_balance.py`. It asks for the address, but the window closes as soon as the result prints, so running it from a terminal works better.

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED`** (mostly macOS with the python.org installer). Do one of these:

```bash
pip3 install certifi
```

or run `Install Certificates.command` from `/Applications/Python 3.x/`.

**`Invalid address`**: the address must be `0x` followed by 40 hexadecimal characters.

**Timeouts or rate-limit errors**: the public node is sometimes busy. Wait and try again, or change `RPC_URL` at the top of the script to another BSC endpoint, e.g. `https://bsc-dataseed1.binance.org` or `https://bsc-rpc.publicnode.com`.
