"""Backtest engine: replay historical candles through a strategy and record results."""

import asyncio
import math
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.strategy_base import BaseStrategy, Signal, TradingContext, TradeSignal
from app.db import repository as repo
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class _SimPosition:
    """Ephemeral simulated position held during a backtest run."""

    direction: str          # "buy" | "sell"
    entry_price: float
    quantity: float         # notional USDT
    leverage: int
    entry_time: datetime
    entry_fee: float
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    high_water_mark: Optional[float] = None  # for trailing stop
    funding_pnl: float = 0.0
    candles_held: int = 0


@dataclass
class _ClosedTrade:
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    leverage: int
    pnl: float
    pnl_pct: float
    fee: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str = ""  # "signal", "tp", "sl", "trailing_stop", "stop_loss_pct", "end_of_data"
    funding_pnl: float = 0.0
    liquidation_fee: float = 0.0


@dataclass
class BacktestResult:
    run_id: uuid.UUID
    strategy_name: str
    pair: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float
    total_pnl: float
    win_rate: float           # 0.0 – 1.0
    max_drawdown: float       # expressed as a positive fraction (e.g. 0.15 = 15%)
    sharpe_ratio: float       # annualised
    trade_count: int
    trades: list[_ClosedTrade] = field(default_factory=list)
    balance_series: list[float] = field(default_factory=list)
    drawdown_series: list[float] = field(default_factory=list)
    buy_hold_pnl: float = 0.0
    buy_hold_return_pct: float = 0.0


def _candle_to_dict(candle) -> dict:
    """Convert a Candle ORM object to a plain dict for strategy consumption."""
    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def _compute_metrics(
    trades: list[_ClosedTrade],
    initial_balance: float,
    balance_series: list[float],
) -> tuple[float, float, float, float]:
    """Return (total_pnl, win_rate, max_drawdown, sharpe_ratio)."""
    total_pnl = sum(t.pnl for t in trades)
    trade_count = len(trades)

    win_rate = (
        sum(1 for t in trades if t.pnl > 0) / trade_count if trade_count else 0.0
    )

    # Max drawdown from peak equity
    peak = initial_balance
    max_dd = 0.0
    for bal in balance_series:
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Annualised Sharpe ratio from per-trade returns
    # Using 252 trading days as the annualisation factor
    if trade_count < 2:
        sharpe = 0.0
    else:
        returns = [t.pnl / initial_balance for t in trades]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    return total_pnl, win_rate, max_dd, sharpe


def _close_position(
    position: _SimPosition,
    raw_price: float,
    slippage_pct: float,
    fee_rate: float,
    exit_time: datetime,
    exit_reason: str,
    funding_pnl: float = 0.0,
    liquidation_fee: float = 0.0,
) -> tuple[_ClosedTrade, float]:
    """Close a position and return (closed_trade, net_pnl)."""
    if position.direction == "buy":
        exit_price = raw_price * (1 - slippage_pct / 100)
        price_return = (exit_price - position.entry_price) / position.entry_price
    else:
        exit_price = raw_price * (1 + slippage_pct / 100)
        price_return = (position.entry_price - exit_price) / position.entry_price

    gross_pnl = position.quantity * price_return * position.leverage
    exit_fee = position.quantity * fee_rate
    net_pnl = gross_pnl - exit_fee + funding_pnl - liquidation_fee
    pnl_pct = (net_pnl / position.quantity) * 100.0 if position.quantity else 0.0

    trade = _ClosedTrade(
        direction=position.direction,
        entry_price=position.entry_price,
        exit_price=exit_price,
        quantity=position.quantity,
        leverage=position.leverage,
        pnl=net_pnl,
        pnl_pct=pnl_pct,
        fee=position.entry_fee + exit_fee + liquidation_fee,
        entry_time=position.entry_time,
        exit_time=exit_time,
        exit_reason=exit_reason,
        funding_pnl=funding_pnl,
        liquidation_fee=liquidation_fee,
    )
    return trade, net_pnl


def _timeframe_to_minutes(timeframe: str) -> int:
    tf = str(timeframe or "1m").strip()
    try:
        if tf.endswith("m"):
            return max(1, int(tf[:-1]))
        if tf.endswith("H") or tf.endswith("h"):
            return max(1, int(tf[:-1])) * 60
        if tf.endswith("D") or tf.endswith("d"):
            return max(1, int(tf[:-1])) * 60 * 24
        if tf.endswith("W") or tf.endswith("w"):
            return max(1, int(tf[:-1])) * 60 * 24 * 7
    except Exception:
        pass
    return 1


