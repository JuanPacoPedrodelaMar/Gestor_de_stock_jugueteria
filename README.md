# Gestor de Stock — Juguetería

Sistema de gestión de stock para una juguetería. Compuesto por cuatro APIs
REST (FastAPI: auth, productos, clientes y movimientos), un worker de
mensajería asíncrona y un panel de administración (HTML/JS) servido con nginx,
que además actúa de *gateway*.

> **Versión AE4** — ver [`docs/CAMBIOS_AE4.md`](./docs/CAMBIOS_AE4.md) para lo que se agregó:
> observabilidad (logs JSON, métricas, correlación), resiliencia (circuit breaker),
> CI/CD con registry y despliegue, endurecimiento de seguridad y accesibilidad.

## Estructura del repositorio

```
.
├── docker-compose.yml           # base con valores SEGUROS por defecto
├── docker-compose.override.yml  # desarrollo (se aplica solo con "docker compose up")
├── docker-compose.prod.yml      # producción: imágenes del registry, TLS, secretos obligatorios
├── .env.example · .env.prod.example
├── .github/workflows/     # tests.yml (tests + calidad) y ci-cd.yml (sistema → registry → despliegue)
├── observabilidad/        # Prometheus, reglas de alerta y dashboard de Grafana
├── despliegue/            # Caddyfile (TLS)
├── scripts/               # prueba_sistema.py · prueba_carga.py · verificar_copias.py · auditar_contraste.py
├── ejecutar_docker.ps1    # Windows: levanta TODO con Docker Compose (crea .env y el secreto si faltan)
├── ejecutar_local.ps1     # Windows, sin Docker: levanta el sistema o corre los tests (-Tests, -Bateria, -Todo)
├── docs/
│   ├── ARQUITECTURA.md    # Diagramas (servicios, capas, flujos, consistencia, concurrencia)
│   ├── adr/               # Decisiones de arquitectura (9 ADR)
│   ├── OBSERVABILIDAD.md  # Logs, métricas, correlación, alertas
│   ├── DESPLIEGUE.md      # Servidor, secretos, pipeline, rollback
│   └── EVIDENCIAS_AE4.md  # Criterio de la consigna → dónde está la evidencia y cómo reproducirla
├── services/
│   ├── auth/              # Login, JWT (access/refresh), roles (FastAPI + SQLite + Redis para la blacklist)
│   ├── productos/         # CRUD de Producto + ajuste atómico e idempotente de stock (FastAPI + SQLite)
│   ├── clientes/          # Clientes: ID propio, documento libre, email y teléfono opcionales, búsqueda (FastAPI + SQLite)
│   ├── movimientos/       # Historial + saga de registro + outbox de eventos (FastAPI + SQLite + RabbitMQ)
│   └── worker-alertas/    # Consumidor RabbitMQ: alertas de stock bajo (DLQ, idempotencia, GET /health)
└── frontend/              # Panel de administración, servido con nginx
```

Cada carpeta bajo `services/` es un servicio independiente, con su propio
Dockerfile, dependencias y (cuando corresponde) su propia base de datos.
Ver [`docs/ARQUITECTURA.md`](./docs/ARQUITECTURA.md) para diagramas de cómo
se relacionan.

## Requisitos

- Docker y Docker Compose (plugin `compose`: `docker compose`, no el binario
  viejo `docker-compose`).

No se necesita Python ni Node.js instalados localmente: todo corre dentro de
contenedores. En Windows, el script `ejecutar_docker.ps1` automatiza todo el
arranque (ver abajo).

Alternativa opcional en Windows, sin Docker: Python 3.10 a 3.13 (recomendado
3.12) y el script `ejecutar_local.ps1`. Ver "Desarrollo local sin Docker".

## Puesta en marcha desde cero

### Windows: un solo comando

Con Docker Desktop iniciado, desde PowerShell en la raíz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\ejecutar_docker.ps1
```

El script verifica que Docker y `docker compose` estén funcionando, crea el
`.env` a partir de `.env.example` si no existe, **genera una `AUTH_SECRET_KEY`
aleatoria si falta** (es obligatoria; ver "Variables de entorno"), ejecuta
`docker compose up -d --build`, espera a que los servicios respondan y abre el
frontend. Lee los puertos y las credenciales de `.env`, así que respeta los
cambios que hagas ahí. Si ya hay una `AUTH_SECRET_KEY`, no la toca (cambiarla
invalidaría las sesiones abiertas).

| Comando | Qué hace |
|---|---|
| `.\ejecutar_docker.ps1` | Construye y levanta todo |
| `.\ejecutar_docker.ps1 -NoAbrir` | Igual, sin abrir el navegador |
| `.\ejecutar_docker.ps1 -Detener` | Detiene el sistema; los datos se conservan |
| `.\ejecutar_docker.ps1 -BorrarDatos` | Detiene y **borra todos los datos** (pide escribir `SI`) |

Usa los mismos puertos que `ejecutar_local.ps1` (8000, 8001, 8002, 8004, 8080): si lo
tenías corriendo, cerrá esas ventanas antes.

### Manual (cualquier sistema)

```bash
cp .env.example .env
# Obligatorio: .env.example no incluye AUTH_SECRET_KEY y sin ella docker compose
# se detiene. Agregar una (por ejemplo, con openssl):
echo "AUTH_SECRET_KEY=$(openssl rand -hex 32)" >> .env
docker compose up --build
```

Esto levanta, en orden (según `depends_on` + healthchecks):

1. **`redis`** — blacklist de tokens JWT (logout).
2. **`rabbitmq`** — broker de mensajería. Panel de administración en
   `http://localhost:15672` (usuario/clave en `.env`, por defecto
   `admin` / `admin123`).
3. **`auth`** en `http://localhost:8001` — crea los usuarios de prueba y
   firma los JWT.
4. **`productos`** en `http://localhost:8000` — valida JWT localmente y
   expone el CRUD + ajuste atómico de stock.
5. **`clientes`** en `http://localhost:8004` — alta y búsqueda de clientes
   (ID propio; el documento puede repetirse; email y teléfono opcionales).
6. **`movimientos`** en `http://localhost:8002` — registra movimientos, valida
   el cliente contra `clientes`, ajusta stock en `productos` y publica eventos
   en RabbitMQ (vía outbox).
7. **`worker-alertas`** — consumidor asíncrono. Expone `GET /health` en
   `http://localhost:8003` (200 solo si está consumiendo) y se puede seguir
   también por logs (`docker compose logs -f worker-alertas`).
8. **`frontend`** en `http://localhost:8080` — con su `config.js` generado
   en runtime a partir de las variables de entorno.

Abrir `http://localhost:8080` en el navegador para usar el panel.

Documentación interactiva (Swagger) de cada API:

- Productos: `http://localhost:8000/docs`
- Movimientos: `http://localhost:8002/docs`
- Clientes: `http://localhost:8004/docs`
- Auth: `http://localhost:8001/docs`

Para bajar todo:

```bash
docker compose down
```

Para bajar todo y borrar también los datos persistidos (empezar 100% limpio):

```bash
docker compose down -v
```

## Usuarios y acceso rápido (entorno de pruebas)

Con `HABILITAR_USUARIOS_PRUEBA=true` (es el valor por defecto **solo en desarrollo**:
lo activa `docker-compose.override.yml`; el compose base y el de producción lo dejan en `false`),
`auth` crea una cuenta por rol al arrancar, y la pantalla de login del
frontend muestra un botón de **acceso rápido** por cada una. Se entra con el
**DNI** (el admin también con su email):

