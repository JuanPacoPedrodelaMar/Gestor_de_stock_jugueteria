"""Tests del circuit breaker y los reintentos (sin red: reloj, espera y azar inyectados)."""
import pytest

from app.core.observabilidad import Registro
from app.core.resiliencia import ABIERTO, CERRADO, SEMIABIERTO, CircuitBreaker, CircuitoAbierto, con_reintentos


class Reloj:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def avanzar(self, s): self.t += s


def _cb(umbral=3, espera=10.0, registro=None):
    reloj = Reloj()
    return CircuitBreaker("productos", umbral_fallos=umbral, espera_segundos=espera, reloj=reloj, registro=registro), reloj


def test_arranca_cerrado_y_permite_llamadas():
    cb, _ = _cb()
    assert cb.estado == CERRADO and cb.permitir()


def test_se_abre_tras_el_umbral_de_fallos_consecutivos():
    cb, _ = _cb(umbral=3)
    for _ in range(2):
        cb.permitir(); cb.fallo()
    assert cb.estado == CERRADO
    cb.permitir(); cb.fallo()
    assert cb.estado == ABIERTO
    assert cb.permitir() is False


def test_un_exito_reinicia_la_cuenta_de_fallos():
    cb, _ = _cb(umbral=3)
    for _ in range(2):
        cb.fallo()
    cb.exito()
    for _ in range(2):
        cb.fallo()
    assert cb.estado == CERRADO  # nunca hubo 3 seguidos


def test_abierto_rechaza_hasta_que_pasa_la_espera_y_entonces_deja_una_prueba():
    cb, reloj = _cb(umbral=1, espera=10)
    cb.fallo()
    reloj.avanzar(9.9)
    assert cb.permitir() is False
    reloj.avanzar(0.2)
    assert cb.permitir() is True and cb.estado == SEMIABIERTO
    assert cb.permitir() is False  # solo una prueba a la vez


def test_si_la_prueba_sale_bien_se_cierra():
    cb, reloj = _cb(umbral=1, espera=10)
    cb.fallo(); reloj.avanzar(11)
    assert cb.permitir()
    cb.exito()
    assert cb.estado == CERRADO and cb.permitir()


def test_si_la_prueba_falla_se_vuelve_a_abrir_y_espera_de_nuevo():
    cb, reloj = _cb(umbral=1, espera=10)
    cb.fallo(); reloj.avanzar(11)
    assert cb.permitir()
    cb.fallo()
    assert cb.estado == ABIERTO
    reloj.avanzar(5)
    assert cb.permitir() is False
    reloj.avanzar(6)
    assert cb.permitir() is True


def test_un_exito_tardio_con_el_circuito_abierto_no_lo_cierra():
    cb, _ = _cb(umbral=1)
    cb.fallo()
    cb.exito()
    assert cb.estado == ABIERTO


def test_ejecutar_cuenta_fallos_pero_no_los_errores_de_negocio():
    cb, _ = _cb(umbral=2)

    def negocio():
        raise KeyError("404 de negocio")

    for _ in range(5):
        with pytest.raises(KeyError):
            cb.ejecutar(negocio, es_fallo=lambda e: False)
    assert cb.estado == CERRADO

    def caido():
        raise ConnectionError("caído")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.ejecutar(caido)
    assert cb.estado == ABIERTO
    with pytest.raises(CircuitoAbierto):
        cb.ejecutar(lambda: "no debería llamarse")


def test_ejecutar_devuelve_el_resultado():
    cb, _ = _cb()
    assert cb.ejecutar(lambda: 42) == 42


def test_publica_metricas_de_estado_transiciones_y_rechazos():
    reg = Registro()
    cb, reloj = _cb(umbral=1, espera=10, registro=reg)
    cb.fallo(); cb.permitir()
    texto = reg.exponer()
    assert 'circuit_breaker_estado{nombre="productos"} 2' in texto
    assert 'circuit_breaker_transiciones_total{a="abierto",nombre="productos"} 1' in texto
    assert 'circuit_breaker_rechazos_total{nombre="productos"} 1' in texto


def test_umbral_invalido():
    with pytest.raises(ValueError):
        CircuitBreaker("x", umbral_fallos=0)


# --- reintentos -------------------------------------------------------------

def test_con_reintentos_reintenta_y_devuelve_el_primer_exito():
    llamadas, esperas = [], []

    def inestable():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise ConnectionError("x")
        return "ok"

    assert con_reintentos(inestable, (ConnectionError,), reintentos=2, espera_segundos=1.0,
                          dormir=esperas.append, azar=lambda: 0.5) == "ok"
    assert len(llamadas) == 3
    assert esperas == [1.0, 2.0]  # exponencial: 1*(2^0)*1.0, 1*(2^1)*1.0


def test_con_reintentos_relanza_al_agotarse():
    def siempre():
        raise ConnectionError("x")
    with pytest.raises(ConnectionError):
        con_reintentos(siempre, (ConnectionError,), reintentos=1, dormir=lambda s: None)


def test_con_reintentos_no_reintenta_otras_excepciones():
    llamadas = []

    def otra():
        llamadas.append(1)
        raise ValueError("no es de red")
    with pytest.raises(ValueError):
        con_reintentos(otra, (ConnectionError,), reintentos=3, dormir=lambda s: None)
    assert len(llamadas) == 1
