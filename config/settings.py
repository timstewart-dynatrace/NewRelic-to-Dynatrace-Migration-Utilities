"""
Configuration management for the New Relic to Dynatrace Migration Tool.
"""

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class NewRelicConfig(BaseSettings):
    """New Relic API Configuration."""

    api_key: str = Field(..., alias="NEW_RELIC_API_KEY")
    account_id: str = Field(..., alias="NEW_RELIC_ACCOUNT_ID")
    region: str = Field(default="US", alias="NEW_RELIC_REGION")  # US or EU

    @property
    def graphql_endpoint(self) -> str:
        """Get the NerdGraph API endpoint based on region."""
        if self.region.upper() == "EU":
            return "https://api.eu.newrelic.com/graphql"
        return "https://api.newrelic.com/graphql"

    @property
    def rest_api_base(self) -> str:
        """Get the REST API base URL based on region."""
        if self.region.upper() == "EU":
            return "https://api.eu.newrelic.com/v2"
        return "https://api.newrelic.com/v2"

    class Config:
        env_file = ".env"
        extra = "ignore"


class DynatraceConfig(BaseSettings):
    """Dynatrace API Configuration."""

    api_token: str = Field(..., alias="DYNATRACE_API_TOKEN")
    environment_url: str = Field(..., alias="DYNATRACE_ENVIRONMENT_URL")

    @field_validator("environment_url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        """Ensure URL doesn't have trailing slash."""
        return v.rstrip("/")

    @property
    def api_v2_base(self) -> str:
        """Get the API v2 base URL."""
        return f"{self.environment_url}/api/v2"

    @property
    def config_api_base(self) -> str:
        """Get the Config v1 base URL.

        Reachable only when the user runs with `--legacy` (Phase 14). Default
        Gen3 code paths use Settings 2.0, Document API, and Automation API
        instead.
        """
        return f"{self.environment_url}/api/config/v1"

    @property
    def platform_url(self) -> str:
        """Apps-subdomain URL for Gen3 Platform APIs (Document, Automation)."""
        return self.environment_url.replace(".live.", ".apps.")

    @property
    def settings_api(self) -> str:
        """Get the Settings 2.0 API URL.

        Gen3 SaaS (.apps.*) tenants expose Settings 2.0 under
        `/platform/classic/environment-api/v2/settings`; Classic SaaS
        (.live.*) and Managed keep the legacy `/api/v2/settings` path.
        """
        base = self.environment_url.rstrip("/")
        if ".apps." in base:
            return f"{base}/platform/classic/environment-api/v2/settings"
        return f"{base}/api/v2/settings"

    class Config:
        env_file = ".env"
        extra = "ignore"


class MigrationConfig(BaseSettings):
    """Migration tool configuration."""

    # Components to migrate
    components: List[str] = Field(
        default=["dashboards", "alerts", "synthetics", "slos", "workloads"],
        alias="MIGRATION_COMPONENTS"
    )

    # Output directory for exports
    output_dir: str = Field(default="./output", alias="MIGRATION_OUTPUT_DIR")

    # Dry run mode
    dry_run: bool = Field(default=False, alias="MIGRATION_DRY_RUN")

    # Batch size for API calls
    batch_size: int = Field(default=50, alias="MIGRATION_BATCH_SIZE")

    # Rate limiting (requests per second)
    rate_limit: float = Field(default=5.0, alias="MIGRATION_RATE_LIMIT")

    # Continue on errors
    continue_on_error: bool = Field(default=True, alias="MIGRATION_CONTINUE_ON_ERROR")

    # Backup before import
    backup_before_import: bool = Field(default=True, alias="MIGRATION_BACKUP")

    # Logging level
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Gen2 / classic tenant compatibility mode. When True, the migrator uses
    # the legacy transformers + client + exporters (Alerting Profiles,
    # Management Zones, Auto-Tag Rules, Config v1 dashboards/synthetics).
    # Prefer Gen3 defaults; this flag is a stop-gap for tenants without
    # Workflows / Segments / OpenPipeline / Document API provisioned.
    legacy_mode: bool = Field(default=False, alias="MIGRATION_LEGACY_MODE")

    class Config:
        env_file = ".env"
        extra = "ignore"


class Settings:
    """Main settings class combining all configurations."""

    _instance: Optional["Settings"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize all configuration sections."""
        self.newrelic = NewRelicConfig()  # type: ignore[call-arg]  # reads from env
        self.dynatrace = DynatraceConfig()  # type: ignore[call-arg]  # reads from env
        self.migration = MigrationConfig()

    @classmethod
    def reset(cls):
        """Reset singleton for testing."""
        cls._instance = None


# Convenience function to get settings
def get_settings() -> Settings:
    """Get the settings singleton."""
    return Settings()


# Available components for migration
AVAILABLE_COMPONENTS = [
    "dashboards",
    "alerts",
    "synthetics",
    "slos",
    "workloads",
    "notification_channels",
    "infrastructure",
    "log_parsing",
    "tags",
    "drop_rules",
]

# Component dependencies (must be migrated in order)
COMPONENT_DEPENDENCIES = {
    "alerts": ["notification_channels"],  # Alerts need notification channels first
    "slos": ["alerts"],  # SLOs may reference alerts
}
