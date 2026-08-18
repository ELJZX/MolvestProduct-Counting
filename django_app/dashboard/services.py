"""Бизнес-логика: приём показаний контроллеров, смена продукта,
построение минутных рядов и данных для отчётов.
"""
import datetime
from collections import OrderedDict

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import ControllerReading, Line, Product, ProductAssignment, ProductionRecord

MINUTE = datetime.timedelta(minutes=1)
MAX_CHART_MINUTES = 7 * 24 * 60  # максимум 7 дней на диаграмме


def floor_minute(dt):
    """Начало минуты в локальном времени предприятия (aware datetime)."""
    local = timezone.localtime(dt)
    return local.replace(second=0, microsecond=0)


def parse_dt(value):
    """Разбор ISO-строки от контроллера/UI; naive интерпретируется как локальное время."""
    if not value:
        return timezone.now()
    from django.utils.dateparse import parse_datetime
    dt = parse_datetime(str(value))
    if dt is None:
        raise ValueError(f'Некорректная дата/время: {value!r}')
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def get_or_create_product(code):
    """Возвращает продукт по коду, при необходимости создаёт заглушку."""
    code = str(code).strip().zfill(3)
    if not (code.isdigit() and 1 <= int(code) <= 999):
        raise ValueError(f'Код продукта должен быть в диапазоне 001..999, получено: {code!r}')
    product, _ = Product.objects.get_or_create(
        code=code, defaults={'name': f'Продукт {code}'},
    )
    return product


@transaction.atomic
def record_reading(controller_id, product_code, count=None, delta=None,
                   at=None, target_quantity=None):
    """Обрабатывает одно показание контроллера ОВЕН.

    Параметры:
      controller_id  — идентификатор линии (controller_id у Line или её id)
      product_code   — код продукта 001..999
      count          — суммарное показание счётчика за смену продукта (кумулятивно)
      delta          — готовое приращение за приём (альтернатива count)
      at             — момент измерения (ISO или None = сейчас)
      target_quantity— план задания (опционально)

    Если присланный продукт отличается от текущего на линии, предыдущее
    задание закрывается и стартует новое — диаграмма начинается с этой минуты.
    """
    line = (Line.objects.filter(controller_id=str(controller_id)).first()
            or (Line.objects.filter(pk=controller_id).first()
                if str(controller_id).isdigit() else None))
    if line is None:
        raise ValueError(
            f'Линия с controller_id={controller_id!r} не найдена. '
            'Проверьте значение controller_id у линии.'
        )

    at = parse_dt(at) if at else timezone.now()
    product = get_or_create_product(product_code)

    # ---- Смена ключа продукта: закрываем старое задание, открываем новое ----
    assignment = line.current_assignment
    if assignment is None or assignment.product_id != product.pk or assignment.ended_at is not None:
        if assignment is not None and assignment.ended_at is None:
            assignment.ended_at = at
            assignment.save(update_fields=['ended_at'])
        assignment = ProductAssignment.objects.create(
            line=line, product=product, started_at=at,
            target_quantity=target_quantity,
        )
        line.current_product = product
        line.current_assignment = assignment
        line.save(update_fields=['current_product', 'current_assignment', 'last_seen'])

    # ---- Приращение ----
    prev = (ControllerReading.objects
            .filter(line=line, product=product)
            .order_by('-received_at').first())
    if delta is None:
        if count is None:
            raise ValueError('Не передано ни count (суммарное показание), ни delta (приращение).')
        count = int(count)
        delta = count if prev is None else count - prev.total
        if delta < 0:
            # Счётчик контроллера сброшен — считаем с нуля
            delta = count
    else:
        delta = int(delta)
        count = count if count is not None else ((prev.total + delta) if prev else delta)

    # ---- Минутная запись ----
    minute = floor_minute(at)
    record, _ = ProductionRecord.objects.get_or_create(
        line=line, minute_start=minute, defaults={'assignment': assignment, 'count': 0},
    )
    record.count += delta
    if record.assignment_id is None:
        record.assignment = assignment
    record.save(update_fields=['count', 'assignment'])

    assignment.total_count += delta
    assignment.save(update_fields=['total_count'])

    line.last_seen = at
    line.save(update_fields=['last_seen'])

    ControllerReading.objects.create(
        line=line, product=product, assignment=assignment,
        total=count, delta=delta, received_at=at,
    )

    return {
        'line': line.pk,
        'line_name': str(line),
        'product': product.code,
        'assignment_id': assignment.pk,
        'assignment_started_at': assignment.started_at.isoformat(),
        'delta': delta,
        'record_minute': minute.isoformat(),
        'record_count': record.count,
        'total_count': assignment.total_count,
    }


