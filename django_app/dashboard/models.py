"""Модели системы учёта продукции.

Иерархия предприятия:  Цех (Shop) -> Линия (Line).
Продукция нумеруется уникальными кодами 001..999 (Product.code).
Каждая смена ключа продукта на линии порождает Задание (ProductAssignment),
а количество, пройденное под датчиком, раскладывается по минутным
интервалам (ProductionRecord).
"""
import os
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class Product(models.Model):
    """Продукт с уникальным кодом 001..999 (например 001 — 'Молоко 3,2%').

    Продукт может принадлежать цеху (поле shop). Одинаковые наименования и
    одинаковые коды 1С допустимы в разных цехах; код продукта (001..999)
    всегда уникален. Поле shop пустое — «общий» продукт, доступный везде.
    """

    code = models.CharField(
        'Код', max_length=3, unique=True,
        help_text='Уникальный код продукта в диапазоне 001..999',
    )
    name = models.CharField('Наименование', max_length=200)
    shop = models.ForeignKey(
        'Shop', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='products', verbose_name='Цех',
        help_text='Цех, которому принадлежит продукт (пусто — общий продукт)',
    )
    description = models.TextField('Описание', blank=True)
    code_1c = models.CharField(
        'Код 1С', max_length=64, blank=True,
        help_text='Код продукта в учётной системе 1С (заполняется администратором вручную)',
    )
    color = models.CharField(
        'Цвет на диаграмме', max_length=7, default='#1f6feb',
        help_text='HEX-цвет (например #1f6feb) для столбиков диаграммы',
    )
    image = models.ImageField(
        'Изображение', upload_to='products/', blank=True, null=True,
        help_text='Необязательное изображение продукта (продукт можно добавить без картинки)',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Продукт'
        verbose_name_plural = 'Продукты'

    def __str__(self):
        return f'{self.code} — {self.name}'


class Shop(models.Model):
    """Цех предприятия."""

    name = models.CharField('Название', max_length=150, unique=True)
    code = models.CharField('Код', max_length=20, unique=True)
    description = models.TextField('Описание', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Цех'
        verbose_name_plural = 'Цеха'

    def __str__(self):
        return self.name

    @property
    def lines_total(self):
        return self.lines.count()

    @property
    def lines_active(self):
        return self.lines.filter(is_active=True).count()

    @property
    def lines_in_work(self):
        """Линии, у которых открыто задание (идёт производство)."""
        return self.lines.filter(
            is_active=True, current_assignment__ended_at__isnull=True,
        ).distinct().count()


class ProductAssignment(models.Model):
    """Задание линии — интервал времени с момента смены ключа продукта."""

    line = models.ForeignKey(
        'Line', on_delete=models.CASCADE, related_name='assignments',
        verbose_name='Линия',
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='assignments',
        verbose_name='Продукт',
    )
    started_at = models.DateTimeField('Начало (момент смены ключа)')
    ended_at = models.DateTimeField('Окончание', null=True, blank=True)
    target_quantity = models.BigIntegerField(
        'План (шт.)', null=True, blank=True,
    )
    total_count = models.BigIntegerField('Изготовлено (шт.)', default=0)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Задание (смена продукта)'
        verbose_name_plural = 'Задания (смены продукта)'

    def __str__(self):
        end = f' по {self.ended_at:%d.%m.%Y %H:%M}' if self.ended_at else ''
        return f'{self.line} · {self.product.code} с {self.started_at:%d.%m.%Y %H:%M}{end}'

    @property
    def is_active(self):
        return self.ended_at is None


class Line(models.Model):
    """Производственная линия с оптическим датчиком и контроллером ОВЕН."""

    shop = models.ForeignKey(
        Shop, on_delete=models.CASCADE, related_name='lines',
        verbose_name='Цех',
    )
    number = models.PositiveSmallIntegerField('Номер линии')
    name = models.CharField('Название', max_length=150)
    controller_id = models.CharField(
        'Идентификатор контроллера ОВЕН', max_length=64, unique=True, blank=True,
        help_text='Значение поля controller_id, которое присылает контроллер',
    )
    is_active = models.BooleanField('Линия в эксплуатации', default=True)
    current_product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='lines_current', verbose_name='Текущий продукт',
    )
    current_assignment = models.ForeignKey(
        ProductAssignment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Текущее задание',
    )
    last_seen = models.DateTimeField(
        'Последнее обращение контроллера', null=True, blank=True,
    )
    performance_per_hour = models.PositiveIntegerField(
        'Производительность в час (шт.)', default=0,
        help_text='Нормативная производительность линии, шт. в час (заполняется администратором)',
    )
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        ordering = ['shop__code', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['shop', 'number'], name='uniq_line_shop_number',
            ),
        ]
        verbose_name = 'Линия'
        verbose_name_plural = 'Линии'

    def __str__(self):
        return self.name

    @property
    def is_working(self):
        a = self.current_assignment
        return bool(self.is_active and a and a.ended_at is None)

    # Коды, которые меняют статус линии (при смене ключа продукта на линии)
    STATUS_CODE_DEBUG = '888'
    STATUS_CODE_EXP1 = '999'
    STATUS_CODE_EXP2 = '998'
    STATUS_CODE_MAP = {
        STATUS_CODE_DEBUG: ('Отладка', 'danger'),
        STATUS_CODE_EXP1: ('Эксперимент 1', 'warning'),
        STATUS_CODE_EXP2: ('Эксперимент 2', 'warning'),
    }

    @property
    def status(self):
        """Текущий статус линии: (название, класс Bootstrap).

        При кодах продукта 888/999/998 статус меняется на
        «Отладка» / «Эксперимент 1» / «Эксперимент 2», любой другой код — «В работе».
        """
        if not self.is_working:
            return ('Остановлена', 'secondary')
        code = self.current_product.code if self.current_product else None
        if code in self.STATUS_CODE_MAP:
            return self.STATUS_CODE_MAP[code]
        return ('В работе', 'success')


