#!/bin/sh
set -e

echo "==> Ожидание базы данных $DB_HOST:$DB_PORT ..."
python - <<'PY'
import os, socket, time
host = os.environ.get('DB_HOST', 'db')
port = int(os.environ.get('DB_PORT', '5432'))
timeout = 90
deadline = time.time() + timeout
while time.time() < deadline:
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('База данных недоступна (таймаут).')
PY

echo "==> Миграции ..."
python manage.py migrate --noinput

echo "==> Демо-данные (продукты, цеха, линии, пользователи) ..."
python manage.py seed_data

echo "==> Коллекция статики ..."
python manage.py collectstatic --noinput

echo "==> Запуск gunicorn ..."
exec gunicorn django_app.wsgi:application \
    --workers 1 \
    --threads 8 \
    --timeout 120 \
    --bind 0.0.0.0:8000
