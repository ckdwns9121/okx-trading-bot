"""Order placement with full lifecycle tracking in the database."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.config import Settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.runtime_events import add_event
from app.core.strategy_base import Signal, TradeSignal
from app.db import repository as repo
from app.exchange.okx_client import OKXClient
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
    ) -> None:
        self._client = okx_client
        self._session_factory = session_factory
        self._cb = circuit_breaker
        self._settings = settings
        self._telegram = telegram_notifier

    async def _send_telegram(self, text: str) -> None:
        if self._telegram is None:
            return
        try:
            await self._telegram.send_text(text)
        except Exception as exc:
            logger.warning("telegram_notify_failed", error=str(exc))

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

    async def _get_usdt_balance(self) -> float:
        result = await self._client.get_account_balance()
        details: list[dict] = result.get("data", [{}])[0].get("details", [])
        for item in details:
            if item.get("ccy") == "USDT":
                return float(item.get("availBal", 0.0))
        return 0.0

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
        created_order_id: Optional[uuid.UUID] = None

        try:
            balance = await self._get_usdt_balance()
            notional = (
                balance
                * (self._settings.MAX_POSITION_SIZE_PCT / 100.0)
                * (signal.size_pct / 100.0)
            )
            side = self._signal_to_side(signal.signal)
            leverage = signal.leverage

            # OKX SWAP: sz is number of contracts (integer).
            # Fetch current price to convert USDT notional → contracts.
            # BTC-USDT-SWAP: 1 contract = 0.01 BTC; ETH-USDT-SWAP: 1 contract = 0.1 ETH
            # Use ctVal from instrument info, or estimate: contracts = notional / (price * ctVal)
            # Simplified: use notional / price to get base amount, then / ctVal for contracts
            price = await self._get_last_price(pair)
            if price <= 0:
                log.error("open_position_no_price", pair=pair)
                return None

            # Contract value mapping (common USDT-SWAP pairs)
            ct_val = self._get_contract_value(pair)
            contracts = int(notional / (price * ct_val))
            if contracts < 1:
                contracts = 1
            size_str = str(contracts)

            # pos_side for hedge mode: "long" when buying to open long, "short" when selling to open short
            pos_side = "long" if signal.signal == Signal.LONG else "short"

            log.info("open_position_sizing", balance=balance, notional=notional, leverage=leverage, contracts=contracts, price=price)
            add_event(
                event="order_open_attempt",
                pair=pair,
                details={
                    "side": side,
                    "contracts": contracts,
                    "leverage": leverage,
                },
            )

            await self._client.set_leverage(pair, leverage)

            cl_ord_id = uuid.uuid4().hex

            async with self._session_factory() as session:
                order = await repo.create_order(session, {
                    "pair": pair, "side": side, "order_type": "market",
                    "quantity": float(contracts), "leverage": leverage,
                    "status": "pending", "cl_ord_id": cl_ord_id,
                })
                created_order_id = order.id
                await session.commit()

                result = await self._client.place_order(
                    pair=pair, side=side, size=size_str,
                    leverage=leverage, order_type="market", cl_ord_id=cl_ord_id,
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
                        log.error("open_position_order_rejected", s_code=s_code, err_msg=err_msg)
                        add_event(
                            event="order_open_rejected",
                            level="error",
                            pair=pair,
                            message=err_msg,
                            details={"s_code": s_code},
                        )
                        mode_label = "DEMO" if self._settings.is_demo else "LIVE"
                        await self._send_telegram(
                            "\n".join(
                                [
                                    f"[OKX BOT][{mode_label}] OPEN REJECTED",
                                    f"pair: {pair}",
                                    f"side: {side}",
                                    f"code: {s_code}",
                                    f"error: {err_msg}",
                                ]
                            )
                        )
                        await repo.update_order(session, order.id, {"status": "rejected", "error_message": err_msg})
                        await session.commit()
                        return None

                await repo.update_order(session, order.id, {"status": "filled", "exchange_order_id": exchange_order_id})

                fill_price, fill_contracts = await self._fetch_order_fill(cl_ord_id, pair)
                entry_price = fill_price if fill_price > 0 else price
                qty_contracts = fill_contracts if fill_contracts > 0 else float(contracts)
                executed_notional = entry_price * qty_contracts * ct_val

                await repo.create_position(session, {
                    "pair": pair, "direction": side, "entry_price": entry_price,
                    "quantity": qty_contracts, "leverage": leverage,
                    "unrealized_pnl": 0.0, "exchange_position_id": exchange_order_id,
                })
                await session.commit()

            log.info(
                "open_position_success",
                exchange_order_id=exchange_order_id,
                notional=executed_notional,
                entry_price=entry_price,
                contracts=qty_contracts,
            )
            add_event(
                event="order_open_success",
                pair=pair,
                details={
                    "exchange_order_id": exchange_order_id,
                    "notional": executed_notional,
                    "entry_price": entry_price,
                    "contracts": qty_contracts,
                },
            )
            mode_label = "DEMO" if self._settings.is_demo else "LIVE"
            await self._send_telegram(
                "\n".join(
                    [
                        f"[OKX BOT][{mode_label}] OPEN",
                        f"pair: {pair}",
                        f"side: {side}",
                        f"contracts: {qty_contracts}",
                        f"leverage: {leverage}x",
                        f"entry_price: {entry_price:.4f}",
                        f"notional: {executed_notional:.2f} USDT",
                        f"order_id: {exchange_order_id or '-'}",
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
            if created_order_id is not None:
                try:
                    async with self._session_factory() as session:
                        await repo.update_order(
                            session,
                            created_order_id,
                            {"status": "rejected", "error_message": str(exc)[:500]},
                        )
                        await session.commit()
                except Exception as update_exc:
                    log.error("open_position_reject_mark_failed", error=str(update_exc))
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

                result = await self._client.place_order(
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
