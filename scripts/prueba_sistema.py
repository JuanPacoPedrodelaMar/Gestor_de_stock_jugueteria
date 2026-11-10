#!/usr/bin/env python3
"""
Prueba de SISTEMA de punta a punta contra el stack levantado (docker compose o el despliegue).

Solo usa la biblioteca estándar. Verifica los recorridos críticos del AE4:

  R1  login -> producto -> venta -> stock -> evento -> ALERTA en el worker
  R3  concurrencia: 10 ventas simultáneas sobre stock 1 -> exactamente 1 confirmada, stock final 0
      idempotencia: el mismo Idempotency-Key dos veces NO duplica el movimiento ni el stock
  --  seguridad (401 sin token, encabezados), correlación (X-Request-ID) y métricas (/metrics)
  R2  (opcional, --caida) falla parcial: se detiene Productos, la venta queda PENDIENTE, el circuit
      breaker se abre, y al volver Productos el reintento con la MISMA clave descuenta el stock UNA vez.

Uso:
    python scripts/prueba_sistema.py                 # R1 + R3 + seguridad + métricas
    python scripts/prueba_sistema.py --caida         # además R2 (necesita "docker compose" y permisos)
Variables (todas opcionales): AUTH_URL PRODUCTOS_URL MOVIMIENTOS_URL CLIENTES_URL WORKER_URL
    GATEWAY_URL (si se define, las 4 APIs se piden a ese origen; /metrics y worker no) ,
    ADMIN_EMAIL ADMIN_PASSWORD COMPOSE_CMD (default "docker compose")
Código de salida: 0 si todo pasó, 1 si algo falló.
"""
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

GATEWAY = os.getenv("GATEWAY_URL", "").rstrip("/")
AUTH = GATEWAY or os.getenv("AUTH_URL", "http://localhost:8001")
PRODUCTOS = GATEWAY or os.getenv("PRODUCTOS_URL", "http://localhost:8000")
MOVIMIENTOS = GATEWAY or os.getenv("MOVIMIENTOS_URL", "http://localhost:8002")
CLIENTES = GATEWAY or os.getenv("CLIENTES_URL", "http://localhost:8004")
WORKER = os.getenv("WORKER_URL", "http://localhost:8003")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@test.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin12345")
COMPOSE = os.getenv("COMPOSE_CMD", "docker compose").split()

resultados = []


def paso(nombre):
    def deco(f):
        def envoltura(*a, **k):
            try:
                valor = f(*a, **k)
                resultados.append((nombre, True, ""))
                print(f"  OK     {nombre}")
                return valor
            except AssertionError as e:
                resultados.append((nombre, False, str(e)))
                print(f"  FALLA  {nombre}: {e}")
            except Exception as e:  # noqa: BLE001 - se informa cualquier error inesperado
                resultados.append((nombre, False, f"{type(e).__name__}: {e}"))
                print(f"  FALLA  {nombre}: {type(e).__name__}: {e}")
        return envoltura
    return deco


