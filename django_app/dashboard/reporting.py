"""Движок формирования отчётов по счётчикам (линиям).

Вкладки: Смена, Сутки, Месяц, Квартал, Год, Период.
Смены (локальное время предприятия):
    Смена 1 — 00:00–07:59,  Смена 2 — 08:00–23:59.
"""
import datetime
import calendar

from django.conf import settings
from django.db.models import F, Q, Sum
from django.db.models.expressions import RawSQL
from django.utils import timezone

from . import services
from .models import Counter, Product, ProductionRecord, ReportLog

TZ = settings.TIME_ZONE
SHIFT_BREAK_HOUR = 8  # Смена 2 начинается в 08:00 локального времени

SHIFT_LABELS = {
    1: 'Смена 1 (00:00–07:59)',
    2: 'Смена 2 (08:00–23:59)',
}


# ---------------------------------------------------------------------------
# Журнал формирований отчётов (идентификатор отчёта)
# ---------------------------------------------------------------------------

def _plural(n, one, few, many):
    """Русские формы множественного числа: _plural(3, 'час', 'часа', 'часов')."""
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


def _fmt_duration(minutes):
    """Длительность простоя: 45 -> '45 минут', 75 -> '1 час 15 минут'."""
    minutes = int(minutes or 0)
    h, m = divmod(minutes, 60)
    if h == 0:
        return f'{m} {_plural(m, "минута", "минуты", "минут")}'
    if m == 0:
        return f'{h} {_plural(h, "час", "часа", "часов")}'
    return (f'{h} {_plural(h, "час", "часа", "часов")} '
            f'{m} {_plural(m, "минута", "минуты", "минут")}')


def _shift_segments(line, from_dt, to_dt):
    """Сегменты работы линии (задания) в пределах периода смены.

    Для каждого сегмента: код продукта, заводской код (1С), наименование,
    количество за период, время начала подсчёта (активации кода), временной
    диапазон периода и минуты простоя. Соседние сегменты с одинаковым кодом
    продукта сливаются в одну строку (начало подсчёта не повторяется).
    """
    assignments = list(
        line.assignments
        .filter(started_at__lt=to_dt)
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=from_dt))
        .select_related('product')
        .order_by('started_at')
    )
    segments = []
    for a in assignments:
        seg_start = max(from_dt, a.started_at)
        seg_end = to_dt if a.ended_at is None else min(to_dt, a.ended_at)
        if seg_end <= seg_start:
            continue
        count = (ProductionRecord.objects
                 .filter(line=line, assignment=a,
                         minute_start__gte=seg_start, minute_start__lt=seg_end)
                 .aggregate(t=Sum('count'))['t'] or 0)
        segments.append({
            'code': a.product.code,
            'code_1c': a.product.code_1c or '',
            'name': a.product.name,
            'count': count,
            'start': a.started_at,       # момент активации кода
            'seg_start': seg_start,      # диапазон внутри периода отчёта
            'seg_end': seg_end,
            'downtime': 0,
        })

    # слияние соседних сегментов с одинаковым кодом продукта
    merged = []
    for s in segments:
        if merged and merged[-1]['code'] == s['code'] and merged[-1]['code_1c'] == s['code_1c']:
            merged[-1]['count'] += s['count']
            merged[-1]['seg_end'] = s['seg_end']
        else:
            merged.append(dict(s))

    # простой по каждому итоговому сегменту (с учётом разрывов между ними)
    for s in merged:
        s['downtime'] = sum(
            e['minutes'] for e in services.downtime_events(line, s['seg_start'], s['seg_end'])
        )
    return merged


