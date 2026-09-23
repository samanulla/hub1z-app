"""Auth decorators for role-based access control."""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from ..models.user import UserRole


def roles_required(*roles: UserRole):
    """Restrict a view to users whose ``role`` is in ``roles``.

    Usage:
        @roles_required(UserRole.SUPER_ADMIN, UserRole.LOCATION_MANAGER)
        def some_view(): ...
    """
    role_values = {r.value if isinstance(r, UserRole) else r for r in roles}

    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            role_val = current_user.role.value if hasattr(current_user.role, "value") else current_user.role
            if role_val not in role_values:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return deco


def admin_required(view):
    return roles_required(UserRole.PLATFORM_OWNER, UserRole.SUPER_ADMIN,
                          UserRole.MANAGER, UserRole.LOCATION_MANAGER)(view)


def super_admin_required(view):
    return roles_required(UserRole.PLATFORM_OWNER, UserRole.SUPER_ADMIN)(view)


def manager_or_super_required(view):
    return roles_required(UserRole.PLATFORM_OWNER, UserRole.SUPER_ADMIN, UserRole.MANAGER)(view)


def platform_owner_required(view):
    return roles_required(UserRole.PLATFORM_OWNER)(view)


def platform_staff_required(view):
    """Platform Owner or Platform Manager — any authenticated platform-level user."""
    return roles_required(UserRole.PLATFORM_OWNER, UserRole.PLATFORM_MANAGER)(view)


def platform_permission_required(feature: str):
    """Restrict a /platform/* view to staff who hold a specific feature grant.

    Platform Owners always pass (they implicitly hold every feature). A
    Platform Manager must have ``feature`` in their ``platform_permissions``.
    """
    def deco(view):
        @wraps(view)
        @platform_staff_required
        def wrapper(*args, **kwargs):
            if not current_user.has_platform_permission(feature):
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return deco


def company_admin_required(view):
    return roles_required(UserRole.COMPANY_ADMIN)(view)


def member_required(view):
    return roles_required(UserRole.EMPLOYEE, UserRole.INDIVIDUAL, UserRole.COMPANY_ADMIN)(view)
