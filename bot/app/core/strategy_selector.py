"""Auto strategy selector: analyses market regime and recommends the best strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StrategyScore:
    strategy_name: str
    sharpe_ratio: float
    total_pnl: float
    win_rate: float
    regime_fit: float  # 0.0-1.0, how well this strategy type fits the regime
    composite_score: float  # weighted combination


@dataclass
class SelectionResult:
    pair: str
    regime: dict  # RegimeResult as dict
    recommended_strategy: str
    recommended_params: dict
    scores: list[StrategyScore]  # all strategies ranked
    reasoning: str  # human-readable explanation


# ---------------------------------------------------------------------------
# Regime-fit mapping
# ---------------------------------------------------------------------------

REGIME_FIT: dict[str, dict[str, float]] = {
    "trending_up": {
        "ma_7d_5m": 0.9,
        "example_sma_cross": 0.9,
        "macd_strategy": 0.85,
        "breakout_strategy": 0.9,
        "multi_ema": 0.95,
        "volume_momentum": 0.8,
        "example_rsi": 0.3,
        "bollinger_band": 0.4,
        "mean_reversion": 0.2,
        "rsi_bollinger_combo": 0.35,
        "elliott_wave_fib": 0.7,
    },
    "trending_down": {
        "ma_7d_5m": 0.9,
        "example_sma_cross": 0.85,
        "macd_strategy": 0.85,
        "breakout_strategy": 0.85,
        "multi_ema": 0.9,
        "volume_momentum": 0.75,
        "example_rsi": 0.4,
        "bollinger_band": 0.45,
        "mean_reversion": 0.3,
        "rsi_bollinger_combo": 0.4,
        "elliott_wave_fib": 0.65,
    },
    "ranging": {
        "example_rsi": 0.9,
        "bollinger_band": 0.95,
        "mean_reversion": 0.95,
        "rsi_bollinger_combo": 0.9,
        "elliott_wave_fib": 0.5,
        "ma_7d_5m": 0.2,
        "example_sma_cross": 0.2,
        "macd_strategy": 0.3,
        "breakout_strategy": 0.1,
        "multi_ema": 0.15,
        "volume_momentum": 0.3,
    },
    "volatile": {
        "elliott_wave_fib": 0.8,
        "mean_reversion": 0.7,
        "rsi_bollinger_combo": 0.75,
        "bollinger_band": 0.65,
        "example_rsi": 0.6,
        "breakout_strategy": 0.5,
        "volume_momentum": 0.6,
        "ma_7d_5m": 0.35,
        "example_sma_cross": 0.3,
        "macd_strategy": 0.4,
        "multi_ema": 0.35,
    },
}

# Strategy descriptions for reasoning
_STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "ma_7d_5m": "uses a 5-minute 7-day SMA cross with Bollinger Band volatility filters and dynamic take-profit",
    "multi_ema": "buys pullbacks to the medium EMA during confirmed uptrends",
    "example_sma_cross": "uses SMA crossover signals to capture trend changes",
    "macd_strategy": "uses MACD histogram divergence to detect momentum shifts",
    "breakout_strategy": "enters on price breakouts above resistance levels",
    "volume_momentum": "combines volume spikes with momentum indicators",
    "example_rsi": "trades overbought/oversold RSI levels for mean reversion",
    "bollinger_band": "trades Bollinger Band bounces in ranging markets",
    "mean_reversion": "captures price reversals back to the mean",
    "rsi_bollinger_combo": "combines RSI extremes with BB levels for high-probability entries",
    "elliott_wave_fib": "identifies Elliott Wave patterns with Fibonacci retracements",
}

_REGIME_LABELS: dict[str, str] = {
    "trending_up": "TRENDING UP",
    "trending_down": "TRENDING DOWN",
    "ranging": "RANGING",
    "volatile": "VOLATILE",
}

_REGIME_STRATEGY_TYPE: dict[str, str] = {
    "trending_up": "trend-following strategies perform best in strong uptrends",
    "trending_down": "trend-following strategies perform best in strong downtrends",
    "ranging": "mean-reversion strategies perform best in range-bound markets",
    "volatile": "adaptive strategies perform best in highly volatile conditions",
}


class StrategySelector:
    """Selects the best strategy for the current market regime."""

    def __init__(self, session_factory, okx_client) -> None:
        self._session_factory = session_factory
        self._okx_client = okx_client

    async def select(
        self,
        pair: str,
        timeframe: str = "1H",
        lookback_days: int = 30,
        initial_balance: float = 10000,
        leverage: int = 1,
    ) -> SelectionResult:
        """Analyse recent market data and recommend the best strategy.

        1. Fetch recent candles via OKX API
        2. Detect market regime
        3. Run quick backtests for each registered strategy
        4. Score and rank strategies
        5. Return recommendation with reasoning
        """
        from app.core.backtest_engine import BacktestEngine
        from app.core.regime_detector import MarketRegimeDetector, RegimeResult
        from app.core.strategy_registry import registry
        from app.exchange.data_collector import DataCollector

        log = logger.bind(pair=pair, timeframe=timeframe, lookback_days=lookback_days)
        log.info("strategy_selection_started")

        end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        start_dt = end_dt - timedelta(days=lookback_days)

        # -------------------------------------------------------------- #
        # 1. Fetch candles and persist for backtesting                    #
        # -------------------------------------------------------------- #
        async with self._session_factory() as session:
            collector = DataCollector(okx_client=self._okx_client, db_session=session)
            candle_count = await collector.fetch_historical_candles(
                pair=pair,
                timeframe=timeframe,
                start_date=start_dt,
                end_date=end_dt,
            )
            await session.commit()
            log.info("candles_fetched_for_selection", count=candle_count)

        # -------------------------------------------------------------- #
        # 2. Fetch raw candle data for regime detection                    #
        # -------------------------------------------------------------- #
        raw_candles = await self._okx_client.get_candles(pair=pair, timeframe=timeframe, limit=100)

        if not raw_candles:
            return SelectionResult(
                pair=pair,
                regime={"regime": "ranging", "confidence": 0.0, "adx": 0.0, "volatility": 0.0, "trend_direction": 0.0, "details": {}},
                recommended_strategy="",
                recommended_params={},
                scores=[],
                reasoning="No candle data available for analysis.",
            )

        # Sort oldest first (OKX returns newest first)
        raw_candles.sort(key=lambda c: c["timestamp"])

        closes = [c["close"] for c in raw_candles]
        volumes = [c["volume"] for c in raw_candles]
        highs = [c["high"] for c in raw_candles]
        lows = [c["low"] for c in raw_candles]

        detector = MarketRegimeDetector()
        regime = detector.detect(closes=closes, volumes=volumes, highs=highs, lows=lows)

        log.info("regime_detected_for_selection", regime=regime.regime, confidence=regime.confidence)

        # -------------------------------------------------------------- #
        # 3. Run quick backtests for each strategy                        #
        # -------------------------------------------------------------- #
        strategy_names = registry.list_all()
        scores: list[StrategyScore] = []
        regime_fit_map = REGIME_FIT.get(regime.regime, {})

        for strategy_name in strategy_names:
            log_strat = log.bind(strategy=strategy_name)
            try:
                async with self._session_factory() as session:
                    strategy_cls = registry.get(strategy_name)
                    strategy_inst = strategy_cls()
                    strategy_inst.configure({})

                    engine = BacktestEngine(db_session=session)
                    bt_result = await engine.run(
                        strategy=strategy_inst,
                        pair=pair,
                        timeframe=timeframe,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_balance=initial_balance,
                        leverage=leverage,
                    )
                    await session.commit()

                scores.append(
                    StrategyScore(
                        strategy_name=strategy_name,
                        sharpe_ratio=bt_result.sharpe_ratio,
                        total_pnl=bt_result.total_pnl,
                        win_rate=bt_result.win_rate,
                        regime_fit=regime_fit_map.get(strategy_name, 0.5),
                        composite_score=0.0,  # computed below
                    )
                )
                log_strat.info(
                    "selection_backtest_complete",
                    sharpe=bt_result.sharpe_ratio,
                    pnl=bt_result.total_pnl,
                    win_rate=bt_result.win_rate,
                )

            except Exception as exc:
                log_strat.error("selection_backtest_failed", error=str(exc))
                scores.append(
                    StrategyScore(
                        strategy_name=strategy_name,
                        sharpe_ratio=0.0,
                        total_pnl=0.0,
                        win_rate=0.0,
                        regime_fit=regime_fit_map.get(strategy_name, 0.5),
                        composite_score=0.0,
                    )
                )

        # -------------------------------------------------------------- #
        # 4. Compute composite scores                                      #
        # -------------------------------------------------------------- #
        _compute_composite_scores(scores)

        # Sort by composite_score descending
        scores.sort(key=lambda s: s.composite_score, reverse=True)

        # -------------------------------------------------------------- #
        # 5. Build result                                                  #
        # -------------------------------------------------------------- #
        best = scores[0] if scores else None
        recommended_name = best.strategy_name if best else ""

        reasoning = _build_reasoning(regime, best)

        regime_dict = {
            "regime": regime.regime,
            "confidence": regime.confidence,
            "adx": regime.adx,
            "volatility": regime.volatility,
            "trend_direction": regime.trend_direction,
            "details": regime.details,
        }

        # Round numeric fields for clean API output
        for s in scores:
            s.sharpe_ratio = round(s.sharpe_ratio, 4)
            s.total_pnl = round(s.total_pnl, 2)
            s.win_rate = round(s.win_rate, 4)
            s.regime_fit = round(s.regime_fit, 4)
            s.composite_score = round(s.composite_score, 4)

        log.info("strategy_selection_complete", recommended=recommended_name)

        return SelectionResult(
            pair=pair,
            regime=regime_dict,
            recommended_strategy=recommended_name,
            recommended_params={},
            scores=scores,
            reasoning=reasoning,
        )


def _compute_composite_scores(scores: list[StrategyScore]) -> None:
    """Compute composite_score for each strategy using weighted combination.

    composite = 0.4 * normalized_sharpe + 0.3 * regime_fit + 0.2 * normalized_win_rate + 0.1 * normalized_pnl
    """
    if not scores:
        return

    # Collect raw values
    sharpes = [s.sharpe_ratio for s in scores]
    win_rates = [s.win_rate for s in scores]
    pnls = [s.total_pnl for s in scores]

    # Normalize each metric to 0-1 range
    norm_sharpe = _normalize(sharpes)
    norm_wr = _normalize(win_rates)
    norm_pnl = _normalize(pnls)

    for i, s in enumerate(scores):
        s.composite_score = (
            0.4 * norm_sharpe[i]
            + 0.3 * s.regime_fit
            + 0.2 * norm_wr[i]
            + 0.1 * norm_pnl[i]
        )


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize a list of values to 0-1 range."""
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    rng = max_v - min_v
    if rng == 0:
        return [0.5] * len(values)
    return [(v - min_v) / rng for v in values]


def _build_reasoning(regime, best: StrategyScore | None) -> str:
    """Build a human-readable reasoning string."""
    from app.core.regime_detector import RegimeResult

    label = _REGIME_LABELS.get(regime.regime, regime.regime.upper())
    if best is None:
        return f"Market is {label} but no strategies could be evaluated."

    strat_desc = _STRATEGY_DESCRIPTIONS.get(best.strategy_name, "applies its trading logic")
    regime_why = _REGIME_STRATEGY_TYPE.get(regime.regime, "adapts to current conditions")

    return (
        f"Market is {label} (ADX: {regime.adx:.0f}, confidence: {regime.confidence:.2f}). "
        f"Recommended: {best.strategy_name} (score: {best.composite_score:.2f}) — "
        f"{regime_why}. This strategy {strat_desc}."
    )