def _effective_slippage_pct(
    *,
    base_slippage_pct: float,
    notional: float,
    price: float,
    volume: float,
    liquidity_impact_factor: float,
) -> float:
    """Return slippage percent with simple liquidity impact model."""
    base = max(0.0, float(base_slippage_pct))
    if liquidity_impact_factor <= 0 or price <= 0 or volume <= 0 or notional <= 0:
        return base
    est_quote_liquidity = price * volume
    if est_quote_liquidity <= 0:
        return base
    impact_pct = max(0.0, float(liquidity_impact_factor)) * (notional / est_quote_liquidity) * 100.0
    return base + impact_pct


def _simulate_sync(
    candles: list,
    strategy_lookback: int,
    timeframe: str,
    initial_balance: float,
    leverage: int,
    fee_rate: float,
    slippage_pct: float,
    signals: list[TradeSignal],
    stop_loss_pct: float = 0.03,
    cooldown_candles: int = 0,
    funding_rate_per_8h: float = 0.0,
    liquidity_impact_factor: float = 0.0,
    maintenance_margin_ratio: float = 0.005,
    liquidation_fee_pct: float = 0.002,
) -> tuple[list[_ClosedTrade], list[float], float]:
    """Pure CPU computation — run inside asyncio.to_thread to avoid blocking.

    Returns (closed_trades, balance_series, final_balance).

    Supports: per-signal TP/SL prices, trailing stops, cooldown after stop-loss,
    and the legacy stop_loss_pct fallback.
    """
    balance = initial_balance
    balance_series: list[float] = [balance]
    closed_trades: list[_ClosedTrade] = []
    position: Optional[_SimPosition] = None
    cooldown_remaining: int = 0
    timeframe_minutes = _timeframe_to_minutes(timeframe)
    funding_interval_candles = max(1, int((8 * 60) / max(1, timeframe_minutes)))

    for i, candle in enumerate(candles):
        if i >= len(signals):
            break

        sig = signals[i]
        if i + 1 < len(candles):
            raw_price = candles[i + 1].open
        else:
            raw_price = candle.close

        # Decrement cooldown
        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        # --- Flip: if in position and opposite signal comes, close then re-enter ---
        if sig.signal in (Signal.LONG, Signal.SHORT) and position is not None:
            current_dir = position.direction
            new_dir = "buy" if sig.signal == Signal.LONG else "sell"
            if current_dir != new_dir:
                effective_slip = _effective_slippage_pct(
                    base_slippage_pct=slippage_pct,
                    notional=position.quantity,
                    price=float(candle.close),
                    volume=float(getattr(candle, "volume", 0.0) or 0.0),
                    liquidity_impact_factor=liquidity_impact_factor,
                )
                trade, net_pnl = _close_position(
                    position,
                    raw_price,
                    effective_slip,
                    fee_rate,
                    candle.timestamp,
                    "signal_flip",
                    funding_pnl=position.funding_pnl,
                )
                balance += net_pnl
                balance_series.append(balance)
                closed_trades.append(trade)
                position = None

        # --- Open new position (respect cooldown) ---
        if sig.signal in (Signal.LONG, Signal.SHORT) and position is None:
            if cooldown_remaining > 0:
                pass  # skip entry during cooldown
            else:
                effective_slip = _effective_slippage_pct(
                    base_slippage_pct=slippage_pct,
                    notional=balance * (sig.size_pct / 100.0),
                    price=raw_price,
                    volume=float(getattr(candle, "volume", 0.0) or 0.0),
                    liquidity_impact_factor=liquidity_impact_factor,
                )
                slippage_mult = (1 + effective_slip / 100) if sig.signal == Signal.LONG else (1 - effective_slip / 100)
                entry_price = raw_price * slippage_mult
                notional = balance * (sig.size_pct / 100.0)
                entry_fee = notional * fee_rate
                balance -= entry_fee
                direction = "buy" if sig.signal == Signal.LONG else "sell"
                position = _SimPosition(
                    direction=direction,
                    entry_price=entry_price,
                    quantity=notional,
                    leverage=leverage,
                    entry_time=candle.timestamp,
                    entry_fee=entry_fee,
                    tp_price=sig.tp_price,
                    sl_price=sig.sl_price,
                    trailing_stop_pct=sig.trailing_stop_pct,
                    high_water_mark=entry_price,
                    funding_pnl=0.0,
                    candles_held=0,
                )

        elif sig.signal == Signal.CLOSE and position is not None:
            effective_slip = _effective_slippage_pct(
                base_slippage_pct=slippage_pct,
                notional=position.quantity,
                price=float(candle.close),
                volume=float(getattr(candle, "volume", 0.0) or 0.0),
                liquidity_impact_factor=liquidity_impact_factor,
            )
            trade, net_pnl = _close_position(
                position,
                raw_price,
                effective_slip,
                fee_rate,
                candle.timestamp,
                "signal",
                funding_pnl=position.funding_pnl,
            )
            balance += net_pnl
            balance_series.append(balance)
            closed_trades.append(trade)
            position = None

        # --- TP/SL/Trailing/StopLossPct checks on current candle ---
        if position is not None:
            exit_reason = ""
            exit_price_override: Optional[float] = None
            liquidation_fee = 0.0
            position.candles_held += 1

            # Periodic funding (8h) approximation.
            if funding_rate_per_8h != 0 and position.candles_held % funding_interval_candles == 0:
                # Positive funding: longs pay, shorts receive.
                direction_sign = -1.0 if position.direction == "buy" else 1.0
                funding_delta = position.quantity * funding_rate_per_8h * direction_sign
                position.funding_pnl += funding_delta

            # Liquidation check (simplified).
            liq_move = max(0.001, (1.0 / max(position.leverage, 1)) - maintenance_margin_ratio)
            if position.direction == "buy":
                liq_price = position.entry_price * (1.0 - liq_move)
                if candle.low <= liq_price:
                    exit_reason = "liquidated"
                    exit_price_override = liq_price
                    liquidation_fee = position.quantity * max(0.0, liquidation_fee_pct)
            else:
                liq_price = position.entry_price * (1.0 + liq_move)
                if candle.high >= liq_price:
                    exit_reason = "liquidated"
                    exit_price_override = liq_price
                    liquidation_fee = position.quantity * max(0.0, liquidation_fee_pct)

            # Update trailing stop high-water mark
            if not exit_reason and position.trailing_stop_pct is not None:
                if position.direction == "buy":
                    if candle.high > (position.high_water_mark or 0):
                        position.high_water_mark = candle.high
                else:
                    if position.high_water_mark is None or candle.low < position.high_water_mark:
                        position.high_water_mark = candle.low

            # Check take-profit
            if position.tp_price is not None:
                if position.direction == "buy" and candle.high >= position.tp_price:
                    exit_price_override = position.tp_price
                    exit_reason = "tp"
                elif position.direction == "sell" and candle.low <= position.tp_price:
                    exit_price_override = position.tp_price
                    exit_reason = "tp"

            # Check per-signal stop-loss
            if not exit_reason and position.sl_price is not None:
                if position.direction == "buy" and candle.low <= position.sl_price:
                    exit_price_override = position.sl_price
                    exit_reason = "sl"
                elif position.direction == "sell" and candle.high >= position.sl_price:
                    exit_price_override = position.sl_price
                    exit_reason = "sl"

            # Check trailing stop
            if not exit_reason and position.trailing_stop_pct is not None and position.high_water_mark is not None:
                if position.direction == "buy":
                    trail_stop = position.high_water_mark * (1 - position.trailing_stop_pct)
                    if candle.low <= trail_stop:
                        exit_price_override = trail_stop
                        exit_reason = "trailing_stop"
                else:
                    trail_stop = position.high_water_mark * (1 + position.trailing_stop_pct)
                    if candle.high >= trail_stop:
                        exit_price_override = trail_stop
                        exit_reason = "trailing_stop"

            # Fallback: legacy stop_loss_pct
            if not exit_reason and stop_loss_pct > 0:
                if position.direction == "buy":
                    stop_price = position.entry_price * (1 - stop_loss_pct)
                    if candle.low <= stop_price:
                        exit_price_override = stop_price
                        exit_reason = "stop_loss_pct"
                elif position.direction == "sell":
                    stop_price = position.entry_price * (1 + stop_loss_pct)
                    if candle.high >= stop_price:
                        exit_price_override = stop_price
                        exit_reason = "stop_loss_pct"

            # Execute exit if triggered
            if exit_reason and exit_price_override is not None:
                effective_slip = _effective_slippage_pct(
                    base_slippage_pct=slippage_pct,
                    notional=position.quantity,
                    price=float(candle.close),
                    volume=float(getattr(candle, "volume", 0.0) or 0.0),
                    liquidity_impact_factor=liquidity_impact_factor,
                )
                trade, net_pnl = _close_position(
                    position,
                    exit_price_override,
                    effective_slip,
                    fee_rate,
                    candle.timestamp,
                    exit_reason,
                    funding_pnl=position.funding_pnl,
                    liquidation_fee=liquidation_fee,
                )
                balance += net_pnl
                balance_series.append(balance)
                closed_trades.append(trade)
                position = None
                # Activate cooldown on stop-loss exits
                if exit_reason in ("sl", "stop_loss_pct", "trailing_stop") and cooldown_candles > 0:
                    cooldown_remaining = cooldown_candles

    # Force-close any open position at the last candle's close
    if position is not None:
        last = candles[-1]
        effective_slip = _effective_slippage_pct(
            base_slippage_pct=slippage_pct,
            notional=position.quantity,
            price=float(last.close),
            volume=float(getattr(last, "volume", 0.0) or 0.0),
            liquidity_impact_factor=liquidity_impact_factor,
        )
        trade, net_pnl = _close_position(
            position,
            last.close,
            effective_slip,
            fee_rate,
            last.timestamp,
            "end_of_data",
            funding_pnl=position.funding_pnl,
        )
        balance += net_pnl
        balance_series.append(balance)
        closed_trades.append(trade)

    return closed_trades, balance_series, balance


