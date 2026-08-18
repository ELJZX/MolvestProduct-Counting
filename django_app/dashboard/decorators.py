"""Декораторы контроля уровня доступа."""
from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Разрешает доступ только пользователям с указанными ролями.

    Пример: @role_required('admin', 'operator')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if profile is None or profile.role not in roles:
                raise PermissionDenied('Недостаточно прав доступа.')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def can_manage(user):
    """Может ли пользователь управлять линиями (смена продукта и т.п.)."""
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.role in ('admin', 'operator'))
