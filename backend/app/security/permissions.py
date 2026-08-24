"""Role-based access control (RBAC) permission checks.

This module holds the *policy* side of permissions: given a set of permissions
granted to a user and the permission required by a tool, decide whether the call
is allowed. The source of a user's permissions (DB / role / JWT claim) is wired
elsewhere; this module is pure and testable.

Native tools and MCP tools share the exact same check, so neither provider can
bypass the Tool Gateway's permission gate.
"""
from typing import Iterable, Optional


def check_permission(
    required_permission: Optional[str],
    user_permissions: Iterable[str],
) -> bool:
    """Return ``True`` if ``user_permissions`` satisfy ``required_permission``.

    Rules:

    * If a tool requires no permission (``None`` / ``""``) it is always allowed.
    * A user satisfies the requirement if the exact permission string is present
      in their granted set, or if they hold the wildcard ``"*"`` permission.

    Args:
        required_permission: the permission a tool demands (may be ``None``).
        user_permissions: permissions granted to the calling user.
    """
    if not required_permission:
        return True
    perms = set(user_permissions or set())
    if "*" in perms:
        return True
    return required_permission in perms


def permission_denied_message(tool_name: str, required_permission: str) -> str:
    """Standard error string returned when a tool's permission is missing."""
    return f"permission_denied: tool '{tool_name}' requires '{required_permission}'"
