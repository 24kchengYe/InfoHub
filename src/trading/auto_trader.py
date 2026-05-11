"""AutoTrader — automated signal-to-order execution engine.

Architecture (dual-mode):
  - Paper mode: PaperBroker (SQLite, virtual $100K, yfinance prices)
  - Live mode:  VnpyBroker (future, CTP/XTP gateway → real A-share execution)

Both modes share the same decision pipeline:
  1. Evaluate composite signals (sentiment + technical + volume)
  2. Filter by confidence threshold
  3. Calculate position size via RiskManager
  4. Submit OrderRequest to the active Broker
  5. Log every decision for audit trail

The Broker interface is pluggable — AutoTrader only produces OrderRequest
objects and reads Account/Position state. It never touches execution details.
"""

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Protocol, runtime_checkable

from .broker import PaperBroker, OrderResult
from .risk import OrderRequest, RiskManager, RiskConfig, Account, Position
from .strategy import CompositeStrategy, CompositeSignal
from .sentiment import SentimentResult, Sentiment

logger = logging.getLogger("infohub.trading.auto")


# ------------------------------------------------------------------
# Broker protocol — any broker (paper / vnpy / alpaca) implements this
# ------------------------------------------------------------------

@runtime_checkable
class BrokerProtocol(Protocol):
    """Abstract broker interface for pluggable execution backends."""
    async def get_account(self) -> Account: ...
    async def get_positions(self) -> List[Position]: ...
    async def submit_order(self, order: OrderRequest) -> OrderResult: ...
    async def get_order_history(self, limit: int = 50) -> List[dict]: ...


@dataclass
class TradeDecision:
    """Record of a single auto-trade decision (executed or skipped)."""
    timestamp: str
    ticker: str
    direction: str
    confidence: float
    action: str          # "buy" | "sell" | "skip" | "rejected"
    quantity: int = 0
    price: Optional[float] = None
    order_id: Optional[str] = None
    reason: str = ""
    broker_mode: str = "paper"  # "paper" | "live"
    agent_opinions: Optional[dict] = None  # Multi-agent opinions (JSON-serializable)


@dataclass
class AutoTraderConfig:
    """Configuration for automatic trading."""
    enabled: bool = False
    mode: str = "paper"                 # "paper" | "live" (future: vnpy)
    min_confidence: float = 0.6         # Minimum composite confidence to act
    max_positions: int = 5              # Max simultaneous positions
    position_size_pct: float = 0.08     # 8% of equity per position
    max_order_value: float = 8000.0     # Max single order $
    cooldown_minutes: int = 60          # Same ticker cooldown
    check_stop_loss: bool = True        # Monitor stop-loss / take-profit
    stop_loss_pct: float = 0.05         # 5% stop loss
    take_profit_pct: float = 0.15       # 15% take profit
    # Only trade during US market hours (ET 9:30-16:00 = UTC 13:30-20:00)
    market_hours_only: bool = False
    use_multi_agent: bool = True        # Use Multi-Agent LLM decision (vs simple formula)


