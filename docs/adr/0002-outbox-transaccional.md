# ADR 0002 — Publicar eventos con outbox transaccional (at-least-once) y consumidor idempotente

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Al confirmar un movimiento hay que avisar al worker de alertas por RabbitMQ. Publicar directo después del `commit` puede perder el evento si el proceso cae o el broker no responde; publicar antes puede anunciar algo que no se confirmó.

## Decisión
El evento se guarda en la tabla `outbox_eventos` **en la misma transacción** que la confirmación del movimiento. Un *relay* (hilo de `movimientos`) lo publica en RabbitMQ con confirmaciones del broker, mensajes persistentes y `mandatory` (si ninguna cola está enlazada, el evento se conserva en lugar de perderse), con backoff ante fallas. La entrega es **at-least-once**, así que el worker es **idempotente** por `id_movimiento`.

## Alternativas descartadas
- **Publicar directo tras el commit:** pierde eventos ante caídas.
- **Exactly-once:** no es alcanzable de punta a punta con un broker; se prefiere at-least-once + idempotencia.
- **CDC / Debezium:** excesivo para este alcance.

## Consecuencias
+ Ningún evento se pierde aunque RabbitMQ esté caído (se acumula en el outbox y se publica al volver).
− El relay es de **instancia única** por base SQLite: con varias réplicas publicarían duplicados (el consumidor los toleraría, pero sería ineficiente). Para replicar `movimientos` hay que pasar a Postgres con `SELECT … FOR UPDATE SKIP LOCKED` (ADR 0007).
− La tabla crece sin purga (mejora pendiente).
