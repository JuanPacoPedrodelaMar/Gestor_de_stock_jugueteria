# services/productos

API REST del CRUD de la entidad **Producto** del sistema de gestión de stock
para la juguetería, más el endpoint atómico de ajuste de stock que consume
`services/movimientos`. Construida con FastAPI + SQLAlchemy.

## Ejecutar

Ver el README raíz del repositorio para levantar todo con Docker Compose.
Para correr solo este servicio en desarrollo:

```bash
cd services/productos
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
mkdir -p data   # SQLite no crea directorios intermedios por su cuenta
export AUTH_SECRET_KEY=clave-de-desarrollo
uvicorn app.main:app --reload
```

La variable `AUTH_SECRET_KEY` es obligatoria: el servicio la usa para
validar los JWT emitidos por `services/auth`. Debe ser **la misma** que usa
`auth` para firmar. En Docker llega por `.env`; para correr localmente hay
que exportarla (cualquier string sirve mientras sea consistente con la que
usa el `auth` local).

Documentación interactiva: `http://localhost:8000/docs`.

## Autenticación

Todos los endpoints de la API (excepto `/health`, `/` y el router de seed
si está habilitado) exigen un JWT válido en el header `Authorization:
Bearer <access_token>`.

El servicio **valida el JWT localmente** usando el mismo `AUTH_SECRET_KEY`
que usó `auth` para firmarlo. No llama a `auth` por cada request — eso
agregaría una llamada de red y un punto de falla extra. La única
dependencia de red real es Redis, para consultar la blacklist de tokens
revocados (un logout debe invalidar el token en todos los servicios que lo
acepten, no solo en `auth`).

Roles:

| Rol | Acceso |
|---|---|
| `admin` | CRUD completo, `DELETE` sin restricciones y atender solicitudes de stock |
| `almacen` | Listar, ver, **crear**; **eliminar solo lo que cargó él mismo durante los primeros 5 minutos**; pedir reposición de stock. **No** edita. |
| `ventas` | Listar y ver. No crea, edita ni elimina. Sus movimientos sí ajustan el stock (vía `movimientos`). |
| `mixto` | Lo de `almacen` y lo de `ventas`. |

### Ventana de arrepentimiento para eliminar

Cada producto guarda quién lo cargó (`creado_por`) y cuándo (`fecha_creacion`).
Un `almacen` o `mixto` puede eliminar un producto **solo si lo cargó él mismo y
hace menos de 5 minutos** (`PRODUCTO_COOLDOWN_BORRADO_SEGUNDOS`, por defecto
300): sirve para deshacer una carga hecha por error. Pasado ese tiempo, o si lo
cargó otra persona, recibe `403` con el motivo y solo un `admin` puede
eliminarlo. Los productos anteriores a este campo (sin autor) también quedan
solo para el admin. La eliminación sigue las reglas de siempre: con movimientos
asociados es una baja lógica.

Para que el panel sepa qué botón mostrar, cada producto de `GET` y `POST`
incluye `puede_eliminar` y `segundos_restantes_eliminar`, calculados para quien
consulta (el admin siempre puede y no tiene límite de tiempo).

Ver `app/core/jwt_auth.py` para el mecanismo de validación.

## Endpoints

| Método | Ruta | Descripción | Rol mínimo |
|---|---|---|---|
| GET | `/api/v1/productos` | Lista productos. Por defecto solo `activo=true`. `?incluir_inactivos=true` para ver también los dados de baja. | cualquiera |
| GET | `/api/v1/productos/{id}` | Obtiene un producto por ID (activo o no). | cualquiera |
| POST | `/api/v1/productos` | Crea un producto. Acepta `stock_actual` (default 0). Registra el autor. | `admin`, `almacen`, `mixto` |
| PUT | `/api/v1/productos/{id}` | Actualiza datos descriptivos. **No acepta `stock_actual`** (ver más abajo). | `admin` |
| DELETE | `/api/v1/productos/{id}` | Elimina o da de baja según tenga movimientos asociados (ver más abajo). Empleados: solo lo suyo y dentro de la ventana de 5 min. | `admin`, `almacen`*, `mixto`* |
| PATCH | `/api/v1/productos/{id}/ajustar-stock` | Ajusta el stock atómicamente. **Endpoint interno**, consumido por `services/movimientos` con el token de quien registra el movimiento. | `admin`, `ventas`, `mixto` |
| GET | `/api/v1/productos/ajustes/{clave}` | ¿Se aplicó un ajuste con esa `Idempotency-Key`? 200 o 404. Lo usa `movimientos` para reconciliar. | `admin`, `ventas`, `mixto` |
| POST | `/api/v1/solicitudes-stock` | Pide reposición de un producto. **No cambia el stock**: es un aviso. | `almacen`, `mixto` |
| GET | `/api/v1/solicitudes-stock?estado=` | Lista solicitudes (el admin ve todas; almacén y mixto, las propias). | `admin`, `almacen`, `mixto` |
| PATCH | `/api/v1/solicitudes-stock/{id}` | Marca una solicitud pendiente como `atendida` o `rechazada` (`409` si ya estaba resuelta). | `admin` |
| GET | `/health` | Healthcheck (sin auth). | — |
| POST | `/api/v1/dev/seed-productos?cantidad=N` | Genera N productos de prueba. Solo desarrollo. | `admin` |

