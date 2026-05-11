"""Composite trading strategy — fuses sentiment + technical + news volume."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .sentiment import SentimentAnalyzer, SentimentResult, Sentiment
from .indicators import TechnicalIndicators, TechnicalSignal
from .market_data import MarketDataProvider, OHLCV

logger = logging.getLogger(__name__)


@dataclass
class CompositeSignal:
    """Unified trade recommendation combining multiple analysis dimensions."""
    ticker: str
    direction: str           # "long" | "short" | "hold"
    confidence: float        # 0.0 - 1.0

    # Three-dimensional scores
    sentiment_score: float   # -1.0 (very bearish) to +1.0 (very bullish)
    technical_score: float   # -1.0 to +1.0
    news_volume: int         # number of related news items

    # Suggested trade parameters
    current_price: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: str = "normal"  # "light" | "normal" | "heavy"

    # Analysis details
    sentiment_detail: str = ""
    technical_detail: str = ""
    reasoning: str = ""
    generated_at: str = ""

    # Raw data for frontend
    technical_indicators: dict = field(default_factory=dict)
    sentiment_breakdown: dict = field(default_factory=dict)


class CompositeStrategy:
    """Composite strategy engine fusing sentiment, technical, and volume signals.

    Weights (configurable):
    - Sentiment: 40% — LLM-analyzed news sentiment
    - Technical: 40% — indicator-based signals from price data
    - Volume:   20% — news mention frequency (momentum proxy)
    """

    def __init__(
        self,
        sentiment_weight: float = 0.4,
        technical_weight: float = 0.4,
        volume_weight: float = 0.2,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.15,
    ):
        self.weights = {
            "sentiment": sentiment_weight,
            "technical": technical_weight,
            "volume": volume_weight,
        }
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.market_data = MarketDataProvider()

    async def evaluate(
        self,
        ticker: str,
        sentiment_results: List[SentimentResult],
    ) -> CompositeSignal:
        """Evaluate a single ticker using all three dimensions.

        Args:
            ticker: Stock ticker symbol
            sentiment_results: Pre-computed sentiment results for this ticker
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Sentiment dimension
        sentiment_score, sentiment_detail, sentiment_breakdown = self._compute_sentiment(
            sentiment_results
        )

        # 2. Technical dimension
        technical_score, technical_detail, technical_indicators = await self._compute_technical(
            ticker
        )

        # 3. Volume dimension (news mention count)
        news_volume = len(sentiment_results)
        # Normalize volume: 1-2 mentions = low, 3-5 = medium, 6+ = high
        if news_volume >= 6:
            volume_score = 1.0
            position_size = "heavy"
        elif news_volume >= 3:
            volume_score = 0.5
            position_size = "normal"
        else:
            volume_score = 0.2
            position_size = "light"

        # 4. Weighted composite score
        composite = (
            sentiment_score * self.weights["sentiment"]
            + technical_score * self.weights["technical"]
            + (volume_score if sentiment_score > 0 else -volume_score) * self.weights["volume"]
        )

        # 5. Determine direction and confidence
        if composite > 0.15:
            direction = "long"
            confidence = min(abs(composite), 1.0)
        elif composite < -0.15:
            direction = "short"
            confidence = min(abs(composite), 1.0)
        else:
            direction = "hold"
            confidence = 0.3

        # 6. Get current price and calculate entry/SL/TP
        current_price = None
        entry_price = None
        stop_loss = None
        take_profit = None

        quote = await self.market_data.get_realtime_quote(ticker)
        if quote:
            current_price = quote.price
            entry_price = current_price
            if direction == "long":
                stop_loss = round(current_price * (1 - self.stop_loss_pct), 2)
                take_profit = round(current_price * (1 + self.take_profit_pct), 2)
            elif direction == "short":
                stop_loss = round(current_price * (1 + self.stop_loss_pct), 2)
                take_profit = round(current_price * (1 - self.take_profit_pct), 2)

        # 7. Generate reasoning
        parts = []
        if sentiment_detail:
            parts.append(f"情绪面: {sentiment_detail}")
        if technical_detail:
            parts.append(f"技术面: {technical_detail}")
        parts.append(f"新闻热度: {news_volume}条提及")
        reasoning = " | ".join(parts)

        return CompositeSignal(
            ticker=ticker,
            direction=direction,
            confidence=round(confidence, 2),
            sentiment_score=round(sentiment_score, 2),
            technical_score=round(technical_score, 2),
            news_volume=news_volume,
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            sentiment_detail=sentiment_detail,
            technical_detail=technical_detail,
            reasoning=reasoning,
            generated_at=now,
            technical_indicators=technical_indicators,
            sentiment_breakdown=sentiment_breakdown,
        )

    async def evaluate_multiple(
        self,
        ticker_sentiments: dict[str, List[SentimentResult]],
    ) -> List[CompositeSignal]:
        """Evaluate multiple tickers, returning sorted by confidence."""
        signals = []
        for ticker, sents in ticker_sentiments.items():
            try:
                signal = await self.evaluate(ticker, sents)
                if signal.direction != "hold" or signal.news_volume >= 3:
                    signals.append(signal)
            except Exception as exc:
                logger.warning("Failed to evaluate %s: %s", ticker, exc)

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    @staticmethod
    def _compute_sentiment(
        results: List[SentimentResult],
    ) -> tuple[float, str, dict]:
        """Compute aggregate sentiment score from multiple results."""
        if not results:
            return 0.0, "无数据", {}

        bull = sum(1 for r in results if r.sentiment == Sentiment.BULLISH)
        bear = sum(1 for r in results if r.sentiment == Sentiment.BEARISH)
        neutral = sum(1 for r in results if r.sentiment == Sentiment.NEUTRAL)
        total = len(results)

        # Weighted score: bullish = +confidence, bearish = -confidence
        score = 0.0
        for r in results:
            if r.sentiment == Sentiment.BULLISH:
                score += r.confidence
            elif r.sentiment == Sentiment.BEARISH:
                score -= r.confidence
        score = score / total  # Normalize

        # Detail string
        if score > 0.2:
            detail = f"看涨({bull}涨/{bear}跌/{neutral}中)"
        elif score < -0.2:
            detail = f"看跌({bull}涨/{bear}跌/{neutral}中)"
        else:
            detail = f"中性({bull}涨/{bear}跌/{neutral}中)"

        breakdown = {
            "bullish": bull,
            "bearish": bear,
            "neutral": neutral,
            "total": total,
            "avg_confidence": round(sum(r.confidence for r in results) / total, 2),
        }

        return round(score, 2), detail, breakdown

    async def _compute_technical(
        self, ticker: str,
    ) -> tuple[float, str, dict]:
        """Compute technical analysis from K-line data."""
        try:
            kline = await self.market_data.get_kline(ticker, "daily", 60)
            if len(kline) < 30:
                return 0.0, "数据不足", {}

            closes = [k.close for k in kline]
            highs = [k.high for k in kline]
            lows = [k.low for k in kline]

            signal = TechnicalIndicators.generate_signal(closes, highs, lows)

            # Convert direction to score
            if signal.direction == "bullish":
                score = signal.strength
            elif signal.direction == "bearish":
                score = -signal.strength
            else:
                score = 0.0

            return round(score, 2), signal.summary, signal.indicators

        except Exception as exc:
            logger.warning("Technical analysis failed for %s: %s", ticker, exc)
            return 0.0, "技术分析不可用", {}
