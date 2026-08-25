"""Представления веб-интерфейса."""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from . import dbf_reader, dbf_reporting, reporting, services
from .decorators import can_manage, role_required
from .forms import ProductForm
from .models import (
    Counter, Line, Product, ProductAssignment, ProductionRecord, Shop, SystemConfig,
)
from .reports import (
    build_day_chart_xlsx, build_downtime_csv, build_downtime_xlsx,
    export_reports_bundle_csv, export_reports_bundle_xlsx,
    export_tables_csv, export_tables_xlsx,
)


def _fmt_dt(dt):
    return timezone.localtime(dt).strftime('%d.%m.%Y %H:%M') if dt else '—'


def _fmt_int(n):
    try:
        return f'{int(n):,}'.replace(',', ' ')
    except (TypeError, ValueError):
        return '0'


@login_required
def home(request):
    """Главная: статистика предприятия."""
    now = timezone.now()
    today_start = services.today_local_start()
    lines = Line.objects.select_related('shop', 'current_product', 'current_assignment__product')
    # «Линии в работе» — линии, где установлен код, отличный от кода отладки 888
    working_lines = [
        l for l in lines
        if l.is_working and not (l.current_product and l.current_product.code == Line.STATUS_CODE_DEBUG)
    ]
    today_total = (ProductionRecord.objects
                   .filter(minute_start__gte=today_start)
                   .aggregate(total=Sum('count'))['total'] or 0)
    today_assignments = ProductAssignment.objects.filter(started_at__gte=today_start).count()

    # Производительность за последний час по каждой работающей линии
    last_hour_start = now - timezone.timedelta(minutes=60)
    hour_stats = {
        s['line_id']: s['count']
        for s in ProductionRecord.objects
        .filter(minute_start__gte=last_hour_start)
        .values('line_id').annotate(count=Sum('count'))
    }
    for line in working_lines:
        hour_count = hour_stats.get(line.pk, 0)
        line.hour_count = hour_count
        norm = line.performance_per_hour or 0
        if norm > 0:
            line.perf_percent = min(100, round(hour_count / norm * 100))
        else:
            line.perf_percent = None

    # Простои за сегодня (в минутах) по каждой линии — колонка в таблице «Линии»
    today_downtime_minutes = 0
    for line in lines:
        events = services.downtime_events(line, today_start, now)
        minutes = sum(e['minutes'] for e in events)
        line.downtime_today = minutes
        today_downtime_minutes += minutes

    context = {
        'working_lines': working_lines,
        'today_total': today_total,
        'today_assignments': today_assignments,
        'today_downtime_minutes': today_downtime_minutes,
        'fmt_dt': _fmt_dt,
        'fmt_int': _fmt_int,
    }
    return render(request, 'dashboard/home.html', context)


@login_required
def shop_list(request):
    shops = list(Shop.objects.annotate(
        lines_count=Count('lines'),
        active_count=Count('lines', filter=Q(lines__is_active=True)),
    ).order_by('name'))
    today_start = services.today_local_start()
    now = timezone.now()
    for shop in shops:
        shop.today_total = (ProductionRecord.objects
                            .filter(line__shop=shop, minute_start__gte=today_start)
                            .aggregate(t=Sum('count'))['t'] or 0)
        dt_minutes = 0
        for line in shop.lines.all():
            dt_minutes += sum(e['minutes'] for e in services.downtime_events(line, today_start, now))
        shop.today_downtime = dt_minutes
    return render(request, 'dashboard/shops.html', {'shops': shops})


@login_required
def shop_detail(request, pk):
    shop = get_object_or_404(Shop, pk=pk)
    lines = (shop.lines
             .select_related('current_product', 'current_assignment__product')
             .order_by('number'))
    today_start = services.today_local_start()
    for line in lines:
        line.today_total = (ProductionRecord.objects
                            .filter(line=line, minute_start__gte=today_start)
                            .aggregate(t=Sum('count'))['t'] or 0)
    return render(request, 'dashboard/shop_detail.html', {
        'shop': shop, 'lines': lines, 'fmt_dt': _fmt_dt,
    })


@login_required
def line_list(request):
    shop_id = request.GET.get('shop')
    qs = (Line.objects.select_related('shop', 'current_product', 'current_assignment__product')
          .order_by('shop__code', 'number'))
    if shop_id:
        qs = qs.filter(shop_id=shop_id)
    lines = list(qs)
    return render(request, 'dashboard/lines.html', {
        'lines': lines,
        'shops': Shop.objects.all(),
        'active_shop': shop_id,
        'fmt_dt': _fmt_dt,
    })


