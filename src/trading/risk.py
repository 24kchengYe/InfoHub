"""Risk management module — enforces safety rules before any trade execution."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Risk control parameters."""
    max_position_pct: float = 0.1       # Max 10% of portfolio in one ticker
    max_daily_loss_pct: float = 0.02    # Max 2% daily loss
    max_open_positions: int = 10        # Max 10 simultaneous positions
    stop_loss_pct: float = 0.05         # Default 5% stop loss
    take_profit_pct: float = 0.15       # Default 15% take profit
    min_confidence: float = 0.7         # Minimum signal confidence to trade
    cooldown_hours: int = 24            # Same ticker cooldown period
    max_order_value: float = 10000.0    # Max single order value ($)
    require_confirmation: bool = True   # Require human confirmation


@dataclass
class Account:
    """Trading account state."""
    equity: float
    cash: float
    buying_power: float
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0


@dataclass
class Position:
    """A single position."""
    ticker: str
    quantity: int
    avg_price: float
    current_price: float
    market_value: float
    pnl: float
    pnl_pct: float


@dataclass
class OrderRequest:
    """A proposed trade order."""
    ticker: str
    side: str           # "buy" | "sell"
    quantity: int
    order_type: str     # "market" | "limit" | "stop_loss"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    signal_source: str = ""
    signal_confidence: float = 0.0
    ai_reasoning: str = ""
    requires_confirmation: bool = True


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    approved: bool
    order: OrderRequest
    warnings: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    suggested_quantity: Optional[int] = None
    suggested_stop_loss: Optional[float] = None
    suggested_take_profit: Optional[float] = None