@transaction.atomic
def switch_product(line_id, product_code, at=None, target_quantity=None):
    """Принудительная смена ключа продукта на линии (UI)."""
    return record_reading(
        controller_id=line_id, product_code=product_code, delta=0,
        at=at, target_quantity=target_quantity,
    )


def current_assignment(line):
    return line.current_assignment if line.current_assignment_id else None


def default_range(line):
    """Диапазон по умолчанию: с момента смены ключа продукта до сейчас."""
    now = timezone.now()
    assignment = current_assignment(line)
    if assignment:
        from_dt = floor_minute(assignment.started_at)
    else:
        from_dt = today_local_start()
    return from_dt, now


def resolve_range(line, from_raw=None, to_raw=None, clamp=True):
    """Диапазон по запросу пользователя; None -> значения по умолчанию."""
    now = timezone.now()
    default_from, _ = default_range(line)
    from_dt = parse_dt(from_raw) if from_raw else default_from
    to_dt = parse_dt(to_raw) if to_raw else now
    if from_dt >= to_dt:
        raise ValueError('Начало диапазона должно быть раньше окончания.')
    if clamp and (to_dt - from_dt) > datetime.timedelta(minutes=MAX_CHART_MINUTES):
        from_dt = to_dt - datetime.timedelta(minutes=MAX_CHART_MINUTES)
    return floor_minute(from_dt), to_dt


def build_minute_series(line, from_dt, to_dt):
    """Минутный ряд [{minute, ts, count, assignment_id}] с заполнением нулей."""
    records = OrderedDict(
        (r.minute_start, r)
        for r in ProductionRecord.objects.filter(
            line=line, minute_start__gte=from_dt, minute_start__lt=floor_minute(to_dt),
        ).select_related('assignment__product')
    )
    series = []
    cur = from_dt
    end = floor_minute(to_dt)
    while cur < end:
        rec = records.get(cur)
        series.append({
            'minute': timezone.localtime(cur).strftime('%H:%M'),
            'full_minute': timezone.localtime(cur).strftime('%d.%m.%Y %H:%M'),
            'ts': cur.isoformat(),
            'count': rec.count if rec else 0,
            'assignment_id': rec.assignment_id if rec else None,
            'product_code': (rec.assignment.product.code
                             if rec and rec.assignment_id else None),
            'product_name': (rec.assignment.product.name
                             if rec and rec.assignment_id else None),
        })
        cur += MINUTE
    return series


def range_summary(line, from_dt, to_dt):
    """Итоги по выбранному диапазону: всего + разбивка по продуктам."""
    qs = (ProductionRecord.objects
          .filter(line=line, minute_start__gte=from_dt, minute_start__lt=floor_minute(to_dt))
          .select_related('assignment__product'))
    total = qs.aggregate(total=Sum('count'))['total'] or 0
    per_product = []
    rows = (qs.values('assignment__product__code', 'assignment__product__name')
            .annotate(count=Sum('count')).order_by('assignment__product__code'))
    for r in rows:
        per_product.append({
            'code': r['assignment__product__code'],
            'name': r['assignment__product__name'],
            'count': r['count'],
        })
    return {'total': total, 'per_product': per_product}


def today_local_start():
    """Начало текущих суток в локальном времени предприятия (aware)."""
    local_now = timezone.localtime()
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0)

# ---------------------------------------------------------------------------
# Простои
# ---------------------------------------------------------------------------

