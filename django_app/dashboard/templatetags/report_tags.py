"""Пользовательские фильтры шаблонов."""
from django import template

register = template.Library()


@register.filter
def zip_lists(types, labels):
    """Склеивает две |-строки в список пар (значение, подпись)."""
    ts = [x for x in str(types).split('|') if x]
    ls = [x for x in str(labels).split('|') if x]
    return list(zip(ts, ls + [''] * (len(ts) - len(ls))))
