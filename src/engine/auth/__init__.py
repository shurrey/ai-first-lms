"""Server-side identity: passwords, sessions, current_user(), CSRF and scope checks."""

from engine.auth.deps import csrf_protect, current_user
from engine.auth.models import AuthContext

__all__ = ["AuthContext", "csrf_protect", "current_user"]
