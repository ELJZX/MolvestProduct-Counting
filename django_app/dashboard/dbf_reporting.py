"""Отчёты и графики из файлов DBF (запасной режим).

Режим включается в админке Django (SystemConfig -> «Файлы DBF»). Во вкладке
«Отчёты» в списке «Счётчик» показываются коды счётчиков, найденные в именах
файлов DBF (например, 20442023.dbf -> код 2044). Для выбранного периода
(Смена/Сутки/Месяц/Квартал/Год/Период) автоматически находятся файлы этого
счётчика, покрывающие период, и строится отчёт или график.

Интерфейс совместим с reporting.build_report: те же вкладки, типы отчётов и
структура результата, поэтому таблицы, графики и экспорт XLSX/CSV работают
без изменений.
"""
import datetime
import os

from django.utils import timezone

from . import dbf_reader
from .models import Product, SystemConfig
from .reporting import SHIFT_BREAK_HOUR, _table, resolve_period

MINUTE = datetime.timedelta(minutes=1)

REPORT_TYPES = {
    'shift': ['total', 'detail', 'downtime'],
    'day': ['total', 'detail_shifts', 'chart', 'downtime'],
    'month': ['by_shift', 'total_days', 'chart', 'downtime', 'gross'],
    'quarter': ['total_months', 'gross', 'by_shift', 'downtime'],
    'year': ['total_quarters', 'gross', 'by_shift', 'downtime'],
    'period': ['total_year', 'gross', 'by_shift', 'downtime', 'detail'],
}

TYPE_LABELS = {
    'total': 'Отчёт итоговый', 'detail': 'Отчёт подробный',
    'detail_shifts': 'Отчёт подробный (по сменам)', 'chart': 'График продукции',
    'downtime': 'Отчёт о простоях', 'by_shift': 'Отчёт по смене',
    'total_days': 'Отчёт итоговый по дням', 'gross': 'Отчёт валовый',
    'total_months': 'Отчёт итоговый по месяцам',
    'total_quarters': 'Отчёт итоговый по кварталам',
    'total_year': 'Отчёт итоговый в пределах года',
}


def _fmt_count(n):
    try:
        return f'{int(n):,}'.replace(',', ' ')
    except (TypeError, ValueError):
        return '0'


def _resolve_files(counter_id, from_dt, to_dt):
    """Файлы DBF по коду счётчика и периоду: (paths, error)."""
    cfg = SystemConfig.get()
    d = cfg.resolved_dbf_dir()
    code = str(counter_id or '').strip()
    if not code:
        return None, 'Выберите код счётчика.'
    files = dbf_reader.find_files_for_period(d, code, from_dt, to_dt)
    if not files:
        codes = dbf_reader.list_counter_codes(d)
        if code not in codes:
            found = ', '.join(sorted(codes)) if codes else '—'
            return None, (
                f'Код счётчика {code} не найден в файлах DBF '
                f'(папка: {d}). Найдены коды: {found}.'
            )
        return None, f'Для выбранного периода файлы счётчика {code} не найдены (папка: {d}).'
    return [f['path'] for f in files], None


def _products_map():
    return {
        p.code: {'name': p.name, 'color': p.color or '#6c757d',
                 'image': p.image.url if p.image else None,
                 'code_1c': p.code_1c or ''}
        for p in Product.objects.all()
    }


def _prod_info(kod_str, pmap):
    if kod_str and kod_str in pmap:
        return pmap[kod_str]
    return {'name': f'Продукт {kod_str}', 'color': '#6c757d',
            'image': None, 'code_1c': ''}


def _floor_minute(dt):
    local = timezone.localtime(dt)
    return local.replace(second=0, microsecond=0)


def _rows(paths, from_dt, to_dt):
    """Генератор строк по всем файлам периода: {minute (aware), count, kod_str}."""
    for path in paths:
        for r in dbf_reader.iter_minutes(path, from_dt, to_dt):
            yield {'minute': r['minute'], 'count': r['count'], 'kod_str': r['kod_str']}


def _per_product(paths, from_dt, to_dt):
    acc = {}
    for r in _rows(paths, from_dt, to_dt):
        k = r['kod_str'] or '000'
        acc[k] = acc.get(k, 0) + r['count']
    return acc