def _report_identity(line, tab, rtype, from_dt, to_dt, report_id):
    """Идентификатор отчёта: номер из журнала ReportLog для выбранного периода.

    Если передан report_id (при экспорте) — используется существующая запись,
    новый номер не создаётся.
    """
    if report_id:
        try:
            rl = ReportLog.objects.get(pk=report_id)
            return rl.identifier, rl.pk
        except (ReportLog.DoesNotExist, ValueError, TypeError):
            return None, None
    count = ReportLog.objects.filter(
        line=line, tab=tab, period_start=from_dt, period_end=to_dt,
    ).count()
    number = count + 1
    identifier = f'{timezone.localtime(from_dt):%Y%m%d}-{number:03d}'
    rl = ReportLog.objects.create(
        line=line, tab=tab, rtype=rtype,
        period_start=from_dt, period_end=to_dt,
        number=number, identifier=identifier,
    )
    return identifier, rl.pk


def _segment_rows(line, from_dt, to_dt):
    """Строки по сегментам (сменам кода продукта): колонки подробного отчёта.

    Возвращает (rows, total_count, total_downtime).
    """
    segments = _shift_segments(line, from_dt, to_dt)
    rows = []
    total_count = 0
    total_downtime = 0
    for s in segments:
        dt_str = _fmt_duration(s['downtime']) if s['downtime'] else '—'
        rows.append([
            s['code'],
            s['code_1c'] or '—',
            s['name'],
            f'{s["count"]:,}'.replace(',', ' '),
            timezone.localtime(s['start']).strftime('%H:%M'),
            f'{timezone.localtime(s["seg_start"]):%H:%M} – {timezone.localtime(s["seg_end"]):%H:%M}',
            dt_str,
        ])
        total_count += s['count']
        total_downtime += s['downtime']
    return rows, total_count, total_downtime


# ---------------------------------------------------------------------------
# Локальные SQL-выражения (агрегация по времени предприятия)
# ---------------------------------------------------------------------------

def _local_day():
    return RawSQL("date_trunc('day', minute_start AT TIME ZONE %s)", (TZ,))


def _local_month():
    return RawSQL("date_trunc('month', minute_start AT TIME ZONE %s)", (TZ,))


def _local_quarter():
    return RawSQL("date_trunc('quarter', minute_start AT TIME ZONE %s)", (TZ,))


def _local_hour():
    return RawSQL("EXTRACT(HOUR FROM minute_start AT TIME ZONE %s)::int", (TZ,))


def shift_of(dt):
    """Номер смены по локальному времени."""
    return 1 if dt.hour < SHIFT_BREAK_HOUR else 2


def _make_aware(naive):
    if naive is None:
        return None
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return naive


def _local_midnight(d):
    return timezone.make_aware(
        datetime.datetime(d.year, d.month, d.day), timezone.get_current_timezone(),
    )


def _products_map():
    """Код продукта -> {name, color, image, code_1c} (для тултипов графиков)."""
    return {
        p.code: {
            'name': p.name,
            'color': p.color or '#6c757d',
            'image': p.image.url if p.image else None,
            'code_1c': p.code_1c or '',
        }
        for p in Product.objects.all()
    }


def _chart_details_from_series(series, products_map):
    """Детали по каждой точке минутного ряда: продукт, цвет, картинка."""
    details = []
    for pt in series:
        code = pt.get('product_code')
        p = products_map.get(code) if code else None
        details.append({
            'code': code,
            'name': pt.get('product_name') or (p['name'] if p else None),
            'color': p['color'] if p else '#6c757d',
            'image': p['image'] if p else None,
            'code_1c': p['code_1c'] if p else '',
            'ts': pt.get('full_minute') or '',
        })
    return details


# ---------------------------------------------------------------------------
# Периоды
# ---------------------------------------------------------------------------

