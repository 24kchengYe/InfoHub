"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  Search,
  RefreshCw,
  Moon,
  Sun,
  ExternalLink,
  Eye,
  EyeOff,
  Inbox,
  Menu,
  X,
  Star,
  List,
  Newspaper,
  ChevronDown,
  Trash2,
  TrendingUp,
} from "lucide-react";
import {
  fetchItems,
  fetchDomains,
  fetchStats,
  fetchDailySummary,
  fetchDailyList,
  fetchDailyTrend,
  fetchScoreDistribution,
  fetchSourceBreakdown,
  fetchTradingOverview,
  fetchSentimentData,
  fetchMarketOverview,
  fetchCompositeSignals,
  fetchKline,
  fetchBrokerStatus,
  fetchTradingAccount,
  fetchTradingPositions,
  fetchAutoTraderStatus,
  toggleAutoTrader,
  runAutoTraderOnce,
  fetchOrderHistory,
  markItemRead,
  triggerPipeline,
  type Item,
  type Domain,
  type Stats,
  type DailySummary,
  type TradingOverview,
  type SentimentData,
} from "@/lib/api";
import { cn, formatTime, scoreStyle, sourceIcon, groupByDate, type Lang } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const PER_PAGE = 20;

type View = "featured" | "all" | "daily" | "sources" | "stats" | "trading";

const DOMAIN_NAMES: Record<string, { zh: string; en: string }> = {
  ai: { zh: "人工智能", en: "AI" },
  finance: { zh: "金融财经", en: "Finance" },
};

type NavItem = {
  key: View;
  label: { zh: string; en: string };
  icon: string;
};

const NAV_ITEMS: NavItem[] = [
  { key: "featured", label: { zh: "精选", en: "Featured" }, icon: "⚡" },
  { key: "all", label: { zh: "全部动态", en: "All Updates" }, icon: "📋" },
  { key: "daily", label: { zh: "日报", en: "Daily" }, icon: "📰" },
  { key: "trading", label: { zh: "交易信号", en: "Trading" }, icon: "📈" },
  { key: "stats", label: { zh: "统计", en: "Stats" }, icon: "📊" },
  { key: "sources", label: { zh: "信源管理", en: "Sources" }, icon: "📡" },
];

// ---------------------------------------------------------------------------
// i18n strings
// ---------------------------------------------------------------------------
const I18N = {
  zh: {
    searchPlaceholder: "搜索文章...",
    searchBtn: "搜索",
    refreshTitle: "抓取最新资讯",
    themeTitle: "切换主题",
    allDomains: "全部领域",
    allDomainPill: "全部",
    sortScore: "按评分",
    sortDate: "按时间",
    timeAll: "全部",
    timeToday: "今天",
    time3d: "3天",
    timeWeek: "7天",
    domains: "领域",
    statTotal: "总条目",
    statUnread: "未读",
    statStarred: "收藏",
    statAvgScore: "均分",
    statPipeline: "管线",
    emptyDaily: "暂无日报数据",
    emptyItems: "暂无数据，点击刷新按钮抓取最新资讯",
    loadedAll: (n: number) => `— 已加载全部 ${n} 条 —`,
    source: "原文",
    markRead: "已读",
    markUnread: "未读",
    articles: "篇",
    itemsCount: "条",
    heroSubtitle: "AI 自动挑选的高价值内容",
    allSubtitle: "所有领域的最新动态",
    dailySubtitle: "每日精华摘要",
    recommendReason: "推荐理由：",
    statsSubtitle: "数据概览与趋势分析",
    tradingSubtitle: "金融市场情绪与交易信号",
    about: "关于",
    changelog: "更新日志",
    feedback: "反馈",
  },
  en: {
    searchPlaceholder: "Search articles...",
    searchBtn: "Search",
    refreshTitle: "Fetch latest",
    themeTitle: "Toggle theme",
    allDomains: "All Domains",
    allDomainPill: "All",
    sortScore: "By Score",
    sortDate: "By Date",
    timeAll: "All",
    timeToday: "Today",
    time3d: "3 Days",
    timeWeek: "7 Days",
    domains: "Domains",
    statTotal: "Total",
    statUnread: "Unread",
    statStarred: "Starred",
    statAvgScore: "Avg Score",
    statPipeline: "Pipeline",
    emptyDaily: "No daily report available",
    emptyItems: "No data yet. Click refresh to fetch the latest.",
    loadedAll: (n: number) => `— All ${n} items loaded —`,
    source: "Source",
    markRead: "Read",
    markUnread: "Unread",
    articles: "articles",
    itemsCount: "items",
    heroSubtitle: "High-value content curated by AI",
    allSubtitle: "Latest updates across all domains",
    dailySubtitle: "Daily highlights summary",
    recommendReason: "Recommendation: ",
    statsSubtitle: "Data overview and trend analysis",
    tradingSubtitle: "Market sentiment and trading signals",
    about: "About",
    changelog: "Changelog",
    feedback: "Feedback",
  },
} as const;

// ---------------------------------------------------------------------------
// Tiny markdown renderer (for daily report)
// ---------------------------------------------------------------------------
function renderMarkdown(md: string): string {
  return md
    .replace(
      /^### (.+)$/gm,
      '<h3>$1</h3>',
    )
    .replace(
      /^## (.+)$/gm,
      '<h2>$1</h2>',
    )
    .replace(
      /^# (.+)$/gm,
      '<h1>$1</h1>',
    )
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>',
    )
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/\n{2,}/g, '<div class="spacer"></div>')
    .replace(/\n/g, "<br/>");
}

// ---------------------------------------------------------------------------
// Date label with year, e.g. "2026年5月9日" or "May 9, 2026"
// ---------------------------------------------------------------------------
function shortDateLabel(dateStr: string, lang: Lang): string {
  const d = new Date(dateStr);
  if (lang === "zh") {
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
  }
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

// ---------------------------------------------------------------------------
// Highlight — wraps text and highlights matching search terms
// ---------------------------------------------------------------------------
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query || !text) return <>{text}</>;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark key={i} className="bg-yellow-300/40 text-inherit rounded-sm px-0.5">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

