"""Web app: the page in web/index.html plus a JSON API over scanner.py.

Run locally:   uvicorn api.index:app --reload
On Vercel, vercel.json sends every request to this file.
"""

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # so `chains` and `scanner` import the same way on Vercel and locally

from fastapi import FastAPI, Query  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from chains import CHAINS, detect_chain  # noqa: E402
from scanner import (  # noqa: E402
    DEFAULT_VIEW,
    MAX_VIEW,
    ScanError,
    UpstreamError,
    chain_key,
    get_assets,
    get_chain,
    get_history,
    load_tokens,
    parse_list,
    parse_view,
    resolve_chain,
)

INDEX_HTML = ROOT / "web" / "index.html"

app = FastAPI(title="tx-scanner", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


@app.exception_handler(ScanError)
def scan_error_handler(request, error):
    # 502: a node or API failed; 400: the request itself can't be answered.
    status = 502 if isinstance(error, UpstreamError) else 400
    return JSONResponse({"detail": str(error)}, status_code=status)


def _chain_for(address, chain):
    return resolve_chain(address, get_chain(chain) if chain else None)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.get("/api/chains")
def chains():
    """Supported chains and their token lists (numbers are 1-based, as in the CLI)."""
    result = []
    for key, chain in CHAINS.items():
        tokens = load_tokens(chain)
        result.append({
            "key": key,
            "name": chain.name,
            "tokens": [
                {"number": n, "symbol": t.symbol, "contract": t.contract, "native": t.contract is None}
                for n, t in enumerate(tokens, 1)
            ],
        })
    return {"chains": result, "default_view": DEFAULT_VIEW, "max_view": MAX_VIEW}


@app.get("/api/detect")
def detect(address: str):
    """Which chain an address belongs to, or null. Checks the format only; no network requests."""
    chain = detect_chain(address.strip())
    return {"chain": chain_key(chain) if chain else None}


@app.get("/api/balances")
def balances(
    address: str,
    chain: Optional[str] = None,
    tokens: Optional[str] = Query(None, description="Token numbers, e.g. 1,3,4"),
    token: Optional[str] = Query(None, description="One token contract address"),
):
    selected_chain = _chain_for(address, chain)
    numbers = parse_list(tokens, len(load_tokens(selected_chain))) if tokens else None
    return get_assets(selected_chain, address.strip(), numbers=numbers, contract=token or None)


@app.get("/api/history")
def history(address: str, chain: Optional[str] = None, view: str = str(DEFAULT_VIEW)):
    selected_chain = _chain_for(address, chain)
    return get_history(selected_chain, address.strip(), parse_view(view))
