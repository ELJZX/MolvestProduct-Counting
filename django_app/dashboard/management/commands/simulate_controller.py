"""Симулятор контроллера ОВЕН.

Каждую минуту «присылает» показания по всем активным линиям:
  * напрямую через сервисный слой (по умолчанию), либо
  * по HTTP на /api/v1/counter/ (--http), что проверяет весь стек.

Примеры:
    python manage.py simulate_controller --minutes 5
    python manage.py simulate_controller --http --switch-after 10
"""
import random
import sys
import time
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard import services
from dashboard.models import Line, Product

PRODUCT_FAVORITES = ['001', '002', '010', '011', '012', '017', '021', '022', '025']


class Command(BaseCommand):
    help = 'Симулирует контроллер ОВЕН: отправляет показания каждую минуту.'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=0,
                            help='Сколько минут симулировать (0 — бесконечно, Ctrl+C для остановки)')
        parser.add_argument('--http', action='store_true',
                            help='Отправлять данные по HTTP на /api/v1/counter/')
        parser.add_argument('--switch-after', type=int, default=0,
                            help='Менять продукт на линии каждые N минут (0 — не менять)')
        parser.add_argument('--base-url', default='http://127.0.0.1:8000',
                            help='Базовый URL сервера для --http')

    def handle(self, *args, **options):
        minutes = options['minutes']
        use_http = options['http']
        switch_after = options['switch_after']
        base_url = options['base_url'].rstrip('/')

        lines = list(Line.objects.filter(is_active=True))
        if not lines:
            self.stderr.write('Нет активных линий. Сначала выполните: python manage.py seed_data')
            sys.exit(1)

        products = list(Product.objects.filter(code__in=PRODUCT_FAVORITES))
        if not products:
            products = list(Product.objects.all()[:10])

        self.stdout.write(self.style.SUCCESS(
            f'Симулятор запущен: линий={len(lines)}, http={use_http}, '
            f'смена продукта каждые {switch_after or "—"} мин'
        ))

        line_state = {l.pk: {'count': random.randint(100, 500), 'product': random.choice(products).code, 'ticks': 0}
                      for l in lines}

        tick = 0
        try:
            while True:
                tick += 1
                for line in lines:
                    st = line_state[line.pk]
                    if switch_after and st['ticks'] >= switch_after:
                        st['product'] = random.choice(products).code
                        st['ticks'] = 0
                        st['count'] = 0
                    st['ticks'] += 1
                    st['count'] += random.randint(30, 150)

                    payload = {
                        'controller_id': line.controller_id,
                        'product': st['product'],
                        'count': st['count'],
                        'at': timezone.now().isoformat(),
                    }
                    if use_http:
                        self._send_http(base_url, payload)
                        self.stdout.write(
                            f'  [{tick:03d}] {line.controller_id}: продукт {payload["product"]}, '
                            f'счётчик {payload["count"]} (HTTP)'
                        )
                    else:
                        result = services.record_reading(**payload)
                        self.stdout.write(
                            f'  [{tick:03d}] {line.controller_id}: продукт {payload["product"]}, '
                            f'+{result["delta"]} шт (всего {result["total_count"]})'
                        )
                self.stdout.write(self.style.SUCCESS(f'--- минута {tick} обработана ---'))
                if minutes and tick >= minutes:
                    break
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write('Остановлено пользователем.')

    def _send_http(self, base_url, payload):
        import json
        req = urllib.request.Request(
            base_url + '/api/v1/counter/',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'X-API-Key': settings.CONTROLLER_API_KEY},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