def resolve_period(tab, params):
    """Возвращает (from_dt, to_dt, label, error)."""
    tz = timezone.get_current_timezone()
    try:
        if tab == 'shift':
            date = datetime.datetime.strptime(params.get('date', ''), '%Y-%m-%d').date()
            shift = int(params.get('shift') or 1)
            if shift not in (1, 2):
                return None, None, '', 'Выберите смену (1 или 2).'
            day_start = _local_midnight(date)
            if shift == 1:
                from_dt, to_dt = day_start, day_start + datetime.timedelta(hours=8)
            else:
                from_dt, to_dt = day_start + datetime.timedelta(hours=8), day_start + datetime.timedelta(hours=24)
            label = f'{date.strftime("%d.%m.%Y")} · {SHIFT_LABELS[shift]}'
        elif tab == 'day':
            date = datetime.datetime.strptime(params.get('date', ''), '%Y-%m-%d').date()
            day_start = _local_midnight(date)
            from_dt, to_dt = day_start, day_start + datetime.timedelta(days=1)
            label = date.strftime('%d.%m.%Y')
        elif tab == 'month':
            year = int(params.get('year'))
            month = int(params.get('month'))
            first = datetime.date(year, month, 1)
            from_dt = _local_midnight(first)
            next_month = first.replace(day=1) + datetime.timedelta(days=calendar.monthrange(year, month)[1])
            to_dt = _local_midnight(next_month)
            label = f'{month:02d}.{year}'
        elif tab == 'quarter':
            year = int(params.get('year'))
            q = int(params.get('quarter') or 1)
            if q not in (1, 2, 3, 4):
                return None, None, '', 'Выберите квартал (I–IV).'
            start_month = (q - 1) * 3 + 1
            first = datetime.date(year, start_month, 1)
            from_dt = _local_midnight(first)
            if start_month == 10:
                to_dt = _local_midnight(datetime.date(year + 1, 1, 1))
            else:
                to_dt = _local_midnight(datetime.date(year, start_month + 3, 1))
            roman = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}[q]
            label = f'{roman} квартал {year}'
        elif tab == 'year':
            year = int(params.get('year'))
            from_dt = _local_midnight(datetime.date(year, 1, 1))
            to_dt = _local_midnight(datetime.date(year + 1, 1, 1))
            label = str(year)
        elif tab == 'period':
            from_dt = services.parse_dt(params.get('start'))
            to_dt = services.parse_dt(params.get('end'))
            if from_dt >= to_dt:
                return None, None, '', 'Начало периода должно быть раньше окончания.'
            label = (timezone.localtime(from_dt).strftime('%d.%m.%Y %H:%M') +
                     ' — ' + timezone.localtime(to_dt).strftime('%d.%m.%Y %H:%M'))
        else:
            return None, None, '', f'Неизвестная вкладка: {tab}'
    except (ValueError, TypeError):
        return None, None, '', 'Некорректные параметры периода (проверьте даты и год).'
    return from_dt, to_dt, label, None


# ---------------------------------------------------------------------------
# Агрегации
# ---------------------------------------------------------------------------

def _base_qs(line, from_dt, to_dt):
    return (ProductionRecord.objects
            .filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
            .select_related('assignment__product'))


def _per_product(line, from_dt, to_dt):
    qs = _base_qs(line, from_dt, to_dt)
    rows = list(qs.values('assignment__product__code', 'assignment__product__name')
                .annotate(total=Sum('count')).order_by('assignment__product__code'))
    total = qs.aggregate(t=Sum('count'))['t'] or 0
    return rows, total


def _per_day(line, from_dt, to_dt):
    qs = (ProductionRecord.objects.filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
          .annotate(day=_local_day()).values('day').annotate(total=Sum('count')).order_by('day'))
    return [{'day': _make_aware(r['day']), 'total': r['total']} for r in qs]


def _per_day_shift(line, from_dt, to_dt):
    qs = (ProductionRecord.objects
          .filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
          .annotate(day=_local_day(), hour=_local_hour())
          .values('day', 'hour').annotate(total=Sum('count')))
    acc = {}
    for r in qs:
        day = _make_aware(r['day'])
        sh = 1 if r['hour'] < SHIFT_BREAK_HOUR else 2
        acc.setdefault(day, {1: 0, 2: 0})
        acc[day][sh] += r['total']
    rows = []
    for day in sorted(acc):
        rows.append({'day': day, 'shift1': acc[day][1], 'shift2': acc[day][2],
                     'total': acc[day][1] + acc[day][2]})
    return rows


