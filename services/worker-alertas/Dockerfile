# syntax=docker/dockerfile:1
# Imagen endurecida (AE4): usuario sin privilegios, sin pytest ni compiladores.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_FORMAT=json

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Solo el código del worker (no los tests): ver .dockerignore
COPY --chown=root:root . .

# Carpeta para la base sqlite local de idempotencia (se monta como volumen en compose)
RUN mkdir -p /app/data && chown -R app:app /app/data

USER app

# Puerto del healthcheck HTTP (GET /health) y de las métricas (GET /metrics)
EXPOSE 8003

CMD ["python", "worker.py"]