class RiskManager:
    """Risk control engine — all orders must pass through this before execution.

    Safety principles:
    1. Position sizing based on portfolio percentage
    2. Daily loss limits
    3. Maximum open positions
    4. Minimum signal confidence
    5. Per-ticker cooldown
    6. Mandatory stop-loss
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self._recent_trades: dict[str, str] = {}  # ticker -> last trade ISO timestamp

    def check_order(
        self,
        order: OrderRequest,
        account: Account,
        positions: List[Position],
    ) -> RiskCheckResult:
        """Check if an order passes all risk rules.

        Args:
            order: The proposed order
            account: Current account state
            positions: Current open positions

        Returns:
            RiskCheckResult with approved/rejected status
        """
        warnings: List[str] = []
        rejections: List[str] = []

        # 1. Check daily loss limit
        if account.daily_pnl_pct < -self.config.max_daily_loss_pct * 100:
            rejections.append(
                f"Daily loss limit exceeded: {account.daily_pnl_pct:.2f}% "
                f"(limit: {-self.config.max_daily_loss_pct * 100:.1f}%)"
            )

        # 2. Check max open positions (only for buy orders)
        if order.side == "buy" and len(positions) >= self.config.max_open_positions:
            existing = any(p.ticker == order.ticker for p in positions)
            if not existing:
                rejections.append(
                    f"Max open positions reached: {len(positions)}/{self.config.max_open_positions}"
                )

        # 3. Check signal confidence
        if order.signal_confidence < self.config.min_confidence:
            warnings.append(
                f"Low signal confidence: {order.signal_confidence:.2f} "
                f"(threshold: {self.config.min_confidence:.2f})"
            )

        # 4. Check position size limit
        if order.side == "buy":
            price = order.limit_price or 0
            order_value = price * order.quantity if price > 0 else 0

            if order_value > 0:
                position_pct = order_value / account.equity if account.equity > 0 else 1.0
                if position_pct > self.config.max_position_pct:
                    suggested_qty = int(account.equity * self.config.max_position_pct / price)
                    warnings.append(
                        f"Position too large: {position_pct:.1%} of portfolio "
                        f"(limit: {self.config.max_position_pct:.1%}). "
                        f"Suggested: {suggested_qty} shares"
                    )

            # 5. Check max order value
            if order_value > self.config.max_order_value:
                warnings.append(
                    f"Order value ${order_value:,.0f} exceeds max ${self.config.max_order_value:,.0f}"
                )

        # 6. Check cooldown
        if order.ticker in self._recent_trades:
            last_trade = datetime.fromisoformat(self._recent_trades[order.ticker])
            now = datetime.now(timezone.utc)
            hours_since = (now - last_trade).total_seconds() / 3600
            if hours_since < self.config.cooldown_hours:
                warnings.append(
                    f"Cooldown active for {order.ticker}: "
                    f"{hours_since:.1f}h since last trade "
                    f"(cooldown: {self.config.cooldown_hours}h)"
                )

        # 7. Check sufficient buying power
        if order.side == "buy":
            price = order.limit_price or 0
            needed = price * order.quantity
            if needed > account.buying_power:
                rejections.append(
                    f"Insufficient buying power: need ${needed:,.0f}, "
                    f"have ${account.buying_power:,.0f}"
                )

        # Calculate suggested stop-loss and take-profit
        price = order.limit_price or 0
        suggested_sl = None
        suggested_tp = None
        if price > 0 and order.side == "buy":
            suggested_sl = round(price * (1 - self.config.stop_loss_pct), 2)
            suggested_tp = round(price * (1 + self.config.take_profit_pct), 2)

        # Calculate suggested quantity based on risk rules
        suggested_qty = None
        if order.side == "buy" and price > 0 and account.equity > 0:
            max_by_position = int(account.equity * self.config.max_position_pct / price)
            max_by_order_value = int(self.config.max_order_value / price)
            max_by_buying_power = int(account.buying_power / price)
            suggested_qty = max(1, min(max_by_position, max_by_order_value, max_by_buying_power))

        approved = len(rejections) == 0

        return RiskCheckResult(
            approved=approved,
            order=order,
            warnings=warnings,
            rejections=rejections,
            suggested_quantity=suggested_qty,
            suggested_stop_loss=suggested_sl,
            suggested_take_profit=suggested_tp,
        )

    def calculate_position_size(
        self,
        ticker: str,
        price: float,
        account: Account,
        signal_confidence: float = 0.5,
    ) -> int:
        """Calculate recommended position size based on risk rules.

        Uses a confidence-scaled approach:
        - Base size = max_position_pct of equity
        - Scaled by signal confidence
        - Capped by max_order_value and buying_power
        """
        if price <= 0 or account.equity <= 0:
            return 0

        # Base allocation scaled by confidence
        confidence_scale = max(0.3, min(signal_confidence, 1.0))
        base_allocation = account.equity * self.config.max_position_pct * confidence_scale

        # Cap by max order value
        allocation = min(base_allocation, self.config.max_order_value)

        # Cap by buying power
        allocation = min(allocation, account.buying_power * 0.95)

        quantity = int(allocation / price)
        return max(0, quantity)

    def record_trade(self, ticker: str) -> None:
        """Record a trade for cooldown tracking."""
        self._recent_trades[ticker] = datetime.now(timezone.utc).isoformat()

    def get_risk_summary(self, account: Account, positions: List[Position]) -> dict:
        """Generate a risk summary for the dashboard."""
        total_exposure = sum(p.market_value for p in positions)
        exposure_pct = (total_exposure / account.equity * 100) if account.equity > 0 else 0

        largest_position = max(positions, key=lambda p: p.market_value) if positions else None
        largest_pct = (largest_position.market_value / account.equity * 100) if largest_position and account.equity > 0 else 0

        # Risk level assessment
        risk_level = "low"
        if exposure_pct > 80 or abs(account.daily_pnl_pct) > 1.5:
            risk_level = "high"
        elif exposure_pct > 50 or abs(account.daily_pnl_pct) > 0.8:
            risk_level = "medium"

        return {
            "risk_level": risk_level,
            "total_exposure": round(total_exposure, 2),
            "exposure_pct": round(exposure_pct, 2),
            "open_positions": len(positions),
            "max_positions": self.config.max_open_positions,
            "daily_pnl": round(account.daily_pnl, 2),
            "daily_pnl_pct": round(account.daily_pnl_pct, 2),
            "daily_loss_limit_pct": self.config.max_daily_loss_pct * 100,
            "largest_position": largest_position.ticker if largest_position else None,
            "largest_position_pct": round(largest_pct, 2),
            "max_position_pct": self.config.max_position_pct * 100,
        }
