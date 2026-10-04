"""Markets API — top 100 USDT-SWAP pairs by 24h USD volume."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["markets"])

_OKX_BASE = "https://www.okx.com"

# (name, sector) — display metadata for well-known symbols; unknown symbols fall back to the raw ticker
_COINS: dict[str, tuple[str, str]] = {
    "BTC":    ("Bitcoin",          "Layer 1"),
    "ETH":    ("Ethereum",         "Layer 1"),
    "SOL":    ("Solana",           "Layer 1"),
    "XRP":    ("XRP",              "Payments"),
    "BNB":    ("BNB",              "Layer 1"),
    "DOGE":   ("Dogecoin",         "Meme"),
    "ADA":    ("Cardano",          "Layer 1"),
    "AVAX":   ("Avalanche",        "Layer 1"),
    "DOT":    ("Polkadot",         "Layer 1"),
    "LINK":   ("Chainlink",        "Oracle"),
    "TRX":    ("TRON",             "Layer 1"),
    "TON":    ("Toncoin",          "Layer 1"),
    "SHIB":   ("Shiba Inu",        "Meme"),
    "MATIC":  ("Polygon",          "Layer 2"),
    "POL":    ("Polygon",          "Layer 2"),
    "UNI":    ("Uniswap",          "DeFi"),
    "ATOM":   ("Cosmos",           "Layer 1"),
    "LTC":    ("Litecoin",         "Payments"),
    "BCH":    ("Bitcoin Cash",     "Payments"),
    "FIL":    ("Filecoin",         "Storage"),
    "APT":    ("Aptos",            "Layer 1"),
    "ARB":    ("Arbitrum",         "Layer 2"),
    "OP":     ("Optimism",         "Layer 2"),
    "NEAR":   ("NEAR Protocol",    "Layer 1"),
    "SUI":    ("Sui",              "Layer 1"),
    "PEPE":   ("Pepe",             "Meme"),
    "WLD":    ("Worldcoin",        "AI"),
    "TIA":    ("Celestia",         "Layer 1"),
    "SEI":    ("Sei",              "Layer 1"),
    "INJ":    ("Injective",        "DeFi"),
    "FET":    ("Fetch.ai",         "AI"),
    "RENDER": ("Render",           "AI"),
    "RNDR":   ("Render",           "AI"),
    "AAVE":   ("Aave",             "DeFi"),
    "MKR":    ("Maker",            "DeFi"),
    "CRV":    ("Curve",            "DeFi"),
    "LDO":    ("Lido DAO",         "DeFi"),
    "PENDLE": ("Pendle",           "DeFi"),
    "ENA":    ("Ethena",           "DeFi"),
    "FLOKI":  ("Floki",            "Meme"),
    "BONK":   ("Bonk",             "Meme"),
    "WIF":    ("dogwifhat",        "Meme"),
    "ORDI":   ("ORDI",             "BRC-20"),
    "STX":    ("Stacks",           "Layer 2"),
    "IMX":    ("Immutable X",      "Gaming"),
    "GALA":   ("Gala",             "Gaming"),
    "AXS":    ("Axie Infinity",    "Gaming"),
    "SAND":   ("The Sandbox",      "Gaming"),
    "MANA":   ("Decentraland",     "Gaming"),
    "AR":     ("Arweave",          "Storage"),
    "GRT":    ("The Graph",        "Infrastructure"),
    "FTM":    ("Fantom",           "Layer 1"),
    "ALGO":   ("Algorand",         "Layer 1"),
    "HBAR":   ("Hedera",           "Layer 1"),
    "VET":    ("VeChain",          "Layer 1"),
    "ICP":    ("Internet Computer","Layer 1"),
    "PYTH":   ("Pyth Network",     "Oracle"),
    "JUP":    ("Jupiter",          "DeFi"),
    "STRK":   ("Starknet",         "Layer 2"),
    "TAO":    ("Bittensor",        "AI"),
    "ONDO":   ("Ondo Finance",     "RWA"),
    "NOT":    ("Notcoin",          "Meme"),
    "KAS":    ("Kaspa",            "Layer 1"),
    "RUNE":   ("THORChain",        "DeFi"),
    "DYDX":   ("dYdX",             "DeFi"),
    "XLM":    ("Stellar",          "Payments"),
    "EOS":    ("EOS",              "Layer 1"),
    "SATS":   ("SATS",             "BRC-20"),
    "THETA":  ("Theta Network",    "Infrastructure"),
    "BLUR":   ("Blur",             "NFT"),
    "ENS":    ("ENS",              "Infrastructure"),
    "JASMY":  ("JasmyCoin",        "IoT"),
}


_OKX_ICON_CDN = "https://static.okx.com/cdn/oksupport/asset/currency/icon"


def _icon(symbol: str) -> str:
    return f"{_OKX_ICON_CDN}/{symbol.lower()}.png"


class MarketTicker(BaseModel):
    pair: str
    symbol: str
    name: str
    price: float
    change_24h: float
    change_pct_24h: float
    volume_24h: float
    high_24h: float
    low_24h: float
    icon_url: str
    sector: str


@router.get("/markets", response_model=list[MarketTicker])
async def get_markets() -> list[MarketTicker]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_OKX_BASE}/api/v5/market/tickers", params={"instType": "SWAP"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    tickers: list[MarketTicker] = []
    for item in data.get("data", []):
        inst_id: str = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        try:
            last = float(item.get("last", 0) or 0)
            open24h = float(item.get("open24h", 0) or 0)
            high24h = float(item.get("high24h", 0) or 0)
            low24h = float(item.get("low24h", 0) or 0)
            vol_ccy = float(item.get("volCcy24h", 0) or 0)
        except (TypeError, ValueError):
            continue
        if open24h == 0 or last == 0:
            continue

        symbol = inst_id.split("-")[0]
        coin = _COINS.get(symbol)
        name = coin[0] if coin else symbol
        sector = coin[1] if coin else "Other"

        change = last - open24h
        change_pct = (change / open24h) * 100
        usd_vol = last * vol_ccy

        tickers.append(MarketTicker(
            pair=inst_id, symbol=symbol, name=name, price=last,
            change_24h=round(change, 8), change_pct_24h=round(change_pct, 4),
            volume_24h=usd_vol, high_24h=high24h, low_24h=low24h,
            icon_url=_icon(symbol),
            sector=sector,
        ))

    tickers.sort(key=lambda t: t.volume_24h, reverse=True)
    return tickers[:100]
