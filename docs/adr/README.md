# Decisiones de arquitectura (ADR)

Cada archivo documenta una decisión: contexto, decisión, alternativas descartadas y consecuencias.

| N.º | Decisión |
|---|---|
| 0001 | [Registrar un movimiento: saga de «intención primero» con recuperación hacia adelante](./0001-saga-con-intencion-primero.md) |
| 0002 | [Publicar eventos con outbox transaccional (at-least-once) y consumidor idempotente](./0002-outbox-transaccional.md) |
| 0003 | [Idempotencia con `Idempotency-Key` en cada capa](./0003-idempotencia-en-cuatro-capas.md) |
| 0004 | [Redis con persistencia AOF y política fail-open/fail-closed](./0004-redis-persistente-y-fail-open.md) |
| 0005 | [Resiliencia en llamadas entre servicios: circuit breaker y reintentos acotados](./0005-resiliencia-circuit-breaker.md) |
| 0006 | [Observabilidad: logs JSON, ID de correlación y métricas Prometheus implementadas con la biblioteca estándar](./0006-observabilidad-propia.md) |
| 0007 | [Persistencia: SQLite con WAL ahora, Postgres si se necesita alta disponibilidad](./0007-sqlite-wal-y-limite-de-ha.md) |
| 0008 | [Un solo origen con TLS (nginx gateway + Caddy) y valores por defecto seguros](./0008-gateway-tls-y-defaults-seguros.md) |
| 0009 | [Un producto dado de baja sigue aceptando movimientos (decisión de negocio)](./0009-productos-dados-de-baja.md) |
