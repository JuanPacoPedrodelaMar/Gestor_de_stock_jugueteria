# ADR 0003 — Idempotencia con `Idempotency-Key` en cada capa

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Un reintento (del usuario, del navegador o de la saga) no debe descontar dos veces el stock ni crear dos movimientos.

## Decisión
- **Frontend:** un UUID por intento; se reutiliza solo si el intento terminó sin respuesta definitiva y el formulario no cambió.
- **`movimientos`:** columna `idempotency_key` con índice único. Mismo contenido → mismo movimiento; contenido distinto → 422.
- **`productos`:** tabla `ajustes_stock` con la clave como clave primaria, escrita en la **misma transacción** que el cambio de stock. Un ajuste rechazado por falta de stock no consume la clave.
- **Confirmación:** `UPDATE … WHERE estado='pendiente'`: solo quien logra la transición encola el evento.
- **Worker:** `INSERT OR IGNORE` por `id_movimiento`.
- **`auth`:** el refresh token es de un solo uso (`GETDEL` atómico).
La unicidad la garantiza **la base de datos**, no código Python: es lo único correcto bajo concurrencia.

## Consecuencias
+ Reintentos y pedidos simultáneos con la misma clave son seguros (probado con tests de concurrencia).
− La clave no está atada al usuario (otro usuario autenticado que repita una clave con idéntico contenido recibiría ese movimiento); mejora futura: incluir el `sub` del token en la unicidad.
− `POST /productos` (alta) no es idempotente.