class ProductionRecord(models.Model):
    """Количество продукции на линии за одну минуту (столбик диаграммы)."""

    line = models.ForeignKey(
        Line, on_delete=models.CASCADE, related_name='records',
        verbose_name='Линия',
    )
    assignment = models.ForeignKey(
        ProductAssignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='records', verbose_name='Задание',
    )
    minute_start = models.DateTimeField('Начало минуты')
    count = models.BigIntegerField('Количество (шт.)', default=0)

    class Meta:
        ordering = ['minute_start']
        constraints = [
            models.UniqueConstraint(
                fields=['line', 'minute_start'], name='uniq_line_minute',
            ),
        ]
        indexes = [
            models.Index(fields=['line', 'minute_start']),
        ]
        verbose_name = 'Минутный счёт'
        verbose_name_plural = 'Минутные счета'


class ControllerReading(models.Model):
    """Сырые показания контроллера ОВЕН (история приёмов данных)."""

    line = models.ForeignKey(
        Line, on_delete=models.CASCADE, related_name='readings',
        verbose_name='Линия',
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='readings', verbose_name='Продукт',
    )
    assignment = models.ForeignKey(
        ProductAssignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='readings', verbose_name='Задание',
    )
    total = models.BigIntegerField('Суммарное показание счётчика', default=0)
    delta = models.BigIntegerField('Приращение за приём', default=0)
    received_at = models.DateTimeField('Время получения', default=timezone.now)

    class Meta:
        ordering = ['-received_at']
        verbose_name = 'Показание контроллера'
        verbose_name_plural = 'Показания контроллеров'


