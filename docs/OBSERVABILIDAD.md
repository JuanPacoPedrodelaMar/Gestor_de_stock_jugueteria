# Observabilidad

Qué se puede **ver** del sistema en funcionamiento, y cómo. Decisión de diseño: [ADR 0006](./adr/0006-observabilidad-propia.md).

| Pilar | Qué hay | Dónde se ve |
|---|---|---|
| **Logs estructurados** | Una línea JSON por evento, con `request_id` | `docker compose logs -f <servicio>` |
| **Correlación / trazabilidad** | Un `X-Request-ID` que atraviesa nginx → APIs → evento de RabbitMQ → worker | Buscar el ID en los logs de todos los servicios |
| **Métricas** | `GET /metrics` (formato Prometheus) en los 5 servicios | Prometheus (`:9090`) y Grafana (`:3000`) |
| **Alertas** | 8 reglas (caída, latencia p95, errores 5xx, pendientes, outbox, DLQ, circuit breaker, fuerza bruta) | Prometheus → pestaña *Alerts* |

## Levantar el monitoreo

```bash
docker compose --profile observabilidad up -d        # desarrollo
# Grafana:    http://localhost:3000   (usuario admin / contraseña GRAFANA_ADMIN_PASSWORD, por defecto "admin")
# Prometheus: http://localhost:9090   (Status → Targets: los 5 servicios deben estar UP)
```
El dashboard **«Juguetería — visión general»** viene provisionado (carpeta *Juguetería*): pedidos por segundo, **latencia media y p95** por servicio, errores 5xx, movimientos pendientes, eventos sin publicar, productos con stock bajo, estado del circuit breaker, resultados del worker y de los logins.

En producción Prometheus y Grafana solo escuchan en `127.0.0.1` del servidor; se accede por túnel SSH: `ssh -L 3000:localhost:3000 usuario@servidor`.

## Logs estructurados

Se activan con `LOG_FORMAT=json` (las imágenes ya lo traen). Ejemplo real de un pedido:

```json
{"ts":"2026-11-08T14:32:10.123+00:00","nivel":"INFO","servicio":"movimientos","logger":"movimientos.http","mensaje":"pedido atendido","request_id":"9f1c2e7a4b3d4c6e8a1b2c3d4e5f6a7b","evento":"http","metodo":"POST","ruta":"/api/v1/movimientos","estado":201,"duracion_ms":41.8}
```
Los *healthchecks* y `/metrics` no se loguean (corren cada pocos segundos). Cambiar el nivel con `LOG_LEVEL`.

## Seguir una venta de punta a punta (correlación)

1. El navegador hace `POST /api/v1/movimientos`. nginx genera el `X-Request-ID` (o lo respeta si ya viene uno válido).
2. `movimientos` lo registra en sus logs y lo **reenvía** en las llamadas a `productos` y `clientes`.
3. Al confirmar, el ID queda **dentro del evento** (`request_id`, ver [EVENTOS.md](../services/movimientos/EVENTOS.md)).
4. El worker lo retoma y lo escribe en su log de alerta.

Para ver todo el recorrido de un pedido:
```bash
docker compose logs --no-log-prefix auth productos clientes movimientos worker-alertas 2>&1 | grep 9f1c2e7a4b3d4c6e8a1b2c3d4e5f6a7b
```
Con un solo ID se ven los logs de `movimientos` → `productos` → `worker-alertas` en orden de tiempo. La respuesta HTTP también devuelve el encabezado `X-Request-ID`, útil para reportar un problema.

## Catálogo de métricas

| Métrica | Tipo | Etiquetas | Qué indica |
|---|---|---|---|
| `http_requests_total` | contador | servicio, método, ruta (plantilla), estado | Pedidos atendidos |
| `http_request_duration_seconds` | histograma | servicio, método, ruta | Latencia (de acá salen media y p95) |
| `movimientos_registrados_total` | contador | categoría, resultado | Ventas/ingresos… por resultado (`confirmado`, `rechazado_409`, `pendiente_503`, …) |
| `movimientos_pendientes` | gauge | — | Sagas incompletas. **Debe ser 0** |
| `outbox_eventos_sin_publicar` | gauge | — | Eventos esperando a RabbitMQ. **Debe ser 0** |
| `outbox_publicaciones_total` | contador | resultado | Éxitos y fallos del relay |
| `productos_activos`, `productos_stock_bajo` | gauge | — | Catálogo y cuántos están por debajo del mínimo |
| `clientes_total` | gauge | — | Clientes registrados |
| `circuit_breaker_estado` | gauge | nombre | 0 cerrado · 1 semiabierto · 2 abierto |
| `circuit_breaker_transiciones_total`, `…_rechazos_total` | contador | nombre | Aperturas y llamadas rechazadas al instante |
| `auth_login_total` | contador | resultado | `exitoso`, `credenciales_invalidas`, `bloqueado` |
| `worker_mensajes_total` | contador | resultado | `alerta`, `sin_alerta`, `duplicado`, `reintento`, `dlq`, `invalido` |

Las rutas se etiquetan con su **plantilla** (`/api/v1/productos/{id_producto}`) y las inexistentes como `no_encontrada`, para que la cantidad de series no crezca con los datos.

## Alertas (`observabilidad/alertas.yml`)

| Alerta | Condición | Qué hacer |
|---|---|---|
| `ServicioCaido` | `up == 0` por 1 min | `docker compose ps`, `logs <servicio>` |
| `CircuitBreakerAbierto` | estado = 2 por 1 min | Revisar el servicio destino; se cierra solo al volver |
| `LatenciaP95Alta` | p95 > 1 s por 5 min | Ver el cuello de botella (README, «Rendimiento») |
| `TasaDeErrores5xxAlta` | > 5 % por 5 min | Logs del servicio |
| `MovimientosPendientesSinResolver` | pendientes > 0 por 10 min | Reintentar o `POST /api/v1/movimientos/reconciliar` |
| `OutboxSinPublicar` | > 0 por 5 min | ¿RabbitMQ caído o worker sin arrancar? |
| `MensajesEnDLQ` | mensajes a la DLQ | Inspeccionar `alertas.stock.bajo.dlq` (header `x-motivo-dlq`) |
| `PosibleFuerzaBrutaEnLogin` | > 30 logins fallidos/bloqueados en 5 min | Revisar IPs en los logs de nginx |

No hay Alertmanager: las alertas se **ven** en Prometheus/Grafana. Enviar mails o mensajes es el siguiente paso.

## Qué NO hay (honestidad)
- **Trazas distribuidas con spans** (OpenTelemetry/Jaeger): la correlación por `request_id` cubre el seguimiento de un pedido, pero no mide cuánto tardó cada tramo.
- Agregación centralizada de logs (Loki/ELK): los logs JSON están listos para enviarse a una.
