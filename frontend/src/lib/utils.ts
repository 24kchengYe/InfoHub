/**
 * InfoHub — utility helpers
 */

export type Lang = "zh" | "en";

/** Merge class names, filtering out falsy values. */
export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * Format a timestamp as concrete HH:MM time.
 */
export function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/**
 * Group items by their published_at date, returning labelled groups.
 */
export interface DateGroup<T> {
  label: string;
  items: T[];
}

export function groupByDate<T extends { published_at: string }>(
  items: T[],
  lang: Lang,
): DateGroup<T>[] {
  const groups: Map<string, T[]> = new Map();

  for (const item of items) {
    const dateStr = new Date(item.published_at).toDateString();
    if (!groups.has(dateStr)) groups.set(dateStr, []);
    groups.get(dateStr)!.push(item);
  }

  return Array.from(groups.entries()).map(([dateStr, groupItems]) => {
    const d = new Date(dateStr);
    const label = lang === "zh"
      ? d.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" })
      : d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
    return { label, items: groupItems };
  });
}

/**
 * Returns an inline style object for score badges.
 * Uses the design-spec score colour palette.
 */
export function scoreStyle(score?: number): { color: string; backgroundColor: string } {
  if (score == null || score < 5)
    return { color: "var(--score-muted)", backgroundColor: "var(--score-muted-bg)" };
  if (score >= 9)
    return { color: "var(--score-high)", backgroundColor: "var(--score-high-bg)" };
  if (score >= 7)
    return { color: "var(--score-mid)", backgroundColor: "var(--score-mid-bg)" };
  // 5-6
  return { color: "var(--score-low)", backgroundColor: "var(--score-low-bg)" };
}

/**
 * Map source_type to an emoji glyph.
 */
export function sourceIcon(type: string): string {
  const icons: Record<string, string> = {
    hackernews: "🔶",
    rss: "📡",
    reddit: "🔴",
    github: "🐙",
    twitter: "🐦",
    telegram: "✈️",
    wechat: "💬",
    arxiv: "📄",
  };
  return icons[type] || "📰";
}
