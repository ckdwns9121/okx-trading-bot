"""Startup reconciliation between exchange state and local DB."""

from datetime import datetime, timezone
from typing import Any

from app.db import repository as repo
from app.exchange.okx_client import OKXClient
from app.logging_config import get_logger

logger = get_logger(__name__)


class Reconciler:
    def __init__(self, okx_client: OKXClient, session_factory) -> None:
        self._client = okx_client
        self._session_factory = session_factory

    async def reconcile(self) -> dict[str, int]:
        summary: dict[str, int] = {"orphaned": 0, "unknown": 0, "matched": 0, "orders_reconciled": 0}

        try:
            exchange_positions: list[dict[str, Any]] = await self._client.get_positions()

            async with self._session_factory() as session:
                local_positions = await repo.get_positions(session)

                exchange_by_pair: dict[str, dict[str, Any]] = {}
                for ep in exchange_positions:
                    inst_id: str = ep.get("instId", "")
                    if inst_id:
                        exchange_by_pair[inst_id] = ep

                local_by_pair: dict[str, Any] = {p.pair: p for p in local_positions}

                # Orphaned: in DB but not on exchange
                for pair, local_pos in local_by_pair.items():
                    if pair not in exchange_by_pair:
                        logger.warning("reconcile_orphaned_position", pair=pair)
                        try:
                            await repo.create_trade(session, {
                                "strategy_name": "reconciler", "pair": pair,
                                "direction": local_pos.direction, "entry_price": local_pos.entry_price,
                                "exit_price": None, "quantity": local_pos.quantity,
                                "leverage": local_pos.leverage, "pnl": local_pos.unrealized_pnl,
                                "pnl_pct": None, "fee": 0.0, "entry_time": local_pos.opened_at,
                                "exit_time": datetime.now(timezone.utc), "status": "closed_orphaned",
                                "source": "live",
                            })
                            await repo.delete_position(session, pair)
                            await session.commit()
                            summary["orphaned"] += 1
                        except Exception as exc:
                            logger.error("reconcile_orphaned_cleanup_error", pair=pair, error=str(exc))
                            await session.rollback()

                # Unknown: on exchange but not in DB
                for pair, ep in exchange_by_pair.items():
                    if pair not in local_by_pair:
                        pos_side = ep.get("posSide", "long")
                        direction = "buy" if pos_side == "long" else "sell"
                        try:
                            await repo.create_position(session, {
                                "pair": pair, "direction": direction,
                                "entry_price": float(ep.get("avgPx", 0.0) or 0.0),
                                "quantity": float(ep.get("pos", 0.0) or 0.0),
                                "leverage": int(float(ep.get("lever", 1) or 1)),
                                "unrealized_pnl": float(ep.get("upl", 0.0) or 0.0),
                                "exchange_position_id": ep.get("posId"),
                            })
                            await session.commit()
                            summary["unknown"] += 1
                            logger.warning("reconcile_unknown_position", pair=pair)
                        except Exception as exc:
                            logger.error("reconcile_unknown_create_error", pair=pair, error=str(exc))
                            await session.rollback()

                # Matched: refresh unrealized PnL
                for pair in set(local_by_pair) & set(exchange_by_pair):
                    ep = exchange_by_pair[pair]
                    upnl = float(ep.get("upl", 0.0) or 0.0)
                    try:
                        await repo.update_position(session, pair, {"unrealized_pnl": upnl})
                        await session.commit()
                        summary["matched"] += 1
                    except Exception as exc:
                        logger.error("reconcile_matched_update_error", pair=pair, error=str(exc))
                        await session.rollback()

                # Orders reconciliation
                pending_local_orders = await repo.get_orders(session, status="pending")

                try:
                    exchange_pending = await self._client.get_pending_orders()
                except Exception as exc:
                    logger.error("reconcile_fetch_pending_orders_error", error=str(exc))
                    exchange_pending = []

                exchange_order_ids = {o.get("clOrdId", "") for o in exchange_pending if o.get("clOrdId")}

                for local_order in pending_local_orders:
                    if local_order.cl_ord_id not in exchange_order_ids:
                        try:
                            ex_order = await self._client.get_order_by_cl_ord_id(
                                local_order.cl_ord_id,
                                pair=local_order.pair,
                            )
                            ex_state = ex_order.get("state", "unknown")
                            new_status = (
                                "filled" if ex_state in ("filled", "partially_filled")
                                else "cancelled" if ex_state == "canceled"
                                else "unknown"
                            )
                            await repo.update_order(session, local_order.id, {
                                "status": new_status,
                                "exchange_order_id": ex_order.get("ordId"),
                            })
                            await session.commit()
                            logger.info("reconcile_order_status_updated", cl_ord_id=local_order.cl_ord_id, new_status=new_status)
                            summary["orders_reconciled"] += 1
                        except Exception as exc:
                            logger.error("reconcile_order_check_error", cl_ord_id=local_order.cl_ord_id, error=str(exc))
                            await session.rollback()

        except Exception as exc:
            logger.error("reconcile_fatal_error", error=str(exc))

        logger.info("RECONCILIATION_SUMMARY", **summary)
        return summary
