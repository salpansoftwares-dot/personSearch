"""
Application configuration.

All settings are loaded from environment variables (or a .env file).
Never hard-code secrets here.
"""

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ────────────────────────────────────────────────────────────
    app_name: str = "PersonSearch API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = Field("development", pattern="^(development|staging|production)$")

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/personsearch"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False  # set True to log SQL in dev

    # ── Redis / Queue ──────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600  # 1 hour default

    # ── Auth ───────────────────────────────────────────────────────────────────
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ── Rate limiting ──────────────────────────────────────────────────────────
    rate_limit_searches_per_minute: int = 10
    rate_limit_burst: int = 20

    # ── AI / Model adapter ─────────────────────────────────────────────────────
    ai_provider: str = Field("nvidia", pattern="^(nvidia|google|openai|anthropic)$")
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    google_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Separate model tiers: cheap for bulk extraction, strong for hard cases
    ai_model_extraction: str = "meta/llama-3.2-11b-vision-instruct"
    ai_model_reasoning: str = "meta/llama-3.2-90b-vision-instruct"

    # ── Source collector ───────────────────────────────────────────────────────
    collector_timeout_seconds: int = 5
    collector_max_retries: int = 1
    collector_per_domain_delay_seconds: float = 0.2


    # ── Entity resolution ──────────────────────────────────────────────────────
    # Conservative merge: a cluster score must exceed this to auto-merge.
    # With the direct_search_hit signal (weight 0.40), a search-engine result
    # scores at minimum 0.50 (name_similarity 0.10 + direct_hit 0.40).
    entity_merge_threshold: float = 0.45

    # ── Governance ─────────────────────────────────────────────────────────────
    claim_expiry_days: int = 90          # claims older than this are staleness-flagged
    removal_sla_hours: int = 72          # target SLA for processing removal requests

    # ── Staleness & retention ──────────────────────────────────────────────────
    # Source TTL by source type (days). Keys match source_type values in the collector.
    # Sources not listed here fall back to source_ttl_default_days.
    source_ttl_default_days: int = 90
    source_ttl_linkedin_days: int = 30   # LinkedIn profiles change frequently
    source_ttl_github_days: int = 60
    source_ttl_press_days: int = 180     # News articles change rarely
    source_ttl_conference_days: int = 365
    # How often the re-verification worker sweeps for expired sources (seconds).
    reverify_sweep_interval_seconds: int = 3600  # 1 hour
    # Max sources to re-verify in one sweep run (avoid thundering-herd).
    reverify_batch_size: int = 50

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173"]  # Vite dev server


# Single shared instance — import this everywhere.
settings = Settings()
