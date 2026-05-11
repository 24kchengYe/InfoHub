# InfoHub 金融交易模块 Phase 2 — 详细方案

## 一、现状（Phase 1 已完成）

| 组件 | 实现 | 局限 |
|------|------|------|
| 情绪分析 | 关键词匹配（54 个中英文关键词） | 不够准确，无法理解语义 |
| 交易信号 | 按 ticker 聚合情绪 → long/short/hold | 没有行情数据辅助 |
| 数据源 | 10 个 RSS + 3 个 Reddit | 只有英文财经，缺少 A 股信源 |
| 前端展示 | 情绪面板 + 信号列表 + ticker 热度 | 没有 K 线图、没有持仓管理 |
| 交易执行 | ❌ 无 | 不能下单 |

## 二、Phase 2 目标

**让系统从"看新闻"进化到"能交易"：**
1. LLM 驱动的情绪分析（替代关键词）
2. 实时行情数据接入
3. 券商 API 模拟盘对接（纸上交易）
4. 专业级前端交易面板
5. 中国 A 股 + 基金信源

## 三、技术架构

```
                    ┌─────────────────────────────────────┐
                    │         InfoHub Trading v2           │
                    └─────────────────────────────────────┘
                                    │
        ┌───────────────┬───────────┴───────────┬────────────────┐
        ▼               ▼                       ▼                ▼
 ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐ ┌──────────────┐
 │  数据层       │ │  分析层       │ │  交易执行层         │ │  展示层       │
 │              │ │              │ │                   │ │              │
 │ · 财经 RSS   │ │ · LLM 情绪   │ │ · Alpaca 模拟盘   │ │ · K 线图     │
 │ · AKShare    │ │ · 技术指标   │ │ · 风控模块        │ │ · 持仓面板   │
 │ · Reddit/HN  │ │ · 综合信号   │ │ · 订单管理        │ │ · 情绪热力图 │
 │ · A股信源    │ │ · 回测引擎   │ │ · 纸上交易记录    │ │ · 交易历史   │
 └──────────────┘ └──────────────┘ └───────────────────┘ └──────────────┘
```

## 四、分步实施计划

---

### Step 1：LLM 情绪分析升级（2-3 天）

**目标**：用 DeepSeek V3（已接入）替代关键词匹配，准确度从 ~60% 提升到 ~90%

**改动文件**：`src/trading/sentiment.py`

**方案**：
```python
class LLMSentimentAnalyzer:
    """用 LLM 分析金融新闻情绪，替代关键词匹配。"""
    
    PROMPT = """分析以下金融新闻的市场情绪。返回 JSON：
    {
        "sentiment": "bullish" | "bearish" | "neutral",
        "confidence": 0.0-1.0,
        "tickers": ["AAPL", "TSLA"],  // 涉及的股票代码
        "impact": "high" | "medium" | "low",  // 对市场的影响程度
        "reasoning": "一句话解释",
        "time_horizon": "short" | "medium" | "long"  // 影响时间跨度
    }
    
    标题：{title}
    摘要：{summary}
    """
```

