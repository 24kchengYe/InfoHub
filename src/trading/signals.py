"""Trade signal generation from sentiment analysis results."""

import logging
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from .sentiment import SentimentResult, Sentiment

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    ticker: str
    direction: str  # "long" | "short" | "hold"
    strength: float  # 0.0 - 1.0
    sentiment_count: int
    avg_confidence: float
    generated_at: str
    reasons: List[str]


class TradeSignalGenerator:
    """Generate trade signals by aggregating sentiment across multiple news items.

    This is a scaffold — real trading logic requires:
    - Broker API integration (e.g. Alpaca, Interactive Brokers)
    - Risk management and position sizing
    - Backtesting framework
    - Regulatory compliance checks
    """

    def __init__(self, min_mentions: int = 2, min_confidence: float = 0.6):
        self.min_mentions = min_mentions
        self.min_confidence = min_confidence

    def generate(self, sentiments: List[SentimentResult]) -> List[TradeSignal]:
        """Aggregate sentiment results into trade signals per ticker."""
        # Group by ticker
        ticker_sentiments: dict[str, List[SentimentResult]] = {}
        for s in sentiments:
            for ticker in s.tickers:
                ticker_sentiments.setdefault(ticker, []).append(s)

        signals = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for ticker, sents in ticker_sentiments.items():
            if len(sents) < self.min_mentions:
                continue

            bull = sum(1 for s in sents if s.sentiment == Sentiment.BULLISH)
            bear = sum(1 for s in sents if s.sentiment == Sentiment.BEARISH)
            avg_conf = sum(s.confidence for s in sents) / len(sents)

            if avg_conf < self.min_confidence:
                continue

            if bull > bear:
                direction = "long"
                strength = min(bull / len(sents) * avg_conf, 1.0)
            elif bear > bull:
                direction = "short"
                strength = min(bear / len(sents) * avg_conf, 1.0)
            else:
                direction = "hold"
                strength = 0.3

            # Boost for high-impact sentiments
            impact_boost = sum(1 for s in sents if getattr(s, 'impact', 'medium') == 'high') / len(sents)
            strength = min(strength * (1 + impact_boost * 0.3), 1.0)

            signals.append(TradeSignal(
                ticker=ticker,
                direction=direction,
                strength=round(strength, 2),
                sentiment_count=len(sents),
                avg_confidence=round(avg_conf, 2),
                generated_at=now,
                reasons=[s.reasoning for s in sents if s.reasoning][:3],
            ))

        signals.sort(key=lambda s: s.strength, reverse=True)
        return signals