class Counter(models.Model):
    """Счётчик, закреплённый за линией (для отчётов)."""

    name = models.CharField('Название счетчика', max_length=100)
    line = models.OneToOneField(
        Line, on_delete=models.CASCADE, related_name='counter',
        verbose_name='Линия',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Счетчик'
        verbose_name_plural = 'Счетчики'

    def __str__(self):
        return f'{self.name} ({self.line.name})'


class UserProfile(models.Model):
    """Профиль пользователя с уровнем доступа."""

    ROLE_ADMIN = 'admin'
    ROLE_OPERATOR = 'operator'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Администратор'),
        (ROLE_OPERATOR, 'Оператор'),
        (ROLE_VIEWER, 'Наблюдатель'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='profile', verbose_name='Пользователь',
    )
    role = models.CharField(
        'Роль', max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER,
    )
    shop = models.ForeignKey(
        Shop, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='staff', verbose_name='Цех (для оператора)',
    )

    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'


class SystemConfig(models.Model):
    """Глобальная настройка системы: источник данных для отчётов и графиков.

    data_source='db'  — база данных PostgreSQL (основной режим);
    data_source='dbf' — файлы DBF (запасной режим: отчёты и графики строятся
                        из архивов контроллера в папке dbf_dir).
    """

    DATA_SOURCE_DB = 'db'
    DATA_SOURCE_DBF = 'dbf'
    DATA_SOURCE_CHOICES = [
        (DATA_SOURCE_DB, 'База данных (PostgreSQL)'),
        (DATA_SOURCE_DBF, 'Файлы DBF'),
    ]

    data_source = models.CharField(
        'Источник данных для отчётов', max_length=10,
        choices=DATA_SOURCE_CHOICES, default=DATA_SOURCE_DB,
    )
    dbf_dir = models.CharField(
        'Папка с файлами DBF', max_length=500, blank=True,
        help_text='Путь к папке, где лежат файлы *.dbf. '
                  'Пусто — корневая папка проекта (где лежат 20442023.dbf и т.п.). '
                  'Можно указать абсолютный путь (C:\\dbf) или относительный.',
    )
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Настройка системы'
        verbose_name_plural = 'Настройки системы'

    def __str__(self):
        return f'Источник данных: {self.get_data_source_display()}'

    @classmethod
    def get(cls):
        """Единственный экземпляр настроек (создаётся при первом обращении)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def resolved_dbf_dir(self):
        """Реальный путь к папке с файлами DBF.

        Если поле dbf_dir пустое: сначала корень проекта, а если файлов *.dbf
        в корне нет — подпапка «DBF VIKO» (автоопределение). Относительные пути
        считаются от корня проекта.
        """
        base = settings.BASE_DIR.parent
        d = (self.dbf_dir or '').strip()
        if not d:
            d = str(base)
            try:
                if not any(e.lower().endswith('.dbf') for e in os.listdir(d)):
                    alt = os.path.join(d, 'DBF VIKO')
                    if os.path.isdir(alt) and any(
                        e.lower().endswith('.dbf') for e in os.listdir(alt)
                    ):
                        d = alt
            except OSError:
                pass
            return d
        p = Path(d).expanduser()
        if not p.is_absolute():
            p = base / p
        return str(p)


class ReportLog(models.Model):
    """Журнал формирований отчётов.

    Нужен для «Идентификатора отчёта»: база отслеживает, сколько раз отчёт
    был сформирован за выбранный период (та же линия, вкладка, период),
    и присваивает следующий порядковый номер.
    """

    line = models.ForeignKey(
        Line, null=True, blank=True, on_delete=models.CASCADE,
        related_name='report_logs', verbose_name='Линия',
        help_text='Пусто для запасного режима (файлы DBF).',
    )
    tab = models.CharField('Вкладка', max_length=20)
    rtype = models.CharField('Тип отчёта', max_length=30)
    period_start = models.DateTimeField('Начало периода')
    period_end = models.DateTimeField('Окончание периода')
    number = models.PositiveIntegerField('Номер за период')
    identifier = models.CharField('Идентификатор отчёта', max_length=64)
    created_at = models.DateTimeField('Сформирован', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Формирование отчёта'
        verbose_name_plural = 'Формирования отчётов'

    def __str__(self):
        return f'{self.identifier} · {self.line} · {self.get_tab_display()}'