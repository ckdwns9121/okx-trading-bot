from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scripts import run_funding_oi_demo_trader as demo_trader


class _FakeOkxClient:
    async def set_leverage(self, inst_id: str, leverage: int) -> None:
        if inst_id == "PLUME-USDT-SWAP":
            raise RuntimeError("OKX API error 51001: Instrument ID, Instrument ID code, or Spread ID doesn't exist.")


@pytest.mark.asyncio
async def test_filter_demo_tradeable_instruments_blocks_unknown_demo_symbols() -> None:
    valid, blocked = await demo_trader.filter_demo_tradeable_instruments(
        _FakeOkxClient(),  # type: ignore[arg-type]
        instruments=("GRASS-USDT-SWAP", "PLUME-USDT-SWAP"),
        leverage=5,
    )

    assert valid == ("GRASS-USDT-SWAP",)
    assert "PLUME-USDT-SWAP" in blocked


@pytest.mark.asyncio
async def test_place_market_retry_halves_on_insufficient_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_place(_client: object, **kwargs: object) -> dict[str, object]:
        size = str(kwargs["size"])
        calls.append(size)
        if len(calls) < 3:
            raise RuntimeError("OKX API error 1: [51008] Order failed. Insufficient USDT margin in account")
        return {"ok": True, "clOrdId": "open-1"}

    async def fake_confirm(
        _client: object,
        *,
        pair: str,
        cl_ord_id: str,
        requested_size: Decimal,
    ) -> dict[str, object]:
        return {
            "executed_size": str(requested_size),
            "avg_price": 1.23,
            "order_state": "filled",
        }

    monkeypatch.setattr(demo_trader, "_place_with_pos_side_fallback", fake_place)
    monkeypatch.setattr(demo_trader, "_confirm_order_execution", fake_confirm)
    spec = demo_trader.InstrumentSpec(
        inst_id="GRASS-USDT-SWAP",
        ct_val=Decimal("1"),
        lot_size=Decimal("1"),
        min_size=Decimal("1"),
        max_market_size=None,
    )

    result = await demo_trader._place_market_with_size_retry(
        object(),  # type: ignore[arg-type]
        pair="GRASS-USDT-SWAP",
        side="buy",
        size=Decimal("16"),
        spec=spec,
        leverage=5,
        pos_side="long",
    )

    assert calls == ["16", "8", "4"]
    assert result["executed_size"] == "4"
    assert result["avg_price"] == 1.23
    assert len(result["size_retry_errors"]) == 2


class _CanceledOrderClient:
    async def get_order_by_cl_ord_id(self, cl_ord_id: str, pair: str | None = None) -> dict[str, str]:
        return {
            "clOrdId": cl_ord_id,
            "instId": pair or "GRASS-USDT-SWAP",
            "state": "canceled",
            "accFillSz": "0",
            "avgPx": "",
        }


@pytest.mark.asyncio
async def test_confirm_order_execution_rejects_canceled_unfilled_order() -> None:
    with pytest.raises(demo_trader.OrderNotFilledError):
        await demo_trader._confirm_order_execution(
            _CanceledOrderClient(),  # type: ignore[arg-type]
            pair="GRASS-USDT-SWAP",
            cl_ord_id="close-1",
            requested_size=Decimal("10"),
        )


class _LiveUnfilledOrderClient:
    def __init__(self) -> None:
        self.canceled = False

    async def get_order_by_cl_ord_id(self, cl_ord_id: str, pair: str | None = None) -> dict[str, str]:
        state = "canceled" if self.canceled else "live"
        return {
            "clOrdId": cl_ord_id,
            "ordId": "ord-1",
            "instId": pair or "GRASS-USDT-SWAP",
            "state": state,
            "accFillSz": "0",
            "avgPx": "",
        }

    async def _request(self, method: str, path: str, data: dict[str, str]) -> dict[str, object]:
        self.canceled = True
        return {"method": method, "path": path, "data": data}


