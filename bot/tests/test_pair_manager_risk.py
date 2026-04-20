import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.pair_manager import PairManager, PairRiskPolicy, PairRiskState, PairStatus


class PairManagerRiskHelpersTest(unittest.TestCase):
    def test_build_risk_policy_defaults_for_chronos(self) -> None:
        policy = PairManager._build_risk_policy("chronos_regime_hybrid", {})
        self.assertTrue(policy.enabled)
        self.assertAlmostEqual(policy.hard_stop_pct, 0.35)
        self.assertEqual(policy.time_stop_candles, 8)
        self.assertAlmostEqual(policy.degrade_size_scale, 0.5)

    def test_build_risk_policy_override(self) -> None:
        policy = PairManager._build_risk_policy(
            "chronos_regime_hybrid",
            {
                "tail_risk_overlay_enabled": "true",
                "hard_stop_pct": 0.5,
                "trailing_activation_pct": 0.4,
                "trailing_stop_pct": 0.2,
                "time_stop_candles": 12,
                "time_stop_edge_pct": 0.05,
                "degrade_after_losses": 3,
                "pause_after_losses": 4,
                "degrade_size_scale": 0.4,
                "pause_minutes": 180,
            },
        )
        self.assertTrue(policy.enabled)
        self.assertAlmostEqual(policy.hard_stop_pct, 0.5)
        self.assertAlmostEqual(policy.trailing_activation_pct, 0.4)
        self.assertAlmostEqual(policy.trailing_stop_pct, 0.2)
        self.assertEqual(policy.time_stop_candles, 12)
        self.assertAlmostEqual(policy.time_stop_edge_pct, 0.05)
        self.assertEqual(policy.degrade_after_losses, 3)
        self.assertEqual(policy.pause_after_losses, 4)
        self.assertAlmostEqual(policy.degrade_size_scale, 0.4)
        self.assertEqual(policy.pause_minutes, 180)

    def test_extract_edge_pct(self) -> None:
        self.assertAlmostEqual(
            PairManager._extract_edge_pct("chronos_hold edge=-0.213% uncertainty=2.085%"),
            -0.213,
        )
        self.assertIsNone(PairManager._extract_edge_pct("no edge marker"))

    def test_move_pct(self) -> None:
        self.assertAlmostEqual(PairManager._move_pct("long", 100.0, 101.0), 1.0)
        self.assertAlmostEqual(PairManager._move_pct("short", 100.0, 99.0), 1.0)
        self.assertAlmostEqual(PairManager._move_pct("long", 100.0, 99.5), -0.5)
        self.assertAlmostEqual(PairManager._move_pct("short", 100.0, 100.5), -0.5)


class _DummyLog:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _FakeOKXClient:
    async def get_candles(self, pair: str, timeframe: str, limit: int):
        # Exchange shape is newest-first; pair manager reverses this to oldest->newest.
        return [
            {"timestamp": "2000", "open": "100", "high": "101", "low": "99", "close": "99.5", "volume": "10", "confirm": "1"},
            {"timestamp": "1000", "open": "100", "high": "101", "low": "99", "close": "100", "volume": "10", "confirm": "1"},
        ]

    async def get_funding_rate(self, pair: str):
        return None


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class PairManagerRiskLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_hard_stop_marks_last_candle_and_skips_strategy_eval(self) -> None:
        order_manager = SimpleNamespace(
            open_position=AsyncMock(return_value=None),
            close_position=AsyncMock(return_value={"ok": True}),
        )
        pm = PairManager(
            okx_client=_FakeOKXClient(),
            session_factory=lambda: _FakeSessionCtx(),
            order_manager=order_manager,
            strategy_registry=SimpleNamespace(get=lambda _: None),
        )

        pair = "ETH-USDT-SWAP"
        pm._pair_status[pair] = PairStatus(
            pair=pair,
            strategy_name="chronos_regime_hybrid",
            timeframe="15m",
            status="running",
            leverage=5,
        )
        pm._pair_risk_policy[pair] = PairRiskPolicy(
            enabled=True,
            hard_stop_pct=0.35,
            trailing_activation_pct=0.25,
            trailing_stop_pct=0.18,
            time_stop_candles=8,
            time_stop_edge_pct=0.03,
            degrade_after_losses=2,
            pause_after_losses=3,
            degrade_size_scale=0.5,
            pause_minutes=120,
        )
        pm._pair_risk_state[pair] = PairRiskState()

        strategy = SimpleNamespace(
            name="chronos_regime_hybrid",
            lookback_period=1,
            on_candle=AsyncMock(),
        )

        with patch("app.core.pair_manager.repo.get_position", new=AsyncMock(return_value=SimpleNamespace(
            direction="long",
            entry_price=100.0,
            quantity=1.0,
            unrealized_pnl=0.0,
        ))):
            pm._record_close_outcome = AsyncMock()
            await pm._pair_loop_iteration(
                pair=pair,
                strategy=strategy,
                leverage=5,
                timeframe="15m",
                log=_DummyLog(),
            )

        status = pm._pair_status[pair]
        self.assertEqual(status.last_signal, "close")
        self.assertEqual(status.last_candle_ts, "2000")
        order_manager.close_position.assert_awaited_once()
        strategy.on_candle.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
