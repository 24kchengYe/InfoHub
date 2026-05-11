# InfoHub — 本地多领域信息聚合系统

## 项目概述

类 AIHOT 的本地信息聚合系统，覆盖 AI + 金融投资等多领域，带 Web Dashboard + MCP Server。

- **后端**: FastAPI + Uvicorn + aiosqlite，端口 18899
- **前端**: Next.js 16 + Tailwind CSS，端口 3000（rewrites 代理 API 到 18899）
- **数据库**: SQLite `data/infohub.db`
- **AI 模型**: DeepSeek V3 via OpenRouter (`deepseek/deepseek-chat-v3-0324`)
- **MCP**: `infohub`，已注册到 Claude Code，6 个工具
- **开机自启**: `scripts/start-infohub.vbs` 在 Windows 启动文件夹

## 启动方式

```bash
# 后端
ALL_PROXY= PYTHONIOENCODING=utf-8 uv run python -m src.main

# 前端
cd frontend && npx next start -p 3000

# 或用脚本
scripts/start-infohub.bat
```

## 目录结构

```
src/
├── main.py              # 入口
├── models.py            # Pydantic 数据模型
├── database.py          # SQLite CRUD（模块级函数 + Database 类 wrapper）
├── config.py            # 配置加载（data/config.json + data/domains/*.json）
├── pipeline.py          # Pipeline（可中断，逐条评分即时存 DB）
├── scheduler.py         # APScheduler 定时抓取
├── search.py            # 搜索模块
├── scrapers/            # RSS/HN/Reddit/GitHub/Telegram/Twitter
├── ai/
│   ├── analyzer.py      # AI 评分 + 双语翻译 + 分类（score_item → 即时 upsert）
│   ├── enricher.py      # 增强（联网搜索 + 深度分析，仅高分条目）
│   ├── prompts.py       # 所有 LLM prompt
│   ├── client.py        # 多 provider AI 客户端
│   └── summarizer.py    # 日报生成
├── api/
│   ├── app.py           # FastAPI 工厂 + lifespan
│   ├── routes_items.py  # GET /api/items（支持 category 参数）
│   ├── routes_domains.py # GET /api/domains（返回 categories）
│   ├── routes_pipeline.py # POST run/cancel, GET status/runs
│   ├── routes_sources.py # 信源 CRUD
│   ├── routes_daily.py
│   └── routes_stats.py
└── mcp/server.py        # 6 个 MCP 工具（stdio）

frontend/                # Next.js 项目
├── src/app/page.tsx     # 完整 Dashboard 单页
├── src/app/globals.css  # 暗色/浅色主题
├── src/lib/api.ts       # API 客户端
└── src/lib/utils.ts     # 工具函数

data/
├── config.json          # 全局配置
├── infohub.db           # SQLite
└── domains/             # 领域 JSON（含 categories）
    ├── ai.json
    └── finance.json
```

## Pipeline 流程

```
fetch(逐信源串行,可中断) → dedup → store raw
  → score(逐条,即时存DB,生成title_zh/summary_zh/reason_zh/category)
  → filter(阈值) → enrich(逐条,联网+深度分析) → store enriched → daily summary
```

## 已知坑

1. `ALL_PROXY=socks5` 导致 httpx 报错 → Pipeline/MCP 入口处 `os.environ.pop("ALL_PROXY")`
2. 端口 18888 被 svchost 占 → 用 18899
3. Google Fonts 被墙 → layout.tsx 不引入 next/font/google
4. Anthropic 没有 RSS feed（404），Microsoft AI RSS 403
5. Qwen 122B 评分太慢 → 用 DeepSeek V3
6. `enricher._enrich_item()` 和 `analyzer._analyze_item()` 是私有方法但 Pipeline 直接调用
7. aiosqlite `_connect` 用 async context manager class 而非 async function
8. Pipeline 评分后**必须** `upsert_items(scored, stage="scored")` 存回 DB

## 待做功能（TODO.md 有完整列表）

1. 语言切换验证（确保 title_zh 正确生成）
2. URL 去重优化（跨 feed 同 URL 重复）
3. 图片预览（scraper 提取 og:image）
4. 搜索高亮
5. 日报修复（链接+双语）
6. 统计图表
7. 金融交易模块
