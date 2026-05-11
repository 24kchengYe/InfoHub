"""VnpyBroker — future live trading broker via vnpy CTP/XTP gateway.

Architecture:
  - Wraps a vnpy MainEngine
  - CTP gateway → A-share futures
  - XTP gateway → A-share stocks
  - Same BrokerProtocol interface as PaperBroker

Requirements:
  pip install vnpy vnpy_ctp vnpy_xtp
  Configure broker credentials in data/vnpy_config.json

This is currently a stub — all methods raise NotImplementedError
with clear guidance on what's needed for implementation.
"""

import logging
from typing import List, Optional

from .risk import Account, Position, OrderRequest
from .broker import OrderResult

logger = logging.getLogger("infohub.trading.vnpy")


class VnpyBroker:
    """Live trading broker via vnpy (CTP/XTP gateway).

    Implements the same BrokerProtocol as PaperBroker.
    Uses vnpy's MainEngine + EventEngine for real order execution.

    Future implementation roadmap:
    1. Initialize vnpy MainEngine with CTP or XTP gateway
    2. Connect to broker (requires credentials in config)
    3. Map OrderRequest to vnpy OrderRequest format
    4. Handle async event callbacks (on_order, on_trade, on_position)
    5. Convert vnpy positions/account to our data models
    """

    def __init__(self, gateway: str = "ctp", config_path: Optional[str] = None):
        """Initialize vnpy broker.

        Args:
            gateway: "ctp" for futures, "xtp" for A-share stocks
            config_path: Path to vnpy gateway config JSON
        """
        self.gateway = gateway
        self.config_path = config_path
        raise NotImplementedError(
            f"VnpyBroker (gateway={gateway}) is not yet implemented.\n\n"
            "To enable live trading:\n"
            "1. Install: pip install vnpy vnpy_ctp vnpy_xtp\n"
            "2. Create config: data/vnpy_config.json with broker credentials\n"
            "3. Implement this class to wrap vnpy MainEngine\n\n"
            "Current architecture supports this — AutoTrader uses BrokerProtocol,\n"
            "so replacing PaperBroker with VnpyBroker requires no changes to\n"
            "the decision pipeline (Multi-Agent or formula mode)."
        )

    async def get_account(self) -> Account:
        """Get live account state from broker."""
        raise NotImplementedError("VnpyBroker.get_account not implemented")

    async def get_positions(self) -> List[Position]:
        """Get live positions from broker."""
        raise NotImplementedError("VnpyBroker.get_positions not implemented")

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit real order to broker via vnpy gateway."""
        raise NotImplementedError("VnpyBroker.submit_order not implemented")

    async def get_order_history(self, limit: int = 50) -> List[dict]:
        """Get recent orders from broker."""
        raise NotImplementedError("VnpyBroker.get_order_history not implemented")

    @staticmethod
    def is_configured() -> bool:
        """Check if vnpy and gateway config are available."""
        try:
            import vnpy  # noqa: F401
            return True
        except ImportError:
            return False
