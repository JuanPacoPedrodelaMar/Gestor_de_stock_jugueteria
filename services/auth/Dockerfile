# syntax=docker/dockerfile:1
# Imagen endurecida (AE4): multi-stage, sin compiladores en la imagen final y
# ejecución con un usuario sin privilegios. Las dependencias se compilan en la
# etapa "constructor" y solo se copia el resultado.

FROM python:3.12-slim AS constructor
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/instalacion -r requirements.txt


FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: sin .pyc. PYTHONUNBUFFERED: logs sin buffer.
# LOG_FORMAT=json: logs estructurados (ver app/core/observabilidad.py).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_FORMAT=json

# Solo curl (lo usa el healthcheck).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=constructor /instalacion /usr/local

# Código de la aplicación (con dueño "app", pero sin permiso de escritura sobre él mismo)
COPY --chown=root:root app ./app

# Carpeta para la base de datos SQLite (se monta como volumen en compose).
# Si el volumen ya existía de una versión anterior (creado como root), hay que
# recrearlo o ejecutar: chown -R 10001:10001 sobre su contenido.
RUN mkdir -p /app/data && chown -R app:app /app/data

USER app

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl -f http://localhost:8001/health || exit 1

# --no-access-log: el log de acceso lo emite la app misma, en JSON y con request_id.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