def _per_month(line, from_dt, to_dt):
    qs = (ProductionRecord.objects.filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
          .annotate(month=_local_month()).values('month').annotate(total=Sum('count')).order_by('month'))
    return [{'month': _make_aware(r['month']), 'total': r['total']} for r in qs]


def _per_quarter(line, from_dt, to_dt):
    qs = (ProductionRecord.objects.filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
          .annotate(quarter=_local_quarter()).values('quarter').annotate(total=Sum('count')).order_by('quarter'))
    return [{'quarter': _make_aware(r['quarter']), 'total': r['total']} for r in qs]


def _minute_records(line, from_dt, to_dt):
    return list(_base_qs(line, from_dt, to_dt).order_by('minute_start'))


# Простои
def _downtime_events(line, from_dt, to_dt):
    return services.downtime_events(line, from_dt, to_dt, timezone.now())


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


def _downtime_by(line, from_dt, to_dt, bucket):
    acc = {}
    for e in _downtime_events(line, from_dt, to_dt):
        key = _bucket_start(e['start'], bucket)
        acc[key] = acc.get(key, 0) + e['minutes']
    return sorted(acc.items())


# ---------------------------------------------------------------------------
# Построение таблиц
# ---------------------------------------------------------------------------

def _table(title, columns, rows, total_row=None, note=None, title_row=None):
    return {'title': title, 'columns': columns, 'rows': rows,
            'total_row': total_row, 'note': note, 'title_row': title_row}


def _rows_product_summary(line, from_dt, to_dt):
    rows, total = _per_product(line, from_dt, to_dt)
    out = []
    for r in rows:
        pct = (r['total'] / total * 100) if total else 0
        out.append([r['assignment__product__code'], r['assignment__product__name'],
                    f'{r["total"]:,}'.replace(',', ' '), f'{pct:.1f}%'.replace('.', ',')])
    return out, total


def _downtime_rows(events):
    rows = []
    for i, e in enumerate(events, start=1):
        rows.append([
            str(i),
            timezone.localtime(e['start']).strftime('%d.%m.%Y %H:%M'),
            timezone.localtime(e['end']).strftime('%d.%m.%Y %H:%M'),
            _fmt_duration(e['minutes']),
            f"{e['product_code']} — {e['product_name']}",
            'продолжается' if e['ongoing'] else 'завершён',
        ])
    return rows


# ---------------------------------------------------------------------------
# Сборка отчёта
# ---------------------------------------------------------------------------

REPORT_TYPES = {
    'shift': ['total', 'detail', 'downtime'],
    'day': ['total', 'detail_shifts', 'chart', 'downtime'],
    'month': ['by_shift', 'total_days', 'chart', 'downtime', 'gross'],
    'quarter': ['total_months', 'gross', 'by_shift', 'downtime'],
    'year': ['total_quarters', 'gross', 'by_shift', 'downtime'],
    'period': ['total_year', 'gross', 'by_shift', 'downtime', 'detail'],
}


