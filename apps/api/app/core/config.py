from decimal import Decimal
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_name: str = "EnterpriseFlow AI"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./enterpriseflow.db"
    migration_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    frontend_url: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:8000"
    allowed_origins: str = "http://localhost:3000"
    session_cookie_secret: str = "local-only-change-this-session-secret-32-chars"
    session_ttl_seconds: int = 28800
    oidc_issuer: str = "http://localhost:8080/realms/enterpriseflow"
    oidc_audience: str = "enterpriseflow-api"
    oidc_client_id: str = "enterpriseflow-web"
    oidc_client_secret: str = ""
    oidc_jwks_url: str = ""
    oidc_token_url: str = ""
    oidc_authorize_url: str = ""
    oidc_logout_url: str = ""
    storage_backend: str = "local"
    storage_path: str = ".uploads"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "enterpriseflow-documents"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    max_upload_mb: int = 20
    clamav_host: str = ""
    clamav_port: int = 3310
    require_virus_scan: bool = False
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    anthropic_model: str = "claude-sonnet-4-5"
    default_llm_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rerank_model: str = ""
    # Configurable estimates, not a promise of current provider pricing.
    input_cost_per_million: Decimal = Decimal("3")
    output_cost_per_million: Decimal = Decimal("15")
    execution_budget_usd: Decimal = Decimal("0.25")
    daily_budget_usd: Decimal = Decimal("10")
    model_timeout_seconds: int = 60
    enable_fake_provider: bool = False
    enable_dev_users: bool = False
    jobs_eager: bool = False
    otel_exporter_otlp_endpoint: str = ""
    invoice_approval_threshold: Decimal = Decimal("1000")

    @property
    def is_production(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def llm_provider_configured(self) -> bool:
        return bool(self.openai_api_key) if self.default_llm_provider == "openai" else bool(self.anthropic_api_key) if self.default_llm_provider == "anthropic" else False

    @model_validator(mode="after")
    def production_safety(self):
        if self.is_production:
            if self.enable_fake_provider or self.enable_dev_users or self.jobs_eager:
                raise ValueError("Demo users, fake providers and eager jobs are disabled in production")
            if len(self.session_cookie_secret) < 32 or "local-only" in self.session_cookie_secret:
                raise ValueError("Set a strong SESSION_COOKIE_SECRET")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("Production OIDC must use HTTPS")
            if self.storage_backend != "s3" or self.database_url.startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL and S3")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