@pytest.mark.asyncio
async def test_confirm_order_execution_cancels_live_unfilled_order(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    client = _LiveUnfilledOrderClient()
    monkeypatch.setattr(demo_trader.asyncio, "sleep", no_sleep)

    with pytest.raises(demo_trader.OrderNotFilledError):
        await demo_trader._confirm_order_execution(
            client,  # type: ignore[arg-type]
            pair="GRASS-USDT-SWAP",
            cl_ord_id="open-1",
            requested_size=Decimal("10"),
        )

    assert client.canceled is True


class _LivePartialOrderClient(_LiveUnfilledOrderClient):
    async def get_order_by_cl_ord_id(self, cl_ord_id: str, pair: str | None = None) -> dict[str, str]:
        if self.canceled:
            return {
                "clOrdId": cl_ord_id,
                "ordId": "ord-1",
                "instId": pair or "GRASS-USDT-SWAP",
                "state": "canceled",
                "accFillSz": "3",
                "avgPx": "1.25",
            }
        return {
            "clOrdId": cl_ord_id,
            "ordId": "ord-1",
            "instId": pair or "GRASS-USDT-SWAP",
            "state": "live",
            "accFillSz": "0",
            "avgPx": "",
        }


@pytest.mark.asyncio
async def test_confirm_order_execution_returns_partial_fill_after_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    client = _LivePartialOrderClient()
    monkeypatch.setattr(demo_trader.asyncio, "sleep", no_sleep)

    result = await demo_trader._confirm_order_execution(
        client,  # type: ignore[arg-type]
        pair="GRASS-USDT-SWAP",
        cl_ord_id="open-1",
        requested_size=Decimal("10"),
    )

    assert result["executed_size"] == "3"
    assert result["avg_price"] == 1.25
    assert result["cancel_result"]["path"] == "/api/v5/trade/cancel-order"


def test_execution_price_alignment_rejects_large_mismatch() -> None:
    with pytest.raises(demo_trader.ExecutionPriceMismatchError):
        demo_trader.ensure_execution_price_aligned(
            pair="GRASS-USDT-SWAP",
            snapshot_price=0.416,
            execution_price=0.529,
            max_deviation_pct=2.0,
        )

    assert demo_trader.ensure_execution_price_aligned(
        pair="GRASS-USDT-SWAP",
        snapshot_price=100.0,
        execution_price=101.0,
        max_deviation_pct=2.0,
    ) == pytest.approx(1.0)


def test_close_reason_uses_profit_protection_before_time_exit() -> None:
    opened_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    position = {
        "opened_at": opened_at.isoformat(),
        "entry_price": 100.0,
        "peak_move_pct": 2.5,
    }

    assert demo_trader._close_reason(
        position=position,
        latest={"mid_price": 102.1},
        hold_seconds=900,
        hard_stop_pct=1.2,
        take_profit_pct=2.0,
        trailing_activation_pct=1.0,
        trailing_drawdown_pct=0.5,
    ) == "take_profit"
    assert demo_trader._close_reason(
        position=position,
        latest={"mid_price": 101.8},
        hold_seconds=900,
        hard_stop_pct=1.2,
        take_profit_pct=3.0,
        trailing_activation_pct=1.0,
        trailing_drawdown_pct=0.5,
    ) == "trailing_stop"


class _FlatPositionsClient:
    async def get_positions(self) -> list[dict[str, str]]:
        return []


@pytest.mark.asyncio
async def test_reconcile_clears_local_position_when_exchange_is_flat() -> None:
    state = {
        "open_position": {
            "inst_id": "GRASS-USDT-SWAP",
            "side": "long",
            "entry_price": 1.0,
            "size": "10",
            "ct_val": "1",
        },
        "reconciliations": [],
        "last_exit_by_instrument": {},
    }

    items = await demo_trader.reconcile_state_with_exchange(
        _FlatPositionsClient(),  # type: ignore[arg-type]
        state=state,
        instruments=("GRASS-USDT-SWAP",),
        specs={},
        leverage=5,
    )

    assert state["open_position"] is None
    assert items[0]["type"] == "exchange_flat"
    assert "GRASS-USDT-SWAP" in state["last_exit_by_instrument"]


def test_demo_status_details_hides_raw_order_result() -> None:
    state = {
        "strategy_name": demo_trader.STRATEGY_NAME,
        "mode": "demo",
        "dry_run": False,
        "started_at": "2026-05-21T16:41:19+00:00",
        "last_loop_at": "2026-05-21T16:41:49+00:00",
        "snapshot_count_seen": 100,
        "processed_events": ["AI-USDT-SWAP:2026-05-21T16:40:00+00:00"],
        "closed_trades": [],
        "order_errors": [],
        "config": {
            "instruments": ["AI-USDT-SWAP", "GRASS-USDT-SWAP"],
            "leverage": 5,
            "notional_usd": 25_000,
            "status_event_seconds": 30,
        },
        "open_position": {
            "inst_id": "AI-USDT-SWAP",
            "side": "long",
            "entry_price": 1.23,
            "size": "10",
            "open_result": {"ordId": "raw-exchange-order"},
        },
    }

    details = demo_trader._demo_status_details(state, status="running")

    assert details["status"] == "running"
    assert details["watched_instrument_count"] == 2
    assert details["processed_event_count"] == 1
    assert details["open_position"]["inst_id"] == "AI-USDT-SWAP"
    assert "open_result" not in details["open_position"]


def test_demo_telegram_message_skips_heartbeat_events() -> None:
    assert demo_trader._demo_telegram_message(
        "funding_oi_demo_status",
        level="info",
        message="Funding/OI demo trader heartbeat",
        pair=None,
        state={},
        status="running",
        details={},
    ) is None


def test_demo_telegram_message_summarizes_opened_position() -> None:
    text = demo_trader._demo_telegram_message(
        "funding_oi_position_opened",
        level="info",
        message="Opened GRASS-USDT-SWAP long",
        pair="GRASS-USDT-SWAP",
        state={
            "open_position": {
                "entry_price": 0.42,
                "size": "100",
                "notional_usd": 42.0,
                "features": {
                    "lookback_return_pct": -1.25,
                    "funding_rate": 0.00005,
                    "oi_change_pct": 3.5,
                    "spread_pct": 0.04,
                    "setup": "long_flush_reversal",
                },
            }
        },
        status="running",
        details={"entry_price": 0.42, "size": "100"},
    )

    assert text is not None
    assert "포지션 진입" in text
    assert "GRASS-USDT-SWAP" in text
    assert "펀딩비: +0.0050%" in text
    assert "가격 움직임: -1.25%" in text


@pytest.mark.asyncio
async def test_demo_telegram_sender_filters_status_but_sends_trade_events() -> None:
    class FakeNotifier:
        def __init__(self) -> None:
            self.messages: list[str] = []

        async def send_text(self, text: str) -> bool:
            self.messages.append(text)
            return True

    notifier = FakeNotifier()
    demo_trader._set_demo_telegram_notifier(notifier)
    try:
        await demo_trader._send_demo_telegram_event(
            "funding_oi_demo_status",
            level="info",
            message="Funding/OI demo trader heartbeat",
            pair=None,
            state={},
            status="running",
            details={},
        )
        await demo_trader._send_demo_telegram_event(
            "funding_oi_position_closed",
            level="info",
            message="Closed GRASS-USDT-SWAP via take_profit",
            pair="GRASS-USDT-SWAP",
            state={},
            status="running",
            details={
                "closed_trade": {
                    "entry_price": 0.4,
                    "exit_price": 0.42,
                    "pnl_usd_estimate": 50.0,
                    "pnl_pct_estimate": 5.0,
                    "close_reason": "take_profit",
                }
            },
        )
    finally:
        demo_trader._set_demo_telegram_notifier(None)

    assert len(notifier.messages) == 1
    assert "포지션 청산" in notifier.messages[0]
    assert "손익 추정: +50.00 USDT" in notifier.messages[0]


def test_calculate_order_size_steps_to_lot_and_caps_market_size() -> None:
    spec = demo_trader.InstrumentSpec(
        inst_id="GRASS-USDT-SWAP",
        ct_val=Decimal("1"),
        lot_size=Decimal("1"),
        min_size=Decimal("1"),
        max_market_size=Decimal("74000"),
    )

    size = demo_trader.calculate_order_size(notional_usd=25_000, price=Decimal("0.365"), spec=spec)  # type: ignore[arg-type]

    assert size == Decimal("68493")


def test_calculate_order_size_with_market_cap_fraction() -> None:
    spec = demo_trader.InstrumentSpec(
        inst_id="GRASS-USDT-SWAP",
        ct_val=Decimal("1"),
        lot_size=Decimal("1"),
        min_size=Decimal("1"),
        max_market_size=Decimal("74000"),
    )

    size = demo_trader.calculate_order_size_with_market_cap(
        notional_usd=25_000,
        price=0.365,
        spec=spec,
        max_market_size_fraction=0.5,
    )

    assert size == Decimal("37000")


def test_calculate_order_size_rejects_too_small_notional() -> None:
    spec = demo_trader.InstrumentSpec(
        inst_id="ARKM-USDT-SWAP",
        ct_val=Decimal("1"),
        lot_size=Decimal("1"),
        min_size=Decimal("10"),
        max_market_size=None,
    )

    with pytest.raises(ValueError, match="below min size"):
        demo_trader.calculate_order_size(notional_usd=1, price=1.0, spec=spec)


def test_choose_fresh_event_skips_processed_and_stale_events() -> None:
    now = datetime.now(timezone.utc)
    snapshots = []
    for index in range(8):
        snapshots.append(
            {
                "inst_id": "AI-USDT-SWAP",
                "observed_at": now - timedelta(seconds=(7 - index) * 60),
                "mid_price": 100.0 if index < 3 else 99.0,
                "last_price": 100.0 if index < 3 else 99.0,
                "spread_pct": 0.04,
                "bid_depth_notional": 1000.0,
                "ask_depth_notional": 1000.0,
                "book_imbalance": 0.0,
                "reported_buy_notional": 100.0,
                "reported_sell_notional": 1000.0,
                "funding_rate": 0.00008,
                "open_interest": 10_000 + index * 100,
                "open_interest_usd": 1_000_000 + index * 1_000,
            }
        )

    event = demo_trader.choose_fresh_event(
        snapshots,
        processed_events=set(),
        fresh_seconds=180,
        lookback_seconds=300,
        min_abs_move_pct=0.5,
        min_abs_funding_rate=0.00005,
        min_oi_change_pct=0.2,
        cooldown_seconds=300,
    )

    assert event is not None
    processed = {demo_trader._event_key(event.inst_id, event.occurred_at)}
    assert demo_trader.choose_fresh_event(
        snapshots,
        processed_events=processed,
        fresh_seconds=180,
        lookback_seconds=300,
        min_abs_move_pct=0.5,
        min_abs_funding_rate=0.00005,
        min_oi_change_pct=0.2,
        cooldown_seconds=300,
    ) is None
