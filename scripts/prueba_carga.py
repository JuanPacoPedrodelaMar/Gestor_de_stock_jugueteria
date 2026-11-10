#!/usr/bin/env python3
"""
Prueba de CARGA: mide latencia media, p50, p95, p99 y tasa de error con concurrencia creciente.

Solo biblioteca estándar. Para cada nivel de concurrencia lanza N "usuarios" (hilos con conexión
persistente) que repiten pedidos durante `--duracion` segundos, y calcula las estadísticas.

Escenarios:
  lectura  GET  /api/v1/productos                 (Productos; consulta)
  venta    POST /api/v1/movimientos (venta de 1)  (Movimientos -> Productos -> outbox; escritura con saga)

Uso típico:
    python scripts/prueba_carga.py --niveles 1,10,25,50 --duracion 15
    python scripts/prueba_carga.py --salida resultados_carga.md --actualizar-readme README.md

Con --actualizar-readme reemplaza el texto entre <!-- CARGA:INICIO --> y <!-- CARGA:FIN --> del README
con la tabla medida (así el README siempre tiene números REALES, no inventados).
Un "error" es cualquier respuesta que no sea 2xx (o un fallo de conexión). El 409 de "sin stock" cuenta
como error: el producto de prueba se crea con 1.000.000 de unidades para que no ocurra.
"""
import argparse
import http.client
import json
import math
import os
import platform
import statistics
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime

MARCA_INICIO = "<!-- CARGA:INICIO -->"
MARCA_FIN = "<!-- CARGA:FIN -->"


def percentil(valores, p):
    """Percentil por método de rango más cercano (nearest-rank). `valores` en cualquier orden."""
    if not valores:
        return float("nan")
    ordenados = sorted(valores)
    k = max(1, math.ceil(p / 100 * len(ordenados)))
    return ordenados[k - 1]


def resumir(latencias_ms, errores, segundos):
    n = len(latencias_ms)
    return {
        "pedidos": n,
        "errores": errores,
        "tasa_error_pct": round(100 * errores / n, 2) if n else 0.0,
        "rps": round(n / segundos, 1) if segundos else 0.0,
        "media_ms": round(statistics.fmean(latencias_ms), 1) if n else float("nan"),
        "p50_ms": round(percentil(latencias_ms, 50), 1),
        "p95_ms": round(percentil(latencias_ms, 95), 1),
        "p99_ms": round(percentil(latencias_ms, 99), 1),
        "max_ms": round(max(latencias_ms), 1) if n else float("nan"),
    }


class Cliente:
    """Conexión HTTP persistente (keep-alive) a una URL base; se reconecta si se corta."""

    def __init__(self, base):
        u = urllib.parse.urlparse(base)
        self.host, self.puerto, self.https = u.hostname, u.port or (443 if u.scheme == "https" else 80), u.scheme == "https"
        self.conn = None

    def _abrir(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        self.conn = cls(self.host, self.puerto, timeout=30)

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None):
        datos = json.dumps(cuerpo) if cuerpo is not None else None
        h = {"Content-Type": "application/json", **(cabeceras or {})}
        for intento in (1, 2):
            try:
                if self.conn is None:
                    self._abrir()
                self.conn.request(metodo, ruta, body=datos, headers=h)
                r = self.conn.getresponse()
                cuerpo_resp = r.read()
                return r.status, cuerpo_resp
            except (http.client.HTTPException, OSError):
                self.conn = None
                if intento == 2:
                    return 0, b""


def medir_nivel(fabrica_pedido, concurrencia, duracion):
    latencias, errores = [], [0]
    cerrojo = threading.Lock()
    fin = time.time() + duracion

    def usuario():
        pedir = fabrica_pedido()
        propias, errs = [], 0
        while time.time() < fin:
            t0 = time.perf_counter()
            estado = pedir()
            propias.append((time.perf_counter() - t0) * 1000)
            if not (200 <= estado < 300):
                errs += 1
        with cerrojo:
            latencias.extend(propias)
            errores[0] += errs

    hilos = [threading.Thread(target=usuario) for _ in range(concurrencia)]
    inicio = time.time()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resumir(latencias, errores[0], time.time() - inicio)


