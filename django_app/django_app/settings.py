"""
Django settings for the product counting system (django_app).

Система учёта продукции, прошедшей под оптическими датчиками.
Количество фиксируется контроллерами ОВЕН и передаётся на сервер
через API  /api/v1/counter/  (заголовок X-API-Key).
"""
from pathlib import Path

from decouple import Config, RepositoryEnv

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Конфигурация из .env (лежит рядом с проектом) ----
_ENV_FILE = BASE_DIR.parent / '.env'
if _ENV_FILE.exists():
    env = Config(RepositoryEnv(str(_ENV_FILE)))
else:
    from decouple import config as _config
    env = _config

SECRET_KEY = env('SECRET_KEY', default='django-insecure-dev-key-change-me')
DEBUG = env('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = [h.strip() for h in env('ALLOWED_HOSTS', default='*').split(',') if h.strip()]

# Ключ авторизации контроллеров ОВЕН
CONTROLLER_API_KEY = env('CONTROLLER_API_KEY', default='super-secret-controller-key')

# Временная зона предприятия
APP_TIME_ZONE = env('APP_TIME_ZONE', default='Europe/Moscow')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'django_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.app_logo',
                'dashboard.context_processors.app_version',
            ],
        },
    },
]

WSGI_APPLICATION = 'django_app.wsgi.application'
ASGI_APPLICATION = 'django_app.asgi.application'

# ---- База данных: PostgreSQL (по умолчанию) или SQLite для отладки ----
DB_ENGINE = env('DB_ENGINE', default='postgresql').lower()
if DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default='molvest'),
            'USER': env('DB_USER', default='postgres'),
            'PASSWORD': env('DB_PASSWORD', default=''),
            'HOST': env('DB_HOST', default='127.0.0.1'),
            'PORT': env('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
            'OPTIONS': {'connect_timeout': 10},
        }
    }

# ---- Пароли ----
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---- Интернационализация ----
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = APP_TIME_ZONE
USE_I18N = True
USE_TZ = True

# ---- Авторизация ----
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'reports'
LOGOUT_REDIRECT_URL = 'login'

# ---- Статика и медиа ----
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'dashboard' / 'static']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Версия сборки (видна в шапке — по ней легко понять, какая версия запущена)
APP_VERSION = '1.6.9'

# ---- DRF ----
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
    ],
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'