"""
Tests del worker de Alertas: lógica de idempotencia y de evaluación de la
alerta, sin necesitar RabbitMQ ni Productos corriendo.

El payload del evento incluye stock_actual y stock_minimo (snapshot del
producto al momento del movimiento), así que no hace falta mockear
Productos.
"""
import os
import tempfile

import pytest

from alertas import (
    evaluar_y_generar_alerta,
    inicializar_db,
    marcar_como_procesado,
    ya_fue_procesado,
)
import json

import pika

import worker
from worker import PayloadInvalido, contar_reintentos_previos, interpretar_payload, procesar_mensaje


@pytest.fixture()
def db_idempotencia():
    archivo_temporal = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    archivo_temporal.close()
    conexion = inicializar_db(archivo_temporal.name)
    yield conexion
    conexion.close()
    os.remove(archivo_temporal.name)


def test_marca_y_detecta_un_movimiento_ya_procesado(db_idempotencia):
    assert ya_fue_procesado(db_idempotencia, id_movimiento=1) is False

    marcar_como_procesado(db_idempotencia, id_movimiento=1, id_producto=10, genero_alerta=True)

    assert ya_fue_procesado(db_idempotencia, id_movimiento=1) is True
    # Un id_movimiento distinto no está afectado.
    assert ya_fue_procesado(db_idempotencia, id_movimiento=2) is False


def test_marcar_como_procesado_es_idempotente(db_idempotencia):
    """Insertar el mismo id_movimiento dos veces no debe fallar (INSERT OR IGNORE)."""
    marcar_como_procesado(db_idempotencia, id_movimiento=1, id_producto=10, genero_alerta=False)
    marcar_como_procesado(db_idempotencia, id_movimiento=1, id_producto=10, genero_alerta=False)
    assert ya_fue_procesado(db_idempotencia, id_movimiento=1) is True


def test_genera_alerta_si_stock_actual_por_debajo_del_minimo():  # caso base; ver también el parametrizado
    payload = {
        "id_movimiento": 1,
        "id_producto": 5,
        "nombre_producto": "Auto a fricción",
        "stock_actual": 2,
        "stock_minimo": 5,
    }
    assert evaluar_y_generar_alerta(payload) is True


@pytest.mark.parametrize(
    "stock_actual,stock_minimo,debe_alertar",
    [
        (2, 5, True),    # por debajo del mínimo
        (5, 5, True),    # EXACTAMENTE en el mínimo: antes no alertaba (< estricto) y el frontend sí lo marcaba
        (6, 5, False),   # apenas por encima
        (0, 0, True),    # mínimo 0 y producto agotado
        (1, 0, False),   # mínimo 0 con stock
    ],
)
def test_la_regla_de_stock_bajo_es_menor_o_igual_al_minimo(stock_actual, stock_minimo, debe_alertar):
    """Misma regla que la tabla de Inventario del frontend: stock_actual <= stock_minimo."""
    payload = {
        "id_movimiento": 3,
        "id_producto": 5,
        "nombre_producto": "Auto a fricción",
        "stock_actual": stock_actual,
        "stock_minimo": stock_minimo,
    }
    assert evaluar_y_generar_alerta(payload) is debe_alertar


def test_no_genera_alerta_si_hay_stock_suficiente():
    payload = {
        "id_movimiento": 2,
        "id_producto": 5,
        "nombre_producto": "Auto a fricción",
        "stock_actual": 20,
        "stock_minimo": 5,
    }
    assert evaluar_y_generar_alerta(payload) is False


def _props(x_death=None):
    class P:
        headers = {"x-death": x_death} if x_death is not None else None
    return P()


def test_contar_reintentos_previos_sin_header():
    assert contar_reintentos_previos(_props()) == 0
    assert contar_reintentos_previos(_props([])) == 0


def test_contar_reintentos_usa_el_count_de_la_cola_principal_y_no_la_longitud_de_la_lista():
    """Formato REAL de RabbitMQ: una entrada por (cola, razón) con un contador acumulado."""
    x_death = [
        {"queue": "alertas.stock.bajo", "reason": "rejected", "count": 6, "exchange": "stock.events"},
        {"queue": "alertas.stock.bajo.retry", "reason": "expired", "count": 6, "exchange": "stock.events.dlx"},
    ]
    assert len(x_death) == 2          # la longitud NO sirve: jamás pasaría de 2
    assert contar_reintentos_previos(_props(x_death)) == 6


