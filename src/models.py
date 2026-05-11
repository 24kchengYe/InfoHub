"""Core data models for InfoHub.

Extends Horizon's ContentItem with multi-domain support,
read/star tracking, pipeline stages, and domain configuration.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

from pydantic import BaseModel, HttpUrl, Field


# ---------------------------------------------------------------------------
# Source types (same as Horizon)
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """Supported information source types."""
    GITHUB = "github"
    HACKERNEWS = "hackernews"
    RSS = "rss"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"


# ---------------------------------------------------------------------------
# Content item (extended from Horizon)
# ---------------------------------------------------------------------------

class ContentItem(BaseModel):
    """Unified content item from any source.

    Keeps every original Horizon field and adds InfoHub-specific
    fields for multi-domain management, read/star state, clustering,
    and pipeline tracking.
    """

    # --- Original Horizon fields ---
    id: str                                     # Format: {source}:{subtype}:{native_id}
    source_type: SourceType
    title: str
    url: HttpUrl
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # AI analysis results
    ai_score: Optional[float] = None            # 0-10 importance score
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_tags: List[str] = Field(default_factory=list)

    # --- InfoHub extensions ---
    domain: Optional[str] = None                # Domain slug, e.g. "ai", "finance"
    is_read: bool = False
    is_starred: bool = False
    cluster_id: Optional[str] = None            # Dedup / clustering identifier
    stage: Optional[str] = None                 # Pipeline stage: fetched / scored / filtered / enriched
    pipeline_run_id: Optional[str] = None       # Which pipeline run produced this item


# ---------------------------------------------------------------------------
# AI provider & config (carried over from Horizon for scrapers / ai modules)
# ---------------------------------------------------------------------------

class AIProvider(str, Enum):
    """Supported AI providers."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE = "azure"
    ALI = "ali"
    GEMINI = "gemini"
    DOUBAO = "doubao"
    MINIMAX = "minimax"


class AIConfig(BaseModel):
    """AI client configuration."""

    provider: AIProvider
    model: str
    base_url: Optional[str] = None
    api_key_env: str
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Azure OpenAI specific
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Source configs (carried over from Horizon for scrapers)
# ---------------------------------------------------------------------------

class GitHubSourceConfig(BaseModel):
    """GitHub source configuration."""
    type: str                                   # "user_events", "repo_releases", etc.
    username: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True


class HackerNewsConfig(BaseModel):
    """Hacker News configuration."""
    enabled: bool = True
    fetch_top_stories: int = 30
    min_score: int = 100


class RSSSourceConfig(BaseModel):
    """RSS feed source configuration."""
    name: str
    url: HttpUrl
    enabled: bool = True
    category: Optional[str] = None


class RedditSubredditConfig(BaseModel):
    """Configuration for monitoring a specific subreddit."""
    subreddit: str
    enabled: bool = True
    sort: str = "hot"
    time_filter: str = "day"
    fetch_limit: int = 25
    min_score: int = 10


class RedditUserConfig(BaseModel):
    """Configuration for monitoring a specific Reddit user."""
    username: str
    enabled: bool = True
    sort: str = "new"
    fetch_limit: int = 10


class RedditConfig(BaseModel):
    """Reddit source configuration."""
    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list)
    users: List[RedditUserConfig] = Field(default_factory=list)
    fetch_comments: int = 5


class TelegramChannelConfig(BaseModel):
    """Configuration for monitoring a specific Telegram channel."""
    channel: str
    enabled: bool = True
    fetch_limit: int = 20


class TelegramConfig(BaseModel):
    """Telegram source configuration."""
    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list)


class TwitterConfig(BaseModel):
    """Twitter source configuration via Apify."""
    enabled: bool = True
    apify_token_env: str = "APIFY_TOKEN"
    actor_id: str = "altimis~scweet"
    users: List[str] = Field(default_factory=list)
    fetch_limit: int = 10
    fetch_reply_text: bool = False
    max_replies_per_tweet: int = 3
    max_tweets_to_expand: int = 10
    reply_min_likes: int = 0


class SourcesConfig(BaseModel):
    """All sources configuration."""
    github: List[GitHubSourceConfig] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    rss: List[RSSSourceConfig] = Field(default_factory=list)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    twitter: Optional[TwitterConfig] = None


# ---------------------------------------------------------------------------
# Webhook / Email / Filtering (carried over from Horizon)
# ---------------------------------------------------------------------------

class WebhookConfig(BaseModel):
    """Webhook notification configuration."""
    url_env: Optional[str] = None
    request_body: Optional[Union[str, dict, list]] = None
    headers: Optional[str] = None
    delivery: str = "summary"
    overview_position: str = "first"
    platform: str = "generic"
    layout: str = "markdown"
    fallback_layout: str = "markdown"
    languages: Optional[List[str]] = None
    enabled: bool = False


class EmailConfig(BaseModel):
    """Email configuration for updates/subscriptions."""
    imap_server: str
    imap_port: int = 993
    smtp_server: str
    smtp_port: int = 465
    email_address: str
    password_env: str = "EMAIL_PASSWORD"
    sender_name: str = "Horizon Daily"
    subscribe_keyword: str = "SUBSCRIBE"
    unsubscribe_keyword: str = "UNSUBSCRIBE"
    enabled: bool = False


class FilteringConfig(BaseModel):
    """Content filtering configuration."""
    ai_score_threshold: float = 7.0
    time_window_hours: int = 24


class Config(BaseModel):
    """Horizon-compatible main configuration model."""
    version: str = "1.0"
    ai: AIConfig
    sources: SourcesConfig
    filtering: FilteringConfig
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None


# ---------------------------------------------------------------------------
# InfoHub domain configuration (loaded from data/domains/*.json)
# ---------------------------------------------------------------------------

class DomainConfig(BaseModel):
    """Per-domain configuration loaded from data/domains/<slug>.json."""

    slug: str                                   # e.g. "ai", "finance"
    name: str                                   # Display name, e.g. "人工智能"
    icon: str = ""                              # Emoji icon
    color: str = "#6366f1"                      # Hex color for UI
    enabled: bool = True
    sort_order: int = 0

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    filtering: FilteringConfig = Field(default_factory=FilteringConfig)


# ---------------------------------------------------------------------------
# InfoHub global configuration
# ---------------------------------------------------------------------------

class ServerConfig(BaseModel):
    """Web server configuration."""
    host: str = "0.0.0.0"
    port: int = 18888


class SchedulerConfig(BaseModel):
    """Scheduler configuration."""
    enabled: bool = True
    cron: str = "0 */4 * * *"
    default_hours: int = 24


class GlobalConfig(BaseModel):
    """Top-level InfoHub configuration (data/config.json)."""
    ai: AIConfig
    server: ServerConfig = Field(default_factory=ServerConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
