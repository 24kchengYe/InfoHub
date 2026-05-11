const API_BASE = "/api";

export interface ItemMetadata {
  title_en?: string;
  title_zh?: string;
  detailed_summary_en?: string;
  detailed_summary_zh?: string;
  background_en?: string;
  background_zh?: string;
  community_discussion_en?: string;
  community_discussion_zh?: string;
  sources?: string[];
  image_url?: string;
  [key: string]: any;
}

export interface Item {
  id: string;
  source_type: string;
  title: string;
  url: string;
  content?: string;
  author?: string;
  published_at: string;
  fetched_at: string;
  ai_score?: number;
  ai_reason?: string;
  ai_summary?: string;
  ai_tags: string[];
  domain?: string;
  is_read: boolean;
  is_starred: boolean;
  metadata?: ItemMetadata;
}

export interface DomainCategory {
  key: string;
  label_zh: string;
  label_en: string;
}

export interface Domain {
  slug: string;
  name: string;
  icon: string;
  color: string;
  enabled: number;
  categories?: DomainCategory[];
}

export interface Stats {
  total: number;
  unread: number;
  starred: number;
  by_source: Record<string, number>;
  avg_score?: number;
  pipeline_runs: number;
}

export interface DailySummary {
  date: string;
  domain: string;
  language: string;
  markdown: string;
  item_count: number;
}

export async function fetchItems(params: {
  domain?: string;
  category?: string;
  source_type?: string;
  min_score?: number;
  search?: string;
  is_read?: boolean;
  sort?: string;
  page?: number;
  per_page?: number;
}): Promise<{ data: Item[]; meta: { total: number; page: number; per_page: number } }> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") searchParams.set(k, String(v));
  });
  const res = await fetch(`${API_BASE}/items?${searchParams}`);
  return res.json();
}

export async function fetchDomains(): Promise<{ data: Domain[] }> {
  const res = await fetch(`${API_BASE}/domains`);
  return res.json();
}

export async function fetchStats(): Promise<{ data: Stats }> {
  const res = await fetch(`${API_BASE}/stats/overview`);
  return res.json();
}

export async function fetchDailySummary(params?: {
  date?: string;
  domain?: string;
  language?: string;
}): Promise<{ data: DailySummary | null }> {
  const searchParams = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) searchParams.set(k, v);
    });
  }
  const res = await fetch(`${API_BASE}/daily/latest?${searchParams}`);
  if (!res.ok) return { data: null };
  try {
    const json = await res.json();
    return { data: json?.data ?? null };
  } catch {
    return { data: null };
  }
}

export async function fetchDailyList(limit: number = 30): Promise<{ data: { date: string; domain: string; language: string; item_count: number }[] }> {
  const res = await fetch(`${API_BASE}/daily?limit=${limit}`);
  if (!res.ok) return { data: [] };
  try {
    const json = await res.json();
    return { data: json?.data ?? [] };
  } catch {
    return { data: [] };
  }
}

export async function markItemRead(id: string, is_read: boolean): Promise<void> {
  await fetch(`${API_BASE}/items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_read }),
  });
}

export async function triggerPipeline(domain: string = "all", hours: number = 24): Promise<any> {
  const res = await fetch(`${API_BASE}/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, hours }),
  });
  return res.json();
}

export async function fetchDailyTrend(params?: {
  domain?: string;
  days?: number;
}): Promise<{ data: { day: string; count: number }[] }> {
  const searchParams = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) searchParams.set(k, String(v));
    });
  }
  const res = await fetch(`${API_BASE}/stats/daily-trend?${searchParams}`);
  return res.json();
}

export async function fetchScoreDistribution(params?: {
  domain?: string;
  days?: number;
}): Promise<{ data: { bucket: string; count: number }[] }> {
  const searchParams = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) searchParams.set(k, String(v));
    });
  }
  const res = await fetch(`${API_BASE}/stats/score-distribution?${searchParams}`);
  return res.json();
}

export async function fetchSourceBreakdown(params?: {
  domain?: string;
  days?: number;
}): Promise<{ data: { source_type: string; source_name: string; count: number }[] }> {
  const searchParams = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) searchParams.set(k, String(v));
    });
  }
  const res = await fetch(`${API_BASE}/stats/source-breakdown?${searchParams}`);
  return res.json();
}

export interface TradingOverview {
  market_mood: string;
  sentiment: { bullish: number; bearish: number; neutral: number; total: number };
  signals: { ticker: string; direction: string; strength: number; sentiment_count: number; avg_confidence: number; reasons: string[] }[];
  total_items: number;
}

export interface SentimentData {
  summary: { total: number; bullish: number; bearish: number; neutral: number };
  top_tickers: { ticker: string; bullish: number; bearish: number; neutral: number; total: number }[];
  items: { id: string; title: string; title_en?: string; url: string; sentiment: string; confidence: number; tickers: string[]; score: number; published_at: string }[];
}

export async function fetchTradingOverview(): Promise<{ data: TradingOverview }> {
  const res = await fetch(`${API_BASE}/trading/overview`);
  return res.json();
}

export async function fetchSentimentData(): Promise<{ data: SentimentData }> {
  const res = await fetch(`${API_BASE}/trading/sentiment`);
  return res.json();
}

export async function fetchMarketOverview(): Promise<{ data: { code: string; name: string; price: number; change: number; change_pct: number }[] }> {
  const res = await fetch(`${API_BASE}/trading/market-overview`);
  return res.json();
}

export async function fetchCompositeSignals(): Promise<{ data: any[] }> {
  const res = await fetch(`${API_BASE}/trading/composite-signals`);
  return res.json();
}

export async function fetchKline(ticker: string, count: number = 30): Promise<{ data: { date: string; open: number; high: number; low: number; close: number; volume: number }[] }> {
  const res = await fetch(`${API_BASE}/trading/kline/${ticker}?count=${count}`);
  return res.json();
}

export async function fetchBrokerStatus(): Promise<{ data: { configured: boolean; broker: string; mode: string; message: string } }> {
  const res = await fetch(`${API_BASE}/trading/broker/status`);
  return res.json();
}

export async function fetchTradingAccount(): Promise<{ data: any }> {
  const res = await fetch(`${API_BASE}/trading/account`);
  return res.json();
}

export async function fetchTradingPositions(): Promise<{ data: any[] }> {
  const res = await fetch(`${API_BASE}/trading/positions`);
  return res.json();
}

export async function fetchBacktest(ticker: string, days: number = 365): Promise<{ data: any }> {
  const res = await fetch(`${API_BASE}/trading/backtest/${ticker}?days=${days}`);
  return res.json();
}

export async function fetchAutoTraderStatus(): Promise<{ data: any }> {
  const res = await fetch(`${API_BASE}/trading/auto/status`);
  return res.json();
}

export async function toggleAutoTrader(body: {
  enabled: boolean;
  mode?: string;
  min_confidence?: number;
  max_positions?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
}): Promise<{ data: any }> {
  const res = await fetch(`${API_BASE}/trading/auto/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function runAutoTraderOnce(): Promise<{ data: any }> {
  const res = await fetch(`${API_BASE}/trading/auto/run-once`, { method: "POST" });
  return res.json();
}

export async function fetchOrderHistory(limit: number = 50): Promise<{ data: any[] }> {
  const res = await fetch(`${API_BASE}/trading/orders?limit=${limit}`);
  return res.json();
}