\* con las restricciones de la sección anterior (solo productos propios, durante la ventana).

El contrato completo está exportado en [`openapi.json`](./openapi.json)
(regenerarlo con `python export_openapi.py` tras cualquier cambio de
schemas o rutas) y también disponible en vivo en `/docs` y `/openapi.json`
mientras el servicio corre.

### `PATCH /api/v1/productos/{id}/ajustar-stock`

Este endpoint es el que usa `services/movimientos` para reflejar ventas,
ingresos, estropeos y devoluciones sobre el stock. El body es:

```json
{ "delta": -1 }
```

`delta > 0` incrementa el stock (ingreso, devolución); `delta < 0` intenta
decrementarlo (venta, estropeo). El ajuste se aplica de forma **atómica**
(ver sección Concurrencia más abajo), así que es seguro ante llamadas
concurrentes: nunca deja `stock_actual` negativo.

**Idempotente (opcional):** si se envía el header `Idempotency-Key`, el ajuste se
aplica **una sola vez por clave**. La clave se guarda en la tabla
`ajustes_stock` **en la misma transacción** que el cambio de stock, así que no
puede quedar un ajuste aplicado sin su clave ni al revés. Repetir el pedido
(mismo producto y misma cantidad) devuelve `200` con el producto actual y no
vuelve a modificar el stock; con dos pedidos simultáneos con la misma clave, la
clave primaria deja pasar a uno solo y el otro revierte su cambio. Reutilizar la
clave para un ajuste distinto devuelve `422`. Un ajuste rechazado por falta de
stock (409) **no** consume la clave. Es lo que permite a `movimientos`
reintentar o recuperar un movimiento pendiente sin descontar dos veces. Sin
header, el comportamiento es el de siempre.

El token del usuario que originó el movimiento se propaga desde
`movimientos` hacia acá — no se usan credenciales de servicio. Así, las
reglas de rol se aplican siempre sobre el usuario real.

## Decisiones de diseño (issue #6)

### 1. El PUT ya no puede pisar `stock_actual`

**Problema original:** `ProductoUpdate` heredaba todos los campos de
`ProductoBase`, incluido `stock_actual` como obligatorio. Esto forzaba a
cualquier cliente que quisiera editar solo, por ejemplo, el precio, a
mandar también el stock — y si ese valor había cambiado entre que el
cliente cargó el formulario y lo envió (por una venta, una carga de
mercadería, etc.), el PUT lo pisaba con un dato desactualizado, perdiendo
información real de inventario.

**Solución:** `ProductoUpdate` ya no incluye `stock_actual` en absoluto.
El schema deliberadamente no lo declara, así que:
- El contrato OpenAPI documenta explícitamente que el PUT no lo acepta.
- Si un cliente igual lo manda en el body, Pydantic lo ignora (no forma
  parte del modelo, así que nunca llega a `model_dump()`).
- `producto_service.actualizar_producto` solo puede tocar los campos que
  el schema declara: `nombre`, `marca`, `precio_venta`, `stock_minimo`,
  `categoria`.

El stock operativo (`stock_actual`) queda reservado para modificarse
exclusivamente a través de **movimientos de inventario** (entradas,
salidas, ajustes) — nunca editando la ficha del producto. `ProductoCreate`
sí acepta `stock_actual` (con default `0`) porque dar de alta un producto
requiere declarar su stock inicial.

### 2. Baja lógica en vez de borrado físico cuando hay movimientos

**Problema:** borrar físicamente un producto que tiene movimientos de
stock asociados destruiría la trazabilidad histórica de esos movimientos
(¿a qué producto correspondía esa entrada de 50 unidades del mes pasado?).

