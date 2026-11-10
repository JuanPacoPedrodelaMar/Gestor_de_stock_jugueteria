# ADR 0004 — Redis con persistencia AOF y política fail-open/fail-closed

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
Redis guarda la **blacklist** de access tokens revocados y los **refresh tokens** (solo viven ahí). Sin persistencia, reiniciarlo desloguea a todos y «des-revoca» los access tokens cerrados (hasta 15 min).

## Decisión
- Redis corre con `--appendonly yes --appendfsync everysec` y un volumen (`redis_data`). Se pierde como máximo ~1 s de escrituras ante un corte.
- Si Redis **no responde**: `auth` falla (no puede emitir ni rotar tokens → 5xx) y los demás servicios hacen **fail-open** al validar la blacklist (aceptan el token mientras su firma y expiración sean válidas). Se prioriza disponibilidad de la operación; la ventana de riesgo está acotada por los 15 min del access token.
- Al **borrar un producto** (operación destructiva) se hace **fail-closed**: si no se puede consultar `movimientos`, no se borra.

## Alternativas descartadas
- Redis sin persistencia (versión anterior): logout masivo ante cada reinicio.
- Fail-closed en la validación de tokens: una caída de Redis tiraría todo el sistema.

## Consecuencias
Se acepta una ventana acotada en la que un token revocado podría seguir valiendo si Redis cae. Se documenta y se monitorea la disponibilidad de Redis.
