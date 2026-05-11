"""Base class for all trading agents."""

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

from src.ai.client import AIClient


@dataclass
class AgentOpinion:
    """Structured output from any trading agent."""
    agent_name: str
    direction: str          # "bullish" | "bearish" | "neutral"
    confidence: float       # 0.0 - 1.0
    reasoning: str          # One paragraph explanation
    key_factors: List[str]  # Key data points driving the opinion
    risk_flags: List[str]   # Warnings / concerns
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class BaseAgent(ABC):
    """Abstract base for all trading agents.

    Each agent:
    1. Receives structured data (news, indicators, portfolio state)
    2. Calls the LLM with a specialized system prompt
    3. Parses the JSON response into an AgentOpinion
    """

    def __init__(self, ai_client: AIClient, name: str):
        self.ai_client = ai_client
        self.name = name
        self.logger = logging.getLogger(f"infohub.agent.{name}")

    @abstractmethod
    async def analyze(self, **kwargs) -> AgentOpinion:
        """Run analysis and return structured opinion."""
        ...

    async def _call_llm(self, system: str, user: str) -> dict:
        """Call LLM and parse JSON response with fallback strategies."""
        try:
            response = await self.ai_client.complete(
                system=system,
                user=user,
                temperature=0.1,
                max_tokens=1024,
            )
            return self._parse_json(response)
        except Exception as exc:
            self.logger.warning("[%s] LLM call failed: %s", self.name, exc)
            raise

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if m:
            return json.loads(m.group(1))
        # Try finding first { ... } block
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Cannot parse JSON from response: {text[:200]}")

    def _make_opinion(self, data: dict) -> AgentOpinion:
        """Convert parsed JSON dict to AgentOpinion."""
        return AgentOpinion(
            agent_name=self.name,
            direction=data.get("direction", "neutral"),
            confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
            reasoning=data.get("reasoning", ""),
            key_factors=data.get("key_factors", []),
            risk_flags=data.get("risk_flags", []),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _fallback_opinion(self, reason: str) -> AgentOpinion:
        """Return a neutral opinion when analysis fails."""
        return AgentOpinion(
            agent_name=self.name,
            direction="neutral",
            confidence=0.0,
            reasoning=f"Analysis unavailable: {reason}",
            key_factors=[],
            risk_flags=[reason],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
