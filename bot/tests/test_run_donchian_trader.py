from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.config import settings
from scripts import run_donchian_trader as rt

NOW = datetime(2026, 10, 9, 0, 10, tzinfo=timezone.utc)
DAY = 86_400_000
YDAY = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp() * 1000)


def daily(closes: list[float]) -> list[dict[str, Any]]:
    n = len(closes)
    out = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else c
        out.append({"timestamp": str(YDAY - (n - 1 - k) * DAY), "open": o, "high": max(o, c) * 1.002,
                    "low": min(o, c) * 0.998, "close": c, "volume": 1.0, "confirm": "1"})
    return out


FLAT = [100.0 + (1.0 if k % 2 else -1.0) for k in range(80)]
BREAKOUT = FLAT[:-1] + [130.0]


class FakeMarket:
    def __init__(self, series: dict[str, list[float]]) -> None:
        self.series = series

    async def get_instruments(self, *, inst_type: str, inst_id: str) -> list[dict[str, Any]]:
        return [{"instId": inst_id, "lotSz": "0.0001", "minSz": "0.0001"}]

    async def get_candles(self, inst: str, bar: str, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        assert bar == "1Dutc"
        return list(reversed(daily(self.series[inst])))  # OKX returns newest first

    async def get_ticker(self, inst: str) -> dict[str, Any]:
        px = self.series[inst][-1]
        return {"last": px, "mid_price": px}

    async def close(self) -> None:
        pass


class FakeClient:
    def __init__(self, balances: dict[str, float]) -> None:
        self.balances = dict(balances)
        self.orders: dict[str, dict[str, Any]] = {}
        self.sent: list[dict[str, Any]] = []
        self.fail_send = False

    async def get_balances(self) -> dict[str, float]:
        return dict(self.balances)

    async def find_order(self, *, inst_id: str, cl_ord_id: str) -> dict[str, Any] | None:
        return self.orders.get(cl_ord_id)

    async def place_spot_market_order(self, *, inst_id: str, side: str, size: str, cl_ord_id: str, size_in_quote: bool) -> dict:
        self.sent.append({"inst": inst_id, "side": side, "size": size, "cl": cl_ord_id})
        if self.fail_send:
            # simulate: request timed out client-side but OKX accepted it
            self._fill(inst_id, side, size, cl_ord_id, size_in_quote)
            raise TimeoutError("read timeout")
        self._fill(inst_id, side, size, cl_ord_id, size_in_quote)
        return {"code": "0"}

    def _fill(self, inst: str, side: str, size: str, cl: str, in_quote: bool) -> None:
        px = 130.0
        base = float(size) / px if in_quote else float(size)
        coin = inst.split("-")[0]
        fee = base * 0.001
        if side == "buy":
            self.balances[coin] = self.balances.get(coin, 0.0) + base - fee
            self.balances["USDT"] -= base * px
            fee_ccy = coin
        else:
            self.balances[coin] -= base
            self.balances["USDT"] += base * px * 0.999
            fee, fee_ccy = base * px * 0.001, "USDT"
        self.orders[cl] = {"state": "filled", "accFillSz": str(base), "avgPx": str(px), "fee": str(-fee), "feeCcy": fee_ccy,
                           "fillTime": str(int(NOW.timestamp() * 1000))}

    async def close(self) -> None:
        pass


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "RISK_KILL_SWITCH_FILE", str(tmp_path / "ks.json"))
    monkeypatch.setattr(settings, "RISK_EXECUTION_LOG_FILE", str(tmp_path / "tca.jsonl"))
    monkeypatch.setattr(settings, "RISK_MAX_ORDER_NOTIONAL_USD", 5000.0)
    monkeypatch.setattr(settings, "RISK_MAX_INSTRUMENT_NOTIONAL_USD", 5000.0)
    monkeypatch.setattr(settings, "RISK_MAX_TOTAL_EXPOSURE_USD", 10000.0)
    monkeypatch.setattr(settings, "RISK_MAX_PRICE_DEVIATION_PCT", 5.0)
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(rt, "now_utc", lambda: NOW)
    monkeypatch.setattr(rt, "FILL_POLL_DELAY_S", 0)

    async def no_sleep(*_: Any) -> None:
        return None

    monkeypatch.setattr(rt.asyncio, "sleep", no_sleep)
    return tmp_path


