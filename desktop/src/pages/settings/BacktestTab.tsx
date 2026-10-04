import { useEffect, useState } from "react";
import { runBacktest } from "@/lib/api";
import type { BacktestRequest, BacktestResult } from "@/lib/types";
import { deltaClass, fmtPct, fmtUsd } from "@/lib/format";
import EquityChart from "@/components/EquityChart";
import { Badge, Button, Card, Notice, Segmented, Select } from "@/components/ui";

const STORAGE_KEY = "okxbot.backtest";

const DEFAULTS: BacktestRequest = {
  strategy: "donchian",
  pairs: ["BTC-USDT"],
  days: 400,
  allocation_usd: 1000,
  fee_pct: 0.1,
  min_trade_usd: 25,
  donchian: { entry_period: 55, exit_period: 20, atr_period: 20, atr_stop_mult: 2 },
  ma_periods: [20, 50, 100],
};

const DAY_OPTIONS = [
  { value: 180, label: "6개월" },
  { value: 400, label: "400일" },
  { value: 730, label: "2년" },
  { value: 900, label: "900일" },
  { value: 1200, label: "1200일" },
];

function loadSaved(): BacktestRequest {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<BacktestRequest>) };
  } catch {
    /* ignore */
  }
  return DEFAULTS;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink-secondary">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink-faint mt-1">{hint}</span>}
    </label>
  );
}

const inputCls =
  "mt-1.5 h-10 w-full bg-surface-muted rounded-md px-3 text-base text-ink tabular focus:outline-none focus:bg-surface focus:ring-2 focus:ring-blue-200 transition-colors";

function NumberInput({ value, onChange, step = 1, min, max }: { value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number }) {
  return (
    <input
      type="number"
      value={Number.isFinite(value) ? value : ""}
      step={step}
      min={min}
      max={max}
      onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))}
      className={inputCls}
    />
  );
}

function Metric({ label, value, sub, cls }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="rounded-lg bg-surface-muted px-4 py-3">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className={`mt-0.5 text-xl font-bold tabular ${cls ?? "text-ink"}`}>{value}</p>
      {sub && <p className="text-xs text-ink-faint mt-0.5 tabular">{sub}</p>}
    </div>
  );
}

