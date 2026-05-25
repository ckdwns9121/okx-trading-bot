from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.collect_basis_arbitrage_snapshots import collect_one_basis_snapshot, parse_instruments


class _FakeMarketData:
    async def get_ticker(self, pair: str) -> dict:
        if pair.endswith("-SWAP"):
            return {
                "instId": pair,
                "last": 100.2,
                "mid_price": 100.2,
                "spread_pct": 0.02,
                "timestamp_iso": datetime(2026, 5, 24, tzinfo=timezone.utc).isoformat(),
                "raw": {"instId": pair},
            }
        return {
            "instId": pair,
            "last": 100.0,
            "mid_price": 100.0,
            "spread_pct": 0.01,
            "timestamp_iso": datetime(2026, 5, 24, tzinfo=timezone.utc).isoformat(),
            "raw": {"instId": pair},
        }

    async def get_order_book_top_depth(self, pair: str, depth: int = 5) -> dict:
        price = 100.2 if pair.endswith("-SWAP") else 100.0
        return {
            "instId": pair,
            "mid_price": price,
            "spread_pct": 0.01,
            "timestamp_iso": datetime(2026, 5, 24, tzinfo=timezone.utc).isoformat(),
            "raw": {"ts": "1770000000000", "bids": [["1", "1"]], "asks": [["1", "1"]]},
        }

    async def get_funding_rate(self, pair: str) -> dict:
        return {
            "instId": pair,
            "funding_rate": 0.0002,
            "timestamp_iso": datetime(2026, 5, 24, tzinfo=timezone.utc).isoformat(),
            "next_funding_time_iso": datetime(2026, 5, 24, 8, tzinfo=timezone.utc).isoformat(),
            "raw": {"fundingRate": "0.0002"},
        }


def test_parse_instruments_requires_swap_ids() -> None:
    assert parse_instruments("BTC-USDT-SWAP, ETH-USDT-SWAP") == ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    with pytest.raises(ValueError):
        parse_instruments("BTC-USDT")


@pytest.mark.asyncio
async def test_collect_one_basis_snapshot_derives_spot_and_basis() -> None:
    snapshot = await collect_one_basis_snapshot(_FakeMarketData(), "BTC-USDT-SWAP")  # type: ignore[arg-type]

    assert snapshot["inst_id"] == "BTC-USDT-SWAP"
    assert snapshot["spot_inst_id"] == "BTC-USDT"
    assert snapshot["basis_pct"] == pytest.approx(0.2)
    assert snapshot["funding_rate"] == pytest.approx(0.0002)
    assert snapshot["estimated_daily_funding_pct"] == pytest.approx(0.06)
    assert snapshot["data_quality_flags"]["strategy"] == "funding_basis_arbitrage"
