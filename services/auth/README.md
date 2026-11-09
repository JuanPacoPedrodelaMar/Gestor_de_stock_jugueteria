# services/auth

API REST de autenticación y autorización del sistema. Emite y revoca JWT
(access + refresh), gestiona usuarios y expone el endpoint `/me` con el que
el frontend obtiene los datos del usuario logueado. Construida con FastAPI +
SQLAlchemy + Redis.

## Ejecutar

Ver el README raíz del repositorio para levantar todo con Docker Compose.
Para correr solo este servicio en desarrollo:

```bash
cd services/auth
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
export AUTH_SECRET_KEY=clave-de-desarrollo
uvicorn app.main:app --reload --port 8001
```

Requiere Redis corriendo (o `REDIS_URL=memory://` para usar `fakeredis` en
desarrollo local, ver `requirements-local.txt`). Documentación interactiva:
`http://localhost:8001/docs`.

## Endpoints

Prefijo: `/api/v1/auth`.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/login` | Autentica email + contraseña y devuelve un par de tokens |
| `POST` | `/refresh` | Renueva el access token a partir de un refresh token |
| `POST` | `/logout` | Revoca los tokens actuales (agrega el `jti` a una blacklist en Redis) |
| `GET` | `/me` | Datos del usuario logueado (requiere access token válido) |
| `GET` | `/tokens/{jti}/revocado` | **Solo modo local sin Docker.** Dice si un access token fue revocado. Responde 404 salvo que `HABILITAR_CONSULTA_REVOCACION=true` |
| `GET` | `/health` | Healthcheck |

### Login

```bash
curl -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@test.com", "password": "admin12345"}'
```

Respuesta:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### Refresh

El refresh token es **de un solo uso**: cada llamada a `/refresh` devuelve un
refresh token nuevo en el header de respuesta `X-New-Refresh-Token`. Si el
cliente lo pierde y reutiliza el anterior, ese refresh queda invalidado.

```bash
curl -X POST http://localhost:8001/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<token>"}'
```

### Logout

Agrega el `jti` del access token a la blacklist de Redis
(`auth:blacklist:<jti>`), con TTL igual al tiempo de vida restante del
token. A partir de ese momento, cualquier servicio que valide JWT (auth,
productos, movimientos) rechaza ese token aunque su firma siga siendo
válida y no haya expirado.

## Autenticación entre servicios

`auth` es el **único** servicio que firma y revoca JWT. Los demás servicios
(`productos`, `movimientos`) validan el token **localmente**, compartiendo
la misma `AUTH_SECRET_KEY` por variable de entorno. La única dependencia de
red es Redis, para consultar la blacklist de revocados:

```
auth    ──(firma JWT con AUTH_SECRET_KEY)──►  cliente
cliente ──(Bearer <token>)──►  productos / movimientos
                                  │
                                  ├──(valida firma/expiración localmente)
                                  └──(consulta blacklist en Redis)
```

Si Redis está caído, `productos` y `movimientos` fallan hacia "no revocado"
(fail-open): siguen validando firma y expiración, pero pierden la capacidad
de rechazar tokens revocados antes de que expiren solos.

**Modo local sin Docker.** Con `REDIS_URL=memory://` cada servicio tiene su
propio Redis en memoria, así que `productos` y `movimientos` no verían los
tokens que `auth` revoca. Para que el logout sea efectivo igual, en ese modo
(`AUTH_SERVICE_URL` definida) le preguntan a `auth`
`GET /api/v1/auth/tokens/{jti}/revocado`. El endpoint está deshabilitado por
defecto (404) y es público a propósito, porque los servicios no tienen
credenciales propias: el `jti` es un UUID aleatorio y la respuesta es un solo
booleano, así que no revela nada a quien no tenga ya el token.
`ejecutar_local.ps1` configura las variables necesarias.

## Roles

| Rol | Qué puede hacer |
|---|---|
| `admin` | Todo: catálogo (cargar, editar, eliminar), movimientos, clientes, atender solicitudes de stock y gestionar usuarios. |
| `almacen` | Empleado de depósito. Ve el catálogo, **carga productos**, **elimina los que cargó él mismo durante 5 minutos** (ventana de arrepentimiento) y **solicita reposición de stock**. No edita productos, no registra movimientos y no ve clientes. |
| `ventas` | Atención al cliente. Ve el catálogo, **registra movimientos** (nunca los edita ni los borra) y **busca y crea clientes**. No toca el catálogo. |
| `mixto` | Suma los permisos de `almacen` y de `ventas`. |

Los empleados (`almacen`, `ventas`, `mixto`) **inician sesión con su DNI**; el
admin puede entrar con DNI o con email. El DNI viaja en el token (claim `dni`)
y es el que queda registrado como empleado en cada movimiento: no es un campo
que se complete a mano. El rol genérico `empleado` de versiones anteriores
se migra a `mixto` al arrancar (conserva los permisos que tenía).

