"""Decision Agent — synthesizes all agent opinions into final trade decision."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .base import BaseAgent, AgentOpinion
from .prompts import DECISION_AGENT_SYSTEM
from src.ai.client import AIClient


@dataclass
class FinalDecision:
    """Output from the Decision Agent."""
    ticker: str
    action: str               # "buy" | "sell" | "hold"
    direction: str            # "long" | "short" | "hold"
    confidence: float         # 0.0 - 1.0
    position_size: str        # "none" | "light" | "normal" | "heavy"
    reasoning: str            # Multi-sentence synthesis
    dissenting_views: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class DecisionAgent(BaseAgent):
    """Chief investment decision agent — synthesizes all opinions."""

    def __init__(self, ai_client: AIClient):
        super().__init__(ai_client, "decision")

    async def analyze(self, **kwargs) -> AgentOpinion:
        """Not used directly — use decide() instead."""
        raise NotImplementedError("Use DecisionAgent.decide() instead")

    async def decide(
        self,
        ticker: str,
        sentiment_opinion: AgentOpinion,
        technical_opinion: AgentOpinion,
        risk_opinion: AgentOpinion,
        current_price: Optional[float] = None,
        account_equity: Optional[float] = None,
    ) -> FinalDecision:
        """Synthesize three agent opinions into a final decision."""
        from datetime import datetime, timezone

        user_prompt = f"""Ticker: ${ticker}
Current Price: ${f'{current_price:.2f}' if current_price else 'N/A'}
Account Equity: ${f'{account_equity:,.2f}' if account_equity else 'N/A'}

=== Sentiment Agent ===
Direction: {sentiment_opinion.direction} (confidence: {sentiment_opinion.confidence:.2f})
Reasoning: {sentiment_opinion.reasoning}
Key Factors: {', '.join(sentiment_opinion.key_factors)}
Risk Flags: {', '.join(sentiment_opinion.risk_flags) or 'None'}

=== Technical Agent ===
Direction: {technical_opinion.direction} (confidence: {technical_opinion.confidence:.2f})
Reasoning: {technical_opinion.reasoning}
Key Factors: {', '.join(technical_opinion.key_factors)}
Risk Flags: {', '.join(technical_opinion.risk_flags) or 'None'}

=== Risk Agent ===
Direction: {risk_opinion.direction} (confidence: {risk_opinion.confidence:.2f})
Reasoning: {risk_opinion.reasoning}
Key Factors: {', '.join(risk_opinion.key_factors)}
Risk Flags: {', '.join(risk_opinion.risk_flags) or 'None'}

Synthesize these three opinions into a final trade decision for ${ticker}."""

        try:
            data = await self._call_llm(DECISION_AGENT_SYSTEM, user_prompt)
            return FinalDecision(
                ticker=ticker,
                action=data.get("action", "hold"),
                direction=data.get("direction", "hold"),
                confidence=min(max(float(data.get("confidence", 0.3)), 0.0), 1.0),
                position_size=data.get("position_size", "none"),
                reasoning=data.get("reasoning", ""),
                dissenting_views=data.get("dissenting_views", []),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            self.logger.warning("[DecisionAgent] Failed for %s: %s", ticker, exc)
            return FinalDecision(
                ticker=ticker,
                action="hold",
                direction="hold",
                confidence=0.0,
                position_size="none",
                reasoning=f"Decision synthesis failed: {exc}",
                dissenting_views=[],
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
