"""Technical analysis indicators — pure Python, no external dependencies."""

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class TechnicalSignal:
    """Aggregated technical analysis result."""
    direction: str  # "bullish" | "bearish" | "neutral"
    strength: float  # 0.0 - 1.0
    indicators: dict  # individual indicator values
    summary: str  # human-readable summary


class TechnicalIndicators:
    """Calculate common technical indicators from price data."""

    @staticmethod
    def sma(prices: List[float], period: int) -> List[Optional[float]]:
        """Simple Moving Average."""
        result: List[Optional[float]] = []
        for i in range(len(prices)):
            if i < period - 1:
                result.append(None)
            else:
                window = prices[i - period + 1:i + 1]
                result.append(sum(window) / period)
        return result

    @staticmethod
    def ema(prices: List[float], period: int) -> List[Optional[float]]:
        """Exponential Moving Average."""
        if len(prices) < period:
            return [None] * len(prices)

        multiplier = 2 / (period + 1)
        result: List[Optional[float]] = [None] * (period - 1)
        # First EMA = SMA of first `period` prices
        ema_val = sum(prices[:period]) / period
        result.append(ema_val)

        for i in range(period, len(prices)):
            ema_val = (prices[i] - ema_val) * multiplier + ema_val
            result.append(ema_val)
        return result

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """Relative Strength Index (0-100)."""
        if len(prices) < period + 1:
            return [None] * len(prices)

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        result: List[Optional[float]] = [None] * period

        # Initial average gain/loss
        gains = [max(d, 0) for d in deltas[:period]]
        losses = [abs(min(d, 0)) for d in deltas[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100 - 100 / (1 + rs), 2))

        # Subsequent values using smoothed averages
        for i in range(period, len(deltas)):
            gain = max(deltas[i], 0)
            loss = abs(min(deltas[i], 0))
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(round(100 - 100 / (1 + rs), 2))

        return result

    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """MACD (Moving Average Convergence Divergence).

        Returns:
            (macd_line, signal_line, histogram)
        """
        ti = TechnicalIndicators
        ema_fast = ti.ema(prices, fast)
        ema_slow = ti.ema(prices, slow)

        # MACD line = EMA(fast) - EMA(slow)
        macd_line: List[Optional[float]] = []
        for f, s in zip(ema_fast, ema_slow):
            if f is not None and s is not None:
                macd_line.append(round(f - s, 4))
            else:
                macd_line.append(None)

        # Signal line = EMA of MACD line
        macd_values = [v for v in macd_line if v is not None]
        if len(macd_values) < signal:
            signal_line = [None] * len(macd_line)
        else:
            signal_ema = ti.ema(macd_values, signal)
            # Pad with None to align
            pad = len(macd_line) - len(macd_values)
            signal_line = [None] * pad + signal_ema

        # Histogram = MACD - Signal
        histogram: List[Optional[float]] = []
        for m, s in zip(macd_line, signal_line):
            if m is not None and s is not None:
                histogram.append(round(m - s, 4))
            else:
                histogram.append(None)

        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """Bollinger Bands.

        Returns:
            (upper_band, middle_band, lower_band)
        """
        ti = TechnicalIndicators
        middle = ti.sma(prices, period)

        upper: List[Optional[float]] = []
        lower: List[Optional[float]] = []

        for i in range(len(prices)):
            if middle[i] is None:
                upper.append(None)
                lower.append(None)
            else:
                window = prices[max(0, i - period + 1):i + 1]
                mean = middle[i]
                variance = sum((x - mean) ** 2 for x in window) / len(window)
                std = math.sqrt(variance)
                upper.append(round(mean + std_dev * std, 4))
                lower.append(round(mean - std_dev * std, 4))

        return upper, middle, lower

    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
        """Average True Range — measures volatility."""
        if len(highs) < 2:
            return [None] * len(highs)

        true_ranges = [highs[0] - lows[0]]
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        result: List[Optional[float]] = [None] * (period - 1)
        atr_val = sum(true_ranges[:period]) / period
        result.append(round(atr_val, 4))

        for i in range(period, len(true_ranges)):
            atr_val = (atr_val * (period - 1) + true_ranges[i]) / period
            result.append(round(atr_val, 4))

        return result

    @classmethod
    def generate_signal(cls, closes: List[float], highs: List[float] = None, lows: List[float] = None) -> TechnicalSignal:
        """Generate a composite technical signal from price data.

        Args:
            closes: List of closing prices (most recent last)
            highs: Optional list of high prices
            lows: Optional list of low prices
        """
        if len(closes) < 30:
            return TechnicalSignal(
                direction="neutral",
                strength=0.3,
                indicators={},
                summary="Insufficient data for technical analysis",
            )

        highs = highs or closes
        lows = lows or closes

        signals = []  # List of (direction, weight) tuples
        indicators = {}

        current_price = closes[-1]

        # 1. SMA crossover (5 vs 20)
        sma5 = cls.sma(closes, 5)
        sma20 = cls.sma(closes, 20)
        if sma5[-1] is not None and sma20[-1] is not None:
            indicators["sma5"] = round(sma5[-1], 2)
            indicators["sma20"] = round(sma20[-1], 2)
            if sma5[-1] > sma20[-1]:
                signals.append(("bullish", 0.2))
            elif sma5[-1] < sma20[-1]:
                signals.append(("bearish", 0.2))
            else:
                signals.append(("neutral", 0.1))

        # 2. RSI
        rsi_vals = cls.rsi(closes, 14)
        rsi_val = rsi_vals[-1]
        if rsi_val is not None:
            indicators["rsi"] = rsi_val
            if rsi_val > 70:
                signals.append(("bearish", 0.25))  # Overbought
            elif rsi_val < 30:
                signals.append(("bullish", 0.25))  # Oversold
            elif rsi_val > 50:
                signals.append(("bullish", 0.1))
            else:
                signals.append(("bearish", 0.1))

        # 3. MACD
        macd_line, signal_line, histogram = cls.macd(closes)
        if histogram[-1] is not None:
            indicators["macd"] = histogram[-1]
            if histogram[-1] > 0:
                signals.append(("bullish", 0.2))
            elif histogram[-1] < 0:
                signals.append(("bearish", 0.2))
            else:
                signals.append(("neutral", 0.1))

        # 4. Bollinger Bands
        upper, middle, lower = cls.bollinger_bands(closes, 20)
        if upper[-1] is not None and lower[-1] is not None:
            indicators["boll_upper"] = round(upper[-1], 2)
            indicators["boll_lower"] = round(lower[-1], 2)
            bb_width = upper[-1] - lower[-1]
            if bb_width > 0:
                bb_pos = (current_price - lower[-1]) / bb_width
                indicators["boll_position"] = round(bb_pos, 2)
                if bb_pos > 0.8:
                    signals.append(("bearish", 0.15))  # Near upper band
                elif bb_pos < 0.2:
                    signals.append(("bullish", 0.15))  # Near lower band
                else:
                    signals.append(("neutral", 0.05))

        # 5. Price vs SMA20 (trend)
        if sma20[-1] is not None:
            pct_from_sma = (current_price - sma20[-1]) / sma20[-1] * 100
            indicators["pct_from_sma20"] = round(pct_from_sma, 2)
            if pct_from_sma > 5:
                signals.append(("bullish", 0.2))
            elif pct_from_sma < -5:
                signals.append(("bearish", 0.2))

        # Aggregate signals
        bull_score = sum(w for d, w in signals if d == "bullish")
        bear_score = sum(w for d, w in signals if d == "bearish")
        total_weight = bull_score + bear_score + sum(w for d, w in signals if d == "neutral")

        if total_weight == 0:
            return TechnicalSignal("neutral", 0.3, indicators, "No technical signals available")

        if bull_score > bear_score:
            direction = "bullish"
            strength = min(bull_score / total_weight, 1.0)
        elif bear_score > bull_score:
            direction = "bearish"
            strength = min(bear_score / total_weight, 1.0)
        else:
            direction = "neutral"
            strength = 0.5

        # Generate summary
        parts = []
        if "rsi" in indicators:
            if indicators["rsi"] > 70:
                parts.append(f"RSI超买({indicators['rsi']:.0f})")
            elif indicators["rsi"] < 30:
                parts.append(f"RSI超卖({indicators['rsi']:.0f})")
        if "macd" in indicators:
            parts.append(f"MACD{'金叉' if indicators['macd'] > 0 else '死叉'}")
        if sma5[-1] and sma20[-1]:
            parts.append(f"MA5{'>' if sma5[-1] > sma20[-1] else '<'}MA20")

        summary = " · ".join(parts) if parts else "技术面中性"

        return TechnicalSignal(
            direction=direction,
            strength=round(strength, 2),
            indicators=indicators,
            summary=summary,
        )