class AutoTrader:
    """Automated trading engine connecting signals → broker.

    Usage:
        trader = AutoTrader(config)
        decisions = await trader.run_cycle(db)  # one evaluation cycle

    Dual-mode architecture:
        - config.mode="paper" → PaperBroker (default, safe)
        - config.mode="live"  → VnpyBroker (future, requires explicit enable)
    """

    def __init__(self, config: AutoTraderConfig = None, broker: BrokerProtocol = None, ai_client=None):
        self.config = config or AutoTraderConfig()
        self._ai_client = ai_client  # For Multi-Agent mode
        # Pluggable broker: injected or created by mode
        if broker:
            self.broker = broker
        else:
            self.broker = self._create_broker(self.config.mode)
        self._cycle_count = 0
        self.risk_manager = RiskManager(RiskConfig(
            max_position_pct=self.config.position_size_pct,
            max_open_positions=self.config.max_positions,
            max_order_value=self.config.max_order_value,
            min_confidence=self.config.min_confidence,
            stop_loss_pct=self.config.stop_loss_pct,
            take_profit_pct=self.config.take_profit_pct,
            require_confirmation=False,
        ))
        self._cooldowns: dict[str, datetime] = {}
        self._trade_log: List[TradeDecision] = []

    @staticmethod
    def _create_broker(mode: str) -> BrokerProtocol:
        """Create broker by mode. 'live' will use VnpyBroker when available."""
        if mode == "live":
            # Future: from .vnpy_broker import VnpyBroker; return VnpyBroker()
            raise NotImplementedError(
                "Live trading via vnpy is not yet implemented. "
                "Use mode='paper' for now."
            )
        return PaperBroker()

    @property
    def trade_log(self) -> List[TradeDecision]:
        return list(self._trade_log)

    def get_config_dict(self) -> dict:
        return asdict(self.config)

    def get_status(self) -> dict:
        """Return current auto-trader status for API."""
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "use_multi_agent": self.config.use_multi_agent and self._ai_client is not None,
            "cycle_count": self._cycle_count,
            "open_positions": 0,  # filled by caller
            "recent_decisions": len(self._trade_log),
            "config": self.get_config_dict(),
        }

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, db) -> List[TradeDecision]:
        """Execute one full evaluation cycle:
        1. Generate composite signals from DB items
        2. Decide buy/sell/skip for each
        3. Execute orders
        4. Check stop-loss/take-profit on existing positions
        """
        if not self.config.enabled:
            return []

        now = datetime.now(timezone.utc)
        decisions: List[TradeDecision] = []

        self._cycle_count += 1
        logger.info("[AutoTrader] Cycle #%d at %s (mode=%s)",
                    self._cycle_count, now.isoformat(), self.config.mode)

        # --- Phase 1: Check stop-loss / take-profit on existing positions ---
        if self.config.check_stop_loss:
            sl_decisions = await self._check_stop_loss_take_profit()
            decisions.extend(sl_decisions)

        # --- Phase 2: Generate new signals and open positions ---
        account = await self.broker.get_account()
        positions = await self.broker.get_positions()
        held_tickers = {p.ticker for p in positions}

        if self.config.use_multi_agent and self._ai_client:
            # Multi-Agent mode: LLM-powered decision pipeline
            try:
                ma_decisions = await self._run_multi_agent(db, account, positions, held_tickers, now)
                decisions.extend(ma_decisions)
            except Exception as exc:
                logger.error("[AutoTrader] Multi-Agent failed, falling back to formula: %s", exc, exc_info=True)
                # Fallback to formula mode
                await self._run_formula_mode(db, account, positions, held_tickers, now, decisions)
        else:
            # Formula mode: simple weighted composite
            await self._run_formula_mode(db, account, positions, held_tickers, now, decisions)

        self._trade_log.extend(decisions)
        # Keep log bounded
        if len(self._trade_log) > 500:
            self._trade_log = self._trade_log[-300:]

        logger.info("[AutoTrader] Cycle complete: %d decisions (%d trades)",
                    len(decisions), sum(1 for d in decisions if d.action in ("buy", "sell")))
        return decisions

    # ------------------------------------------------------------------
    # Multi-Agent mode
    # ------------------------------------------------------------------

    async def _run_multi_agent(self, db, account, positions, held_tickers, now) -> List[TradeDecision]:
        """Run Multi-Agent evaluation pipeline."""
        from .agents.orchestrator import AgentOrchestrator

        # Build news data from DB
        result = await db.get_items(domain="finance", sort="published_at", page=1, per_page=100)
        items = result["items"]

        ticker_news: dict[str, list] = {}
        for item in items:
            meta = item.metadata or {}
            tickers = meta.get("tickers", [])
            if not tickers:
                continue
            news_entry = {
                "title": meta.get("title_zh") or item.title,
                "summary": (meta.get("detailed_summary_zh") or meta.get("detailed_summary_en")
                            or item.ai_summary or "")[:300],
                "published_at": item.published_at.isoformat() if item.published_at else "",
                "sentiment_keyword": meta.get("sentiment", ""),
            }
            for ticker in tickers:
                ticker_news.setdefault(ticker, []).append(news_entry)

        if not ticker_news:
            return []

        orchestrator = AgentOrchestrator(self._ai_client)
        ma_results = await orchestrator.evaluate_multiple(ticker_news, account, positions)

        decisions = []
        ts = now.isoformat()

        for mar in ma_results:
            dec = mar.final_decision
            agent_data = mar.to_dict()

            # Map multi-agent decision to trade execution
            if dec.action == "hold" or dec.confidence < self.config.min_confidence:
                decisions.append(TradeDecision(
                    timestamp=ts, ticker=mar.ticker, direction=dec.direction,
                    confidence=dec.confidence, action="skip",
                    reason=dec.reasoning, agent_opinions=agent_data,
                ))
                continue

            # Cooldown check
            if mar.ticker in self._cooldowns:
                elapsed = (now - self._cooldowns[mar.ticker]).total_seconds() / 60
                if elapsed < self.config.cooldown_minutes:
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction=dec.direction,
                        confidence=dec.confidence, action="skip",
                        reason=f"Cooldown: {elapsed:.0f}m / {self.config.cooldown_minutes}m",
                        agent_opinions=agent_data,
                    ))
                    continue

            if dec.action == "buy" and mar.ticker not in held_tickers:
                if len(positions) >= self.config.max_positions:
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="long",
                        confidence=dec.confidence, action="skip",
                        reason=f"Max positions reached ({self.config.max_positions})",
                        agent_opinions=agent_data,
                    ))
                    continue

                # Get price and calculate quantity
                from .market_data import MarketDataProvider
                provider = MarketDataProvider()
                quote = await provider.get_realtime_quote(mar.ticker)
                if not quote or quote.price <= 0:
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="long",
                        confidence=dec.confidence, action="skip",
                        reason="No price data", agent_opinions=agent_data,
                    ))
                    continue

                quantity = self.risk_manager.calculate_position_size(
                    mar.ticker, quote.price, account, dec.confidence,
                )
                if quantity <= 0:
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="long",
                        confidence=dec.confidence, action="skip",
                        reason="Quantity=0 after risk sizing", agent_opinions=agent_data,
                    ))
                    continue

                order = OrderRequest(
                    ticker=mar.ticker, side="buy", quantity=quantity,
                    order_type="market", limit_price=quote.price,
                    signal_source="multi_agent",
                    signal_confidence=dec.confidence,
                    ai_reasoning=dec.reasoning,
                    requires_confirmation=False,
                )
                result = await self.broker.submit_order(order)
                self._cooldowns[mar.ticker] = now

                if result.status == "filled":
                    logger.info("[MultiAgent] BUY %d %s @ $%.2f", quantity, mar.ticker, result.filled_price)
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="long",
                        confidence=dec.confidence, action="buy",
                        quantity=quantity, price=result.filled_price,
                        order_id=result.order_id, reason=dec.reasoning,
                        agent_opinions=agent_data,
                    ))
                    account = await self.broker.get_account()
                    positions = await self.broker.get_positions()
                    held_tickers = {p.ticker for p in positions}
                else:
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="long",
                        confidence=dec.confidence, action="rejected",
                        reason=result.message, agent_opinions=agent_data,
                    ))

            elif dec.action == "sell" and mar.ticker in held_tickers:
                pos = next((p for p in positions if p.ticker == mar.ticker), None)
                if not pos:
                    continue
                order = OrderRequest(
                    ticker=mar.ticker, side="sell", quantity=pos.quantity,
                    order_type="market",
                    signal_source="multi_agent_sell",
                    signal_confidence=dec.confidence,
                    ai_reasoning=dec.reasoning,
                    requires_confirmation=False,
                )
                result = await self.broker.submit_order(order)
                self._cooldowns[mar.ticker] = now

                if result.status == "filled":
                    pnl = (result.filled_price - pos.avg_price) * pos.quantity
                    logger.info("[MultiAgent] SELL %d %s @ $%.2f (P&L: $%.2f)",
                                pos.quantity, mar.ticker, result.filled_price, pnl)
                    decisions.append(TradeDecision(
                        timestamp=ts, ticker=mar.ticker, direction="short",
                        confidence=dec.confidence, action="sell",
                        quantity=pos.quantity, price=result.filled_price,
                        order_id=result.order_id, reason=f"Agent sell. P&L: ${pnl:.2f}",
                        agent_opinions=agent_data,
                    ))
                    account = await self.broker.get_account()
                    positions = await self.broker.get_positions()
                    held_tickers = {p.ticker for p in positions}

        return decisions

    async def _run_formula_mode(self, db, account, positions, held_tickers, now, decisions):
        """Fallback: formula-based signal generation (no LLM)."""
        try:
            signals = await self._generate_signals(db)
        except Exception as exc:
            logger.error("[AutoTrader] Formula signal generation failed: %s", exc)
            return

        for signal in signals:
            decision = await self._process_signal(signal, account, positions, held_tickers, now)
            if decision:
                decisions.append(decision)
                if decision.action == "buy":
                    account = await self.broker.get_account()
                    positions = await self.broker.get_positions()
                    held_tickers = {p.ticker for p in positions}

    # ------------------------------------------------------------------
    # Signal generation (formula mode fallback)
    # ------------------------------------------------------------------

    async def _generate_signals(self, db) -> List[CompositeSignal]:
        """Generate composite signals from finance items in DB."""
        result = await db.get_items(domain="finance", sort="published_at", page=1, per_page=100)
        items = result["items"]

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
            return []

        strategy = CompositeStrategy(
            stop_loss_pct=self.config.stop_loss_pct,
            take_profit_pct=self.config.take_profit_pct,
        )
        return await strategy.evaluate_multiple(ticker_sentiments)

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    async def _process_signal(
        self,
        signal: CompositeSignal,
        account,
        positions,
        held_tickers: set,
        now: datetime,
    ) -> Optional[TradeDecision]:
        """Decide what to do with a single signal."""
        ts = now.isoformat()

        # Skip low confidence
        if signal.confidence < self.config.min_confidence:
            return TradeDecision(
                timestamp=ts, ticker=signal.ticker, direction=signal.direction,
                confidence=signal.confidence, action="skip",
                reason=f"Confidence {signal.confidence:.2f} < threshold {self.config.min_confidence:.2f}",
            )

        # Skip hold signals
        if signal.direction == "hold":
            return TradeDecision(
                timestamp=ts, ticker=signal.ticker, direction="hold",
                confidence=signal.confidence, action="skip", reason="Hold signal",
            )

        # Cooldown check
        if signal.ticker in self._cooldowns:
            elapsed = (now - self._cooldowns[signal.ticker]).total_seconds() / 60
            if elapsed < self.config.cooldown_minutes:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction=signal.direction,
                    confidence=signal.confidence, action="skip",
                    reason=f"Cooldown: {elapsed:.0f}m / {self.config.cooldown_minutes}m",
                )

        # --- BUY logic ---
        if signal.direction == "long" and signal.ticker not in held_tickers:
            if len(positions) >= self.config.max_positions:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="long",
                    confidence=signal.confidence, action="skip",
                    reason=f"Max positions reached ({self.config.max_positions})",
                )

            price = signal.current_price
            if not price or price <= 0:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="long",
                    confidence=signal.confidence, action="skip",
                    reason="No price data available",
                )

            # Calculate position size
            quantity = self.risk_manager.calculate_position_size(
                signal.ticker, price, account, signal.confidence,
            )
            if quantity <= 0:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="long",
                    confidence=signal.confidence, action="skip",
                    reason="Calculated quantity = 0 (insufficient funds or risk limit)",
                )

            # Submit order
            order = OrderRequest(
                ticker=signal.ticker,
                side="buy",
                quantity=quantity,
                order_type="market",
                limit_price=price,
                signal_source="auto_trader",
                signal_confidence=signal.confidence,
                ai_reasoning=signal.reasoning,
                requires_confirmation=False,
            )
            result = await self.broker.submit_order(order)
            self._cooldowns[signal.ticker] = now

            if result.status == "filled":
                logger.info("[AutoTrader] BUY %d %s @ $%.2f (conf=%.2f)",
                            quantity, signal.ticker, result.filled_price, signal.confidence)
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="long",
                    confidence=signal.confidence, action="buy",
                    quantity=quantity, price=result.filled_price,
                    order_id=result.order_id, reason=signal.reasoning,
                )
            else:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="long",
                    confidence=signal.confidence, action="rejected",
                    reason=result.message,
                )

        # --- SELL logic: if bearish and we hold the position ---
        if signal.direction == "short" and signal.ticker in held_tickers:
            pos = next((p for p in positions if p.ticker == signal.ticker), None)
            if not pos:
                return None

            order = OrderRequest(
                ticker=signal.ticker,
                side="sell",
                quantity=pos.quantity,
                order_type="market",
                signal_source="auto_trader_bearish",
                signal_confidence=signal.confidence,
                ai_reasoning=f"Bearish signal: {signal.reasoning}",
                requires_confirmation=False,
            )
            result = await self.broker.submit_order(order)
            self._cooldowns[signal.ticker] = now

            if result.status == "filled":
                pnl = (result.filled_price - pos.avg_price) * pos.quantity
                logger.info("[AutoTrader] SELL %d %s @ $%.2f (P&L: $%.2f)",
                            pos.quantity, signal.ticker, result.filled_price, pnl)
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="short",
                    confidence=signal.confidence, action="sell",
                    quantity=pos.quantity, price=result.filled_price,
                    order_id=result.order_id,
                    reason=f"Bearish signal sell. P&L: ${pnl:.2f}",
                )
            else:
                return TradeDecision(
                    timestamp=ts, ticker=signal.ticker, direction="short",
                    confidence=signal.confidence, action="rejected",
                    reason=result.message,
                )

        return None

    # ------------------------------------------------------------------
    # Stop-loss / Take-profit monitor
    # ------------------------------------------------------------------

    async def _check_stop_loss_take_profit(self) -> List[TradeDecision]:
        """Check all open positions against stop-loss and take-profit levels."""
        decisions = []
        positions = await self.broker.get_positions()
        now = datetime.now(timezone.utc).isoformat()

        for pos in positions:
            if pos.quantity <= 0:
                continue

            pnl_pct = pos.pnl_pct / 100  # convert from percentage

            triggered = None
            reason = ""

            if pnl_pct <= -self.config.stop_loss_pct:
                triggered = "stop_loss"
                reason = f"Stop-loss triggered: {pos.pnl_pct:.1f}% (limit: -{self.config.stop_loss_pct*100:.0f}%)"
            elif pnl_pct >= self.config.take_profit_pct:
                triggered = "take_profit"
                reason = f"Take-profit triggered: {pos.pnl_pct:.1f}% (target: +{self.config.take_profit_pct*100:.0f}%)"

            if not triggered:
                continue

            logger.info("[AutoTrader] %s on %s: %s", triggered.upper(), pos.ticker, reason)

            order = OrderRequest(
                ticker=pos.ticker,
                side="sell",
                quantity=pos.quantity,
                order_type="market",
                signal_source=f"auto_{triggered}",
                signal_confidence=1.0,
                ai_reasoning=reason,
                requires_confirmation=False,
            )
            result = await self.broker.submit_order(order)

            if result.status == "filled":
                decisions.append(TradeDecision(
                    timestamp=now, ticker=pos.ticker, direction="sell",
                    confidence=1.0, action="sell",
                    quantity=pos.quantity, price=result.filled_price,
                    order_id=result.order_id, reason=reason,
                ))
            else:
                decisions.append(TradeDecision(
                    timestamp=now, ticker=pos.ticker, direction="sell",
                    confidence=1.0, action="rejected",
                    reason=f"{triggered} sell rejected: {result.message}",
                ))

        return decisions