class BacktestEngine:
    """Replay historical candles through a strategy and persist the results."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def run(
        self,
        strategy: BaseStrategy,
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        leverage: int,
        fee_rate: float = 0.0005,
        slippage_pct: float = 0.05,
        stop_loss_pct: float = 0.03,
        cooldown_candles: int = 0,
        funding_rate_per_8h: float = 0.0,
        liquidity_impact_factor: float = 0.0,
        maintenance_margin_ratio: float = 0.005,
        liquidation_fee_pct: float = 0.002,
        persist: bool = True,
    ) -> BacktestResult:
        """Execute a backtest and return a :class:`BacktestResult`.

        1. Loads candles from the DB for the requested range.
        2. Calls strategy.on_candle() for every candle with a sliding lookback
           window to collect signals (async, serial).
        3. Off-loads the CPU-heavy P&L simulation to a thread.
        4. Persists BacktestRun + Trade rows to the DB (unless *persist* is False).
        """
        log = logger.bind(
            strategy=strategy.name,
            pair=pair,
            timeframe=timeframe,
        )
        log.info(
            "backtest_start",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_balance=initial_balance,
            leverage=leverage,
        )

        # ---------------------------------------------------------------- #
        # 1. Load candles                                                    #
        # ---------------------------------------------------------------- #
        candles = await repo.get_candles(
            self._session, pair, timeframe, start_date, end_date
        )
        if len(candles) < strategy.lookback_period + 1:
            log.warning(
                "backtest_insufficient_candles",
                available=len(candles),
                required=strategy.lookback_period + 1,
            )

        log.info("backtest_candles_loaded", count=len(candles))

        # ---------------------------------------------------------------- #
        # 2. Collect signals via strategy.on_candle()                       #
        # ---------------------------------------------------------------- #
        await strategy.on_start()

        lookback = strategy.lookback_period
        history_window: deque[dict] = deque(maxlen=lookback)
        signals: list[TradeSignal] = []

        # Simulated context — position state is managed by the simulation step
        sim_balance = initial_balance
        sim_position: Optional[dict] = None

        for candle in candles:
            candle_dict = _candle_to_dict(candle)
            history = list(history_window)

            ctx = TradingContext(
                current_position=sim_position,
                account_balance=sim_balance,
                leverage=leverage,
                pair=pair,
            )

            try:
                signal = await strategy.on_candle(candle_dict, history, ctx)
            except Exception as exc:
                log.error(
                    "backtest_strategy_error",
                    candle_ts=candle.timestamp.isoformat(),
                    error=str(exc),
                )
                signal = TradeSignal(
                    signal=Signal.HOLD, pair=pair, leverage=leverage
                )

            signals.append(signal)

            # Keep a lightweight sim_position for context accuracy
            if signal.signal in (Signal.LONG, Signal.SHORT):
                new_dir = "buy" if signal.signal == Signal.LONG else "sell"
                # If no position, open. If opposite direction, flip.
                if sim_position is None or sim_position.get("direction") != new_dir:
                    sim_position = {
                        "direction": new_dir,
                        "entry_price": candle.close,
                        "quantity": sim_balance * (signal.size_pct / 100.0),
                        "unrealized_pnl": 0.0,
                    }
            elif signal.signal == Signal.CLOSE:
                sim_position = None

            history_window.append(candle_dict)

        await strategy.on_stop()

        # ---------------------------------------------------------------- #
        # 3. CPU-heavy P&L simulation in thread                             #
        # ---------------------------------------------------------------- #
        closed_trades, balance_series, final_balance = await asyncio.to_thread(
            _simulate_sync,
            candles,
            lookback,
            timeframe,
            initial_balance,
            leverage,
            fee_rate,
            slippage_pct,
            signals,
            stop_loss_pct,
            cooldown_candles,
            funding_rate_per_8h,
            liquidity_impact_factor,
            maintenance_margin_ratio,
            liquidation_fee_pct,
        )

        total_pnl, win_rate, max_drawdown, sharpe_ratio = _compute_metrics(
            closed_trades, initial_balance, balance_series
        )

        # Compute drawdown series from balance_series
        drawdown_series: list[float] = []
        peak = initial_balance
        for bal in balance_series:
            if bal > peak:
                peak = bal
            dd = -((peak - bal) / peak) if peak > 0 else 0.0
            drawdown_series.append(dd)

        # Buy & Hold benchmark
        buy_hold_pnl = 0.0
        buy_hold_return_pct = 0.0
        if len(candles) >= 2:
            first_open = candles[0].open
            last_close = candles[-1].close
            if first_open > 0:
                bh_return = (last_close - first_open) / first_open
                buy_hold_pnl = initial_balance * bh_return * leverage
                buy_hold_return_pct = bh_return * leverage * 100.0

        log.info(
            "backtest_complete",
            trade_count=len(closed_trades),
            total_pnl=total_pnl,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            final_balance=final_balance,
            buy_hold_pnl=buy_hold_pnl,
        )

        # ---------------------------------------------------------------- #
        # 4. Persist BacktestRun + Trades                                   #
        # ---------------------------------------------------------------- #
        run_id: uuid.UUID

        if persist:
            run = await repo.create_backtest_run(
                self._session,
                {
                    "strategy_name": strategy.name,
                    "pair": pair,
                    "timeframe": timeframe,
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_balance": initial_balance,
                    "leverage": leverage,
                    "fee_rate": fee_rate,
                    "slippage_pct": slippage_pct,
                    "total_pnl": total_pnl,
                    "win_rate": win_rate,
                    "max_drawdown": max_drawdown,
                    "sharpe_ratio": sharpe_ratio,
                    "trade_count": len(closed_trades),
                },
            )
            run_id = run.id

            for t in closed_trades:
                try:
                    await repo.create_trade(
                        self._session,
                        {
                            "strategy_name": strategy.name,
                            "pair": pair,
                            "direction": t.direction,
                            "entry_price": t.entry_price,
                            "exit_price": t.exit_price,
                            "quantity": t.quantity,
                            "leverage": t.leverage,
                            "pnl": t.pnl,
                            "pnl_pct": t.pnl_pct,
                            "fee": t.fee,
                            "entry_time": t.entry_time,
                            "exit_time": t.exit_time,
                            "status": "closed",
                            "source": "backtest",
                            "backtest_run_id": run_id,
                        },
                    )
                except Exception as exc:
                    log.error(
                        "backtest_trade_persist_error",
                        error=str(exc),
                    )

            await self._session.commit()
        else:
            run_id = uuid.uuid4()

        return BacktestResult(
            run_id=run_id,
            strategy_name=strategy.name,
            pair=pair,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=initial_balance,
            final_balance=final_balance,
            total_pnl=total_pnl,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trade_count=len(closed_trades),
            trades=closed_trades,
            balance_series=balance_series,
            drawdown_series=drawdown_series,
            buy_hold_pnl=buy_hold_pnl,
            buy_hold_return_pct=buy_hold_return_pct,
        )