**Solución:** se agregó el campo `activo: bool` (default `True`) al
modelo `Producto`. El comportamiento de `DELETE /api/v1/productos/{id}`
depende de si el producto tiene movimientos asociados:

- **Sin movimientos:** se borra físicamente, como antes → `204 No Content`.
- **Con movimientos:** se marca `activo = False` (baja lógica) en lugar de
  borrarse → `200 OK` con el producto actualizado en el body, para que el
  cliente distinga ambos casos.

Un producto dado de baja:
- Sigue siendo consultable por `GET /api/v1/productos/{id}` (para ver su
  detalle o su historial).
- **No** aparece en `GET /api/v1/productos` por defecto.
- Sí aparece con `GET /api/v1/productos?incluir_inactivos=true`.

**Cómo se decide "tiene movimientos":** `producto_service.tiene_movimientos_asociados`
consulta de verdad al servicio `movimientos`
(`GET /api/v1/productos/{id}/movimientos/cantidad`, vía
`app/clients/movimientos_client.py`), reenviando el token del admin que hace la
baja. Cuenta los movimientos confirmados y también los pendientes de
confirmación (el stock pudo haberse ajustado ya).

Si `movimientos` no responde, el `DELETE` **falla cerrado**: devuelve `503` y no
borra ni da de baja nada. Suponer "sin movimientos" ante la duda llevaría a
borrar físicamente un producto con historial, que es justo lo que esta
decisión evita. La consulta y el borrado no forman una transacción (son
servicios distintos), así que un movimiento registrado en los milisegundos
entre ambos pasos no se vería.

`productos` solo llama a `movimientos` en tiempo de ejecución; en
`docker-compose.yml` no hay `depends_on` en esa dirección (movimientos ya
depende de productos y sería un ciclo).

## Concurrencia en el ajuste de stock

### Problema

El endpoint `PATCH /ajustar-stock` puede recibir múltiples requests
concurrentes sobre el mismo producto (por ejemplo, dos ventas simultáneas
desde dos cajas, disparadas ambas por `services/movimientos`). Un ajuste
implementado como "leer stock → validar en Python → escribir nuevo valor"
produce una **condición de carrera** conocida como *lost update*: ambos
requests leen el mismo stock antes de que ninguno escriba, ambos pasan la
validación "hay stock suficiente", y ambos descuentan.

### Resultado incorrecto

Con `stock_actual = 1` y dos ventas simultáneas de 1 unidad cada una:

- **2 ventas aceptadas** sobre un producto que solo tenía 1 unidad
  (sobreventa).
- El stock final no refleja las dos operaciones aceptadas (lost update).

### Mecanismo

La función `producto_service.ajustar_stock_atomico` evalúa la condición de
stock **dentro de la propia sentencia SQL**:

```sql
UPDATE productos
   SET stock_actual = stock_actual + :delta
 WHERE id_producto = :id
   AND stock_actual >= :delta_absoluto   -- solo cuando delta < 0
```

La base de datos resuelve la carrera atómicamente: si dos `UPDATE` intentan
matchear la misma fila, solo uno puede tener éxito. El otro devuelve
`rowcount == 0`, que el router traduce a **409 Conflict**. El resultado es
que nunca se acepta una venta sin stock suficiente, sin importar el orden
de llegada ni el paralelismo.

### Verificación

`tests/test_concurrencia_stock.py` corre dos escenarios con hilos reales
(`threading.Thread` + `threading.Barrier` para forzar el entrelazado):

- `test_ajuste_no_atomico_permite_sobreventa`: reproduce el problema
  (asserta que las 2 ventas se aceptan con un ajuste no atómico).
- `test_ajuste_atomico_previene_sobreventa`: prueba la solución (asserta
  que exactamente una venta se acepta, la otra se rechaza con
  `"sin_stock"`, y el stock nunca queda negativo).

```bash
cd services/productos
pip install -r requirements-dev.txt
python -m pytest tests/test_concurrencia_stock.py -v
```

## Validación de entrada y encabezados de seguridad

**Validación.** Los campos de texto libre (`nombre`, `marca`, `categoria`) no
pueden contener `<` `>` `;` `=` `{` `}` `\`, el acento grave ni caracteres de
control (byte nulo, saltos de línea, tabulaciones). Un valor así devuelve
`400` con el formato de error del proyecto, antes de tocar la base. Se
aceptan tildes, ñ y la puntuación habitual (`. , - ' & / ( ) + : % # ° ® ™ ! ?`).
El filtro está en `ProductoEntrada` (base de `ProductoCreate` y
`ProductoUpdate`) y **no** en `ProductoOut`: así un producto guardado antes de
este control sigue listándose sin dar un `500`.

