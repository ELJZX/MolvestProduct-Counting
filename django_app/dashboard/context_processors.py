"""Контекст-процессоры: общие данные для всех шаблонов."""
from .models import SystemConfig


def app_logo(request):
    """URL логотипа из настроек системы (для шапки сайта).

    В шаблонах доступна переменная {{ app_logo_url }}: если в настройках
    системы загружен логотип — его URL, иначе None.
    """
    try:
        cfg = SystemConfig.get()
        url = cfg.logo.url if cfg.logo and cfg.logo.name else None
    except Exception:
        url = None
    return {'app_logo_url': url}
