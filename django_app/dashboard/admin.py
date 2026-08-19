from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html

from . import dbf_reader
from .models import (
    ControllerReading, Counter, Line, Product, ProductAssignment,
    ProductionRecord, Shop, SystemConfig, UserProfile,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'created_at')
    list_display_links = ('code', 'name')
    search_fields = ('code', 'name')
    ordering = ('code',)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'lines_total', 'created_at')
    search_fields = ('name', 'code')


@admin.register(Line)
class LineAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'shop', 'number', 'controller_id', 'is_active',
                    'current_product', 'performance_per_hour', 'last_seen')
    list_filter = ('shop', 'is_active')
    search_fields = ('name', 'controller_id', 'shop__name')
    autocomplete_fields = ('shop',)
    fieldsets = (
        (None, {'fields': ('shop', 'number', 'name', 'controller_id')}),
        ('Параметры', {'fields': ('is_active', 'performance_per_hour')}),
    )


class AssignmentInline(admin.TabularInline):
    model = ProductAssignment
    extra = 0
    readonly_fields = ('total_count',)
    autocomplete_fields = ('product',)


@admin.register(Counter)
class CounterAdmin(admin.ModelAdmin):
    list_display = ('name', 'line', 'created_at')
    search_fields = ('name', 'line__name')
    autocomplete_fields = ('line',)


@admin.register(ProductAssignment)
class ProductAssignmentAdmin(admin.ModelAdmin):
    list_display = ('line', 'product', 'started_at', 'ended_at', 'total_count', 'target_quantity')
    list_filter = ('line__shop', 'product')
    search_fields = ('line__name', 'product__code', 'product__name')
    autocomplete_fields = ('line', 'product')


@admin.register(ProductionRecord)
class ProductionRecordAdmin(admin.ModelAdmin):
    list_display = ('line', 'minute_start', 'count', 'assignment')
    list_filter = ('line__shop', 'line')
    search_fields = ('line__name',)
    date_hierarchy = 'minute_start'


@admin.register(ControllerReading)
class ControllerReadingAdmin(admin.ModelAdmin):
    list_display = ('line', 'product', 'total', 'delta', 'received_at')
    list_filter = ('line', 'product')
    date_hierarchy = 'received_at'


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdminWithProfile(BaseUserAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdminWithProfile)


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    """Настройка системы: папка с файлами DBF.

    Переключение источника данных (база PostgreSQL / файлы DBF) выполняется
    кнопкой на вкладке «Отчёты», здесь задаётся только путь к папке с *.dbf.
    """

    list_display = ('dbf_dir', 'updated_at')
    fieldsets = (
        ('Файлы DBF', {
            'fields': ('dbf_dir', 'dbf_files_preview'),
            'description': 'Папка, где лежат файлы *.dbf (например 20442023.dbf). '
                           'Если поле пустое — используется корень проекта. '
                           'Переключение источника данных (БД/DBF) выполняется '
                           'кнопкой на вкладке «Отчёты».',
        }),
    )
    readonly_fields = ('dbf_files_preview', 'updated_at')

    def dbf_files_preview(self, obj):
        d = obj.resolved_dbf_dir() if obj else ''
        files = dbf_reader.list_dbf_files(d) if d else []
        if not files:
            return format_html(
                'Файлы *.dbf не найдены в папке <code>{}</code>.',
                d or '—',
            )
        rows = []
        for f in files:
            rows.append(
                '<li><code>{}</code> — {} записей · {} – {}</li>'.format(
                    f['filename'], f['record_count'], f['first_str'], f['last_str'],
                ),
            )
        more = '' if len(files) <= 30 else f'<li>… и ещё {len(files) - 30}</li>'
        return format_html(
            'Папка: <code>{}</code> · найдено файлов: {}<ul>{}{}</ul>',
            d, len(files), ''.join(rows), more,
        )

    dbf_files_preview.short_description = 'Найденные DBF-файлы'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False