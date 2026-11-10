# Evidencias para el AE4

Qué pide la consigna, dónde está la evidencia en el repositorio y cómo reproducirla. La columna **Estado**
separa lo que **ya está en el repositorio** de lo que **solo el equipo puede completar** (despliegue real,
mediciones, historial Git, entregables personales).

| Criterio (peso) | Evidencia en el repo | Cómo reproducirla | Estado |
|---|---|---|---|
| **Integración funcional (15)** | Recorridos R1, R2, R3 automatizados en `scripts/prueba_sistema.py`; flujo manual en README «Cómo probar el sistema de punta a punta» | `docker compose up -d --build` → `python scripts/prueba_sistema.py --caida` | Implementado · ⚠ falta confirmar con la cátedra el alcance de «8 servicios» (hoy 5 componentes + panel) |
| **Arquitectura, contratos, datos (10)** | `docs/ARQUITECTURA.md` (servicios, capas, propiedad de datos, despliegue, correlación, breaker), `docs/adr/` (9 ADR), OpenAPI por servicio (`openapi.json`), `services/movimientos/EVENTOS.md` | Abrir los archivos; `/docs` de cada API en desarrollo | Implementado |
| **Comunicación distribuida, estado, concurrencia, idempotencia (10)** | Saga + outbox + idempotencia en 4 capas; DLQ y mensajes inválidos corregidos; tests `test_concurrencia_stock`, `test_idempotencia_ajuste`, `test_saga_consistencia`, `test_outbox`, `test_worker_alertas` | `pytest` en cada servicio; prueba de sistema (R3 + idempotencia) | Implementado |
| **Seguridad (8)** | JWT + roles (4), blacklist/rotación/bloqueo, BOLA en solicitudes (cada usuario ve las suyas), DNI del empleado tomado del token, validación y topes de entrada, headers en las 4 APIs y nginx (CSP estricta), rate limit de login, defaults seguros, secretos por entorno, `pip-audit` en CI | `pytest`; `curl -I`; README «Seguridad de las APIs» | Implementado · ⚠ TLS depende del despliegue real |
| **Calidad, testing, accesibilidad, performance (8)** | 446 funciones de test (unidad, API, concurrencia, saga, outbox, resiliencia, observabilidad), prueba de sistema, auditoría de contraste (`scripts/auditar_contraste.py`), ARIA y teclado en todos los desplegables, `scripts/prueba_carga.py` | `pytest`; `python scripts/auditar_contraste.py frontend/index.html`; `python scripts/prueba_carga.py` | Implementado · ⚠ **falta ejecutar la carga y completar los números del README** |
| **Contenedores, CI/CD, registry, despliegue remoto (8)** | Dockerfiles endurecidos (multi-stage, usuario no root), `docker-compose.prod.yml`, `.github/workflows/ci-cd.yml` (sistema → GHCR → despliegue → humo → release), `docs/DESPLIEGUE.md` | `git tag v1.0.0-ae4 && git push --tags` | Preparado · ⚠ **falta provisionar el servidor, cargar secretos y ejecutar el pipeline** |
| **Resiliencia, HA, observabilidad (6)** | Circuit breaker + reintentos (ADR 0005), prueba de falla R2, logs JSON, `X-Request-ID`, `/metrics`, Prometheus + Grafana + 8 alertas (`observabilidad/`) | `docker compose --profile observabilidad up -d`; `python scripts/prueba_sistema.py --caida` | Implementado · HA con réplicas **no** (ADR 0007: degradación controlada) |
| **Trazabilidad Git y documentación (10)** | README, `docs/`, ADRs, `docs/CAMBIOS_AE4.md` | — | ⚠ **El equipo**: commits pequeños y claros, ramas/PRs/issues, tags (el zip no incluye `.git`) |
| **Portafolio, integración con otros equipos, bitácoras (5)** | `docs/plantillas/BITACORA_INDIVIDUAL.md`, informe `Informe_AE4` | — | ⚠ **El equipo**: la bitácora es **personal** y debe reflejar el trabajo real de cada integrante |
| **Coloquio (20)** | Preguntas de repaso en el informe (sección 11) | — | ⚠ Preparación individual |

## Reproducir la verificación completa

```bash
# 1) Tests por servicio (en cada carpeta de services/)
pip install -r requirements-dev.txt && pytest
# 2) Controles transversales
python scripts/verificar_copias.py && python scripts/auditar_contraste.py frontend/index.html
# 3) Sistema completo
docker compose up -d --build --wait
python scripts/prueba_sistema.py --caida
python scripts/prueba_carga.py --niveles 1,10,25,50 --duracion 15 --actualizar-readme README.md
docker compose --profile observabilidad up -d     # Grafana en http://localhost:3000
```

## Capturas recomendadas para el Portafolio
1. Pantalla de **Prometheus → Targets** con los 5 servicios *UP*.
2. **Dashboard de Grafana** durante la prueba de carga (latencia p95, req/s).
3. Salida de `prueba_sistema.py --caida` completa (R1, R2, R3).
4. **Logs JSON** de una venta con el mismo `request_id` en `movimientos`, `productos` y `worker-alertas`.
5. Pantalla de **GitHub Actions** con el pipeline en verde y los paquetes en **GHCR**.
6. La **URL pública** funcionando con el candado de HTTPS.
