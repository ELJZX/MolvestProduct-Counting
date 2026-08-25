from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    ControllerReading, Counter, Line, Product, ProductAssignment,
    ProductionRecord, ReportLog, Shop, SystemConfig, UserProfile,
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


@admin.register(ReportLog)
class ReportLogAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'line', 'tab', 'rtype', 'period_start', 'period_end', 'number', 'created_at')
    list_filter = ('tab', 'rtype', 'line')
    search_fields = ('identifier', 'line__name')
    date_hierarchy = 'created_at'


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    """Настройки системы: источник данных для отчётов, путь к папке DBF
    и пин-код смены продукта на линии.

    Позволяет администратору быстро поменять папку с файлами *.dbf
    (запасной режим отчётов) прямо из админки Django.
    """
    list_display = ('data_source', 'switch_pin', 'dbf_dir', 'resolved_dbf_dir_display', 'updated_at')
    fields = ('data_source', 'switch_pin', 'dbf_dir')
    readonly_fields = ('resolved_dbf_dir_display',)

    def has_add_permission(self, request):
        # Настройки — одиночная запись (pk=1), создаётся автоматически
        return not SystemConfig.objects.exists()

    @admin.display(description='Фактическая папка DBF')
    def resolved_dbf_dir_display(self, obj):
        return obj.resolved_dbf_dir()


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdminWithProfile(BaseUserAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdminWithProfile)