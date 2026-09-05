# Simulator line (line_simulator) — независимый сервис на stdlib.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY line_simulator /app/line_simulator

WORKDIR /app/line_simulator

EXPOSE 8050

CMD ["python", "server.py"]
