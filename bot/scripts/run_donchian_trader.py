"""OKX demo trader: Donchian breakout on BTC/ETH/SOL/XRP spot, ATR-sized sleeves.

Strategy evidence: docs/research/donchian-majors-v3/v4-result-2026-10-09.md.
Operational checklist: docs/research/how-people-build-trading-bots-2026-10-09.md §5.

Every loop (default 10 min) does, in order:
  1. settle orders that were sent but not yet confirmed (query by clOrdId)
  2. reconcile bot-owned coins against exchange balances (pre-bot holdings excluded);
     a shortfall trips the kill switch and stops trading
  3. for each sleeve, once per new confirmed UTC daily bar: freshness check →
     signal → RiskGate → deterministic clOrdId → send once → confirm by query
     → mark the bar handled only when its outcome is settled
  4. persist state atomically; one Telegram summary per UTC day

Usage:
    python -m scripts.run_donchian_trader --once      # single pass
    python -m scripts.run_donchian_trader             # loop (compose service)
Refuses to start unless OKX_MODE=demo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.config import settings
from app.core.donchian_majors import DonchianParams
from app.core.donchian_trader import (
    Decision,
    Fill,
    Sleeve,
    apply_fill,
    candles_to_bars,
    client_order_id,
    decide,
    expected_latest_bar_ts,
    floor_to_step,
    is_fresh,
    reconcile,
    sleeve_equity,
)
from app.core.execution_quality import ExecutionQualityLog, ExecutionRecord
from app.core.risk_gate import AccountState, OrderIntent, RiskGate, build_risk_gate_from_settings
from app.core.runtime_events import add_event
from app.exchange.okx_client import OKXClient
from app.exchange.public_market_data import OKXPublicMarketData

STRATEGY = "Donchian 55/20 ATR-sized (OKX demo spot)"
MIN_NOTIONAL_USD = 10.0
FILL_POLL_ATTEMPTS = 6
FILL_POLL_DELAY_S = 1.5
UNKNOWN_ORDER_GRACE_S = 15 * 60  # an order OKX never heard of after this long is dropped


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"state file {path} is unreadable ({exc}); move it aside and reconcile manually") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"state file {path} is not an object")
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".donchian_trader_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


class Notifier:
    """Telegram for actionable events only; everything also goes to runtime events."""

    def __init__(self) -> None:
        self._tg = None
        if settings.telegram_enabled:
            from app.core.telegram_notifier import TelegramNotifier

            self._tg = TelegramNotifier(bot_token=settings.TELEGRAM_BOT_TOKEN, chat_id=settings.TELEGRAM_CHAT_ID,
                                        enabled=settings.TELEGRAM_NOTIFICATIONS_ENABLED)

    async def send(self, text: str) -> None:
        if self._tg is None:
            return
        try:
            await self._tg.send_text(f"[돈치안 데모] {text}")
        except Exception:  # notifications must never break trading
            pass

    async def close(self) -> None:
        if self._tg is not None:
            await self._tg.close()


# --------------------------------------------------------------------------- #
# Trader
# --------------------------------------------------------------------------- #


class Trader:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.pairs: tuple[str, ...] = tuple(p.strip().upper() for p in args.pairs.split(",") if p.strip())
        self.params = DonchianParams(args.entry, args.exit, 20, args.atr_stop, risk_pct=args.risk_pct)
        self.state_path = Path(args.state_file)
        self.client = OKXClient(api_key=settings.OKX_API_KEY, secret=settings.OKX_SECRET,
                                passphrase=settings.OKX_PASSPHRASE, mode=settings.OKX_MODE)
        self.market = OKXPublicMarketData()
        self.gate: RiskGate = build_risk_gate_from_settings(settings)
        self.tca = ExecutionQualityLog(settings.RISK_EXECUTION_LOG_FILE)
        self.notify = Notifier()
        self.specs: dict[str, dict[str, float]] = {}
        self.state: dict[str, Any] = {}
        self.sleeves: dict[str, Sleeve] = {}

    # ---------------- setup ----------------

    async def start(self) -> None:
        for inst in self.pairs:
            rows = await self.market.get_instruments(inst_type="SPOT", inst_id=inst)
            if not rows:
                raise SystemExit(f"OKX has no spot instrument {inst}")
            r = rows[0]
            self.specs[inst] = {"lot": float(r.get("lotSz") or 0.0), "min": float(r.get("minSz") or 0.0)}

        self.state = load_state(self.state_path)
        balances = await self.client.get_balances()
        if not self.state:
            baseline = {inst.split("-")[0]: balances.get(inst.split("-")[0], 0.0) for inst in self.pairs}
            usdt = balances.get("USDT", 0.0)
            if usdt < self.args.capital_usd:
                raise SystemExit(f"need {self.args.capital_usd} USDT free, account has {usdt:.2f}")
            per = self.args.capital_usd / len(self.pairs)
            self.state = {
                "version": 1,
                "strategy": STRATEGY,
                "started_at": now_utc().isoformat(),
                "config": {"pairs": list(self.pairs), "capital_usd": self.args.capital_usd, "params": asdict(self.params),
                           "mode": settings.OKX_MODE, "poll_seconds": self.args.poll_seconds},
                "baseline": baseline,
                "baseline_usdt": usdt,
                "sleeves": {inst: Sleeve(inst, per).to_dict() for inst in self.pairs},
                "handled_bar": {},
                "pending": {},
                "trades": [],
                "equity_history": [],
                "alerts_sent": {},
                "last_summary_day": None,
            }
            add_event(event="donchian_initialised", strategy=STRATEGY,
                      message=f"fresh state: {len(self.pairs)} sleeves × ${per:,.0f}; baseline holdings excluded {baseline}",
                      details={"baseline": baseline})
        self.state["config"]["poll_seconds"] = self.args.poll_seconds
        self.sleeves = {k: Sleeve.from_dict(v) for k, v in self.state["sleeves"].items()}
        save_state(self.state_path, self.state)
        add_event(event="donchian_started", strategy=STRATEGY,
                  message=f"trader started ({settings.OKX_MODE}) for {', '.join(self.pairs)}",
                  details=self.state["config"])
        await self.notify.send(f"시작: {', '.join(p.split('-')[0] for p in self.pairs)} · 슬리브 ${self.args.capital_usd/len(self.pairs):,.0f}씩")

    def _persist(self) -> None:
        self.state["sleeves"] = {k: s.to_dict() for k, s in self.sleeves.items()}
        self.state["last_loop_at"] = now_utc().isoformat()
        save_state(self.state_path, self.state)

    async def _alert_once(self, key: str, text: str) -> None:
        """Same alert at most once per key (e.g. per instrument per bar)."""
        if self.state["alerts_sent"].get(key):
            return
        self.state["alerts_sent"][key] = now_utc().isoformat()
        await self.notify.send(text)

    # ---------------- 1. settle pending orders ----------------

    async def settle_pending(self) -> None:
        for cl_id, p in list(self.state["pending"].items()):
            order = await self.client.find_order(inst_id=p["inst"], cl_ord_id=cl_id)
            if order is None:
                age = (now_utc() - datetime.fromisoformat(p["sent_at"])).total_seconds()
                if age > UNKNOWN_ORDER_GRACE_S:
                    self.state["pending"].pop(cl_id)
                    add_event(event="donchian_order_unknown", level="warning", pair=p["inst"], strategy=STRATEGY,
                              message=f"{p['side']} {cl_id} never reached OKX; will re-decide on the same bar")
                continue
            st = str(order.get("state") or "")
            filled = float(order.get("accFillSz") or 0.0)
            if st == "filled" or (st in {"canceled", "mmp_canceled"} and filled > 0):
                await self._book_fill(cl_id, p, order)
            elif st in {"canceled", "mmp_canceled"}:
                self.state["pending"].pop(cl_id)
                add_event(event="donchian_order_canceled", level="warning", pair=p["inst"], strategy=STRATEGY,
                          message=f"{p['side']} {cl_id} canceled with no fill; will re-decide")

    async def _book_fill(self, cl_id: str, p: dict[str, Any], order: dict[str, Any]) -> None:
        sleeve = self.sleeves[p["inst"]]
        decision = Decision(**p["decision"])
        fill = Fill(side=p["side"], base_filled=float(order.get("accFillSz") or 0.0), avg_px=float(order.get("avgPx") or 0.0),
                    fee=float(order.get("fee") or 0.0), fee_ccy=str(order.get("feeCcy") or "USDT"))
        fill_ts = int(order.get("fillTime") or order.get("uTime") or now_utc().timestamp() * 1000)
        rec = apply_fill(sleeve, fill, fill_ts=fill_ts, decision=decision)
        rec["cl_ord_id"] = cl_id
        self.state["trades"].append(rec)
        self.state["pending"].pop(cl_id, None)
        self.state["handled_bar"][p["inst"]] = decision.bar_ts
        self.tca.record(ExecutionRecord(inst_id=p["inst"], side=p["side"], quantity=fill.base_filled, decision_price=decision.close,
                                        fill_price=fill.avg_px, fee_usd=rec["fee_usd"], occurred_at=now_utc().isoformat(),
                                        strategy=STRATEGY, order_ref=cl_id))
        coin = p["inst"].split("-")[0]
        pnl = f", 실현 {rec['realized_pnl_usd']:+,.2f}$" if rec["realized_pnl_usd"] is not None else ""
        msg = f"{'매수' if p['side']=='buy' else '매도'} {coin} {fill.base_filled:g} @ {fill.avg_px:,.4g} (${rec['quote_usd']:,.0f}, 사유 {decision.reason}{pnl})"
        add_event(event="donchian_fill", pair=p["inst"], strategy=STRATEGY, timeframe="1D", message=msg, details=rec)
        await self.notify.send(msg)

    # ---------------- 2. reconcile ----------------

    async def reconcile_books(self) -> bool:
        balances = await self.client.get_balances()
        tolerances = {inst.split("-")[0]: max(self.specs[inst]["lot"] * 2, 1e-12) for inst in self.pairs}
        mismatches = reconcile(self.sleeves, balances, self.state["baseline"], tolerances)
        if not mismatches:
            return True
        critical = [m for m in mismatches if m.critical]
        for m in mismatches:
            add_event(event="donchian_reconciliation_mismatch", level="error" if m.critical else "warning",
                      strategy=STRATEGY, message=m.detail, details=asdict(m))
        if critical:
            self.gate.kill_switch.trip(reason="donchian trader: coins missing vs book", source="reconciliation")
            await self._alert_once(f"recon:{expected_latest_bar_ts(now_utc())}",
                                   "⚠️ 장부 불일치 — 봇이 산 코인이 거래소에 부족합니다. 긴급 정지했습니다. " + "; ".join(m.detail for m in critical))
            return False
        return True

    # ---------------- 3. decide & trade ----------------

    async def process(self, inst: str) -> None:
        candles = await self.market.get_candles(inst, "1Dutc", limit=300)
        bars = candles_to_bars(inst, candles)
        if len(bars.ts) < self.params.warmup() + 1:
            add_event(event="donchian_skip", level="warning", pair=inst, strategy=STRATEGY, message="not enough history")
            return
        latest = bars.ts[-1]
        if not is_fresh(latest, now_utc()):
            add_event(event="donchian_stale_data", level="warning", pair=inst, strategy=STRATEGY,
                      message=f"latest confirmed bar {iso(latest)} is older than expected {iso(expected_latest_bar_ts(now_utc()))}")
            await self._alert_once(f"stale:{inst}:{expected_latest_bar_ts(now_utc())}", f"{inst} 일봉 데이터가 늦습니다 ({iso(latest)}). 오늘 판단 보류.")
            return
        if self.state["handled_bar"].get(inst) == latest:
            return
        if any(p["inst"] == inst for p in self.state["pending"].values()):
            return  # an order for this sleeve is still being settled

        sleeve = self.sleeves[inst]
        d = decide(bars, sleeve, self.params, min_notional=MIN_NOTIONAL_USD)
        add_event(event="donchian_signal", pair=inst, strategy=STRATEGY, timeframe="1D",
                  message=f"{inst} {iso(latest)} close {d.close:,.4g}: {d.action} ({d.reason})", details=asdict(d))
        if d.action == "none":
            self.state["handled_bar"][inst] = latest
            return

        ticker = await self.market.get_ticker(inst)
        px = float(ticker.get("mid_price") or ticker.get("last") or 0.0)
        if px <= 0:
            return
        spec = self.specs[inst]
        if d.action == "buy":
            size_str = f"{d.quote_to_spend:.2f}"
            notional = d.quote_to_spend
        else:
            qty = floor_to_step(min(d.base_to_sell, sleeve.qty), spec["lot"])
            if qty < spec["min"] or qty * px < MIN_NOTIONAL_USD:
                self.state["handled_bar"][inst] = latest  # only dust left
                return
            size_str = f"{qty:.10f}".rstrip("0").rstrip(".")
            notional = qty * px

        exposure = {k: s.qty * (px if k == inst else s.entry_px or 0.0) for k, s in self.sleeves.items() if s.qty > 0}
        today = expected_latest_bar_ts(now_utc()) + 86_400_000
        realized_today = sum(t["realized_pnl_usd"] or 0.0 for t in self.state["trades"] if t["fill_ts"] >= today)
        decision = self.gate.validate(
            OrderIntent(inst_id=inst, side=d.action, notional_usd=notional, reference_price=d.close, execution_price=px,
                        reduce_only=d.action == "sell"),
            AccountState(instrument_notional_usd=exposure, total_exposure_usd=sum(exposure.values()), daily_realized_pnl_usd=realized_today),
        )
        if not decision.allowed:
            reasons = "; ".join(decision.rejection_reasons)
            add_event(event="donchian_order_rejected", level="warning", pair=inst, strategy=STRATEGY,
                      message=f"risk gate rejected {d.action}: {reasons}")
            await self._alert_once(f"reject:{inst}:{latest}", f"{inst} {d.action} 거부됨 (리스크 게이트): {reasons}. 다음 루프에 재시도.")
            return  # bar NOT marked: retried next loop

        cl_id = client_order_id(inst, latest, d.action)
        existing = await self.client.find_order(inst_id=inst, cl_ord_id=cl_id)
        pending = {"inst": inst, "side": d.action, "size": size_str, "sent_at": now_utc().isoformat(), "decision": asdict(d)}
        self.state["pending"][cl_id] = pending
        self._persist()  # record intent BEFORE sending
        if existing is None:
            try:
                await self.client.place_spot_market_order(inst_id=inst, side=d.action, size=size_str, cl_ord_id=cl_id,
                                                          size_in_quote=d.action == "buy")
            except Exception as exc:
                # Unknown outcome — never resend. Query by clOrdId below; if OKX never got it,
                # settle_pending drops it after the grace period and the bar is re-decided.
                add_event(event="donchian_order_error", level="error", pair=inst, strategy=STRATEGY,
                          message=f"{d.action} {cl_id} send failed: {type(exc).__name__}: {exc}")
                await self._alert_once(f"senderr:{cl_id}", f"{inst} {d.action} 주문 전송 오류 — 체결 여부를 주문번호로 확인 중입니다. ({exc})")
        for _ in range(FILL_POLL_ATTEMPTS):
            order = await self.client.find_order(inst_id=inst, cl_ord_id=cl_id)
            if order and str(order.get("state")) in {"filled", "canceled", "mmp_canceled"}:
                break
            await asyncio.sleep(FILL_POLL_DELAY_S)
        await self.settle_pending()

    # ---------------- 4. summary ----------------

    async def daily_summary(self) -> None:
        day = now_utc().strftime("%Y-%m-%d")
        if self.state.get("last_summary_day") == day:
            return
        lines, total = [], 0.0
        for inst, s in self.sleeves.items():
            t = await self.market.get_ticker(inst)
            px = float(t.get("last") or t.get("mid_price") or 0.0)
            eq = sleeve_equity(s, px)
            total += eq
            avg = f"{s.entry_px:,.4g}" if s.entry_px else "?"
            pos = f"보유 {s.qty:g} (평단 {avg})" if s.in_position(px, MIN_NOTIONAL_USD) else "현금"
            lines.append(f"{inst.split('-')[0]}: ${eq:,.0f} · {pos}")
        cap = self.state["config"]["capital_usd"]
        self.state["equity_history"].append({"day": day, "equity_usd": round(total, 2)})
        self.state["last_summary_day"] = day
        ks = "⚠️ 긴급정지 중" if self.gate.kill_switch.is_tripped() else "정상"
        await self.notify.send(f"일일 요약 {day} · 총 ${total:,.0f} ({(total/cap-1)*100:+.1f}%) · {ks}\n" + "\n".join(lines))

    # ---------------- loop ----------------

    async def run_once(self) -> None:
        await self.settle_pending()
        if await self.reconcile_books():
            for inst in self.pairs:
                try:
                    await self.process(inst)
                except Exception as exc:
                    add_event(event="donchian_error", level="error", pair=inst, strategy=STRATEGY, message=f"{type(exc).__name__}: {exc}")
                self._persist()
        await self.daily_summary()
        self._persist()

    async def close(self) -> None:
        self._persist()
        await self.market.close()
        await self.client.close()
        await self.notify.close()


async def run(args: argparse.Namespace) -> None:
    if settings.OKX_MODE != "demo":
        raise SystemExit(f"refusing to run: OKX_MODE={settings.OKX_MODE!r}; this trader is demo-only")
    try:
        from app.core.runtime_events import configure_persistence
        from app.db.database import AsyncSessionLocal

        configure_persistence(session_factory=AsyncSessionLocal)
    except Exception as exc:
        add_event(event="donchian_persistence_warning", level="warning", strategy=STRATEGY, message=str(exc))

    trader = Trader(args)
    try:
        await trader.start()
        while True:
            await trader.run_once()
            if args.once:
                break
            await asyncio.sleep(max(args.poll_seconds, 60))
    finally:
        await trader.close()
        try:
            from app.core.runtime_events import shutdown_persistence

            await asyncio.sleep(1.0)
            await shutdown_persistence()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT")
    p.add_argument("--capital-usd", type=float, default=4000.0, help="USDT split equally across sleeves")
    p.add_argument("--risk-pct", type=float, default=5.0, help="sleeve %% lost if the ATR stop is hit; 0 = all-in (v3)")
    p.add_argument("--entry", type=int, default=55)
    p.add_argument("--exit", type=int, default=20)
    p.add_argument("--atr-stop", type=float, default=2.0)
    p.add_argument("--poll-seconds", type=int, default=600)
    p.add_argument("--state-file", default="state/donchian_trader.json")
    p.add_argument("--once", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.risk_pct <= 0:
        args.risk_pct = None
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
