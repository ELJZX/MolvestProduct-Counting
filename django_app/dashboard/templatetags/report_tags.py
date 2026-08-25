"""Пользовательские фильтры шаблонов."""
from django import template

from dashboard.reporting import _fmt_duration

register = template.Library()


@register.filter
def zip_lists(types, labels):
    """Склеивает две |-строки в список пар (значение, подпись)."""
    ts = [x for x in str(types).split('|') if x]
    ls = [x for x in str(labels).split('|') if x]
    return list(zip(ts, ls + [''] * (len(ts) - len(ls))))


@register.filter
def duration(value):
    """Длительность в человекочитаемом виде: 65 -> '1 час 5 минут'."""
    try:
        return _fmt_duration(int(value or 0))
    except (TypeError, ValueError):
        return '—'


@register.filter
def startswith(value, arg):
    """Проверка начала строки: {{ value|startswith:'Код' }}."""
    return str(value or '').startswith(str(arg))