def tabla_markdown(titulo, filas):
    lineas = [f"**{titulo}**", "",
              "| Concurrencia | Pedidos | req/s | Media (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Máx (ms) | Errores |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for nivel, r in filas:
        lineas.append(f"| {nivel} | {r['pedidos']} | {r['rps']} | {r['media_ms']} | {r['p50_ms']} | {r['p95_ms']} | "
                      f"{r['p99_ms']} | {r['max_ms']} | {r['errores']} ({r['tasa_error_pct']}%) |")
    return "\n".join(lineas)


def actualizar_readme(ruta, bloque):
    texto = open(ruta, encoding="utf-8").read()
    if MARCA_INICIO not in texto or MARCA_FIN not in texto:
        raise SystemExit(f"{ruta} no tiene las marcas {MARCA_INICIO} / {MARCA_FIN}")
    ini = texto.index(MARCA_INICIO) + len(MARCA_INICIO)
    fin = texto.index(MARCA_FIN)
    open(ruta, "w", encoding="utf-8").write(texto[:ini] + "\n\n" + bloque + "\n\n" + texto[fin:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auth-url", default=os.getenv("AUTH_URL", "http://localhost:8001"))
    ap.add_argument("--productos-url", default=os.getenv("PRODUCTOS_URL", "http://localhost:8000"))
    ap.add_argument("--movimientos-url", default=os.getenv("MOVIMIENTOS_URL", "http://localhost:8002"))
    ap.add_argument("--email", default=os.getenv("ADMIN_EMAIL", "admin@test.com"))
    ap.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", "admin12345"))
    ap.add_argument("--niveles", default="1,10,25,50", help="concurrencias separadas por coma")
    ap.add_argument("--duracion", type=float, default=15, help="segundos por nivel")
    ap.add_argument("--escenarios", default="lectura,venta")
    ap.add_argument("--entorno", default="Docker Compose local", help="texto que describe dónde se midió")
    ap.add_argument("--salida", help="guarda el informe en markdown")
    ap.add_argument("--actualizar-readme", metavar="README.md")
    a = ap.parse_args()
    niveles = [int(x) for x in a.niveles.split(",")]

    auth = Cliente(a.auth_url)
    estado, cuerpo = auth.pedir("POST", "/api/v1/auth/login", {"email": a.email, "password": a.password})
    if estado != 200:
        raise SystemExit(f"No se pudo iniciar sesión ({estado}). ¿Están levantados los servicios y los usuarios de prueba?")
    token = json.loads(cuerpo)["access_token"]
    cab = {"Authorization": f"Bearer {token}"}

    prod = Cliente(a.productos_url)
    estado, cuerpo = prod.pedir("POST", "/api/v1/productos", {
        "nombre": f"Carga {uuid.uuid4().hex[:8]}", "marca": "QA", "precio_venta": 1000,
        "stock_actual": 1_000_000, "stock_minimo": 1, "categoria": "Carga"}, cab)
    if estado != 201:
        raise SystemExit(f"No se pudo crear el producto de prueba ({estado}): {cuerpo[:200]!r}")
    id_producto = json.loads(cuerpo)["id_producto"]

    def lectura():
        c = Cliente(a.productos_url)
        return lambda: c.pedir("GET", "/api/v1/productos", None, cab)[0]

    def venta():
        c = Cliente(a.movimientos_url)
        return lambda: c.pedir("POST", "/api/v1/movimientos",
                               {"categoria_movimiento": "venta", "cantidad_movida": 1, "id_producto": id_producto},
                               {**cab, "Idempotency-Key": uuid.uuid4().hex})[0]

    escenarios = {"lectura": ("Lectura: GET /api/v1/productos", lectura), "venta": ("Escritura: POST /api/v1/movimientos (venta)", venta)}
    partes = [f"_Medido el {datetime.now():%Y-%m-%d %H:%M} · {a.entorno} · {platform.system()} {platform.machine()} · "
              f"{a.duracion:g} s por nivel · conexiones persistentes · cliente en el mismo equipo/red que el sistema._"]
    resultados = {}
    for clave in a.escenarios.split(","):
        titulo, fabrica = escenarios[clave.strip()]
        print(f"\n== {titulo}")
        filas = []
        for n in niveles:
            r = medir_nivel(fabrica, n, a.duracion)
            filas.append((n, r))
            print(f"  concurrencia {n:>3}: {r['rps']:>7} req/s  media {r['media_ms']:>7} ms  p95 {r['p95_ms']:>7} ms  "
                  f"p99 {r['p99_ms']:>7} ms  errores {r['errores']} ({r['tasa_error_pct']}%)")
        partes.append(tabla_markdown(titulo, filas))
        resultados[clave] = filas
    informe = "\n\n".join(partes)
    if a.salida:
        open(a.salida, "w", encoding="utf-8").write(informe + "\n")
        print(f"\nInforme guardado en {a.salida}")
    if a.actualizar_readme:
        actualizar_readme(a.actualizar_readme, informe)
        print(f"README actualizado: {a.actualizar_readme}")


if __name__ == "__main__":
    main()
