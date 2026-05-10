"""Order placement with full lifecycle tracking in the database."""

import asyncio
import statistics
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.config import Settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.microstructure import evaluate_microstructure_gate
from app.core.runtime_events import add_event
from app.core.strategy_base import Signal, TradeSignal
from app.db import repository as repo
from app.exchange.okx_client import OKXClient
from app.exchange.public_market_data import OKXPublicMarketData
from app.logging_config import get_logger
from app.models.strategy_config import StrategyConfig

logger = get_logger(__name__)


class OrderManager:
    def __init__(
        self,
        okx_client: OKXClient,
        session_factory,
        circuit_breaker: CircuitBreaker,
        settings: Settings,
        telegram_notifier=None,
        market_data_client=None,
    ) -> None:
        self._client = okx_client
        self._session_factory = session_factory
        self._cb = circuit_breaker
        self._settings = settings
        self._telegram = telegram_notifier
        self._market_data = market_data_client

    async def _send_telegram(self, text: str) -> None:
        if self._telegram is None:
            return
        try:
            await self._telegram.send_text(text)
        except Exception as exc:
            logger.warning("telegram_notify_failed", error=str(exc))

    async def close(self) -> None:
        close = getattr(self._market_data, "close", None)
        if close is not None:
            await close()

    @staticmethod
    def _get_contract_value(pair: str) -> float:
        """Contract value per 1 contract for common SWAP pairs."""
        symbol = pair.split("-")[0]
        ct_values = {
            "BTC": 0.01, "ETH": 0.1, "SOL": 1.0, "XRP": 100.0,
            "DOGE": 1000.0, "ADA": 100.0, "AVAX": 1.0, "DOT": 10.0,
            "LINK": 1.0, "LTC": 1.0, "BCH": 0.1, "FIL": 1.0,
            "APT": 1.0, "ARB": 10.0, "OP": 10.0, "NEAR": 10.0,
            "SUI": 10.0, "PEPE": 10000.0, "INJ": 1.0, "FET": 10.0,
        }
        return ct_values.get(symbol, 1.0)

    async def _get_last_price(self, pair: str) -> float:
        """Fetch current mark price from OKX."""
        try:
            result = await self._client.get_candles(pair, "1m", limit=1)
            if result:
                return float(result[0].get("close", 0))
        except Exception:
            pass
        return 0.0

    async def _get_market_data_client(self):
        if self._market_data is None:
            self._market_data = OKXPublicMarketData()
        return self._market_data

    async def _check_microstructure_gate(
        self,
        *,
        pair: str,
        side: str,
        notional: float,
        strategy_name: str | None,
    ) -> bool:
        if not self._settings.MICROSTRUCTURE_GATE_ENABLED:
            return True

        try:
            market_data = await self._get_market_data_client()
            snapshot = await market_data.get_order_book_top_depth(
                pair,
                depth=self._settings.MICROSTRUCTURE_ORDER_BOOK_DEPTH,
            )
        except Exception as exc:
            details = evaluate_microstructure_gate(
                side=side,
                order_notional=notional,
                max_spread_pct=self._settings.MICROSTRUCTURE_MAX_SPREAD_PCT,
                min_visible_depth_notional=self._settings.MICROSTRUCTURE_MIN_VISIBLE_DEPTH_NOTIONAL,
                max_market_data_age_seconds=self._settings.MICROSTRUCTURE_MAX_MARKET_DATA_AGE_SECONDS,
                market_data={},
            )
            details.update({
                "reason": "market_data_fetch_failed",
                "error": str(exc),
            })
            add_event(
                event="order_open_blocked",
                level="warning",
                pair=pair,
                strategy=strategy_name,
                message="Blocked by microstructure gate",
                details=details,
            )
            return False

        payload = evaluate_microstructure_gate(
            side=side,
            order_notional=notional,
            max_spread_pct=self._settings.MICROSTRUCTURE_MAX_SPREAD_PCT,
            min_visible_depth_notional=self._settings.MICROSTRUCTURE_MIN_VISIBLE_DEPTH_NOTIONAL,
            max_market_data_age_seconds=self._settings.MICROSTRUCTURE_MAX_MARKET_DATA_AGE_SECONDS,
            market_data=snapshot,
        )
        if payload["allow"]:
            return True

        add_event(
            event="order_open_blocked",
            level="warning",
            pair=pair,
            strategy=strategy_name,
            message="Blocked by microstructure gate",
            details=payload,
        )
        return False

    async def _get_usdt_balance(self) -> float:
        result = await self._client.get_account_balance()
        details: list[dict] = result.get("data", [{}])[0].get("details", [])
        for item in details:
            if item.get("ccy") == "USDT":
                return float(item.get("availBal", 0.0))
        return 0.0

    def _estimate_position_notional(self, position) -> float:
        """Estimate position notional in USDT from local position row."""
        ct_val = self._get_contract_value(position.pair)
        return max(0.0, float(position.quantity) * float(position.entry_price) * ct_val)

    async def _get_open_exposure_notional(
        self,
        session,
        pair: str,
    ) -> tuple[float, float]:
        """Return (total_open_notional, pair_open_notional)."""
        positions = await repo.get_positions(session)
        total = 0.0
        pair_total = 0.0
        for pos in positions:
            n = self._estimate_position_notional(pos)
            total += n
            if pos.pair == pair:
                pair_total += n
        return total, pair_total

    async def _estimate_volatility_scale(self, pair: str) -> float:
        """Estimate size scaling factor based on short-horizon realized volatility."""
        if not self._settings.RISK_VOL_ENABLED:
            return 1.0

        lookback = max(20, int(self._settings.RISK_VOL_LOOKBACK))
        try:
            candles = await self._client.get_candles(pair, "1m", limit=lookback + 1)
        except Exception as exc:
            logger.warning("risk_volatility_fetch_failed", pair=pair, error=str(exc))
            return 1.0

        if len(candles) < 3:
            return 1.0

        # Ensure chronological order.
        ordered = sorted(candles, key=lambda c: int(str(c.get("timestamp", "0"))))
        closes = [float(c.get("close", 0.0)) for c in ordered if float(c.get("close", 0.0)) > 0]
        if len(closes) < 3:
            return 1.0

        returns_pct: list[float] = []
        for prev, cur in zip(closes[:-1], closes[1:]):
            if prev <= 0:
                continue
            returns_pct.append(((cur - prev) / prev) * 100.0)
        if len(returns_pct) < 2:
            return 1.0

        realized_vol_pct = statistics.pstdev(returns_pct)
        target_vol_pct = max(0.01, float(self._settings.RISK_VOL_TARGET_PCT))
        raw_scale = target_vol_pct / realized_vol_pct if realized_vol_pct > 0 else 1.0
        scale = max(
            float(self._settings.RISK_VOL_MIN_SCALE),
            min(float(self._settings.RISK_VOL_MAX_SCALE), raw_scale),
        )
        return scale

    @staticmethod
    def _split_contracts(total_contracts: int, parts: int) -> list[int]:
        """Split contract count into near-even integer slices."""
        total = max(1, int(total_contracts))
        p = max(1, min(int(parts), total))
        base = total // p
        rem = total % p
        slices = [base + (1 if i < rem else 0) for i in range(p)]
        return [s for s in slices if s > 0]

    async def _place_order_with_retry(
        self,
        *,
        pair: str,
        side: str,
        size: str,
        leverage: int,
        cl_ord_id: str,
        pos_side: str,
        order_type: str = "market",
    ) -> dict:
        """Place order with retry + idempotency check via clOrdId lookup."""
        attempts = max(1, int(self._settings.ORDER_RETRY_MAX_ATTEMPTS))
        backoff = max(0.05, float(self._settings.ORDER_RETRY_BACKOFF_SEC))
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await self._client.place_order(
                    pair=pair,
                    side=side,
                    size=size,
                    leverage=leverage,
                    order_type=order_type,
                    cl_ord_id=cl_ord_id,
                    pos_side=pos_side,
                )
            except Exception as exc:
                last_exc = exc
                # If request may have succeeded server-side, recover idempotently.
                try:
                    detail = await self._client.get_order_by_cl_ord_id(cl_ord_id, pair=pair)
                    if detail.get("ordId"):
                        logger.warning(
                            "order_retry_recovered_by_clord",
                            pair=pair,
                            cl_ord_id=cl_ord_id,
                            attempt=attempt,
                        )
                        return {"data": [{"ordId": detail.get("ordId"), "sCode": "0", "sMsg": "existing_order"}]}
                except Exception:
                    pass

                if attempt < attempts:
                    await asyncio.sleep(backoff * attempt)

        raise RuntimeError(f"order placement failed after retries: {last_exc}")

    @staticmethod
    def _signal_to_side(signal: Signal) -> str:
        return "buy" if signal == Signal.LONG else "sell"

    @staticmethod
    def _normalize_trade_direction(direction: str | None) -> str:
        value = (direction or "").strip().lower()
        if value in ("buy", "long"):
            return "long"
        if value in ("sell", "short"):
            return "short"
        return value or "unknown"

    async def _resolve_strategy_name(self, session, pair: str, preferred: str | None) -> str:
        if preferred and preferred.strip():
            return preferred.strip()

        result = await session.execute(
            select(StrategyConfig.strategy_name).where(
                StrategyConfig.pair == pair,
                StrategyConfig.is_active.is_(True),
            )
        )
        names = sorted({str(name) for name in result.scalars().all() if name})
        if len(names) == 1:
            return names[0]
        return "unknown"

    async def _fetch_order_fill(self, cl_ord_id: str, pair: str) -> tuple[float, float]:
        """Best-effort fetch of (avg_fill_price, filled_contracts)."""
        for _ in range(3):
            try:
                detail = await self._client.get_order_by_cl_ord_id(cl_ord_id, pair=pair)
                avg_px = float(detail.get("avgPx") or detail.get("fillPx") or 0.0)
                filled_sz = float(
                    detail.get("accFillSz")
                    or detail.get("fillSz")
                    or detail.get("sz")
                    or 0.0
                )
                if filled_sz > 0:
                    return avg_px, filled_sz
            except Exception:
                pass
            await asyncio.sleep(0.3)
        return 0.0, 0.0

    async def open_position(
        self,
        pair: str,
        signal: TradeSignal,
        *,
        strategy_name: str | None = None,
    ) -> Optional[dict]:
        if not await self._cb.check():
            logger.warning("open_position_blocked_circuit_breaker", pair=pair)
            add_event(
                event="order_open_blocked",
                level="warning",
                pair=pair,
                message="Blocked by circuit breaker",
            )
            return None

        log = logger.bind(pair=pair, signal=signal.signal.value, strategy=strategy_name or "unknown")

        try:
            balance = await self._get_usdt_balance()
            side = self._signal_to_side(signal.signal)
            leverage = signal.leverage

            price = await self._get_last_price(pair)
            if price <= 0:
                log.error("open_position_no_price", pair=pair)
                return None

            vol_scale = await self._estimate_volatility_scale(pair)
            requested_notional = (
                balance
                * (self._settings.MAX_POSITION_SIZE_PCT / 100.0)
                * (signal.size_pct / 100.0)
                * vol_scale
            )

            ct_val = self._get_contract_value(pair)
            pos_side = "long" if signal.signal == Signal.LONG else "short"

            async with self._session_factory() as session:
                existing_position = await repo.get_position(session, pair)
                if existing_position is not None:
                    log.warning("open_position_blocked_existing_position")
                    add_event(
                        event="order_open_blocked",
                        level="warning",
                        pair=pair,
                        strategy=strategy_name,
                        message="Blocked by existing open position",
                    )
                    return None

                open_total_notional, open_pair_notional = await self._get_open_exposure_notional(session, pair)
                total_cap_notional = balance * (self._settings.MAX_TOTAL_EXPOSURE_PCT / 100.0)
                pair_cap_notional = balance * (self._settings.MAX_PAIR_EXPOSURE_PCT / 100.0)
                total_room = max(0.0, total_cap_notional - open_total_notional)
                pair_room = max(0.0, pair_cap_notional - open_pair_notional)

                notional = min(requested_notional, total_room, pair_room)
                if notional <= 0:
                    log.warning(
                        "open_position_blocked_exposure_limit",
                        requested_notional=requested_notional,
                        total_room=total_room,
                        pair_room=pair_room,
                        open_total_notional=open_total_notional,
                        open_pair_notional=open_pair_notional,
                    )
                    add_event(
                        event="order_open_blocked",
                        level="warning",
                        pair=pair,
                        strategy=strategy_name,
                        message="Blocked by exposure limits",
                        details={
                            "requested_notional": requested_notional,
                            "total_room": total_room,
                            "pair_room": pair_room,
                            "open_total_notional": open_total_notional,
                            "open_pair_notional": open_pair_notional,
                        },
                    )
                    return None

                contracts_total = int(notional / (price * ct_val))
                if contracts_total < 1:
                    log.warning(
                        "open_position_notional_below_single_contract",
                        notional=notional,
                        price=price,
                        ct_val=ct_val,
                    )
                    return None

                if not await self._check_microstructure_gate(
                    pair=pair,
                    side=side,
                    notional=notional,
                    strategy_name=strategy_name,
                ):
                    log.warning("open_position_blocked_microstructure")
                    return None

                await self._client.set_leverage(pair, leverage)

                split_parts = (
                    max(1, int(self._settings.ORDER_SPLIT_PARTS))
                    if self._settings.ORDER_SPLIT_ENABLED
                    else 1
                )
                slices = self._split_contracts(contracts_total, split_parts)
                log.info(
                    "open_position_sizing",
                    balance=balance,
                    requested_notional=requested_notional,
                    effective_notional=notional,
                    volatility_scale=vol_scale,
                    leverage=leverage,
                    contracts_total=contracts_total,
                    split_parts=len(slices),
                    price=price,
                )
                add_event(
                    event="order_open_attempt",
                    pair=pair,
                    strategy=strategy_name,
                    details={
                        "side": side,
                        "leverage": leverage,
                        "contracts_total": contracts_total,
                        "split_parts": len(slices),
                        "requested_notional": requested_notional,
                        "effective_notional": notional,
                        "volatility_scale": vol_scale,
                    },
                )

                executed_contracts = 0.0
                executed_notional = 0.0
                exchange_order_ids: list[str] = []

                for idx, contracts_slice in enumerate(slices, start=1):
                    cl_ord_id = uuid.uuid4().hex
                    order = await repo.create_order(
                        session,
                        {
                            "pair": pair,
                            "side": side,
                            "order_type": "market",
                            "quantity": float(contracts_slice),
                            "leverage": leverage,
                            "status": "pending",
                            "cl_ord_id": cl_ord_id,
                        },
                    )
                    await session.commit()

                    result = await self._place_order_with_retry(
                        pair=pair,
                        side=side,
                        size=str(contracts_slice),
                        leverage=leverage,
                        order_type="market",
                        cl_ord_id=cl_ord_id,
                        pos_side=pos_side,
                    )

                    order_data: list[dict] = result.get("data", [{}])
                    exchange_order_id: Optional[str] = None
                    if order_data:
                        item = order_data[0]
                        exchange_order_id = item.get("ordId")
                        s_code = item.get("sCode", "0")
                        if s_code != "0":
                            err_msg = item.get("sMsg", "unknown rejection")
                            await repo.update_order(
                                session,
                                order.id,
                                {"status": "rejected", "error_message": err_msg},
                            )
                            await session.commit()
                            log.error(
                                "open_position_order_rejected",
                                slice_index=idx,
                                s_code=s_code,
                                err_msg=err_msg,
                            )
                            continue

                    await repo.update_order(
                        session,
                        order.id,
                        {"status": "filled", "exchange_order_id": exchange_order_id},
                    )
                    await session.commit()

                    fill_price, fill_contracts = await self._fetch_order_fill(cl_ord_id, pair)
                    filled_qty = fill_contracts if fill_contracts > 0 else float(contracts_slice)
                    filled_price = fill_price if fill_price > 0 else price
                    executed_contracts += filled_qty
                    executed_notional += filled_price * filled_qty * ct_val
                    if exchange_order_id:
                        exchange_order_ids.append(str(exchange_order_id))

                if executed_contracts <= 0:
                    log.error("open_position_all_slices_failed")
                    return None

                entry_price = executed_notional / (executed_contracts * ct_val)
                exchange_position_id = ",".join(exchange_order_ids) if exchange_order_ids else None
                await repo.create_position(
                    session,
                    {
                        "pair": pair,
                        "direction": side,
                        "entry_price": entry_price,
                        "quantity": executed_contracts,
                        "leverage": leverage,
                        "unrealized_pnl": 0.0,
                        "exchange_position_id": exchange_position_id,
                    },
                )
                await session.commit()

            result = {
                "data": [{"ordId": exchange_order_ids[-1]}] if exchange_order_ids else [],
                "meta": {
                    "contracts": executed_contracts,
                    "notional": executed_notional,
                    "split_parts": len(slices),
                },
            }
            log.info(
                "open_position_success",
                exchange_order_ids=exchange_order_ids,
                notional=executed_notional,
                entry_price=entry_price,
                contracts=executed_contracts,
                split_parts=len(slices),
            )
            add_event(
                event="order_open_success",
                pair=pair,
                details={
                    "exchange_order_ids": exchange_order_ids,
                    "notional": executed_notional,
                    "entry_price": entry_price,
                    "contracts": executed_contracts,
                    "split_parts": len(slices),
                    "volatility_scale": vol_scale,
                },
            )
            mode_label = "DEMO" if self._settings.is_demo else "LIVE"
            await self._send_telegram(
                "\n".join(
                    [
                        f"[OKX BOT][{mode_label}] OPEN",
                        f"pair: {pair}",
                        f"side: {side}",
                        f"contracts: {executed_contracts}",
                        f"leverage: {leverage}x",
                        f"entry_price: {entry_price:.4f}",
                        f"notional: {executed_notional:.2f} USDT",
                        f"slices: {len(slices)}",
                        f"order_ids: {','.join(exchange_order_ids) if exchange_order_ids else '-'}",
                        f"reason: {signal.reason}",
                    ]
                )
            )
            return result

        except Exception as exc:
            log.error("open_position_error", error=str(exc))
            add_event(event="order_open_error", level="error", pair=pair, message=str(exc))
            mode_label = "DEMO" if self._settings.is_demo else "LIVE"
            await self._send_telegram(
                "\n".join(
                    [
                        f"[OKX BOT][{mode_label}] OPEN ERROR",
                        f"pair: {pair}",
                        f"signal: {signal.signal.value}",
                        f"error: {str(exc)}",
                    ]
                )
            )
            return None

    async def close_position(
        self,
        pair: str,
        *,
        strategy_name: str | None = None,
    ) -> Optional[dict]:
        log = logger.bind(pair=pair)
        created_order_id: Optional[uuid.UUID] = None
        local_position = None

        try:
            async with self._session_factory() as session:
                position = await repo.get_position(session, pair)
                if position is None:
                    log.warning("close_position_no_local_position")
                    return None
                local_position = position

                direction = self._normalize_trade_direction(position.direction)
                pos_side = "long" if direction == "long" else "short"
                close_side = "sell" if direction == "long" else "buy"
                close_contracts = max(1, int(round(float(position.quantity))))

                cl_ord_id = uuid.uuid4().hex
                order = await repo.create_order(session, {
                    "pair": pair,
                    "side": close_side,
                    "order_type": "market", "quantity": float(close_contracts),
                    "leverage": position.leverage, "status": "pending",
                    "cl_ord_id": cl_ord_id,
                })
                created_order_id = order.id
                await session.commit()

                result = await self._place_order_with_retry(
                    pair=pair,
                    side=close_side,
                    size=str(close_contracts),
                    leverage=position.leverage,
                    order_type="market",
                    cl_ord_id=cl_ord_id,
                    pos_side=pos_side,
                )

                close_data: list[dict] = result.get("data", [{}])
                exchange_order_id: Optional[str] = None
                if close_data:
                    item = close_data[0]
                    exchange_order_id = item.get("ordId")
                    s_code = item.get("sCode", "0")
                    if s_code != "0":
                        err_msg = item.get("sMsg", "unknown rejection")
                        await repo.update_order(
                            session,
                            order.id,
                            {"status": "rejected", "error_message": err_msg},
                        )
                        await session.commit()
                        log.error("close_position_order_rejected", s_code=s_code, err_msg=err_msg)
                        return None

                await repo.update_order(session, order.id, {"status": "filled", "exchange_order_id": exchange_order_id})

                fill_price, fill_contracts = await self._fetch_order_fill(cl_ord_id, pair)
                qty_contracts = fill_contracts if fill_contracts > 0 else float(close_contracts)
                exit_price = fill_price
                if exit_price <= 0:
                    exit_price = await self._get_last_price(pair)

                entry_contracts = float(position.quantity)
                qty_for_pnl = min(entry_contracts, qty_contracts) if entry_contracts > 0 else qty_contracts
                ct_val = self._get_contract_value(pair)
                if direction == "long":
                    pnl = (exit_price - float(position.entry_price)) * qty_for_pnl * ct_val
                else:
                    pnl = (float(position.entry_price) - exit_price) * qty_for_pnl * ct_val
                cost_basis = float(position.entry_price) * qty_for_pnl * ct_val
                pnl_pct = (pnl / cost_basis) * 100.0 if cost_basis > 0 else 0.0

                resolved_strategy = await self._resolve_strategy_name(session, pair, strategy_name)

                await repo.create_trade(session, {
                    "strategy_name": resolved_strategy, "pair": pair,
                    "direction": direction, "entry_price": position.entry_price,
                    "exit_price": exit_price, "quantity": qty_for_pnl,
                    "leverage": position.leverage, "pnl": pnl, "pnl_pct": pnl_pct,
                    "fee": 0.0, "entry_time": position.opened_at,
                    # DB column is TIMESTAMP WITHOUT TIME ZONE (naive)
                    "exit_time": datetime.utcnow(), "status": "closed",
                    "source": "live", "entry_order_id": None, "exit_order_id": order.id,
                })

                await repo.delete_position(session, pair)
                await session.commit()

            log.info("close_position_success", exchange_order_id=exchange_order_id, pnl=pnl)
            add_event(
                event="order_close_success",
                pair=pair,
                details={"exchange_order_id": exchange_order_id, "pnl": pnl, "exit_price": exit_price},
            )
            mode_label = "DEMO" if self._settings.is_demo else "LIVE"
            await self._send_telegram(
                "\n".join(
                    [
                        f"[OKX BOT][{mode_label}] CLOSE",
                        f"pair: {pair}",
                        f"side: {'sell' if local_position and self._normalize_trade_direction(local_position.direction) == 'long' else 'buy'}",
                        f"qty: {local_position.quantity if local_position else '-'}",
                        f"leverage: {local_position.leverage if local_position else '-'}x",
                        f"exit_price: {exit_price:.4f}",
                        f"pnl: {pnl:.6f}",
                        f"order_id: {exchange_order_id or '-'}",
                    ]
                )
            )
            return result

        except Exception as exc:
            log.error("close_position_error", error=str(exc))
            add_event(event="order_close_error", level="error", pair=pair, message=str(exc))
            mode_label = "DEMO" if self._settings.is_demo else "LIVE"
            await self._send_telegram(
                "\n".join(
                    [
                        f"[OKX BOT][{mode_label}] CLOSE ERROR",
                        f"pair: {pair}",
                        f"error: {str(exc)}",
                    ]
                )
            )
            if created_order_id is not None:
                try:
                    async with self._session_factory() as session:
                        await repo.update_order(
                            session,
                            created_order_id,
                            {"status": "rejected", "error_message": str(exc)[:500]},
                        )
                        # If exchange says position does not exist (already closed), clean local stale row.
                        if "51023" in str(exc):
                            await repo.delete_position(session, pair)
                            log.warning("close_position_local_stale_cleanup", reason="okx_51023")
                        await session.commit()
                except Exception as update_exc:
                    log.error("close_position_reject_mark_failed", error=str(update_exc))
            return None