@login_required
def line_detail(request, pk):
    line = get_object_or_404(
        Line.objects.select_related('shop', 'current_product',
                                    'current_assignment__product'), pk=pk)
    assignment = line.current_assignment
    products = (Product.objects
                .filter(Q(shop=line.shop) | Q(shop__isnull=True))
                .order_by('code'))
    context = {
        'line': line,
        'assignment': assignment,
        'products': products,
        'can_manage': can_manage(request.user),
        'fmt_dt': _fmt_dt,
    }
    return render(request, 'dashboard/line_detail.html', context)


@login_required
@role_required('admin', 'operator')
def line_switch_product(request, pk):
    """Ручная смена ключа продукта на линии (с подтверждением пин-кодом).

    Двухшаговый Ajax-сценарий:
      action=verify   — проверка пин-кода, смена ещё не выполняется;
      action=confirm  — пин-код уже проверен, выполняем смену продукта.
    При неверном пин-коде (или его отсутствии) возвращается
    «Операция отклонена», смена не выполняется.
    """
    line = get_object_or_404(Line, pk=pk)
    if request.method != 'POST':
        return redirect('line_detail', pk=line.pk)
    is_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    product_code = (request.POST.get('product_code') or '').strip()
    pin = (request.POST.get('pin') or '').strip()
    action = request.POST.get('action') or 'confirm'

    cfg = SystemConfig.get()
    expected = (cfg.switch_pin or '').strip() or '2020'
    if pin != expected:
        if is_json:
            return JsonResponse({'ok': False, 'error': 'Операция отклонена'}, status=400)
        messages.error(request, 'Операция отклонена: неверный пин-код.')
        return redirect('line_detail', pk=line.pk)

    if action == 'verify':
        current_code = line.current_product.code if line.current_product else '—'
        return JsonResponse({'ok': True, 'current_code': current_code,
                             'new_code': product_code or '—'})

    # action == 'confirm' — выполняем смену
    try:
        services.switch_product(line.pk, product_code)
        if is_json:
            return JsonResponse({'ok': True, 'message': f'Код продукта изменён на {product_code}.'})
        messages.success(request, f'Продукт {product_code} установлен на линии.')
    except ValueError as exc:
        if is_json:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))
    return redirect('line_detail', pk=line.pk)


# ---------------------------------------------------------------------------
# Отчёты (новая вкладка: Смена / Сутки / Месяц / Квартал / Год / Период)
# ---------------------------------------------------------------------------

@login_required
def reports_page(request):
    """Вкладка «Отчёты». Источник данных зависит от настройки SystemConfig:
    база данных (Counter/ProductionRecord) или файлы DBF (запасной режим)."""
    cfg = SystemConfig.get()
    now = timezone.now()
    now_local = timezone.localtime(now)
    years = list(range(now_local.year, now_local.year - 6, -1))
    counters_json = []
    counter_options = []

    if cfg.data_source == SystemConfig.DATA_SOURCE_DBF:
        # В режиме DBF «счётчиками» являются коды, найденные в именах файлов
        # (например, 20442023.dbf -> код 2044). Файл за нужный период
        # подбирается автоматически при формировании отчёта.
        codes = dbf_reader.list_counter_codes(cfg.resolved_dbf_dir())
        latest_last = None  # самая поздняя дата данных среди всех файлов
        for code, info in sorted(codes.items()):
            if info['last'] and (latest_last is None or info['last'] > latest_last):
                latest_last = info['last']
            label = f'Счётчик {code}'
            if info['first'] and info['last']:
                label += (f' · {info["first"].strftime("%d.%m.%Y")} – '
                          f'{info["last"].strftime("%d.%m.%Y")}')
            # Актуальность файла: дата и время последнего редактирования
            if info.get('modified'):
                label += (f' · обновлён {info["modified"].strftime("%d.%m.%Y %H:%M")}')
            counters_json.append({
                'id': code,
                'name': f'Счётчик {code}',
                'line': code,
                'first_record': info['first'].isoformat() if info['first'] else None,
                # «Весь период» в DBF должен брать последнюю дату в файле,
                # а не текущее время (файлы могут заканчиваться раньше)
                'now': info['last'].isoformat() if info['last'] else now.isoformat(),
            })
            counter_options.append({'id': code, 'label': label})
        # В DBF дата/время по умолчанию — конец данных, а не «сейчас»,
        # иначе у свежедобавленного блока дата вне диапазона файлов → «нет счётчика»
        if latest_last:
            latest_local = timezone.localtime(latest_last)
            now_local = latest_local
            years = list(range(latest_local.year, latest_local.year - 6, -1))
    else:
        for c in Counter.objects.select_related('line').order_by('id'):
            first = (ProductionRecord.objects
                     .filter(line=c.line).order_by('minute_start')
                     .values_list('minute_start', flat=True).first())
            counters_json.append({
                'id': c.pk,
                'name': c.name,
                'line': c.line.name,
                'first_record': first.isoformat() if first else None,
                'now': now.isoformat(),
            })
            counter_options.append({'id': c.pk, 'label': f'{c.name} ({c.line.name})'})

    return render(request, 'dashboard/reports.html', {
        'counter_options': counter_options,
        'counters_json': json.dumps(counters_json, ensure_ascii=False),
        'years': years,
        'today': now_local.strftime('%Y-%m-%d'),
        'now_local': now_local.strftime('%Y-%m-%dT%H:%M'),
        'data_source_label': cfg.get_data_source_display(),
        'data_source_dbf': cfg.data_source == SystemConfig.DATA_SOURCE_DBF,
        'is_admin': getattr(getattr(request.user, 'profile', None), 'role', None) == 'admin',
    })


