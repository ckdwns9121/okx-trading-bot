import { getPnl, getPositions, getTrades, getHealth, getAccountBalance } from "@/lib/api";
import OverviewClient from "./OverviewClient";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [pnl, positions, trades, health, balance] = await Promise.allSettled([
    getPnl("live"),
    getPositions(),
    getTrades({ source: "live", limit: 100 }),
    getHealth(),
    getAccountBalance(),
  ]);

  const pnlData =
    pnl.status === "fulfilled"
      ? pnl.value
      : { realized_pnl: 0, win_rate: 0, trade_count: 0, today_pnl: 0 };

  const positionsData =
    positions.status === "fulfilled" ? positions.value : [];

  const tradesData =
    trades.status === "fulfilled" ? trades.value : [];

  const healthData =
    health.status === "fulfilled"
      ? health.value
      : null;

  const balanceData =
    balance.status === "fulfilled"
      ? balance.value
      : null;

  return (
    <OverviewClient
      initialPnl={pnlData}
      initialPositions={positionsData}
      initialTrades={tradesData}
      initialHealth={healthData}
      initialBalance={balanceData}
    />
  );
}
