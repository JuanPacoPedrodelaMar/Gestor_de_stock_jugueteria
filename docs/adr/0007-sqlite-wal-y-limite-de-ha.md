# ADR 0007 — Persistencia: SQLite con WAL ahora, Postgres si se necesita alta disponibilidad

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Cada servicio tiene su base SQLite (propiedad de datos por servicio). SQLite permite un solo escritor y está ligada a un volumen local.

## Decisión
Se mantiene SQLite, endurecida: modo **WAL** (lectores sin bloquear al escritor), `busy_timeout=5000` y pool de 20 + 60 conexiones (antes 5 + 10, que se agotaba con 150 ventas simultáneas). Cada servicio es **una sola instancia**; la disponibilidad se apoya en `restart: unless-stopped`, healthchecks y en que la saga tolera caídas (los movimientos quedan pendientes y se completan al volver).

## Límite explícito
**No hay alta disponibilidad con réplicas**: con SQLite no se pueden replicar `productos` ni `movimientos`, y el relay del outbox es de instancia única. Para réplicas hay que migrar a Postgres (el acceso a datos ya está aislado en SQLAlchemy) y usar `SKIP LOCKED` en el relay. Se deja como evolución; la prueba de falla (R2) demuestra **degradación controlada y recuperación**, no réplicas.

## Consecuencias
+ Simple de operar y de testear; concurrencia mejorada.
− Techo de escalabilidad horizontal (ver el análisis de cuello de botella en el README).
