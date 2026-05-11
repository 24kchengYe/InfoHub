# InfoHub 待做功能清单

## 优先级 P0（核心体验）

### 1. Pipeline 可中断 + 断点续传
- 后端加 `POST /api/pipeline/cancel` 接口
- Pipeline 运行时检查 cancel 信号（用 asyncio.Event）
- 已抓取的数据保留，下次从断点继续
- 前端加"停止"按钮（刷新按钮旁边）

### 2. 多天补抓
- 记录上次成功抓取的时间到数据库（new table `system_config`）
- 刷新时自动计算 `hours = now - last_fetch_time`
- 如果超过 24h，分天抓取避免一次请求太多
- 显示"距离上次抓取已过 X 天，正在补抓..."

### 3. 进度显示更详细
- Pipeline 的 `_fetch_all_sources` 改为逐源报告进度
- 后端 status 增加 `sources_total` 和 `sources_done` 字段
- 前端显示：`人工智能 · 抓取中（5/13 信源）· 已获取 45 条`
- 评分阶段显示：`AI评分中（12/45 条）`

### 4. 实时显示新数据
- Pipeline 每存一批（upsert_items 后）发一个事件
- 前端 pollPipeline 时同时轮询 `/api/items` 刷新卡片列表
- 或用 SSE (Server-Sent Events) 推送实时更新

### 5. 前端分类 Tab 渲染
- 后端 `/api/domains` 已返回 categories 列表
- 后端 `/api/items?category=model` 已支持
- 前端需要在领域 pill 下方渲染分类 sub-tabs
- 选中领域后显示该领域的分类：模型/产品/行业/论文/技巧
- 选中分类后筛选 items

## 优先级 P1（完善体验）

### 6. 语言切换完善
- 确保所有 enriched 条目都有 title_zh/summary_zh/reason_zh
- 未翻译的条目显示原文+翻译标记
- 分类 Tab 标签跟随语言切换（模型/Models）

### 7. 去重优化
- 当前按 item ID 去重，但同一 URL 可能有不同 ID
- 在 upsert_items 时加 URL 去重逻辑
- 或在 _merge_duplicates 中同时按 URL 和标题相似度去重

### 8. 图片预览
- RSS scraper 提取 `<media:thumbnail>`, `<enclosure>`, `og:image`
- Reddit scraper 提取 `preview.images[0].source.url`
- 存入 metadata.image_url
- 前端已有 `item.metadata?.image_url` 的渲染逻辑

### 9. 搜索增强
- 中英文双语搜索已支持（搜 metadata JSON）
- 加搜索结果高亮
- 加搜索历史记录（localStorage）

## 优先级 P2（扩展功能）

### 10. 金融交易模块预留
- 新建 `src/trading/` 目录
- 读取金融领域 items 做情绪分析
- 通过 MCP 让 Claude Code 分析新闻 + 调用券商 API
- 架构：`infohub_query(domain="finance")` → LLM 分析 → 交易信号

### 11. 日报完善
- 日报超链接指向具体条目（不是都指向同一个页面）
- 日报支持中英双语切换
- 日报按分类分组显示

### 12. 统计图表
- 按天的抓取量趋势图
- 按来源的分布饼图
- 评分分布直方图

## 技术架构备忘

```
D:/InfoHub/
├── src/
│   ├── main.py              # 入口
│   ├── models.py            # 数据模型
│   ├── database.py          # SQLite (DB_PATH = D:/InfoHub/data/infohub.db)
│   ├── config.py            # 配置加载
│   ├── pipeline.py          # Pipeline (on_progress callback)
│   ├── scheduler.py         # APScheduler
│   ├── scrapers/            # RSS/HN/Reddit/GitHub/Telegram/Twitter
│   ├── ai/                  # analyzer.py(评分+翻译), enricher.py(增强), prompts.py
│   ├── api/                 # FastAPI routes
│   │   ├── app.py
│   │   ├── routes_items.py  # 支持 category 参数
│   │   ├── routes_domains.py # 返回 categories
│   │   ├── routes_pipeline.py # 进度 status 含 phase/fetched/scored/filtered
│   │   ├── routes_sources.py # 信源 CRUD
│   │   ├── routes_daily.py
│   │   └── routes_stats.py
│   └── mcp/server.py        # 6 个 MCP 工具
├── frontend/                # Next.js 16 + Tailwind
│   └── src/app/page.tsx     # 单页 Dashboard
├── data/
│   ├── config.json          # 全局配置 (DeepSeek V3, port 18899)
│   ├── infohub.db           # SQLite
│   └── domains/             # 领域 JSON (含 categories)
│       ├── ai.json
│       └── finance.json
└── scripts/                 # 启动脚本 + 开机自启
```

## 关键修复历史（避免重复踩坑）

1. Pipeline 评分后必须 upsert_items(scored, stage="scored") 存回 DB
2. ALL_PROXY=socks5:// 会导致 httpx 报错，Pipeline 和 MCP 入口处 pop 掉
3. 端口 18888 被 svchost 占用，改用 18899
4. Google Fonts 被墙，layout.tsx 不要引入 next/font/google
5. Anthropic 没有公开 RSS feed
6. metadata 中的中文翻译字段：title_zh, detailed_summary_zh, reason_zh, category
