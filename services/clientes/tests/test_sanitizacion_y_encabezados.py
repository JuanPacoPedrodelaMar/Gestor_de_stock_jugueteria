"""
Sanitización de los campos de texto de un cliente (documento, email, teléfono)
y encabezados de seguridad. Mismo criterio que la batería de Productos y
Movimientos: un valor peligroso devuelve 400 (nunca 500) y no se guarda nada.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

CLIENTES = "/api/v1/clientes"

CARGAS_MALICIOSAS = [
    ("xss_en_documento", {"documento": "<script>alert(1)</script>"}),
    ("sqli_corta_en_documento", {"documento": "' OR '1'='1"}),
    ("sqli_drop_table", {"documento": "1; DROP TABLE clientes;--"}),
    ("comilla_y_comentario", {"documento": "123'--"}),
    ("path_traversal", {"documento": "../../etc/passwd"}),
    ("byte_nulo", {"documento": "1234\u0000"}),
    ("salto_de_linea_en_el_medio", {"documento": "1234\n5678"}),
    ("xss_en_email", {"email": "<img src=x onerror=alert(1)>@x.com"}),
    ("sqli_en_email", {"email": "a'; DROP TABLE clientes;--@x.com"}),
    ("email_con_espacios", {"email": "a b@x.com"}),
    ("sqli_en_telefono", {"telefono": "1; DROP TABLE clientes;--"}),
    ("letras_en_telefono", {"telefono": "llamame"}),
]


@pytest.mark.parametrize("malicioso", [c for _, c in CARGAS_MALICIOSAS], ids=[n for n, _ in CARGAS_MALICIOSAS])
def test_sanitizacion_devuelve_400_y_no_500(client, SessionLocal, malicioso):
    from app.models.cliente import Cliente

    valido = {"documento": "30123456", "email": "ana@ejemplo.com", "telefono": "+54 376 4123456"}

    respuesta = client.post(CLIENTES, json={**valido, **malicioso})

    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["error"] is True
    db = SessionLocal()
    try:
        assert db.query(Cliente).count() == 0
    finally:
        db.close()


def test_un_salto_de_linea_en_los_extremos_se_recorta_y_no_se_guarda(client, SessionLocal):
    """Los espacios/saltos de línea de los extremos se limpian; lo guardado queda sin ellos."""
    from app.models.cliente import Cliente

    respuesta = client.post(CLIENTES, json={"documento": "  12345678\n", "email": " ana@ejemplo.com\n"})

    assert respuesta.status_code == 201
    db = SessionLocal()
    try:
        guardado = db.query(Cliente).one()
        assert (guardado.documento, guardado.email) == ("12345678", "ana@ejemplo.com")
    finally:
        db.close()


def test_no_rechaza_datos_validos(client):
    """Control: el filtro no puede ser tan estricto que rechace datos reales."""
    respuesta = client.post(
        CLIENTES,
        json={"documento": "AB-123.456/7", "email": "ana.perez+tienda@ejemplo.com.ar", "telefono": "(0376) 412-3456"},
    )

    assert respuesta.status_code == 201


ENCABEZADOS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "content-security-policy": "frame-ancestors 'none'",
}


def _verificar_encabezados(respuesta, contexto):
    for nombre, valor in ENCABEZADOS.items():
        assert respuesta.headers.get(nombre) == valor, f"{contexto}: falta {nombre}"


def test_encabezados_de_seguridad_en_todas_las_respuestas(client):
    _verificar_encabezados(client.get("/health"), "200 /health")
    _verificar_encabezados(client.get(CLIENTES), "200 listado")
    _verificar_encabezados(client.post(CLIENTES, json={"documento": "1234567"}), "201 creación")
    _verificar_encabezados(client.get(f"{CLIENTES}/9999"), "404")
    _verificar_encabezados(client.post(CLIENTES, json={}), "400 validación")


def test_encabezados_de_seguridad_tambien_en_el_error_500(client):
    with patch("app.services.cliente_service.buscar_clientes", side_effect=RuntimeError("falla simulada")):
        with TestClient(app, raise_server_exceptions=False) as cliente_500:
            respuesta = cliente_500.get(CLIENTES)

    assert respuesta.status_code == 500
    assert respuesta.json() == {"error": True, "mensaje": "Error interno del servidor."}
    _verificar_encabezados(respuesta, "500")


def test_health_y_raiz_responden_sin_autenticacion(client_sin_auth):
    assert client_sin_auth.get("/health").json() == {"status": "ok", "service": "clientes"}
    assert client_sin_auth.get("/").status_code == 200
