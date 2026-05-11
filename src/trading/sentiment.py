"""Sentiment analysis for financial news items."""

import json
import logging
import re
from typing import List, Optional
from dataclasses import dataclass, field
from enum import Enum

from ..models import ContentItem

logger = logging.getLogger(__name__)


class Sentiment(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class SentimentResult:
    item_id: str
    sentiment: Sentiment
    confidence: float  # 0.0 - 1.0
    reasoning: str = ""
    tickers: List[str] = field(default_factory=list)
    impact: str = "medium"  # high/medium/low
    time_horizon: str = "short"  # short/medium/long


class SentimentAnalyzer:
    """Analyze financial news for market sentiment.

    Uses LLM when ai_client is provided, falls back to keyword heuristic.
    """

    _LLM_SYSTEM = """You are a financial sentiment analyst. Analyze the given news and return ONLY a JSON object:
{
    "sentiment": "bullish" | "bearish" | "neutral",
    "confidence": 0.0-1.0,
    "tickers": ["AAPL"],
    "impact": "high" | "medium" | "low",
    "time_horizon": "short" | "medium" | "long",
    "reasoning": "one sentence explanation in the same language as the input"
}
Rules:
- Extract ALL stock ticker symbols mentioned (both $AAPL format and plain AAPL/TSLA)
- For Chinese stocks use codes like 600519, 000001
- confidence should reflect how clear the sentiment signal is
- impact: high = affects entire market/sector, medium = affects specific company, low = minor news
- time_horizon: short = days, medium = weeks, long = months+
- Return ONLY valid JSON, no markdown, no explanation outside JSON"""

    def __init__(self, ai_client=None):
        self.ai_client = ai_client

    async def analyze_async(self, item: ContentItem) -> Optional[SentimentResult]:
        """Analyze using LLM (async). Falls back to keyword heuristic on failure."""
        if item.domain != "finance":
            return None

        if self.ai_client:
            try:
                return await self._llm_analyze(item)
            except Exception as exc:
                logger.warning("LLM sentiment failed for %s, falling back to keywords: %s", item.id, exc)

        return self._keyword_analyze(item)

    def analyze(self, item: ContentItem) -> Optional[SentimentResult]:
        """Synchronous keyword-based analysis (backward compatible)."""
        if item.domain != "finance":
            return None
        return self._keyword_analyze(item)

    async def _llm_analyze(self, item: ContentItem) -> SentimentResult:
        """Use LLM for sentiment analysis."""
        title = item.metadata.get("title_zh") or item.title
        summary = item.metadata.get("detailed_summary_zh") or item.ai_summary or item.content or ""
        if len(summary) > 500:
            summary = summary[:500] + "..."

        user_prompt = f"Title: {title}\nSummary: {summary}"

        response = await self.ai_client.complete(
            system=self._LLM_SYSTEM,
            user=user_prompt,
            temperature=0.1,
            max_tokens=300,
        )

        # Parse JSON response
        text = response.strip()
        # Try to extract JSON from possible markdown code blocks
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group()

        data = json.loads(text)

        sentiment = Sentiment(data.get("sentiment", "neutral"))
        tickers = data.get("tickers", [])
        # Also extract tickers from the original text as fallback
        extra_tickers = re.findall(r'\$([A-Z]{1,5})\b', item.title + " " + (item.content or ""))
        all_tickers = list(set(tickers + extra_tickers))

        return SentimentResult(
            item_id=item.id,
            sentiment=sentiment,
            confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
            reasoning=data.get("reasoning", ""),
            tickers=all_tickers,
            impact=data.get("impact", "medium"),
            time_horizon=data.get("time_horizon", "short"),
        )

    def _keyword_analyze(self, item: ContentItem) -> SentimentResult:
        """Keyword-based heuristic (fallback)."""
        bullish_kw = {
            "growth", "surge", "rally", "gain", "profit", "bullish", "upgrade",
            "soar", "jump", "rise", "boom", "record high", "outperform", "beat",
            "exceeded", "strong", "buy", "positive", "recovery", "breakout",
            "all-time high", "上涨", "暴涨", "利好", "买入", "突破", "新高",
        }
        bearish_kw = {
            "crash", "drop", "loss", "decline", "bearish", "downgrade", "recession",
            "plunge", "fall", "sink", "tumble", "selloff", "sell-off", "miss",
            "weak", "sell", "negative", "warning", "crisis", "default", "layoff",
            "下跌", "暴跌", "利空", "卖出", "跳水", "崩盘", "裁员",
        }

        title_lower = item.title.lower()
        summary_lower = (item.ai_summary or "").lower()
        text = f"{title_lower} {summary_lower}"

        bull_hits = sum(1 for kw in bullish_kw if kw in text)
        bear_hits = sum(1 for kw in bearish_kw if kw in text)

        if bull_hits > bear_hits:
            sentiment = Sentiment.BULLISH
            confidence = min(0.5 + bull_hits * 0.1, 0.95)
        elif bear_hits > bull_hits:
            sentiment = Sentiment.BEARISH
            confidence = min(0.5 + bear_hits * 0.1, 0.95)
        else:
            sentiment = Sentiment.NEUTRAL
            confidence = 0.4

        # Extract tickers
        text_for_tickers = item.title + " " + (item.content or "")
        tickers = re.findall(r'\$([A-Z]{1,5})\b', text_for_tickers)
        standalone = re.findall(r'(?:^|\s)([A-Z]{2,5})(?:\s|$|,|\.)', text_for_tickers)
        common_tickers = {
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "TSLA", "META", "NVDA",
            "AMD", "INTC", "NFLX", "DIS", "BA", "JPM", "GS", "MS", "BAC",
            "WFC", "C", "V", "MA", "PYPL", "SQ", "COIN", "BTC", "ETH",
            "SPY", "QQQ", "IWM", "VTI", "VOO",
        }
        tickers.extend(t for t in standalone if t in common_tickers)

        return SentimentResult(
            item_id=item.id,
            sentiment=sentiment,
            confidence=confidence,
            reasoning=item.ai_reason or "",
            tickers=list(set(tickers)),
        )

    def analyze_batch(self, items: List[ContentItem]) -> List[SentimentResult]:
        """Batch analysis using keyword method (sync)."""
        results = []
        for item in items:
            result = self.analyze(item)
            if result:
                results.append(result)
        return results

    async def analyze_batch_async(self, items: List[ContentItem]) -> List[SentimentResult]:
        """Batch analysis using LLM (async)."""
        results = []
        for item in items:
            result = await self.analyze_async(item)
            if result:
                results.append(result)
        return results
