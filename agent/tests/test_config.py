import pytest

from agent.core.config import Settings
from agent.core.errors import MissingConfigError


def test_anthropic_key_from_standard_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-standard")
    key = Settings(_env_file=None).anthropic_api_key
    assert key is not None and key.get_secret_value() == "sk-standard"


def test_anthropic_key_from_cloud_session_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODIFY_ANTHROPIC_API_KEY", "sk-codify")
    key = Settings(_env_file=None).anthropic_api_key
    assert key is not None and key.get_secret_value() == "sk-codify"


def test_codify_name_wins_when_both_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-standard")
    monkeypatch.setenv("CODIFY_ANTHROPIC_API_KEY", "sk-codify")
    key = Settings(_env_file=None).anthropic_api_key
    assert key is not None and key.get_secret_value() == "sk-codify"


def test_set_by_field_name() -> None:
    key = Settings(_env_file=None, anthropic_api_key="sk-direct").anthropic_api_key
    assert key is not None and key.get_secret_value() == "sk-direct"


def test_missing_key_names_both_env_vars() -> None:
    with pytest.raises(MissingConfigError) as exc:
        Settings(_env_file=None).require("anthropic_api_key", "slack_webhook_url", scope="funding")
    assert exc.value.env_vars == [
        "ANTHROPIC_API_KEY (or CODIFY_ANTHROPIC_API_KEY)",
        "SLACK_WEBHOOK_URL",
    ]


def test_blank_value_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "   ")
    assert Settings(_env_file=None).missing("slack_webhook_url") == ["SLACK_WEBHOOK_URL"]
