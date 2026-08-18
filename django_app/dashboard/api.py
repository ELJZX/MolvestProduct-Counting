"""REST API.

POST /api/v1/counter/          — приём показаний от контроллеров ОВЕН
                                 (заголовок X-API-Key: <CONTROLLER_API_KEY>)
GET  /api/v1/lines/<id>/chart/ — данные минутной диаграммы для веб-интерфейса
GET  /api/v1/events/           — real-time события (SSE/socket): изменения линий
GET  /api/v1/sim/lines/        — список линий для сервиса-эмулятора (X-API-Key)
GET  /api/v1/sim/products/     — справочник продукции для эмулятора (X-API-Key)
GET  /api/v1/health/           — проверка доступности
"""
import hmac
import json
import time

from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Line, Product


class ControllerKeyPermission(BasePermission):
    """Доступ контроллеров по ключу из заголовка X-API-Key."""

    message = 'Неверный или отсутствующий X-API-Key контроллера.'

    def has_permission(self, request, view):
        key = request.headers.get('X-API-Key', '')
        expected = getattr(settings, 'CONTROLLER_API_KEY', '') or ''
        return bool(expected) and hmac.compare_digest(str(key).strip(), str(expected).strip())


class CounterView(APIView):
    """Точка приёма данных от контроллеров ОВЕН."""

    authentication_classes = []
    permission_classes = [ControllerKeyPermission]

    def post(self, request):
        data = request.data or {}
        try:
            result = services.record_reading(
                controller_id=data.get('controller_id') or data.get('line'),
                product_code=data.get('product') or data.get('product_code'),
                count=data.get('count'),
                delta=data.get('delta'),
                at=data.get('at') or data.get('timestamp'),
                target_quantity=data.get('target_quantity'),
            )
        except (ValueError, TypeError) as exc:
            return Response({'ok': False, 'error': str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({'ok': True, **result})


class LineChartView(APIView):
    """Минутный ряд для диаграммы линии (используется веб-интерфейсом)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            line = Line.objects.select_related('shop', 'current_product').get(pk=pk)
        except Line.DoesNotExist:
            return Response({'ok': False, 'error': 'Линия не найдена'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            from_dt, to_dt = services.resolve_range(
                line, request.query_params.get('from'), request.query_params.get('to'),
            )
        except ValueError as exc:
            return Response({'ok': False, 'error': str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)

        assignment = line.current_assignment
        series = services.build_minute_series(line, from_dt, to_dt)
        summary = services.range_summary(line, from_dt, to_dt)
        downtime = [
            {
                'start': timezone.localtime(e['start']).isoformat(),
                'end': timezone.localtime(e['end']).isoformat(),
                'minutes': e['minutes'],
                'ongoing': e['ongoing'],
                'product_code': e['product_code'],
                'product_name': e['product_name'],
            }
            for e in services.downtime_events(line, from_dt, to_dt)
        ]
        products_map = {
            p.code: {
                'name': p.name,
                'color': p.color or '#6c757d',
                'image': p.image.url if p.image else None,
                'code_1c': p.code_1c or '',
            }
            for p in Product.objects.all()
        }
        return Response({
            'ok': True,
            'line': {
                'id': line.pk,
                'name': line.name,
                'shop': line.shop.name,
                'controller_id': line.controller_id,
                'is_working': line.is_working,
                'last_seen': line.last_seen.isoformat() if line.last_seen else None,
            },
            'assignment': {
                'id': assignment.pk,
                'product_code': assignment.product.code,
                'product_name': assignment.product.name,
                'started_at': assignment.started_at.isoformat(),
                'total_count': assignment.total_count,
                'is_active': assignment.ended_at is None,
            } if assignment else None,
            'range': {
                'from': from_dt.isoformat(),
                'to': to_dt.isoformat(),
                'now': timezone.now().isoformat(),
            },
            'series': series,
            'summary': summary,
            'products': products_map,
            'downtime': downtime,
        })


class HealthView(APIView):
    """Проверка, что сервис жив."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({
            'ok': True,
            'service': 'product-counting',
            'time': timezone.now().isoformat(),
            'lines': Line.objects.count(),
        })

# ---------------------------------------------------------------------------
# Real-time события (SSE / socket)
# ---------------------------------------------------------------------------

