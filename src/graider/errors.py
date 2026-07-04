"""Exception types. Any GraiderError message is safe to show the user."""


class GraiderError(Exception):
    """Base class for expected, user-facing errors."""


class ConfigError(GraiderError):
    """Configuration is missing or malformed."""


class AuthError(GraiderError):
    """A GitLab token is required but was not found."""
