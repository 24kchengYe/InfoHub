"""Finance trading module — sentiment analysis and trade signal generation.

Architecture:
  infohub_query(domain="finance") → LLM sentiment analysis → trade signals

This module is a placeholder/scaffold for future implementation.
"""

from .broker import PaperBroker, OrderResult
from .indicators import TechnicalIndicators, TechnicalSignal
from .market_data import MarketDataProvider
from .risk import RiskManager, RiskConfig, RiskCheckResult, OrderRequest, Account, Position
from .sentiment import SentimentAnalyzer
from .signals import TradeSignalGenerator
from .strategy import CompositeStrategy, CompositeSignal
from .backtest import Backtester, BacktestResult
from .auto_trader import AutoTrader, AutoTraderConfig, TradeDecision, BrokerProtocol
