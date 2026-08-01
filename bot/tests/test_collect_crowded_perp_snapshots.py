from __future__ import annotations

import json

import pytest

from scripts import collect_crowded_perp_snapshots as collector


class _FakeSnapshotClient:
    async def get_ticker(self, inst_id: str):
        return {
            "instId": inst_id,
            "last": 100.0,
            "mid_price": 100.0,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "raw": {"instId": inst_id, "last": "100", "ts": "1767225600000"},
        }

    async def get_order_book_top_depth(self, inst_id: str, depth: int = 5):
        raw_bids = [["100", "1", "0", "1"] for _ in range(25)]
        raw_asks = [["101", "1", "0", "1"] for _ in range(25)]
        return {
            "bid_depth_notional": 100.0,
            "ask_depth_notional": 101.0,
            "mid_price": 100.5,
            "spread_pct": 0.1,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "raw": {"ts": "1767225600000", "seqId": 1, "bids": raw_bids, "asks": raw_asks},
        }

    async def get_recent_trades(self, inst_id: str, limit: int = 100):
        return [
            {
                "side": "buy" if index % 2 == 0 else "sell",
                "notional": 100.0,
                "timestamp_iso": "2026-01-01T00:00:00+00:00",
                "raw": {"instId": inst_id, "side": "buy", "px": "100", "sz": "1", "tradeId": str(index)},
            }
            for index in range(30)
        ]

    async def get_funding_rate(self, inst_id: str):
        return {
            "funding_rate": 0.0001,
            "premium": 0.0002,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "raw": {"instId": inst_id, "fundingRate": "0.0001", "premium": "0.0002"},
        }

    async def get_open_interest(self, inst_id: str):
        return {
            "open_interest": 1000.0,
            "open_interest_usd": 100000.0,
            "timestamp_iso": "2026-01-01T00:00:00+00:00",
            "raw": {"instId": inst_id, "oi": "1000", "oiUsd": "100000"},
        }


class _FailingSnapshotClient(_FakeSnapshotClient):
    async def get_funding_rate(self, inst_id: str):
        raise RuntimeError("HTTP 429 rate limit")


def test_collector_rejects_excessive_default_instruments() -> None:
    with pytest.raises(ValueError, match="at most three instruments"):
        collector.parse_instruments("BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,XRP-USDT-SWAP")


def test_collector_main_prints_dry_run_payload_without_network(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def fake_run(args):
        assert args.dry_run is True
        assert args.duration == 30
        return [{"inst_id": "BTC-USDT-SWAP", "observed_at": "2026-01-01T00:00:00+00:00"}]

    monkeypatch.setattr(collector, "run", fake_run)

    exit_code = collector.main(["--dry-run", "--duration", "30", "--interval", "10"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["count"] == 1
    assert output["snapshots"][0]["inst_id"] == "BTC-USDT-SWAP"


@pytest.mark.asyncio
async def test_collect_one_snapshot_bounds_raw_fragments_and_marks_dry_run() -> None:
    snapshot = await collector.collect_one_snapshot(
        _FakeSnapshotClient(),
        "BTC-USDT-SWAP",
        depth=999,
        dry_run=False,
    )

    assert snapshot["data_quality_flags"]["dry_run_only"] is False
    assert snapshot["raw_json"]["ticker"]["last"] == "100"
    assert len(snapshot["raw_json"]["book"]["bids"]) == collector.MAX_BOOK_DEPTH
    assert len(snapshot["raw_json"]["book"]["asks"]) == collector.MAX_BOOK_DEPTH
    assert len(snapshot["raw_json"]["trades"]) == collector.MAX_RAW_TRADES
    assert snapshot["raw_json"]["trades"][0]["px"] == "100"


@pytest.mark.asyncio
async def test_collect_one_snapshot_records_endpoint_gap_and_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(collector, "BACKOFF_SECONDS", 0.25)
    monkeypatch.setattr(collector.asyncio, "sleep", fake_sleep)

    snapshot = await collector.collect_one_snapshot(
        _FailingSnapshotClient(),
        "BTC-USDT-SWAP",
        dry_run=True,
    )

    assert snapshot["data_quality_flags"]["endpoint_gaps"] == ["funding"]
    assert snapshot["data_quality_flags"]["backoff_seconds"] == 0.25
    assert snapshot["data_quality_flags"]["dry_run_only"] is True
    assert "HTTP 429" in snapshot["raw_json"]["endpoint_errors"]["funding"]
    assert sleep_calls == [0.25]
