"""Markets API — top 100 USDT-SWAP pairs by 24h USD volume."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["markets"])

_OKX_BASE = "https://www.okx.com"

# (name, sector, coingecko_image_id) — image_id is the numeric folder in coingecko CDN
_COINS: dict[str, tuple[str, str, int]] = {
    "BTC":    ("Bitcoin",          "Layer 1",        1),
    "ETH":    ("Ethereum",         "Layer 1",        279),
    "SOL":    ("Solana",           "Layer 1",        4128),
    "XRP":    ("XRP",              "Payments",       44),
    "BNB":    ("BNB",              "Layer 1",        825),
    "DOGE":   ("Dogecoin",         "Meme",           5),
    "ADA":    ("Cardano",          "Layer 1",        975),
    "AVAX":   ("Avalanche",        "Layer 1",        12559),
    "DOT":    ("Polkadot",         "Layer 1",        12171),
    "LINK":   ("Chainlink",        "Oracle",         877),
    "TRX":    ("TRON",             "Layer 1",        1094),
    "TON":    ("Toncoin",          "Layer 1",        17980),
    "SHIB":   ("Shiba Inu",        "Meme",           11939),
    "MATIC":  ("Polygon",          "Layer 2",        4713),
    "POL":    ("Polygon",          "Layer 2",        4713),
    "UNI":    ("Uniswap",          "DeFi",           12504),
    "ATOM":   ("Cosmos",           "Layer 1",        1481),
    "LTC":    ("Litecoin",         "Payments",       2),
    "BCH":    ("Bitcoin Cash",     "Payments",       780),
    "FIL":    ("Filecoin",         "Storage",        12817),
    "APT":    ("Aptos",            "Layer 1",        26455),
    "ARB":    ("Arbitrum",         "Layer 2",        16547),
    "OP":     ("Optimism",         "Layer 2",        25244),
    "NEAR":   ("NEAR Protocol",    "Layer 1",        10365),
    "SUI":    ("Sui",              "Layer 1",        26375),
    "PEPE":   ("Pepe",             "Meme",           29850),
    "WLD":    ("Worldcoin",        "AI",             31069),
    "TIA":    ("Celestia",         "Layer 1",        31967),
    "SEI":    ("Sei",              "Layer 1",        28205),
    "INJ":    ("Injective",        "DeFi",           12882),
    "FET":    ("Fetch.ai",         "AI",             5681),
    "RENDER": ("Render",           "AI",             11636),
    "RNDR":   ("Render",           "AI",             11636),
    "AAVE":   ("Aave",             "DeFi",           12645),
    "MKR":    ("Maker",            "DeFi",           1364),
    "CRV":    ("Curve",            "DeFi",           12124),
    "LDO":    ("Lido DAO",         "DeFi",           13573),
    "PENDLE": ("Pendle",           "DeFi",           15069),
    "ENA":    ("Ethena",           "DeFi",           36530),
    "FLOKI":  ("Floki",            "Meme",           10947),
    "BONK":   ("Bonk",             "Meme",           28600),
    "WIF":    ("dogwifhat",        "Meme",           33566),
    "ORDI":   ("ORDI",             "BRC-20",         30162),
    "STX":    ("Stacks",           "Layer 2",        2069),
    "IMX":    ("Immutable X",      "Gaming",         17233),
    "GALA":   ("Gala",             "Gaming",         12493),
    "AXS":    ("Axie Infinity",    "Gaming",         13029),
    "SAND":   ("The Sandbox",      "Gaming",         12129),
    "MANA":   ("Decentraland",     "Gaming",         2566),
    "AR":     ("Arweave",          "Storage",        4343),
    "GRT":    ("The Graph",        "Infrastructure", 13397),
    "FTM":    ("Fantom",           "Layer 1",        4001),
    "ALGO":   ("Algorand",         "Layer 1",        4030),
    "HBAR":   ("Hedera",           "Layer 1",        3688),
    "VET":    ("VeChain",          "Layer 1",        3077),
    "ICP":    ("Internet Computer","Layer 1",        14495),
    "PYTH":   ("Pyth Network",     "Oracle",         31924),
    "JUP":    ("Jupiter",          "DeFi",           34188),
    "STRK":   ("Starknet",         "Layer 2",        26997),
    "TAO":    ("Bittensor",        "AI",             28452),
    "ONDO":   ("Ondo Finance",     "RWA",            26580),
    "NOT":    ("Notcoin",          "Meme",           28681),
    "KAS":    ("Kaspa",            "Layer 1",        25767),
    "RUNE":   ("THORChain",        "DeFi",           6595),
    "DYDX":   ("dYdX",             "DeFi",           17500),
    "XLM":    ("Stellar",          "Payments",       100),
    "EOS":    ("EOS",              "Layer 1",        738),
    "SATS":   ("SATS",             "BRC-20",         30299),
    "THETA":  ("Theta Network",    "Infrastructure", 2538),
    "BLUR":   ("Blur",             "NFT",            28453),
    "ENS":    ("ENS",              "Infrastructure", 19785),
    "JASMY":  ("JasmyCoin",        "IoT",            13876),
}


def _icon(image_id: int) -> str:
    return f"https://assets.coingecko.com/coins/images/{image_id}/small/thumb.png"


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
        image_id = coin[2] if coin else 0

        change = last - open24h
        change_pct = (change / open24h) * 100
        usd_vol = last * vol_ccy

        tickers.append(MarketTicker(
            pair=inst_id, symbol=symbol, name=name, price=last,
            change_24h=round(change, 8), change_pct_24h=round(change_pct, 4),
            volume_24h=usd_vol, high_24h=high24h, low_24h=low24h,
            icon_url=_icon(image_id) if image_id else "",
            sector=sector,
        ))

    tickers.sort(key=lambda t: t.volume_24h, reverse=True)
    return tickers[:100]
