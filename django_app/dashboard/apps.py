from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    verbose_name = 'Учёт продукции'

    def ready(self):
        # Регистрируем сигналы (автосоздание профилей пользователей)
        from . import signals  # noqa: F401
