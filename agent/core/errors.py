class AgentError(Exception):
    """Base class for errors the CLI reports cleanly (no traceback)."""


class MissingConfigError(AgentError):
    def __init__(self, scope: str, env_vars: list[str]) -> None:
        self.scope = scope
        self.env_vars = env_vars
        super().__init__(f"{scope}: missing required env var(s): {', '.join(env_vars)}")


class UnknownSourceError(AgentError):
    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(f"unknown source {name!r}; available: {', '.join(available)}")


class DuplicateLeadError(AgentError):
    """A lead with this domain was inserted concurrently."""


class DuplicateSignalError(AgentError):
    """A signal with this source_url already exists."""
