"""
Tests de la observabilidad: logs JSON, ID de correlación y métricas Prometheus.

El mismo archivo corre en los 5 servicios (en el worker el módulo está en la
raíz; en los demás, en app/core). Las pruebas del middleware necesitan FastAPI y
se saltean solas en el worker.
"""
import json
import logging

import pytest

try:
    from app.core import observabilidad as obs
except ImportError:  # worker-alertas: el módulo está en la raíz del servicio
    import observabilidad as obs


# ---------------------------------------------------------------------------
# ID de correlación
# ---------------------------------------------------------------------------

def test_un_request_id_valido_se_conserva():
    assert obs.request_id_entrante("abc12345-DEF_67.89") == "abc12345-DEF_67.89"


@pytest.mark.parametrize("malo", [None, "", "corto", "con espacio 12345678", "a" * 65, "linea\nnueva-12345", "<script>12345678"])
def test_un_request_id_invalido_se_reemplaza_por_uno_nuevo(malo):
    nuevo = obs.request_id_entrante(malo)
    assert nuevo != malo
    assert len(nuevo) == 32 and nuevo.isalnum()


def test_las_cabeceras_de_propagacion_llevan_el_id_del_contexto():
    assert obs.cabeceras_propagacion() == {}
    token = obs.fijar_request_id("id-de-prueba-123")
    try:
        assert obs.cabeceras_propagacion() == {"X-Request-ID": "id-de-prueba-123"}
    finally:
        obs.restablecer_request_id(token)
    assert obs.cabeceras_propagacion() == {}


# ---------------------------------------------------------------------------
# Logs estructurados
# ---------------------------------------------------------------------------

