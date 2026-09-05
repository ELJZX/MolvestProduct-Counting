#!/usr/bin/env bash
# Резервная копия Docker-образов стека в папку backups/
# Linux / macOS:  ./backup.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups

version="$(grep -oP "APP_VERSION = '\K[^']+" django_app/django_app/settings.py || echo snapshot)"

for img in molvestproductounting-django:latest molvestproductounting-simulator:latest postgres:16-alpine nginx:1.27-alpine; do
  name="$(echo "$img" | tr ':/' '__')"
  echo "Сохраняю $img -> backups/${name}_${version}.tar"
  docker save -o "backups/${name}_${version}.tar" "$img"
done

echo "Готово."
