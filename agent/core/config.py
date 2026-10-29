from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.core.errors import MissingConfigError

# Fields read from more than one env var, named that way in error messages.
ENV_NAMES = {"anthropic_api_key": "ANTHROPIC_API_KEY (or CODIFY_ANTHROPIC_API_KEY)"}


class Settings(BaseSettings):
    """Agent settings from env vars (or a local .env). Every key is optional here;
    each source declares what it needs and calls `require`, so a missing key
    fails that source only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    # Claude Code cloud sessions store it as CODIFY_ANTHROPIC_API_KEY so Claude
    # Code itself doesn't pick it up; GitHub Actions uses ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CODIFY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    apify_token: SecretStr | None = None
    hunter_api_key: SecretStr | None = None
    apollo_api_key: SecretStr | None = None
    millionverifier_api_key: SecretStr | None = None
    google_pagespeed_api_key: SecretStr | None = None
    google_places_api_key: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    reddit_user_agent: str | None = None
    producthunt_token: SecretStr | None = None
    slack_webhook_url: SecretStr | None = None

    def missing(self, *fields: str) -> list[str]:
        """Env var names (upper case) for the given fields that are unset or blank."""
        absent = []
        for field in fields:
            value = getattr(self, field)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if not value or not str(value).strip():
                absent.append(ENV_NAMES.get(field, field.upper()))
        return absent

    def require(self, *fields: str, scope: str) -> None:
        if absent := self.missing(*fields):
            raise MissingConfigError(scope, absent)

    @property
    def has_supabase(self) -> bool:
        return not self.missing("supabase_url", "supabase_service_role_key")