def _day_key(dt):
    return timezone.localtime(dt).date()


def _per_day(paths, from_dt, to_dt):
    acc = {}
    for r in _rows(paths, from_dt, to_dt):
        d = _day_key(r['minute'])
        acc[d] = acc.get(d, 0) + r['count']
    return sorted(acc.items())


def _per_day_shift(paths, from_dt, to_dt):
    acc = {}
    for r in _rows(paths, from_dt, to_dt):
        d = _day_key(r['minute'])
        sh = 1 if timezone.localtime(r['minute']).hour < SHIFT_BREAK_HOUR else 2
        acc.setdefault(d, {1: 0, 2: 0})
        acc[d][sh] += r['count']
    rows = []
    for d in sorted(acc):
        rows.append({'day': d, 'shift1': acc[d][1], 'shift2': acc[d][2],
                     'total': acc[d][1] + acc[d][2]})
    return rows


def _month_start(d):
    return datetime.date(d.year, d.month, 1)


def _per_month(paths, from_dt, to_dt):
    acc = {}
    for r in _rows(paths, from_dt, to_dt):
        m = _month_start(_day_key(r['minute']))
        acc[m] = acc.get(m, 0) + r['count']
    return sorted(acc.items())


def _quarter_start(d):
    qm = ((d.month - 1) // 3) * 3 + 1
    return datetime.date(d.year, qm, 1)


def _per_quarter(paths, from_dt, to_dt):
    acc = {}
    for r in _rows(paths, from_dt, to_dt):
        q = _quarter_start(_day_key(r['minute']))
        acc[q] = acc.get(q, 0) + r['count']
    return sorted(acc.items())


def _minute_series(paths, from_dt, to_dt):
    """Минутный ряд с заполнением нулей: [{minute, full_minute, ts, count, kod_str}]."""
    from_dt = _floor_minute(from_dt)
    to_dt = _floor_minute(to_dt)
    rows = {r['minute']: r for r in _rows(paths, from_dt, to_dt)}
    series = []
    cur = from_dt
    while cur < to_dt:
        r = rows.get(cur)
        series.append({
            'minute': timezone.localtime(cur).strftime('%H:%M'),
            'full_minute': timezone.localtime(cur).strftime('%d.%m.%Y %H:%M'),
            'ts': cur.isoformat(),
            'count': r['count'] if r else 0,
            'kod_str': r['kod_str'] if r else None,
        })
        cur += MINUTE
    return series


def _non_zero_records(paths, from_dt, to_dt):
    """Минутные записи с ненулевым счётом (для подробных таблиц)."""
    return [r for r in _rows(paths, from_dt, to_dt) if r['count'] > 0]


def _rows_product_summary(per_product, total, pmap):
    out = []
    for kod, count in sorted(per_product.items()):
        pct = (count / total * 100) if total else 0
        p = _prod_info(kod, pmap)
        out.append([kod, p['name'], _fmt_count(count),
                    f'{pct:.1f}%'.replace('.', ',')])
    return out


def _bucket_start(dt, bucket):
    local = timezone.localtime(dt)
    if bucket == 'day':
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == 'month':
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if bucket == 'quarter':
        qm = ((local.month - 1) // 3) * 3 + 1
        return local.replace(month=qm, day=1, hour=0, minute=0, second=0, microsecond=0)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _downtime_events(paths, from_dt, to_dt):
    events = []
    for path in paths:
        events.extend(dbf_reader.downtime_events(path, from_dt, to_dt))
    events.sort(key=lambda e: e['start'])
    return events


def _downtime_rows(events):
    rows = []
    for i, e in enumerate(events, start=1):
        rows.append([
            str(i),
            timezone.localtime(e['start']).strftime('%d.%m.%Y %H:%M'),
            timezone.localtime(e['end']).strftime('%d.%m.%Y %H:%M'),
            e['minutes'],
            e['product_name'],
            'продолжается' if e['ongoing'] else 'завершён',
        ])
    return rows


def _downtime_by(paths, from_dt, to_dt, bucket):
    acc = {}
    for e in _downtime_events(paths, from_dt, to_dt):
        key = _bucket_start(e['start'], bucket)
        acc[key] = acc.get(key, 0) + e['minutes']
    return sorted(acc.items())


def _chart_day(paths, from_dt, to_dt, pmap):
    series = _minute_series(paths, from_dt, to_dt)
    details = []
    for pt in series:
        p = _prod_info(pt['kod_str'], pmap)
        details.append({
            'code': pt['kod_str'],
            'name': pt['kod_str'] and p['name'],
            'color': p['color'],
            'image': p['image'],
            'code_1c': p['code_1c'],
            'ts': pt['full_minute'],
        })
    events = _downtime_events(paths, from_dt, to_dt)
    return {
        'type': 'bar',
        'title': 'График продукции (по минутам)',
        'labels': [s['minute'] for s in series],
        'datasets': [{'label': 'Кол-во, шт./мин',
                      'data': [s['count'] for s in series]}],
        'details': details,
        'colors': [d['color'] for d in details],
        'minute_ts': [s['ts'] for s in series],
        'downtime': [
            {
                'start': timezone.localtime(e['start']).isoformat(),
                'end': timezone.localtime(e['end']).isoformat(),
                'minutes': e['minutes'],
                'ongoing': e['ongoing'],
                'product_code': e['product_code'],
                'product_name': e['product_name'],
            }
            for e in events
        ],
    }


def _chart_month(paths, from_dt, to_dt, pmap):
    by_day = {}
    for r in _rows(paths, from_dt, to_dt):
        d = _day_key(r['minute'])
        item = by_day.setdefault(d, {'count': 0, 'prods': {}})
        item['count'] += r['count']
        if r['kod_str']:
            item['prods'][r['kod_str']] = item['prods'].get(r['kod_str'], 0) + r['count']
    days = sorted(by_day.keys())
    tz = timezone.get_current_timezone()
    details = []
    for d in days:
        prods = by_day[d]['prods']
        dom = max(prods, key=prods.get) if prods else None
        p = _prod_info(dom, pmap)
        details.append({
            'code': dom,
            'name': p['name'],
            'color': p['color'],
            'image': p['image'],
            'code_1c': p['code_1c'],
            'ts': d.strftime('%d.%m.%Y'),
        })
    dt_by_day = {
        timezone.localtime(k).date(): v
        for k, v in _downtime_by(paths, from_dt, to_dt, 'day')
    }
    return {
        'type': 'bar',
        'title': 'График продукции (по дням)',
        'labels': [timezone.localtime(
            timezone.make_aware(datetime.datetime(d.year, d.month, d.day), tz)
        ).strftime('%d.%m') for d in days],
        'datasets': [{'label': 'Кол-во, шт./день',
                      'data': [by_day[d]['count'] for d in days]}],
        'details': details,
        'colors': [d['color'] for d in details],
        # минуты простоя по дням (столбики второго датасета)
        'downtime_by_day': [dt_by_day.get(d, 0) for d in days],
    }


def build_report(tab, rtype, counter_id, params):
    """Собирает отчёт из файлов DBF по коду счётчика: {'ok', 'tables', 'chart', ...}."""
    if tab not in REPORT_TYPES:
        return {'ok': False, 'error': f'Неизвестная вкладка: {tab}'}
    if rtype not in REPORT_TYPES[tab]:
        return {'ok': False, 'error': f'Неизвестный тип отчёта: {rtype}'}

    from_dt, to_dt, label, err = resolve_period(tab, params)
    if err:
        return {'ok': False, 'error': err}

    paths, err = _resolve_files(counter_id, from_dt, to_dt)
    if err:
        return {'ok': False, 'error': err}

    pmap = _products_map()
    tables = []
    chart = None

    # ----- Смена -----
    if tab == 'shift':
        if rtype == 'total':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт итоговый (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%'],
            ))
        elif rtype == 'detail':
            rows, run = [], 0
            for r in _non_zero_records(paths, from_dt, to_dt):
                run += r['count']
                p = _prod_info(r['kod_str'], pmap)
                rows.append([timezone.localtime(r['minute']).strftime('%H:%M'),
                             r['kod_str'] or '—', p['name'], r['count'], run])
            tables.append(_table(
                'Отчёт подробный (по минутам)',
                ['Время', 'Код', 'Продукт', 'Кол-во, шт.', 'Накопительно'],
                rows, total_row=['', '', 'ИТОГО', run, ''],
            ))
        elif rtype == 'downtime':
            events = _downtime_events(paths, from_dt, to_dt)
            total_min = sum(e['minutes'] for e in events)
            tables.append(_table(
                'Отчёт о простоях (подробный)',
                ['№', 'Начало', 'Окончание', 'Минут', 'Продукт', 'Статус'],
                _downtime_rows(events), total_row=['', '', 'ИТОГО', total_min, '', ''],
            ))

    # ----- Сутки -----
    elif tab == 'day':
        if rtype == 'total':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт итоговый (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%'],
            ))
        elif rtype == 'detail_shifts':
            rows, last_shift = [], None
            shift_total = {1: 0, 2: 0}
            for r in _non_zero_records(paths, from_dt, to_dt):
                sh = 1 if timezone.localtime(r['minute']).hour < SHIFT_BREAK_HOUR else 2
                if last_shift is not None and sh != last_shift:
                    rows.append(['—', '', f'ИТОГО по смене {last_shift}', shift_total[last_shift], ''])
                last_shift = sh
                shift_total[sh] += r['count']
                p = _prod_info(r['kod_str'], pmap)
                rows.append([timezone.localtime(r['minute']).strftime('%H:%M'),
                             f'Смена {sh}', p['name'], r['count'], ''])
            if last_shift is not None:
                rows.append(['—', '', f'ИТОГО по смене {last_shift}', shift_total[last_shift], ''])
            tables.append(_table(
                'Отчёт подробный (с раскладкой по сменам)',
                ['Время', 'Смена', 'Продукт', 'Кол-во, шт.', ''],
                rows, total_row=['', '', 'ИТОГО', shift_total[1] + shift_total[2], ''],
            ))
        elif rtype == 'chart':
            chart = _chart_day(paths, from_dt, to_dt, pmap)
            # График без текстовой плашки: таблиц нет, отображается только график
        elif rtype == 'downtime':
            events = _downtime_events(paths, from_dt, to_dt)
            total_min = sum(e['minutes'] for e in events)
            tables.append(_table(
                'Отчёт о простоях (подробный)',
                ['№', 'Начало', 'Окончание', 'Минут', 'Продукт', 'Статус'],
                _downtime_rows(events), total_row=['', '', 'ИТОГО', total_min, '', ''],
            ))

    # ----- Месяц -----
    elif tab == 'month':
        if rtype == 'by_shift':
            rows = []
            for r in _per_day_shift(paths, from_dt, to_dt):
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 1', r['shift1']])
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 2', r['shift2']])
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total],
            ))
        elif rtype == 'total_days':
            days = _per_day(paths, from_dt, to_dt)
            rows = [[d.strftime('%d.%m.%Y'), _fmt_count(total)] for d, total in days]
            total = sum(t for _, t in days)
            per_prod = _per_product(paths, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями по дням)',
                ['Дата', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', _fmt_count(total)]))
            tables.append(_table(
                'По продуктам за месяц',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'chart':
            chart = _chart_month(paths, from_dt, to_dt, pmap)
            # График без текстовой плашки: таблиц нет, отображается только график
        elif rtype == 'downtime':
            items = _downtime_by(paths, from_dt, to_dt, 'day')
            rows = [[timezone.localtime(d).strftime('%d.%m.%Y'), m] for d, m in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по дням)',
                ['Дата', 'Минут простоя'], rows, total_row=['ИТОГО', total]))
        elif rtype == 'gross':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))

    # ----- Квартал -----
    elif tab == 'quarter':
        if rtype == 'total_months':
            months = _per_month(paths, from_dt, to_dt)
            rows = [[m.strftime('%m.%Y'), _fmt_count(total)] for m, total in months]
            total = sum(t for _, t in months)
            per_prod = _per_product(paths, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями за месяцы)',
                ['Месяц', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', _fmt_count(total)]))
            tables.append(_table(
                'По продуктам за квартал',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'gross':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'by_shift':
            rows = []
            for r in _per_day_shift(paths, from_dt, to_dt):
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 1', r['shift1']])
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 2', r['shift2']])
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(paths, from_dt, to_dt, 'month')
            rows = [[timezone.localtime(m).strftime('%m.%Y'), mins] for m, mins in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по месяцам)',
                ['Месяц', 'Минут простоя'], rows, total_row=['ИТОГО', total]))

    # ----- Год -----
    elif tab == 'year':
        if rtype == 'total_quarters':
            quarters = _per_quarter(paths, from_dt, to_dt)
            rows = [[q.strftime('%Y-%m'), _fmt_count(total)] for q, total in quarters]
            total = sum(t for _, t in quarters)
            per_prod = _per_product(paths, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями за кварталы)',
                ['Квартал', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', _fmt_count(total)]))
            tables.append(_table(
                'По продуктам за год',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'gross':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'by_shift':
            rows = []
            for r in _per_day_shift(paths, from_dt, to_dt):
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 1', r['shift1']])
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 2', r['shift2']])
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(paths, from_dt, to_dt, 'quarter')
            rows = []
            for q, mins in items:
                qn = (q.month - 1) // 3 + 1
                rows.append([q.strftime('%Y'), f'{qn} кв.', mins])
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по кварталам)',
                ['Год', 'Квартал', 'Минут простоя'], rows,
                total_row=['', 'ИТОГО', total]))

    # ----- Период -----
    elif tab == 'period':
        if rtype == 'total_year':
            months = _per_month(paths, from_dt, to_dt)
            rows = [[m.strftime('%m.%Y'), _fmt_count(total)] for m, total in months]
            total = sum(t for _, t in months)
            per_prod = _per_product(paths, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (в пределах года, по месяцам)',
                ['Месяц', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', _fmt_count(total)]))
            tables.append(_table(
                'По продуктам за период',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'gross':
            per_prod = _per_product(paths, from_dt, to_dt)
            total = sum(per_prod.values())
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                _rows_product_summary(per_prod, total, pmap),
                total_row=['', 'ИТОГО', _fmt_count(total), '100,0%']))
        elif rtype == 'by_shift':
            rows = []
            for r in _per_day_shift(paths, from_dt, to_dt):
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 1', r['shift1']])
                rows.append([r['day'].strftime('%d.%m.%Y'), 'Смена 2', r['shift2']])
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(paths, from_dt, to_dt, 'day')
            rows = [[timezone.localtime(d).strftime('%d.%m.%Y'), mins] for d, mins in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по дням)',
                ['Дата', 'Минут простоя'], rows, total_row=['ИТОГО', total]))
        elif rtype == 'detail':
            if (to_dt - from_dt) > datetime.timedelta(days=2):
                return {'ok': False,
                        'error': 'Отчёт подробный формируется за период не более 2 суток.'}
            rows, run = [], 0
            for r in _non_zero_records(paths, from_dt, to_dt):
                run += r['count']
                p = _prod_info(r['kod_str'], pmap)
                rows.append([timezone.localtime(r['minute']).strftime('%d.%m.%Y %H:%M'),
                             r['kod_str'] or '—', p['name'], r['count'], run])
            tables.append(_table(
                'Отчёт подробный за период (по минутам)',
                ['Время', 'Код', 'Продукт', 'Кол-во, шт.', 'Накопительно'],
                rows, total_row=['', '', 'ИТОГО', run, ''],
            ))

    if not tables and chart is None:
        return {'ok': False, 'error': 'Нет данных для формирования отчёта.'}

    return {
        'ok': True,
        'tables': tables,
        'chart': chart,
        'error': None,
        'title': TYPE_LABELS.get(rtype, rtype),
        'period_label': label,
        'counter': f'Счётчик {str(counter_id).strip()} (DBF)',
        'line': f'Счётчик {str(counter_id).strip()} (DBF)',
        'range': {
            'from': timezone.localtime(from_dt).isoformat(),
            'to': timezone.localtime(to_dt).isoformat(),
        },
    }
