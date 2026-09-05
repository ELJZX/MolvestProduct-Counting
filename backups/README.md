# Резервные копии Docker-образов

В этой папке сохраняются резервные копии образов стека (`docker save`).
Сами `.tar`-файлы большие и **не загружаются на GitHub** (добавлены в
`.gitignore`); здесь хранится только это описание.

Создание копий:

- PowerShell (Windows): `.\backup.ps1`
- Linux / macOS: `./backup.sh`

Восстановление образа:

```bash
docker load --input backups/molvest_django_3.0.1.tar
docker load --input backups/molvest_simulator_3.0.1.tar
```
