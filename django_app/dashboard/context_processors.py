"""Контекст-процессоры: общие данные для всех шаблонов."""
from django.conf import settings


def app_logo(request):
    """URL логотипа из корня проекта (файл logo.svg, иначе logo.png).

    Логотип «вшит» в проект по умолчанию: пока файл существует, в шапке
    показывается изображение, иначе — стандартная иконка.
    """
    try:
        base = settings.BASE_DIR.parent
        if (base / 'logo.svg').is_file():
            url = '/logo.svg'
        elif (base / 'logo.png').is_file():
            url = '/logo.png'
        else:
            url = None
    except Exception:
        url = None
    return {'app_logo_url': url}


def app_version(request):
    """Версия сборки для метки в шапке."""
    return {'app_version': getattr(settings, 'APP_VERSION', '')}
