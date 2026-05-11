"""Risk Agent — LLM-based portfolio risk assessment."""

from typing import List

from .base import BaseAgent, AgentOpinion
from .prompts import RISK_AGENT_SYSTEM
from src.ai.client import AIClient
from src.trading.risk import Account, Position


class RiskAgent(BaseAgent):
    """Evaluates portfolio risk state and advises on trade prudence."""

    def __init__(self, ai_client: AIClient):
        super().__init__(ai_client, "risk")

    async def analyze(
        self,
        ticker: str,
        proposed_direction: str,
        account: Account,
        positions: List[Position],
    ) -> AgentOpinion:
        """Evaluate portfolio risk for a proposed trade.

        Args:
            ticker: Target ticker
            proposed_direction: "long" or "short" from quick heuristic
            account: Current account state
            positions: Current open positions
        """
        # Build portfolio summary
        total_exposure = sum(p.market_value for p in positions)
        exposure_pct = (total_exposure / account.equity * 100) if account.equity > 0 else 0

        positions_text = "None" if not positions else "\n".join(
            f"  - {p.ticker}: {p.quantity} shares @ ${p.avg_price:.2f}, "
            f"P&L: ${p.pnl:.2f} ({p.pnl_pct:.1f}%), "
            f"weight: {(p.market_value / account.equity * 100):.1f}%"
            for p in positions
        )

        # Check if ticker already held
        existing = next((p for p in positions if p.ticker == ticker), None)
        already_held = f"Yes — {existing.quantity} shares, P&L: ${existing.pnl:.2f}" if existing else "No"

        user_prompt = f"""Proposed Trade:
- Ticker: ${ticker}
- Direction: {proposed_direction}
- Already holding: {already_held}

Portfolio State:
- Total Equity: ${account.equity:,.2f}
- Cash Available: ${account.cash:,.2f}
- Daily P&L: ${account.daily_pnl:,.2f} ({account.daily_pnl_pct:.2f}%)
- Total Exposure: ${total_exposure:,.2f} ({exposure_pct:.1f}% of equity)
- Open Positions: {len(positions)}/{10} max

Current Positions:
{positions_text}

Evaluate whether this trade is prudent from a risk management perspective."""

        try:
            data = await self._call_llm(RISK_AGENT_SYSTEM, user_prompt)
            return self._make_opinion(data)
        except Exception as exc:
            self.logger.warning("[RiskAgent] Failed for %s: %s", ticker, exc)
            return self._fallback_opinion(str(exc))