def make_trader(tmp: Path, market: FakeMarket, client: FakeClient, **kw: Any) -> rt.Trader:
    args = argparse.Namespace(pairs="SOL-USDT,XRP-USDT", capital_usd=2000.0, risk_pct=5.0, entry=55, exit=20, atr_stop=2.0,
                              poll_seconds=600, state_file=str(tmp / "state.json"), once=True)
    for k, v in kw.items():
        setattr(args, k, v)
    t = rt.Trader(args)
    t.client, t.market = client, market
    return t


@pytest.mark.asyncio
async def test_fresh_start_buys_breakout_once_and_is_idempotent_across_restart(env: Path) -> None:
    market = FakeMarket({"SOL-USDT": BREAKOUT, "XRP-USDT": FLAT})
    client = FakeClient({"USDT": 6000.0, "SOL": 3.0})  # 3 SOL pre-existing → baseline
    t = make_trader(env, market, client)
    await t.start()
    await t.run_once()

    assert len(client.sent) == 1 and client.sent[0]["inst"] == "SOL-USDT" and client.sent[0]["side"] == "buy"
    st = rt.load_state(env / "state.json")
    assert st["baseline"]["SOL"] == 3.0
    assert st["pending"] == {}
    assert st["handled_bar"]["SOL-USDT"] == YDAY and st["handled_bar"]["XRP-USDT"] == YDAY
    assert st["sleeves"]["SOL-USDT"]["qty"] > 0 and st["sleeves"]["XRP-USDT"]["qty"] == 0
    assert len(st["trades"]) == 1

    # restart: same bar must not trade again
    t2 = make_trader(env, market, client)
    await t2.start()
    await t2.run_once()
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_send_timeout_is_settled_by_clordid_without_resending(env: Path) -> None:
    market = FakeMarket({"SOL-USDT": BREAKOUT, "XRP-USDT": FLAT})
    client = FakeClient({"USDT": 6000.0})
    client.fail_send = True
    t = make_trader(env, market, client)
    await t.start()
    await t.run_once()
    assert len(client.sent) == 1  # never resent
    st = rt.load_state(env / "state.json")
    assert st["pending"] == {}  # found by clOrdId and booked
    assert st["sleeves"]["SOL-USDT"]["qty"] > 0


@pytest.mark.asyncio
async def test_missing_coins_trip_kill_switch_and_block_trading(env: Path) -> None:
    market = FakeMarket({"SOL-USDT": FLAT, "XRP-USDT": FLAT})
    client = FakeClient({"USDT": 6000.0, "SOL": 1.0})
    t = make_trader(env, market, client)
    await t.start()
    t.sleeves["SOL-USDT"].qty = 2.0  # book thinks it owns 2 SOL above baseline, exchange has 0 extra
    market.series["XRP-USDT"] = BREAKOUT
    await t.run_once()
    assert t.gate.kill_switch.is_tripped()
    assert client.sent == []


@pytest.mark.asyncio
async def test_stale_data_skips_decision(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    market = FakeMarket({"SOL-USDT": BREAKOUT, "XRP-USDT": FLAT})
    client = FakeClient({"USDT": 6000.0})
    monkeypatch.setattr(rt, "now_utc", lambda: NOW + timedelta(days=2))  # data now two days old
    t = make_trader(env, market, client)
    await t.start()
    await t.run_once()
    assert client.sent == []
    assert rt.load_state(env / "state.json")["handled_bar"] == {}


@pytest.mark.asyncio
async def test_refuses_live_mode(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.setattr(settings, "OKX_MODE", "live")
    with pytest.raises(SystemExit):
        await rt.run(argparse.Namespace(once=True))
