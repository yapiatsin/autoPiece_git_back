"""Point d'entrée MIDDLEWARE (la logique est dans idle_timeout.py)."""
from .idle_timeout import IdleTimeoutMiddleware

__all__ = ['IdleTimeoutMiddleware']
