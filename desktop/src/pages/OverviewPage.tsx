import type { AccountBalance, HealthStatus, PnlSummary, Position, Trade } from "@/lib/types";
import OverviewClient from "./OverviewClient";

const EMPTY_PNL: PnlSummary = {
  realized_pnl: 0,
  win_rate: 0,
  trade_count: 0,
  today_pnl: 0,
};

const EMPTY_POSITIONS: Position[] = [];
const EMPTY_TRADES: Trade[] = [];
const EMPTY_HEALTH: HealthStatus | null = null;
const EMPTY_BALANCE: AccountBalance | null = null;

export default function OverviewPage() {
  return (
    <OverviewClient
      initialPnl={EMPTY_PNL}
      initialPositions={EMPTY_POSITIONS}
      initialTrades={EMPTY_TRADES}
      initialHealth={EMPTY_HEALTH}
      initialBalance={EMPTY_BALANCE}
    />
  );
}
