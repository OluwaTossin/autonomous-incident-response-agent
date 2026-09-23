"""Hosted authentication primitives, independent from authorization."""

from app.auth.context import ActorContext, AuthenticationMethod

__all__ = ["ActorContext", "AuthenticationMethod"]
