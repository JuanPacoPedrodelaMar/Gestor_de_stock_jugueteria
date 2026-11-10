# Cambios de la versión AE4

Resumen de lo agregado sobre la versión anterior (v3), agrupado por objetivo.

## Corregido (defectos encontrados al analizar la v3)
| Problema | Corrección |
|---|---|
| **La DLQ del worker nunca se alcanzaba**: se contaba `len(x-death)`, pero RabbitMQ guarda una entrada por (cola, razón) con un `count`; la lista nunca superaba 2. Un mensaje fallido se reintentaba para siempre. | `contar_reintentos_previos` suma el `count` de la cola principal. Tests con el formato real. |
| **Un mensaje malformado tumbaba al worker** (excepción fuera del `try` → caída → reentrega → bucle). | Se valida el mensaje; los inválidos van directo a la DLQ con `x-motivo-dlq`. |
| Defaults inseguros del compose (usuarios de prueba y seed activos, RabbitMQ publicado). | Compose base seguro + override de desarrollo + compose de producción. |
| Redis sin persistencia (el volumen estaba declarado y no montado). | AOF + volumen `redis_data`. |
| Enteros gigantes → 500; `precio_venta=Infinity` pasaba la validación. | Topes y `allow_inf_nan=False`, con tests. |
| `auth` y nginx sin headers de seguridad. | Headers en las 4 APIs y nginx; CSP estricta (se quitaron los `onclick` y el script inline). |
| Contraste de color insuficiente (botones blancos sobre naranja/rosa/turquesa, grises tenues). | Paleta ajustada (≥ 4.65:1) y auditoría automática. |
| Desplegable de productos de movimientos sin flechas; ARIA incompleta. | Navegación por teclado y patrón combobox/listbox en todos. |
| Pool de conexiones y SQLite sin ajustar (documentado como pendiente). | Pool 20+60, WAL, `busy_timeout`. |
| Código muerto (`idempotencia/redis_client.py`, `worker-alertas/productos_client.py`), `pytest` en las imágenes de producción. | Eliminado / separado en `requirements-dev.txt`. |

## Agregado
- **Observabilidad:** logs JSON, `X-Request-ID` de punta a punta (también dentro del evento), `/metrics`, Prometheus + Grafana + alertas.
- **Resiliencia:** circuit breaker y reintentos con backoff en `movimientos` → `productos`/`clientes`.
- **CI/CD y despliegue:** pipeline sistema → GHCR → despliegue → humo → release; gateway nginx; Caddy con TLS; compose de producción.
- **Pruebas:** `prueba_sistema.py` (R1, R2, R3), `prueba_carga.py` (media/p50/p95/p99), tests de resiliencia, observabilidad, worker y límites.
- **Documentación:** 9 ADR, diagramas de propiedad de datos/despliegue/correlación/breaker, guías de observabilidad y despliegue, evidencias.

## Decisiones que NO cambian (y por qué)
- Producto dado de baja sigue aceptando ajustes ([ADR 0009](./adr/0009-productos-dados-de-baja.md)).
- SQLite en lugar de Postgres: sin réplicas ([ADR 0007](./adr/0007-sqlite-wal-y-limite-de-ha.md)).
- Observabilidad propia en lugar de `prometheus_client`/OpenTelemetry ([ADR 0006](./adr/0006-observabilidad-propia.md)).

## ⚠ Para actualizar un entorno existente
Las imágenes corren ahora con un usuario sin privilegios (UID 10001). Los volúmenes creados por la versión anterior (como root) hay que recrearlos (`docker compose down -v`, **borra datos**) o corregir su dueño (`chown -R 10001:10001`). Ver `docs/DESPLIEGUE.md`, sección 5.

## Cómo se verificó este trabajo (honestidad)
El entorno donde se desarrolló **no tenía acceso a red ni a las dependencias** (FastAPI, SQLAlchemy, pytest, pika), por lo que **la suite completa de tests de los servicios NO se ejecutó** antes de la entrega. Sí se verificó: sintaxis de todo el Python y JS; la lógica de `observabilidad`, `resiliencia`, `worker` (con doble de `pika`) y del cliente HTTP (con doble de `httpx`); el parseo de YAML/JSON; el contraste de colores; y los scripts de sistema y carga contra un servidor simulado. **El primer paso al recibir esta versión es correr `pytest` en cada servicio y el pipeline.**
