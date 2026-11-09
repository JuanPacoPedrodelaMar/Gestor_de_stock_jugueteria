# Servicio de Clientes

Servicio REST (FastAPI + SQLite) dueño de los **clientes** de la juguetería.
Cada cliente tiene un `id_cliente` que asigna el sistema; el `documento` (DNI,
pasaporte u otro) **no es único ni se valida como DNI argentino**, así que se
pueden cargar personas de otros países o documentos repetidos, y el ID es lo
que las distingue. `email` y `telefono` son opcionales.

Corre en el puerto **8004** (en Docker, el contenedor escucha en 8000 y se
publica como 8004). Swagger: `http://localhost:8004/docs`.

## Quién usa qué

| Rol | Acceso a clientes |
|---|---|
| `admin` | Crear, buscar y consultar |
| `ventas` | Crear, buscar y consultar |
| `mixto` | Crear, buscar y consultar |
| `almacen` | Ninguno (`403`) |

Se autentica igual que los demás servicios: JWT firmado por `auth`, validado
localmente con `AUTH_SECRET_KEY`, y revocación de tokens consultada a Redis (o a
`auth` en el modo local sin Docker).

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/clientes` | Crea un cliente (`documento` obligatorio; `email` y `telefono` opcionales). |
| GET | `/api/v1/clientes?q=texto&limite=N` | Busca por ID (exacto, con o sin `#`), documento, email o teléfono (contiene el texto, sin distinguir mayúsculas). Sin `q`, los últimos dados de alta. `limite` 1–200 (50 por defecto). |
| GET | `/api/v1/clientes/{id}` | Datos de un cliente (`404` si no existe). También lo consulta `movimientos`. |
| GET | `/health` | Healthcheck (sin auth). |

El **historial de movimientos** de un cliente no está acá: lo tiene `movimientos`
(`GET /api/v1/movimientos?id_cliente=N`), que es dueño de esos datos.

## Validación

Los campos de texto usan un juego de caracteres acotado (mismo criterio de
sanitización que `productos` y `movimientos`): un valor peligroso devuelve `400`
y no se guarda nada.

| Campo | Formato |
|---|---|
| `documento` | Obligatorio. Letras, números, espacio, punto, guion y barra; hasta 30. Espacios y saltos de línea de los extremos se recortan. |
| `email` | Opcional. Formato `usuario@dominio.tld`, hasta 120. Vacío = no enviado. |
| `telefono` | Opcional. Internacional: `+` opcional, dígitos, espacios, paréntesis y guiones (6 a 25 caracteres). Vacío = no enviado. |

## Cómo se relaciona con Movimientos

Un movimiento puede llevar un `id_cliente` (opcional). Antes de registrarlo,
`movimientos` consulta `GET /api/v1/clientes/{id}` (reenviando el token del
usuario) y guarda en el movimiento una **copia del documento**, de modo que el
historial se muestra sin depender de este servicio y refleja el dato como estaba
al momento de la venta.

- Si el cliente no existe: `404` y no se registra nada ni se toca el stock.
- Si este servicio no responde: `503` y tampoco se registra nada.
- Los movimientos **sin** cliente no dependen de este servicio: si está caído,
  esas ventas se siguen registrando.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `AUTH_SECRET_KEY` | — (obligatoria) | Misma clave con la que `auth` firma los JWT |
| `DATABASE_URL` | `sqlite:///./data/clientes.db` | Base propia del servicio |
| `REDIS_URL` | `redis://localhost:6379/0` | Blacklist de tokens revocados (`memory://` solo en desarrollo local) |
| `AUTH_SERVICE_URL` | — | Solo modo local sin Redis compartido: a quién preguntar si un token fue revocado |

## Migrar clientes de la versión anterior

Los clientes vivían antes en la base de `movimientos`. Para pasarlos conservando
los IDs (los movimientos ya registrados siguen apuntando al cliente correcto):

```bash
python importar_desde_movimientos.py --origen RUTA/movimientos.db --destino RUTA/clientes.db
```

Es idempotente (no duplica) y no modifica el origen. Para el caso con Docker, ver
el README de la raíz.

## Tests

```bash
cd services/clientes
AUTH_SECRET_KEY=cualquier-valor REDIS_URL=memory:// python -m pytest -q
```

No necesitan `auth`, Redis ni otros servicios: la autenticación se simula y la
base es un archivo SQLite temporal. Cubren permisos por rol, alta, búsqueda,
sanitización (`400`, nunca `500`), encabezados de seguridad y la importación.
