"""
Circuit breaker y reintentos del cliente HTTP hacia Productos (sin red: httpx.get/patch simulados).

Los demás tests reemplazan por completo las funciones del cliente; estos prueban el cliente REAL
(la lógica de resiliencia que está alrededor de httpx).
"""
import httpx
import pytest

from app.clients import productos_client as pc
from app.core.observabilidad import Registro
from app.core.resiliencia import ABIERTO, CERRADO, CircuitBreaker


class Reloj:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


@pytest.fixture()
def entorno(monkeypatch):
    reloj = Reloj()
    breaker = CircuitBreaker("productos", umbral_fallos=3, espera_segundos=10, reloj=reloj, registro=Registro())
    monkeypatch.setattr(pc, "_BREAKER", breaker)
    monkeypatch.setattr(pc, "REINTENTOS", 1)
    monkeypatch.setattr(pc, "REINTENTO_ESPERA_SEGUNDOS", 0)
    llamadas = []
    return reloj, breaker, llamadas


def _respuesta(estado, cuerpo=None):
    return httpx.Response(estado, json=cuerpo if cuerpo is not None else {})


def test_un_404_o_409_son_respuestas_de_negocio_y_no_abren_el_circuito(entorno, monkeypatch):
    _, breaker, _ = entorno
    monkeypatch.setattr(pc.httpx, "patch", lambda *a, **k: _respuesta(409))
    for _ in range(10):
        with pytest.raises(pc.ProductosClientError) as e:
            pc.ajustar_stock(1, -1, "tok", clave="k")
        assert e.value.status_code == 409
    assert breaker.estado == CERRADO


def test_los_fallos_de_conexion_abren_el_circuito_y_despues_se_rechaza_sin_llamar_a_la_red(entorno, monkeypatch):
    _, breaker, llamadas = entorno

    def caido(*a, **k):
        llamadas.append(1)
        raise httpx.ConnectError("sin conexión")

    monkeypatch.setattr(pc.httpx, "get", caido)
    for _ in range(3):  # umbral = 3 fallos lógicos
        with pytest.raises(pc.ProductosClientError) as e:
            pc.obtener_producto(1, "tok")
        assert e.value.status_code == 503
    assert breaker.estado == ABIERTO
    antes = len(llamadas)
    with pytest.raises(pc.ProductosClientError) as e:
        pc.obtener_producto(1, "tok")
    assert e.value.status_code == 503 and "pausaron" in e.value.mensaje
    assert len(llamadas) == antes, "con el circuito abierto no debe tocar la red"


def test_una_lectura_se_reintenta_una_vez_ante_un_fallo_de_transporte(entorno, monkeypatch):
    _, breaker, llamadas = entorno

    def inestable(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise httpx.ReadTimeout("lento")
        return _respuesta(200, {"id_producto": 1})

    monkeypatch.setattr(pc.httpx, "get", inestable)
    assert pc.obtener_producto(1, "tok") == {"id_producto": 1}
    assert len(llamadas) == 2 and breaker.estado == CERRADO


def test_la_escritura_se_reintenta_solo_si_no_se_pudo_conectar(entorno, monkeypatch):
    _, _, llamadas = entorno

    def sin_conexion(*a, **k):
        llamadas.append(1)
        raise httpx.ConnectError("no conecta")

    monkeypatch.setattr(pc.httpx, "patch", sin_conexion)
    with pytest.raises(pc.ProductosClientError):
        pc.ajustar_stock(1, -1, "tok", clave="k")
    assert len(llamadas) == 2  # el pedido nunca llegó: reintentar es seguro

    llamadas.clear()

    def timeout_de_lectura(*a, **k):
        llamadas.append(1)
        raise httpx.ReadTimeout("el servidor tardó")

    monkeypatch.setattr(pc.httpx, "patch", timeout_de_lectura)
    with pytest.raises(pc.ProductosClientError):
        pc.ajustar_stock(1, -1, "tok", clave="k")
    assert len(llamadas) == 1  # pudo haberse aplicado: NO se repite a ciegas (lo resuelve la saga)


def test_un_5xx_cuenta_como_fallo_del_servicio(entorno, monkeypatch):
    _, breaker, _ = entorno
    monkeypatch.setattr(pc.httpx, "get", lambda *a, **k: _respuesta(503))
    for _ in range(3):
        with pytest.raises(pc.ProductosClientError):
            pc.obtener_producto(1, "tok")
    assert breaker.estado == ABIERTO


def test_el_circuito_se_recupera_solo_cuando_el_servicio_vuelve(entorno, monkeypatch):
    reloj, breaker, _ = entorno
    estado = {"vivo": False}

    def servicio(*a, **k):
        if not estado["vivo"]:
            raise httpx.ConnectError("caído")
        return _respuesta(200, {"id_producto": 1})

    monkeypatch.setattr(pc.httpx, "get", servicio)
    for _ in range(3):
        with pytest.raises(pc.ProductosClientError):
            pc.obtener_producto(1, "tok")
    assert breaker.estado == ABIERTO

    estado["vivo"] = True
    reloj.t += 11  # pasó la espera: se deja pasar una llamada de prueba
    assert pc.obtener_producto(1, "tok") == {"id_producto": 1}
    assert breaker.estado == CERRADO


def test_el_id_de_correlacion_se_envia_a_productos(entorno, monkeypatch):
    from app.core import observabilidad
    visto = {}

    def capturar(url, headers=None, timeout=None):
        visto.update(headers)
        return _respuesta(200, {"id_producto": 1})

    monkeypatch.setattr(pc.httpx, "get", capturar)
    token = observabilidad.fijar_request_id("correlacion-12345678")
    try:
        pc.obtener_producto(1, "tok")
    finally:
        observabilidad.restablecer_request_id(token)
    assert visto["X-Request-ID"] == "correlacion-12345678" and visto["Authorization"] == "Bearer tok"
