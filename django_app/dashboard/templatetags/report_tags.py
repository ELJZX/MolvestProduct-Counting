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


# Названия цветов палитры диаграмм (hex -> русское название)
_COLOR_NAMES = {
    '#dc3545': 'красный', '#e5534b': 'алый', '#d1242f': 'тёмно-красный',
    '#e83e8c': 'розовый', '#bf3989': 'пурпурный', '#9b2c6f': 'тёмно-пурпурный',
    '#fd7e14': 'оранжевый', '#f0883e': 'светло-оранжевый', '#c2410c': 'тёмно-оранжевый',
    '#e0a800': 'янтарный', '#bf8700': 'тёмно-янтарный', '#8a6d3b': 'оливковый',
    '#198754': 'зелёный', '#2da44e': 'светло-зелёный', '#0aac8e': 'бирюзово-зелёный',
    '#0f5132': 'тёмно-зелёный', '#0d9488': 'бирюзовый', '#0a7d63': 'тёмно-бирюзовый',
    '#0dcaf0': 'голубой', '#0a8cff': 'светло-синий', '#1f6feb': 'синий',
    '#0d6efd': 'синий', '#0857c3': 'тёмно-синий', '#3751a1': 'индиго',
    '#6610f2': 'фиолетовый', '#8250df': 'светло-фиолетовый', '#a475f9': 'сиреневый',
    '#6f42c1': 'фиолетовый', '#8957e5': 'светло-сиреневый', '#4b2e83': 'тёмно-фиолетовый',
    '#6c757d': 'серый', '#57606a': 'тёмно-серый', '#adbac7': 'светло-серый',
    '#495057': 'тёмно-серый', '#24292f': 'почти чёрный', '#343a40': 'тёмно-серый',
    '#f8d7da': 'бледно-розовый', '#d63384': 'малиновый', '#ffc107': 'жёлтый',
    '#20c997': 'изумрудный',
}


@register.filter
def color_name(value):
    """Название цвета по hex-коду (#rrggbb) из палитры диаграмм."""
    if not value:
        return '—'
    return _COLOR_NAMES.get(str(value).strip().lower(), str(value))
