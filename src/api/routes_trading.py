"""Trading signal, sentiment, and market data routes."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("infohub.api.trading")
router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.get("/signals")
async def get_signals(
    request: Request,
    domain: str = Query("finance"),
    limit: int = Query(7, ge=1, le=30),
):
    """Get recent trade signals."""
    db = request.app.state.db
    try:
        data = await db.get_trade_signals(domain=domain, limit=limit)
        return {"data": data}
    except Exception as exc:
        logger.error("get_signals error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sentiment")
async def get_sentiment(
    request: Request,
    domain: str = Query("finance"),
    days: int = Query(7, ge=1, le=30),
):
    """Get sentiment analysis results from scored finance items."""
    db = request.app.state.db
    try:
        # Fetch finance items with sentiment data in metadata
        result = await db.get_items(
            domain=domain,
            sort="published_at",
            page=1,
            per_page=100,
        )
        items = result["items"]

        # Extract sentiment data
        sentiments = []
        ticker_counts: dict[str, dict] = {}
        bull_count = 0
        bear_count = 0
        neutral_count = 0

        for item in items:
            meta = item.metadata or {}
            sentiment = meta.get("sentiment")
            if not sentiment:
                continue

            sentiments.append({
                "id": item.id,
                "title": meta.get("title_zh") or item.title,
                "title_en": meta.get("title_en") or item.title,
                "url": str(item.url),
                "sentiment": sentiment,
                "confidence": meta.get("sentiment_confidence", 0),
                "tickers": meta.get("tickers", []),
                "score": item.ai_score,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            })

            if sentiment == "bullish":
                bull_count += 1
            elif sentiment == "bearish":
                bear_count += 1
            else:
                neutral_count += 1

            for ticker in meta.get("tickers", []):
                if ticker not in ticker_counts:
                    ticker_counts[ticker] = {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0}
                ticker_counts[ticker][sentiment] = ticker_counts[ticker].get(sentiment, 0) + 1
                ticker_counts[ticker]["total"] += 1

        # Sort tickers by total mentions
        top_tickers = sorted(
            [{"ticker": k, **v} for k, v in ticker_counts.items()],
            key=lambda x: x["total"],
            reverse=True,
        )[:20]

        return {
            "data": {
                "summary": {
                    "total": len(sentiments),
                    "bullish": bull_count,
                    "bearish": bear_count,
                    "neutral": neutral_count,
                },
                "top_tickers": top_tickers,
                "items": sentiments[:50],
            }
        }
    except Exception as exc:
        logger.error("get_sentiment error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/overview")
async def trading_overview(
    request: Request,
    domain: str = Query("finance"),
):
    """Combined overview: latest signals + sentiment summary."""
    db = request.app.state.db
    try:
        # Get latest signals
        signals_data = await db.get_trade_signals(domain=domain, limit=1)
        latest_signals = signals_data[0]["signals"] if signals_data else []

        # Get sentiment from recent items
        result = await db.get_items(
            domain=domain,
            sort="published_at",
            page=1,
            per_page=50,
        )
        items = result["items"]

        bull = bear = neutral = 0
        for item in items:
            s = (item.metadata or {}).get("sentiment")
            if s == "bullish": bull += 1
            elif s == "bearish": bear += 1
            elif s == "neutral": neutral += 1

        total_sentiment = bull + bear + neutral
        market_mood = "neutral"
        if total_sentiment > 0:
            if bull / total_sentiment > 0.5:
                market_mood = "bullish"
            elif bear / total_sentiment > 0.5:
                market_mood = "bearish"

        return {
            "data": {
                "market_mood": market_mood,
                "sentiment": {
                    "bullish": bull,
                    "bearish": bear,
                    "neutral": neutral,
                    "total": total_sentiment,
                },
                "signals": latest_signals[:10],
                "total_items": result["total"],
            }
        }
    except Exception as exc:
        logger.error("trading_overview error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Composite signals — fused sentiment + technical + news volume
# ---------------------------------------------------------------------------


@router.get("/composite-signals")
async def composite_signals(
    request: Request,
    domain: str = Query("finance"),
):
    """Generate composite trading signals from recent news + market data."""
    db = request.app.state.db
    try:
        from src.trading.strategy import CompositeStrategy
        from src.trading.sentiment import SentimentResult, Sentiment

        # Get recent finance items with sentiment
        result = await db.get_items(domain=domain, sort="published_at", page=1, per_page=100)
        items = result["items"]

        # Group by ticker
        ticker_sentiments: dict[str, list] = {}
        for item in items:
            meta = item.metadata or {}
            sentiment = meta.get("sentiment")
            if not sentiment:
                continue
            tickers = meta.get("tickers", [])
            for ticker in tickers:
                if ticker not in ticker_sentiments:
                    ticker_sentiments[ticker] = []
                ticker_sentiments[ticker].append(SentimentResult(
                    item_id=item.id,
                    sentiment=Sentiment(sentiment),
                    confidence=meta.get("sentiment_confidence", 0.5),
                    reasoning=meta.get("sentiment_reasoning", ""),
                    tickers=tickers,
                    impact=meta.get("sentiment_impact", "medium"),
                    time_horizon=meta.get("sentiment_time_horizon", "short"),
                ))

        if not ticker_sentiments:
            return {"data": [], "message": "No sentiment data available. Run finance pipeline first."}

        strategy = CompositeStrategy()
        signals = await strategy.evaluate_multiple(ticker_sentiments)

        return {
            "data": [
                {
                    "ticker": s.ticker,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "sentiment_score": s.sentiment_score,
                    "technical_score": s.technical_score,
                    "news_volume": s.news_volume,
                    "current_price": s.current_price,
                    "entry_price": s.entry_price,
                    "stop_loss": s.stop_loss,
                    "take_profit": s.take_profit,
                    "position_size": s.position_size,
                    "sentiment_detail": s.sentiment_detail,
                    "technical_detail": s.technical_detail,
                    "reasoning": s.reasoning,
                    "generated_at": s.generated_at,
                    "technical_indicators": s.technical_indicators,
                    "sentiment_breakdown": s.sentiment_breakdown,
                }
                for s in signals
            ]
        }
    except Exception as exc:
        logger.error("composite_signals error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Broker API — Alpaca paper trading
# ---------------------------------------------------------------------------


@router.get("/account")
async def get_account(request: Request):
    """Get paper trading account info."""
    try:
        from src.trading.broker import PaperBroker
        broker = PaperBroker()
        account = await broker.get_account()
        return {"data": account.__dict__}
    except Exception as exc:
        logger.error("get_account error: %s", exc, exc_info=True)
        return {"data": None, "message": str(exc)}


@router.get("/positions")
async def get_positions(request: Request):
    """Get current paper trading positions."""
    try:
        from src.trading.broker import PaperBroker
        broker = PaperBroker()
        positions = await broker.get_positions()
        return {"data": [p.__dict__ for p in positions]}
    except Exception as exc:
        logger.error("get_positions error: %s", exc, exc_info=True)
        return {"data": [], "message": str(exc)}


@router.get("/orders")
async def get_orders(request: Request, limit: int = Query(50, ge=1, le=200)):
    """Get paper trading order history."""
    try:
        from src.trading.broker import PaperBroker
        broker = PaperBroker()
        orders = await broker.get_order_history(limit=limit)
        return {"data": orders}
    except Exception as exc:
        logger.error("get_orders error: %s", exc, exc_info=True)
        return {"data": [], "message": str(exc)}


class SubmitOrderBody(BaseModel):
    ticker: str
    side: str  # "buy" | "sell"
    quantity: int
    order_type: str = "market"  # "market" | "limit"
    limit_price: Optional[float] = None
    signal_source: str = ""
    signal_confidence: float = 0.0
    ai_reasoning: str = ""


@router.post("/orders")
async def submit_order(request: Request, body: SubmitOrderBody):
    """Submit a paper trading order (requires confirmation by default)."""
    try:
        from src.trading.broker import PaperBroker
        from src.trading.risk import OrderRequest

        order = OrderRequest(
            ticker=body.ticker,
            side=body.side,
            quantity=body.quantity,
            order_type=body.order_type,
            limit_price=body.limit_price,
            signal_source=body.signal_source,
            signal_confidence=body.signal_confidence,
            ai_reasoning=body.ai_reasoning,
            requires_confirmation=True,
        )

        broker = PaperBroker()
        result = await broker.submit_order(order)
        return {"data": result.__dict__}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("submit_order error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/orders/{order_id}/confirm")
async def confirm_order(request: Request, order_id: str, body: SubmitOrderBody):
    """Confirm and execute a pending order."""
    try:
        from src.trading.broker import PaperBroker
        from src.trading.risk import OrderRequest

        order = OrderRequest(
            ticker=body.ticker,
            side=body.side,
            quantity=body.quantity,
            order_type=body.order_type,
            limit_price=body.limit_price,
            requires_confirmation=False,
        )

        broker = PaperBroker()
        result = await broker.confirm_and_execute(int(order_id), order)
        return {"data": result.__dict__}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("confirm_order error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/risk/config")
async def get_risk_config(request: Request):
    """Get current risk management configuration."""
    from src.trading.risk import RiskConfig
    config = RiskConfig()
    return {"data": config.__dict__}


@router.get("/broker/status")
async def broker_status(request: Request):
    """Check if broker is configured and connected."""
    from src.trading.broker import PaperBroker
    configured = PaperBroker.is_configured()
    return {
        "data": {
            "configured": configured,
            "broker": "paper_local",
            "mode": "paper",
            "message": "Local paper trading ready" if configured else "Paper broker unavailable",
        }
    }


@router.post("/account/reset")
async def reset_account(request: Request):
    """Reset paper trading account to $100,000."""
    try:
        from src.trading.broker import PaperBroker
        broker = PaperBroker()
        await broker.reset_account()
        return {"data": {"message": "Account reset to $100,000"}}
    except Exception as exc:
        logger.error("reset_account error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Market Data — akshare + yfinance
# ---------------------------------------------------------------------------


@router.get("/market-overview")
async def market_overview(request: Request):
    """Major market indices (CN + US)."""
    try:
        from src.trading.market_data import MarketDataProvider
        provider = MarketDataProvider()
        indices = await provider.get_market_overview()
        return {"data": [{"code": i.code, "name": i.name, "price": i.price, "change": i.change, "change_pct": i.change_pct} for i in indices]}
    except Exception as exc:
        logger.error("market_overview error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/quote/{ticker}")
async def get_quote(request: Request, ticker: str):
    """Real-time quote for a ticker."""
    try:
        from src.trading.market_data import MarketDataProvider
        provider = MarketDataProvider()
        quote = await provider.get_realtime_quote(ticker)
        if not quote:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}")
        return {"data": quote.__dict__}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_quote error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/kline/{ticker}")
async def get_kline(request: Request, ticker: str, period: str = Query("daily"), count: int = Query(60, ge=1, le=365)):
    """K-line data for a ticker."""
    try:
        from src.trading.market_data import MarketDataProvider
        provider = MarketDataProvider()
        data = await provider.get_kline(ticker, period, count)
        return {"data": [d.__dict__ for d in data]}
    except Exception as exc:
        logger.error("get_kline error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/backtest/{ticker}")
async def run_backtest(
    request: Request,
    ticker: str,
    days: int = Query(365, ge=30, le=730),
    stop_loss: float = Query(0.05, ge=0.01, le=0.20),
    take_profit: float = Query(0.15, ge=0.05, le=0.50),
):
    """Run a backtest on a ticker with technical strategy."""
    try:
        from src.trading.backtest import Backtester
        bt = Backtester(
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
        )
        result = await bt.run(ticker, days=days)
        return {
            "data": {
                "ticker": result.ticker,
                "period": result.period,
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "profit_trades": result.profit_trades,
                "loss_trades": result.loss_trades,
                "avg_profit_pct": result.avg_profit_pct,
                "avg_loss_pct": result.avg_loss_pct,
                "profit_factor": result.profit_factor,
                "max_consecutive_wins": result.max_consecutive_wins,
                "max_consecutive_losses": result.max_consecutive_losses,
                "trades": [
                    {
                        "entry_date": t.entry_date,
                        "exit_date": t.exit_date,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "pnl": round(t.pnl, 2),
                        "pnl_pct": round(t.pnl_pct, 2),
                        "exit_reason": t.exit_reason,
                    }
                    for t in result.trades
                ],
                "equity_curve": result.equity_curve,
            }
        }
    except Exception as exc:
        logger.error("backtest error for %s: %s", ticker, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# AutoTrader — automated trading control
# ---------------------------------------------------------------------------


@router.get("/auto/status")
async def auto_trader_status(request: Request):
    """Get AutoTrader status, config, and recent decisions."""
    trader = getattr(request.app.state, "auto_trader", None)
    if not trader:
        return {"data": {"enabled": False, "message": "AutoTrader not initialized"}}

    positions = await trader.broker.get_positions()
    status = trader.get_status()
    status["open_positions"] = len(positions)

    # Last 20 decisions
    log = trader.trade_log[-20:]
    status["recent_log"] = [
        {
            "timestamp": d.timestamp,
            "ticker": d.ticker,
            "direction": d.direction,
            "action": d.action,
            "quantity": d.quantity,
            "price": d.price,
            "confidence": d.confidence,
            "reason": d.reason,
            "broker_mode": d.broker_mode,
            "agent_opinions": d.agent_opinions,
        }
        for d in reversed(log)
    ]
    return {"data": status}


class AutoTraderToggleBody(BaseModel):
    enabled: bool
    mode: Optional[str] = None           # "paper" | "live"
    min_confidence: Optional[float] = None
    max_positions: Optional[int] = None
    position_size_pct: Optional[float] = None
    max_order_value: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None


@router.post("/auto/toggle")
async def auto_trader_toggle(request: Request, body: AutoTraderToggleBody):
    """Enable/disable AutoTrader and update config."""
    trader = getattr(request.app.state, "auto_trader", None)
    if not trader:
        raise HTTPException(status_code=500, detail="AutoTrader not initialized")

    # Prevent live mode for now
    if body.mode == "live":
        raise HTTPException(
            status_code=400,
            detail="Live trading via vnpy is not yet implemented. Use mode='paper'.",
        )

    trader.config.enabled = body.enabled
    if body.mode:
        trader.config.mode = body.mode
    if body.min_confidence is not None:
        trader.config.min_confidence = body.min_confidence
    if body.max_positions is not None:
        trader.config.max_positions = body.max_positions
    if body.position_size_pct is not None:
        trader.config.position_size_pct = body.position_size_pct
    if body.max_order_value is not None:
        trader.config.max_order_value = body.max_order_value
    if body.stop_loss_pct is not None:
        trader.config.stop_loss_pct = body.stop_loss_pct
    if body.take_profit_pct is not None:
        trader.config.take_profit_pct = body.take_profit_pct

    logger.info("[AutoTrader] %s (mode=%s, confidence>=%.2f)",
                "ENABLED" if body.enabled else "DISABLED",
                trader.config.mode, trader.config.min_confidence)

    return {"data": {"enabled": trader.config.enabled, "config": trader.get_config_dict()}}


@router.post("/auto/run-once")
async def auto_trader_run_once(request: Request):
    """Manually trigger one AutoTrader cycle (ignores enabled flag)."""
    trader = getattr(request.app.state, "auto_trader", None)
    if not trader:
        raise HTTPException(status_code=500, detail="AutoTrader not initialized")

    db = request.app.state.db

    # Temporarily enable for this cycle
    was_enabled = trader.config.enabled
    trader.config.enabled = True
    try:
        decisions = await trader.run_cycle(db)
    finally:
        trader.config.enabled = was_enabled

    return {
        "data": {
            "decisions": [
                {
                    "ticker": d.ticker,
                    "action": d.action,
                    "direction": d.direction,
                    "quantity": d.quantity,
                    "price": d.price,
                    "confidence": d.confidence,
                    "reason": d.reason,
                }
                for d in decisions
            ],
            "total": len(decisions),
            "trades": sum(1 for d in decisions if d.action in ("buy", "sell")),
        }
    }
