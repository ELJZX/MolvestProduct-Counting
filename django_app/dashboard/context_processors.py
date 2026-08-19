"""Контекст-процессоры: общие данные для всех шаблонов."""
import os

from django.conf import settings


def app_logo(request):
    """URL логотипа из корня проекта (файл logo.png рядом с django_app/).

    Логотип «вшит» в проект по умолчанию: пока файл logo.png существует,
    в шапке показывается изображение, иначе — стандартная иконка.
    """
    try:
        logo_path = settings.BASE_DIR.parent / 'logo.png'
        url = '/logo.png' if os.path.isfile(str(logo_path)) else None
    except Exception:
        url = None
    return {'app_logo_url': url}


def app_version(request):
    """Версия сборки для метки в шапке."""
    return {'app_version': getattr(settings, 'APP_VERSION', '')}