**参考项目**：
- [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) — 金融领域微调 LLM
- [LLM-Enhanced-Trading](https://github.com/Ronitt272/LLM-Enhanced-Trading) — FinGPT 驱动的实时交易系统

**新增字段**：`impact`（影响程度）、`time_horizon`（时间跨度）→ 帮助判断短线/中线/长线信号

---

### Step 2：A 股 + 基金数据接入（2-3 天）

**目标**：接入中国市场实时/历史行情，补充中文财经信源

**新增依赖**：
```toml
akshare >= 1.18.0     # 免费 A 股/基金数据
yfinance >= 0.2.0     # 美股/港股行情
```

**新增模块**：`src/trading/market_data.py`

```python
class MarketDataProvider:
    """统一行情数据接口。"""
    
    async def get_realtime_quote(self, ticker: str) -> Quote:
        """实时报价：价格、涨跌幅、成交量"""
    
    async def get_kline(self, ticker: str, period: str, count: int) -> list[OHLCV]:
        """K 线数据：日K、周K、分钟K"""
    
    async def get_fund_nav(self, fund_code: str) -> FundNAV:
        """基金净值"""
    
    async def get_market_overview(self) -> MarketOverview:
        """大盘指数：上证、深证、创业板、纳斯达克"""
```

**中文财经信源补充**（`finance.json`）：
```json
[
  { "name": "华尔街见闻", "url": "https://wallstreetcn.com/rss/news" },
  { "name": "36kr 财经", "url": "https://36kr.com/feed/finance" },
  { "name": "新浪财经", "url": "https://finance.sina.com.cn/rss/money.xml" },
  { "name": "东方财富", "url": "https://rsshub.app/eastmoney/report" }
]
```

**参考项目**：
- [AKShare](https://github.com/akfamily/akshare) — 最全面的免费 A 股数据接口
- [Ashare](https://github.com/mpquant/Ashare) — 极简 A 股实时行情封装

---

### Step 3：技术指标引擎（1-2 天）

**目标**：计算常用技术指标，辅助交易决策

**新增模块**：`src/trading/indicators.py`

```python
class TechnicalIndicators:
    """基于 K 线数据计算技术指标。"""
    
    @staticmethod
    def sma(prices: list[float], period: int) -> list[float]:
        """简单移动平均"""
    
    @staticmethod
    def ema(prices: list[float], period: int) -> list[float]:
        """指数移动平均"""
    
    @staticmethod
    def rsi(prices: list[float], period: int = 14) -> list[float]:
        """相对强弱指标"""
    
    @staticmethod
    def macd(prices: list[float]) -> tuple[list, list, list]:
        """MACD 指标"""
    
    @staticmethod
    def bollinger_bands(prices: list[float], period: int = 20) -> tuple[list, list, list]:
        """布林带"""
    
    @classmethod
    def generate_technical_signal(cls, kline_data: list[OHLCV]) -> TechnicalSignal:
        """综合技术面信号：看多/看空/中性"""
```

**不引入额外依赖** — 纯 Python 实现，因为这些指标算法很简单。

---

### Step 4：综合信号引擎（2 天）

**目标**：融合"情绪面 + 技术面 + 基本面"生成综合交易建议

**新增模块**：`src/trading/strategy.py`

```python
@dataclass
class CompositeSignal:
    ticker: str
    direction: str           # "long" | "short" | "hold"
    confidence: float        # 0.0 - 1.0
    
    # 三维分析
    sentiment_score: float   # LLM 情绪得分 (-1 到 +1)
    technical_score: float   # 技术指标得分 (-1 到 +1)
    news_volume: int         # 相关新闻数量（热度）
    
    # 建议
    entry_price: float | None
    stop_loss: float | None    # 止损价
    take_profit: float | None  # 止盈价
    position_size: str         # "light" | "normal" | "heavy"
    
    reasoning: str
    generated_at: str


class CompositeStrategy:
    """综合策略引擎，融合多维信号。"""
    
    def __init__(self, sentiment_weight=0.4, technical_weight=0.4, volume_weight=0.2):
        self.weights = {
            "sentiment": sentiment_weight,
            "technical": technical_weight,
            "volume": volume_weight,
        }
    
    async def evaluate(self, ticker: str) -> CompositeSignal:
        """对单个标的进行综合评估。"""
        # 1. 获取该 ticker 最近的情绪分析结果
        # 2. 获取行情数据 + 技术指标
        # 3. 加权融合
        # 4. 生成止损止盈建议
```

**参考项目**：
- [TradingAgents](https://github.com/tauricresearch/tradingagents) — 多 Agent 协作框架（基本面分析 Agent + 情绪分析 Agent + 技术分析 Agent + 风控 Agent）

---

### Step 5：券商 API 模拟盘对接（3-4 天）

**目标**：接入真实券商的模拟盘（Paper Trading），AI 生成建议 → 人工确认 → 执行

**推荐券商选择**：

| 券商 | 适合 | API | 模拟盘 | 费用 |
|------|------|-----|--------|------|
| **Alpaca** | 美股 | REST + WebSocket | ✅ 免费 | 免费 |
| **Futu OpenD** | 美股/港股/A股 | Python SDK | ✅ 模拟 | 免费 |
| **vnpy + CTP** | A 股期货 | 事件驱动 | ✅ simnow | 免费 |
| **东方财富 EMQuant** | A 股 | Python SDK | ⚠️ 需申请 | 免费 |

**建议先用 Alpaca**（美股模拟盘，零门槛注册）：

```toml
# 新增依赖
alpaca-py >= 0.30.0
```

**新增模块**：`src/trading/broker.py`

```python
class BrokerClient:
    """券商 API 抽象层。"""
    
    async def get_account(self) -> Account:
        """账户信息：资金、购买力"""
    
    async def get_positions(self) -> list[Position]:
        """当前持仓"""
    
    async def submit_order(self, order: OrderRequest) -> Order:
        """提交订单（需人工确认）"""
    
    async def get_order_history(self) -> list[Order]:
        """历史订单"""


class AlpacaBroker(BrokerClient):
    """Alpaca 美股实现。"""
    
    def __init__(self):
        self.client = TradingClient(
            api_key=os.environ["ALPACA_API_KEY"],
            secret_key=os.environ["ALPACA_SECRET_KEY"],
            paper=True,  # 模拟盘！
        )


@dataclass
class OrderRequest:
    ticker: str
    side: str          # "buy" | "sell"
    quantity: int
    order_type: str    # "market" | "limit" | "stop_loss"
    limit_price: float | None = None
    stop_price: float | None = None
    
    # 安全字段
    requires_confirmation: bool = True  # 默认需要人工确认
    signal_source: str = ""             # 来自哪个信号
    ai_reasoning: str = ""              # AI 的推理过程
```

---

### Step 6：风控模块（1-2 天）

**新增模块**：`src/trading/risk.py`

```python
@dataclass
class RiskConfig:
    max_position_pct: float = 0.1       # 单只股票最大仓位 10%
    max_daily_loss_pct: float = 0.02    # 单日最大亏损 2%
    max_open_positions: int = 10        # 最多同时持有 10 只
    stop_loss_pct: float = 0.05         # 默认止损 5%
    take_profit_pct: float = 0.15       # 默认止盈 15%
    min_confidence: float = 0.7         # 最低信号置信度
    cooldown_hours: int = 24            # 同一标的交易冷却期


class RiskManager:
    """风险控制引擎 — 任何订单执行前必须通过风控检查。"""
    
    def check_order(self, order: OrderRequest, account: Account, 
                    positions: list[Position]) -> RiskCheckResult:
        """检查订单是否符合风控规则。
        
        Returns:
            RiskCheckResult with approved/rejected status and reasons
        """
    
    def calculate_position_size(self, ticker: str, signal: CompositeSignal,
                                account: Account) -> int:
        """根据风控规则计算建议仓位大小。"""
    
    def check_daily_loss(self, account: Account) -> bool:
        """检查是否触及单日亏损上限。"""
```

---

### Step 7：前端交易面板升级（3-4 天）

**参考 TradingView 风格，用纯 SVG 实现**：

#### 7a. 大盘概览卡片
```
┌─────────────────────────────────────┐
│ 📊 大盘指数                         │
│                                     │
│  上证  3,250.32  ▲ +1.2%           │
│  深证  10,830.15 ▼ -0.3%           │
│  纳指  18,520.40 ▲ +2.1%           │
│  标普  5,890.20  ▲ +1.5%           │
└─────────────────────────────────────┘
```

#### 7b. 迷你 K 线图（纯 SVG）
```
┌─────────────────────────────────────┐
│ $NVDA  $1,230.50  ▲ +3.2%         │
│                                     │
│   ┃  ┃ ╻                           │
│  ╻┃  ┃╻┃ ╻                         │
│  ┃┃╻╻┃┃┃ ┃╻                        │  ← 30日蜡烛图
│  ┃┃┃┃┃┃┃╻┃┃                        │
│  ╹╹┃┃╹╹┃┃╹┃                        │
│    ╹╹  ╹╹ ╹                        │
│  ── MA5  ── MA20  ── BOLL          │
└─────────────────────────────────────┘
```

#### 7c. 持仓管理面板
```
┌─────────────────────────────────────┐
│ 💼 模拟持仓  总值: $100,000         │
│                                     │
│  NVDA   10股  $12,305  ▲ +5.2%    │
│  AAPL   20股  $4,120   ▼ -1.1%    │
│  TSLA   5股   $2,850   ▲ +3.8%    │
│                                     │
│  今日盈亏: +$320 (+0.32%)           │
└─────────────────────────────────────┘
```

#### 7d. AI 交易建议（需确认执行）
```
┌─────────────────────────────────────┐
│ 🤖 AI 建议                          │
│                                     │
│  买入 NVDA × 5股 @ $1,230          │
│  情绪: 看涨 92%  技术: 看涨 78%     │
│  止损: $1,168  止盈: $1,415         │
│  理由: "NVIDIA GTC 大会发布新 GPU,  │
│         多家券商上调目标价..."       │
│                                     │
│  [✅ 确认执行]  [❌ 忽略]  [✏️ 修改] │
└─────────────────────────────────────┘
```

---

### Step 8：回测模块（2-3 天）

**新增模块**：`src/trading/backtest.py`

```python
class Backtester:
    """简易回测引擎 — 用历史数据验证策略。"""
    
    async def run(self, strategy: CompositeStrategy, 
                  tickers: list[str],
                  start_date: str, end_date: str,
                  initial_capital: float = 100000) -> BacktestResult:
        """执行回测。"""
    
    def generate_report(self, result: BacktestResult) -> str:
        """生成回测报告 Markdown。"""


@dataclass
class BacktestResult:
    total_return: float         # 总收益率
    annual_return: float        # 年化收益
    max_drawdown: float         # 最大回撤
    sharpe_ratio: float         # 夏普比率
    win_rate: float             # 胜率
    total_trades: int
    profit_trades: int
    loss_trades: int
    trade_history: list[dict]   # 每笔交易记录
```

---

## 五、数据库变更

```sql
-- 持仓记录
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    avg_price   REAL NOT NULL,
    current_price REAL,
    pnl         REAL,
    pnl_pct     REAL,
    opened_at   TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 订单记录
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL,        -- buy/sell
    quantity    INTEGER NOT NULL,
    order_type  TEXT NOT NULL,        -- market/limit/stop
    price       REAL,
    status      TEXT NOT NULL,        -- pending/confirmed/filled/rejected
    signal_id   TEXT,                 -- 关联的信号 ID
    ai_reasoning TEXT,
    created_at  TEXT NOT NULL,
    filled_at   TEXT,
    broker_order_id TEXT
);

-- 行情缓存（避免频繁请求）
CREATE TABLE IF NOT EXISTS quotes_cache (
    ticker      TEXT PRIMARY KEY,
    price       REAL,
    change_pct  REAL,
    volume      INTEGER,
    updated_at  TEXT NOT NULL
);
```

## 六、新增 API 端点

```
GET  /api/trading/market-overview       # 大盘指数
GET  /api/trading/quote/{ticker}        # 实时报价
GET  /api/trading/kline/{ticker}        # K 线数据
GET  /api/trading/indicators/{ticker}   # 技术指标

GET  /api/trading/positions             # 当前持仓
GET  /api/trading/orders                # 订单历史
POST /api/trading/orders                # 提交订单（需确认）
POST /api/trading/orders/{id}/confirm   # 确认执行
POST /api/trading/orders/{id}/cancel    # 取消订单

GET  /api/trading/risk/config           # 风控配置
PUT  /api/trading/risk/config           # 更新风控规则
GET  /api/trading/risk/check            # 风控检查

POST /api/trading/backtest              # 运行回测
GET  /api/trading/backtest/{id}         # 回测结果
```

## 七、新增依赖

```toml
[project.dependencies]
# Phase 2 新增
akshare = ">=1.18.0"        # A 股/基金数据（免费）
yfinance = ">=0.2.0"        # 美股/港股行情
alpaca-py = ">=0.30.0"      # Alpaca 模拟盘券商 API
```

## 八、实施时间线

| 阶段 | 内容 | 预计时间 | 风险 |
|------|------|---------|------|
| Step 1 | LLM 情绪分析升级 | 2-3 天 | 低 — 已有 AI 客户端 |
| Step 2 | A 股 + 基金数据 | 2-3 天 | 中 — 依赖外部 API 稳定性 |
| Step 3 | 技术指标引擎 | 1-2 天 | 低 — 纯算法 |
| Step 4 | 综合信号引擎 | 2 天 | 低 |
| Step 5 | Alpaca 模拟盘 | 3-4 天 | 中 — 需注册 Alpaca 账号 |
| Step 6 | 风控模块 | 1-2 天 | 低 |
| Step 7 | 前端面板升级 | 3-4 天 | 中 — UI 工作量大 |
| Step 8 | 回测模块 | 2-3 天 | 低 |
| **合计** | | **16-23 天** | |

## 九、安全原则

1. **模拟盘优先** — Phase 2 全程使用 Alpaca Paper Trading，不涉及真钱
2. **人工确认** — 所有订单默认 `requires_confirmation=True`
3. **风控兜底** — 任何订单必须通过 RiskManager 检查
4. **API Key 安全** — 只存环境变量名，不存实际密钥
5. **止损保护** — 每笔交易必须设置止损
6. **日亏上限** — 超过 2% 自动停止当日交易

## 十、参考项目

| 项目 | 方向 | 参考价值 |
|------|------|---------|
| [TradingAgents](https://github.com/tauricresearch/tradingagents) | 多 Agent 协作交易 | 架构设计、Agent 编排 |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 金融 LLM | 情绪分析 Prompt、微调方法 |
| [LLM-Enhanced-Trading](https://github.com/Ronitt272/LLM-Enhanced-Trading) | LLM 实时交易 | 端到端流程参考 |
| [AKShare](https://github.com/akfamily/akshare) | A 股数据 | 数据接口 |
| [vnpy](https://github.com/vnpy/vnpy) | 量化平台 | 事件驱动架构、CTP 对接 |
| [Alpaca Python SDK](https://github.com/alpacahq/alpaca-py) | 美股券商 API | 模拟盘交易 |
| [lightweight-charts](https://github.com/nickvdyck/lightweight-charts) | K 线图组件 | 前端图表参考 |