@login_required
@role_required('admin')
def reports_toggle_source(request):
    """Переключение источника данных для отчётов: БД PostgreSQL <-> файлы DBF."""
    if request.method == 'POST':
        cfg = SystemConfig.get()
        cfg.data_source = (
            SystemConfig.DATA_SOURCE_DBF
            if cfg.data_source == SystemConfig.DATA_SOURCE_DB
            else SystemConfig.DATA_SOURCE_DB
        )
        cfg.save()
        messages.success(request, f'Источник данных переключён: {cfg.get_data_source_display()}.')
    return redirect('reports')


def site_logo(request):
    """Логотип проекта: файл logo.svg (или logo.png) в корне.

    Доступен всем (включая страницу входа), без авторизации.
    """
    base = settings.BASE_DIR.parent
    for name, ctype in (('logo.svg', 'image/svg+xml'), ('logo.png', 'image/png')):
        path = base / name
        if path.is_file():
            return FileResponse(open(path, 'rb'), content_type=ctype)
    raise Http404('Логотип не найден')


@login_required
def reports_build(request):
    """POST JSON: {'counter': id, 'tab': ..., 'type': ..., ...} -> таблицы + график."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Метод не поддерживается'}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    tab = data.get('tab') or 'shift'
    rtype = data.get('type') or 'total'
    cfg = SystemConfig.get()
    if cfg.data_source == SystemConfig.DATA_SOURCE_DBF:
        result = dbf_reporting.build_report(
            tab=tab, rtype=rtype, counter_id=data.get('counter'), params=data,
        )
    else:
        result = reporting.build_report(
            tab=tab, rtype=rtype, counter_id=data.get('counter'), params=data,
        )
    if not result.get('ok'):
        return JsonResponse({'ok': False, 'error': result.get('error', 'Ошибка формирования отчёта')})
    # Отчёт-график может не содержать таблиц (только график) — HTML пустой
    html = ''
    if result.get('tables'):
        html = render_to_string(
            'dashboard/_report_tables.html', {'result': result, 'fmt_int': _fmt_int},
        )
    return JsonResponse({'ok': True, 'html': html, 'result': {
        'title': result.get('title'),
        'period_label': result.get('period_label'),
        'chart': result.get('chart'),
        'range': result.get('range'),
        'report_id': result.get('report_id'),
    }})


@login_required
def reports_export(request):
    """Экспорт сформированного отчёта (xlsx/csv). Параметры как у reports_build."""
    fmt = (request.GET.get('fmt') or 'xlsx').lower()
    tab = request.GET.get('tab') or 'shift'
    rtype = request.GET.get('type') or 'total'
    cfg = SystemConfig.get()
    if cfg.data_source == SystemConfig.DATA_SOURCE_DBF:
        result = dbf_reporting.build_report(
            tab=tab, rtype=rtype, counter_id=request.GET.get('counter'),
            params=request.GET,
        )
    else:
        result = reporting.build_report(
            tab=tab, rtype=rtype, counter_id=request.GET.get('counter'),
            params=request.GET,
        )
    if not result.get('ok'):
        messages.error(request, result.get('error', 'Не удалось сформировать отчёт.'))
        return redirect('reports')

    stamp = timezone.localtime().strftime('%Y-%m-%d_%H-%M')
    tab_label = {
        'shift': 'Смена', 'day': 'Сутки', 'month': 'Месяц',
        'quarter': 'Квартал', 'year': 'Год', 'period': 'Период',
    }.get(tab, tab)
    meta = {
        'title': f'{result.get("title")} ({tab_label})',
        'period_label': result.get('period_label', ''),
        'counter': result.get('counter', ''),
        'generated_at': timezone.localtime().strftime('%d.%m.%Y %H:%M'),
        # Шапка отчёта («Счетчик №:», «Линия:», ...) — в начало файла
        'report_meta': result.get('meta') or [],
        'filename_xlsx': f'report_{request.GET.get("tab", "period")}_{request.GET.get("type", "total")}_{stamp}.xlsx',
        'filename_csv': f'report_{request.GET.get("tab", "period")}_{request.GET.get("type", "total")}_{stamp}.csv',
    }

    # График за сутки — выгрузка графическим Excel-файлом (4 части по 6 часов, A4)
    if (not result.get('tables')) and result.get('chart') and tab == 'day' and rtype == 'chart':
        if fmt != 'xlsx':
            messages.error(request, 'Для графика доступна только выгрузка в XLSX.')
            return redirect('reports')
        meta['filename_xlsx'] = f'chart_{request.GET.get("date", "day")}_{stamp}.xlsx'
        filename, payload = build_day_chart_xlsx(meta, result['chart'])
        response = HttpResponse(
            payload,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    if not result.get('tables'):
        messages.error(request, 'В этом отчёте только график — таблиц для выгрузки нет.')
        return redirect('reports')

    if fmt == 'csv':
        filename, payload = export_tables_csv(meta, result['tables'])
        content_type = 'text/csv; charset=utf-8'
    else:
        filename, payload = export_tables_xlsx(meta, result['tables'])
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response = HttpResponse(payload, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def reports_export_multi(request):
    """Пакетный экспорт нескольких сформированных отчётов в один файл.

    POST JSON: {'fmt': 'xlsx'|'csv', 'reports': [{tab, type, counter, ...}]}.
    Каждый отчёт — отдельный лист в Excel (мета-строки на каждом листе;
    график за сутки — 4 диаграммы по 6 часов на листе A4) либо блок строк в CSV.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Метод не поддерживается'}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    fmt = (data.get('fmt') or 'xlsx').lower()
    specs = data.get('reports') or []
    if not specs:
        return JsonResponse({'ok': False, 'error': 'Нет сформированных отчётов.'}, status=400)

    cfg = SystemConfig.get()
    tab_label = {
        'shift': 'Смена', 'day': 'Сутки', 'month': 'Месяц',
        'quarter': 'Квартал', 'year': 'Год', 'period': 'Период',
    }
    items = []
    for spec in specs:
        tab = spec.get('tab') or 'shift'
        rtype = spec.get('type') or 'total'
        if cfg.data_source == SystemConfig.DATA_SOURCE_DBF:
            result = dbf_reporting.build_report(
                tab=tab, rtype=rtype, counter_id=spec.get('counter'), params=spec,
            )
        else:
            result = reporting.build_report(
                tab=tab, rtype=rtype, counter_id=spec.get('counter'), params=spec,
            )
        if not result.get('ok'):
            return JsonResponse(
                {'ok': False, 'error': result.get('error', 'Ошибка формирования отчёта')},
                status=400,
            )
        meta = {
            'title': f'{result.get("title")} ({tab_label.get(tab, tab)})',
            'period_label': result.get('period_label', ''),
            'counter': result.get('counter', ''),
            'generated_at': timezone.localtime().strftime('%d.%m.%Y %H:%M'),
            'report_meta': result.get('meta') or [],
        }
        if result.get('tables'):
            items.append({'kind': 'table', 'meta': meta, 'tables': result.get('tables')})
        elif result.get('chart') and tab == 'day' and rtype == 'chart':
            # График продукции за сутки — отдельный лист с 4 диаграммами по 6 часов
            items.append({'kind': 'chart', 'meta': meta, 'chart': result['chart']})
        elif result.get('chart'):
            return JsonResponse(
                {'ok': False, 'error': 'Отчёт содержит только график — для выгрузки '
                                       'в Excel доступен график за сутки (Сутки → График продукции).'},
                status=400,
            )
        else:
            return JsonResponse(
                {'ok': False, 'error': 'В отчёте нет данных для выгрузки.'},
                status=400,
            )

    if not items:
        return JsonResponse({'ok': False, 'error': 'Нет сформированных отчётов.'}, status=400)

    if fmt == 'csv' and any(i.get('kind') == 'chart' for i in items):
        return JsonResponse(
            {'ok': False, 'error': 'Для графика доступна только выгрузка в XLSX.'},
            status=400,
        )

    if fmt == 'csv':
        filename, payload = export_reports_bundle_csv(items)
        content_type = 'text/csv; charset=utf-8'
    else:
        filename, payload = export_reports_bundle_xlsx(items)
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response = HttpResponse(payload, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Продукция
# ---------------------------------------------------------------------------

@login_required
def products_list(request):
    """Справочник продукции: пагинация сверху, выбор количества на странице."""
    q = (request.GET.get('q') or '').strip()
    per_page = request.GET.get('per_page') or '60'
    try:
        per_page = int(per_page)
        if per_page not in (20, 40, 60, 100):
            per_page = 60
    except ValueError:
        per_page = 60
    qs = Product.objects.all().order_by('code')
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(code_1c__icontains=q))
    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/products.html', {
        'page': page,
        'q': q,
        'per_page': per_page,
        'is_admin': can_manage(request.user) and request.user.profile.role == 'admin',
    })