El rol viaja en el payload del JWT (`rol`) y cada servicio lo verifica en
sus propios endpoints según sus propias reglas.

## Login con DNI o email

`POST /api/v1/auth/login` acepta **uno** de los dos identificadores:

```json
{ "dni": "30000002", "password": "almacen123" }
{ "email": "admin@test.com", "password": "admin12345" }
```

Enviar ninguno o los dos devuelve `400`. El DNI son 7 u 8 dígitos y es único
por usuario. Los intentos fallidos se cuentan por identificador (DNI o email),
y el access token incluye el claim `dni`, que `movimientos` usa para registrar
quién hizo cada operación. Crear un usuario con rol de empleado exige un DNI
(`POST /api/v1/auth/usuarios`); para el admin es opcional.

## Usuarios de prueba

Con `HABILITAR_USUARIOS_PRUEBA=true` en el `.env` (valor por defecto), el
servicio crea una cuenta por rol al arrancar (las que todavía no existan):

| Rol | DNI | Email | Contraseña |
|---|---|---|---|
| `admin` | `20000001` | `admin@test.com` | `admin12345` |
| `almacen` | `30000002` | `almacen@test.com` | `almacen123` |
| `ventas` | `30000003` | `ventas@test.com` | `ventas123` |
| `mixto` | `30000004` | `mixto@test.com` | `mixto123` |

Los valores salen de las variables `PRUEBA_<ROL>_EMAIL`, `_DNI` y `_PASSWORD`.
Opcionalmente se puede definir un admin propio con `AUTH_ADMIN_EMAIL` /
`AUTH_ADMIN_PASSWORD` (se crea solo si la base de usuarios está vacía).

Para entornos reales, poner `HABILITAR_USUARIOS_PRUEBA=false`: no se crean
los usuarios y el frontend deja de recibir las credenciales.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/auth.db` | Base propia de Auth |
| `AUTH_SECRET_KEY` | — (obligatoria) | Secreto compartido con los demás servicios para firmar/validar JWT |
| `REDIS_URL` | `redis://localhost:6379/0` | Blacklist de tokens revocados. `memory://` para modo local |
| `HABILITAR_CONSULTA_REVOCACION` | `false` | Habilita `GET /api/v1/auth/tokens/{jti}/revocado`. Solo para el modo local sin Docker (ver abajo); con Docker no hace falta |
| `HABILITAR_USUARIOS_PRUEBA` | `true` | Crea los usuarios de prueba al arrancar (solo desarrollo) |
| `PRUEBA_<ROL>_EMAIL` / `_PASSWORD` / `_DNI` | ver tabla de usuarios de prueba | Credenciales de la cuenta de prueba de cada rol (`ADMIN`, `ALMACEN`, `VENTAS`, `MIXTO`) |
| `AUTH_ADMIN_EMAIL` / `AUTH_ADMIN_PASSWORD` / `AUTH_ADMIN_DNI` | — | Admin propio, se crea solo si la base está vacía (el DNI es opcional) |

## Persistencia

SQLite mediante SQLAlchemy, en su propio volumen Docker (`auth_data`). Base
**independiente** de `productos` y `movimientos`: cada servicio es dueño de
sus datos, y la comunicación entre ellos es vía API REST, nunca compartiendo
tablas. La blacklist de tokens revocados vive en Redis, que sí se comparte
con los otros servicios (es el único estado distribuido necesario).

## Tests

```bash
cd services/auth
pip install -r requirements-dev.txt
pytest
```

Los tests cubren:
- **Login** (`test_login.py`): credenciales válidas/inválidas, usuario
  inactivo, formato de la respuesta.
- **Logout** (`test_logout.py`): el token queda en la blacklist y se
  rechaza en requests posteriores.
- **Refresh** (`test_refresh.py`): rotación del refresh token (el anterior
  deja de funcionar), refresh inválido o expirado.
- **Roles** (`test_roles.py`): cada endpoint respeta los roles permitidos.
- **Consulta de revocación** (`test_consulta_revocacion.py`): deshabilitado por
  defecto, y tras un logout el `jti` figura como revocado.

Los tests corren contra una base SQLite en memoria, aislados entre sí. Para
Redis, por defecto esperan uno **real** en `localhost:6379/15` (como el CI, donde
se levanta como servicio); la base 15 se vacía antes de cada test (ver
`tests/conftest.py`). Con `REDIS_URL=memory://` usan `fakeredis` y no necesitan
nada instalado (es lo que hace `.\ejecutar_local.ps1 -Tests`). No correrlos
contra el Redis de `docker compose` (base 0), porque se borraría la blacklist de
tokens.

## Contrato de la API

El contrato OpenAPI está exportado en [`openapi.json`](./openapi.json)
(regenerarlo con `python export_openapi.py` tras cualquier cambio de
schemas o rutas) y también disponible en vivo en `/docs` y `/openapi.json`
mientras el servicio corre.