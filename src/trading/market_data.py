"""Market data provider — unified interface for stock/fund quotes and K-line data."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    change: float
    change_pct: float
    volume: int
    high: float
    low: float
    open: float
    prev_close: float
    market: str  # "us" | "cn" | "hk"
    updated_at: str


@dataclass
class OHLCV:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class FundNAV:
    code: str
    name: str
    nav: float
    acc_nav: float
    change_pct: float
    date: str


@dataclass
class IndexQuote:
    code: str
    name: str
    price: float
    change: float
    change_pct: float


class MarketDataProvider:
    """Unified market data interface supporting US, CN, and HK markets."""

    async def get_realtime_quote(self, ticker: str) -> Optional[Quote]:
        """Get real-time quote for a ticker.

        Ticker format:
        - US: AAPL, TSLA, NVDA
        - CN: 600519 (上证), 000001 (深证)
        - HK: 00700
        """
        market = self._detect_market(ticker)
        try:
            if market == "cn":
                return await self._get_cn_quote(ticker)
            elif market == "hk":
                return await self._get_hk_quote(ticker)
            else:
                return await self._get_us_quote(ticker)
        except Exception as exc:
            logger.warning("Failed to get quote for %s: %s", ticker, exc)
            return None

    async def get_kline(self, ticker: str, period: str = "daily", count: int = 60) -> List[OHLCV]:
        """Get K-line (candlestick) data.

        Args:
            ticker: Stock ticker
            period: "daily", "weekly", "monthly"
            count: Number of bars
        """
        market = self._detect_market(ticker)
        try:
            if market == "cn":
                return await self._get_cn_kline(ticker, period, count)
            else:
                return await self._get_us_kline(ticker, period, count)
        except Exception as exc:
            logger.warning("Failed to get kline for %s: %s", ticker, exc)
            return []

    async def get_fund_nav(self, fund_code: str) -> Optional[FundNAV]:
        """Get fund NAV (Net Asset Value) for Chinese mutual funds."""
        try:
            return await self._get_cn_fund(fund_code)
        except Exception as exc:
            logger.warning("Failed to get fund NAV for %s: %s", fund_code, exc)
            return None

    async def get_market_overview(self) -> List[IndexQuote]:
        """Get major market indices."""
        indices = []
        try:
            indices.extend(await self._get_cn_indices())
        except Exception as exc:
            logger.warning("Failed to get CN indices: %s", exc)
        try:
            indices.extend(await self._get_us_indices())
        except Exception as exc:
            logger.warning("Failed to get US indices: %s", exc)
        return indices

    # ---- Private implementations ----

    @staticmethod
    def _detect_market(ticker: str) -> str:
        """Detect market from ticker format."""
        if ticker.isdigit():
            if ticker.startswith(("6", "9")):
                return "cn"  # Shanghai
            elif ticker.startswith(("0", "3")):
                return "cn"  # Shenzhen
            elif ticker.startswith("0") and len(ticker) == 5:
                return "hk"
            return "cn"
        return "us"

    @staticmethod
    async def _get_cn_quote(ticker: str) -> Optional[Quote]:
        """A-share real-time quote via akshare."""
        import akshare as ak
        import asyncio

        def _fetch():
            # akshare uses sync API, run in executor
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == ticker]
            if row.empty:
                return None
            r = row.iloc[0]
            return Quote(
                ticker=ticker,
                name=str(r.get("名称", "")),
                price=float(r.get("最新价", 0)),
                change=float(r.get("涨跌额", 0)),
                change_pct=float(r.get("涨跌幅", 0)),
                volume=int(r.get("成交量", 0)),
                high=float(r.get("最高", 0)),
                low=float(r.get("最低", 0)),
                open=float(r.get("今开", 0)),
                prev_close=float(r.get("昨收", 0)),
                market="cn",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_us_quote(ticker: str) -> Optional[Quote]:
        """US stock quote via yfinance."""
        import yfinance as yf
        import asyncio

        def _fetch():
            t = yf.Ticker(ticker)
            info = t.fast_info
            hist = t.history(period="2d")
            if hist.empty:
                return None
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            price = float(latest["Close"])
            prev_close = float(prev["Close"])
            return Quote(
                ticker=ticker,
                name=ticker,
                price=price,
                change=round(price - prev_close, 2),
                change_pct=round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
                volume=int(latest.get("Volume", 0)),
                high=float(latest.get("High", 0)),
                low=float(latest.get("Low", 0)),
                open=float(latest.get("Open", 0)),
                prev_close=prev_close,
                market="us",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_hk_quote(ticker: str) -> Optional[Quote]:
        """HK stock quote via yfinance (append .HK)."""
        import yfinance as yf
        import asyncio

        def _fetch():
            t = yf.Ticker(f"{ticker}.HK")
            hist = t.history(period="2d")
            if hist.empty:
                return None
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            price = float(latest["Close"])
            prev_close = float(prev["Close"])
            return Quote(
                ticker=ticker,
                name=ticker,
                price=price,
                change=round(price - prev_close, 2),
                change_pct=round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
                volume=int(latest.get("Volume", 0)),
                high=float(latest.get("High", 0)),
                low=float(latest.get("Low", 0)),
                open=float(latest.get("Open", 0)),
                prev_close=prev_close,
                market="hk",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_cn_kline(ticker: str, period: str, count: int) -> List[OHLCV]:
        """A-share K-line via akshare."""
        import akshare as ak
        import asyncio

        period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        ak_period = period_map.get(period, "daily")

        def _fetch():
            df = ak.stock_zh_a_hist(symbol=ticker, period=ak_period, adjust="qfq")
            if df is None or df.empty:
                return []
            df = df.tail(count)
            result = []
            for _, row in df.iterrows():
                result.append(OHLCV(
                    date=str(row.get("日期", "")),
                    open=float(row.get("开盘", 0)),
                    high=float(row.get("最高", 0)),
                    low=float(row.get("最低", 0)),
                    close=float(row.get("收盘", 0)),
                    volume=int(row.get("成交量", 0)),
                ))
            return result

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_us_kline(ticker: str, period: str, count: int) -> List[OHLCV]:
        """US stock K-line via yfinance."""
        import yfinance as yf
        import asyncio

        period_map = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
        yf_interval = period_map.get(period, "1d")
        # Estimate period string from count
        yf_period = f"{min(count * 2, 730)}d" if period == "daily" else f"{min(count * 14, 1825)}d"

        def _fetch():
            t = yf.Ticker(ticker)
            df = t.history(period=yf_period, interval=yf_interval)
            if df is None or df.empty:
                return []
            df = df.tail(count)
            result = []
            for date, row in df.iterrows():
                result.append(OHLCV(
                    date=str(date.date()),
                    open=round(float(row["Open"]), 2),
                    high=round(float(row["High"]), 2),
                    low=round(float(row["Low"]), 2),
                    close=round(float(row["Close"]), 2),
                    volume=int(row["Volume"]),
                ))
            return result

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_cn_fund(fund_code: str) -> Optional[FundNAV]:
        """Chinese mutual fund NAV via akshare."""
        import akshare as ak
        import asyncio

        def _fetch():
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            nav = float(latest.get("单位净值", 0))
            prev_nav = float(prev.get("单位净值", nav))
            return FundNAV(
                code=fund_code,
                name=fund_code,
                nav=nav,
                acc_nav=float(latest.get("累计净值", nav)),
                change_pct=round((nav - prev_nav) / prev_nav * 100, 2) if prev_nav else 0,
                date=str(latest.get("净值日期", "")),
            )

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_cn_indices() -> List[IndexQuote]:
        """Major Chinese indices."""
        import akshare as ak
        import asyncio
        import os

        def _fetch():
            # akshare needs direct connection (no proxy)
            saved = {k: os.environ.pop(k, None) for k in ["ALL_PROXY", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]}
            indices = []
            try:
                df = ak.stock_zh_index_spot_em()
                targets = {"上证指数": "000001", "深证成指": "399001", "创业板指": "399006"}
                for name, code in targets.items():
                    row = df[df["代码"] == code]
                    if not row.empty:
                        r = row.iloc[0]
                        indices.append(IndexQuote(
                            code=code,
                            name=name,
                            price=float(r.get("最新价", 0)),
                            change=float(r.get("涨跌额", 0)),
                            change_pct=float(r.get("涨跌幅", 0)),
                        ))
            except Exception as exc:
                logger.warning("CN indices error: %s", exc)
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
            return indices

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    @staticmethod
    async def _get_us_indices() -> List[IndexQuote]:
        """Major US indices via yfinance."""
        import yfinance as yf
        import asyncio

        def _fetch():
            indices = []
            tickers = {"^GSPC": "标普500", "^IXIC": "纳斯达克", "^DJI": "道琼斯"}
            for symbol, name in tickers.items():
                try:
                    t = yf.Ticker(symbol)
                    hist = t.history(period="2d")
                    if hist.empty:
                        continue
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else latest
                    price = float(latest["Close"])
                    prev_close = float(prev["Close"])
                    indices.append(IndexQuote(
                        code=symbol,
                        name=name,
                        price=round(price, 2),
                        change=round(price - prev_close, 2),
                        change_pct=round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
                    ))
                except Exception:
                    pass
            return indices

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)
