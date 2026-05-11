"""AgentOrchestrator — runs all 4 trading agents for a ticker evaluation."""

import asyncio
import logging
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

from .base import AgentOpinion
from .sentiment_agent import SentimentAgent
from .technical_agent import TechnicalAgent
from .risk_agent import RiskAgent
from .decision_agent import DecisionAgent, FinalDecision
from src.ai.client import AIClient
from src.trading.risk import Account, Position
from src.trading.market_data import MarketDataProvider

logger = logging.getLogger("infohub.agent.orchestrator")


@dataclass
class MultiAgentResult:
    """Complete result from multi-agent evaluation of one ticker."""
    ticker: str
    final_decision: FinalDecision
    sentiment_opinion: AgentOpinion
    technical_opinion: AgentOpinion
    risk_opinion: AgentOpinion
    llm_calls: int
    elapsed_ms: int

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "decision": self.final_decision.to_dict(),
            "agents": {
                "sentiment": self.sentiment_opinion.to_dict(),
                "technical": self.technical_opinion.to_dict(),
                "risk": self.risk_opinion.to_dict(),
            },
            "llm_calls": self.llm_calls,
            "elapsed_ms": self.elapsed_ms,
        }


class AgentOrchestrator:
    """Orchestrates the multi-agent trading pipeline.

    For each ticker:
    1. Run SentimentAgent, TechnicalAgent, RiskAgent in parallel (asyncio.gather)
    2. Feed all three opinions to DecisionAgent
    3. Return MultiAgentResult
    """

    def __init__(self, ai_client: AIClient):
        self.sentiment_agent = SentimentAgent(ai_client)
        self.technical_agent = TechnicalAgent(ai_client)
        self.risk_agent = RiskAgent(ai_client)
        self.decision_agent = DecisionAgent(ai_client)
        self.market_data = MarketDataProvider()

    async def evaluate_ticker(
        self,
        ticker: str,
        news_items: List[dict],
        account: Account,
        positions: List[Position],
    ) -> MultiAgentResult:
        """Run full multi-agent evaluation for one ticker.

        Args:
            ticker: Stock ticker (e.g. "NVDA")
            news_items: List of news dicts with title/summary/published_at
            account: Current account state
            positions: Current open positions
        """
        start = time.monotonic()
        llm_calls = 0

        # Quick heuristic for proposed direction (for Risk Agent context)
        bull = sum(1 for n in news_items if n.get("sentiment_keyword") == "bullish")
        bear = sum(1 for n in news_items if n.get("sentiment_keyword") == "bearish")
        proposed_direction = "long" if bull > bear else ("short" if bear > bull else "long")

        # Get current price for Technical Agent
        current_price = None
        try:
            quote = await self.market_data.get_realtime_quote(ticker)
            if quote:
                current_price = quote.price
        except Exception:
            pass

        # Phase 1: Run 3 analysis agents in parallel
        sentiment_op, technical_op, risk_op = await asyncio.gather(
            self.sentiment_agent.analyze(ticker=ticker, news_items=news_items),
            self.technical_agent.analyze(ticker=ticker, current_price=current_price),
            self.risk_agent.analyze(
                ticker=ticker,
                proposed_direction=proposed_direction,
                account=account,
                positions=positions,
            ),
        )
        llm_calls += 3  # Each agent made 1 LLM call (or 0 if fallback)

        # Phase 2: Decision Agent synthesizes
        decision = await self.decision_agent.decide(
            ticker=ticker,
            sentiment_opinion=sentiment_op,
            technical_opinion=technical_op,
            risk_opinion=risk_op,
            current_price=current_price,
            account_equity=account.equity,
        )
        llm_calls += 1

        elapsed_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "[Orchestrator] %s: %s (conf=%.2f) in %dms [%s|%s|%s]",
            ticker, decision.action, decision.confidence, elapsed_ms,
            f"S:{sentiment_op.direction}", f"T:{technical_op.direction}", f"R:{risk_op.direction}",
        )

        return MultiAgentResult(
            ticker=ticker,
            final_decision=decision,
            sentiment_opinion=sentiment_op,
            technical_opinion=technical_op,
            risk_opinion=risk_op,
            llm_calls=llm_calls,
            elapsed_ms=elapsed_ms,
        )

    async def evaluate_multiple(
        self,
        ticker_data: dict,
        account: Account,
        positions: List[Position],
    ) -> List[MultiAgentResult]:
        """Evaluate multiple tickers sequentially (to respect LLM rate limits).

        Args:
            ticker_data: {ticker: [news_items]} dict
            account: Account state
            positions: Current positions
        """
        results = []
        for ticker, news_items in ticker_data.items():
            try:
                result = await self.evaluate_ticker(ticker, news_items, account, positions)
                results.append(result)
            except Exception as exc:
                logger.error("[Orchestrator] Failed to evaluate %s: %s", ticker, exc)

        # Sort by decision confidence descending
        results.sort(key=lambda r: r.final_decision.confidence, reverse=True)
        return results
