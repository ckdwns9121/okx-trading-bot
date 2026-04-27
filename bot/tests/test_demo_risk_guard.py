from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.demo_profiles import apply_demo_strategy_defaults
from app.core.order_manager import OrderManager
from app.core.pair_manager import PairManager
from app.core.strategy_base import Signal, TradeSignal


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeOKXClient:
    async def get_account_balance(self):
        return {"data": [{"details": [{"ccy": "USDT", "availBal": "10000"}]}]}

    async def get_candles(self, pair: str, timeframe: str, limit: int):
        return [{"close": "100"}]

    async def set_leverage(self, pair: str, leverage: int):
        return {"ok": True}

    async def place_order(self, **kwargs):  # pragma: no cover - duplicate guard should prevent this
        raise AssertionError("place_order should not be called when duplicate position exists")


@pytest.mark.parametrize("mode,expected_profile", [("demo", "limited"), ("live", "default")])
def test_demo_strategy_defaults_only_force_limited_profile_in_demo(mode, expected_profile):
    params = {"risk_profile": "default", "risk_hard_stop_pct": 3.0}

    merged = apply_demo_strategy_defaults(
        strategy_name="rsi_bollinger_regime",
        params=params,
        okx_mode=mode,
    )

    assert merged["risk_profile"] == expected_profile
    if mode == "demo":
        assert merged["tail_risk_overlay_enabled"] is True
        assert merged["risk_hard_stop_pct"] == 3.0
    else:
        assert "tail_risk_overlay_enabled" not in merged


def test_pair_risk_policy_uses_prefixed_overlay_keys_over_strategy_keys():
    policy = PairManager._build_risk_policy(
        "rsi_bollinger_regime",
        {
            "tail_risk_overlay_enabled": True,
            "trailing_stop_pct": 0.025,  # strategy-level fraction, not overlay intent
            "risk_hard_stop_pct": 2.0,
            "risk_trailing_activation_pct": 1.5,
            "risk_trailing_stop_pct": 0.8,
            "risk_pause_after_losses": 3,
            "risk_pause_minutes": 1440,
        },
    )

    assert policy.enabled is True
    assert policy.hard_stop_pct == pytest.approx(2.0)
    assert policy.trailing_activation_pct == pytest.approx(1.5)
    assert policy.trailing_stop_pct == pytest.approx(0.8)
    assert policy.pause_after_losses == 3
    assert policy.pause_minutes == 1440


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("summaries", "expected_reason"),
    [
        (
            [
                {"total_pnl": -100.0, "trade_count": 1},
                {"total_pnl": 0.0, "trade_count": 0},
                {"total_pnl": 0.0, "trade_count": 0},
            ],
            "daily_loss_limit",
        ),
        (
            [
                {"total_pnl": 0.0, "trade_count": 0},
                {"total_pnl": -500.0, "trade_count": 3},
                {"total_pnl": 0.0, "trade_count": 0},
            ],
            "monthly_loss_limit",
        ),
    ],
)
async def test_circuit_breaker_trips_on_daily_and_monthly_loss_limits(summaries, expected_reason):
    calls = iter(summaries)

    async def fake_pnl_summary(session, source, since=None):
        return next(calls)

    cb = CircuitBreaker(
        session_factory=lambda: _FakeSessionCtx(),
        max_daily_loss=100.0,
        max_monthly_loss=500.0,
        starting_equity=10_000.0,
        max_total_drawdown_pct=10.0,
    )

    with patch("app.core.circuit_breaker.get_pnl_summary", new=fake_pnl_summary):
        assert await cb.check() is False

    assert cb.is_tripped is True
    assert cb.trip_reason == expected_reason


@pytest.mark.asyncio
async def test_circuit_breaker_trips_on_total_drawdown_limit():
    async def fake_pnl_summary(session, source, since=None):
        if since is None:
            return {"total_pnl": -1000.0, "trade_count": 5}
        return {"total_pnl": 0.0, "trade_count": 0}

    cb = CircuitBreaker(
        session_factory=lambda: _FakeSessionCtx(),
        max_daily_loss=100.0,
        max_monthly_loss=500.0,
        starting_equity=10_000.0,
        max_total_drawdown_pct=10.0,
    )

    with patch("app.core.circuit_breaker.get_pnl_summary", new=fake_pnl_summary):
        assert await cb.check() is False

    assert cb.is_tripped is True
    assert cb.trip_reason == "total_drawdown_limit"


