# ADR 0008 — Un solo origen con TLS (nginx gateway + Caddy) y valores por defecto seguros

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
En desarrollo el panel llama a cada API en su puerto (CORS). Para un despliegue real conviene exponer un único punto de entrada con HTTPS y no publicar APIs, Redis, RabbitMQ ni `/metrics`. Además los defaults del compose activaban usuarios de prueba y el endpoint de seed.

## Decisión
- El nginx del frontend actúa también de **gateway** por prefijo de ruta (`/api/v1/auth`, `/productos`, `/solicitudes-stock`, `/clientes`, `/movimientos`; el historial `/productos/{id}/movimientos` va a `movimientos`). No enruta `/metrics` ni `/api/v1/dev/*`. Limita el login a 10 pedidos/min por IP y genera el `X-Request-ID`.
- **Caddy** termina TLS (Let's Encrypt automático) y agrega HSTS.
- `config.js` admite el valor `origen` (mismo origen) → en producción no hace falta CORS.
- `docker-compose.yml` trae defaults **seguros** (sin usuarios de prueba, sin seed, RabbitMQ sin puertos); `docker-compose.override.yml` (aplicado automáticamente en desarrollo) los activa. `docker-compose.prod.yml` es independiente, usa imágenes del registry y exige los secretos.
- CSP estricta (`script-src 'self'`): se eliminaron los `onclick` y el `<script>` inline del panel.

## Consecuencias
+ Superficie expuesta mínima y configuración explícita por entorno.
− El rate limit por IP depende de ver la IP real del cliente (detrás de otro proxy habría que configurar `real_ip`).
