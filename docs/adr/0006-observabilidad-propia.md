# ADR 0006 — Observabilidad: logs JSON, ID de correlación y métricas Prometheus implementadas con la biblioteca estándar

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Hay 5 procesos que cooperan; sin logs estructurados, métricas ni correlación es imposible saber por qué una venta tardó o quedó pendiente.

## Decisión
Un módulo único, `observabilidad.py` (idéntico en los 5 servicios; `scripts/verificar_copias.py` lo comprueba en CI):
- **Logs JSON** (una línea por evento) con `ts`, `nivel`, `servicio`, `request_id` y campos propios.
- **`X-Request-ID`**: lo genera nginx (o el servicio) y viaja en los encabezados HTTP internos y **dentro del evento** de RabbitMQ (`request_id`), de modo que el worker lo escribe en su log. Un ID entrante solo se acepta si es seguro (`[A-Za-z0-9._-]{8,64}`).
- **`GET /metrics`** en formato de texto de Prometheus: latencia (histograma) y pedidos por ruta con **plantilla de ruta** (sin explosión de cardinalidad), y métricas de negocio (`movimientos_pendientes`, `outbox_eventos_sin_publicar`, `productos_stock_bajo`, `worker_mensajes_total`, `circuit_breaker_*`, `auth_login_total`).
- **Prometheus + Grafana** (perfil `observabilidad` de Compose) con dashboard y reglas de alerta provisionados.

## Alternativas descartadas
- `prometheus_client` + OpenTelemetry: estándar de la industria, pero suma dependencias en 5 imágenes y no podía verificarse sin instalar; el formato de texto es simple y queda cubierto por tests. El reemplazo futuro es directo (mismas métricas).
- Solo logs de texto: no permite agregar ni alertar.

## Consecuencias
+ Se sigue una venta de punta a punta con un ID y se ven latencias, errores y consistencia en un dashboard.
− **No hay trazas distribuidas con spans/Jaeger**: la correlación por `request_id` cubre el mismo caso de uso con menos costo; OpenTelemetry queda como siguiente paso.
