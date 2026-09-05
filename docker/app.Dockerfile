# Django-приложение (django_app) для Docker.
# Внутри не используется файл .env — все настройки берутся из переменных
# окружения (см. docker-compose.yml), т.к. settings.py без .env читает os.environ.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl — для healthcheck (проверка готовности сервиса)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости
COPY django_app/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Код проекта
COPY django_app /app/django_app
COPY logo.svg /app/logo.svg
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

WORKDIR /app/django_app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
