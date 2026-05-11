"""Technical Agent — LLM-interpreted technical indicator analysis."""

from typing import Optional

from .base import BaseAgent, AgentOpinion
from .prompts import TECHNICAL_AGENT_SYSTEM
from src.ai.client import AIClient
from src.trading.indicators import TechnicalIndicators, TechnicalSignal
from src.trading.market_data import MarketDataProvider


class TechnicalAgent(BaseAgent):
    """Interprets technical indicators using LLM for nuanced analysis."""

    def __init__(self, ai_client: AIClient):
        super().__init__(ai_client, "technical")
        self.market_data = MarketDataProvider()

    async def analyze(
        self,
        ticker: str,
        technical_signal: Optional[TechnicalSignal] = None,
        current_price: Optional[float] = None,
    ) -> AgentOpinion:
        """Analyze technical indicators for a ticker.

        If technical_signal is not provided, fetches K-line and computes it.
        """
        # Compute technical signal if not provided
        if technical_signal is None:
            try:
                kline = await self.market_data.get_kline(ticker, "daily", 60)
                if len(kline) < 30:
                    return self._fallback_opinion(f"Insufficient K-line data ({len(kline)} bars)")
                closes = [k.close for k in kline]
                highs = [k.high for k in kline]
                lows = [k.low for k in kline]
                technical_signal = TechnicalIndicators.generate_signal(closes, highs, lows)
            except Exception as exc:
                return self._fallback_opinion(f"K-line fetch failed: {exc}")

        if current_price is None:
            try:
                quote = await self.market_data.get_realtime_quote(ticker)
                current_price = quote.price if quote else 0
            except Exception:
                current_price = 0

        # Format indicators into user prompt
        ind = technical_signal.indicators
        price_str = f"${current_price:.2f}" if current_price else "N/A"
        sma20 = ind.get('sma20')
        if sma20 and current_price:
            vs_sma20 = f"{((current_price / sma20 - 1) * 100):.1f}% {'above' if current_price > sma20 else 'below'}"
        else:
            vs_sma20 = "N/A"

        user_prompt = f"""Ticker: ${ticker}
Current Price: {price_str}

Technical Indicators:
- Direction (rule-based): {technical_signal.direction} (strength: {technical_signal.strength:.2f})
- Summary: {technical_signal.summary}
- RSI(14): {ind.get('rsi', 'N/A')}
- MACD Histogram: {ind.get('macd_histogram', 'N/A')}
- MACD Signal Cross: {ind.get('macd_cross', 'N/A')}
- SMA5: {ind.get('sma5', 'N/A')}
- SMA20: {ind.get('sma20', 'N/A')}
- SMA Crossover: {'SMA5 > SMA20 (bullish)' if ind.get('sma5', 0) > ind.get('sma20', 0) else 'SMA5 < SMA20 (bearish)'}
- Bollinger Position: {ind.get('bb_position', 'N/A')}
- ATR(14): {ind.get('atr', 'N/A')}
- Price vs SMA20: {vs_sma20}

Interpret these indicators and provide your technical analysis opinion."""

        try:
            data = await self._call_llm(TECHNICAL_AGENT_SYSTEM, user_prompt)
            return self._make_opinion(data)
        except Exception as exc:
            self.logger.warning("[TechnicalAgent] Failed for %s: %s", ticker, exc)
            return self._fallback_opinion(str(exc))
