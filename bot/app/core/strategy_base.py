from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Signal(Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE = "close"
    HOLD = "hold"


@dataclass
class TradingContext:
    current_position: Optional[dict]  # {direction, entry_price, quantity, unrealized_pnl} or None
    account_balance: float
    leverage: int
    pair: str
    funding_rate: Optional[float] = None


@dataclass
class TradeSignal:
    signal: Signal
    pair: str
    leverage: int = 1
    size_pct: float = 100.0
    reason: str = ""
    tp_price: Optional[float] = None       # take-profit price
    sl_price: Optional[float] = None       # stop-loss price
    trailing_stop_pct: Optional[float] = None  # trailing stop as fraction (e.g. 0.02 = 2%)


class BaseStrategy(ABC):
    name: str

    @property
    @abstractmethod
    def lookback_period(self) -> int:
        ...

    @abstractmethod
    async def on_candle(
        self,
        candle: dict,
        history: list[dict],
        context: TradingContext,
    ) -> TradeSignal:
        ...

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass

    @abstractmethod
    def configure(self, params: dict) -> None:
        ...