| Rol | DNI | Email | Contraseña | Permisos |
|---|---|---|---|---|
| `admin` | `20000001` | `admin@test.com` | `admin12345` | Todo: catálogo, movimientos, clientes, solicitudes de stock y usuarios. |
| `almacen` | `30000002` | `almacen@test.com` | `almacen123` | Carga productos, elimina los suyos durante 5 min y pide reposición de stock. |
| `ventas` | `30000003` | `ventas@test.com` | `ventas123` | Registra movimientos y busca/crea clientes. No toca el catálogo. |
| `mixto` | `30000004` | `mixto@test.com` | `mixto123` | Lo de almacén y lo de ventas. |

El detalle de qué puede hacer cada rol está en [`services/auth/README.md`](services/auth/README.md#roles).

Los valores salen de `PRUEBA_<ROL>_EMAIL`, `_DNI` y `_PASSWORD` en `.env`. Para
un entorno real, poner `HABILITAR_USUARIOS_PRUEBA=false`: no se crean los
usuarios y el frontend deja de recibir las credenciales. Opcionalmente se
puede definir un admin propio con `AUTH_ADMIN_EMAIL` / `AUTH_ADMIN_PASSWORD`
(se crea solo si la base de usuarios está vacía).

> Si cambiás las contraseñas de prueba en `.env` con una base ya creada, el
> usuario existente conserva la anterior: `docker compose down -v` para
> empezar de cero.

## Cómo probar el sistema de punta a punta

Guía rápida para verificar manualmente que el sistema completo funciona:
autenticación, CRUD de productos, registro de movimientos, ajuste atómico de
stock, alerta asíncrona de stock bajo y la recuperación ante fallas (outbox,
movimientos pendientes, borrado con `movimientos` caído).

### Preparación

En Windows alcanza con `.\ejecutar_docker.ps1` (ver "Puesta en marcha desde
cero"). A mano:

```bash
cp .env.example .env
echo "AUTH_SECRET_KEY=$(openssl rand -hex 32)" >> .env   # obligatoria
docker compose up -d --build
docker compose ps
```

Esperar a que todos los contenedores queden `healthy` (incluido
`worker-alertas`, que expone `GET /health` en el puerto 8003). Abrir:

- **Frontend:** http://localhost:8080
- **Panel de RabbitMQ:** http://localhost:15672 (usuario/clave en `.env`, por defecto `admin` / `admin123`)

### Paso 1 — Login

1. Abrir `http://localhost:8080`.
2. Usar el botón de **acceso rápido como Admin** (o loguearse con
   `admin@test.com` / `admin12345`).
3. Verificar que aparece el nombre y rol del usuario en el header.

### Paso 2 — Crear un producto con stock bajo

1. Ir a la pestaña **Inventario**.
2. Crear un producto con:
   - Nombre: `Producto de prueba`
   - Precio: `500`
   - Stock actual: `5`
   - Stock mínimo: `10` ← **más alto que el actual, para forzar la alerta**
3. Guardar. El producto aparece en la tabla con la etiqueta de stock bajo.

> Cada campo tiene un texto de ayuda y un tooltip ("?"), y la guía
> desplegable de la pantalla incluye un botón que completa el formulario con
> un ejemplo.

### Paso 3 — Registrar una venta

1. Ir a la pestaña **Movimientos**.
2. Producto: elegir "Producto de prueba" del dropdown (escribir "Produ" para
   filtrar).
3. Categoría: **Venta (descuenta)**.
4. Cantidad: `2`.
5. Click en **Registrar movimiento**.

Verificar:
- Aparece un mensaje verde "Movimiento registrado correctamente".
- El movimiento aparece en la tabla de abajo con la categoría marcada en rojo.
- Volver a la pestaña **Inventario**: el stock bajó de `5` a `3`.

### Paso 4 — Verificar la alerta asíncrona

El evento `movimiento.registrado` se guardó en el outbox de `movimientos` y
el relay lo publicó en RabbitMQ. El worker lo consumió y evaluó que el stock
quedó **en el mínimo o por debajo** (`stock_actual <= stock_minimo`). Verificar
en los logs:

```bash
docker compose logs worker-alertas | Select-Object -Last 5
```

Debería aparecer algo como:

```
[ALERTA STOCK BAJO] producto=Producto de prueba (id=1) stock_actual=3 stock_minimo=10 -- disparado por movimiento id_movimiento=1
```

También se puede ver el flujo en el panel de RabbitMQ:
- **Exchanges** → `stock.events` con publish count > 0.
- **Queues** → `alertas.stock.bajo` con acknowledges > 0.

Y la salud del worker:

```powershell
curl.exe http://localhost:8003/health
# {"status": "ok", "service": "worker-alertas", "ultimo_latido_hace_s": 3.1}
```

### Paso 5 — Probar la concurrencia (opcional, vía tests)

La concurrencia se verifica con los tests, que simulan ventas simultáneas
reales con hilos:

```powershell
cd services\productos
pip install -r requirements-dev.txt
python -m pytest tests/test_concurrencia_stock.py -v
```

(Los tests no están dentro de las imágenes de Docker de `productos`, por eso se
corren en la máquina local. `.\ejecutar_local.ps1 -Tests` prepara todo y corre la
suite completa.)

Esperado: los 2 tests pasan. Uno demuestra el problema (sobreventa con un
ajuste no atómico), el otro demuestra que el ajuste atómico la previene.

### Paso 6 — Probar la idempotencia (opcional)

Con el token obtenido del navegador (DevTools → Application → Local Storage
→ `jugueteria.sesion` → campo `access`), enviar dos veces el mismo request
con la misma `Idempotency-Key`:

```powershell
$TOKEN = "pegar-token-aca"

curl.exe -X POST http://localhost:8002/api/v1/movimientos `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $TOKEN" `
  -H "Idempotency-Key: prueba-manual-001" `
  -d '{\"categoria_movimiento\":\"venta\",\"cantidad_movida\":1,\"id_producto\":1}'
```

Ejecutar el mismo comando dos veces. Ambas respuestas deben traer el **mismo
`id_movimiento`**, y el stock del producto debe haber bajado **una sola
unidad** (no dos).

### Paso 7 — Probar errores y envíos duplicados (opcional, manual)

Verificaciones del panel (ver la sección "Interfaz del panel"):

1. **Error por campo:** en Inventario, escribir solo espacios en *Nombre* y
   guardar. El servidor responde 400 y el mensaje aparece **debajo del campo**.
2. **Doble clic:** en las herramientas del navegador (F12 → Red) elegir
   "Slow 3G" y hacer doble clic en *Guardar producto*. Se ve el spinner y se
   crea **un solo** producto.
3. **Sin conexión:** elegir "Offline" y guardar. Aparece un aviso de
   conexión y los datos siguen en el formulario.
4. **Stock insuficiente:** en Movimientos, registrar una venta con más
   unidades que el stock. El aviso bajo *Cantidad* indica cuántas hay
   disponibles.
5. **Caracteres no permitidos:** en Inventario, escribir `<script>` en
   *Nombre* y guardar. El servidor responde 400 y el mensaje "Contiene
   caracteres no permitidos" aparece **debajo del campo** (ver "Seguridad de
   las APIs").

### Paso 8 — Probar que el evento no se pierde con RabbitMQ caído (outbox)

```powershell
docker compose stop rabbitmq
```

1. Registrar una venta desde el frontend que deje el stock en el mínimo o por
   debajo. **Sigue respondiendo `201`**: el movimiento se confirma igual.
2. Ver el evento esperando en el outbox:

```powershell
docker compose exec movimientos python -c "import sqlite3; print(sqlite3.connect('/app/data/movimientos.db').execute('select id, publicado_en, intentos, ultimo_error from outbox_eventos').fetchall())"
```

Debería mostrar el evento con `publicado_en` en `None`, `intentos` creciendo y
el error de conexión en `ultimo_error`. El relay reintenta con backoff (de 5 s
hasta 60 s).

3. Levantar RabbitMQ de nuevo:

```powershell
docker compose start rabbitmq
```

Dentro de aproximadamente un minuto repetir la consulta: `publicado_en` ya
tiene fecha. El worker (que se cayó al perder la conexión y Docker reinició)
vuelve a consumir y en `docker compose logs worker-alertas` aparece la alerta.
El evento **no se perdió**.

### Paso 9 — Probar un movimiento pendiente y su recuperación

Con el `$TOKEN` del Paso 6, apagar `productos` y registrar una venta con una
`Idempotency-Key` nueva:

```powershell
docker compose stop productos

curl.exe -i -X POST http://localhost:8002/api/v1/movimientos `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $TOKEN" `
  -H "Idempotency-Key: prueba-pendiente-001" `
  -d '{\"categoria_movimiento\":\"venta\",\"cantidad_movida\":1,\"id_producto\":1}'
```

Responde **`503`** y el mensaje aclara que el movimiento *quedó pendiente de
confirmación*. Verlo en el historial (aparece con `"estado": "pendiente"`):

```powershell
curl.exe http://localhost:8002/api/v1/movimientos -H "Authorization: Bearer $TOKEN"
```

Levantar `productos`, esperar a que quede `healthy` (`docker compose ps`) y
**repetir exactamente el mismo comando** (misma `Idempotency-Key`):

```powershell
docker compose start productos
```

Ahora responde **`201`** con `"estado": "confirmado"` y el mismo
`id_movimiento`. Verificar en el panel que el stock del producto bajó **una
sola unidad**.

**Reconciliación (admin).** Si nadie reintenta, un admin puede resolver los
pendientes. Repetir el comando anterior con otra clave
(`prueba-pendiente-002`) con `productos` apagado, volver a levantarlo y, con
un token de **admin**:

```powershell
curl.exe -X POST "http://localhost:8002/api/v1/movimientos/reconciliar?antiguedad_minima_segundos=0" `
  -H "Authorization: Bearer $TOKEN"
```

Como esa venta nunca llegó a aplicarse en `productos`, responde
`{"revisados":1,"confirmados":0,"descartados":1,"sin_resolver":0}` y el
movimiento desaparece del historial. Reconciliar **nunca** vuelve a modificar
el stock. (Sin `antiguedad_minima_segundos=0` solo se revisan los pendientes de
más de 5 minutos.) Cualquier rol que no sea admin recibe `403`.

### Paso 10 — Probar el borrado de un producto con `movimientos` caído

Usar un producto de prueba (la baja es real). Con un token de **admin**:

```powershell
docker compose stop movimientos
curl.exe -i -X DELETE http://localhost:8000/api/v1/productos/1 -H "Authorization: Bearer $TOKEN"
```

Responde **`503`** y el mensaje aclara que no se eliminó nada: sin poder
consultar el historial, `productos` no se arriesga a borrar un producto que
tenga movimientos. Verificar con `GET /api/v1/productos/1` que sigue activo.
Con `docker compose start movimientos` (y esperando que quede `healthy`) repetir
el `DELETE`: si el producto tiene movimientos responde `200` con
`"activo": false` (baja lógica); si no, `204` (borrado físico).

### Paso 11 — Probar carga, sanitización y headers (opcional)

La batería de la actividad "Prueba de Carga y Blindaje de Endpoints" corre
sola, sin Docker ni servicios levantados (ver "Tests"):

```powershell
powershell -ExecutionPolicy Bypass -File .\ejecutar_local.ps1 -Bateria
```

Esperado: pasan los tests de `productos`, `movimientos` y `clientes`, y cada servicio
imprime una línea con el resultado de la prueba de carga, por ejemplo:

```
[CARGA] 20 peticiones concurrentes -> éxito: 100% (20/20) | latencia media: 120 ms | máxima: 240 ms
```

(Los milisegundos dependen de la máquina.) Con el sistema levantado, los
headers también se ven a mano:

```powershell
curl.exe -i http://localhost:8000/health
curl.exe -i http://localhost:8002/health
```

La respuesta incluye `x-content-type-options: nosniff`, `x-frame-options: DENY`
y `content-security-policy: frame-ancestors 'none'`.

### Resumen de lo que se prueba

| Paso | Qué se valida |
|---|---|
| 1 | Autenticación JWT + roles |
| 2 | CRUD de productos + validación de stock mínimo |
| 3 | Vertical completa: frontend → movimientos → productos → DB |
| 4 | Mensajería asíncrona: outbox → RabbitMQ → worker, y salud del worker (`/health`) |
| 5 | Concurrencia: ajuste atómico bajo ventas simultáneas |
| 6 | Idempotencia: reintento con la misma clave no duplica |
| 7 | Errores por campo, anti-duplicados y manejo de fallas de red en el panel |
| 8 | Outbox: con RabbitMQ caído el evento espera y se publica al volver |
| 9 | Saga: movimiento pendiente si `productos` cae, recuperación por reintento y reconciliación |
| 10 | Borrado de producto: consulta real a `movimientos`, falla cerrada si no responde |
| 11 | Carga concurrente (20 peticiones), rechazo 400 de caracteres maliciosos y headers de seguridad |

## Concurrencia en el ajuste de stock

### Problema

`POST /api/v1/movimientos` puede recibir múltiples requests concurrentes
sobre el mismo producto (por ejemplo, dos ventas simultáneas desde dos
cajas). Un ajuste implementado como "leer stock → validar en Python →
escribir nuevo valor" produce una **condición de carrera conocida como
_lost update_ o _read-modify-write_**: ambos requests leen el mismo stock
antes de que ninguno escriba, ambos pasan la validación "hay stock
suficiente", y ambos descuentan.

### Resultado incorrecto

Con `stock_actual = 1` y dos ventas simultáneas de 1 unidad cada una, un
ajuste no atómico produce:

- **2 ventas aceptadas** sobre un producto que solo tenía 1 unidad
  (sobreventa).
- El stock final no refleja las dos operaciones aceptadas: la segunda
  escritura pisa a la primera con el mismo valor calculado de forma
  independiente (el stock queda en 0, pero se "vendieron" 2 unidades).

El resultado es un sistema que reporta más ventas de las que el stock
permitía, sin que ninguna operación haya fallado.

### Mecanismo

El endpoint `PATCH /api/v1/productos/{id}/ajustar-stock` (en
`services/productos/app/services/producto_service.py`, función
`ajustar_stock_atomico`) evalúa la condición de stock **dentro de la propia
sentencia SQL**:

```sql
UPDATE productos
   SET stock_actual = stock_actual + :delta
 WHERE id_producto = :id
   AND stock_actual >= :delta_absoluto   -- solo cuando delta < 0
```

La base de datos resuelve la carrera atómicamente: si dos UPDATE intentan
matchear la misma fila, solo uno puede tener éxito. El otro devuelve
`rowcount == 0`, que se traduce a un **409 Conflict** en el endpoint. El
resultado es que nunca se acepta una venta sin stock suficiente, sin
importar el orden de llegada ni el paralelismo.

### Verificación

`services/productos/tests/test_concurrencia_stock.py` corre dos escenarios
con hilos reales (`threading.Thread` + `threading.Barrier` para forzar el
entrelazado):

- `test_ajuste_no_atomico_permite_sobreventa`: reproduce el problema
  (asserta que las 2 ventas se aceptan).
- `test_ajuste_atomico_previene_sobreventa`: prueba la solución (asserta
  que exactamente una venta se acepta, la otra se rechaza con `"sin_stock"`,
  y el stock queda consistente).

Se corren con:

```bash
docker compose exec productos pytest tests/test_concurrencia_stock.py -v
```

## Consistencia, idempotencia y mensajería asíncrona

### Registro de un movimiento: una saga en tres pasos

Registrar un movimiento toca **dos bases de datos de servicios distintos**
(stock en `productos`, historial en `movimientos`); no existe una
transacción que las abarque. Por eso `movimientos` usa una saga de
"intención primero" (ver `services/movimientos/app/services/movimiento_service.py`):

1. **Guarda la intención**: inserta el movimiento como `pendiente`, con una
   `operacion_id` propia. Si falla acá, todavía no pasó nada en `productos`.
2. **Ajusta el stock** en `productos` enviando esa `operacion_id` como
   `Idempotency-Key`. `productos` aplica el cambio **una sola vez por clave**
   (la clave se guarda en la misma transacción que el stock), así que este
   paso se puede repetir sin riesgo de descontar dos veces.
3. **Confirma**: en una única transacción local, el movimiento pasa a
   `confirmado` y se guarda su evento en el *outbox*.

Qué pasa si algo falla:

| Falla | Resultado |
|---|---|
| `productos` rechaza (404 producto inexistente, 409 sin stock) | El stock no se tocó: la intención se descarta. No queda nada. |
| `productos` no responde / respuesta perdida | No se sabe si el stock cambió. El movimiento queda `pendiente` y el cliente recibe 503 avisándolo. **Reintentar con la misma clave lo completa** (aplica ahora, o `productos` responde que ya estaba aplicado). |
| Falla el guardado final (el "segundo paso") | El stock ya cambió pero el movimiento sigue `pendiente`: el reintento lo confirma. No hace falta deshacer el stock: se avanza hasta terminar. |
| Nadie reintenta | Un admin puede llamar a `POST /api/v1/movimientos/reconciliar`: consulta a `productos` si cada pendiente llegó a aplicarse y lo **confirma** (si se aplicó) o lo **descarta** (si no). Reconciliar **nunca vuelve a tocar el stock**, así que no ejecuta por sorpresa algo que el usuario abandonó. |

El frontend marca los movimientos pendientes con una etiqueta en el historial.

### Idempotencia

`POST /api/v1/movimientos` acepta un header opcional `Idempotency-Key`. Si
el cliente reintenta la misma solicitud (por un timeout, un doble clic, un
problema de red), el servicio devuelve el mismo movimiento **sin volver a
ajustar stock** (si estaba pendiente, lo completa).

- **Es atómica**: la clave se guarda en la base de datos de `movimientos` con
  un índice único. Dos pedidos simultáneos con la misma clave no pueden crear
  dos movimientos: lo garantiza la base, no un "consultar y luego guardar".
- Reutilizar la clave con **otro contenido** devuelve `422`.
- **`productos` también la tiene**: `PATCH /ajustar-stock` acepta
  `Idempotency-Key` (opcional) y `GET /api/v1/productos/ajustes/{clave}`
  informa si una operación llegó a aplicarse. Un ajuste rechazado por falta de
  stock no consume la clave.
- Ya no depende de Redis (antes se guardaba allí con TTL de 24 h): si Redis
  está caído, la idempotencia sigue funcionando.

El **frontend** genera la clave (un UUID por intento de registro). Con un
timeout, un corte de red, un 5xx o un 401 y los datos sin cambios, el
reintento reutiliza la misma clave; con una respuesta definitiva o con datos
distintos se genera una nueva. `POST /api/v1/productos` no tiene idempotencia.

### Evento `movimiento.registrado` y outbox

Al **confirmar** un movimiento, `movimientos` guarda el evento
`movimiento.registrado` en la tabla `outbox_eventos`, **en la misma
transacción** que cambia el estado a `confirmado` (*transactional outbox*). Un
relay en segundo plano lo publica en el exchange `stock.events` (tipo
`topic`, durable) y recién cuando RabbitMQ lo **confirma** lo marca como
publicado. El evento es **autocontenido**: incluye un snapshot del producto
(`stock_actual`, `stock_minimo`, `nombre`) al momento del ajuste, para que los
consumidores no tengan que llamar a `productos` (que exige JWT de usuario, y
un worker asíncrono no tiene uno).

- Con **RabbitMQ caído**, el endpoint igual devuelve `201 Created` y **el
  evento no se pierde**: queda en el outbox y el relay reintenta con backoff
  (de 5 s hasta 60 s) hasta que el broker vuelva. Sobrevive incluso a un
  reinicio del servicio, porque está en la base de datos.
- Se publica con *publisher confirms* y `mandatory`: si no hay ninguna cola
  donde rutear el mensaje (por ejemplo, el worker todavía no declaró la suya),
  RabbitMQ lo devolvería y se descartaría en silencio; acá el evento queda
  pendiente hasta que exista un consumidor.
- La entrega es **at-least-once**: un evento puede publicarse más de una vez si
  el proceso cae entre publicar y marcarlo. El worker es idempotente por
  `id_movimiento`, así que un duplicado es inocuo.

Ver `services/movimientos/EVENTOS.md` para el catálogo completo del evento
(exchange, routing key, payload, garantías de entrega).

### Worker de alertas

`services/worker-alertas` consume el exchange `stock.events` y evalúa si el
stock resultante de un producto quedó **en el mínimo o por debajo**
(`stock_actual <= stock_minimo`, la misma regla que usa la tabla de
Inventario del frontend). Es
**idempotente por `id_movimiento`** (verifica una base SQLite local antes
de reprocesar) porque RabbitMQ garantiza entrega *at-least-once*: el mismo
mensaje puede llegar más de una vez.

Tiene **reintentos con backoff** y **Dead-Letter Queue**:

- Si el procesamiento falla, el mensaje se rechaza (`nack`) y RabbitMQ lo
  dead-letterea a `alertas.stock.bajo.retry` (TTL 5 s), que lo devuelve a
  la cola principal.
- Después de `MAX_REINTENTOS` (5 por defecto, contados a partir del header
  `x-death`), el mensaje se mueve a `alertas.stock.bajo.dlq` para
  inspección manual desde el panel de RabbitMQ.

Expone `GET /health` (puerto 8003): responde 200 solo si el worker está
conectado y consumiendo, con un latido reciente que ejecuta la propia
conexión de RabbitMQ (si el consumidor se traba, pasa a 503). Docker Compose
lo usa como healthcheck.

Ver `services/worker-alertas/README.md` para el detalle de la topología de
colas.

### Verificación de la mensajería

```bash
# Ver que el worker arrancó y está consumiendo
docker compose logs -f worker-alertas
curl http://localhost:8003/health      # {"status": "ok", ...}

# Ver los eventos del outbox (publicado_en vacío = todavía sin publicar)
docker compose exec movimientos python -c "import sqlite3; print(sqlite3.connect('/app/data/movimientos.db').execute('select id, publicado_en, intentos from outbox_eventos').fetchall())"

# Disparar una alerta: crear un producto con stock_minimo > stock_actual,
# registrar una venta desde el frontend, y mirar el log del worker:
# [ALERTA STOCK BAJO] producto=... stock_actual=2 stock_minimo=7 ...

# Panel de RabbitMQ
open http://localhost:15672   # usuario/clave en .env
```

## Seguridad de las APIs: validación de entrada y headers

`productos`, `movimientos` y `clientes` aplican dos controles, que cubre la batería de la
actividad "Prueba de Carga y Blindaje de Endpoints" (ver "Tests"):

### Validación de entrada

Vive en los schemas de Pydantic: un dato inválido se rechaza con `400` y el
formato de error del proyecto (`{"error": true, "mensaje": ..., "detalles": [...]}`)
antes de tocar la base de datos o llamar a otro servicio. Nunca debe terminar
en `500`.

| Servicio | Campos | Qué se rechaza |
|---|---|---|
| `productos` | `nombre`, `marca`, `categoria` | Los caracteres `<` `>` `;` `=` `{` `}` `\`, el acento grave y los caracteres de control (byte nulo, saltos de línea, tabulaciones). Se aceptan tildes, ñ y la puntuación habitual de un catálogo (`. , - ' & / ( ) + : % # ° ® ™ ! ?`). |
| `clientes` | `documento`, `email`, `telefono` | `documento`: solo letras, números, espacio, punto, guion y barra (hasta 30; **no** se valida como DNI argentino ni es único). `email` y `telefono` (opcionales): formato de email y de teléfono internacional. El empleado ya no es un campo: sale del token. |

- El filtro de `productos` es una **lista de caracteres prohibidos**, no una
  lista blanca: los nombres de un catálogo necesitan mucha variedad de
  caracteres. Es una capa adicional. La defensa principal contra la inyección
  SQL es que el acceso a datos usa SQLAlchemy con parámetros enlazados, y
  contra XSS que el panel escapa el HTML al dibujar las tablas.
- Se aplica solo a lo que **entra** (alta y edición), no a las respuestas: así
  un dato guardado antes de este control no rompe un `GET` con un `500`.
- Referencia de diseño: OWASP Top 10 (2013), A1 (Inyección) y A3 (XSS), que
  proponen las consultas parametrizadas y el escape de salida como defensa
  principal, y la validación de entrada como complemento.

### Headers de seguridad

Un middleware los agrega a **toda** respuesta de `productos`, `movimientos` y `clientes`,
errores incluidos (también el `500` inesperado, ver
[`docs/ARQUITECTURA.md`](./docs/ARQUITECTURA.md#seguridad-de-entrada-y-encabezados)).

| Header | Valor | Qué evita |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Sniffing: el navegador respeta el `Content-Type` declarado y no "adivina" el tipo del contenido. |
| `X-Frame-Options` | `DENY` | Clickjacking: ningún sitio puede mostrar la respuesta dentro de un iframe. |
| `Content-Security-Policy` | `frame-ancestors 'none'` | El mismo objetivo que `X-Frame-Options`, expresado con CSP; en los navegadores que lo soportan, lo reemplaza. |

`auth` y el frontend (nginx) todavía no definen estos headers.

## Interfaz del panel (frontend)

El panel (`frontend/index.html`, `app.js` y `movimientos.js`) incluye, en
Inventario y en Movimientos:

- **Errores de validación junto al campo:** los errores 400 del backend
  (`detalles`) se traducen a español y se muestran bajo el campo
  correspondiente, con borde rojo y `aria-invalid`. En Movimientos también se
  muestran junto al campo el producto no elegido, el stock insuficiente (con
  las unidades disponibles) y el producto inexistente.
- **Ayuda al usuario:** texto de ayuda con regla y ejemplo en cada campo,
  tooltip ("?") con la explicación de qué se ingresa, y una guía desplegable
  por pantalla con un botón que completa el formulario con un ejemplo.
- **Envíos seguros:** el botón se bloquea con un spinner mientras se procesa
  la petición y se ignoran envíos repetidos (doble clic, Enter). Las
  peticiones tienen un tiempo máximo de espera de 15 s y, ante fallas de red,
  los datos quedan en el formulario con un aviso claro. Al crear un producto,
  si no hay respuesta, el aviso pide revisar el inventario antes de
  reintentar.
- **Accesibilidad básica:** `lang="es"`, labels asociados, tooltips operables
  con teclado (Escape los oculta) y mensajes anunciados con `aria-live`.

Ver el flujo completo en
[`docs/ARQUITECTURA.md`](./docs/ARQUITECTURA.md#frontend-validación-errores-y-envíos).

## Variables de entorno

Ver `.env.example` para el detalle de cada variable. `AUTH_SECRET_KEY`
(firma de los JWT) es **obligatoria** y hoy `.env.example` no la incluye:
agregar a mano una línea `AUTH_SECRET_KEY=<un valor largo y aleatorio>` en el
`.env`; sin ella `docker compose up` se detiene con un mensaje pidiéndola. El
archivo `.env` real **no se sube al repositorio** (ver `.gitignore`).

## Persistencia de datos

Cada servicio con estado tiene su propio volumen Docker, montado en
`/app/data` dentro del contenedor y **excluido del repositorio** (ver
`.gitignore`):

| Servicio | Volumen | Contenido |
|---|---|---|
| `auth` | `auth_data` | `auth.db` (usuarios, tokens de refresh) |
| `productos` | `productos_data` | `jugueteria.db` (catálogo + stock) |
| `clientes` | `clientes_data` | `clientes.db` (clientes: ID, documento, email, teléfono) |
| `movimientos` | `movimientos_data` | `movimientos.db` (histórico de movimientos, claves de idempotencia y outbox de eventos) |
| `worker-alertas` | `alertas_data` | `alertas_procesadas.db` (idempotencia local) |
| `redis` | `redis_data` | Blacklist de JWT (tokens revocados por logout) |
| `rabbitmq` | `rabbitmq_data` | Colas y mensajes persistentes |

### Migrar clientes de la versión anterior

Si ya habías cargado clientes cuando estaban dentro de `movimientos` (tabla
`clientes` de `movimientos.db`), hay que pasarlos al servicio `clientes`. Al
arrancar, `movimientos` ya copia el documento de cada cliente a sus movimientos
(el historial no se pierde), pero la ficha del cliente (email, teléfono) hay que
importarla, conservando los IDs para que los movimientos sigan apuntando bien:

```bash
docker compose down
# copiar movimientos.db del volumen movimientos_data a ./tmp y correr la importación
docker run --rm -v jugueteria_movimientos_data:/origen -v jugueteria_clientes_data:/destino \
  -v "$PWD/services/clientes:/app" -w /app python:3.12-slim sh -c \
  "pip install -q -r requirements.txt && python importar_desde_movimientos.py \
   --origen /origen/movimientos.db --destino /destino/clientes.db"
docker compose up -d
```

(El prefijo de los nombres de volumen depende del nombre de la carpeta del
proyecto: `docker volume ls` muestra los reales.) El script es idempotente y no
modifica `movimientos.db`. Sin Docker: `python importar_desde_movimientos.py
--origen services/movimientos/data/movimientos.db --destino services/clientes/data/clientes.db`
desde `services/clientes`. Si todavía no cargaste clientes, no hace falta nada.

Para precargar datos de ejemplo en `productos` una vez que el servicio está
corriendo:

```bash
docker compose exec productos python seed_data.py
```

## Desarrollo local sin Docker (opcional)

> Si tenés Docker, preferí `ejecutar_docker.ps1` (ver "Puesta en marcha desde
> cero"): levanta el sistema **completo**, con RabbitMQ y el worker. Este modo
> local es para cuando no se puede usar Docker.

**Windows, sin instalar Redis ni RabbitMQ.** Requiere Python 3.10 a 3.13
(recomendado 3.12; las dependencias fijadas no se instalan en 3.14 o
superior). Desde PowerShell, en la raíz del proyecto ya descomprimida:

```powershell
powershell -ExecutionPolicy Bypass -File .\ejecutar_local.ps1
```

El script crea un entorno virtual por servicio, instala las dependencias
(`requirements-local.txt`) y abre una ventana de PowerShell para cada uno:

| Componente | Puerto |
|---|---|
| `auth` | 8001 |
| `productos` | 8000 |
| `movimientos` | 8002 |
| `clientes` | 8004 |
| `frontend` (`python -m http.server`) | 8080 |

Los cinco puertos deben estar libres. Cada servicio usa un Redis en memoria
(`REDIS_URL=memory://`, vía `fakeredis`). Es solo para probar; limitaciones
de este modo:

- **No corren RabbitMQ ni `worker-alertas`.** Los movimientos se registran
  igual y su evento queda guardado en el outbox de `movimientos` (el relay que
  lo publicaría está desactivado en este modo para no llenar la ventana de
  errores de AMQP). No se procesan alertas de stock bajo.
- **El logout sí invalida el token en los cuatro servicios**, aunque cada uno
  tenga su propio Redis en memoria: `productos`, `clientes` y `movimientos` le preguntan a
  `auth` si el token fue revocado (`AUTH_SERVICE_URL`, y `auth` habilita
  `GET /api/v1/auth/tokens/{jti}/revocado` con `HABILITAR_CONSULTA_REVOCACION`;
  el script ya configura las tres variables). Es una llamada HTTP extra por
  request, solo en este modo; si `auth` no responde, se deja pasar el token
  (igual que cuando Redis no responde) y la firma y expiración se siguen
  validando. Con `docker compose` no se usa: el Redis compartido alcanza.
- El estado en memoria de `auth` (bloqueo por intentos de login, rotación de
  refresh tokens) se pierde al reiniciar el servicio.

Si el script falla:

- Ejecutarlo con **PowerShell**, no con Python (un `SyntaxError` sobre `@'`
  indica que se corrió con `python`).
- Si aparece `No module named pip`, `No pyvenv.cfg file` o
  `No module named uvicorn`, el entorno virtual quedó a medias (suele pasar
  por el antivirus o una versión de Python incompatible): borrar la carpeta
  `venv` de ese servicio y volver a ejecutar.
- Si el navegador no muestra los cambios del frontend, recargar con Ctrl+F5.

### Correr los tests con el mismo script

El script también prepara y corre los tests, sin Docker, Redis ni RabbitMQ y
sin activar ningún entorno virtual a mano. Usa el Python del entorno de cada
servicio, así que no importa si `pytest` está en el PATH ni desde qué carpeta
o unidad se lance:

| Opción | Qué hace |
|---|---|
| `-Tests` | Corre todos los tests (`auth`, `productos`, `movimientos` y `worker-alertas`) y muestra un resumen. No levanta el sistema. |
| `-Bateria` | Corre solo la batería de carga, sanitización y headers (`productos` y `movimientos`). |
| `-Todo` | Corre todos los tests y, si pasan, levanta el sistema. |

Por ejemplo: `powershell -ExecutionPolicy Bypass -File .\ejecutar_local.ps1 -Tests`.
Termina con un código de salida distinto de 0 si algún test falla. La suite de
`auth` usa el Redis en memoria (`REDIS_URL=memory://`), así que no necesita un
Redis real. La primera vez tarda más porque crea los entornos e instala las
dependencias de test.

Si el script falla:

- Ejecutarlo con **PowerShell**, no con Python (un `SyntaxError` sobre `@'`
  indica que se corrió con `python`).
- Si aparece `No module named pip`, `No pyvenv.cfg file` o
  `No module named uvicorn`, el entorno virtual quedó a medias (suele pasar
  por el antivirus o una versión de Python incompatible): borrar la carpeta
  `venv` de ese servicio y volver a ejecutar.
- Si el navegador no muestra los cambios del frontend, recargar con Ctrl+F5.

Alternativa manual: cada servicio se puede correr con `uvicorn app.main:app
--reload` en su propio virtualenv, ver el README de cada uno bajo
`services/`.

## Contrato de la API

Los contratos OpenAPI de cada servicio están exportados:

- `services/productos/openapi.json`
- `services/movimientos/openapi.json`
- `services/auth/openapi.json`

También están disponibles en vivo mientras los servicios corren:

- Productos: `http://localhost:8000/docs` / `/openapi.json`
- Movimientos: `http://localhost:8002/docs` / `/openapi.json`
- Auth: `http://localhost:8001/docs` / `/openapi.json`

## Tests

Tests por servicio (todos corren contra una base SQLite en memoria o
temporal, aislados entre sí, sin requerir dependencias externas):

En Windows, lo más simple es el script, que prepara los entornos y corre todo
(ver "Desarrollo local sin Docker"):

```powershell
powershell -ExecutionPolicy Bypass -File .\ejecutar_local.ps1 -Tests
```

A mano, dentro de la carpeta de cada servicio (`services/<servicio>`):

```bash
pip install -r requirements-dev.txt   # auth y productos; en movimientos, clientes y worker-alertas alcanza con requirements.txt
python -m pytest
```

Los tests **no están incluidos en las imágenes de Docker** de `auth`,
`productos`, `movimientos` y `clientes` (sus Dockerfile copian solo `app/`), por eso no se
corren con `docker compose exec`. `worker-alertas` sí los incluye en su imagen
(`docker compose exec worker-alertas pytest`).

Cobertura actual:

| Servicio | Tests | Qué cubre |
|---|---|---|
| `auth` | 48 | Login con DNI o email, roles (admin, almacén, ventas, mixto), refresh, logout, bloqueo por intentos, consulta de revocación (modo local), migración de esquema |
| `productos` | 165 | CRUD, validaciones, baja lógica, autenticación, **permisos por rol y ventana de 5 minutos para borrar** (`test_roles_y_borrado.py`), **solicitudes de stock** (`test_solicitudes_stock.py`), **concurrencia** (`test_concurrencia_stock.py`), **idempotencia del ajuste** (`test_idempotencia_ajuste.py`), **integración con movimientos** (`test_integracion_movimientos.py`) |
| `movimientos` | 111 | Delta por categoría, **saga y consistencia** (`test_saga_consistencia.py`), **outbox y relay** (`test_outbox.py`), publisher, migración de esquema, API HTTP, **roles, empleado tomado del token e integración con Clientes** (`test_roles_y_clientes.py`) |
| `clientes` | 69 | Alta (ID propio, documento repetible, email y teléfono opcionales), búsqueda, permisos por rol, sanitización, encabezados de seguridad, importación desde la versión anterior |
| `worker-alertas` | 19 | Idempotencia, regla de stock bajo (`<=`), conteo de reintentos, **healthcheck HTTP** |

Los tests de `auth` necesitan un Redis: por defecto esperan uno **real** en
`localhost:6379/15` (usan la base 15 y la vacían antes de cada test; nunca
correrlos contra el Redis del compose, base 0, porque se borraría la blacklist
de tokens). Con `REDIS_URL=memory://` usan `fakeredis` y no necesitan nada
instalado (es lo que hace el script). Ver `services/auth/tests/conftest.py`.

Además, el CI (`.github/workflows/tests.yml`) corre las cinco suites en cada
push, con un Redis real como servicio para `auth`.

Ver el detalle de qué cubre cada archivo en el README de cada servicio. El
frontend no tiene tests automáticos en el repositorio: se verifica
manualmente (ver Pasos 7 y 11 de "Cómo probar el sistema de punta a punta").

### Batería de carga y blindaje de endpoints

`tests/test_bateria_minima.py`, en `productos` y en `movimientos`, documenta la
actividad "Prueba de Carga y Blindaje de Endpoints en Vivo". Corre sin Docker
ni servicios levantados (Redis, RabbitMQ y los otros servicios se simulan) y
se lanza con `ejecutar_local.ps1 -Bateria`.

| Prueba | `productos` | `movimientos` |
|---|---|---|
| **Carga concurrente**: 20 peticiones simultáneas (una barrera de hilos las libera a la vez); mide latencia media y tasa de éxito | `PATCH /ajustar-stock` sobre un producto con stock 20: las 20 salen bien y el stock termina en 0 | `POST /movimientos`: se registran 20 movimientos distintos y se piden 20 ajustes a `productos` |
| **Sanitización**: caracteres maliciosos (XSS, SQL, plantillas, comandos, byte nulo, saltos de línea) devuelven `400`, nunca `500`, y no se guarda nada | 10 payloads sobre nombre, marca, categoría y precio, más la edición y un control con nombres reales | 7 payloads sobre la categoría, la cantidad, el producto y el cliente, más un control con datos válidos |
| **Headers de seguridad** en respuestas 200, 201, 400, 404 y 500 | Sí | Sí |

`clientes` tiene su propia sanitización y encabezados en `tests/test_sanitizacion_y_encabezados.py`
(12 payloads sobre documento, email y teléfono), que `ejecutar_local.ps1 -Bateria` también corre.

Alcance: la carga es en proceso (`TestClient` con 20 hilos) y con las
dependencias simuladas. Mide cada servicio por separado, no la cadena
completa ni el sistema desplegado. Con más peticiones simultáneas que
conexiones tiene el pool de la base aparece otro límite (ver "Limitaciones
conocidas").

## Calidad y decisiones de diseño

Correcciones de diseño relevantes (con justificación completa y tests que
las respaldan en el README de cada servicio):

- **El PUT de productos ya no puede pisar `stock_actual`.** El schema de
  actualización no incluye ese campo: el stock se modifica exclusivamente
  vía movimientos de inventario.
- **Baja lógica en vez de borrado físico** cuando un producto tiene
  movimientos asociados (se marca `activo=false`), para preservar la
  trazabilidad histórica. La decisión se toma consultando
  de verdad a `movimientos` (`GET /api/v1/productos/{id}/movimientos/cantidad`,
  con el token del admin). Si `movimientos` no responde, el borrado **falla
  cerrado** (503): no se supone "sin historial", porque eso llevaría a borrar
  físicamente un producto con movimientos.
- **Concurrencia resuelta con `UPDATE ... WHERE`** en lugar de locking
  optimista o pesimista: es la solución más simple que da la atomicidad
  necesaria sin agregar coordinación entre procesos. Ver sección
  "Concurrencia en el ajuste de stock".
- **Evento autocontenido** en lugar de "evento + callback": el worker no
  necesita llamar a `productos` para evaluar la alerta. Esto elimina la
  necesidad de autenticación de servicio a servicio y reduce el
  acoplamiento entre servicios.
- **Saga de "intención primero" con recuperación hacia adelante** en lugar de
  intentar deshacer (compensar) el stock: guardar el movimiento como
  `pendiente` antes de tocar `productos`, y hacer idempotente el ajuste, deja
  siempre un camino para terminar la operación sin necesitar una transacción
  distribuida. Ver "Consistencia, idempotencia y mensajería asíncrona".
- **Idempotencia en la base de datos** (índice único) en lugar de Redis con
  TTL: es atómica, sobrevive a un Redis caído y no caduca. El costo es una
  columna más por movimiento, que ya se guarda para siempre de todos modos.
- **Outbox transaccional** en lugar de publicar directo desde el request: es la
  forma de que un movimiento confirmado nunca pierda su evento aunque
  RabbitMQ esté caído, sin coordinar dos sistemas en una sola operación.
- **Reconciliar solo consulta, nunca reaplica**: una intención que el usuario
  abandonó no debe ejecutarse por sorpresa horas después.
- **Validación de entrada en los schemas, solo en la entrada.** Se rechaza
  antes de tocar la base y el formato del `400` es siempre el mismo. En
  `productos` el filtro vive en una base de schemas de entrada
  (`ProductoEntrada`) y no en `ProductoOut`: aplicado a la salida, un dato
  viejo con un carácter prohibido rompería el listado con un `500`.
- **Headers de seguridad por middleware, y explícitos en el `500`.** El
  `500` inesperado lo arma la capa más externa de Starlette, por fuera de los
  middlewares; por eso su handler recibe los headers de forma explícita (lo
  verifica un test).
- **El DNI se valida igual en el backend que en el panel**: solo dígitos,
  hasta 8. Antes el backend aceptaba cualquier texto de hasta 20 caracteres.
- **Regla de stock bajo `stock_actual <= stock_minimo`** en el frontend y en el
  worker: el mínimo es el punto de reposición, así que estar *en* el mínimo ya
  es "hay que reponer". Con mínimo 0, además, alerta cuando el producto se agota.

## Observabilidad

Logs JSON con ID de correlación, métricas Prometheus en `GET /metrics` de cada servicio, un
dashboard de Grafana y reglas de alerta. Guía completa en [`docs/OBSERVABILIDAD.md`](./docs/OBSERVABILIDAD.md).

```bash
docker compose --profile observabilidad up -d
# Grafana http://localhost:3000 (admin/admin) · Prometheus http://localhost:9090
```
Un `X-Request-ID` atraviesa nginx → APIs → evento de RabbitMQ → worker, así que una venta se sigue
de punta a punta con un solo ID (`docker compose logs ... | grep <id>`).

## Resiliencia

- **Circuit breaker** en las llamadas de `movimientos` a `productos` y `clientes`: tras 5 fallos
  seguidos rechaza al instante (503) durante 15 s y luego prueba con una sola llamada; así una
  caída de `productos` no arrastra a `movimientos` (ver [ADR 0005](./docs/adr/0005-resiliencia-circuit-breaker.md)).
- **Reintentos acotados** con backoff y jitter, solo donde es seguro (lecturas, y la escritura
  idempotente únicamente ante errores de conexión).
- La **saga** deja el movimiento `pendiente` y lo completa luego con la misma clave: sin doble descuento.
- **Prueba de falla** (recorrido R2): `python scripts/prueba_sistema.py --caida` detiene `productos`
  en medio de una venta, verifica el 503, el movimiento pendiente y el circuito abierto, y comprueba
  que al volver el reintento descuenta el stock **una sola vez**. También corre en el pipeline.
- **Límite honesto:** no hay réplicas (SQLite). La disponibilidad es degradación controlada +
  recuperación automática, no alta disponibilidad activa-activa ([ADR 0007](./docs/adr/0007-sqlite-wal-y-limite-de-ha.md)).

## Rendimiento: latencia media y p95

Se mide con `scripts/prueba_carga.py` (biblioteca estándar; concurrencia creciente; media, p50, p95, p99
y tasa de error). Para regenerar esta sección con números **reales** de tu equipo:

```bash
docker compose up -d --build
python scripts/prueba_carga.py --niveles 1,10,25,50 --duracion 15 --actualizar-readme README.md
```

<!-- CARGA:INICIO -->

_Medido el 2026-11-10 11:33 · Docker Compose local · Windows AMD64 · 15 s por nivel · conexiones persistentes · cliente en el mismo equipo/red que el sistema._

**Lectura: GET /api/v1/productos**

| Concurrencia | Pedidos | req/s | Media (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Máx (ms) | Errores |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4096 | 273.0 | 3.7 | 3.5 | 4.7 | 5.5 | 51.8 | 0 (0.0%) |
| 10 | 3565 | 237.2 | 42.1 | 40.9 | 55.5 | 76.8 | 95.2 | 0 (0.0%) |
| 25 | 3479 | 231.0 | 107.9 | 105.1 | 141.2 | 168.9 | 228.4 | 0 (0.0%) |
| 50 | 3454 | 228.4 | 217.9 | 210.3 | 266.4 | 332.6 | 468.9 | 0 (0.0%) |

**Escritura: POST /api/v1/movimientos (venta)**

| Concurrencia | Pedidos | req/s | Media (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Máx (ms) | Errores |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 216 | 14.4 | 69.7 | 69.0 | 76.0 | 85.4 | 185.3 | 0 (0.0%) |
| 10 | 736 | 48.6 | 204.6 | 166.5 | 411.3 | 863.4 | 1531.1 | 0 (0.0%) |
| 25 | 734 | 47.6 | 515.5 | 288.8 | 1610.2 | 2901.3 | 4594.4 | 0 (0.0%) |
| 50 | 788 | 50.2 | 970.3 | 561.9 | 3022.2 | 4371.4 | 5313.4 | 1 (0.13%) |

<!-- CARGA:FIN -->

**Cuello de botella analizado.** La escritura (`POST /api/v1/movimientos`) es la operación más cara:
una llamada síncrona a `productos`, varios commits y **un único escritor en SQLite**. Antes, con el
pool por defecto de SQLAlchemy (5 + 10) 150 ventas simultáneas agotaban las conexiones
(`QueuePool limit of size 5 overflow 10 reached`) y la mayoría no obtenía respuesta; con `pool_size=20`
y `max_overflow=60` se resolvieron todas. Mejora aplicada: pool 20 + 60 (`DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`) y SQLite en modo **WAL** con `busy_timeout` de 5 s (los lectores ya no bloquean al
escritor). Para cuantificar el antes/después, ejecutar la prueba con `DB_POOL_SIZE=5 DB_MAX_OVERFLOW=10`
y luego con los valores nuevos, y comparar el p95 y los errores en el nivel de 50 de concurrencia. El techo que
queda es el escritor único de SQLite: superarlo exige Postgres ([ADR 0007](./docs/adr/0007-sqlite-wal-y-limite-de-ha.md)).

## Despliegue y CI/CD

- `tests.yml`: tests de los 5 servicios + controles de calidad (copias idénticas, contraste WCAG,
  sintaxis JS, compose válidos) + `pip-audit`.
- `ci-cd.yml`: **prueba de sistema** con todos los contenedores → **publicación de imágenes versionadas
  en GHCR** → **despliegue por SSH** → **prueba de humo** → release.
- Producción: `docker-compose.prod.yml` (un solo punto de entrada HTTPS con Caddy, secretos obligatorios,
  sin usuarios de prueba). Paso a paso en [`docs/DESPLIEGUE.md`](./docs/DESPLIEGUE.md).

```bash
git tag v1.0.0-ae4 && git push origin v1.0.0-ae4     # dispara el pipeline completo
```

## Desarrollo vs. producción (Docker Compose)

| | Desarrollo (`docker compose up`) | Producción (`-f docker-compose.prod.yml`) |
|---|---|---|
| Archivos | `docker-compose.yml` + `docker-compose.override.yml` (automático) | `docker-compose.prod.yml` solo |
| Usuarios de prueba / seed | **sí** (override) | **no** |
| Puertos publicados | APIs, panel, RabbitMQ (5672/15672) | solo 80/443 (Caddy) |
| Imágenes | se construyen localmente | del registry (GHCR) |
| Secretos | `.env` | `.env.prod`, **obligatorios** |

El `docker-compose.yml` base ya no activa usuarios de prueba ni el endpoint de seed por defecto:
solo lo hace el override de desarrollo.

## Healthchecks

- `auth`: `GET /health` → `{"status": "ok", "service": "auth"}`
- `productos`: `GET /health` → `{"status": "ok", "service": "productos"}`
- `movimientos`: `GET /health` → `{"status": "ok", "service": "movimientos"}`
- `frontend`: `GET /healthz` → `200 ok` (nginx sirviendo contenido)
- `redis`: `redis-cli ping` → `PONG`
- `rabbitmq`: `rabbitmq-diagnostics ping`
- `worker-alertas`: `GET /health` (puerto 8003) → 200 `{"status": "ok", ...}` si
  está consumiendo con latido reciente; 503 `starting` mientras conecta a
  RabbitMQ o `unhealthy` si el consumidor dejó de latir. Como la imagen no trae
  `curl`, el healthcheck de Compose usa Python. También se puede seguir por
  logs: `docker compose logs -f worker-alertas`.

`docker compose ps` muestra el estado (`healthy` / `unhealthy`) de cada
servicio una vez que Docker ejecuta los healthchecks definidos en
`docker-compose.yml`.

## Limitaciones conocidas

Ver [`docs/ARQUITECTURA.md`](./docs/ARQUITECTURA.md#limitaciones-del-sistema-resumen)
para el detalle de cada una. Las más relevantes:

- **SQLite en lugar de Postgres**: adecuado para la etapa actual, limita la
  concurrencia real y la separación física de datos. Además hay un único
  relay de outbox por instancia de `movimientos` (no está pensado para
  varias réplicas escribiendo la misma base).
- **Los movimientos `pendiente` necesitan un reintento o una reconciliación
  manual.** No hay un proceso automático que los resuelva porque los servicios
  no tienen credenciales propias: un reintento usa el token del usuario y la
  reconciliación el de un admin (`POST /api/v1/movimientos/reconciliar`).
- **Ventana residual al reconciliar:** si un pendiente de más de 5 minutos se
  reconcilia (se descarta por no haberse aplicado) en el mismo instante en que
  el cliente lo reintenta, el stock podría cambiar sin que quede movimiento. El
  margen de antigüedad y que el reintento llegue justo ahí lo hacen muy
  improbable; cerrarlo del todo exigiría cancelar la clave en `productos`.
- **El borrado de un producto no es atómico con la consulta a `movimientos`**
  (son servicios distintos): un movimiento registrado en los milisegundos entre
  ambos pasos no se vería.
- **Eventos de movimientos reconciliados** llevan el stock *actual* del
  producto, no el de aquel instante (no se conserva).
- **Outbox sin consumidor:** si ninguna cola está enlazada al exchange (el
  worker nunca arrancó), los eventos se acumulan pendientes en lugar de
  perderse. Es lo deseado, pero la tabla `outbox_eventos` crece mientras tanto.
- **Modo local sin Docker:** sin RabbitMQ ni worker (los eventos quedan en el
  outbox), y la revocación de tokens suma una llamada HTTP a `auth` por request.
- Los headers de seguridad existen ahora en las 4 APIs y en nginx (con CSP). El filtro de caracteres
  de entrada existe en `productos`, `movimientos` y `clientes`.
- El filtro de caracteres de `productos` es una lista de caracteres
  prohibidos, no una lista blanca: es una capa adicional (ver "Seguridad de
  las APIs").
- **El pool de conexiones y el modo WAL de SQLite ya están aplicados** (ver «Rendimiento»); el techo de
  concurrencia de escritura sigue siendo el escritor único de SQLite.
- **Sin alta disponibilidad con réplicas** (SQLite; relay del outbox de instancia única): ver ADR 0007.
- **Sin trazas distribuidas con spans** (OpenTelemetry/Jaeger): la correlación por `X-Request-ID` cubre
  el seguimiento de un pedido, no la medición por tramo. Sin Alertmanager (las alertas se ven en Prometheus).
- **Producto dado de baja:** por API todavía acepta ajustes de stock (decisión de negocio abierta, ADR 0009).
- **BOLA:** las solicitudes de stock son por titular (cada usuario ve las suyas; el admin todas). El
  historial de movimientos es compartido entre roles de venta por diseño (un vendedor consulta el historial de un cliente).
- El frontend no tiene tests de interfaz automatizados: el pipeline valida la sintaxis del JS y el contraste de colores (WCAG AA); la navegación por teclado se verifica a mano.
