# ADR 0001 — Registrar un movimiento: saga de «intención primero» con recuperación hacia adelante

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Registrar un movimiento toca dos servicios con base propia: `movimientos` (historial) y `productos` (stock). No existe una transacción que abarque las dos bases, y cualquier paso puede fallar o perderse la respuesta (timeouts, caídas).

## Decisión
1. Se guarda primero el movimiento como `pendiente` (la **intención**).
2. Se llama a `productos` para ajustar el stock de forma atómica e idempotente (clave = `operacion_id`).
3. Si salió bien, se confirma el movimiento y se encola el evento **en la misma transacción** (ver ADR 0002).
Ante una falla ambigua el movimiento queda `pendiente`; se resuelve **hacia adelante**: reintentar con la misma `Idempotency-Key` o reconciliar (`POST /api/v1/movimientos/reconciliar`, solo admin), que consulta a `productos` si el ajuste llegó a aplicarse y **nunca** vuelve a tocar el stock.

## Alternativas descartadas
- **Commit en dos fases (2PC):** SQLite/FastAPI no lo soportan y bloquea recursos entre servicios.
- **Aplicar el stock primero y registrar después:** una falla entre ambos pasos deja stock modificado sin rastro.
- **Compensación (deshacer el stock):** ejecutaría por sorpresa una operación que el usuario quizá ya reintentó; además el «deshacer» también puede fallar.

## Consecuencias
+ Nunca hay stock modificado sin una intención registrada; no hay doble descuento.
− Existen estados transitorios (`pendiente`) visibles y hace falta reconciliar. Hoy la reconciliación es manual (los servicios no tienen credenciales propias); se mide con la métrica `movimientos_pendientes` y la alerta `MovimientosPendientesSinResolver`.
