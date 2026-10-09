"""Cache OKX spot intraday candles for research (read-only, public endpoints).

    python -m scripts.fetch_intraday --bar 15m --days 1100 --pairs BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT

Writes state/research_cache/spot_<bar>/<INST>.json as raw OKX rows (oldest → newest),
confirmed bars only. Resumable: an existing file is extended back/forward, not refetched.
Throttled well under OKX's public limit (history-candles ≈ 10 req / 2 s per IP).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.exchange.public_market_data import OKXPublicMarketData

REQUEST_GAP_S = 0.22


async def fetch(market: OKXPublicMarketData, inst: str, bar: str, since_ms: int, out: Path) -> int:
    rows: dict[int, list] = {}
    if out.exists():
        for r in json.loads(out.read_text()):
            rows[int(r[0])] = r
    newest_known = max(rows) if rows else None
    oldest_known = min(rows) if rows else None

    async def page(after: str | None) -> list:
        params = {"instId": inst, "bar": bar, "limit": "100"}
        if after:
            params["after"] = after
        for attempt in range(8):
            try:
                path = "/api/v5/market/history-candles" if after else "/api/v5/market/candles"
                payload = await market._request(path, params=params)  # noqa: SLF001 — research script
                await asyncio.sleep(REQUEST_GAP_S)
                return payload.get("data", [])
            except Exception:
                await asyncio.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"{inst}: giving up after retries")

    # walk back from now until we reach rows we already have (or since_ms)
    after: str | None = None
    started = time.time()
    while True:
        data = await page(after)
        if not data:
            break
        for r in data:
            if str(r[8] if len(r) > 8 else "1") == "1":
                rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in data)
        if oldest <= since_ms:
            break
        if newest_known is not None and oldest <= newest_known and oldest_known is not None and oldest_known <= since_ms:
            break  # caught up with an already-complete cache
        if newest_known is not None and oldest <= newest_known:
            after = str(oldest_known)  # jump past the cached block
            newest_known = None
            continue
        if after == str(oldest):
            break
        after = str(oldest)
        if len(rows) % 5000 < 100:
            print(f"  {inst}: {len(rows):,} bars back to {datetime.fromtimestamp(oldest/1000, timezone.utc):%Y-%m-%d} ({time.time()-started:.0f}s)", flush=True)
    ordered = [rows[k] for k in sorted(rows) if k >= since_ms]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ordered))
    return len(ordered)


async def main_async(args: argparse.Namespace) -> None:
    since = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp() * 1000)
    out_dir = Path(f"state/research_cache/spot_{args.bar}")
    market = OKXPublicMarketData()
    try:
        for inst in [p.strip().upper() for p in args.pairs.split(",") if p.strip()]:
            n = await fetch(market, inst, args.bar, since, out_dir / f"{inst}.json")
            rows = json.loads((out_dir / f"{inst}.json").read_text())
            print(f"{inst}: {n:,} {args.bar} bars {datetime.fromtimestamp(int(rows[0][0])/1000, timezone.utc):%Y-%m-%d} → "
                  f"{datetime.fromtimestamp(int(rows[-1][0])/1000, timezone.utc):%Y-%m-%d %H:%M}", flush=True)
    finally:
        await market.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bar", default="15m")
    p.add_argument("--days", type=int, default=1100)
    p.add_argument("--pairs", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