// ===========================================================================
// Root component
// ===========================================================================
export default function Dashboard() {
  // ---- data state ----
  const [items, setItems] = useState<Item[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [dailySummary, setDailySummary] = useState<DailySummary | null>(null);
  const [dailyList, setDailyList] = useState<{ date: string; domain: string; language: string; item_count: number }[]>([]);
  const [selectedDailyDate, setSelectedDailyDate] = useState<string>("");

  // ---- UI state ----
  const [currentView, setCurrentView] = useState<View>("featured");
  const [currentDomain, setCurrentDomain] = useState<string | null>(null);
  const [currentCategory, setCurrentCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<"score" | "date">("score");
  const [days, setDays] = useState<number | null>(null);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("light");
  const [lang, setLang] = useState<Lang>("zh");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const [showSearchHistory, setShowSearchHistory] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const t = I18N[lang];

  const sentinelRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // ---- debounce search ----
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // ---- theme persistence ----
  useEffect(() => {
    const saved = localStorage.getItem("infohub-theme");
    if (saved === "dark") {
      setTheme("dark");
      document.documentElement.classList.remove("light");
    } else {
      // Default to light theme
      setTheme("light");
      document.documentElement.classList.add("light");
    }
  }, []);

  // ---- language persistence ----
  useEffect(() => {
    const savedLang = localStorage.getItem("infohub-lang");
    if (savedLang === "en" || savedLang === "zh") {
      setLang(savedLang);
    }
  }, []);

  // ---- search history persistence ----
  useEffect(() => {
    const saved = localStorage.getItem("infohub-search-history");
    if (saved) {
      try { setSearchHistory(JSON.parse(saved)); } catch {}
    }
  }, []);

  const addSearchHistory = useCallback((q: string) => {
    if (!q.trim()) return;
    setSearchHistory(prev => {
      const next = [q, ...prev.filter(h => h !== q)].slice(0, 10);
      localStorage.setItem("infohub-search-history", JSON.stringify(next));
      return next;
    });
  }, []);

  const toggleLang = useCallback(() => {
    setLang((prev) => {
      const next = prev === "zh" ? "en" : "zh";
      localStorage.setItem("infohub-lang", next);
      return next;
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("light", next === "light");
      localStorage.setItem("infohub-theme", next);
      return next;
    });
  }, []);

  // ---- boot: load domains + stats ----
  useEffect(() => {
    fetchDomains()
      .then((r) => { setDomains(r.data || []); })
      .catch(() => {});
    fetchStats()
      .then((r) => { setStats(r.data || null); })
      .catch(() => {});
  }, []);

  // ---- load items ----
  const loadItems = useCallback(
    async (pageNum: number, append: boolean) => {
      if (currentView === "daily" || currentView === "sources" || currentView === "stats" || currentView === "trading") return;
      setLoading(true);
      try {
        const params: Record<string, string | number> = {
          page: pageNum,
          per_page: PER_PAGE,
          sort: sort === "score" ? "ai_score" : "published_at",
        };
        if (currentView === "featured") params.min_score = 7;
        if (days) params.days = days;
        if (dateFrom) params.date_from = dateFrom;
        if (dateTo) params.date_to = dateTo;
        if (currentDomain) params.domain = currentDomain;
        if (currentCategory) params.category = currentCategory;
        if (debouncedSearch) params.search = debouncedSearch;

        const res = await fetchItems(params);
        const newItems = res.data || [];
        setTotal(res.meta?.total || 0);
        setItems((prev) => (append ? [...prev, ...newItems] : newItems));
      } catch (err) {
        console.error("[InfoHub] loadItems error:", err);
        if (!append) setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [currentView, currentDomain, currentCategory, sort, days, dateFrom, dateTo, debouncedSearch],
  );

  // ---- reset on filter change ----
  useEffect(() => {
    setPage(1);
    if (currentView === "sources" || currentView === "stats" || currentView === "trading") {
      setLoading(false);
    } else if (currentView === "daily") {
      setLoading(true);
      Promise.all([
        fetchDailyList(30),
      ])
        .then(async ([list]) => {
          // Deduplicate list first — prefer "all" domain, then matching language
          const dateMap = new Map<string, { date: string; domain: string; language: string; item_count: number }>();
          for (const d of (list.data || [])) {
            const existing = dateMap.get(d.date);
            if (!existing
              || (d.domain === "all" && existing.domain !== "all")
              || (d.domain === existing.domain && d.language === lang && existing.language !== lang)) {
              dateMap.set(d.date, d);
            }
          }
          const deduped = Array.from(dateMap.values()).sort((a, b) => b.date.localeCompare(a.date));
          setDailyList(deduped);
          if (deduped.length > 0) {
            const latestDate = selectedDailyDate || deduped[0].date;
            if (!selectedDailyDate) setSelectedDailyDate(latestDate);
            await loadDailyByDate(latestDate);
          } else {
            setDailySummary(null);
          }
        })
        .catch(() => { setDailySummary(null); setDailyList([]); })
        .finally(() => setLoading(false));
    } else {
      loadItems(1, false);
    }
    scrollRef.current?.scrollTo(0, 0);
  }, [currentView, currentDomain, currentCategory, sort, days, dateFrom, dateTo, debouncedSearch, loadItems, lang]);

  // ---- infinite scroll ----
  useEffect(() => {
    if (currentView === "daily" || currentView === "sources" || currentView === "stats" || currentView === "trading") return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && items.length < total) {
          const nextPage = page + 1;
          setPage(nextPage);
          loadItems(nextPage, true);
        }
      },
      { root: scrollRef.current, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [currentView, loading, items.length, total, page, loadItems]);

  // ---- pipeline progress polling ----
  const pollPipelineRef = useRef(false);
  const pollPipeline = useCallback(async () => {
    if (pollPipelineRef.current) return;
    pollPipelineRef.current = true;
    setRefreshing(true);

    for (let i = 0; i < 200; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const res = await fetch("/api/pipeline/status");
        const json = await res.json();
        const s = json.data;
        if (!s || s.status === "idle") { setPipelineStatus(null); break; }
        if (s.status === "completed") {
          setPipelineStatus(
            lang === "zh"
              ? `✅ 完成！已抓取 ${s.fetched || 0} 条，评分 ${s.scored || 0} 条，精选 ${s.filtered || 0} 条`
              : `✅ Done! Fetched ${s.fetched || 0}, scored ${s.scored || 0}, selected ${s.filtered || 0}`
          );
          setPage(1);
          loadItems(1, false);
          fetchStats().then((sr) => setStats(sr.data || null)).catch(() => {});
          setTimeout(() => setPipelineStatus(null), 5000);
          break;
        }
        if (s.status === "cancelled") {
          setPipelineStatus(lang === "zh" ? "⏹ 已取消" : "⏹ Cancelled");
          setPage(1);
          loadItems(1, false);
          fetchStats().then((sr) => setStats(sr.data || null)).catch(() => {});
          setTimeout(() => setPipelineStatus(null), 3000);
          break;
        }
        if (s.status === "error") {
          setPipelineStatus(lang === "zh" ? `❌ 出错: ${s.error || ""}` : `❌ Error: ${s.error || ""}`);
          setTimeout(() => setPipelineStatus(null), 5000);
          break;
        }
        // Running progress — detailed phase display
        const domain = s.current_domain || "";
        const done = s.domains_done || 0;
        const dtotal = s.domains_total || 1;

        let detail = "";
        if (s.phase === "fetching") {
          detail = lang === "zh"
            ? `抓取中（${s.sources_done || 0}/${s.sources_total || "?"} 信源）· ${s.current_source || ""} · 已获取 ${s.fetched || 0} 条`
            : `Fetching (${s.sources_done || 0}/${s.sources_total || "?"} sources) · ${s.current_source || ""} · ${s.fetched || 0} items`;
        } else if (s.phase === "scoring") {
          detail = lang === "zh"
            ? `AI评分中（${s.score_current || 0}/${s.score_total || 0} 条）`
            : `AI Scoring (${s.score_current || 0}/${s.score_total || 0})`;
        } else if (s.phase === "filtering") {
          detail = lang === "zh" ? `筛选中 · 已精选 ${s.filtered || 0} 条` : `Filtering · ${s.filtered || 0} selected`;
        } else if (s.phase === "enriching") {
          detail = lang === "zh"
            ? `增强中（${s.enrich_current || 0}/${s.enrich_total || 0} 条）`
            : `Enriching (${s.enrich_current || 0}/${s.enrich_total || 0})`;
        } else {
          const phases: Record<string, string> = lang === "zh"
            ? { starting: "启动中" }
            : { starting: "Starting" };
          detail = phases[s.phase] || s.phase;
        }

        const hoursNote = (s.hours && s.hours > 24)
          ? (lang === "zh" ? ` · 补抓 ${Math.ceil(s.hours / 24)} 天` : ` · Backfilling ${Math.ceil(s.hours / 24)} days`)
          : "";

        setPipelineStatus(
          lang === "zh"
            ? `${domain}（${done + 1}/${dtotal}）· ${detail}${hoursNote}`
            : `${domain} (${done + 1}/${dtotal}) · ${detail}${hoursNote}`
        );

        // Refresh items periodically so new data appears in real time
        if (i % 3 === 0 && s.status === "running") {
          loadItems(1, false);
          fetchStats().then((sr) => setStats(sr.data || null)).catch(() => {});
        }
      } catch { /* continue */ }
    }
    setRefreshing(false);
    pollPipelineRef.current = false;
  }, [lang, loadItems]);

  // ---- auto-detect running pipeline on page load ----
  useEffect(() => {
    fetch("/api/pipeline/status")
      .then((r) => r.json())
      .then((json) => {
        if (json.data && json.data.status === "running") {
          pollPipeline();
        }
      })
      .catch(() => {});
  }, [pollPipeline]);

  // ---- handlers ----
  const handleRefresh = async () => {
    setPipelineStatus(lang === "zh" ? "正在启动抓取..." : "Starting pipeline...");
    try {
      await triggerPipeline("all");
      pollPipeline();
    } catch {
      setPipelineStatus(lang === "zh" ? "❌ 启动失败" : "❌ Failed to start");
      setTimeout(() => setPipelineStatus(null), 3000);
    }
  };

  const handleCancel = async () => {
    try {
      await fetch("/api/pipeline/cancel", { method: "POST" });
      // Let pollPipeline detect "cancelled" and clean up naturally.
      // But also reset the ref so the next refresh can start a new poll.
      pollPipelineRef.current = false;
      setRefreshing(false);
      setPipelineStatus(lang === "zh" ? "⏹ 已取消" : "⏹ Cancelled");
      setTimeout(() => setPipelineStatus(null), 3000);
    } catch { /* ignore */ }
  };

  const handleClearData = async () => {
    try {
      await fetch("/api/data/clear", { method: "DELETE" });
      setItems([]);
      setTotal(0);
      setStats(null);
      setDailySummary(null);
      setDailyList([]);
      setSelectedDailyDate("");
      setShowClearConfirm(false);
      fetchStats().then((r) => setStats(r.data || null)).catch(() => {});
    } catch { /* ignore */ }
  };

  const loadDailyByDate = async (date: string) => {
    setLoading(true);
    try {
      // No domain selected → try "all" first; domain selected → try that first then "all"
      const domains = currentDomain ? [currentDomain, "all"] : ["all", "ai", "finance"];
      let found = false;
      for (const domain of domains) {
        const res = await fetch(`/api/daily/${date}?domain=${domain}&language=${lang}`);
        if (res.ok) {
          const json = await res.json();
          if (json.data) { setDailySummary(json.data); found = true; break; }
        }
      }
      if (!found) setDailySummary(null);
    } catch { setDailySummary(null); }
    setLoading(false);
  };

  const handleMarkRead = async (item: Item) => {
    const next = !item.is_read;
    await markItemRead(item.id, next);
    setItems((prev) =>
      prev.map((i) => (i.id === item.id ? { ...i, is_read: next } : i)),
    );
  };

  const handleViewChange = (v: View) => {
    setCurrentView(v);
    // Featured defaults to score sort; All defaults to date sort
    if (v === "featured") setSort("score");
    else if (v === "all") setSort("date");
    setMobileSidebarOpen(false);
  };

  const handleDomainChange = (slug: string | null) => {
    setCurrentDomain(slug);
    setCurrentCategory(null);
    setMobileSidebarOpen(false);
  };

  // ---- hero text ----
  const heroTitle =
    NAV_ITEMS.find((n) => n.key === currentView)?.label[lang] || "";

  const heroSubtitle =
    currentView === "featured"
      ? t.heroSubtitle
      : currentView === "all"
        ? t.allSubtitle
        : currentView === "trading"
          ? t.tradingSubtitle
          : currentView === "stats"
            ? t.statsSubtitle
            : t.dailySubtitle;

  // ===========================================================================
  // Render
  // ===========================================================================
  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-base)]">
      {/* ---- Mobile overlay backdrop ---- */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* ================================================================
          SIDEBAR — always 160px, always showing text (AIHOT style)
          ================================================================ */}
      <aside className="hidden md:flex flex-col shrink-0 w-[160px] border-r border-[var(--border-subtle)] bg-[var(--bg-surface)] z-50">
        <SidebarContent
          currentView={currentView}
          currentDomain={currentDomain}
          domains={domains}
          stats={stats}
          lang={lang}
          theme={theme}
          onViewChange={handleViewChange}
          onDomainChange={handleDomainChange}
          onToggleTheme={toggleTheme}
          onToggleLang={toggleLang}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          onClearData={() => setShowClearConfirm(true)}
        />
      </aside>

      {/* Mobile sidebar (slide-in) */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-[260px] bg-[var(--bg-surface)] border-r border-[var(--border-subtle)] flex flex-col transition-transform duration-300 md:hidden",
          mobileSidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 h-14 border-b border-[var(--border-subtle)]">
          <span className="text-lg font-bold text-[var(--text-primary)] tracking-wider">
            <span className="opacity-60">Info</span>Hub
          </span>
          <button
            onClick={() => setMobileSidebarOpen(false)}
            className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]"
          >
            <X size={18} />
          </button>
        </div>
        <SidebarContent
          currentView={currentView}
          currentDomain={currentDomain}
          domains={domains}
          stats={stats}
          lang={lang}
          theme={theme}
          onViewChange={handleViewChange}
          onDomainChange={handleDomainChange}
          onToggleTheme={toggleTheme}
          onToggleLang={toggleLang}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          onClearData={() => setShowClearConfirm(true)}
        />
      </aside>

      {/* ================================================================
          MAIN CONTENT AREA
          ================================================================ */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* ---------- Scrollable content ---------- */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto"
        >
          <div className="max-w-[860px] mx-auto px-6 py-8">
            {/* Mobile hamburger row */}
            <div className="md:hidden flex items-center justify-between mb-4">
              <button
                className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]"
                onClick={() => setMobileSidebarOpen(true)}
              >
                <Menu size={20} />
              </button>
              <span className="text-lg font-bold text-[var(--text-primary)] tracking-wider">
                <span className="opacity-60">Info</span>Hub
              </span>
              <div className="w-8" />
            </div>

            {/* ---- Hero heading ---- */}
            <div className="mb-6">
              <h1 className="text-2xl font-bold text-[var(--text-primary)]">
                {heroTitle}
              </h1>
              <p className="mt-1 text-sm text-[var(--text-tertiary)]">
                {heroSubtitle}
              </p>
            </div>

            {/* ---- Pipeline progress banner ---- */}
            {pipelineStatus && (
              <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5">
                {refreshing && (
                  <div className="w-4 h-4 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin shrink-0" />
                )}
                <span className="text-sm text-emerald-600 dark:text-emerald-400 flex-1">
                  {pipelineStatus}
                </span>
                {refreshing && (
                  <button
                    onClick={handleCancel}
                    className="p-1.5 rounded-lg text-red-400 hover:text-red-500 hover:bg-red-500/10 shrink-0 transition-colors"
                    title={lang === "zh" ? "停止" : "Stop"}
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
            )}

            {/* ---- Clear data confirmation modal (3-step) ---- */}
            {showClearConfirm && (
              <ClearDataModal
                lang={lang}
                onConfirm={() => { handleClearData(); setShowClearConfirm(false); }}
                onCancel={() => setShowClearConfirm(false)}
              />
            )}

            {/* ---- Category tabs + Search row (only for item views) ---- */}
            {(currentView === "featured" || currentView === "all") && (
            <>
            <div className="flex items-center gap-3 mb-6 flex-wrap">
              {/* Domain pills */}
              <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
                <DomainPill
                  active={currentDomain === null}
                  onClick={() => handleDomainChange(null)}
                >
                  {t.allDomainPill}
                </DomainPill>
                {domains.map((d) => (
                  <DomainPill
                    key={d.slug}
                    active={currentDomain === d.slug}
                    onClick={() => handleDomainChange(d.slug)}
                  >
                    {d.icon} {DOMAIN_NAMES[d.slug]?.[lang] || d.name}
                  </DomainPill>
                ))}

                {/* Time filter */}
                <div className="flex items-center rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-0.5 ml-1">
                  {([null, 1, 3, 7] as (number | null)[]).map((d) => (
                    <SortButton key={d ?? "all"} active={days === d && !dateFrom} onClick={() => { setDays(d); setDateFrom(""); setDateTo(""); setShowDatePicker(false); }}>
                      {d === null ? t.timeAll : d === 1 ? t.timeToday : d === 3 ? t.time3d : t.timeWeek}
                    </SortButton>
                  ))}
                  <div className="relative">
                    <SortButton active={!!dateFrom} onClick={() => setShowDatePicker(!showDatePicker)}>
                      {dateFrom ? `${dateFrom}${dateTo && dateTo !== dateFrom ? `~${dateTo}` : ""}` : (lang === "zh" ? "选日期" : "Date")}
                    </SortButton>
                    {showDatePicker && (
                      <div className="absolute top-full right-0 mt-1 p-3 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg shadow-lg z-50 flex flex-col gap-2 min-w-[220px]">
                        <label className="text-xs text-[var(--text-secondary)]">{lang === "zh" ? "开始日期" : "From"}</label>
                        <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setDays(null); }} className="px-2 py-1 rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-sm text-[var(--text-primary)]" />
                        <label className="text-xs text-[var(--text-secondary)]">{lang === "zh" ? "结束日期" : "To"}</label>
                        <input type="date" value={dateTo || dateFrom} onChange={(e) => setDateTo(e.target.value)} className="px-2 py-1 rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-sm text-[var(--text-primary)]" />
                        <div className="flex gap-2 mt-1">
                          <button onClick={() => { setDateFrom(""); setDateTo(""); setDays(null); setShowDatePicker(false); }} className="flex-1 text-xs px-2 py-1 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">{lang === "zh" ? "清除" : "Clear"}</button>
                          <button onClick={() => setShowDatePicker(false)} className="flex-1 text-xs px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-500">{lang === "zh" ? "确定" : "OK"}</button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Sort toggle */}
                <div className="flex items-center rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] p-0.5 ml-1">
                  <SortButton
                    active={sort === "score"}
                    onClick={() => setSort("score")}
                  >
                    {t.sortScore}
                  </SortButton>
                  <SortButton
                    active={sort === "date"}
                    onClick={() => setSort("date")}
                  >
                    {t.sortDate}
                  </SortButton>
                </div>
              </div>

              {/* Search box + button (AIHOT style) */}
              <div className="relative flex items-center gap-0 shrink-0">
                <div className="flex items-center gap-2 h-9 px-3 rounded-l-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] border-r-0 focus-within:ring-1 focus-within:ring-emerald-500 focus-within:border-emerald-500 transition-all w-[200px]">
                  <Search size={14} className="text-[var(--text-tertiary)] shrink-0" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onFocus={() => setShowSearchHistory(true)}
                    onBlur={() => setTimeout(() => setShowSearchHistory(false), 200)}
                    onKeyDown={(e) => { if (e.key === 'Enter') addSearchHistory(search); }}
                    placeholder={t.searchPlaceholder}
                    className="bg-transparent border-none outline-none text-sm flex-1 text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]"
                  />
                  {search && (
                    <button
                      onClick={() => setSearch("")}
                      className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                <button
                  onClick={() => addSearchHistory(search)}
                  className="h-9 px-4 rounded-r-lg text-sm font-medium text-white bg-[var(--text-primary)] hover:opacity-90 transition-opacity"
                >
                  {t.searchBtn}
                </button>
                {showSearchHistory && searchHistory.length > 0 && !search && (
                  <div className="absolute top-full right-0 mt-1 w-[280px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg shadow-lg z-50 py-1">
                    <div className="flex items-center justify-between px-3 py-1.5">
                      <span className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase">{lang === "zh" ? "搜索历史" : "Recent"}</span>
                      <button
                        onClick={() => { setSearchHistory([]); localStorage.removeItem("infohub-search-history"); }}
                        className="text-[10px] text-[var(--text-tertiary)] hover:text-red-400"
                      >{lang === "zh" ? "清除" : "Clear"}</button>
                    </div>
                    {searchHistory.map((h, i) => (
                      <button
                        key={i}
                        onClick={() => { setSearch(h); setShowSearchHistory(false); }}
                        className="w-full text-left px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] truncate"
                      >{h}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* ---- Category sub-tabs ---- */}
            {(() => {
              const currentDomainObj = domains.find(d => d.slug === currentDomain);
              const categories = currentDomainObj?.categories || [];
              if (categories.length === 0) return null;
              return (
                <div className="flex items-center gap-1.5 mb-6 -mt-3 flex-wrap">
                  <button
                    onClick={() => setCurrentCategory(null)}
                    className={cn(
                      "px-2.5 py-1 rounded-full text-xs transition-colors",
                      !currentCategory
                        ? "bg-[var(--text-tertiary)] text-white"
                        : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
                    )}
                  >
                    {lang === "zh" ? "全部" : "All"}
                  </button>
                  {categories.map(cat => (
                    <button
                      key={cat.key}
                      onClick={() => setCurrentCategory(cat.key)}
                      className={cn(
                        "px-2.5 py-1 rounded-full text-xs transition-colors",
                        currentCategory === cat.key
                          ? "bg-[var(--text-tertiary)] text-white"
                          : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
                      )}
                    >
                      {lang === "zh" ? cat.label_zh : cat.label_en}
                    </button>
                  ))}
                </div>
              );
            })()}
            </>
            )}

            {/* ---- Content ---- */}
            {/* Stats view */}
            {currentView === "stats" && (
              <StatsView lang={lang} currentDomain={currentDomain} stats={stats} />
            )}

            {/* Trading view */}
            {currentView === "trading" && (
              <TradingViewSafe lang={lang} />
            )}

            {/* Sources management view */}
            {currentView === "sources" && (
              <SourcesManager lang={lang} />
            )}

            {/* Daily view — newspaper style with date sidebar */}
            {currentView === "daily" && (
              <div className="flex gap-6">
                {/* Left: date navigation */}
                {dailyList.length > 0 && (
                  <div className="w-[180px] shrink-0 hidden md:block">
                    <div className="sticky top-8 space-y-0.5 max-h-[80vh] overflow-y-auto pr-1">
                      {dailyList.map((dl) => {
                        const date = new Date(dl.date);
                        const month = date.getMonth() + 1;
                        const day = date.getDate();
                        const isActive = (selectedDailyDate || dailyList[0]?.date) === dl.date;
                        return (
                          <button
                            key={`${dl.date}-${dl.domain}`}
                            onClick={() => { setSelectedDailyDate(dl.date); loadDailyByDate(dl.date); }}
                            className={cn(
                              "w-full text-left px-3 py-2 rounded-lg transition-colors",
                              isActive
                                ? "font-medium"
                                : "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]",
                            )}
                            style={isActive ? { backgroundColor: "rgba(5, 150, 105, 0.08)", color: "#059669" } : undefined}
                          >
                            <span className="text-sm font-bold mr-1.5">{month}/{day}</span>
                            <span className="text-xs text-[var(--text-tertiary)]">{dl.item_count}{lang === "zh" ? "篇" : " items"}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Right: daily content */}
                <div className="flex-1 min-w-0">
                  {loading ? (
                    <SkeletonList />
                  ) : dailySummary ? (
                    <DailyReport summary={dailySummary} lang={lang} />
                  ) : (
                    <EmptyState message={t.emptyDaily} />
                  )}
                </div>
              </div>
            )}

            {/* Items view — timeline layout */}
            {currentView !== "daily" && currentView !== "sources" && currentView !== "stats" && currentView !== "trading" && (
              <>
                {loading && items.length === 0 ? (
                  <SkeletonList />
                ) : items.length === 0 ? (
                  <EmptyState message={t.emptyItems} />
                ) : (
                  <>
                    {groupByDate(items, lang).map((group) => {
                      // Derive a short date label from the first item
                      const shortLabel = group.items[0]
                        ? shortDateLabel(group.items[0].published_at, lang)
                        : group.label;

                      return (
                        <div key={group.label} className="mb-4">
                          {/* Date group header */}
                          <div className="flex items-center gap-3 py-3">
                            <span className="text-sm font-semibold text-[var(--text-primary)]">
                              {shortLabel}
                            </span>
                            <div className="flex-1 h-px bg-[var(--border-subtle)]" />
                            <span className="text-xs text-[var(--text-tertiary)]">
                              {group.items.length} {t.itemsCount}
                            </span>
                          </div>

                          {/* Timeline cards */}
                          <div className="space-y-0">
                            {group.items.map((item) => (
                              <TimelineCard
                                key={item.id}
                                item={item}
                                lang={lang}
                                currentView={currentView}
                                onMarkRead={handleMarkRead}
                                searchQuery={debouncedSearch}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                    {/* Sentinel */}
                    <div ref={sentinelRef} className="h-px" />
                    {/* Loading more indicator */}
                    {loading && items.length > 0 && (
                      <div className="flex justify-center py-6">
                        <div className="w-5 h-5 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin" />
                      </div>
                    )}
                    {/* End */}
                    {items.length >= total && items.length > 0 && (
                      <p className="text-center text-xs text-[var(--text-tertiary)] py-6">
                        {t.loadedAll(total)}
                      </p>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ===========================================================================
// SidebarContent (shared between desktop & mobile)
// ===========================================================================
function SidebarContent({
  currentView,
  currentDomain,
  domains,
  stats,
  lang,
  theme,
  onViewChange,
  onDomainChange,
  onToggleTheme,
  onToggleLang,
  onRefresh,
  refreshing,
  onClearData,
}: {
  currentView: View;
  currentDomain: string | null;
  domains: Domain[];
  stats: Stats | null;
  lang: Lang;
  theme: "dark" | "light";
  onViewChange: (v: View) => void;
  onDomainChange: (slug: string | null) => void;
  onToggleTheme: () => void;
  onToggleLang: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  onClearData: () => void;
}) {
  const t = I18N[lang];

  return (
    <>
      {/* Logo */}
      <div className="h-14 shrink-0 flex items-center px-4 border-b border-[var(--border-subtle)]">
        <span className="text-base font-bold text-[var(--text-primary)] tracking-wider">
          <span className="opacity-50">Info</span>
          <span className="text-emerald-600">Hub</span>
        </span>
      </div>

      {/* Navigation */}
      <nav className="py-3 px-2 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const active = currentView === item.key;
          const navLabel = item.label[lang];
          return (
            <button
              key={item.key}
              onClick={() => onViewChange(item.key)}
              className={cn(
                "w-full flex items-center gap-2.5 h-9 px-3 rounded-lg transition-colors text-sm",
                active
                  ? "bg-emerald-50 text-emerald-700 font-medium dark:bg-emerald-900/30 dark:text-emerald-400"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]",
              )}
              style={active ? { backgroundColor: "rgba(5, 150, 105, 0.08)", color: "#059669" } : undefined}
            >
              <span className="text-base leading-none shrink-0">{item.icon}</span>
              <span className="whitespace-nowrap">{navLabel}</span>
            </button>
          );
        })}
      </nav>

      {/* Divider */}
      <div className="mx-3 border-t border-[var(--border-subtle)]" />

      {/* Domains section */}
      <div className="py-3 px-2 space-y-0.5 flex-1 overflow-y-auto">
        <p className="text-[10px] font-semibold text-[var(--text-tertiary)] uppercase tracking-widest px-3 mb-1.5">
          {t.domains}
        </p>
        <button
          onClick={() => onDomainChange(null)}
          className={cn(
            "w-full flex items-center gap-2.5 h-8 px-3 rounded-lg transition-colors text-sm",
            currentDomain === null
              ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] font-medium"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]",
          )}
        >
          <span className="text-base shrink-0 leading-none">🌐</span>
          <span className="whitespace-nowrap">{t.allDomains}</span>
        </button>

        {domains.map((d) => (
          <button
            key={d.slug}
            onClick={() => onDomainChange(d.slug)}
            className={cn(
              "w-full flex items-center gap-2.5 h-8 px-3 rounded-lg transition-colors text-sm",
              currentDomain === d.slug
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] font-medium"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]",
            )}
          >
            <span className="text-base shrink-0 leading-none">{d.icon}</span>
            <span className="whitespace-nowrap">{DOMAIN_NAMES[d.slug]?.[lang] || d.name}</span>
          </button>
        ))}
      </div>

      {/* Stats */}
      {stats && (
        <div className="shrink-0 border-t border-[var(--border-subtle)] px-3 py-2.5 space-y-1">
          <StatRow label={t.statTotal} value={String(stats.total)} />
          <StatRow label={t.statUnread} value={String(stats.unread)} valueColor="#059669" />
          {stats.avg_score != null && (
            <StatRow label={t.statAvgScore} value={stats.avg_score.toFixed(1)} valueColor="var(--score-high)" />
          )}
        </div>
      )}

      {/* Bottom action bar */}
      <div className="shrink-0 border-t border-[var(--border-subtle)] px-3 py-2.5 flex items-center justify-between">
        <button
          onClick={onToggleTheme}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
          title={t.themeTitle}
        >
          {theme === "dark" ? <Moon size={16} /> : <Sun size={16} />}
        </button>
        <button
          onClick={onToggleLang}
          className="px-2 py-1 rounded-md text-xs font-medium text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
        >
          {lang === "zh" ? "EN" : "中文"}
        </button>
        <button
          onClick={onClearData}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
          title={lang === "zh" ? "清空数据" : "Clear data"}
        >
          <Trash2 size={16} />
        </button>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] disabled:opacity-40 transition-colors"
          title={t.refreshTitle}
        >
          <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
        </button>
      </div>
    </>
  );
}

// ===========================================================================
// StatRow
// ===========================================================================
function StatRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-[var(--text-tertiary)]">{label}</span>
      <span
        className="font-mono font-medium"
        style={valueColor ? { color: valueColor } : { color: "var(--text-secondary)" }}
      >
        {value}
      </span>
    </div>
  );
}

// ===========================================================================
// DomainPill (AIHOT capsule style)
// ===========================================================================
function DomainPill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3.5 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all",
        active
          ? "text-white shadow-sm"
          : "bg-[var(--bg-surface)] text-[var(--text-tertiary)] border border-[var(--border-subtle)] hover:text-[var(--text-secondary)] hover:border-[var(--border)]",
      )}
      style={active ? { backgroundColor: "#059669", color: "#ffffff" } : undefined}
    >
      {children}
    </button>
  );
}

// ===========================================================================
// ClearDataModal — 3-step confirmation
// ===========================================================================
function ClearDataModal({ lang, onConfirm, onCancel }: { lang: Lang; onConfirm: () => void; onCancel: () => void }) {
  const [step, setStep] = useState(1);
  const [inputVal, setInputVal] = useState("");
  const confirmText = lang === "zh" ? "确认删除" : "DELETE";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6 max-w-sm mx-4 shadow-2xl">
        {step === 1 && (
          <>
            <h3 className="text-base font-semibold text-red-500 mb-2">
              {lang === "zh" ? "⚠️ 危险操作" : "⚠️ Dangerous Operation"}
            </h3>
            <p className="text-sm text-[var(--text-secondary)] mb-5">
              {lang === "zh"
                ? "将删除所有已抓取的文章、管线记录和日报数据。此操作不可撤销！"
                : "This will delete ALL fetched articles, pipeline runs, and daily reports. This CANNOT be undone!"}
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]">{lang === "zh" ? "取消" : "Cancel"}</button>
              <button onClick={() => setStep(2)} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-500 hover:bg-red-600">{lang === "zh" ? "继续" : "Continue"}</button>
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <h3 className="text-base font-semibold text-red-500 mb-2">
              {lang === "zh" ? "⚠️ 再次确认" : "⚠️ Are you sure?"}
            </h3>
            <p className="text-sm text-[var(--text-secondary)] mb-5">
              {lang === "zh"
                ? "数据删除后无法恢复。确定要继续吗？"
                : "Data cannot be recovered after deletion. Are you sure?"}
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]">{lang === "zh" ? "取消" : "Cancel"}</button>
              <button onClick={() => setStep(3)} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-500 hover:bg-red-600">{lang === "zh" ? "继续" : "Continue"}</button>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <h3 className="text-base font-semibold text-red-500 mb-2">
              {lang === "zh" ? "⚠️ 最终确认" : "⚠️ Final Confirmation"}
            </h3>
            <p className="text-sm text-[var(--text-secondary)] mb-3">
              {lang === "zh"
                ? `请输入「${confirmText}」以确认删除：`
                : `Type "${confirmText}" to confirm:`}
            </p>
            <input
              type="text"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder={confirmText}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-sm text-[var(--text-primary)] mb-4"
            />
            <div className="flex justify-end gap-3">
              <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]">{lang === "zh" ? "取消" : "Cancel"}</button>
              <button
                onClick={onConfirm}
                disabled={inputVal !== confirmText}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-500 hover:bg-red-600 disabled:opacity-30 disabled:cursor-not-allowed"
              >{lang === "zh" ? "确认清空" : "Delete All"}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// SortButton
// ===========================================================================
function SortButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "px-2.5 py-1 rounded-full text-xs transition-colors",
        active
          ? "bg-[var(--bg-surface)] text-[var(--text-primary)] font-medium shadow-sm"
          : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
      )}
    >
      {children}
    </button>
  );
}

// ===========================================================================
// TimelineCard — AIHOT-style timeline layout
// Left: time column with dot
// Right: full card with source, title, summary, tags, reason
// ===========================================================================
function TimelineCard({
  item,
  lang,
  currentView,
  onMarkRead,
  searchQuery,
}: {
  item: Item;
  lang: Lang;
  currentView: View;
  onMarkRead: (item: Item) => void;
  searchQuery?: string;
}) {
  const style = scoreStyle(item.ai_score);
  const t = I18N[lang];

  const displayTitle =
    lang === "zh"
      ? item.metadata?.title_zh || item.title
      : item.metadata?.title_en || item.title;

  const displaySummary =
    lang === "zh"
      ? item.metadata?.detailed_summary_zh || item.ai_summary || ""
      : item.metadata?.detailed_summary_en || item.ai_summary || "";

  // Recommendation reason — bilingual
  const aiReason = lang === "zh"
    ? (item.metadata?.reason_zh || item.metadata?.background_zh || item.ai_reason || "")
    : (item.metadata?.reason_en || item.metadata?.background_en || item.ai_reason || "");

  // Score badge label
  const scoreBadgeLabel = currentView === "featured"
    ? `${lang === "zh" ? "精选" : "Pick"} ${item.ai_score != null ? item.ai_score.toFixed(0) : ""}`
    : item.ai_score != null
      ? item.ai_score.toFixed(1)
      : null;

  // Score badge color
  const scoreBadgeBg = item.ai_score != null && item.ai_score >= 8
    ? "#ef4444"
    : item.ai_score != null && item.ai_score >= 6
      ? "#059669"
      : "#6b7280";

  // Dot color by score
  const dotColor = item.ai_score != null && item.ai_score >= 8
    ? "#ef4444"
    : item.ai_score != null && item.ai_score >= 6
      ? "#059669"
      : "#9ca3af";

  return (
    <div
      className={cn(
        "flex gap-0 group",
        item.is_read && "opacity-50",
      )}
    >
      {/* ---- Time column (AIHOT style: large bold time) ---- */}
      <div className="w-[90px] shrink-0 flex items-start justify-end gap-2.5 pt-6 pr-4">
        <span className="text-lg font-bold font-mono text-[var(--text-primary)] whitespace-nowrap tracking-tight">
          {formatTime(item.published_at)}
        </span>
        <span
          className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
          style={{ backgroundColor: dotColor }}
        />
      </div>

      {/* ---- Card body ---- */}
      <div className="flex-1 min-w-0 border-b border-[var(--border-subtle)] py-5 pr-2 relative">
        {/* Score badge — top right (AIHOT style: ✦ 精选 71) */}
        {scoreBadgeLabel && (
          <span
            className="absolute top-5 right-2 inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold text-white"
            style={{ backgroundColor: scoreBadgeBg }}
          >
            <span>✦</span> {scoreBadgeLabel}
          </span>
        )}

        {/* Source info — icon + name + handle */}
        <div className="flex items-center gap-2 mb-2.5">
          <span className="text-base leading-none">{sourceIcon(item.source_type)}</span>
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {item.source_type}
          </span>
          {item.author && (
            <span className="text-sm text-[var(--text-tertiary)]">
              @{item.author}
            </span>
          )}
        </div>

        {/* Title — clickable link to source */}
        <h3 className="text-[17px] font-bold leading-snug mb-2.5 pr-24">
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--text-primary)] hover:text-[var(--accent)] transition-colors"
          >
            <Highlight text={displayTitle} query={searchQuery || ""} />
          </a>
        </h3>

        {/* Summary — full display, no truncation */}
        {displaySummary && (
          <p className="text-[15px] text-[var(--text-secondary)] leading-relaxed mb-3">
            <Highlight text={displaySummary} query={searchQuery || ""} />
          </p>
        )}

        {/* Image preview */}
        {item.metadata?.image_url && (
          <div className="mb-3 rounded-lg overflow-hidden border border-[var(--border-subtle)] bg-[var(--bg-elevated)] flex items-center justify-center max-h-[240px]">
            <img
              src={item.metadata.image_url}
              alt=""
              loading="lazy"
              className="max-w-full max-h-[240px] object-contain"
              onError={(e) => { (e.target as HTMLImageElement).parentElement!.style.display = 'none'; }}
            />
          </div>
        )}

        {/* Tags */}
        {item.ai_tags && item.ai_tags.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap mb-3">
            {item.ai_tags.map((tag) => (
              <span
                key={tag}
                className="px-2.5 py-1 rounded-full border text-xs"
                style={{
                  borderColor: "var(--border)",
                  color: "var(--text-secondary)",
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* AI Reason — green text with prefix */}
        {aiReason && (
          <p className="text-sm leading-relaxed mt-1" style={{ color: "#059669" }}>
            <span className="font-semibold">{t.recommendReason}</span>
            {aiReason}
          </p>
        )}

        {/* Action buttons — visible on hover */}
        <div className="mt-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onMarkRead(item);
            }}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
          >
            {item.is_read ? (
              <><EyeOff size={12} /> {t.markUnread}</>
            ) : (
              <><Eye size={12} /> {t.markRead}</>
            )}
          </button>
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs hover:bg-[var(--bg-elevated)] transition-colors"
            style={{ color: "#059669" }}
          >
            {t.source} <ExternalLink size={12} />
          </a>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// DailyReport — AIHOT-style newspaper layout
// ===========================================================================
function DailyReport({ summary, lang }: { summary: DailySummary; lang: Lang }) {
  const nums = ["\u3007", "\u4e00", "\u4e8c", "\u4e09", "\u56db", "\u4e94", "\u516d", "\u4e03", "\u516b", "\u4e5d"];
  const toZh = (n: number) => String(n).split("").map(c => nums[parseInt(c)]).join("");
  const weekdays = ["\u65e5", "\u4e00", "\u4e8c", "\u4e09", "\u56db", "\u4e94", "\u516d"];

  const d = new Date(summary.date);
  const dateZh = `${toZh(d.getFullYear())}\u5e74${toZh(d.getMonth() + 1)}\u6708${toZh(d.getDate())}\u65e5\u3000\u661f\u671f${weekdays[d.getDay()]}`;
  const dateEn = d.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });

  return (
    <div>
      {/* Newspaper header */}
      <div className="border-b border-[var(--border)] pb-6 mb-8">
        {/* Top meta line */}
        <div className="flex items-center justify-center gap-3 text-xs tracking-[0.2em] text-[var(--text-tertiary)] mb-6">
          <span className="w-8 h-px bg-[var(--border)] inline-block" />
          <span>VOL.{summary.date.replace(/-/g, ".")}</span>
          <span>&middot;</span>
          <span>{summary.item_count} STORIES</span>
          <span>&middot;</span>
          <span>INFOHUB DAILY</span>
          <span className="w-8 h-px bg-[var(--border)] inline-block" />
        </div>

        {/* Big title */}
        <h1 className="text-center text-5xl font-black tracking-tight mb-4" style={{ fontFamily: "Georgia, 'Noto Serif SC', serif" }}>
          <span className="text-[var(--text-tertiary)]">Info</span>
          <span style={{ color: "#059669" }}>Hub</span>
          <span className="text-[var(--text-primary)] ml-3">{lang === "zh" ? "\u65e5\u62a5" : "Daily"}</span>
        </h1>

        {/* Date + subtitle */}
        <div className="flex items-center justify-between mt-2">
          <p className="text-base text-[var(--text-secondary)]" style={{ fontFamily: lang === "zh" ? "'Noto Serif SC', serif" : "inherit" }}>
            {lang === "zh" ? dateZh : dateEn}
          </p>
          <p className="text-xs tracking-[0.15em] text-[var(--text-tertiary)] uppercase">
            DAILY &middot; {lang === "zh" ? "\u6bcf\u65e5\u66f4\u65b0" : "UPDATED DAILY"}
          </p>
        </div>
      </div>

      {/* Rendered markdown content */}
      <article
        className="daily-prose text-[15px] leading-relaxed"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(summary.markdown) }}
      />
    </div>
  );
}

// ===========================================================================
// EmptyState
// ===========================================================================
function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-[var(--text-tertiary)]">
      <Inbox size={48} strokeWidth={1} className="mb-4 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ===========================================================================
// SkeletonList (shimmer loading) — timeline style
// ===========================================================================
// ===========================================================================
// SourcesManager — view & manage RSS sources per domain
// ===========================================================================
interface DomainSources {
  slug: string;
  name: string;
  icon: string;
  rss: { name: string; url: string; category?: string }[];
  hackernews: Record<string, unknown>;
  reddit: Record<string, unknown>;
  github: unknown[];
}

function SourcesManager({ lang }: { lang: Lang }) {
  const [sources, setSources] = useState<DomainSources[]>([]);
  const [loadingSrc, setLoadingSrc] = useState(true);
  const [addDomain, setAddDomain] = useState("");
  const [addName, setAddName] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [addCategory, setAddCategory] = useState("");

  const loadSources = async () => {
    setLoadingSrc(true);
    try {
      const res = await fetch("/api/sources");
      const json = await res.json();
      setSources(json.data || []);
    } catch { /* ignore */ }
    setLoadingSrc(false);
  };

  useEffect(() => { loadSources(); }, []);

  const handleAdd = async () => {
    if (!addDomain || !addName || !addUrl) return;
    try {
      const res = await fetch("/api/sources/rss/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          domain: addDomain,
          name: addName,
          url: addUrl,
          category: addCategory || null,
        }),
      });
      if (res.ok) {
        setAddName("");
        setAddUrl("");
        setAddCategory("");
        await loadSources();
      }
    } catch { /* ignore */ }
  };

  const handleRemove = async (domain: string, url: string) => {
    try {
      await fetch("/api/sources/rss/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain, url }),
      });
      await loadSources();
    } catch { /* ignore */ }
  };

  if (loadingSrc) return <SkeletonList />;

  return (
    <div className="space-y-8">
      {/* Add RSS form */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
          {lang === "zh" ? "➕ 添加 RSS 信源" : "➕ Add RSS Source"}
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">
              {lang === "zh" ? "所属领域" : "Domain"}
            </label>
            <select
              value={addDomain}
              onChange={(e) => setAddDomain(e.target.value)}
              className="w-full h-9 px-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <option value="">{lang === "zh" ? "选择领域" : "Select domain"}</option>
              {sources.map((d) => (
                <option key={d.slug} value={d.slug}>{d.icon} {DOMAIN_NAMES[d.slug]?.[lang] || d.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">
              {lang === "zh" ? "信源名称" : "Name"}
            </label>
            <input
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              placeholder="e.g. Anthropic Blog"
              className="w-full h-9 px-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] outline-none focus:ring-1 focus:ring-emerald-500 placeholder:text-[var(--text-tertiary)]"
            />
          </div>
          <div>
            <label className="text-xs text-[var(--text-tertiary)] mb-1 block">RSS URL</label>
            <input
              value={addUrl}
              onChange={(e) => setAddUrl(e.target.value)}
              placeholder="https://..."
              className="w-full h-9 px-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] outline-none focus:ring-1 focus:ring-emerald-500 placeholder:text-[var(--text-tertiary)]"
            />
          </div>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="text-xs text-[var(--text-tertiary)] mb-1 block">
                {lang === "zh" ? "分类（可选）" : "Category (optional)"}
              </label>
              <input
                value={addCategory}
                onChange={(e) => setAddCategory(e.target.value)}
                placeholder="e.g. ai-official"
                className="w-full h-9 px-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-sm text-[var(--text-primary)] outline-none focus:ring-1 focus:ring-emerald-500 placeholder:text-[var(--text-tertiary)]"
              />
            </div>
            <button
              onClick={handleAdd}
              disabled={!addDomain || !addName || !addUrl}
              className="h-9 px-4 rounded-lg text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {lang === "zh" ? "添加" : "Add"}
            </button>
          </div>
        </div>
      </div>

      {/* Domain source lists */}
      {sources.map((domain) => (
        <div key={domain.slug} className="space-y-2">
          <h3 className="text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
            <span>{domain.icon}</span> {domain.name}
            <span className="text-xs font-normal text-[var(--text-tertiary)] ml-2">
              {domain.rss.length} RSS
              {domain.reddit && Object.keys(domain.reddit).length > 0 ? " · Reddit" : ""}
              {domain.hackernews && (domain.hackernews as Record<string, boolean>).enabled ? " · HackerNews" : ""}
              {domain.github && (domain.github as unknown[]).length > 0 ? " · GitHub" : ""}
            </span>
          </h3>

          {/* RSS sources */}
          <div className="space-y-0">
            {domain.rss.map((rss) => (
              <div
                key={rss.url}
                className="group flex items-center gap-3 py-2.5 px-3 border-b border-[var(--border-subtle)] hover:bg-[var(--bg-elevated)] rounded transition-colors"
              >
                <span className="text-sm">📡</span>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-[var(--text-primary)]">{rss.name}</span>
                  <span className="text-xs text-[var(--text-tertiary)] ml-2 truncate">{rss.url}</span>
                </div>
                {rss.category && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--border-subtle)] text-[var(--text-tertiary)]">
                    {rss.category}
                  </span>
                )}
                <button
                  onClick={() => handleRemove(domain.slug, rss.url)}
                  className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-500 transition-all text-xs px-2 py-1 rounded hover:bg-red-500/10"
                >
                  {lang === "zh" ? "删除" : "Remove"}
                </button>
              </div>
            ))}
          </div>

          {/* Non-RSS sources (read-only display) */}
          {domain.hackernews && (domain.hackernews as Record<string, boolean>).enabled ? (
            <div className="flex items-center gap-3 py-2 px-3 text-sm text-[var(--text-secondary)]">
              <span>🔶</span> HackerNews
              <span className="text-xs text-[var(--text-tertiary)]">
                top {String((domain.hackernews as Record<string, number>).fetch_top_stories || 30)}
              </span>
            </div>
          ) : null}
          {domain.reddit && (domain.reddit as Record<string, boolean>).enabled ? (
            <div className="flex items-center gap-3 py-2 px-3 text-sm text-[var(--text-secondary)]">
              <span>🔴</span> Reddit
              <span className="text-xs text-[var(--text-tertiary)]">
                {(Array.isArray((domain.reddit as Record<string, unknown>).subreddits) ? ((domain.reddit as Record<string, unknown>).subreddits as unknown[]).length : 0)} subreddits
              </span>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// ===========================================================================
// Activity Heatmap — GitHub contribution style
// ===========================================================================

function ActivityHeatmap({ data, lang }: { data: { day: string; count: number }[]; lang: Lang }) {
  const countMap = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of data) m[d.day] = d.count;
    return m;
  }, [data]);

  // Build grid from first data point to today
  const weeks = useMemo(() => {
    const today = new Date();
    const result: { date: Date; dateStr: string; count: number }[][] = [];
    // Start from first data point (or 4 weeks ago if no data)
    const sortedDays = Object.keys(countMap).sort();
    const firstDay = sortedDays.length > 0 ? new Date(sortedDays[0]) : new Date(today.getTime() - 28 * 86400000);
    const start = new Date(firstDay);
    start.setDate(start.getDate() - start.getDay()); // align to Sunday

    let currentWeek: { date: Date; dateStr: string; count: number }[] = [];
    const d = new Date(start);
    while (d <= today) {
      const ds = d.toISOString().slice(0, 10);
      currentWeek.push({ date: new Date(d), dateStr: ds, count: countMap[ds] || 0 });
      if (currentWeek.length === 7) {
        result.push(currentWeek);
        currentWeek = [];
      }
      d.setDate(d.getDate() + 1);
    }
    if (currentWeek.length > 0) result.push(currentWeek);
    return result;
  }, [countMap]);

  const maxCount = useMemo(() => Math.max(1, ...data.map((d) => d.count)), [data]);
  const totalItems = useMemo(() => data.reduce((s, d) => s + d.count, 0), [data]);

  const getColor = (count: number) => {
    if (count === 0) return "var(--hm-0, #ebedf0)";
    const ratio = count / maxCount;
    if (ratio <= 0.25) return "var(--hm-1, #9be9a8)";
    if (ratio <= 0.5) return "var(--hm-2, #40c463)";
    if (ratio <= 0.75) return "var(--hm-3, #30a14e)";
    return "var(--hm-4, #216e39)";
  };

  // Month labels
  const months = useMemo(() => {
    const labels: { label: string; col: number }[] = [];
    const monthNames = lang === "zh"
      ? ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
      : ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    let lastMonth = -1;
    for (let i = 0; i < weeks.length; i++) {
      const firstDay = weeks[i][0];
      if (firstDay) {
        const m = firstDay.date.getMonth();
        if (m !== lastMonth) {
          labels.push({ label: monthNames[m], col: i });
          lastMonth = m;
        }
      }
    }
    return labels;
  }, [weeks, lang]);

  const CELL = 12;
  const GAP = 2;
  const step = CELL + GAP;

  return (
    <div>
      <div className="text-xs text-[var(--text-tertiary)] mb-3">
        {lang === "zh" ? `过去一年共 ${totalItems} 条内容` : `${totalItems} items in the past year`}
      </div>
      <div className="overflow-x-auto">
        <svg width={weeks.length * step + 30} height={7 * step + 20} className="block">
          {/* Month labels */}
          {months.map((m) => (
            <text key={m.col} x={m.col * step + 30} y={10} className="fill-[var(--text-tertiary)]" fontSize={10}>{m.label}</text>
          ))}
          {/* Cells */}
          {weeks.map((week, wi) =>
            week.map((day, di) => (
              <rect
                key={day.dateStr}
                x={wi * step + 30}
                y={di * step + 16}
                width={CELL}
                height={CELL}
                rx={2}
                fill={getColor(day.count)}
                className="transition-colors hover:stroke-emerald-500 hover:stroke-1"
              >
                <title>{`${day.dateStr}: ${day.count} ${lang === "zh" ? "条" : "items"}`}</title>
              </rect>
            ))
          )}
          {/* Weekday labels */}
          {(lang === "zh" ? ["日","一","二","三","四","五","六"] : ["S","M","T","W","T","F","S"]).map((d, i) =>
            i % 2 === 1 ? (
              <text key={i} x={0} y={i * step + 16 + CELL - 2} className="fill-[var(--text-tertiary)]" fontSize={9}>{d}</text>
            ) : null
          )}
        </svg>
      </div>
      {/* Legend */}
      <div className="flex items-center gap-1 mt-2 text-xs text-[var(--text-tertiary)]">
        <span>{lang === "zh" ? "少" : "Less"}</span>
        {[0, 0.25, 0.5, 0.75, 1].map((r) => (
          <span key={r} style={{ display: "inline-block", width: CELL, height: CELL, borderRadius: 2, backgroundColor: getColor(Math.ceil(r * maxCount)) }} />
        ))}
        <span>{lang === "zh" ? "多" : "More"}</span>
      </div>
    </div>
  );
}

// ===========================================================================
// SVG Chart Components — pure SVG, no external libraries
// ===========================================================================

function MiniBarChart({ data, lang }: { data: { day: string; count: number }[]; lang: Lang }) {
  if (!data.length) return null;
  const maxCount = Math.max(...data.map(d => d.count), 1);
  const barW = Math.max(Math.floor(700 / data.length) - 4, 8);
  const h = 180;
  const paddingBottom = 24;
  const chartH = h - paddingBottom;

  return (
    <svg viewBox={`0 0 ${data.length * (barW + 4)} ${h}`} className="w-full" preserveAspectRatio="xMidYMid meet">
      {data.map((d, i) => {
        const barH = (d.count / maxCount) * (chartH - 20);
        const x = i * (barW + 4);
        const y = chartH - barH;
        return (
          <g key={d.day}>
            <rect x={x} y={y} width={barW} height={barH} rx={3} fill="#059669" opacity={0.8}>
              <title>{d.day}: {d.count}</title>
            </rect>
            <text x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize={10} fill="var(--text-tertiary)">
              {d.count > 0 ? d.count : ""}
            </text>
            {i % Math.max(1, Math.floor(data.length / 7)) === 0 && (
              <text x={x + barW / 2} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--text-tertiary)">
                {d.day.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function ScoreHistogram({ data, lang }: { data: { bucket: string; count: number }[]; lang: Lang }) {
  if (!data.length) return null;
  const maxCount = Math.max(...data.map(d => d.count), 1);
  const colors = ["#6b7280", "#f59e0b", "#3b82f6", "#059669", "#ef4444"];
  const barW = 60;
  const gap = 12;
  const h = 160;
  const chartH = h - 24;
  const totalW = data.length * (barW + gap);

  return (
    <svg viewBox={`0 0 ${totalW} ${h}`} className="w-full" preserveAspectRatio="xMidYMid meet">
      {data.map((d, i) => {
        const barH = Math.max((d.count / maxCount) * (chartH - 20), 2);
        const x = i * (barW + gap);
        const y = chartH - barH;
        return (
          <g key={d.bucket}>
            <rect x={x} y={y} width={barW} height={barH} rx={4} fill={colors[i] || "#6b7280"} opacity={0.85} />
            <text x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize={11} fontWeight="600" fill="var(--text-secondary)">
              {d.count}
            </text>
            <text x={x + barW / 2} y={h - 4} textAnchor="middle" fontSize={10} fill="var(--text-tertiary)">
              {d.bucket}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function SourcePieChart({ data, lang }: { data: Record<string, number>; lang: Lang }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const colors = ["#059669", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];
  const cx = 80, cy = 80, r = 70;
  let cumAngle = -Math.PI / 2;

  return (
    <div className="flex items-center gap-6">
      <svg width={160} height={160} viewBox="0 0 160 160">
        {entries.map(([name, count], i) => {
          const angle = (count / total) * Math.PI * 2;
          const x1 = cx + r * Math.cos(cumAngle);
          const y1 = cy + r * Math.sin(cumAngle);
          cumAngle += angle;
          const x2 = cx + r * Math.cos(cumAngle);
          const y2 = cy + r * Math.sin(cumAngle);
          const largeArc = angle > Math.PI ? 1 : 0;
          return (
            <path
              key={name}
              d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${largeArc},1 ${x2},${y2} Z`}
              fill={colors[i % colors.length]}
              opacity={0.85}
            >
              <title>{name}: {count}</title>
            </path>
          );
        })}
      </svg>
      <div className="space-y-1.5">
        {entries.map(([name, count], i) => (
          <div key={name} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: colors[i % colors.length] }} />
            <span className="text-[var(--text-secondary)]">{name}</span>
            <span className="text-[var(--text-tertiary)] ml-auto">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
// StatsView — fetches trend + score distribution and renders charts
// ===========================================================================
function StatsView({ lang, currentDomain, stats }: { lang: Lang; currentDomain: string | null; stats: Stats | null }) {
  const [trend, setTrend] = useState<{ day: string; count: number }[]>([]);
  const [heatmapData, setHeatmapData] = useState<{ day: string; count: number }[]>([]);
  const [scoreDist, setScoreDist] = useState<{ bucket: string; count: number }[]>([]);
  const [sourceBreakdown, setSourceBreakdown] = useState<{ source_type: string; source_name: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchDailyTrend({ domain: currentDomain || undefined }),
      fetchDailyTrend({ domain: currentDomain || undefined, days: 90 }),
      fetchScoreDistribution({ domain: currentDomain || undefined }),
      fetchSourceBreakdown({ domain: currentDomain || undefined }),
    ])
      .then(([t, h, s, sb]) => {
        setTrend(t.data || []);
        setHeatmapData(h.data || []);
        setScoreDist(s.data || []);
        setSourceBreakdown(sb.data || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [currentDomain]);

  if (loading) return <SkeletonList />;

  const sourceTotal = sourceBreakdown.reduce((s, r) => s + r.count, 0);

  return (
    <div className="space-y-8">
      {/* Activity Heatmap */}
      {heatmapData.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "🟩 内容活跃度" : "🟩 Activity Heatmap"}
          </h3>
          <ActivityHeatmap data={heatmapData} lang={lang} />
        </div>
      )}

      {/* Daily trend */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
          {lang === "zh" ? "📈 每日抓取趋势（近14天）" : "📈 Daily Fetch Trend (14 days)"}
        </h3>
        {trend.length > 0 ? <MiniBarChart data={trend} lang={lang} /> : (
          <p className="text-sm text-[var(--text-tertiary)]">{lang === "zh" ? "暂无数据" : "No data"}</p>
        )}
      </div>

      {/* Source breakdown — per feed */}
      {sourceBreakdown.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? `📡 信源统计（共 ${sourceTotal} 条）` : `📡 Source Breakdown (${sourceTotal} total)`}
          </h3>
          <div className="space-y-2">
            {sourceBreakdown.map((s) => {
              const pct = sourceTotal > 0 ? (s.count / sourceTotal) * 100 : 0;
              const typeIcon: Record<string, string> = { rss: "📡", hackernews: "🔶", reddit: "🔴", github: "🐙", twitter: "🐦", telegram: "✈️" };
              return (
                <div key={`${s.source_type}-${s.source_name}`} className="flex items-center gap-3">
                  <span className="text-sm shrink-0">{typeIcon[s.source_type] || "📰"}</span>
                  <span className="text-sm text-[var(--text-secondary)] w-[180px] truncate shrink-0" title={s.source_name}>
                    {s.source_name}
                  </span>
                  <div className="flex-1 h-5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: "#059669" }}
                    />
                  </div>
                  <span className="text-xs font-mono text-[var(--text-tertiary)] w-12 text-right shrink-0">
                    {s.count}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Source distribution — pie */}
      {stats?.by_source && Object.keys(stats.by_source).length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "📊 来源类型分布" : "📊 Source Type Distribution"}
          </h3>
          <SourcePieChart data={stats.by_source} lang={lang} />
        </div>
      )}

      {/* Score distribution */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
          {lang === "zh" ? "📉 评分分布" : "📉 Score Distribution"}
        </h3>
        {scoreDist.length > 0 ? <ScoreHistogram data={scoreDist} lang={lang} /> : (
          <p className="text-sm text-[var(--text-tertiary)]">{lang === "zh" ? "暂无数据" : "No data"}</p>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// TradingView — market sentiment & trade signals dashboard
// ===========================================================================
function MiniCandleChart({ data }: { data: { date: string; open: number; high: number; low: number; close: number }[] }) {
  if (!data || data.length < 5) return null;

  const w = 320;
  const h = 100;
  const padding = { top: 5, bottom: 5, left: 5, right: 5 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;

  const allPrices = data.flatMap(d => [d.high, d.low]);
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);
  const priceRange = maxPrice - minPrice || 1;

  const barWidth = Math.max(Math.floor(chartW / data.length) - 2, 2);
  const gap = Math.max(Math.floor(chartW / data.length) - barWidth, 1);

  const toY = (price: number) => padding.top + chartH - ((price - minPrice) / priceRange) * chartH;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-[320px]" preserveAspectRatio="xMidYMid meet">
      {data.map((d, i) => {
        const x = padding.left + i * (barWidth + gap);
        const isUp = d.close >= d.open;
        const color = isUp ? "#059669" : "#ef4444";
        const bodyTop = toY(Math.max(d.open, d.close));
        const bodyBot = toY(Math.min(d.open, d.close));
        const bodyH = Math.max(bodyBot - bodyTop, 1);
        const wickX = x + barWidth / 2;

        return (
          <g key={i}>
            <line x1={wickX} y1={toY(d.high)} x2={wickX} y2={toY(d.low)} stroke={color} strokeWidth={1} />
            <rect x={x} y={bodyTop} width={barWidth} height={bodyH} fill={color} rx={0.5}>
              <title>{d.date}: O={d.open} H={d.high} L={d.low} C={d.close}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}

// ===========================================================================
// Error boundary wrapper for TradingView
function TradingViewSafe({ lang }: { lang: Lang }) {
  const [error, setError] = useState<string | null>(null);
  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6">
        <h3 className="text-sm font-semibold text-red-500 mb-2">Trading View Error</h3>
        <p className="text-xs text-[var(--text-secondary)]">{error}</p>
        <button onClick={() => setError(null)} className="mt-3 px-3 py-1 text-xs rounded bg-red-500 text-white">Retry</button>
      </div>
    );
  }
  try {
    return <TradingView lang={lang} />;
  } catch (e: any) {
    setTimeout(() => setError(e?.message || "Unknown error"), 0);
    return null;
  }
}

function TradingView({ lang }: { lang: Lang }) {
  const [overview, setOverview] = useState<TradingOverview | null>(null);
  const [sentimentData, setSentimentData] = useState<SentimentData | null>(null);
  const [indices, setIndices] = useState<any[]>([]);
  const [compositeSignals, setCompositeSignals] = useState<any[]>([]);
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [account, setAccount] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [klineData, setKlineData] = useState<Record<string, any[]>>({});
  const [showStrategyPanel, setShowStrategyPanel] = useState(false);
  const [sentimentWeight, setSentimentWeight] = useState(40);
  const [technicalWeight, setTechnicalWeight] = useState(40);
  const [volumeWeight, setVolumeWeight] = useState(20);
  const [stopLossPct, setStopLossPct] = useState(5);
  const [takeProfitPct, setTakeProfitPct] = useState(15);
  // AutoTrader state
  const [autoStatus, setAutoStatus] = useState<any>(null);
  const [autoToggling, setAutoToggling] = useState(false);
  const [orders, setOrders] = useState<any[]>([]);
  // Trading mode: paper (模拟盘) vs live (实盘)
  const [tradingMode, setTradingMode] = useState<"paper" | "live">("paper");

  // Helper: fetch with timeout (used in effects and callbacks)
  const withTimeout = useCallback(<T,>(promise: Promise<T>, ms: number, fallback: T): Promise<T> =>
    Promise.race([promise, new Promise<T>(resolve => setTimeout(() => resolve(fallback), ms))]), []);

  // Refresh account + positions + autoStatus (called after trades too)
  const klineTickersRef = useRef<string[]>(["NVDA", "AAPL", "TSLA", "AMD", "BABA", "CAT"]);
  useEffect(() => {
    const keys = Object.keys(klineData);
    if (keys.length > 0) klineTickersRef.current = keys;
  }, [klineData]);

  const refreshTradingData = useCallback(() => {
    withTimeout(fetchTradingAccount(), 5000, { data: null }).then(r => setAccount(r.data));
    withTimeout(fetchTradingPositions(), 5000, { data: [] }).then(r => setPositions(r.data || []));
    withTimeout(fetchAutoTraderStatus(), 5000, { data: null }).then(r => setAutoStatus(r.data));
    withTimeout(fetchOrderHistory(20), 5000, { data: [] }).then(r => setOrders(r.data || []));
    // Refresh K-line data every cycle
    Promise.all(klineTickersRef.current.map(t =>
      fetchKline(t, 30).then(res => [t, res.data || []] as const).catch(() => [t, []] as const)
    )).then(results => {
      const map: Record<string, any[]> = {};
      for (const [ticker, data] of results) { if ((data as any[]).length >= 5) map[ticker] = data as any[]; }
      if (Object.keys(map).length > 0) setKlineData(prev => ({ ...prev, ...map }));
    }).catch(() => {});
  }, [withTimeout]);

  useEffect(() => {
    setLoading(true);

    // Load fast APIs first, slow ones (market data) async later
    Promise.all([
      withTimeout(fetchTradingOverview(), 8000, { data: null as any }),
      withTimeout(fetchSentimentData(), 8000, { data: null as any }),
      withTimeout(fetchBrokerStatus(), 5000, { data: { configured: false, broker: "", mode: "", message: "" } }),
      withTimeout(fetchTradingAccount(), 5000, { data: null }),
      withTimeout(fetchTradingPositions(), 5000, { data: [] }),
      withTimeout(fetchAutoTraderStatus(), 5000, { data: null }),
      withTimeout(fetchOrderHistory(20), 5000, { data: [] }),
    ])
      .then(([o, s, bs, a, p, at, ord]) => {
        setOverview(o.data || null);
        setSentimentData(s.data || null);
        setBrokerStatus(bs.data);
        setAccount(a.data);
        setPositions(p.data || []);
        setAutoStatus(at.data);
        setOrders(ord.data || []);
      })
      .finally(() => setLoading(false));

    // Load K-line data immediately for quick display — no dependency on other APIs
    const defaultTickers = ["NVDA", "AAPL", "TSLA", "AMD", "BABA", "CAT"];
    Promise.all(defaultTickers.map(t =>
      fetchKline(t, 30).then(res => [t, res.data || []] as const).catch(() => [t, []] as const)
    )).then(results => {
      const map: Record<string, any[]> = {};
      for (const [ticker, data] of results) { if ((data as any[]).length >= 5) map[ticker] = data as any[]; }
      if (Object.keys(map).length > 0) setKlineData(map);
    }).catch(() => {});

    // Load slow APIs (market data, composite signals) in background — don't block page render
    withTimeout(fetchMarketOverview(), 15000, { data: [] }).then(r => setIndices(r.data || [])).catch(() => {});
    withTimeout(fetchCompositeSignals(), 15000, { data: [] }).then(r => {
      setCompositeSignals(r.data || []);
      // Fetch kline data for composite signal tickers too
      if (r.data && r.data.length > 0) {
        const tickers = r.data.slice(0, 5).map((sig: any) => sig.ticker);
        Promise.all(tickers.map((t: string) =>
          fetchKline(t, 30).then(res => [t, res.data || []]).catch(() => [t, []])
        )).then(results => {
          setKlineData(prev => {
            const map = { ...prev };
            for (const [ticker, data] of results) {
              map[ticker as string] = data as any[];
            }
            return map;
          });
        });
      }
    }).catch(() => {});

    // Auto-refresh trading data every 60s
    const interval = setInterval(refreshTradingData, 60000);
    return () => clearInterval(interval);
  }, [withTimeout, refreshTradingData]);

  const adjustedSignals = useMemo(() => {
    if (!compositeSignals.length) return [];
    const sw = sentimentWeight / 100;
    const tw = technicalWeight / 100;
    const vw = volumeWeight / 100;

    return compositeSignals.map(sig => {
      const volumeScore = sig.news_volume >= 6 ? 1 : sig.news_volume >= 3 ? 0.5 : 0.2;
      const volSigned = sig.sentiment_score > 0 ? volumeScore : -volumeScore;
      const composite = sig.sentiment_score * sw + sig.technical_score * tw + volSigned * vw;

      let direction = "hold";
      let confidence = 0.3;
      if (composite > 0.15) { direction = "long"; confidence = Math.min(Math.abs(composite), 1); }
      else if (composite < -0.15) { direction = "short"; confidence = Math.min(Math.abs(composite), 1); }

      const sl = sig.current_price ? sig.current_price * (1 - stopLossPct / 100) : null;
      const tp = sig.current_price ? sig.current_price * (1 + takeProfitPct / 100) : null;

      return { ...sig, direction, confidence: Math.round(confidence * 100) / 100, stop_loss: sl, take_profit: tp, _composite: composite };
    }).sort((a, b) => b.confidence - a.confidence);
  }, [compositeSignals, sentimentWeight, technicalWeight, volumeWeight, stopLossPct, takeProfitPct]);

  if (loading) return <SkeletonList />;

  const moodColors: Record<string, string> = {
    bullish: "#059669",
    bearish: "#ef4444",
    neutral: "#6b7280",
  };
  const moodLabels: Record<string, Record<string, string>> = {
    bullish: { zh: "看涨", en: "Bullish" },
    bearish: { zh: "看跌", en: "Bearish" },
    neutral: { zh: "中性", en: "Neutral" },
  };
  const dirLabels: Record<string, Record<string, string>> = {
    long: { zh: "做多", en: "Long" },
    short: { zh: "做空", en: "Short" },
    hold: { zh: "观望", en: "Hold" },
  };
  const dirColors: Record<string, string> = {
    long: "#059669",
    short: "#ef4444",
    hold: "#6b7280",
  };

  const mood = overview?.market_mood || "neutral";
  const sentiment = overview?.sentiment || { bullish: 0, bearish: 0, neutral: 0, total: 0 };
  const signals = overview?.signals || [];
  const tickers = sentimentData?.top_tickers || [];
  const sentimentItems = sentimentData?.items || [];

  return (
    <div className="space-y-6">
      {/* ── Paper / Live Mode Tabs ── */}
      <div className="flex items-center gap-1 p-1 rounded-xl bg-[var(--bg-elevated)] w-fit">
        <button
          onClick={() => setTradingMode("paper")}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
            tradingMode === "paper"
              ? "bg-amber-500 text-white shadow-sm"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
          }`}
        >
          {lang === "zh" ? "📋 模拟盘" : "📋 Paper"}
        </button>
        <button
          onClick={() => setTradingMode("live")}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
            tradingMode === "live"
              ? "bg-red-500 text-white shadow-sm"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
          }`}
        >
          {lang === "zh" ? "🔴 实盘" : "🔴 Live"}
        </button>
      </div>

      {/* ══════════ LIVE MODE ══════════ */}
      {tradingMode === "live" && (
        <div className="space-y-6">
          {/* Live mode warning */}
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <span className="text-red-500 text-sm font-bold">{lang === "zh" ? "实盘交易" : "LIVE TRADING"}</span>
            <span className="text-xs text-red-400/70">{lang === "zh" ? "真实资金，所有交易将通过券商执行。请确认已完成配置。" : "Real funds. All trades execute through broker. Confirm configuration."}</span>
          </div>

          {/* Broker Configuration */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
              {lang === "zh" ? "🏦 券商网关配置" : "🏦 Broker Gateway Configuration"}
            </h3>
            <div className="grid grid-cols-2 gap-6">
              {/* CTP Gateway */}
              <div className="bg-[var(--bg-elevated)] rounded-xl p-5 border border-[var(--border-subtle)]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">📊</span>
                    <span className="text-sm font-semibold text-[var(--text-primary)]">CTP</span>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-500/10 text-gray-400">
                    {lang === "zh" ? "未连接" : "Disconnected"}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-tertiary)] mb-3">
                  {lang === "zh" ? "期货交易（上期所/大商所/郑商所/中金所）" : "Futures (SHFE/DCE/CZCE/CFFEX)"}
                </p>
                <div className="space-y-2">
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "经纪商" : "Broker"}</label>
                    <div className="text-xs text-[var(--text-secondary)] bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">
                      {lang === "zh" ? "未配置 — 需要 CTP 账户凭据" : "Not configured — CTP credentials required"}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "行情前置" : "MD Front"}</label>
                    <div className="text-xs text-gray-400 bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">—</div>
                  </div>
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "交易前置" : "TD Front"}</label>
                    <div className="text-xs text-gray-400 bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">—</div>
                  </div>
                </div>
                <button disabled className="mt-3 w-full py-1.5 text-xs rounded bg-gray-500/10 text-gray-400 cursor-not-allowed">
                  {lang === "zh" ? "配置 CTP 网关" : "Configure CTP Gateway"}
                </button>
              </div>

              {/* XTP Gateway */}
              <div className="bg-[var(--bg-elevated)] rounded-xl p-5 border border-[var(--border-subtle)]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">📈</span>
                    <span className="text-sm font-semibold text-[var(--text-primary)]">XTP</span>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-500/10 text-gray-400">
                    {lang === "zh" ? "未连接" : "Disconnected"}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-tertiary)] mb-3">
                  {lang === "zh" ? "A股股票交易（上交所/深交所）" : "A-Share Stocks (SSE/SZSE)"}
                </p>
                <div className="space-y-2">
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "经纪商" : "Broker"}</label>
                    <div className="text-xs text-[var(--text-secondary)] bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">
                      {lang === "zh" ? "未配置 — 需要 XTP 账户凭据" : "Not configured — XTP credentials required"}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "服务器地址" : "Server"}</label>
                    <div className="text-xs text-gray-400 bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">—</div>
                  </div>
                  <div>
                    <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "客户号" : "Client ID"}</label>
                    <div className="text-xs text-gray-400 bg-[var(--bg-surface)] rounded px-2 py-1.5 border border-[var(--border-subtle)]">—</div>
                  </div>
                </div>
                <button disabled className="mt-3 w-full py-1.5 text-xs rounded bg-gray-500/10 text-gray-400 cursor-not-allowed">
                  {lang === "zh" ? "配置 XTP 网关" : "Configure XTP Gateway"}
                </button>
              </div>
            </div>
          </div>

          {/* Multi-Agent Strategy (shared with paper) */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
              {lang === "zh" ? "🤖 Multi-Agent 决策引擎" : "🤖 Multi-Agent Decision Engine"}
            </h3>
            <p className="text-xs text-[var(--text-tertiary)] mb-4">
              {lang === "zh"
                ? "实盘与模拟盘共用同一套 Multi-Agent 决策流程（情绪Agent + 技术Agent + 风控Agent → 决策Agent）。差异仅在执行层：模拟盘用 PaperBroker（SQLite），实盘用 VnpyBroker（CTP/XTP 网关）。"
                : "Live and Paper share the same Multi-Agent decision pipeline. Only the execution layer differs: Paper uses PaperBroker (SQLite), Live uses VnpyBroker (CTP/XTP gateway)."}
            </p>
            <div className="grid grid-cols-4 gap-3">
              {[
                { icon: "🧠", name: lang === "zh" ? "情绪Agent" : "Sentiment", desc: lang === "zh" ? "LLM 分析新闻情绪" : "LLM news sentiment" },
                { icon: "📐", name: lang === "zh" ? "技术Agent" : "Technical", desc: lang === "zh" ? "LLM 解读技术指标" : "LLM indicator analysis" },
                { icon: "🛡️", name: lang === "zh" ? "风控Agent" : "Risk", desc: lang === "zh" ? "LLM 评估组合风险" : "LLM portfolio risk" },
                { icon: "⚖️", name: lang === "zh" ? "决策Agent" : "Decision", desc: lang === "zh" ? "综合三方意见决策" : "Synthesize & decide" },
              ].map(a => (
                <div key={a.name} className="bg-[var(--bg-elevated)] rounded-lg p-3 text-center">
                  <div className="text-xl mb-1">{a.icon}</div>
                  <div className="text-xs font-semibold text-[var(--text-primary)]">{a.name}</div>
                  <div className="text-[9px] text-[var(--text-tertiary)] mt-0.5">{a.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Live Account (placeholder) */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
              {lang === "zh" ? "💰 实盘账户" : "💰 Live Account"}
            </h3>
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: lang === "zh" ? "总权益" : "Equity", value: "—", color: "text-[var(--text-primary)]" },
                { label: lang === "zh" ? "可用资金" : "Available", value: "—", color: "text-[var(--text-primary)]" },
                { label: lang === "zh" ? "持仓市值" : "Positions", value: "—", color: "text-[var(--text-primary)]" },
                { label: lang === "zh" ? "今日盈亏" : "Daily P&L", value: "—", color: "text-gray-400" },
              ].map(item => (
                <div key={item.label} className="bg-[var(--bg-elevated)] rounded-lg p-3">
                  <div className="text-[10px] text-[var(--text-tertiary)]">{item.label}</div>
                  <div className={`text-lg font-bold font-mono ${item.color}`}>{item.value}</div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-[var(--text-tertiary)] mt-3">
              {lang === "zh" ? "连接券商网关后显示实时账户数据" : "Connect broker gateway to show live account data"}
            </p>
          </div>

          {/* Implementation Roadmap */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
              {lang === "zh" ? "🗺️ 实盘接入路线" : "🗺️ Live Trading Roadmap"}
            </h3>
            <div className="space-y-3">
              {[
                { step: "1", title: lang === "zh" ? "安装 vnpy 环境" : "Install vnpy", desc: "pip install vnpy vnpy_ctp vnpy_xtp", done: false },
                { step: "2", title: lang === "zh" ? "申请券商 API 账户" : "Apply for broker API", desc: lang === "zh" ? "SimNow 模拟 / 实盘经纪商" : "SimNow sim / production broker", done: false },
                { step: "3", title: lang === "zh" ? "配置网关凭据" : "Configure gateway", desc: lang === "zh" ? "填写经纪商代码、账号、密码、前置地址" : "Broker code, account, password, front address", done: false },
                { step: "4", title: lang === "zh" ? "实现 VnpyBroker" : "Implement VnpyBroker", desc: lang === "zh" ? "对接 vnpy MainEngine → BrokerProtocol" : "Wrap vnpy MainEngine → BrokerProtocol", done: false },
                { step: "5", title: lang === "zh" ? "SimNow 联调测试" : "SimNow integration test", desc: lang === "zh" ? "模拟环境端到端验证" : "End-to-end in simulation env", done: false },
                { step: "6", title: lang === "zh" ? "实盘上线" : "Go live", desc: lang === "zh" ? "切换到实盘网关，小资金试运行" : "Switch to production, small capital trial", done: false },
              ].map(item => (
                <div key={item.step} className="flex items-start gap-3">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    item.done ? "bg-emerald-500 text-white" : "bg-[var(--bg-elevated)] text-[var(--text-tertiary)] border border-[var(--border-subtle)]"
                  }`}>{item.done ? "✓" : item.step}</div>
                  <div>
                    <div className="text-xs font-semibold text-[var(--text-primary)]">{item.title}</div>
                    <div className="text-[10px] text-[var(--text-tertiary)]">{item.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Market Overview (shared) */}
          {indices.length > 0 && (
            <div className="flex gap-4 overflow-x-auto pb-2">
              {indices.map((idx) => (
                <div key={idx.code} className="shrink-0 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg px-4 py-3 min-w-[160px]">
                  <div className="text-xs text-[var(--text-tertiary)]">{idx.name}</div>
                  <div className="text-lg font-bold font-mono text-[var(--text-primary)]">{idx.price?.toLocaleString()}</div>
                  <div className="text-sm font-mono" style={{ color: (idx.change_pct ?? 0) >= 0 ? "#059669" : "#ef4444" }}>
                    {(idx.change_pct ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(idx.change_pct ?? 0).toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ══════════ PAPER MODE ══════════ */}
      {tradingMode === "paper" && <>

      {/* Paper mode banner */}
      <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
        <span className="text-amber-500 text-sm font-bold">{lang === "zh" ? "模拟盘" : "PAPER TRADING"}</span>
        <span className="text-xs text-amber-400/70">{lang === "zh" ? "虚拟资金 $100,000，不涉及真实交易" : "Virtual $100,000, no real trades"}</span>
      </div>

      {/* ── Strategy Settings (模拟盘) ── */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl mb-6">
        <button
          onClick={() => setShowStrategyPanel(!showStrategyPanel)}
          className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-[var(--text-primary)]"
        >
          <div className="flex items-center gap-2">
            <span>{lang === "zh" ? "⚙️ 策略参数" : "⚙️ Strategy Settings"}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500">{lang === "zh" ? "模拟盘" : "Paper"}</span>
          </div>
          <span className="text-xs text-[var(--text-tertiary)]">{showStrategyPanel ? "▲" : "▼"}</span>
        </button>
        {showStrategyPanel && (
          <div className="px-5 pb-5 space-y-4">
            {/* Weight inputs — slider + manual number input */}
            <div>
              <p className="text-xs text-[var(--text-tertiary)] mb-2">
                {lang === "zh" ? "信号权重（总和需为100%）— 拖动滑块或直接输入数值" : "Signal Weights (must sum to 100%) — drag slider or type value"}
              </p>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "情绪面" : "Sentiment"}</label>
                  <input type="range" min={0} max={100} value={sentimentWeight} onChange={e => {
                    const v = parseInt(e.target.value);
                    setSentimentWeight(v);
                    const remaining = 100 - v;
                    setTechnicalWeight(Math.round(remaining * technicalWeight / (technicalWeight + volumeWeight || 1)));
                    setVolumeWeight(remaining - Math.round(remaining * technicalWeight / (technicalWeight + volumeWeight || 1)));
                  }} className="w-full h-1.5 rounded-full appearance-none bg-[var(--bg-elevated)]" />
                  <div className="flex items-center gap-1 mt-1">
                    <input type="number" min={0} max={100} value={sentimentWeight} onChange={e => {
                      const v = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                      setSentimentWeight(v);
                      const remaining = 100 - v;
                      const oldSum = technicalWeight + volumeWeight || 1;
                      setTechnicalWeight(Math.round(remaining * technicalWeight / oldSum));
                      setVolumeWeight(remaining - Math.round(remaining * technicalWeight / oldSum));
                    }} className="w-12 text-xs font-mono text-center rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-emerald-500 py-0.5" />
                    <span className="text-[10px] text-[var(--text-tertiary)]">%</span>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "技术面" : "Technical"}</label>
                  <input type="range" min={0} max={100} value={technicalWeight} onChange={e => {
                    const v = parseInt(e.target.value);
                    setTechnicalWeight(v);
                    const remaining = 100 - v;
                    setSentimentWeight(Math.round(remaining * sentimentWeight / (sentimentWeight + volumeWeight || 1)));
                    setVolumeWeight(remaining - Math.round(remaining * sentimentWeight / (sentimentWeight + volumeWeight || 1)));
                  }} className="w-full h-1.5 rounded-full appearance-none bg-[var(--bg-elevated)]" />
                  <div className="flex items-center gap-1 mt-1">
                    <input type="number" min={0} max={100} value={technicalWeight} onChange={e => {
                      const v = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                      setTechnicalWeight(v);
                      const remaining = 100 - v;
                      const oldSum = sentimentWeight + volumeWeight || 1;
                      setSentimentWeight(Math.round(remaining * sentimentWeight / oldSum));
                      setVolumeWeight(remaining - Math.round(remaining * sentimentWeight / oldSum));
                    }} className="w-12 text-xs font-mono text-center rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-blue-500 py-0.5" />
                    <span className="text-[10px] text-[var(--text-tertiary)]">%</span>
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "新闻热度" : "Volume"}</label>
                  <input type="range" min={0} max={100} value={volumeWeight} onChange={e => {
                    const v = parseInt(e.target.value);
                    setVolumeWeight(v);
                    const remaining = 100 - v;
                    setSentimentWeight(Math.round(remaining * sentimentWeight / (sentimentWeight + technicalWeight || 1)));
                    setTechnicalWeight(remaining - Math.round(remaining * sentimentWeight / (sentimentWeight + technicalWeight || 1)));
                  }} className="w-full h-1.5 rounded-full appearance-none bg-[var(--bg-elevated)]" />
                  <div className="flex items-center gap-1 mt-1">
                    <input type="number" min={0} max={100} value={volumeWeight} onChange={e => {
                      const v = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                      setVolumeWeight(v);
                      const remaining = 100 - v;
                      const oldSum = sentimentWeight + technicalWeight || 1;
                      setSentimentWeight(Math.round(remaining * sentimentWeight / oldSum));
                      setTechnicalWeight(remaining - Math.round(remaining * sentimentWeight / oldSum));
                    }} className="w-12 text-xs font-mono text-center rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-amber-500 py-0.5" />
                    <span className="text-[10px] text-[var(--text-tertiary)]">%</span>
                  </div>
                </div>
              </div>
              {sentimentWeight + technicalWeight + volumeWeight !== 100 && (
                <p className="text-[10px] text-red-400 mt-1">{lang === "zh" ? `总和 ${sentimentWeight + technicalWeight + volumeWeight}%，需调整为 100%` : `Sum is ${sentimentWeight + technicalWeight + volumeWeight}%, must be 100%`}</p>
              )}
            </div>
            {/* Stop loss / Take profit */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "止损 %" : "Stop Loss %"}</label>
                <div className="flex items-center gap-2">
                  <input type="range" min={1} max={20} value={stopLossPct} onChange={e => setStopLossPct(parseInt(e.target.value))} className="flex-1 h-1.5 rounded-full appearance-none bg-[var(--bg-elevated)]" />
                  <input type="number" min={1} max={20} value={stopLossPct} onChange={e => setStopLossPct(Math.max(1, Math.min(20, parseInt(e.target.value) || 1)))} className="w-12 text-xs font-mono text-center rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-red-400 py-0.5" />
                  <span className="text-[10px] text-[var(--text-tertiary)]">%</span>
                </div>
              </div>
              <div>
                <label className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "止盈 %" : "Take Profit %"}</label>
                <div className="flex items-center gap-2">
                  <input type="range" min={5} max={50} value={takeProfitPct} onChange={e => setTakeProfitPct(parseInt(e.target.value))} className="flex-1 h-1.5 rounded-full appearance-none bg-[var(--bg-elevated)]" />
                  <input type="number" min={5} max={50} value={takeProfitPct} onChange={e => setTakeProfitPct(Math.max(5, Math.min(50, parseInt(e.target.value) || 5)))} className="w-12 text-xs font-mono text-center rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-emerald-400 py-0.5" />
                  <span className="text-[10px] text-[var(--text-tertiary)]">%</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── AutoTrader Control Panel ── */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {lang === "zh" ? "🤖 自动交易引擎" : "🤖 Auto Trading Engine"}
            </h3>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/10 text-amber-500">
              {lang === "zh" ? "模拟盘" : "PAPER"}
            </span>
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
              autoStatus?.enabled
                ? "bg-emerald-500/10 text-emerald-500 animate-pulse"
                : "bg-gray-500/10 text-gray-400"
            }`}>
              {autoStatus?.enabled
                ? (lang === "zh" ? "持续运行中 (5分钟/轮)" : "Running (5min/cycle)")
                : (lang === "zh" ? "已停止" : "Stopped")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              disabled={autoToggling}
              onClick={async () => {
                setAutoToggling(true);
                try {
                  await runAutoTraderOnce();
                  setTimeout(refreshTradingData, 2000);
                } finally { setAutoToggling(false); }
              }}
              className="px-3 py-1 text-xs rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 disabled:opacity-50"
              title={lang === "zh" ? "手动触发一轮：评估信号 → 风控检查 → 下单" : "Manually trigger one cycle: evaluate signals → risk check → place orders"}
            >
              {autoToggling
                ? (lang === "zh" ? "评估中..." : "Evaluating...")
                : (lang === "zh" ? "手动执行一轮" : "Run One Cycle")}
            </button>
            <button
              disabled={autoToggling}
              onClick={async () => {
                setAutoToggling(true);
                try {
                  const next = !autoStatus?.enabled;
                  await toggleAutoTrader({ enabled: next });
                  setTimeout(refreshTradingData, 500);
                } finally { setAutoToggling(false); }
              }}
              className={`px-3 py-1 text-xs rounded font-semibold ${
                autoStatus?.enabled
                  ? "bg-red-500/10 text-red-400 hover:bg-red-500/20"
                  : "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
              } disabled:opacity-50`}
              title={autoStatus?.enabled
                ? (lang === "zh" ? "停止自动循环" : "Stop auto cycle")
                : (lang === "zh" ? "启动后每5分钟自动评估信号并交易" : "Start auto cycle every 5 minutes")}
            >
              {autoStatus?.enabled
                ? (lang === "zh" ? "停止自动" : "Stop Auto")
                : (lang === "zh" ? "启动自动" : "Start Auto")}
            </button>
          </div>
        </div>
        <p className="text-[10px] text-[var(--text-tertiary)] mb-3">
          {autoStatus?.use_multi_agent
            ? (lang === "zh"
              ? "Multi-Agent 模式：情绪Agent + 技术Agent + 风控Agent 独立分析 → 决策Agent 综合研判（4次LLM调用/标的）"
              : "Multi-Agent mode: Sentiment + Technical + Risk agents analyze independently → Decision agent synthesizes (4 LLM calls/ticker)")
            : (lang === "zh"
              ? "公式模式：情绪+技术+热度加权决策（无LLM）。启用 Multi-Agent 需配置 AI 客户端。"
              : "Formula mode: weighted sentiment+technical+volume (no LLM). Multi-Agent requires AI client config.")}
        </p>
        {/* Stats row */}
        <div className="grid grid-cols-4 gap-3 text-center">
          <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
            <div className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "运行周期" : "Cycles"}</div>
            <div className="text-sm font-bold font-mono text-[var(--text-primary)]">{autoStatus?.cycle_count ?? 0}</div>
          </div>
          <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
            <div className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "持仓数" : "Positions"}</div>
            <div className="text-sm font-bold font-mono text-[var(--text-primary)]">{autoStatus?.open_positions ?? positions.length}</div>
          </div>
          <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
            <div className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "最低置信度" : "Min Conf."}</div>
            <div className="text-sm font-bold font-mono text-blue-400">{((autoStatus?.config?.min_confidence ?? 0.6) * 100).toFixed(0)}%</div>
          </div>
          <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
            <div className="text-[10px] text-[var(--text-tertiary)]">{lang === "zh" ? "决策记录" : "Decisions"}</div>
            <div className="text-sm font-bold font-mono text-[var(--text-primary)]">{autoStatus?.recent_decisions ?? 0}</div>
          </div>
        </div>
        {/* Recent trade log */}
        {autoStatus?.recent_log && autoStatus.recent_log.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-1.5">{lang === "zh" ? "最近交易决策" : "Recent Decisions"}</div>
            <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
              {autoStatus.recent_log.slice(0, 10).map((d: any, i: number) => (
                <div key={i} className="border-b border-[var(--border-subtle)] last:border-0 pb-1.5">
                  <div className="flex items-center gap-2 text-xs py-1">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      d.action === "buy" ? "bg-emerald-500" :
                      d.action === "sell" ? "bg-red-500" :
                      d.action === "rejected" ? "bg-amber-500" : "bg-gray-400"
                    }`} />
                    <span className="font-mono font-bold text-[var(--text-primary)] w-12">{d.ticker}</span>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                      d.action === "buy" ? "bg-emerald-500/10 text-emerald-500" :
                      d.action === "sell" ? "bg-red-500/10 text-red-500" :
                      d.action === "rejected" ? "bg-amber-500/10 text-amber-500" :
                      "bg-gray-500/10 text-gray-400"
                    }`}>
                      {d.action === "buy" ? (lang === "zh" ? "买入" : "BUY") :
                       d.action === "sell" ? (lang === "zh" ? "卖出" : "SELL") :
                       d.action === "rejected" ? (lang === "zh" ? "拒绝" : "REJ") :
                       (lang === "zh" ? "跳过" : "SKIP")}
                    </span>
                    {d.quantity > 0 && <span className="font-mono text-[var(--text-secondary)]">{d.quantity}股</span>}
                    {d.price && <span className="font-mono text-[var(--text-secondary)]">@${d.price.toFixed(2)}</span>}
                    <span className="text-[var(--text-tertiary)] truncate flex-1">{d.reason}</span>
                  </div>
                  {/* Agent opinions (Multi-Agent mode) */}
                  {d.agent_opinions?.agents && (
                    <div className="ml-4 mt-1 grid grid-cols-3 gap-1.5">
                      {(["sentiment", "technical", "risk"] as const).map(agentKey => {
                        const ag = d.agent_opinions.agents[agentKey];
                        if (!ag) return null;
                        const dirColor = ag.direction === "bullish" ? "text-emerald-500" :
                          ag.direction === "bearish" ? "text-red-500" : "text-gray-400";
                        return (
                          <div key={agentKey} className="bg-[var(--bg-elevated)] rounded px-2 py-1">
                            <div className="flex items-center gap-1">
                              <span className="text-[9px] text-[var(--text-tertiary)] uppercase">{agentKey}</span>
                              <span className={`text-[9px] font-bold ${dirColor}`}>{ag.direction}</span>
                              <span className="text-[9px] text-[var(--text-tertiary)]">{((ag.confidence ?? 0) * 100).toFixed(0)}%</span>
                            </div>
                            <div className="text-[9px] text-[var(--text-tertiary)] line-clamp-1 mt-0.5">{ag.reasoning}</div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {/* Order history */}
        {orders.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] text-[var(--text-tertiary)] mb-1.5">{lang === "zh" ? "订单历史" : "Order History"}</div>
            <div className="space-y-1 max-h-[160px] overflow-y-auto">
              {orders.slice(0, 10).map((o: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs py-1 border-b border-[var(--border-subtle)] last:border-0">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    o.status === "filled" ? "bg-emerald-500" :
                    o.status === "rejected" ? "bg-red-500" : "bg-amber-500"
                  }`} />
                  <span className="font-mono font-bold text-[var(--text-primary)] w-12">{o.ticker}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    o.side === "buy" ? "bg-emerald-500/10 text-emerald-500" : "bg-red-500/10 text-red-500"
                  }`}>{o.side === "buy" ? "BUY" : "SELL"}</span>
                  <span className="font-mono text-[var(--text-secondary)]">{o.quantity}</span>
                  {o.filled_price && <span className="font-mono text-[var(--text-secondary)]">@${o.filled_price.toFixed(2)}</span>}
                  <span className={`text-[10px] ${o.status === "filled" ? "text-emerald-400" : "text-red-400"}`}>{o.status}</span>
                  <span className="text-[var(--text-tertiary)] text-[10px] ml-auto">{o.created_at?.slice(5, 16)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Market Overview Bar ── */}
      {indices.length > 0 && (
        <div className="flex gap-4 overflow-x-auto pb-2">
          {indices.map((idx) => (
            <div
              key={idx.code}
              className="shrink-0 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg px-4 py-3 min-w-[160px]"
            >
              <div className="text-xs text-[var(--text-tertiary)]">{idx.name}</div>
              <div className="text-lg font-bold font-mono text-[var(--text-primary)]">
                {idx.price?.toLocaleString()}
              </div>
              <div
                className="text-sm font-mono"
                style={{ color: (idx.change_pct ?? 0) >= 0 ? "#059669" : "#ef4444" }}
              >
                {(idx.change_pct ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(idx.change_pct ?? 0).toFixed(2)}%
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── K-Line Charts (independent of composite signals) ── */}
      {Object.keys(klineData).length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            {lang === "zh" ? "📈 K线走势" : "📈 K-Line Charts"}
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {Object.entries(klineData).filter(([, d]) => d.length >= 5).slice(0, 8).map(([ticker, data]) => {
              const last = data[data.length - 1];
              const first = data[0];
              const changePct = first?.close ? ((last.close - first.close) / first.close * 100) : 0;
              return (
                <div key={ticker} className="bg-[var(--bg-elevated)] rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold font-mono text-[var(--text-primary)]">${ticker}</span>
                    <span className="text-[10px] font-mono" style={{ color: changePct >= 0 ? "#059669" : "#ef4444" }}>
                      {changePct >= 0 ? "+" : ""}{changePct.toFixed(1)}%
                    </span>
                  </div>
                  <div className="text-xs font-mono text-[var(--text-secondary)] mb-1.5">
                    ${last?.close?.toFixed(2)}
                  </div>
                  <MiniCandleChart data={data} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Market Mood Card ── */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {lang === "zh" ? "🌡️ 市场情绪" : "🌡️ Market Mood"}
          </h3>
          <span
            className="px-3 py-1 rounded-full text-sm font-bold text-white"
            style={{ backgroundColor: moodColors[mood] }}
          >
            {moodLabels[mood]?.[lang] || mood}
          </span>
        </div>
        {sentiment.total > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-6 rounded-full overflow-hidden flex bg-[var(--bg-elevated)]">
              {sentiment.bullish > 0 && (
                <div
                  className="h-full flex items-center justify-center text-xs font-medium text-white"
                  style={{
                    width: `${(sentiment.bullish / sentiment.total) * 100}%`,
                    backgroundColor: "#059669",
                  }}
                >
                  {`${lang === "zh" ? "涨" : "↑"} ${sentiment.bullish}`}
                </div>
              )}
              {sentiment.neutral > 0 && (
                <div
                  className="h-full flex items-center justify-center text-xs font-medium text-white"
                  style={{
                    width: `${(sentiment.neutral / sentiment.total) * 100}%`,
                    backgroundColor: "#6b7280",
                  }}
                >
                  {sentiment.neutral}
                </div>
              )}
              {sentiment.bearish > 0 && (
                <div
                  className="h-full flex items-center justify-center text-xs font-medium text-white"
                  style={{
                    width: `${(sentiment.bearish / sentiment.total) * 100}%`,
                    backgroundColor: "#ef4444",
                  }}
                >
                  {`${lang === "zh" ? "跌" : "↓"} ${sentiment.bearish}`}
                </div>
              )}
            </div>
            <span className="text-xs text-[var(--text-tertiary)] shrink-0">
              {sentiment.total} {lang === "zh" ? "条" : "items"}
            </span>
          </div>
        )}
        {sentiment.total === 0 && (
          <p className="text-sm text-[var(--text-tertiary)]">
            {lang === "zh" ? "暂无情绪数据，请先抓取金融领域资讯" : "No sentiment data. Fetch finance news first."}
          </p>
        )}
      </div>

      {/* ── Broker Status + Account ── */}
      {brokerStatus?.configured && account && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            {lang === "zh" ? "💼 模拟账户" : "💼 Paper Account"}
            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500">
              {brokerStatus.mode === "paper" ? "Paper" : brokerStatus.mode}
            </span>
          </h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">
                {lang === "zh" ? "总权益" : "Equity"}
              </div>
              <div className="text-lg font-bold font-mono text-[var(--text-primary)]">
                ${account.equity?.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">
                {lang === "zh" ? "可用资金" : "Cash"}
              </div>
              <div className="text-lg font-mono text-[var(--text-secondary)]">
                ${account.cash?.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-tertiary)]">
                {lang === "zh" ? "今日盈亏" : "Daily P&L"}
              </div>
              <div
                className="text-lg font-bold font-mono"
                style={{ color: (account.daily_pnl || 0) >= 0 ? "#059669" : "#ef4444" }}
              >
                {(account.daily_pnl || 0) >= 0 ? "+" : ""}
                {account.daily_pnl?.toFixed(2)}
                <span className="text-xs ml-1">({(account.daily_pnl_pct || 0).toFixed(2)}%)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Positions ── */}
      {brokerStatus?.configured && positions.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            {lang === "zh" ? "📊 持仓" : "📊 Positions"}
          </h3>
          <div className="space-y-2">
            {positions.map((p: any) => (
              <div
                key={p.ticker}
                className="flex items-center justify-between py-2 border-b border-[var(--border-subtle)] last:border-0"
              >
                <div>
                  <span className="font-bold font-mono text-[var(--text-primary)]">{p.ticker}</span>
                  <span className="text-xs text-[var(--text-tertiary)] ml-2">
                    {p.quantity}{lang === "zh" ? "股" : " shares"} @ ${p.avg_price?.toFixed(2)}
                  </span>
                </div>
                <div className="text-right">
                  <div
                    className="font-mono text-sm"
                    style={{ color: (p.pnl ?? 0) >= 0 ? "#059669" : "#ef4444" }}
                  >
                    {(p.pnl ?? 0) >= 0 ? "+" : ""}${p.pnl?.toFixed(2)} ({p.pnl_pct?.toFixed(1)}%)
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Composite Signals ── */}
      {adjustedSignals.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "🎯 综合交易信号" : "🎯 Composite Signals"}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {adjustedSignals.map((sig: any) => (
              <div
                key={sig.ticker}
                className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-5"
              >
                {/* Header: ticker + direction + current price */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold font-mono text-[var(--text-primary)]">
                      ${sig.ticker}
                    </span>
                    <span
                      className="px-2 py-0.5 rounded text-xs font-semibold text-white"
                      style={{
                        backgroundColor:
                          sig.direction === "long"
                            ? "#059669"
                            : sig.direction === "short"
                              ? "#ef4444"
                              : "#6b7280",
                      }}
                    >
                      {sig.direction === "long"
                        ? lang === "zh"
                          ? "做多"
                          : "Long"
                        : sig.direction === "short"
                          ? lang === "zh"
                            ? "做空"
                            : "Short"
                          : lang === "zh"
                            ? "观望"
                            : "Hold"}
                    </span>
                  </div>
                  {sig.current_price != null && (
                    <span className="text-lg font-mono text-[var(--text-primary)]">
                      ${(sig.current_price ?? 0).toFixed(2)}
                    </span>
                  )}
                </div>

                {/* Confidence bar */}
                <div className="mb-3">
                  <div className="flex justify-between text-xs text-[var(--text-tertiary)] mb-1">
                    <span>{lang === "zh" ? "置信度" : "Confidence"}</span>
                    <span>{((sig.confidence ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-[var(--bg-elevated)] overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${(sig.confidence ?? 0) * 100}%`,
                        backgroundColor:
                          sig.direction === "long"
                            ? "#059669"
                            : sig.direction === "short"
                              ? "#ef4444"
                              : "#6b7280",
                      }}
                    />
                  </div>
                </div>

                {/* Three dimension scores with weight indicators */}
                <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                  <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                    <div className="text-[10px] text-[var(--text-tertiary)]">
                      {lang === "zh" ? "情绪" : "Sentiment"}
                    </div>
                    <div
                      className="text-sm font-bold"
                      style={{
                        color:
                          (sig.sentiment_score ?? 0) > 0
                            ? "#059669"
                            : (sig.sentiment_score ?? 0) < 0
                              ? "#ef4444"
                              : "#6b7280",
                      }}
                    >
                      {(sig.sentiment_score ?? 0) > 0 ? "+" : ""}
                      {(sig.sentiment_score ?? 0).toFixed(2)}
                    </div>
                    <div className="text-[8px] text-[var(--text-tertiary)]">{sentimentWeight}%</div>
                  </div>
                  <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                    <div className="text-[10px] text-[var(--text-tertiary)]">
                      {lang === "zh" ? "技术" : "Technical"}
                    </div>
                    <div
                      className="text-sm font-bold"
                      style={{
                        color:
                          (sig.technical_score ?? 0) > 0
                            ? "#059669"
                            : (sig.technical_score ?? 0) < 0
                              ? "#ef4444"
                              : "#6b7280",
                      }}
                    >
                      {(sig.technical_score ?? 0) > 0 ? "+" : ""}
                      {(sig.technical_score ?? 0).toFixed(2)}
                    </div>
                    <div className="text-[8px] text-[var(--text-tertiary)]">{technicalWeight}%</div>
                  </div>
                  <div className="bg-[var(--bg-elevated)] rounded-lg p-2">
                    <div className="text-[10px] text-[var(--text-tertiary)]">
                      {lang === "zh" ? "热度" : "Volume"}
                    </div>
                    <div className="text-sm font-bold text-[var(--text-primary)]">
                      {sig.news_volume ?? 0}
                    </div>
                    <div className="text-[8px] text-[var(--text-tertiary)]">{volumeWeight}%</div>
                  </div>
                </div>

                {/* Mini Candlestick Chart */}
                {klineData[sig.ticker] && klineData[sig.ticker].length > 0 && (
                  <div className="mb-3">
                    <MiniCandleChart data={klineData[sig.ticker]} />
                  </div>
                )}

                {/* Entry / Stop-Loss / Take-Profit */}
                {sig.entry_price != null && (
                  <div className="flex items-center gap-4 text-xs font-mono">
                    <span className="text-[var(--text-tertiary)]">
                      {lang === "zh" ? "入场" : "Entry"}:{" "}
                      <span className="text-[var(--text-primary)]">${(sig.entry_price ?? 0).toFixed(2)}</span>
                    </span>
                    {sig.stop_loss != null && (
                      <span className="text-red-400">
                        {lang === "zh" ? "止损" : "SL"}: ${(sig.stop_loss ?? 0).toFixed(2)}
                      </span>
                    )}
                    {sig.take_profit != null && (
                      <span className="text-emerald-400">
                        {lang === "zh" ? "止盈" : "TP"}: ${(sig.take_profit ?? 0).toFixed(2)}
                      </span>
                    )}
                  </div>
                )}

                {/* Position size */}
                {sig.position_size != null && (
                  <div className="mt-1 text-xs text-[var(--text-tertiary)]">
                    {lang === "zh" ? "仓位" : "Size"}: {sig.position_size}
                  </div>
                )}

                {/* Reasoning */}
                {sig.reasoning && (
                  <p className="mt-2 text-xs text-[var(--text-tertiary)] leading-relaxed">
                    {sig.reasoning}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Trade Signals (legacy overview signals) ── */}
      {signals.length > 0 && compositeSignals.length === 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "📊 交易信号" : "📊 Trade Signals"}
          </h3>
          <div className="space-y-3">
            {signals.map((sig) => (
              <div
                key={sig.ticker}
                className="flex items-center gap-3 p-3 rounded-lg bg-[var(--bg-elevated)]"
              >
                <span className="text-base font-bold font-mono text-[var(--text-primary)] w-16">
                  ${sig.ticker}
                </span>
                <span
                  className="px-2 py-0.5 rounded text-xs font-semibold text-white"
                  style={{ backgroundColor: dirColors[sig.direction] || "#6b7280" }}
                >
                  {dirLabels[sig.direction]?.[lang] || sig.direction}
                </span>
                <div className="flex-1 h-2 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${sig.strength * 100}%`,
                      backgroundColor: dirColors[sig.direction] || "#6b7280",
                    }}
                  />
                </div>
                <span className="text-xs text-[var(--text-tertiary)] font-mono w-10 text-right">
                  {((sig.strength ?? 0) * 100).toFixed(0)}%
                </span>
                <span className="text-xs text-[var(--text-tertiary)]">
                  {sig.sentiment_count} {lang === "zh" ? "条" : "mentions"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Top Tickers ── */}
      {tickers.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "🏷️ 热门标的" : "🏷️ Trending Tickers"}
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {tickers.map((t) => {
              const dominant = t.bullish >= t.bearish ? "bullish" : "bearish";
              return (
                <div
                  key={t.ticker}
                  className="flex flex-col items-center gap-1 p-3 rounded-lg bg-[var(--bg-elevated)]"
                >
                  <span className="text-sm font-bold font-mono text-[var(--text-primary)]">${t.ticker}</span>
                  <div className="flex items-center gap-1.5 text-xs">
                    <span style={{ color: "#059669" }}>↑{t.bullish}</span>
                    <span style={{ color: "#6b7280" }}>—{t.neutral}</span>
                    <span style={{ color: "#ef4444" }}>↓{t.bearish}</span>
                  </div>
                  <span
                    className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                    style={{
                      color: moodColors[dominant],
                      backgroundColor:
                        dominant === "bullish" ? "rgba(5,150,105,0.1)" : "rgba(239,68,68,0.1)",
                    }}
                  >
                    {moodLabels[dominant]?.[lang]}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Recent Sentiment Items ── */}
      {sentimentItems.length > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-xl p-6">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
            {lang === "zh" ? "📰 最新情绪分析" : "📰 Recent Sentiment"}
          </h3>
          <div className="space-y-2">
            {sentimentItems.slice(0, 20).map((item) => (
              <div
                key={item.id}
                className="flex items-start gap-3 py-2 border-b border-[var(--border-subtle)] last:border-0"
              >
                <span
                  className="shrink-0 mt-1 w-2 h-2 rounded-full"
                  style={{ backgroundColor: moodColors[item.sentiment] || "#6b7280" }}
                />
                <div className="flex-1 min-w-0">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-[var(--text-primary)] hover:text-[var(--accent)] line-clamp-1"
                  >
                    {lang === "zh" ? item.title : (item.title_en || item.title)}
                  </a>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span
                      className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                      style={{
                        color: moodColors[item.sentiment],
                        backgroundColor:
                          item.sentiment === "bullish"
                            ? "rgba(5,150,105,0.1)"
                            : item.sentiment === "bearish"
                              ? "rgba(239,68,68,0.1)"
                              : "rgba(107,114,128,0.1)",
                      }}
                    >
                      {moodLabels[item.sentiment]?.[lang]} {((item.confidence ?? 0) * 100).toFixed(0)}%
                    </span>
                    {item.tickers.length > 0 && (
                      <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                        {item.tickers.map((t: string) => `$${t}`).join(" ")}
                      </span>
                    )}
                  </div>
                </div>
                {item.score != null && (
                  <span className="text-xs font-mono text-[var(--text-tertiary)] shrink-0">
                    {(item.score ?? 0).toFixed(1)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      </>}
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-0">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex gap-0">
          {/* Time col */}
          <div className="w-[72px] shrink-0 flex items-start justify-end gap-2 pt-5 pr-3">
            <div className="skeleton w-10 h-3" />
            <div className="skeleton w-2 h-2 rounded-full mt-0.5" />
          </div>
          {/* Card body */}
          <div className="flex-1 border-b border-[var(--border-subtle)] py-4 pr-2">
            <div className="flex items-center gap-2 mb-2">
              <div className="skeleton w-5 h-5 rounded-full" />
              <div className="skeleton w-16 h-3" />
              <div className="skeleton w-20 h-3" />
            </div>
            <div className="skeleton h-5 w-4/5 mb-2" />
            <div className="space-y-1.5 mb-3">
              <div className="skeleton h-3.5 w-full" />
              <div className="skeleton h-3.5 w-full" />
              <div className="skeleton h-3.5 w-3/5" />
            </div>
            <div className="flex gap-2">
              <div className="skeleton w-12 h-5 rounded-full" />
              <div className="skeleton w-14 h-5 rounded-full" />
              <div className="skeleton w-10 h-5 rounded-full" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
