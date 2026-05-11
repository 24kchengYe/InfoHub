"""Local paper trading simulator — no external broker needed.

Uses SQLite to persist orders and positions, akshare/yfinance for real-time prices.
Starts with $100,000 virtual capital.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .risk import Account, Position, OrderRequest, RiskManager, RiskConfig, RiskCheckResult

logger = logging.getLogger(__name__)

DB_PATH = Path("D:/InfoHub/data/infohub.db")

PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    initial_capital REAL NOT NULL DEFAULT 100000.0,
    cash            REAL NOT NULL DEFAULT 100000.0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL UNIQUE,
    quantity        INTEGER NOT NULL DEFAULT 0,
    avg_price       REAL NOT NULL DEFAULT 0.0,
    opened_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    order_type      TEXT NOT NULL DEFAULT 'market',
    limit_price     REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    filled_price    REAL,
    signal_source   TEXT DEFAULT '',
    signal_confidence REAL DEFAULT 0.0,
    ai_reasoning    TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    filled_at       TEXT
);
"""


@dataclass
class OrderResult:
    order_id: str
    ticker: str
    side: str
    quantity: int
    status: str  # "pending_confirm" | "filled" | "rejected"
    filled_price: Optional[float] = None
    message: str = ""


class PaperBroker:
    """Local paper trading broker — everything stored in SQLite.

    Features:
    - $100,000 starting capital
    - Buy/sell with real-time prices from yfinance/akshare
    - Position tracking with P&L
    - Order history
    - Risk management integration
    - No external API keys needed
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.risk_manager = RiskManager(RiskConfig())
        self._initialized = False

    async def _ensure_tables(self):
        """Create paper trading tables if they don't exist."""
        if self._initialized:
            return
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.executescript(PAPER_SCHEMA)
            # Ensure account row exists
            row = await db.execute("SELECT id FROM paper_account WHERE id = 1")
            if not await row.fetchone():
                await db.execute("INSERT INTO paper_account (id, initial_capital, cash) VALUES (1, 100000.0, 100000.0)")
            await db.commit()
        self._initialized = True

    async def get_account(self) -> Account:
        """Get virtual account state with live P&L."""
        await self._ensure_tables()
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute("SELECT * FROM paper_account WHERE id = 1")
            acct = await row.fetchone()
            cash = float(acct["cash"])
            initial = float(acct["initial_capital"])

            # Calculate equity from positions
            positions = await self._get_positions_internal(db)
            total_market_value = sum(p.market_value for p in positions)
            equity = cash + total_market_value
            daily_pnl = equity - initial  # simplified: total P&L as "daily"

        return Account(
            equity=round(equity, 2),
            cash=round(cash, 2),
            buying_power=round(cash, 2),
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(daily_pnl / initial * 100, 2) if initial > 0 else 0,
        )

    async def get_positions(self) -> List[Position]:
        """Get all open positions with live prices."""
        await self._ensure_tables()
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            return await self._get_positions_internal(db)

    async def _get_positions_internal(self, db) -> List[Position]:
        """Internal: get positions with current prices."""
        rows = await db.execute_fetchall("SELECT * FROM paper_positions WHERE quantity > 0")
        positions = []
        for r in rows:
            ticker = r["ticker"]
            qty = int(r["quantity"])
            avg_price = float(r["avg_price"])

            # Get current price
            current_price = avg_price  # fallback
            try:
                from .market_data import MarketDataProvider
                provider = MarketDataProvider()
                quote = await provider.get_realtime_quote(ticker)
                if quote:
                    current_price = quote.price
            except Exception:
                pass

            market_value = current_price * qty
            cost_basis = avg_price * qty
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

            positions.append(Position(
                ticker=ticker,
                quantity=qty,
                avg_price=round(avg_price, 2),
                current_price=round(current_price, 2),
                market_value=round(market_value, 2),
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
            ))
        return positions

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order with risk check.

        If requires_confirmation=True, saves as pending.
        Otherwise executes immediately at current market price.
        """
        await self._ensure_tables()

        # Risk check
        account = await self.get_account()
        positions = await self.get_positions()
        risk_result = self.risk_manager.check_order(order, account, positions)

        if not risk_result.approved:
            return OrderResult(
                order_id="",
                ticker=order.ticker,
                side=order.side,
                quantity=order.quantity,
                status="rejected",
                message="Risk check failed: " + "; ".join(risk_result.rejections),
            )

        # Save order
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            cursor = await db.execute(
                """INSERT INTO paper_orders (ticker, side, quantity, order_type, limit_price,
                   status, signal_source, signal_confidence, ai_reasoning)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order.ticker, order.side, order.quantity, order.order_type,
                 order.limit_price, "pending" if order.requires_confirmation else "filling",
                 order.signal_source, order.signal_confidence, order.ai_reasoning),
            )
            order_id = str(cursor.lastrowid)
            await db.commit()

        if order.requires_confirmation:
            warnings_msg = (" Warnings: " + "; ".join(risk_result.warnings)) if risk_result.warnings else ""
            return OrderResult(
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                quantity=order.quantity,
                status="pending_confirm",
                message=f"Awaiting confirmation.{warnings_msg}",
            )

        # Execute immediately
        return await self._execute_order(int(order_id), order)

    async def confirm_and_execute(self, order_id: int, order: OrderRequest) -> OrderResult:
        """Execute a previously pending order."""
        return await self._execute_order(order_id, order)

    async def _execute_order(self, order_id: int, order: OrderRequest) -> OrderResult:
        """Execute order at current market price."""
        # Get current price
        from .market_data import MarketDataProvider
        provider = MarketDataProvider()
        quote = await provider.get_realtime_quote(order.ticker)

        if not quote:
            # Update order status
            import aiosqlite
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("UPDATE paper_orders SET status = 'rejected' WHERE id = ?", (order_id,))
                await db.commit()
            return OrderResult(
                order_id=str(order_id),
                ticker=order.ticker,
                side=order.side,
                quantity=order.quantity,
                status="rejected",
                message=f"Cannot get price for {order.ticker}",
            )

        fill_price = quote.price
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            if order.side == "buy":
                cost = fill_price * order.quantity
                # Check cash
                row = await db.execute("SELECT cash FROM paper_account WHERE id = 1")
                acct = await row.fetchone()
                cash = float(acct[0])
                if cost > cash:
                    await db.execute("UPDATE paper_orders SET status = 'rejected' WHERE id = ?", (order_id,))
                    await db.commit()
                    return OrderResult(
                        order_id=str(order_id), ticker=order.ticker, side=order.side,
                        quantity=order.quantity, status="rejected",
                        message=f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}",
                    )

                # Deduct cash
                await db.execute("UPDATE paper_account SET cash = cash - ? WHERE id = 1", (cost,))

                # Update or create position
                existing = await db.execute("SELECT quantity, avg_price FROM paper_positions WHERE ticker = ?", (order.ticker,))
                row = await existing.fetchone()
                if row:
                    old_qty = int(row[0])
                    old_avg = float(row[1])
                    new_qty = old_qty + order.quantity
                    new_avg = (old_avg * old_qty + fill_price * order.quantity) / new_qty
                    await db.execute(
                        "UPDATE paper_positions SET quantity = ?, avg_price = ?, updated_at = ? WHERE ticker = ?",
                        (new_qty, round(new_avg, 4), now, order.ticker),
                    )
                else:
                    await db.execute(
                        "INSERT INTO paper_positions (ticker, quantity, avg_price, opened_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (order.ticker, order.quantity, fill_price, now, now),
                    )

            elif order.side == "sell":
                # Check position
                existing = await db.execute("SELECT quantity, avg_price FROM paper_positions WHERE ticker = ?", (order.ticker,))
                row = await existing.fetchone()
                if not row or int(row[0]) < order.quantity:
                    await db.execute("UPDATE paper_orders SET status = 'rejected' WHERE id = ?", (order_id,))
                    await db.commit()
                    return OrderResult(
                        order_id=str(order_id), ticker=order.ticker, side=order.side,
                        quantity=order.quantity, status="rejected",
                        message=f"Insufficient position: have {int(row[0]) if row else 0}, want to sell {order.quantity}",
                    )

                proceeds = fill_price * order.quantity
                await db.execute("UPDATE paper_account SET cash = cash + ? WHERE id = 1", (proceeds,))

                new_qty = int(row[0]) - order.quantity
                if new_qty == 0:
                    await db.execute("DELETE FROM paper_positions WHERE ticker = ?", (order.ticker,))
                else:
                    await db.execute(
                        "UPDATE paper_positions SET quantity = ?, updated_at = ? WHERE ticker = ?",
                        (new_qty, now, order.ticker),
                    )

            # Update order
            await db.execute(
                "UPDATE paper_orders SET status = 'filled', filled_price = ?, filled_at = ? WHERE id = ?",
                (fill_price, now, order_id),
            )
            await db.commit()

        self.risk_manager.record_trade(order.ticker)

        return OrderResult(
            order_id=str(order_id),
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            status="filled",
            filled_price=fill_price,
            message=f"{'Bought' if order.side == 'buy' else 'Sold'} {order.quantity} {order.ticker} @ ${fill_price:.2f}",
        )

    async def get_order_history(self, limit: int = 50) -> List[dict]:
        """Get recent orders."""
        await self._ensure_tables()
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in rows]

    async def reset_account(self, initial_capital: float = 100000.0):
        """Reset paper account to starting state."""
        await self._ensure_tables()
        import aiosqlite
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("UPDATE paper_account SET cash = ?, initial_capital = ? WHERE id = 1",
                           (initial_capital, initial_capital))
            await db.execute("DELETE FROM paper_positions")
            await db.execute("DELETE FROM paper_orders")
            await db.commit()

    @staticmethod
    def is_configured() -> bool:
        """Local broker is always available."""
        return True