def http(metodo, url, cuerpo=None, token=None, cabeceras=None, timeout=15):
    """Devuelve (status, headers, cuerpo_texto). No levanta por códigos 4xx/5xx."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo)
    if datos is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (cabeceras or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()
    except (urllib.error.URLError, OSError) as e:  # sin conexión / timeout: status 0
        return 0, {}, str(e)


def js(texto):
    try:
        return json.loads(texto)
    except ValueError:
        return {}


def esperar(condicion, segundos=30, cada=1.0):
    limite = time.time() + segundos
    while time.time() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(cada)
    return None


def metrica(texto, patron):
    """Suma los valores de las líneas de /metrics que empiezan con `patron`."""
    total, hallada = 0.0, False
    for linea in texto.splitlines():
        if linea.startswith(patron):
            total += float(linea.rsplit(" ", 1)[1]); hallada = True
    return total if hallada else None


def stock_de(token, id_producto):
    return js(http("GET", f"{PRODUCTOS}/api/v1/productos/{id_producto}", token=token)[2]).get("stock_actual")


def venta(token, id_producto, cantidad=1, clave=None, categoria="venta"):
    return http("POST", f"{MOVIMIENTOS}/api/v1/movimientos",
                {"categoria_movimiento": categoria, "cantidad_movida": cantidad, "id_producto": id_producto},
                token=token, cabeceras={"Idempotency-Key": clave or uuid.uuid4().hex})


# ----------------------------------------------------------------------------------------------

@paso("Los 5 servicios responden /health")
def salud():
    if GATEWAY:  # tras el gateway solo es público /healthz (el /health de cada servicio es interno)
        assert http("GET", f"{GATEWAY}/healthz")[0] == 200, "el gateway no responde /healthz"
        return
    for nombre, url in (("auth", AUTH), ("productos", PRODUCTOS), ("clientes", CLIENTES), ("movimientos", MOVIMIENTOS)):
        estado = http("GET", f"{url}/health")[0]
        assert estado == 200, f"{nombre} /health -> {estado}"
    estado = http("GET", f"{WORKER}/health")[0]
    assert estado == 200, f"worker /health -> {estado}"


@paso("Login del administrador devuelve access y refresh token")
def login():
    estado, _, cuerpo = http("POST", f"{AUTH}/api/v1/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert estado == 200, f"login -> {estado} {cuerpo[:120]} (¿HABILITAR_USUARIOS_PRUEBA=true?)"
    datos = js(cuerpo)
    assert datos.get("access_token") and datos.get("refresh_token")
    return datos["access_token"]


@paso("Sin token las APIs responden 401")
def sin_token():
    for url in (f"{PRODUCTOS}/api/v1/productos", f"{MOVIMIENTOS}/api/v1/movimientos", f"{CLIENTES}/api/v1/clientes"):
        assert http("GET", url)[0] == 401, url


@paso("Encabezados de seguridad presentes en auth y productos")
def encabezados():
    destinos = (f"{PRODUCTOS}/api/v1/productos", f"{AUTH}/api/v1/auth/login") if GATEWAY else (f"{AUTH}/health", f"{PRODUCTOS}/health")
    for url in destinos:
        h = http("GET", url)[1]
        assert h.get("X-Content-Type-Options") == "nosniff", f"{url}: falta nosniff"
        assert h.get("X-Frame-Options") == "DENY", f"{url}: falta X-Frame-Options"


@paso("X-Request-ID se respeta y se devuelve (correlación)")
def correlacion(token):
    rid = "prueba-" + uuid.uuid4().hex
    h = http("GET", f"{PRODUCTOS}/api/v1/productos", token=token, cabeceras={"X-Request-ID": rid})[1]
    if GATEWAY:  # nginx genera su propio ID en el borde: se comprueba que llegue uno, no que sea el enviado
        assert len(h.get("X-Request-ID") or "") >= 8, "el gateway no devolvió X-Request-ID"
    else:
        assert h.get("X-Request-ID") == rid, f"devolvió {h.get('X-Request-ID')}"


@paso("Se crea un producto con stock 1 y stock mínimo 5")
def crear_producto(token):
    nombre = f"Prueba sistema {uuid.uuid4().hex[:8]}"
    estado, _, cuerpo = http("POST", f"{PRODUCTOS}/api/v1/productos", {
        "nombre": nombre, "marca": "QA", "precio_venta": 1000, "stock_actual": 1, "stock_minimo": 5, "categoria": "Prueba"}, token=token)
    assert estado == 201, f"crear producto -> {estado} {cuerpo[:150]}"
    return js(cuerpo)["id_producto"]


@paso("R3 · 10 ventas simultáneas sobre stock 1: exactamente 1 confirmada, 9 rechazadas por stock, stock final 0")
def concurrencia(token, id_producto):
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        respuestas = list(pool.map(lambda _: venta(token, id_producto)[0], range(10)))
    confirmadas, rechazadas = respuestas.count(201), respuestas.count(409)
    assert confirmadas == 1 and rechazadas == 9, f"respuestas: {sorted(respuestas)}"
    assert stock_de(token, id_producto) == 0, "el stock final debe ser 0 (sin sobreventa)"


@paso("Idempotencia · el mismo Idempotency-Key dos veces devuelve el MISMO movimiento y suma el stock una sola vez")
def idempotencia(token, id_producto):
    clave = uuid.uuid4().hex
    e1, _, c1 = venta(token, id_producto, cantidad=3, clave=clave, categoria="ingreso")
    e2, _, c2 = venta(token, id_producto, cantidad=3, clave=clave, categoria="ingreso")
    assert e1 == 201 and e2 in (200, 201), f"estados {e1}/{e2}"
    assert js(c1)["id_movimiento"] == js(c2)["id_movimiento"], "devolvió movimientos distintos"
    assert stock_de(token, id_producto) == 3, "el ingreso se aplicó más de una vez"
    e3, _, _ = venta(token, id_producto, cantidad=5, clave=clave, categoria="ingreso")
    assert e3 == 422, f"reutilizar la clave con otro contenido debe dar 422, dio {e3}"


@paso("R1 · una venta que deja el stock bajo el mínimo genera una ALERTA en el worker")
def alerta(token, id_producto):
    antes = metrica(http("GET", f"{WORKER}/metrics")[2], 'worker_mensajes_total{resultado="alerta"}') or 0
    assert venta(token, id_producto, cantidad=1)[0] == 201  # 3 -> 2, y el mínimo es 5
    despues = esperar(lambda: (lambda v: v if v is not None and v > antes else None)(
        metrica(http("GET", f"{WORKER}/metrics")[2], 'worker_mensajes_total{resultado="alerta"}')), 30)
    assert despues, "el worker no registró la alerta en 30 s (¿RabbitMQ/outbox?)"


@paso("/metrics de movimientos y productos expone contadores, latencias y gauges de negocio")
def metricas():
    m = http("GET", f"{MOVIMIENTOS}/metrics")[2] if not GATEWAY else http("GET", os.getenv("MOVIMIENTOS_URL", "http://localhost:8002") + "/metrics")[2]
    assert "http_request_duration_seconds_bucket" in m
    assert metrica(m, "movimientos_registrados_total") >= 1
    assert metrica(m, "movimientos_pendientes") == 0, "no deben quedar movimientos pendientes"
    p = http("GET", (os.getenv("PRODUCTOS_URL", "http://localhost:8000")) + "/metrics")[2]
    assert "productos_stock_bajo" in p


# ---------------- R2: falla parcial (opcional) ------------------------------------------------

def compose(*args):
    return subprocess.run(COMPOSE + list(args), capture_output=True, text=True, timeout=120)


@paso("R2 · Productos caído: la venta falla con 503 y queda PENDIENTE; el circuit breaker se abre")
def r2_caida(token, id_producto):
    r = compose("stop", "productos")
    assert r.returncode == 0, r.stderr[:200]
    clave = uuid.uuid4().hex
    estado, _, cuerpo = venta(token, id_producto, clave=clave)
    assert estado == 503, f"con Productos caído se esperaba 503, dio {estado}: {cuerpo[:120]}"
    for _ in range(6):  # supera CB_UMBRAL_FALLOS (5) -> el circuito se abre y las siguientes fallan al instante
        venta(token, id_producto)
    m = http("GET", os.getenv("MOVIMIENTOS_URL", "http://localhost:8002") + "/metrics")[2]
    assert metrica(m, "movimientos_pendientes") >= 1, "debe haber un movimiento pendiente"
    assert metrica(m, 'circuit_breaker_estado{nombre="productos"}') == 2, "el circuito debería estar ABIERTO"
    return clave


@paso("R2 · Al volver Productos, el reintento con la MISMA clave descuenta el stock una sola vez")
def r2_recuperacion(token, id_producto, clave, stock_inicial):
    assert compose("start", "productos").returncode == 0
    assert esperar(lambda: http("GET", f"{PRODUCTOS}/health")[0] == 200, 60), "Productos no volvió"
    # el circuito está abierto hasta que pase CB_ESPERA_SEGUNDOS (15 s por defecto): se reintenta hasta lograrlo
    resp = esperar(lambda: (lambda r: r if r[0] in (200, 201) else None)(venta(token, id_producto, clave=clave)), 60, 3)
    assert resp, "el reintento no se pudo completar en 60 s"
    assert stock_de(token, id_producto) == stock_inicial - 1, "el stock debe bajar exactamente 1"


def main():
    print(f"Prueba de sistema contra: auth={AUTH} productos={PRODUCTOS} movimientos={MOVIMIENTOS} worker={WORKER}")
    # Se espera a que el stack termine de arrancar
    sano = (lambda: http("GET", f"{GATEWAY}/healthz")[0] == 200) if GATEWAY else \
        (lambda: all(http("GET", f"{u}/health")[0] == 200 for u in (AUTH, PRODUCTOS, MOVIMIENTOS, CLIENTES)))
    esperar(sano, 90, 2)
    salud()
    token = login()
    if not token:
        return fin()
    sin_token(); encabezados(); correlacion(token)
    pid = crear_producto(token)
    if pid:
        concurrencia(token, pid); idempotencia(token, pid)
        if GATEWAY:
            print("  (modo gateway: se omiten la alerta del worker y /metrics, que no son públicos)")
        else:
            alerta(token, pid); metricas()
        if "--caida" in sys.argv and not GATEWAY:
            stock = stock_de(token, pid)
            clave = r2_caida(token, pid)
            if clave:
                r2_recuperacion(token, pid, clave, stock)
    return fin()


def fin():
    fallos = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallos)}/{len(resultados)} pasos correctos")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
