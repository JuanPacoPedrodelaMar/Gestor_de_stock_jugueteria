# Despliegue (producción) y CI/CD

El sistema corre en **un servidor con Docker** detrás de **Caddy** (HTTPS automático). Las imágenes las construye y publica el pipeline de GitHub Actions en **GHCR** (`ghcr.io`); el servidor solo las descarga.

```
Internet ──443──► Caddy (TLS) ──► frontend (nginx: panel + gateway) ──► auth / productos / clientes / movimientos
                                                                          └─► Redis · RabbitMQ · worker-alertas
(solo Caddy publica puertos: 80 y 443)
```

## 1. Preparar el servidor (una sola vez)

Requisitos: una máquina Linux con IP pública (cualquier VPS o el nivel gratuito de un proveedor de nube), puertos **80 y 443** abiertos, y un **dominio** apuntando a su IP (por ejemplo uno gratuito de DuckDNS).

```bash
# 1) Docker
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER   # volver a iniciar sesión

# 2) Carpeta del proyecto y variables
sudo mkdir -p /opt/jugueteria && sudo chown $USER /opt/jugueteria && cd /opt/jugueteria
# (los archivos docker-compose.prod.yml, despliegue/ y observabilidad/ los copia el pipeline; para la primera
#  vez se pueden copiar a mano con scp o clonar el repo)
cp .env.prod.example .env.prod && chmod 600 .env.prod
```
Completar **`.env.prod`**: `DOMINIO`, `IMAGE_PREFIX` (`ghcr.io/<usuario-en-minúsculas>/jugueteria`), `AUTH_SECRET_KEY` (`python3 -c "import secrets; print(secrets.token_urlsafe(64))"`), el primer administrador (`AUTH_ADMIN_*`) y las credenciales de RabbitMQ. **Nunca se sube al repositorio.**

Si el paquete de GHCR es privado, el servidor necesita iniciar sesión una vez: `echo <TOKEN con permiso read:packages> | docker login ghcr.io -u <usuario> --password-stdin`. (Más simple: marcar los paquetes como públicos.)

## 2. Configurar GitHub (una sola vez)

*Settings → Secrets and variables → Actions*

| Tipo | Nombre | Valor |
|---|---|---|
| Secret | `DEPLOY_HOST` | IP o nombre del servidor |
| Secret | `DEPLOY_USER` | Usuario SSH |
| Secret | `DEPLOY_SSH_KEY` | Clave privada SSH (la pública va en `~/.ssh/authorized_keys` del servidor) |
| Variable | `DEPLOY_DOMINIO` | El mismo dominio que `DOMINIO` |
| Variable | `DEPLOY_PATH` | (opcional) `/opt/jugueteria` |

Además, *Settings → Environments → New environment* llamado **`produccion`** (permite pedir aprobación manual antes de desplegar).

## 3. Publicar una versión

```bash
git tag v1.0.0-ae4 && git push origin v1.0.0-ae4
```
El pipeline (`.github/workflows/ci-cd.yml`) ejecuta, en orden:
1. **Prueba de sistema**: levanta todo con Docker Compose y corre `scripts/prueba_sistema.py --caida` (recorridos R1, R2, R3) y una carga corta (guarda el informe como artefacto).
2. **Publicar**: construye las 6 imágenes y las sube a GHCR con las etiquetas `sha-<commit>`, la versión (`1.0.0-ae4`) y `latest` (solo en `main`).
3. **Desplegar**: copia los archivos de despliegue, descarga las imágenes nuevas y reinicia con `docker compose -f docker-compose.prod.yml up -d`.
4. **Prueba de humo**: `GET /healthz` → 200; un login inválido → **401** (prueba toda la cadena Caddy→gateway→auth→Redis/BD); `/metrics` → **404** (no expuesto).
5. **Release** en GitHub con notas automáticas.

Si no están cargados los secretos `DEPLOY_*`, los pasos 3-4 se **omiten** sin fallar (las imágenes igual quedan publicadas).

## 4. Primer ingreso y operación

- Abrir `https://<dominio>` e iniciar sesión con el administrador de `.env.prod`. No hay usuarios de prueba.
- Ver estado: `docker compose -f docker-compose.prod.yml ps` · logs: `... logs -f movimientos`.
- Monitoreo: `docker compose -f docker-compose.prod.yml --profile observabilidad up -d` y túnel SSH (ver [OBSERVABILIDAD.md](./OBSERVABILIDAD.md)).
- **Volver a una versión anterior (rollback):** cambiar `IMAGE_TAG` en `.env.prod` por la versión previa y `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d`.
- **Backups:** los datos están en volúmenes (`auth_data`, `productos_data`, `clientes_data`, `movimientos_data`, `alertas_data`, `redis_data`, `rabbitmq_data`). Copia simple de una base: `docker run --rm -v jugueteria_productos_data:/d -v $PWD:/b alpine tar czf /b/productos-$(date +%F).tgz -C /d .`

## 5. Actualizar desde una versión anterior del repo (volúmenes existentes)
Las imágenes ahora corren con un usuario **sin privilegios** (UID 10001). Un volumen creado antes por un contenedor como root no será escribible: o se recrea (`docker compose down -v`, **borra los datos**) o se corrige el dueño: `docker run --rm -v <volumen>:/d alpine chown -R 10001:10001 /d`.

## 6. Qué probar después de desplegar
```bash
GATEWAY_URL=https://<dominio> ADMIN_EMAIL=<admin> ADMIN_PASSWORD=<clave> python3 scripts/prueba_sistema.py
```
(`/metrics` y el worker no están expuestos por el gateway, por eso esa prueba solo cubre lo público; el resto se verifica en el pipeline y por túnel SSH.)