class EventsView(APIView):
    """Поток событий Server-Sent Events для обновления интерфейса в реальном
    времени.

    Клиент подключается по GET /api/v1/events/ (EventSource) и получает
    события:
      event: line_update   data: {"line_id": N}  — по линии N изменились данные
                                                    (контроллер передал показания)
      event: ping          — сердцебиение, чтобы соединение не обрывалось
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        response = StreamingHttpResponse(
            self._stream(),
            content_type='text/event-stream; charset=utf-8',
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response

    def _stream(self):
        # состояние: line_id -> последний last_seen (ISO-строка)
        seen = {}
        last_ping = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now - last_ping >= 15:
                    yield ': ping' + chr(10) * 2
                    last_ping = now

                rows = list(
                    Line.objects.filter(is_active=True).values('id', 'last_seen')
                )
                changed = []
                for row in rows:
                    key = row['last_seen'].isoformat() if row['last_seen'] else None
                    if row['id'] in seen and seen[row['id']] != key:
                        changed.append(row['id'])
                    seen[row['id']] = key

                if changed:
                    for line_id in changed:
                        payload = json.dumps({'line_id': line_id})
                        yield 'event: line_update\ndata: ' + payload + '\n\n'
                time.sleep(2)
        except GeneratorExit:
            return


# ---------------------------------------------------------------------------
# Сервис-эмулятор линии (тестирование)
# ---------------------------------------------------------------------------

class SimLinesView(APIView):
    """Список линий для сервиса-эмулятора (окно браузера с кликами).

    Доступ по X-API-Key, как у контроллеров ОВЕН.
    """

    authentication_classes = []
    permission_classes = [ControllerKeyPermission]

    def get(self, request):
        lines = Line.objects.select_related('shop').filter(is_active=True).order_by('shop__code', 'number')
        data = []
        for line in lines:
            a = line.current_assignment
            data.append({
                'id': line.pk,
                'controller_id': line.controller_id,
                'number': line.number,
                'name': line.name,
                'shop': line.shop.name,
                'shop_code': line.shop.code,
                'product_code': line.current_product.code if line.current_product else None,
                'product_name': line.current_product.name if line.current_product else None,
                'total_count': a.total_count if a else 0,
                'assignment_started_at': a.started_at.isoformat() if a else None,
            })
        return Response({'ok': True, 'lines': data})


class SimProductsView(APIView):
    """Справочник продукции для сервиса-эмулятора.

    Доступ по X-API-Key, как у контроллеров ОВЕН.
    """

    authentication_classes = []
    permission_classes = [ControllerKeyPermission]

    def get(self, request):
        products = [
            {
                'code': p.code,
                'name': p.name,
                'code_1c': p.code_1c or '',
            }
            for p in Product.objects.all().order_by('code')
        ]
        return Response({'ok': True, 'products': products})


# ---------------------------------------------------------------------------
# Отчёты о простоях: данные для графиков
# ---------------------------------------------------------------------------

def _fmt_duration(minutes):
    if minutes >= 60:
        return f'{minutes // 60} ч {minutes % 60} мин.'
    return f'{minutes} мин.'


class DowntimeChartView(APIView):
    """Данные для графиков простоев по нескольким линиям и периодам.

    POST JSON: {"lines": [{"id": 1, "from": "...", "to": "..."}, ...]}

    Для каждой линии возвращаются минутный ряд (продукция), события простоя
    и итоги. График продукции накладывается на график простоев на клиенте.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        lines_spec = data.get('lines') or []
        if not isinstance(lines_spec, list) or not lines_spec:
            return Response({'ok': False, 'error': 'Передайте хотя бы одну линию (lines)'},
                            status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        result = []
        for spec in lines_spec:
            line_id = spec.get('id') or spec.get('line_id')
            if line_id is None:
                continue
            try:
                line = Line.objects.select_related('shop').get(pk=line_id)
            except (Line.DoesNotExist, TypeError, ValueError):
                continue
            try:
                from_dt, to_dt = services.resolve_range(
                    line, spec.get('from'), spec.get('to'), clamp=True,
                )
            except ValueError:
                continue
            series = services.build_minute_series(line, from_dt, to_dt)
            events = services.downtime_events(line, from_dt, to_dt, now)
            summary = services.range_summary(line, from_dt, to_dt)
            result.append({
                'line_id': line.pk,
                'name': str(line),
                'shop_name': line.shop.name,
                'color': services._line_color(line.pk),
                'from': from_dt.isoformat(),
                'to': to_dt.isoformat(),
                'series': series,
                'events': [
                    {
                        'start': timezone.localtime(e['start']).isoformat(),
                        'end': timezone.localtime(e['end']).isoformat(),
                        'minutes': e['minutes'],
                        'ongoing': e['ongoing'],
                        'product_code': e['product_code'],
                        'product_name': e['product_name'],
                        'duration_str': _fmt_duration(e['minutes']),
                    }
                    for e in events
                ],
                'total_downtime': sum(e['minutes'] for e in events),
                'total_production': summary['total'],
                'summary': summary,
            })
        if not result:
            return Response({'ok': False, 'error': 'Не найдено линий с корректными диапазонами'},
                            status=status.HTTP_400_BAD_REQUEST)
        products_map = {
            p.code: {
                'name': p.name,
                'color': p.color or '#6c757d',
                'image': p.image.url if p.image else None,
                'code_1c': p.code_1c or '',
            }
            for p in Product.objects.all()
        }
        return Response({'ok': True, 'lines': result, 'products': products_map})