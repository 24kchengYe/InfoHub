"""Simple backtesting engine — validates trading strategies against historical data."""

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional

from .indicators import TechnicalIndicators
from .market_data import MarketDataProvider, OHLCV

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """A single trade in backtesting."""
    ticker: str
    side: str           # "buy" | "sell"
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    quantity: int = 1
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # "take_profit" | "stop_loss" | "signal_reversal" | "end_of_period"


@dataclass
class BacktestResult:
    """Backtesting result summary."""
    ticker: str
    period: str               # "2025-01-01 to 2025-12-31"
    initial_capital: float
    final_capital: float
    total_return: float       # percentage
    annual_return: float      # annualized percentage
    max_drawdown: float       # percentage
    sharpe_ratio: float
    win_rate: float           # percentage
    total_trades: int
    profit_trades: int
    loss_trades: int
    avg_profit_pct: float
    avg_loss_pct: float
    profit_factor: float      # gross profit / gross loss
    max_consecutive_wins: int
    max_consecutive_losses: int
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)  # [{"date": str, "equity": float}]


class Backtester:
    """Simple backtesting engine using technical indicators.

    Strategy: buy on bullish signal, sell on bearish signal or stop-loss/take-profit.
    """

    def __init__(
        self,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.15,
        initial_capital: float = 100000.0,
        position_pct: float = 0.1,  # Use 10% of capital per trade
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.initial_capital = initial_capital
        self.position_pct = position_pct
        self.market_data = MarketDataProvider()

    async def run(
        self,
        ticker: str,
        days: int = 365,
    ) -> BacktestResult:
        """Run backtest on a single ticker using technical signals.

        Args:
            ticker: Stock ticker symbol
            days: Number of historical days to test
        """
        # Fetch historical data
        kline = await self.market_data.get_kline(ticker, "daily", days)
        if len(kline) < 60:
            return BacktestResult(
                ticker=ticker,
                period=f"Insufficient data ({len(kline)} days)",
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                total_return=0, annual_return=0, max_drawdown=0,
                sharpe_ratio=0, win_rate=0, total_trades=0,
                profit_trades=0, loss_trades=0, avg_profit_pct=0,
                avg_loss_pct=0, profit_factor=0,
                max_consecutive_wins=0, max_consecutive_losses=0,
            )

        return self._simulate(ticker, kline)

    def _simulate(self, ticker: str, kline: List[OHLCV]) -> BacktestResult:
        """Run the simulation on historical data."""
        capital = self.initial_capital
        position: Optional[BacktestTrade] = None
        trades: List[BacktestTrade] = []
        equity_curve: List[dict] = []
        peak_equity = capital
        max_drawdown = 0.0
        daily_returns: List[float] = []
        prev_equity = capital

        # We need at least 30 bars of history before we can generate signals
        lookback = 30

        for i in range(lookback, len(kline)):
            # Current bar
            bar = kline[i]
            price = bar.close

            # Calculate equity
            equity = capital
            if position:
                unrealized = (price - position.entry_price) * position.quantity
                equity += unrealized

            equity_curve.append({"date": bar.date, "equity": round(equity, 2)})

            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

            # Daily return
            if prev_equity > 0:
                daily_returns.append((equity - prev_equity) / prev_equity)
            prev_equity = equity

            # Generate signal using data up to current bar
            closes = [k.close for k in kline[:i + 1]]
            highs = [k.high for k in kline[:i + 1]]
            lows = [k.low for k in kline[:i + 1]]
            signal = TechnicalIndicators.generate_signal(closes, highs, lows)

            # Position management
            if position:
                # Check stop-loss
                sl_price = position.entry_price * (1 - self.stop_loss_pct)
                if price <= sl_price:
                    position.exit_date = bar.date
                    position.exit_price = price
                    position.pnl = (price - position.entry_price) * position.quantity
                    position.pnl_pct = (price - position.entry_price) / position.entry_price * 100
                    position.exit_reason = "stop_loss"
                    capital += position.entry_price * position.quantity + position.pnl
                    trades.append(position)
                    position = None
                    continue

                # Check take-profit
                tp_price = position.entry_price * (1 + self.take_profit_pct)
                if price >= tp_price:
                    position.exit_date = bar.date
                    position.exit_price = price
                    position.pnl = (price - position.entry_price) * position.quantity
                    position.pnl_pct = (price - position.entry_price) / position.entry_price * 100
                    position.exit_reason = "take_profit"
                    capital += position.entry_price * position.quantity + position.pnl
                    trades.append(position)
                    position = None
                    continue

                # Check for bearish reversal
                if signal.direction == "bearish" and signal.strength > 0.6:
                    position.exit_date = bar.date
                    position.exit_price = price
                    position.pnl = (price - position.entry_price) * position.quantity
                    position.pnl_pct = (price - position.entry_price) / position.entry_price * 100
                    position.exit_reason = "signal_reversal"
                    capital += position.entry_price * position.quantity + position.pnl
                    trades.append(position)
                    position = None

            else:
                # No position — look for entry
                if signal.direction == "bullish" and signal.strength > 0.5:
                    allocation = capital * self.position_pct
                    quantity = int(allocation / price) if price > 0 else 0
                    if quantity > 0:
                        cost = price * quantity
                        capital -= cost
                        position = BacktestTrade(
                            ticker=ticker,
                            side="buy",
                            entry_date=bar.date,
                            entry_price=price,
                            quantity=quantity,
                        )

        # Close any remaining position at end
        if position:
            last_price = kline[-1].close
            position.exit_date = kline[-1].date
            position.exit_price = last_price
            position.pnl = (last_price - position.entry_price) * position.quantity
            position.pnl_pct = (last_price - position.entry_price) / position.entry_price * 100
            position.exit_reason = "end_of_period"
            capital += position.entry_price * position.quantity + position.pnl
            trades.append(position)

        # Calculate metrics
        final_capital = capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        trading_days = len(kline) - lookback
        annual_return = (((final_capital / self.initial_capital) ** (252 / max(trading_days, 1))) - 1) * 100 if trading_days > 0 else 0

        profit_trades = [t for t in trades if t.pnl > 0]
        loss_trades_list = [t for t in trades if t.pnl <= 0]
        win_rate = len(profit_trades) / len(trades) * 100 if trades else 0

        avg_profit = sum(t.pnl_pct for t in profit_trades) / len(profit_trades) if profit_trades else 0
        avg_loss = sum(t.pnl_pct for t in loss_trades_list) / len(loss_trades_list) if loss_trades_list else 0

        gross_profit = sum(t.pnl for t in profit_trades)
        gross_loss = abs(sum(t.pnl for t in loss_trades_list))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        # Sharpe ratio (annualized, assuming 252 trading days)
        if daily_returns and len(daily_returns) > 1:
            mean_return = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std_return = math.sqrt(variance) if variance > 0 else 0.001
            sharpe = (mean_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        else:
            sharpe = 0

        # Consecutive wins/losses
        max_wins = max_losses = current_wins = current_losses = 0
        for t in trades:
            if t.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        period_str = f"{kline[lookback].date} to {kline[-1].date}" if len(kline) > lookback else "N/A"

        return BacktestResult(
            ticker=ticker,
            period=period_str,
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 2),
            total_return=round(total_return, 2),
            annual_return=round(annual_return, 2),
            max_drawdown=round(max_drawdown, 2),
            sharpe_ratio=round(sharpe, 2),
            win_rate=round(win_rate, 1),
            total_trades=len(trades),
            profit_trades=len(profit_trades),
            loss_trades=len(loss_trades_list),
            avg_profit_pct=round(avg_profit, 2),
            avg_loss_pct=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
            max_consecutive_wins=max_wins,
            max_consecutive_losses=max_losses,
            trades=trades,
            equity_curve=equity_curve,
        )

    def generate_report(self, result: BacktestResult) -> str:
        """Generate a Markdown backtest report."""
        lines = [
            f"# 回测报告 — {result.ticker}",
            f"**测试区间**: {result.period}",
            f"**初始资金**: ${result.initial_capital:,.0f}",
            "",
            "## 核心指标",
            f"| 指标 | 值 |",
            f"|------|------|",
            f"| 最终资金 | ${result.final_capital:,.0f} |",
            f"| 总收益 | {result.total_return:+.2f}% |",
            f"| 年化收益 | {result.annual_return:+.2f}% |",
            f"| 最大回撤 | {result.max_drawdown:.2f}% |",
            f"| 夏普比率 | {result.sharpe_ratio:.2f} |",
            f"| 胜率 | {result.win_rate:.1f}% |",
            f"| 盈亏比 | {result.profit_factor:.2f} |",
            "",
            "## 交易统计",
            f"| 指标 | 值 |",
            f"|------|------|",
            f"| 总交易次数 | {result.total_trades} |",
            f"| 盈利交易 | {result.profit_trades} |",
            f"| 亏损交易 | {result.loss_trades} |",
            f"| 平均盈利 | {result.avg_profit_pct:+.2f}% |",
            f"| 平均亏损 | {result.avg_loss_pct:+.2f}% |",
            f"| 最大连赢 | {result.max_consecutive_wins} |",
            f"| 最大连亏 | {result.max_consecutive_losses} |",
            "",
        ]

        if result.trades:
            lines.append("## 交易记录")
            lines.append("| 日期 | 方向 | 入场价 | 出场价 | 盈亏 | 原因 |")
            lines.append("|------|------|--------|--------|------|------|")
            for t in result.trades[-20:]:  # Last 20 trades
                lines.append(
                    f"| {t.entry_date} → {t.exit_date} | {t.side} | "
                    f"${t.entry_price:.2f} | ${t.exit_price:.2f} | "
                    f"{t.pnl_pct:+.1f}% | {t.exit_reason} |"
                )

        return "\n".join(lines)
