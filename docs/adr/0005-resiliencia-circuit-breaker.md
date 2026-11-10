# ADR 0005 — Resiliencia en llamadas entre servicios: circuit breaker y reintentos acotados

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
`movimientos` llama a `productos` y `clientes` por HTTP con timeout de 5 s. Si `productos` se cuelga, cada pedido espera 5 s y los hilos se acumulan: `movimientos` se degrada también (falla en cascada).

## Decisión
Un **circuit breaker** por dependencia (`app/core/resiliencia.py`, sin librerías):
`CERRADO → ABIERTO` tras 5 fallos consecutivos (`CB_UMBRAL_FALLOS`); abierto, rechaza al instante con 503 durante 15 s (`CB_ESPERA_SEGUNDOS`); luego deja pasar **una** llamada de prueba (`SEMIABIERTO`). Solo cuentan como fallo timeouts, errores de conexión y HTTP 5xx; un 404/409 es una respuesta de negocio sana.
**Reintentos con backoff exponencial y jitter**: 1 reintento (`PRODUCTOS_REINTENTOS`) para lecturas ante cualquier falla de transporte, y para la escritura (`ajustar_stock`) **solo ante errores de conexión** (el pedido nunca llegó). Repetirla es seguro porque el ajuste es idempotente.
Rechazar rápido es compatible con la saga: el movimiento queda `pendiente` y se completa luego con la misma clave.

## Alternativas descartadas
- `pybreaker`/`tenacity`: dependencias nuevas para algo pequeño y testeable con reloj inyectado.
- Reintentar siempre sin breaker: multiplica la carga sobre un servicio ya caído.

## Consecuencias
+ Con `productos` caído, `movimientos` responde en milisegundos (503) en lugar de 5 s, y se recupera solo al volver. Métricas: `circuit_breaker_estado`, `circuit_breaker_transiciones_total`, `circuit_breaker_rechazos_total`.
− Umbrales fijos por variable de entorno (sin ajuste dinámico). El breaker es por proceso (no compartido entre réplicas).