@pytest.mark.asyncio
async def test_circuit_breaker_fails_closed_on_risk_check_error():
    async def failing_pnl_summary(session, source, since=None):
        raise RuntimeError("database unavailable")

    cb = CircuitBreaker(
        session_factory=lambda: _FakeSessionCtx(),
        max_daily_loss=100.0,
        max_monthly_loss=500.0,
        fail_closed_on_error=True,
    )

    with patch("app.core.circuit_breaker.get_pnl_summary", new=failing_pnl_summary):
        assert await cb.check() is False

    assert cb.is_tripped is True
    assert cb.trip_reason == "risk_check_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summaries",
    [
        [
            {"total_pnl": -100.0, "trade_count": 1},
            {"total_pnl": 0.0, "trade_count": 0},
            {"total_pnl": 0.0, "trade_count": 0},
        ],
        [
            {"total_pnl": 0.0, "trade_count": 0},
            {"total_pnl": -500.0, "trade_count": 3},
            {"total_pnl": 0.0, "trade_count": 0},
        ],
    ],
)
async def test_order_manager_blocks_entries_when_daily_or_monthly_limit_trips(summaries):
    calls = iter(summaries)

    async def fake_pnl_summary(session, source, since=None):
        return next(calls)

    settings = Settings(
        OKX_API_KEY="dummy",
        OKX_SECRET="dummy",
        OKX_PASSPHRASE="dummy",
        MAX_POSITION_SIZE_PCT=10.0,
    )
    client = _FakeOKXClient()
    client.get_account_balance = AsyncMock(side_effect=AssertionError("balance should not be fetched"))
    client.place_order = AsyncMock(side_effect=AssertionError("place_order should not be called"))
    circuit_breaker = CircuitBreaker(
        session_factory=lambda: _FakeSessionCtx(),
        max_daily_loss=100.0,
        max_monthly_loss=500.0,
        starting_equity=10_000.0,
        max_total_drawdown_pct=10.0,
    )
    order_manager = OrderManager(
        okx_client=client,
        session_factory=lambda: _FakeSessionCtx(),
        circuit_breaker=circuit_breaker,
        settings=settings,
    )

    with patch("app.core.circuit_breaker.get_pnl_summary", new=fake_pnl_summary):
        result = await order_manager.open_position(
            "BTC-USDT-SWAP",
            TradeSignal(signal=Signal.LONG, pair="BTC-USDT-SWAP", leverage=2),
            strategy_name="rsi_bollinger_regime",
        )

    assert result is None
    client.get_account_balance.assert_not_awaited()
    client.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_order_manager_blocks_duplicate_open_position_before_order_placement():
    settings = Settings(
        OKX_API_KEY="dummy",
        OKX_SECRET="dummy",
        OKX_PASSPHRASE="dummy",
        MAX_POSITION_SIZE_PCT=10.0,
    )
    client = _FakeOKXClient()
    client.place_order = AsyncMock(side_effect=AssertionError("place_order should not be called"))
    order_manager = OrderManager(
        okx_client=client,
        session_factory=lambda: _FakeSessionCtx(),
        circuit_breaker=SimpleNamespace(check=AsyncMock(return_value=True)),
        settings=settings,
    )

    with patch(
        "app.core.order_manager.repo.get_position",
        new=AsyncMock(return_value=SimpleNamespace(pair="BTC-USDT-SWAP")),
    ):
        result = await order_manager.open_position(
            "BTC-USDT-SWAP",
            TradeSignal(signal=Signal.LONG, pair="BTC-USDT-SWAP", leverage=2),
            strategy_name="rsi_bollinger_regime",
        )

    assert result is None
    client.place_order.assert_not_awaited()