def build_report(tab, rtype, counter_id, params):
    """Собирает отчёт: {'ok', 'tables': [...], 'chart': {...}|None, 'error', 'title', 'period_label'}."""
    try:
        counter = Counter.objects.select_related('line').get(pk=counter_id)
    except (Counter.DoesNotExist, TypeError, ValueError):
        return {'ok': False, 'error': 'Выберите счётчик.'}
    line = counter.line

    if tab not in REPORT_TYPES:
        return {'ok': False, 'error': f'Неизвестная вкладка: {tab}'}
    if rtype not in REPORT_TYPES[tab]:
        return {'ok': False, 'error': f'Неизвестный тип отчёта: {rtype}'}

    from_dt, to_dt, label, err = resolve_period(tab, params)
    if err:
        return {'ok': False, 'error': err}

    tables = []
    chart = None
    report_meta = None
    report_id_out = None

    def fmt_ts(dt):
        return timezone.localtime(dt).strftime('%d.%m.%Y %H:%M')

    # ----- Смена -----
    if tab == 'shift':
        shift_no = int(params.get('shift') or 1)
        identifier, report_id_out = _report_identity(
            line, tab, rtype, from_dt, to_dt, params.get('report_id'),
        )
        report_meta = [
            ('Счетчик №:', str(counter.pk)),
            ('Линия:', line.name),
            ('Смена:', f'Смена {shift_no}'),
            ('Период:', f'{fmt_ts(from_dt)} – {fmt_ts(to_dt)}'),
            ('Идентификатор отчета:', identifier or '—'),
        ]

        if rtype == 'total':
            # Итоговый: код продукта, заводской код, наименование, количество
            per_prod, _total = _per_product(line, from_dt, to_dt)
            rows = []
            for r in per_prod:
                code = r['assignment__product__code']
                p = _products_map().get(code, {})
                rows.append([
                    code,
                    p.get('code_1c') or '—',
                    r['assignment__product__name'],
                    f'{r["total"]:,}'.replace(',', ' '),
                ])
            tables.append(_table(
                '',  # название уже в шапке отчёта выше
                ['Код продукта', 'Заводской код', 'Наименование продукта', 'Количество'],
                rows,
                title_row=f'Смена {shift_no}',
            ))
        else:
            # Подробный и Простои: одинаковые колонки, различаются итогом
            rows, total_count, total_downtime = _segment_rows(line, from_dt, to_dt)
            columns = ['Код продукта', 'Заводской код', 'Наименование продукта',
                       'Кол-во продукции', 'Нач. подсчета', 'Период', 'Время простоя']
            if rtype == 'detail':
                # Итог — общее количество продукции
                tables.append(_table(
                    '',  # название уже в шапке отчёта выше
                    columns, rows,
                    total_row=['', '', 'ИТОГО', f'{total_count:,}'.replace(',', ' '),
                               '', '', ''],
                ))
            else:  # downtime
                # Итог — общее время простоя
                tables.append(_table(
                    '',  # название уже в шапке отчёта выше
                    columns, rows,
                    total_row=['', '', 'ИТОГО', '', '', '', _fmt_duration(total_downtime)],
                ))

    # ----- Сутки -----
    elif tab == 'day':
        identifier, report_id_out = _report_identity(
            line, tab, rtype, from_dt, to_dt, params.get('report_id'),
        )
        report_meta = [
            ('Счетчик №:', str(counter.pk)),
            ('Линия:', line.name),
            ('Период:', f'{fmt_ts(from_dt)} – {fmt_ts(to_dt)}'),
            ('Идентификатор отчета:', identifier or '—'),
        ]

        if rtype == 'total':
            # Итоговый за сутки (без разделения на смены)
            per_prod, _total = _per_product(line, from_dt, to_dt)
            rows = []
            for r in per_prod:
                code = r['assignment__product__code']
                p = _products_map().get(code, {})
                rows.append([
                    code,
                    p.get('code_1c') or '—',
                    r['assignment__product__name'],
                    f'{r["total"]:,}'.replace(',', ' '),
                ])
            tables.append(_table(
                '',  # название уже в шапке отчёта выше
                ['Код продукта', 'Заводской код', 'Наименование продукта', 'Количество'],
                rows,
            ))
        elif rtype == 'detail_shifts':
            # Подробный с раскладкой по сменам: две таблицы (Смена 1, Смена 2)
            shift1_to = from_dt + datetime.timedelta(hours=SHIFT_BREAK_HOUR)
            shift2_from = shift1_to
            columns = ['Код продукта', 'Заводской код', 'Наименование продукта',
                       'Кол-во продукции', 'Нач. подсчета', 'Период', 'Время простоя']
            for sh, (sf, st) in [(1, (from_dt, shift1_to)), (2, (shift2_from, to_dt))]:
                rows, total_count, _dt = _segment_rows(line, sf, st)
                tables.append(_table(
                    '',  # название уже в шапке отчёта выше
                    columns, rows,
                    total_row=['', '', 'ИТОГО', f'{total_count:,}'.replace(',', ' '),
                               '', '', ''],
                    title_row=f'Смена {sh}',
                ))
        elif rtype == 'chart':
            series = services.build_minute_series(line, from_dt, to_dt)
            products_map = _products_map()
            details = _chart_details_from_series(series, products_map)
            events = services.downtime_events(line, from_dt, to_dt)
            chart = {
                'type': 'bar',
                'title': 'График продукции (по минутам)',
                'labels': [s['minute'] for s in series],
                'datasets': [{
                    'label': 'Кол-во, шт./мин',
                    'data': [s['count'] for s in series],
                }],
                'details': details,
                'colors': [d['color'] for d in details],
                # индекс минуты (ISO) == индекс столбца; события простоя для столбиков
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
            # График без текстовой плашки: таблиц нет, отображается только график
        elif rtype == 'downtime':
            # Простои за сутки — как на вкладке «Смена», итог — общее время простоя
            rows, _tc, total_downtime = _segment_rows(line, from_dt, to_dt)
            columns = ['Код продукта', 'Заводской код', 'Наименование продукта',
                       'Кол-во продукции', 'Нач. подсчета', 'Период', 'Время простоя']
            tables.append(_table(
                '',  # название уже в шапке отчёта выше
                columns, rows,
                total_row=['', '', 'ИТОГО', '', '', '', _fmt_duration(total_downtime)],
            ))

    # ----- Месяц -----
    elif tab == 'month':
        if rtype == 'by_shift':
            rows = [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 1', r['shift1']]
                    for r in _per_day_shift(line, from_dt, to_dt)]
            rows += [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 2', r['shift2']]
                     for r in _per_day_shift(line, from_dt, to_dt)]
            rows.sort(key=lambda x: (datetime.datetime.strptime(x[0], '%d.%m.%Y'), x[1] == 'Смена 1'))
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total],
            ))
        elif rtype == 'total_days':
            days = _per_day(line, from_dt, to_dt)
            rows = [[timezone.localtime(r['day']).strftime('%d.%m.%Y'),
                     f'{r["total"]:,}'.replace(',', ' ')] for r in days]
            total = sum(r['total'] for r in days)
            prod_rows, prod_total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями по дням)',
                ['Дата', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', f'{total:,}'.replace(',', ' ')]))
            tables.append(_table(
                'По продуктам за месяц',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                prod_rows, total_row=['', 'ИТОГО', f'{prod_total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'chart':
            # Сумма по дням + доминирующий продукт за день (для тултипов)
            qs = (ProductionRecord.objects
                  .filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
                  .annotate(day=_local_day(), code=F('assignment__product__code'),
                            name=F('assignment__product__name'))
                  .values('day', 'code', 'name')
                  .annotate(total=Sum('count')))
            by_day = {}
            for r in qs:
                day = _make_aware(r['day'])
                if day not in by_day or r['total'] > by_day[day]['total']:
                    by_day[day] = {'code': r['code'], 'name': r['name'], 'total': r['total']}
            days = sorted(by_day.keys())
            products_map = _products_map()
            details = []
            for d in days:
                code = by_day[d]['code']
                p = products_map.get(code) if code else None
                details.append({
                    'code': code,
                    'name': by_day[d]['name'] or (p['name'] if p else None),
                    'color': p['color'] if p else '#6c757d',
                    'image': p['image'] if p else None,
                    'code_1c': p['code_1c'] if p else '',
                    'ts': timezone.localtime(d).strftime('%d.%m.%Y'),
                })
            dt_by_day = dict(_downtime_by(line, from_dt, to_dt, 'day'))
            chart = {
                'type': 'bar',
                'title': 'График продукции (по дням)',
                'labels': [timezone.localtime(d).strftime('%d.%m') for d in days],
                'datasets': [{'label': 'Кол-во, шт./день',
                              'data': [by_day[d]['total'] for d in days]}],
                'details': details,
                'colors': [d['color'] for d in details],
                # минуты простоя по дням (столбики второго датасета)
                'downtime_by_day': [dt_by_day.get(d, 0) for d in days],
            }
            # График без текстовой плашки: таблиц нет, отображается только график
        elif rtype == 'downtime':
            items = _downtime_by(line, from_dt, to_dt, 'day')
            rows = [[timezone.localtime(d).strftime('%d.%m.%Y'), _fmt_duration(m)] for d, m in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по дням)',
                ['Дата', 'Время простоя'], rows,
                total_row=['ИТОГО', _fmt_duration(total)]))
        elif rtype == 'gross':
            rows, total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                rows, total_row=['', 'ИТОГО', f'{total:,}'.replace(',', ' '), '100,0%']))

    # ----- Квартал -----
    elif tab == 'quarter':
        if rtype == 'total_months':
            months = _per_month(line, from_dt, to_dt)
            rows = [[timezone.localtime(r['month']).strftime('%m.%Y'),
                     f'{r["total"]:,}'.replace(',', ' ')] for r in months]
            total = sum(r['total'] for r in months)
            prod_rows, prod_total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями за месяцы)',
                ['Месяц', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', f'{total:,}'.replace(',', ' ')]))
            tables.append(_table(
                'По продуктам за квартал',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                prod_rows, total_row=['', 'ИТОГО', f'{prod_total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'gross':
            rows, total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                rows, total_row=['', 'ИТОГО', f'{total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'by_shift':
            rows = [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 1', r['shift1']]
                    for r in _per_day_shift(line, from_dt, to_dt)]
            rows += [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 2', r['shift2']]
                     for r in _per_day_shift(line, from_dt, to_dt)]
            rows.sort(key=lambda x: (datetime.datetime.strptime(x[0], '%d.%m.%Y'), x[1] == 'Смена 1'))
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(line, from_dt, to_dt, 'month')
            rows = [[timezone.localtime(m).strftime('%m.%Y'), _fmt_duration(mins)] for m, mins in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по месяцам)',
                ['Месяц', 'Время простоя'], rows,
                total_row=['ИТОГО', _fmt_duration(total)]))

    # ----- Год -----
    elif tab == 'year':
        if rtype == 'total_quarters':
            quarters = _per_quarter(line, from_dt, to_dt)
            rows = [[timezone.localtime(r['quarter']).strftime('%Y-%m'),
                     f'{r["total"]:,}'.replace(',', ' ')] for r in quarters]
            total = sum(r['total'] for r in quarters)
            prod_rows, prod_total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (с промежуточными значениями за кварталы)',
                ['Квартал', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', f'{total:,}'.replace(',', ' ')]))
            tables.append(_table(
                'По продуктам за год',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                prod_rows, total_row=['', 'ИТОГО', f'{prod_total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'gross':
            rows, total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                rows, total_row=['', 'ИТОГО', f'{total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'by_shift':
            rows = [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 1', r['shift1']]
                    for r in _per_day_shift(line, from_dt, to_dt)]
            rows += [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 2', r['shift2']]
                     for r in _per_day_shift(line, from_dt, to_dt)]
            rows.sort(key=lambda x: (datetime.datetime.strptime(x[0], '%d.%m.%Y'), x[1] == 'Смена 1'))
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(line, from_dt, to_dt, 'quarter')
            rows = []
            for q, mins in items:
                qn = (timezone.localtime(q).month - 1) // 3 + 1
                rows.append([timezone.localtime(q).strftime('%Y'), f'{qn} кв.', _fmt_duration(mins)])
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по кварталам)',
                ['Год', 'Квартал', 'Время простоя'], rows,
                total_row=['', 'ИТОГО', _fmt_duration(total)]))

    # ----- Период -----
    elif tab == 'period':
        if rtype == 'total_year':
            months = _per_month(line, from_dt, to_dt)
            rows = [[timezone.localtime(r['month']).strftime('%m.%Y'),
                     f'{r["total"]:,}'.replace(',', ' ')] for r in months]
            total = sum(r['total'] for r in months)
            prod_rows, prod_total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт итоговый (в пределах года, по месяцам)',
                ['Месяц', 'Кол-во, шт.'], rows,
                total_row=['ИТОГО', f'{total:,}'.replace(',', ' ')]))
            tables.append(_table(
                'По продуктам за период',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                prod_rows, total_row=['', 'ИТОГО', f'{prod_total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'gross':
            rows, total = _rows_product_summary(line, from_dt, to_dt)
            tables.append(_table(
                'Отчёт валовый по всем сменам (по продуктам)',
                ['Код', 'Продукт', 'Кол-во, шт.', '%'],
                rows, total_row=['', 'ИТОГО', f'{total:,}'.replace(',', ' '), '100,0%']))
        elif rtype == 'by_shift':
            rows = [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 1', r['shift1']]
                    for r in _per_day_shift(line, from_dt, to_dt)]
            rows += [[timezone.localtime(r['day']).strftime('%d.%m.%Y'), 'Смена 2', r['shift2']]
                     for r in _per_day_shift(line, from_dt, to_dt)]
            rows.sort(key=lambda x: (datetime.datetime.strptime(x[0], '%d.%m.%Y'), x[1] == 'Смена 1'))
            total = sum(r[2] for r in rows)
            tables.append(_table(
                'Отчёт по смене (по дням)',
                ['Дата', 'Смена', 'Кол-во, шт.'],
                rows, total_row=['', 'ИТОГО', total]))
        elif rtype == 'downtime':
            items = _downtime_by(line, from_dt, to_dt, 'day')
            rows = [[timezone.localtime(d).strftime('%d.%m.%Y'), _fmt_duration(mins)] for d, mins in items]
            total = sum(m for _, m in items)
            tables.append(_table(
                'Отчёт о простоях (сводный, по дням)',
                ['Дата', 'Время простоя'], rows,
                total_row=['ИТОГО', _fmt_duration(total)]))
        elif rtype == 'detail':
            if (to_dt - from_dt) > datetime.timedelta(days=2):
                return {'ok': False,
                        'error': 'Отчёт подробный формируется за период не более 2 суток.'}
            rows = []
            run = 0
            for r in _minute_records(line, from_dt, to_dt):
                run += r.count
                rows.append([
                    timezone.localtime(r.minute_start).strftime('%d.%m.%Y %H:%M'),
                    r.assignment.product.code if r.assignment else '—',
                    r.assignment.product.name if r.assignment else '—',
                    r.count, run,
                ])
            total = run
            tables.append(_table(
                'Отчёт подробный за период (по минутам)',
                ['Время', 'Код', 'Продукт', 'Кол-во, шт.', 'Накопительно'],
                rows, total_row=['', '', 'ИТОГО', total, ''],
            ))

    if not tables and chart is None:
        return {'ok': False, 'error': 'Нет данных для формирования отчёта.'}

    type_labels = {
        'total': 'Отчёт итоговый', 'detail': 'Отчёт подробный',
        'detail_shifts': 'Отчёт подробный (по сменам)', 'chart': 'График продукции',
        'downtime': 'Отчёт о простоях', 'by_shift': 'Отчёт по смене',
        'total_days': 'Отчёт итоговый по дням', 'gross': 'Отчёт валовый',
        'total_months': 'Отчёт итоговый по месяцам', 'total_quarters': 'Отчёт итоговый по кварталам',
        'total_year': 'Отчёт итоговый в пределах года',
    }
    return {
        'ok': True,
        'tables': tables,
        'chart': chart,
        'error': None,
        'title': f'{type_labels.get(rtype, rtype)}',
        'period_label': label,
        'counter': str(counter),
        'line': str(line),
        'meta': report_meta,
        'report_id': report_id_out,
        'range': {
            'from': timezone.localtime(from_dt).isoformat(),
            'to': timezone.localtime(to_dt).isoformat(),
        },
    }