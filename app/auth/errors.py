"""Authentication errors safe to translate into generic client failures."""


class AuthenticationFailed(Exception):
    """A credential could not be verified without exposing account existence."""


class IdentityConfigurationError(ValueError):
    """Hosted identity configuration is invalid or incomplete."""
