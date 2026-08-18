"""Наполнение базы демонстрационными данными.

Пример:
    python manage.py seed_data
    python manage.py seed_data --only-products
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from dashboard.models import Counter, Line, Product, Shop, UserProfile

# Реальные наименования продуктов (код -> название). Остальные коды 001..999
# заполняются заглушками «Продукт XXX», чтобы весь диапазон был в базе.
PRODUCT_NAMES = {
    '001': 'Молоко 3,2%',
    '002': 'Молоко 2,5%',
    '003': 'Молоко 1,5%',
    '004': 'Молоко 0,5%',
    '005': 'Молоко топлёное 4%',
    '006': 'Молоко ультрапастеризованное 2,5%',
    '007': 'Сливки 10%',
    '008': 'Сливки 20%',
    '009': 'Сливки 33%',
    '010': 'Кефир 3,2%',
    '011': 'Кефир 2,5%',
    '012': 'Кефир 1%',
    '105': 'Кефир 1% (пакет 1 л)',
    '135': 'Кефир 1% (пакет 0,5 л)',
    '013': 'Кефир 0,1%',
    '014': 'Биокефир 2,5%',
    '015': 'Ряженка 4%',
    '016': 'Простокваша 3,2%',
    '017': 'Йогурт питьевой «Классика» 2,5%',
    '018': 'Йогурт питьевой «Персик» 2,5%',
    '019': 'Йогурт питьевой «Клубника» 2,5%',
    '020': 'Йогурт питьевой «Лесные ягоды» 1,5%',
    '021': 'Сметана 15%',
    '022': 'Сметана 20%',
    '023': 'Сметана 25%',
    '024': 'Сметана 30%',
    '025': 'Творог 5%',
    '026': 'Творог 9%',
    '027': 'Творог обезжиренный',
    '028': 'Творожная масса с изюмом 18%',
    '029': 'Сыр творожный зерновой 5%',
    '030': 'Сыр «Адыгейский»',
    '031': 'Сыр «Моцарелла»',
    '032': 'Масло сливочное 82,5%',
    '033': 'Масло сливочное «Крестьянское» 72,5%',
    '034': 'Мороженое пломбир ванильный',
    '035': 'Мороженое шоколадное',
    '036': 'Сгущённое молоко 8,5%',
    '037': 'Сыр «Российский»',
    '038': 'Сыр «Голландский»',
    '039': 'Сыр плавленый «Сливочный»',
    '040': 'Напиток сывороточный «Зелёное яблоко»',
}

SHOPS = [
    {'code': 'Ц1', 'name': 'Цех молочной продукции', 'description': 'Линии розлива молока и кисломолочных напитков'},
    {'code': 'Ц2', 'name': 'Цех кисломолочной продукции', 'description': 'Кефиры, йогурты, сметана, творог'},
    {'code': 'Ц3', 'name': 'Цех фасовки и упаковки', 'description': 'Фасовка сыров, масла и мороженого'},
]

LINES = [
    {'shop': 'Ц1', 'number': 1, 'name': 'Линия розлива молока №1', 'controller': 'CTRL-001', 'perf': 2400},
    {'shop': 'Ц1', 'number': 2, 'name': 'Линия розлива молока №2', 'controller': 'CTRL-002', 'perf': 2400},
    {'shop': 'Ц2', 'number': 3, 'name': 'Линия кефира и йогурта', 'controller': 'CTRL-003', 'perf': 1800},
    {'shop': 'Ц2', 'number': 4, 'name': 'Линия творога и сметаны', 'controller': 'CTRL-004', 'perf': 1200},
    {'shop': 'Ц3', 'number': 5, 'name': 'Линия фасовки сыра', 'controller': 'CTRL-005', 'perf': 1500},
    {'shop': 'Ц3', 'number': 6, 'name': 'Линия фасовки масла', 'controller': 'CTRL-006', 'perf': 2000},
]

USERS = [
    {'username': 'admin', 'password': 'admin123', 'role': UserProfile.ROLE_ADMIN, 'staff': True, 'super': True},
    {'username': 'operator', 'password': 'operator123', 'role': UserProfile.ROLE_OPERATOR},
    {'username': 'viewer', 'password': 'viewer123', 'role': UserProfile.ROLE_VIEWER},
]


class Command(BaseCommand):
    help = 'Создаёт справочник продуктов (001..999), цеха, линии и демо-пользователей.'

    def add_arguments(self, parser):
        parser.add_argument('--only-products', action='store_true',
                            help='Заполнить только справочник продуктов')

    def handle(self, *args, **options):
        only_products = options['only_products']

        palette = [
            '#1f6feb', '#2da44e', '#bf8700', '#bf3989', '#8250df', '#0a8cff',
            '#0aac8e', '#d1242f', '#e5534b', '#0d9488', '#e83e8c', '#8957e5',
            '#198754', '#fd7e14', '#0dcaf0', '#6f42c1', '#dc3545', '#087ea4',
            '#8a5a00', '#2f6f4f', '#7a5195', '#c2410c', '#1d6fb8', '#3b5bdb',
        ]
        created_products = 0
        for code in range(1, 1000):
            key = f'{code:03d}'
            name = PRODUCT_NAMES.get(key, f'Продукт {key}')
            color = palette[(code - 1) % len(palette)]
            _, created = Product.objects.get_or_create(
                code=key, defaults={
                    'name': name, 'color': color,
                    'code_1c': f'1C-{key}',
                },
            )
            if created:
                created_products += 1
        # Заполняем код 1С у ранее созданных продуктов, где он ещё пуст
        # (реальные коды администратор прописывает вручную через интерфейс)
        blank = Product.objects.filter(code_1c='')
        for p in blank:
            p.code_1c = f'1C-{p.code}'
            p.save(update_fields=['code_1c'])
        self.stdout.write(self.style.SUCCESS(f'Продукты: создано {created_products}, всего {Product.objects.count()}'))

        if only_products:
            return

        shop_map = {}
        for s in SHOPS:
            shop, _ = Shop.objects.get_or_create(
                code=s['code'],
                defaults={'name': s['name'], 'description': s['description']},
            )
            shop_map[s['code']] = shop
        self.stdout.write(self.style.SUCCESS(f'Цеха: {Shop.objects.count()}'))

        for l in LINES:
            line, created = Line.objects.get_or_create(
                shop=shop_map[l['shop']], number=l['number'],
                defaults={
                    'name': l['name'], 'controller_id': l['controller'],
                    'performance_per_hour': l.get('perf', 0),
                },
            )
            if created:
                self.stdout.write(f'  + линия {line}')
            elif not line.performance_per_hour:
                line.performance_per_hour = l.get('perf', 0)
                line.save(update_fields=['performance_per_hour'])
        self.stdout.write(self.style.SUCCESS(f'Линии: {Line.objects.count()}'))

        # Счётчики: по одному на каждую линию
        created_counters = 0
        for line in Line.objects.all().order_by('id'):
            counter, created = Counter.objects.get_or_create(
                line=line, defaults={'name': f'Счетчик {line.id}'},
            )
            if created:
                created_counters += 1
        self.stdout.write(self.style.SUCCESS(
            f'Счетчики: создано {created_counters}, всего {Counter.objects.count()}'
        ))

        for u in USERS:
            user, created = User.objects.get_or_create(username=u['username'])
            user.set_password(u['password'])
            if u.get('staff'):
                user.is_staff = True
            if u.get('super'):
                user.is_superuser = True
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = u['role']
            profile.save()
            self.stdout.write(f'  + пользователь {u["username"]} (роль: {u["role"]})')

        self.stdout.write(self.style.SUCCESS(
            'Готово. Демо-пользователи: admin/admin123, operator/operator123, viewer/viewer123'
        ))