@login_required
@role_required('admin')
def product_add(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            messages.success(request, f'Продукт {product.code} — «{product.name}» добавлен.')
            return redirect('products')
    else:
        form = ProductForm()
    return render(request, 'dashboard/product_form.html', {
        'form': form, 'mode': 'add',
    })


@login_required
@role_required('admin')
def product_edit(request, pk):
    """Полностраничное редактирование (запасной вариант)."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            product = form.save()
            messages.success(request, f'Продукт {product.code} обновлён.')
            return redirect('products')
    else:
        form = ProductForm(instance=product)
    return render(request, 'dashboard/product_form.html', {
        'form': form, 'mode': 'edit', 'product': product,
    })


@login_required
@role_required('admin')
def product_edit_modal(request, pk):
    """Редактирование продукта в диалоговом окне (GET — форма, POST — сохранение)."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            return JsonResponse({'ok': True})
        return JsonResponse({'ok': False, 'errors': form.errors.get_json_data()})
    form = ProductForm(instance=product)
    return render(request, 'dashboard/product_form_modal.html', {
        'form': form, 'product': product,
    })


@login_required
@role_required('admin')
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        code = product.code
        product.delete()
        messages.success(request, f'Продукт {code} удалён.')
    return redirect('products')


# ---------------------------------------------------------------------------
# Отчёт о простоях (старая вкладка объединена с «Отчётами»)
# ---------------------------------------------------------------------------

@login_required
def downtime_page(request):
    return redirect('reports')


@login_required
def downtime_export(request):
    """Экспорт отчёта о простоях (совместимость со старыми ссылками)."""
    fmt = (request.GET.get('fmt') or 'xlsx').lower()
    now = timezone.now()
    try:
        from_dt = services.parse_dt(request.GET.get('from'))
        to_dt = services.parse_dt(request.GET.get('to'))
    except ValueError:
        messages.error(request, 'Некорректный диапазон дат.')
        return redirect('reports')
    line_ids = [x for x in str(request.GET.get('lines') or '').split(',') if x.isdigit()]
    lines = Line.objects.select_related('shop').order_by('shop__code', 'number')
    if line_ids:
        lines = lines.filter(pk__in=line_ids)

    events = []
    for line in lines:
        events.extend(services.downtime_events(line, from_dt, to_dt, now))
    events.sort(key=lambda e: e['start'])

    stamp = timezone.localtime().strftime('%Y-%m-%d_%H-%M')
    meta = {
        'from_str': timezone.localtime(from_dt).strftime('%d.%m.%Y %H:%M'),
        'to_str': timezone.localtime(to_dt).strftime('%d.%m.%Y %H:%M'),
        'generated_at': timezone.localtime().strftime('%d.%m.%Y %H:%M'),
        'total_minutes': sum(e['minutes'] for e in events),
        'filename_xlsx': f'downtime_{stamp}.xlsx',
        'filename_csv': f'downtime_{stamp}.csv',
    }
    if fmt == 'csv':
        filename, payload = build_downtime_csv(meta, events)
        content_type = 'text/csv; charset=utf-8'
    else:
        filename, payload = build_downtime_xlsx(meta, events)
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response = HttpResponse(payload, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response