export default function BacktestTab() {
  const [req, setReq] = useState<BacktestRequest>(loadSaved);
  const [pairsText, setPairsText] = useState(() => loadSaved().pairs.join(", "));
  const [maText, setMaText] = useState(() => loadSaved().ma_periods.join(", "));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  // 설정은 이 기기에 저장 — 다음에 열어도 마지막 파라미터가 그대로
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(req));
    } catch {
      /* ignore */
    }
  }, [req]);

  function patch(p: Partial<BacktestRequest>) {
    setReq((r) => ({ ...r, ...p }));
  }
  function patchDonchian(p: Partial<BacktestRequest["donchian"]>) {
    setReq((r) => ({ ...r, donchian: { ...r.donchian, ...p } }));
  }

  async function onRun() {
    const pairs = pairsText.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
    const ma = maText.split(",").map((s) => Number(s.trim())).filter((n) => Number.isFinite(n) && n > 1);
    if (pairs.length === 0) return setError("종목을 한 개 이상 입력하세요 (예: BTC-USDT)");
    if (req.strategy === "ma" && ma.length === 0) return setError("이동평균 기간을 입력하세요 (예: 20, 50, 100)");
    const payload: BacktestRequest = { ...req, pairs, ma_periods: ma.length ? ma : req.ma_periods };
    setReq(payload);
    setRunning(true);
    setError(null);
    const started = performance.now();
    try {
      const res = await runBacktest(payload);
      setResult(res);
      setElapsedMs(performance.now() - started);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const beatBenchmark = result ? result.total_return_pct > result.buy_hold_return_pct : false;

  return (
    <div className="space-y-6">
      <Notice tone="blue" title="백테스트는 읽기 전용입니다">
        OKX 공개 일봉을 받아 수수료를 반영해 계산합니다. 종가에 결정하고 다음 날 시가에 체결하므로 미래 데이터가 섞이지 않습니다. 주문은 전혀 나가지 않아요.
      </Notice>

      <Card
        title="백테스트 설정"
        sub="전략과 기간, 비용을 고르고 실행하세요"
        action={
          <Button variant="primary" onClick={onRun} disabled={running}>
            {running ? (
              <>
                <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                캔들 받는 중…
              </>
            ) : (
              "백테스트 실행"
            )}
          </Button>
        }
      >
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-ink-secondary w-16">전략</span>
            <Segmented
              value={req.strategy}
              onChange={(v) => patch({ strategy: v })}
              options={[
                { value: "donchian", label: "돈치안 채널 돌파" },
                { value: "ma", label: "이동평균 앙상블" },
              ]}
            />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Field label="종목" hint="쉼표로 구분 · 현물 심볼">
              <input value={pairsText} onChange={(e) => setPairsText(e.target.value)} placeholder="BTC-USDT, ETH-USDT" className={inputCls} />
            </Field>
            <Field label="기간">
              <Select value={String(req.days)} onChange={(v) => patch({ days: Number(v) })} className="mt-1.5 h-10 w-full text-base">
                {DAY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="종목당 투입 (USD)">
              <NumberInput value={req.allocation_usd} onChange={(v) => patch({ allocation_usd: v })} step={100} min={10} />
            </Field>
            <Field label="수수료 (%/편도)" hint="OKX 테이커 기준 0.10">
              <NumberInput value={req.fee_pct} onChange={(v) => patch({ fee_pct: v })} step={0.01} min={0} max={5} />
            </Field>
          </div>

          {req.strategy === "donchian" ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-line">
              <Field label="진입 채널 (일)" hint="N일 신고가 돌파 시 매수">
                <NumberInput value={req.donchian.entry_period} onChange={(v) => patchDonchian({ entry_period: v })} min={5} max={400} />
              </Field>
              <Field label="청산 채널 (일)" hint="M일 신저가 이탈 시 매도">
                <NumberInput value={req.donchian.exit_period} onChange={(v) => patchDonchian({ exit_period: v })} min={2} max={400} />
              </Field>
              <Field label="ATR 기간">
                <NumberInput value={req.donchian.atr_period} onChange={(v) => patchDonchian({ atr_period: v })} min={2} max={200} />
              </Field>
              <Field label="ATR 손절 배수" hint="0이면 손절 없음">
                <NumberInput value={req.donchian.atr_stop_mult} onChange={(v) => patchDonchian({ atr_stop_mult: v })} step={0.5} min={0} max={20} />
              </Field>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 pt-4 border-t border-line">
              <Field label="이동평균 기간" hint="쉼표로 구분 · 종가가 위에 있는 MA 비율만큼 보유">
                <input value={maText} onChange={(e) => setMaText(e.target.value)} placeholder="20, 50, 100" className={inputCls} />
              </Field>
              <Field label="최소 주문 (USD)">
                <NumberInput value={req.min_trade_usd} onChange={(v) => patch({ min_trade_usd: v })} min={0} />
              </Field>
            </div>
          )}
        </div>
      </Card>

      {error && (
        <Notice tone="red" title="백테스트를 실행하지 못했어요">{error}</Notice>
      )}

      {result && (
        <Card
          title="결과"
          sub={
            <span className="tabular">
              {result.instruments.join(", ")} · {result.days_tested}일 검증 · {fmtDate(result.candles_from)} ~ {fmtDate(result.candles_to)}
              {elapsedMs !== null && ` · ${(elapsedMs / 1000).toFixed(1)}초`}
            </span>
          }
          action={
            <Badge tone={beatBenchmark ? "blue" : "grey"}>{beatBenchmark ? "매수-보유 대비 우위" : "매수-보유가 더 나음"}</Badge>
          }
        >
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <Metric
                label="총 수익률"
                value={fmtPct(result.total_return_pct, { digits: 1 })}
                sub={`매수 보유 ${fmtPct(result.buy_hold_return_pct, { digits: 1 })}`}
                cls={deltaClass(result.total_return_pct)}
              />
              <Metric
                label="최대 낙폭"
                value={`-${result.max_drawdown_pct.toFixed(1)}%`}
                sub={`매수 보유 -${result.buy_hold_max_drawdown_pct.toFixed(1)}%`}
                cls="text-down"
              />
              <Metric label="거래 수" value={`${result.trade_count}건`} sub={result.win_rate_pct !== undefined ? `승률 ${result.win_rate_pct.toFixed(0)}%` : undefined} />
              <Metric label="수수료 합계" value={fmtUsd(result.fees_paid_usd, { digits: 0 })} sub={`${((result.fees_paid_usd / result.starting_equity_usd) * 100).toFixed(2)}% of 원금`} />
              <Metric label="최종 자산" value={fmtUsd(result.final_equity_usd, { digits: 0 })} sub={`시작 ${fmtUsd(result.starting_equity_usd, { digits: 0 })}`} />
            </div>

            <EquityChart points={result.equity_curve} startingEquity={result.starting_equity_usd} />

            <p className="text-xs text-ink-faint leading-relaxed">
              과거 수익률은 미래를 보장하지 않습니다. 이 결과는 데모 트레이딩으로 넘어갈지 판단하는 재료일 뿐이며, 백테스트가 좋았던 전략도 실제 체결 비용과 추세 부재 구간에서 다르게 움직입니다.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}

function fmtDate(ts: string): string {
  const d = new Date(Number(ts));
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleDateString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric" });
}