def test_contar_reintentos_sin_entradas_reconocibles_usa_el_mayor_contador():
    assert contar_reintentos_previos(_props([{"count": 3}, {"count": 1}])) == 3


# --- payload ---------------------------------------------------------------

PAYLOAD_OK = {"id_movimiento": 1, "id_producto": 5, "stock_actual": 2, "stock_minimo": 5, "nombre_producto": "X"}


def test_interpretar_payload_valido():
    assert interpretar_payload(json.dumps(PAYLOAD_OK).encode())["id_movimiento"] == 1


@pytest.mark.parametrize("cuerpo", [
    b"esto no es json", b"\xff\xfe", b"[1, 2]", b"null", b"{}",
    json.dumps({**PAYLOAD_OK, "stock_actual": None}).encode(),
    json.dumps({**PAYLOAD_OK, "id_movimiento": "1"}).encode(),
    json.dumps({**PAYLOAD_OK, "stock_minimo": True}).encode(),
])
def test_interpretar_payload_rechaza_mensajes_invalidos(cuerpo):
    with pytest.raises(PayloadInvalido):
        interpretar_payload(cuerpo)


# --- procesar_mensaje con un canal falso (sin RabbitMQ) ----------------------

class CanalFalso:
    def __init__(self):
        self.acks, self.nacks, self.publicados = [], [], []

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))

    def basic_publish(self, exchange, routing_key, body, properties):
        self.publicados.append((exchange, routing_key, body, properties))


class Metodo:
    delivery_tag = 7


def test_un_mensaje_malformado_va_a_la_dlq_y_no_tira_el_worker(db_idempotencia):
    canal = CanalFalso()
    procesar_mensaje(canal, Metodo(), _props(), b"basura", db_idempotencia)  # no debe levantar
    assert canal.acks == [7] and canal.nacks == []
    exchange, routing_key, body, props = canal.publicados[0]
    assert (exchange, routing_key, body) == (worker.EXCHANGE_DLX, worker.ROUTING_KEY_DLQ, b"basura")
    assert props.headers["x-motivo-dlq"].startswith("payload_invalido")


def test_un_mensaje_valido_se_confirma_y_queda_marcado(db_idempotencia):
    canal = CanalFalso()
    procesar_mensaje(canal, Metodo(), _props(), json.dumps(PAYLOAD_OK).encode(), db_idempotencia)
    assert canal.acks == [7] and not canal.publicados
    assert ya_fue_procesado(db_idempotencia, 1) is True


def test_un_duplicado_se_confirma_sin_reprocesar(db_idempotencia):
    canal = CanalFalso()
    cuerpo = json.dumps(PAYLOAD_OK).encode()
    procesar_mensaje(canal, Metodo(), _props(), cuerpo, db_idempotencia)
    procesar_mensaje(canal, Metodo(), _props(), cuerpo, db_idempotencia)
    assert canal.acks == [7, 7] and not canal.nacks


def _fallar(payload):
    raise RuntimeError("falla simulada del procesamiento")


def test_un_error_de_procesamiento_reintenta_con_nack_sin_requeue(db_idempotencia, monkeypatch):
    monkeypatch.setattr(worker, "evaluar_y_generar_alerta", _fallar)
    canal = CanalFalso()
    x_death = [{"queue": "alertas.stock.bajo", "reason": "rejected", "count": 2}]
    procesar_mensaje(canal, Metodo(), _props(x_death), json.dumps(PAYLOAD_OK).encode(), db_idempotencia)
    assert canal.nacks == [(7, False)] and not canal.acks and not canal.publicados


def test_tras_max_reintentos_el_mensaje_va_a_la_dlq(db_idempotencia, monkeypatch):
    """Antes del arreglo esto no ocurría nunca con mensajes reales de RabbitMQ."""
    monkeypatch.setattr(worker, "evaluar_y_generar_alerta", _fallar)
    canal = CanalFalso()
    x_death = [
        {"queue": "alertas.stock.bajo", "reason": "rejected", "count": worker.MAX_REINTENTOS},
        {"queue": "alertas.stock.bajo.retry", "reason": "expired", "count": worker.MAX_REINTENTOS},
    ]
    procesar_mensaje(canal, Metodo(), _props(x_death), json.dumps(PAYLOAD_OK).encode(), db_idempotencia)
    assert canal.acks == [7] and not canal.nacks
    assert canal.publicados[0][1] == worker.ROUTING_KEY_DLQ
    assert canal.publicados[0][3].headers["x-motivo-dlq"] == f"max_reintentos_{worker.MAX_REINTENTOS}"