**Headers.** Un middleware agrega `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` y `Content-Security-Policy: frame-ancestors 'none'` a
toda respuesta, incluidos los errores. El `500` inesperado lo arma Starlette
por fuera de los middlewares, así que su handler los recibe explícitos.

Ambos puntos están cubiertos por `tests/test_bateria_minima.py`.

## Datos de prueba (`/api/v1/dev/seed-productos`)

Endpoint de utilidad para poblar rápido el inventario con productos
variados (nombre, marca, categoría, precio y stock generados
aleatoriamente dentro de rangos razonables) mientras se prueba la app —
por ejemplo, para ver el listado con muchos registros o el indicador de
"stock bajo" con datos reales. Se dispara desde el botón **"🎲 Cargar
datos de prueba"** en el panel del frontend, junto al título del
inventario.

- `POST /api/v1/dev/seed-productos?cantidad=N` (1 a 200, default 20).
- Agrega productos al inventario existente, no lo reemplaza ni lo limpia.
- No forma parte del CRUD de negocio de Producto (vive en un router
  aparte, `app/routers/seed_router.py`), y se puede deshabilitar con la
  variable de entorno `HABILITAR_SEED_ENDPOINT=false` (ver
  `.env.example`) para no exponerlo en un entorno que no sea de
  desarrollo/pruebas.
- Solo el rol `admin` puede usarlo.

## Persistencia

SQLite mediante SQLAlchemy, con la URL de conexión configurable por la
variable de entorno `DATABASE_URL` (ver `.env.example` en la raíz del
repo). En Docker, el archivo vive en el volumen nombrado `productos_data`,
montado en `/app/data` — nunca en el repositorio (ver *Limitaciones*).

**Por qué SQLite y no Postgres/MySQL:** es un proyecto académico de alcance
acotado, con un único servicio consumidor de esta base (además de
`movimientos`, que accede por API, no por SQL). SQLite no requiere levantar
un contenedor adicional ni gestionar credenciales, lo que simplifica la
reproducibilidad (`docker compose up` sin dependencias externas). La capa
de acceso a datos está detrás de SQLAlchemy, así que migrar a Postgres en
el futuro implica cambiar `DATABASE_URL` y agregar el driver
correspondiente al `requirements.txt`, sin tocar modelos, schemas ni
lógica de negocio.
- **El filtro de caracteres es una lista de prohibidos, no una lista
  blanca**: es una capa adicional; la defensa principal contra la inyección
  SQL son las consultas con parámetros enlazados de SQLAlchemy.
- **Pool de conexiones**: con el pool por defecto de SQLAlchemy (5 más 10 de
  desborde), 150 ventas simultáneas agotaban las conexiones (`QueuePool limit
  of size 5 overflow 10 reached`); con `pool_size=20` y `max_overflow=60` se
  resolvieron todas. **Ese ajuste ya está aplicado** en `app/database/db.py`
  (variables `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`), junto con SQLite en modo WAL
  y `busy_timeout`.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/jugueteria.db` | URL de la base propia |
| `AUTH_SECRET_KEY` | — (obligatoria) | Mismo secreto que `auth`, para validar JWT localmente |
| `REDIS_URL` | `redis://localhost:6379/0` | Para consultar la blacklist de tokens revocados. Se puede usar `memory://` en desarrollo (usa `fakeredis`) |
| `AUTH_SERVICE_URL` | — | **Solo modo local** (`REDIS_URL=memory://`): URL de `auth`. Como cada servicio tiene su propio Redis en memoria, acá se le pregunta a `auth` si un token fue revocado para que el logout sea efectivo |
| `MOVIMIENTOS_SERVICE_URL` | `http://localhost:8002` | URL interna del servicio Movimientos (para saber si un producto tiene historial). En Docker Compose: `http://movimientos:8000` |
| `MOVIMIENTOS_SERVICE_TIMEOUT` | `5` (segundos) | Timeout de esa consulta |
| `HABILITAR_SEED_ENDPOINT` | `true` | Habilita/deshabilita el router de seed |

## Limitaciones conocidas

- **La baja de un producto depende de que `movimientos` responda**: si está
  caído, `DELETE` devuelve 503 (ver "Baja lógica"). Es deliberado (falla
  cerrado), pero significa que no se puede borrar mientras `movimientos` no esté
  disponible.
