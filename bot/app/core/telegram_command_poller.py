"""Telegram command polling and command handlers for bot control/monitoring."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.runtime_events import list_events
from app.logging_config import get_logger
from app.models.position import Position
from app.models.runtime_event import RuntimeEvent
from app.models.trade import Trade

logger = get_logger(__name__)


class TelegramCommandPoller:
    def __init__(
        self,
        *,
        notifier,
        session_factory,
        app_state,
        poll_timeout_sec: int = 25,
        enabled: bool = True,
    ) -> None:
        self._notifier = notifier
        self._session_factory = session_factory
        self._app_state = app_state
        self._poll_timeout_sec = max(1, min(poll_timeout_sec, 60))
        self._enabled = enabled and notifier is not None and getattr(notifier, "enabled", False)
        self._task: asyncio.Task | None = None
        self._offset: int | None = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if not self._enabled:
            logger.info("telegram_command_poller_disabled")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="telegram-command-poller")
        logger.info("telegram_command_poller_started", timeout=self._poll_timeout_sec)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("telegram_command_poller_stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                updates = await self._notifier.get_updates(
                    offset=self._offset,
                    timeout=self._poll_timeout_sec,
                )
                for upd in updates:
                    update_id = int(upd.get("update_id", 0))
                    if self._offset is None or update_id >= self._offset:
                        self._offset = update_id + 1
                    await self._handle_update(upd)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("telegram_command_poller_error", error=str(exc))
                await asyncio.sleep(1.0)

    def _is_allowed_chat(self, chat_id: Any) -> bool:
        return str(chat_id) == str(self._notifier.chat_id)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not self._is_allowed_chat(chat_id):
            logger.warning("telegram_command_unauthorized_chat", chat_id=chat_id)
            return

        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return

        response = await self._dispatch_command(text)
        if response:
            await self._notifier.send_text(response)

    async def _dispatch_command(self, text: str) -> str:
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        args = parts[1:]

        if cmd in ("/help", "/startbot"):
            return (
                "OKX Bot 명령어\n"
                "/status - 엔진 상태\n"
                "/position 또는 /positions - 현재 포지션\n"
                "/balance - 계좌 잔고\n"
                "/pnl - 실현손익 요약\n"
                "/logs - 최근 이벤트\n"
                "/start - 엔진 시작\n"
                "/stop - 엔진 중지\n"
                "/close <PAIR> - 해당 페어 강제 청산"
            )
        if cmd == "/status":
            return await self._cmd_status()
        if cmd in ("/position", "/positions"):
            return await self._cmd_positions()
        if cmd == "/balance":
            return await self._cmd_balance()
        if cmd == "/pnl":
            return await self._cmd_pnl()
        if cmd == "/logs":
            return await self._cmd_logs()
        if cmd == "/start":
            return await self._cmd_start()
        if cmd == "/stop":
            return await self._cmd_stop()
        if cmd == "/close":
            pair = args[0].upper() if args else ""
            if not pair:
                return "사용법: /close ETH-USDT-SWAP"
            return await self._cmd_close(pair)
        return "알 수 없는 명령어입니다. /help"

    def _get_engine(self):
        return getattr(self._app_state, "live_engine", None)

    async def _cmd_status(self) -> str:
        engine = self._get_engine()
        if engine is None:
            return "엔진 없음"
        try:
            running = bool(getattr(engine, "is_running", False))
            pairs = engine.get_status().get("pairs", {})
            lines = [f"engine: {'running' if running else 'stopped'}"]
            if not pairs:
                lines.append("pairs: 없음")
            else:
                lines.append("pairs:")
                for pair, s in pairs.items():
                    lines.append(
                        f"- {pair} {s.get('strategy_name','?')} {s.get('timeframe','1m')} {s.get('status','?')}"
                    )
            return "\n".join(lines)
        except Exception as exc:
            return f"status 조회 실패: {exc}"

    async def _cmd_positions(self) -> str:
        try:
            async with self._session_factory() as session:
                result = await session.execute(select(Position).order_by(Position.opened_at.desc()))
                rows = result.scalars().all()
            if not rows:
                return "open positions: 없음"
            lines = ["open positions:"]
            for p in rows:
                lines.append(
                    f"- {p.pair} {p.direction} qty={p.quantity} entry={p.entry_price:.4f} lev={p.leverage}x"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"positions 조회 실패: {exc}"

    async def _cmd_balance(self) -> str:
        try:
            client = getattr(self._app_state, "okx_client", None)
            if client is None:
                return "balance 조회 실패: okx client 없음"
            raw = await client.get_account_balance()
            row = (raw.get("data") or [{}])[0]
            details = row.get("details") or []
            usdt = next((d for d in details if d.get("ccy") == "USDT"), {})
            total_eq = float(row.get("totalEq") or 0)
            usdt_eq = float(usdt.get("eq") or 0)
            usdt_avail = float(usdt.get("availEq") or usdt.get("availBal") or 0)
            return (
                "balance:\n"
                f"- totalEq: {total_eq:.4f}\n"
                f"- usdtEq: {usdt_eq:.4f}\n"
                f"- usdtAvail: {usdt_avail:.4f}"
            )
        except Exception as exc:
            return f"balance 조회 실패: {exc}"

    async def _cmd_pnl(self) -> str:
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(Trade)
                    .where(Trade.source == "live", Trade.status == "closed", Trade.pnl.is_not(None))
                    .order_by(Trade.exit_time.desc())
                )
                trades = result.scalars().all()
            if not trades:
                return "pnl: 데이터 없음"
            total = sum(float(t.pnl or 0) for t in trades)
            wins = sum(1 for t in trades if float(t.pnl or 0) > 0)
            count = len(trades)
            wr = (wins / count) * 100 if count else 0
            return (
                "live pnl:\n"
                f"- realized: {total:.6f}\n"
                f"- trades: {count}\n"
                f"- winRate: {wr:.2f}%"
            )
        except Exception as exc:
            return f"pnl 조회 실패: {exc}"

    async def _cmd_logs(self) -> str:
        items: list[dict[str, Any]] = []
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(RuntimeEvent)
                    .order_by(RuntimeEvent.id.desc())
                    .limit(8)
                )
                rows = list(result.scalars().all())
            items = [
                {
                    "timestamp": row.timestamp.isoformat(),
                    "event": row.event,
                    "pair": row.pair,
                }
                for row in reversed(rows)
            ]
        except Exception:
            # Fallback to in-memory runtime buffer if DB read fails.
            items = list_events(limit=8)

        if not items:
            return "최근 이벤트 없음"
        lines = ["recent logs:"]
        for e in items[-8:]:
            ts = e.get("timestamp", "")
            hhmmss = ts[11:19] if len(ts) >= 19 else ts
            pair = e.get("pair") or "-"
            event = e.get("event") or "event"
            lines.append(f"- {hhmmss} {event} {pair}")
        return "\n".join(lines)

    async def _cmd_start(self) -> str:
        engine = self._get_engine()
        if engine is None:
            return "start 실패: 엔진 없음"
        try:
            await engine.start()
            return "엔진 시작 완료"
        except Exception as exc:
            return f"start 실패: {exc}"

    async def _cmd_stop(self) -> str:
        engine = self._get_engine()
        if engine is None:
            return "stop 실패: 엔진 없음"
        try:
            await engine.stop()
            return "엔진 중지 완료"
        except Exception as exc:
            return f"stop 실패: {exc}"

    async def _cmd_close(self, pair: str) -> str:
        engine = self._get_engine()
        if engine is None:
            return "close 실패: 엔진 없음"
        try:
            result = await engine.order_manager.close_position(pair)
            if result is None:
                return f"{pair} 청산 대상 포지션 없음"
            return f"{pair} 청산 주문 전송 완료"
        except Exception as exc:
            return f"close 실패: {exc}"