def _registro(mensaje="hola %s", args=("mundo",), **extra):
    r = logging.LogRecord("prueba", logging.INFO, __file__, 1, mensaje, args, None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_el_log_json_tiene_los_campos_basicos_y_es_json_valido():
    linea = obs.FormateadorJson("productos").format(_registro())
    datos = json.loads(linea)
    assert datos["servicio"] == "productos"
    assert datos["nivel"] == "INFO"
    assert datos["mensaje"] == "hola mundo"
    assert datos["ts"].endswith("+00:00")
    assert "request_id" not in datos  # sin contexto de pedido


def test_el_log_json_incluye_request_id_y_campos_extra():
    token = obs.fijar_request_id("id-de-prueba-123")
    try:
        datos = json.loads(obs.FormateadorJson("x").format(_registro(estado=201, metodo="POST")))
    finally:
        obs.restablecer_request_id(token)
    assert datos["request_id"] == "id-de-prueba-123"
    assert datos["estado"] == 201 and datos["metodo"] == "POST"


def test_el_log_json_incluye_la_excepcion():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        r = logging.LogRecord("p", logging.ERROR, __file__, 1, "falló", (), sys.exc_info())
    datos = json.loads(obs.FormateadorJson("x").format(r))
    assert "ValueError: boom" in datos["excepcion"]


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def test_un_contador_se_expone_con_help_type_y_etiquetas():
    reg = obs.Registro()
    reg.inc("pedidos_total", "Pedidos.", {"ruta": "/a", "estado": "200"})
    reg.inc("pedidos_total", "Pedidos.", {"estado": "200", "ruta": "/a"}, n=2)  # mismo conjunto, otro orden
    texto = reg.exponer()
    assert "# HELP pedidos_total Pedidos." in texto
    assert "# TYPE pedidos_total counter" in texto
    assert 'pedidos_total{estado="200",ruta="/a"} 3' in texto


def test_un_gauge_toma_el_ultimo_valor():
    reg = obs.Registro()
    reg.gauge("pendientes", "Pendientes.", 5)
    reg.gauge("pendientes", "Pendientes.", 2)
    assert "pendientes 2" in reg.exponer()


def test_el_histograma_es_acumulativo_y_cierra_con_inf_sum_y_count():
    reg = obs.Registro()
    for v in (0.00390625, 0.015625, 0.25, 20.0):
        reg.observar("latencia", "Latencia.", v, {"ruta": "/x"})
    texto = reg.exponer()
    assert 'latencia_bucket{ruta="/x",le="0.005"} 1' in texto
    assert 'latencia_bucket{ruta="/x",le="0.025"} 2' in texto
    assert 'latencia_bucket{ruta="/x",le="0.5"} 3' in texto
    assert 'latencia_bucket{ruta="/x",le="10"} 3' in texto
    assert 'latencia_bucket{ruta="/x",le="+Inf"} 4' in texto
    assert 'latencia_count{ruta="/x"} 4' in texto
    assert 'latencia_sum{ruta="/x"} 20.26953125' in texto


def test_los_valores_de_etiquetas_se_escapan():
    reg = obs.Registro()
    reg.inc("c", "C.", {"v": 'a"b\\c\nd'})
    assert 'c{v="a\\"b\\\\c\\nd"} 1' in reg.exponer()


def test_un_nombre_no_puede_cambiar_de_tipo():
    reg = obs.Registro()
    reg.inc("x", "X.")
    with pytest.raises(ValueError):
        reg.gauge("x", "X.", 1)


def test_las_funciones_al_exponer_actualizan_gauges_y_un_error_no_rompe_todo():
    reg = obs.Registro()
    reg.al_exponer(lambda r: r.gauge("vivo", "Vivo.", 7))
    reg.al_exponer(lambda r: 1 / 0)
    assert "vivo 7" in reg.exponer()


# ---------------------------------------------------------------------------
# Middleware HTTP (necesita FastAPI)
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_de_prueba():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    reg = obs.Registro()
    app = FastAPI()

    @app.get("/cosas/{id_cosa}")
    def cosa(id_cosa: int):
        return {"id": id_cosa, "request_id": obs.request_id_actual()}

    @app.get("/roto")
    def roto():
        raise RuntimeError("falla simulada")

    obs.instalar(app, "prueba", reg)
    return TestClient(app, raise_server_exceptions=False), reg


def test_el_middleware_devuelve_x_request_id_y_lo_usa_en_el_endpoint(app_de_prueba):
    cliente, _ = app_de_prueba
    r = cliente.get("/cosas/1")
    rid = r.headers["X-Request-ID"]
    assert rid and r.json()["request_id"] == rid


def test_el_middleware_respeta_un_id_entrante_valido(app_de_prueba):
    cliente, _ = app_de_prueba
    r = cliente.get("/cosas/1", headers={"X-Request-ID": "mi-id-de-correlacion"})
    assert r.headers["X-Request-ID"] == "mi-id-de-correlacion"
    assert r.json()["request_id"] == "mi-id-de-correlacion"


def test_el_middleware_reemplaza_un_id_entrante_peligroso(app_de_prueba):
    cliente, _ = app_de_prueba
    r = cliente.get("/cosas/1", headers={"X-Request-ID": "x y z"})
    assert r.headers["X-Request-ID"] != "x y z"


def test_las_metricas_usan_la_plantilla_de_ruta_y_no_el_valor_del_parametro(app_de_prueba):
    cliente, reg = app_de_prueba
    cliente.get("/cosas/1")
    cliente.get("/cosas/2")
    texto = cliente.get("/metrics").text
    assert 'http_requests_total{estado="200",metodo="GET",ruta="/cosas/{id_cosa}",servicio="prueba"} 2' in texto
    assert "/cosas/1" not in texto  # sin explosión de cardinalidad
    assert "http_request_duration_seconds_count" in texto


def test_una_ruta_inexistente_se_cuenta_como_no_encontrada(app_de_prueba):
    cliente, _ = app_de_prueba
    cliente.get("/no-existe-123")
    texto = cliente.get("/metrics").text
    assert 'estado="404",metodo="GET",ruta="no_encontrada"' in texto


def test_un_error_no_controlado_se_cuenta_como_500(app_de_prueba):
    cliente, _ = app_de_prueba
    assert cliente.get("/roto").status_code == 500
    assert 'estado="500"' in cliente.get("/metrics").text


def test_metrics_no_se_cuenta_a_si_mismo_y_tiene_el_content_type_de_prometheus(app_de_prueba):
    cliente, _ = app_de_prueba
    r = cliente.get("/metrics")
    assert r.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert 'ruta="/metrics"' not in r.text