- **Sin paginación** en `GET /api/v1/productos`: devuelve el listado
  completo. Con el volumen de datos esperado para una juguetería (decenas
  o cientos de productos) no es un problema práctico, pero no escalaría
  a catálogos de miles de ítems sin agregar `limit`/`offset`.
- **SQLite en un único archivo**: no soporta escrituras concurrentes de
  alto volumen (es una limitación del motor, no de la lógica). Para el
  alcance actual es suficiente; la concurrencia crítica está resuelta a
  nivel de sentencia SQL (ver sección Concurrencia). Ver la nota de
  persistencia sobre migración a Postgres.
- **CORS abierto (`allow_origins=["*"]`)**: correcto para desarrollo y para
  el alcance de este proyecto, pero en un despliegue productivo debería
  restringirse al dominio real del frontend.
- **Fail-open si Redis está caído**: si Redis no responde, la validación
  de la blacklist de tokens falla hacia "no revocado" (se sigue validando
  firma y expiración). Es una decisión para no bloquear todo el servicio
  por una dependencia secundaria; la contrapartida es que un logout no
  invalida el token hasta que expire solo. En el modo local sin Docker, con
  `AUTH_SERVICE_URL` definida, la revocación se consulta a `auth` (una llamada
  HTTP por request) y, si `auth` no responde, se aplica el mismo criterio.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

(En Windows, `.\ejecutar_local.ps1 -Tests` desde la raíz del repositorio hace
todo esto sola; `-Bateria` corre solo `test_bateria_minima.py`.) Los tests no
están dentro de la imagen de Docker.

La suite cubre:
- **CRUD** (`tests/test_crud_productos.py`): camino feliz de las 5
  operaciones y sus 404.
- **Validaciones** (`tests/test_validaciones_productos.py`): campos
  obligatorios, valores negativos, longitudes, tipos inválidos, y en
  particular que el PUT nunca modifique `stock_actual` aunque el cliente
  intente enviarlo.
- **Baja lógica** (`tests/test_baja_logica_productos.py`): comportamiento
  de `DELETE` con y sin movimientos (simulados con el stub `movimientos_stub`
  de `conftest.py`), filtro `incluir_inactivos`.
- **Idempotencia del ajuste** (`tests/test_idempotencia_ajuste.py`): misma
  clave no descuenta dos veces, clave reutilizada → 422, un 409 no consume la
  clave, consulta `GET /ajustes/{clave}`, y dos pedidos simultáneos con la misma
  clave con hilos reales (se descuenta una sola vez).
- **Integración con movimientos** (`tests/test_integracion_movimientos.py`):
  `DELETE` consulta de verdad a Movimientos (baja lógica / borrado físico), falla
  cerrada con 503 si no responde, reenvía el token, traducción de errores del
  cliente HTTP, y la revocación de tokens consultada a `auth` en modo local.
- **Concurrencia** (`tests/test_concurrencia_stock.py`): reproduce la
  sobreventa con un ajuste no atómico y verifica que el ajuste atómico la
  previene.
- **Autenticación** (`tests/test_autenticacion.py`): 401 sin token, 401
  con token inválido, 403 con rol insuficiente, y verificación de que
  cada endpoint respeta el rol mínimo.
- **Datos de prueba** (`tests/test_seed_productos.py`): generación de
  lotes, límites de cantidad (1-200), y el flag `HABILITAR_SEED_ENDPOINT`.
- **Integración** (`tests/test_integracion.py`): flujos completos
  encadenados (crear → editar → listar → eliminar) y healthcheck.

- **Batería de carga y blindaje** (`tests/test_bateria_minima.py`, 18 tests):
  un test unitario de la regla de negocio, uno de integración (201 con el
  schema JSON) y uno de datos corruptos (400); la **carga concurrente** (20
  `PATCH /ajustar-stock` simultáneos sobre un producto con stock 20: las 20
  salen bien, el stock termina en 0, e imprime latencia media y tasa de
  éxito); la **sanitización** (10 payloads maliciosos en nombre, marca,
  categoría y precio devuelven 400 y no se guardan; la edición también los
  rechaza; un control confirma que nombres reales como `Autito 1/64 (Hot
  Wheels®)` se aceptan); y los **headers de seguridad** en respuestas 200,
  201, 400, 404 y 500.

Cada test corre contra una base SQLite aislada (no comparte estado entre
tests ni toca la base real del contenedor): en memoria, salvo el test de
carga, que usa un archivo temporal porque necesita varias conexiones a la vez.
La autenticación se simula con overrides de dependencias (ver
`tests/conftest.py`), salvo los tests específicos de auth, que usan el
mecanismo real con JWT firmados.