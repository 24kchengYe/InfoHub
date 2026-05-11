"""Sentiment Agent — LLM-based news sentiment analysis."""

from typing import List

from .base import BaseAgent, AgentOpinion
from .prompts import SENTIMENT_AGENT_SYSTEM
from src.ai.client import AIClient


class SentimentAgent(BaseAgent):
    """Analyzes news headlines and summaries to determine market sentiment for a ticker."""

    def __init__(self, ai_client: AIClient):
        super().__init__(ai_client, "sentiment")

    async def analyze(
        self,
        ticker: str,
        news_items: List[dict],
    ) -> AgentOpinion:
        """Analyze news sentiment for a specific ticker.

        Args:
            ticker: Stock ticker symbol (e.g. "NVDA")
            news_items: List of dicts with keys: title, summary, published_at, sentiment_keyword
        """
        if not news_items:
            return self._fallback_opinion("No news items available")

        # Format news into user prompt
        news_text = []
        for i, item in enumerate(news_items[:15], 1):
            title = item.get("title", "")
            summary = item.get("summary", "")[:200]
            pub = item.get("published_at", "")
            pre_sentiment = item.get("sentiment_keyword", "")
            line = f"{i}. [{pub}] {title}"
            if summary:
                line += f"\n   {summary}"
            if pre_sentiment:
                line += f"\n   Pre-labeled: {pre_sentiment}"
            news_text.append(line)

        user_prompt = f"""Ticker: ${ticker}
Number of news items: {len(news_items)}

News:
{chr(10).join(news_text)}

Analyze the overall sentiment for ${ticker} based on these news items."""

        try:
            data = await self._call_llm(SENTIMENT_AGENT_SYSTEM, user_prompt)
            return self._make_opinion(data)
        except Exception as exc:
            self.logger.warning("[SentimentAgent] Failed for %s: %s", ticker, exc)
            return self._fallback_opinion(str(exc))
