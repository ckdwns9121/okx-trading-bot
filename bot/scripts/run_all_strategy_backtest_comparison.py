#!/usr/bin/env python3
"""Run all discovered strategies against OKX public candles and write a report.

The script avoids DB writes and order endpoints. It fetches market candles once
per pair/timeframe, runs every strategy through the existing in-memory backtest
simulator, and writes both JSON evidence and a Markdown comparison report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import structlog

BOT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BOT_DIR.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from app.config import settings  # noqa: E402
from app.core.backtest_engine import _compute_metrics, _simulate_sync  # noqa: E402
from app.core.strategy_base import Signal, TradeSignal, TradingContext  # noqa: E402
from app.core.strategy_registry import auto_discover, registry  # noqa: E402
from app.exchange.okx_client import OKXClient  # noqa: E402

DEFAULT_PAIRS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")
DEFAULT_TIMEFRAMES = ("15m", "1H")
MS_PER_SECOND = 1000


@dataclass(frozen=True)
class CandleView:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def configure_script_logging(verbose: bool) -> None:
    if verbose:
        return
    logging.basicConfig(level=logging.WARNING)
    structlog.configure(
        processors=[structlog.stdlib.filter_by_level],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def ms_to_dt(value: str | int) -> datetime:
    return datetime.fromtimestamp(int(value) / MS_PER_SECOND, tz=timezone.utc).replace(tzinfo=None)


def candle_dict(candle: CandleView) -> dict[str, Any]:
    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


async def fetch_window(
    client: OKXClient,
    *,
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[CandleView]:
    start_ms = int(start.replace(tzinfo=timezone.utc).timestamp() * MS_PER_SECOND)
    end_ms = int(end.replace(tzinfo=timezone.utc).timestamp() * MS_PER_SECOND)
    cursor_after: str | None = str(end_ms + 1)
    by_ts: dict[int, CandleView] = {}

    while True:
        page = await client.get_candles(pair=pair, timeframe=timeframe, limit=100, after=cursor_after)
        if not page:
            break

        for raw in page:
            ts_ms = int(raw["timestamp"])
            if start_ms <= ts_ms <= end_ms:
                by_ts[ts_ms] = CandleView(
                    timestamp=ms_to_dt(ts_ms),
                    open=float(raw["open"]),
                    high=float(raw["high"]),
                    low=float(raw["low"]),
                    close=float(raw["close"]),
                    volume=float(raw["volume"]),
                )

        oldest_in_page = int(page[-1]["timestamp"])
        if oldest_in_page <= start_ms:
            break
        next_cursor = str(oldest_in_page)
        if next_cursor == cursor_after:
            break
        cursor_after = next_cursor

    return [by_ts[ts] for ts in sorted(by_ts)]


def strategy_params(strategy_name: str) -> dict[str, Any]:
    if strategy_name == "chronos_regime_hybrid":
        return {"chronos_enabled": False}
    return {}


async def run_strategy(
    *,
    strategy_name: str,
    candles: list[CandleView],
    pair: str,
    timeframe: str,
    initial_balance: float,
    leverage: int,
    fee_rate: float,
    slippage_pct: float,
    stop_loss_pct: float,
    cooldown_candles: int,
    funding_rate_per_8h: float,
    liquidity_impact_factor: float,
    maintenance_margin_ratio: float,
    liquidation_fee_pct: float,
) -> dict[str, Any]:
    strategy_cls = registry.get(strategy_name)
    strategy = strategy_cls()
    params = strategy_params(strategy_name)
    strategy.configure(params)
    lookback = strategy.lookback_period

    if len(candles) < lookback + 1:
        return {
            "status": "insufficient_candles",
            "parameters": params,
            "lookback_period": lookback,
            "error": f"need at least {lookback + 1} candles",
        }

    await strategy.on_start()
    history_window: deque[dict[str, Any]] = deque(maxlen=lookback)
    signals: list[TradeSignal] = []
    sim_position: dict[str, Any] | None = None
    sim_balance = initial_balance
    strategy_errors = 0

    for candle in candles:
        current = candle_dict(candle)
        context = TradingContext(
            current_position=sim_position,
            account_balance=sim_balance,
            leverage=leverage,
            pair=pair,
        )
        try:
            signal = await strategy.on_candle(current, list(history_window), context)
        except Exception:
            strategy_errors += 1
            signal = TradeSignal(signal=Signal.HOLD, pair=pair, leverage=leverage)
        signals.append(signal)

        if signal.signal in (Signal.LONG, Signal.SHORT):
            new_dir = "buy" if signal.signal == Signal.LONG else "sell"
            if sim_position is None or sim_position.get("direction") != new_dir:
                sim_position = {
                    "direction": new_dir,
                    "entry_price": candle.close,
                    "quantity": sim_balance * (signal.size_pct / 100.0),
                    "unrealized_pnl": 0.0,
                }
        elif signal.signal == Signal.CLOSE:
            sim_position = None

        history_window.append(current)

    await strategy.on_stop()

    trades, balance_series, final_balance = await asyncio.to_thread(
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
        trades,
        initial_balance,
        balance_series,
    )
    winning = sum(t.pnl for t in trades if t.pnl > 0.0)
    losing = abs(sum(t.pnl for t in trades if t.pnl < 0.0))
    profit_factor = winning / losing if losing > 0.0 else (winning if winning > 0.0 else 0.0)
    exit_counts = Counter(t.exit_reason or "unknown" for t in trades)

    return {
        "status": "ok",
        "run_id": str(uuid.uuid4()),
        "parameters": params,
        "lookback_period": lookback,
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "total_pnl": total_pnl,
        "return_pct": (total_pnl / initial_balance) * 100.0,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": len(trades),
        "profit_factor": profit_factor,
        "strategy_errors": strategy_errors,
        "exit_counts": dict(sorted(exit_counts.items())),
    }


def verdict_for(summary: dict[str, Any]) -> str:
    if summary["ok_runs"] == 0:
        return "데이터부족/오류"
    if summary["positive_runs"] == summary["ok_runs"] and summary["max_drawdown_pct"] <= 25.0:
        return "paper 후보"
    if summary["total_pnl"] > 0 and summary["positive_rate_pct"] >= 50.0 and summary["max_drawdown_pct"] <= 40.0:
        return "연구 후보"
    if summary["total_pnl"] > 0:
        return "고위험 관찰"
    return "탈락/보류"


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    strategy_names = sorted({row["strategy"] for row in results})
    for strategy in strategy_names:
        rows = [row for row in results if row["strategy"] == strategy]
        ok_rows = [row for row in rows if row["status"] == "ok"]
        pnls = [row["total_pnl"] for row in ok_rows]
        best = max(ok_rows, key=lambda row: row["total_pnl"], default=None)
        worst = min(ok_rows, key=lambda row: row["total_pnl"], default=None)
        summary = {
            "strategy": strategy,
            "runs": len(rows),
            "ok_runs": len(ok_rows),
            "positive_runs": sum(1 for row in ok_rows if row["total_pnl"] > 0.0),
            "total_pnl": sum(pnls),
            "avg_pnl": (sum(pnls) / len(pnls)) if pnls else 0.0,
            "median_pnl": median(pnls) if pnls else 0.0,
            "avg_profit_factor": (
                sum(row["profit_factor"] for row in ok_rows) / len(ok_rows)
                if ok_rows
                else 0.0
            ),
            "avg_sharpe": (
                sum(row["sharpe_ratio"] for row in ok_rows) / len(ok_rows)
                if ok_rows
                else 0.0
            ),
            "avg_win_rate_pct": (
                sum(row["win_rate"] for row in ok_rows) / len(ok_rows) * 100.0
                if ok_rows
                else 0.0
            ),
            "max_drawdown_pct": max((row["max_drawdown"] for row in ok_rows), default=0.0) * 100.0,
            "total_trades": sum(row.get("trade_count", 0) for row in ok_rows),
            "error_runs": sum(1 for row in rows if row["status"] not in ("ok",)),
            "best_run": best,
            "worst_run": worst,
        }
        summary["positive_rate_pct"] = (
            summary["positive_runs"] / summary["ok_runs"] * 100.0 if summary["ok_runs"] else 0.0
        )
        summary["verdict"] = verdict_for(summary)
        summaries.append(summary)

    return sorted(
        summaries,
        key=lambda row: (
            row["verdict"] not in ("paper 후보", "연구 후보"),
            -row["total_pnl"],
            row["max_drawdown_pct"],
        ),
    )


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def best_worst_label(row: dict[str, Any] | None) -> str:
    if row is None:
        return "-"
    return f"{row['pair']} {row['timeframe']} {fmt(row['total_pnl'])}"


def top_exits(row: dict[str, Any]) -> str:
    counts = row.get("exit_counts") or {}
    if not counts:
        return "-"
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name}:{count}" for name, count in ordered[:3])


def conclusion_lines(payload: dict[str, Any]) -> list[str]:
    summaries = payload["summaries"]
    if not summaries:
        return ["- 실행 가능한 결과가 없어 전략 결론을 낼 수 없다."]

    raw_best = max(summaries, key=lambda row: row["total_pnl"])
    paper_candidates = [row for row in summaries if row["verdict"] == "paper 후보"]
    research_candidates = [row for row in summaries if row["verdict"] == "연구 후보"]

    lines = [
        f"- 단순 합산 PnL 1위는 `{raw_best['strategy']}`이지만 Max DD가 `{fmt(raw_best['max_drawdown_pct'])}%`라서 바로 demo/live 후보로 보지 않는다.",
    ]
    if paper_candidates:
        names = ", ".join(f"`{row['strategy']}`" for row in paper_candidates)
        lines.append(f"- paper 후보: {names}")
    elif research_candidates:
        names = ", ".join(f"`{row['strategy']}`" for row in research_candidates)
        lines.append(f"- paper 후보는 없고, 추가 연구 후보만 있다: {names}")
    else:
        lines.append("- paper 후보와 연구 후보 모두 없다. 수익성보다 생존성 기준에서 전체적으로 불안정하다.")

    regime = next((row for row in summaries if row["strategy"] == "rsi_bollinger_regime"), None)
    if regime is not None:
        lines.append(
            f"- 기존 demo 관찰 후보인 `rsi_bollinger_regime`은 이번 비교에서도 양수 실행 `{regime['positive_runs']}/{regime['ok_runs']}`이지만 Max DD `{fmt(regime['max_drawdown_pct'])}%`라서 `risk_profile=limited` 조건을 계속 유지해야 한다."
        )
    return lines


def markdown_report(payload: dict[str, Any]) -> str:
    summaries = payload["summaries"]
    results = payload["results"]
    lines = [
        "# 전체 전략 백테스트 비교 리포트",
        "",
        f"- 작성일: `{payload['created_at']}`",
        f"- 데이터 구간(UTC): `{payload['start']}` ~ `{payload['end']}`",
        f"- 종목: `{', '.join(payload['pairs'])}`",
        f"- 시간봉: `{', '.join(payload['timeframes'])}`",
        f"- 전략 수: `{len(payload['strategies'])}`개",
        f"- 비용/체결 가정: 수수료 `{payload['assumptions']['fee_rate']}`, 슬리피지 `{payload['assumptions']['slippage_pct']}%`, 펀딩 `{payload['assumptions']['funding_rate_per_8h']}/8h`, 유동성 영향 `{payload['assumptions']['liquidity_impact_factor']}`",
        "",
        "## 해석 기준",
        "",
        "- 이 표는 연구용 백테스트 결과이며 수익 보장이나 실거래 권고가 아니다.",
        "- `chronos_regime_hybrid`는 현재 프로젝트 기본값에 맞춰 `chronos_enabled=false` fallback 경로로 비교했다.",
        "- `ma_7d_5m`은 원래 5분봉 전용 전략이지만, 전체 전략 공통 비교를 위해 같은 시간봉에서도 실행했다.",
        "- `데이터부족/오류`는 해당 전략의 lookback보다 candle 수가 부족하거나 실행 중 오류가 발생한 경우다.",
        "",
        "## 핵심 결론",
        "",
        *conclusion_lines(payload),
        "",
        "## 전략별 종합 순위",
        "",
        "| 순위 | 전략 | 판정 | 실행 | 양수 실행 | 합산 PnL | 평균 PnL | 중앙 PnL | 평균 PF | 평균 Sharpe | 평균 승률 | Max DD | 거래수 | 최고 Run | 최악 Run |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for idx, row in enumerate(summaries, start=1):
        lines.append(
            "| {idx} | `{strategy}` | {verdict} | {ok}/{runs} | {positive} | {total} | {avg} | {median} | {pf} | {sharpe} | {win}% | {dd}% | {trades} | {best} | {worst} |".format(
                idx=idx,
                strategy=row["strategy"],
                verdict=row["verdict"],
                ok=row["ok_runs"],
                runs=row["runs"],
                positive=row["positive_runs"],
                total=fmt(row["total_pnl"]),
                avg=fmt(row["avg_pnl"]),
                median=fmt(row["median_pnl"]),
                pf=fmt(row["avg_profit_factor"]),
                sharpe=fmt(row["avg_sharpe"]),
                win=fmt(row["avg_win_rate_pct"], 1),
                dd=fmt(row["max_drawdown_pct"], 2),
                trades=row["total_trades"],
                best=best_worst_label(row["best_run"]),
                worst=best_worst_label(row["worst_run"]),
            )
        )

    lines += [
        "",
        "## Run 상세",
        "",
        "| 전략 | 종목 | TF | 상태 | Candles | PnL | Return | 승률 | Max DD | PF | Sharpe | 거래수 | 주요 청산 | 비고 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in sorted(results, key=lambda item: (item["strategy"], item["pair"], item["timeframe"])):
        if row["status"] != "ok":
            lines.append(
                f"| `{row['strategy']}` | {row['pair']} | {row['timeframe']} | {row['status']} | {row['candles']} | - | - | - | - | - | - | - | - | {row.get('error', '')} |"
            )
            continue
        note = ""
        if row.get("strategy_errors"):
            note = f"strategy_errors={row['strategy_errors']}"
        lines.append(
            "| `{strategy}` | {pair} | {tf} | ok | {candles} | {pnl} | {ret}% | {win}% | {dd}% | {pf} | {sharpe} | {trades} | {exits} | {note} |".format(
                strategy=row["strategy"],
                pair=row["pair"],
                tf=row["timeframe"],
                candles=row["candles"],
                pnl=fmt(row["total_pnl"]),
                ret=fmt(row["return_pct"]),
                win=fmt(row["win_rate"] * 100.0, 1),
                dd=fmt(row["max_drawdown"] * 100.0, 2),
                pf=fmt(row["profit_factor"]),
                sharpe=fmt(row["sharpe_ratio"]),
                trades=row["trade_count"],
                exits=top_exits(row),
                note=note,
            )
        )

    error_rows = [row for row in results if row["status"] != "ok" or row.get("strategy_errors")]
    lines += [
        "",
        "## 검증 메모",
        "",
        f"- 총 실행 행: `{len(results)}`",
        f"- 정상 실행 행: `{sum(1 for row in results if row['status'] == 'ok')}`",
        f"- 데이터부족/오류 행: `{len([row for row in results if row['status'] != 'ok'])}`",
        f"- 원자료 JSON: `{payload['json_path']}`",
    ]
    if error_rows:
        lines.append("- 일부 행은 데이터 부족 또는 전략 내부 예외가 있어 상세 표의 비고를 확인해야 한다.")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> dict[str, Any]:
    auto_discover(BOT_DIR / "strategies")
    strategies = parse_csv(args.strategies) if args.strategies else registry.list_all()
    pairs = parse_csv(args.pairs)
    timeframes = parse_csv(args.timeframes)
    end = parse_dt(args.end) if args.end else datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    assumptions = {
        "initial_balance": args.initial_balance,
        "leverage": args.leverage,
        "fee_rate": args.fee_rate,
        "slippage_pct": args.slippage_pct,
        "stop_loss_pct": args.stop_loss_pct,
        "cooldown_candles": args.cooldown_candles,
        "funding_rate_per_8h": args.funding_rate_per_8h,
        "liquidity_impact_factor": args.liquidity_impact_factor,
        "maintenance_margin_ratio": args.maintenance_margin_ratio,
        "liquidation_fee_pct": args.liquidation_fee_pct,
    }

    client = OKXClient(
        api_key=settings.OKX_API_KEY,
        secret=settings.OKX_SECRET,
        passphrase=settings.OKX_PASSPHRASE,
        mode=settings.OKX_MODE,
    )
    results: list[dict[str, Any]] = []
    try:
        datasets: dict[tuple[str, str], list[CandleView]] = {}
        for pair in pairs:
            for timeframe in timeframes:
                print(f"fetch {pair} {timeframe} {start.isoformat()}..{end.isoformat()}", flush=True)
                datasets[(pair, timeframe)] = await fetch_window(
                    client,
                    pair=pair,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )

        for strategy_name in strategies:
            if strategy_name not in registry.list_all():
                raise RuntimeError(f"Unknown strategy {strategy_name!r}; available={registry.list_all()}")
            for pair in pairs:
                for timeframe in timeframes:
                    candles = datasets[(pair, timeframe)]
                    print(f"run {strategy_name} {pair} {timeframe} candles={len(candles)}", flush=True)
                    row_base = {
                        "strategy": strategy_name,
                        "pair": pair,
                        "timeframe": timeframe,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "candles": len(candles),
                    }
                    try:
                        metrics = await run_strategy(
                            strategy_name=strategy_name,
                            candles=candles,
                            pair=pair,
                            timeframe=timeframe,
                            **assumptions,
                        )
                    except Exception as exc:
                        metrics = {"status": "error", "error": str(exc)}
                    results.append({**row_base, **metrics})
    finally:
        await client.close()

    payload = {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "pairs": pairs,
        "timeframes": timeframes,
        "strategies": strategies,
        "assumptions": assumptions,
        "results": results,
        "summaries": summarize(results),
    }
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--strategies", default=None, help="Comma-separated strategy names. Default: all discovered.")
    parser.add_argument("--end", default=None, help="UTC ISO timestamp. Default: current UTC.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--leverage", type=int, default=2)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--stop-loss-pct", type=float, default=0.03)
    parser.add_argument("--cooldown-candles", type=int, default=0)
    parser.add_argument("--funding-rate-per-8h", type=float, default=0.0001)
    parser.add_argument("--liquidity-impact-factor", type=float, default=0.1)
    parser.add_argument("--maintenance-margin-ratio", type=float, default=0.005)
    parser.add_argument("--liquidation-fee-pct", type=float, default=0.002)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--md-out", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_script_logging(args.verbose)

    payload = asyncio.run(run(args))
    stamp = payload["created_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    stamp = stamp.replace("+00:00", "Z")
    json_path = (
        Path(args.json_out)
        if args.json_out
        else REPO_DIR / f".omx/context/all-strategy-backtest-comparison-{stamp}.json"
    ).resolve()
    md_path = (
        Path(args.md_out)
        if args.md_out
        else REPO_DIR / f"docs/all-strategy-backtest-comparison-{stamp}.md"
    ).resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload["json_path"] = str(json_path.relative_to(REPO_DIR))
    except ValueError:
        payload["json_path"] = str(json_path)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown_report(payload), encoding="utf-8")

    print(json.dumps({"json_out": str(json_path), "md_out": str(md_path), "rows": len(payload["results"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