def downtime_events(line, from_dt, to_dt, now=None):
    """События простоя линии в диапазоне [from_dt, to_dt).

    Простоем считается время, когда линия должна работать (есть активное
    задание), но подсчёт продукции не ведётся более 1 минуты подряд.

    Возвращает список словарей:
      {line, line_name, shop_name, product_code, product_name,
       start, end, minutes, ongoing}
    """
    now = now or timezone.now()
    from_dt = floor_minute(from_dt)
    to_dt = floor_minute(to_dt)
    if to_dt <= from_dt:
        return []

    records = list(
        ProductionRecord.objects
        .filter(line=line, minute_start__gte=from_dt, minute_start__lt=to_dt)
        .order_by('minute_start')
    )
    by_minute = {r.minute_start: r for r in records}
    rec_minutes = sorted(by_minute.keys())

    assignments = list(
        line.assignments
        .filter(started_at__lt=to_dt)
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=from_dt))
        .select_related('product')
        .order_by('started_at')
    )

    events = []
    for assignment in assignments:
        seg_start = max(from_dt, floor_minute(assignment.started_at))
        if assignment.ended_at is None:
            seg_end = min(to_dt, floor_minute(now))
        else:
            seg_end = min(to_dt, floor_minute(assignment.ended_at))
        if seg_end <= seg_start:
            continue

        # минуты задания с данными в этом сегменте
        present = [m for m in rec_minutes if seg_start <= m < seg_end]

        if not present:
            # Нет данных вообще: весь сегмент — простой (если больше 1 минуты)
            total_min = int((seg_end - seg_start).total_seconds() // 60)
            if total_min > 1:
                events.append({
                    'line': line,
                    'line_name': str(line),
                    'shop_name': line.shop.name,
                    'product_code': assignment.product.code,
                    'product_name': assignment.product.name,
                    'start': seg_start,
                    'end': seg_end,
                    'minutes': total_min,
                    'ongoing': assignment.ended_at is None and seg_end >= floor_minute(now),
                })
            continue

        # идём по соседним записям, ищем пропуски > 1 минуты
        prev = present[0]
        for m in present[1:]:
            gap = int((m - prev).total_seconds() // 60)
            if gap > 1:
                d_start = prev + MINUTE
                d_end = m
                events.append({
                    'line': line,
                    'line_name': str(line),
                    'shop_name': line.shop.name,
                    'product_code': assignment.product.code,
                    'product_name': assignment.product.name,
                    'start': d_start,
                    'end': d_end,
                    'minutes': gap - 1,
                    'ongoing': False,
                })
            prev = m

        # хвост сегмента: данных больше нет до конца задания
        # (или до сейчас, если задание ещё активно — простой продолжается)
        if assignment.ended_at is None:
            tail_end = min(seg_end, floor_minute(now))
        else:
            tail_end = seg_end
        gap = int((tail_end - prev).total_seconds() // 60)
        if gap > 1:
            events.append({
                'line': line,
                'line_name': str(line),
                'shop_name': line.shop.name,
                'product_code': assignment.product.code,
                'product_name': assignment.product.name,
                'start': prev + MINUTE,
                'end': tail_end,
                'minutes': gap - 1,
                'ongoing': assignment.ended_at is None,
            })

    events.sort(key=lambda e: e['start'])
    return events


# ---------------------------------------------------------------------------
# Сравнение линий (вкладка «Отчёты»)
# ---------------------------------------------------------------------------

def comparison_data(lines_spec, now=None):
    """Данные для сравнительной диаграммы.

    lines_spec: список {line_id, from, to} — линия и свой период.
    Возвращает список серий: {line_id, name, color, from, to, series: [...]}.
    """
    now = now or timezone.now()
    result = []
    for spec in lines_spec:
        line_id = spec.get('line_id') or spec.get('id')
        if line_id is None:
            continue
        try:
            line = Line.objects.select_related('shop').get(pk=line_id)
        except (Line.DoesNotExist, KeyError, TypeError, ValueError):
            continue
        try:
            from_dt, to_dt = resolve_range(
                line, spec.get('from'), spec.get('to'), clamp=True,
            )
        except ValueError:
            continue
        series = build_minute_series(line, from_dt, to_dt)
        summary = range_summary(line, from_dt, to_dt)
        result.append({
            'line_id': line.pk,
            'name': str(line),
            'shop_name': line.shop.name,
            'color': _line_color(line.pk),
            'from': from_dt.isoformat(),
            'to': to_dt.isoformat(),
            'total': summary['total'],
            'series': series,
        })
    return result


def _line_color(line_pk):
    palette = ['#1f6feb', '#2da44e', '#bf8700', '#bf3989', '#8250df',
               '#0a8cff', '#0aac8e', '#d1242f', '#57606a', '#e5534b']
    return palette[line_pk % len(palette)]