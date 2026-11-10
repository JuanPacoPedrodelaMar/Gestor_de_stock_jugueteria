#!/usr/bin/env python3
"""
Verifica que las copias compartidas entre servicios sigan idénticas.

Cada servicio se construye con su propio contexto de Docker, así que el código común
(observabilidad) se copia en cada uno. Para que no se desincronicen, este script compara
todas las copias contra la de `productos`. Se ejecuta en CI. Código de salida 1 si hay diferencias.
"""
import hashlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "services"
GRUPOS = {
    "observabilidad.py": [
        "productos/app/core/observabilidad.py", "auth/app/core/observabilidad.py",
        "clientes/app/core/observabilidad.py", "movimientos/app/core/observabilidad.py",
        "worker-alertas/observabilidad.py",
    ],
    "test_observabilidad.py": [
        "productos/tests/test_observabilidad.py", "auth/tests/test_observabilidad.py",
        "clientes/tests/test_observabilidad.py", "movimientos/tests/test_observabilidad.py",
        "worker-alertas/tests/test_observabilidad.py",
    ],
}


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:12]


def main() -> int:
    malo = False
    for nombre, rutas in GRUPOS.items():
        referencia = huella(RAIZ / rutas[0])
        for r in rutas:
            h = huella(RAIZ / r)
            marca = "ok " if h == referencia else "DIFIERE"
            if h != referencia:
                malo = True
            print(f"  {marca} {h}  {r}")
    print("\nTodas las copias son idénticas." if not malo else "\nHAY COPIAS DESINCRONIZADAS: copiá productos/... sobre las demás.")
    return 1 if malo else 0


if __name__ == "__main__":
    sys.exit(main())
