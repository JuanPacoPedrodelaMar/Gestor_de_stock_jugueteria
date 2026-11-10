"""
Resiliencia en las llamadas a otros servicios: circuit breaker y reintentos.

Por qué hace falta. Movimientos llama a Productos (y a Clientes) por HTTP. Si
Productos se cae o se cuelga, cada pedido espera el timeout completo (5 s) antes
de fallar: los hilos del servidor se acumulan esperando y Movimientos termina
degradándose también (falla en cascada). El circuit breaker corta esa espera:

    CERRADO ──(N fallos seguidos)──► ABIERTO ──(pasa `espera_segundos`)──► SEMIABIERTO
       ▲                               │ rechaza al instante                     │
       │                               ▼ (sin llamar a la red)                   │
       └──────────(la prueba sale bien)────────────(la prueba falla: vuelve a ABIERTO)

- CERRADO: todo pasa; se cuentan los fallos CONSECUTIVOS (un éxito los reinicia).
- ABIERTO: se rechaza sin llamar al servicio caído (falla rápido, 503 inmediato).
- SEMIABIERTO: tras la espera se deja pasar UNA sola llamada de prueba; si sale
  bien se cierra, si falla se vuelve a abrir.

Qué cuenta como fallo: solo lo que indica que el SERVICIO está mal (timeout, sin
conexión, HTTP 5xx). Un 404 o un 409 son respuestas de negocio normales: el
servicio está sano, así que cuentan como éxito.

Con la saga de movimientos, rechazar rápido es seguro: el movimiento queda
`pendiente` y se completa con un reintento (misma Idempotency-Key) cuando el
servicio vuelve. Ver docs/adr/0005-resiliencia.md.
"""
import random
import threading
import time
from typing import Callable, Optional

CERRADO = "cerrado"
ABIERTO = "abierto"
SEMIABIERTO = "semiabierto"
_NUMERO_DE_ESTADO = {CERRADO: 0, SEMIABIERTO: 1, ABIERTO: 2}  # para la métrica (gauge)


class CircuitoAbierto(Exception):
    """El circuito está abierto: no se intentó la llamada."""


class CircuitBreaker:
    def __init__(
        self,
        nombre: str,
        umbral_fallos: int = 5,
        espera_segundos: float = 15.0,
        reloj: Callable[[], float] = time.monotonic,
        registro=None,
    ):
        if umbral_fallos < 1:
            raise ValueError("umbral_fallos debe ser >= 1")
        self.nombre = nombre
        self._umbral = umbral_fallos
        self._espera = espera_segundos
        self._reloj = reloj
        self._registro = registro  # observabilidad.Registro (opcional)
        self._lock = threading.Lock()
        self._estado = CERRADO
        self._fallos = 0
        self._abierto_desde = 0.0
        self._prueba_en_curso = False
        self._publicar_estado()

    # -- consulta -----------------------------------------------------------
    @property
    def estado(self) -> str:
        with self._lock:
            return self._estado

    # -- métricas -----------------------------------------------------------
    def _publicar_estado(self) -> None:
        if self._registro is not None:
            self._registro.gauge(
                "circuit_breaker_estado", "Estado del circuit breaker (0 cerrado, 1 semiabierto, 2 abierto).",
                _NUMERO_DE_ESTADO[self._estado], {"nombre": self.nombre},
            )

    def _transicion(self, nuevo: str) -> None:
        if nuevo == self._estado:
            return
        self._estado = nuevo
        self._publicar_estado()
        if self._registro is not None:
            self._registro.inc(
                "circuit_breaker_transiciones_total", "Cambios de estado del circuit breaker.",
                {"nombre": self.nombre, "a": nuevo},
            )

    def _contar_rechazo(self) -> None:
        if self._registro is not None:
            self._registro.inc(
                "circuit_breaker_rechazos_total", "Llamadas rechazadas por circuito abierto.", {"nombre": self.nombre}
            )

    # -- protocolo ----------------------------------------------------------
    def permitir(self) -> bool:
        """¿Se puede intentar la llamada ahora? Quien la intente DEBE informar después exito() o fallo()."""
        with self._lock:
            if self._estado == CERRADO:
                return True
            if self._estado == ABIERTO:
                if self._reloj() - self._abierto_desde >= self._espera:
                    self._transicion(SEMIABIERTO)
                    self._prueba_en_curso = True
                    return True
                self._contar_rechazo()
                return False
            # SEMIABIERTO: una sola llamada de prueba a la vez.
            if not self._prueba_en_curso:
                self._prueba_en_curso = True
                return True
            self._contar_rechazo()
            return False

    def exito(self) -> None:
        with self._lock:
            if self._estado == ABIERTO:
                return  # un éxito tardío de una llamada previa no prueba nada: se espera a la prueba
            self._fallos = 0
            self._prueba_en_curso = False
            self._transicion(CERRADO)

    def fallo(self) -> None:
        with self._lock:
            if self._estado == SEMIABIERTO:
                self._abrir()
            elif self._estado == CERRADO:
                self._fallos += 1
                if self._fallos >= self._umbral:
                    self._abrir()

    def _abrir(self) -> None:
        self._abierto_desde = self._reloj()
        self._fallos = 0
        self._prueba_en_curso = False
        self._transicion(ABIERTO)

    def reiniciar(self) -> None:
        """Vuelve a CERRADO (para tests)."""
        with self._lock:
            self._fallos = 0
            self._prueba_en_curso = False
            self._transicion(CERRADO)

    # -- conveniencia -------------------------------------------------------
    def ejecutar(self, funcion: Callable[[], object], es_fallo: Callable[[BaseException], bool] = lambda e: True):
        """Ejecuta `funcion` protegida por el circuito (levanta CircuitoAbierto si no se puede)."""
        if not self.permitir():
            raise CircuitoAbierto(self.nombre)
        try:
            resultado = funcion()
        except Exception as error:
            if es_fallo(error):
                self.fallo()
            else:
                self.exito()
            raise
        self.exito()
        return resultado


def con_reintentos(
    llamada: Callable[[], object],
    reintentar_en: tuple,
    reintentos: int = 1,
    espera_segundos: float = 0.2,
    dormir: Callable[[float], None] = time.sleep,
    azar: Callable[[], float] = random.random,
):
    """
    Reintenta `llamada` hasta `reintentos` veces más si levanta alguna de las
    excepciones de `reintentar_en`, con espera exponencial y jitter (la espera se
    multiplica por un número entre 0.5 y 1.5 para que varios clientes no
    reintenten todos a la vez). Si se agotan, relanza la última excepción.

    Solo se debe usar con llamadas SEGURAS de repetir: lecturas, o escrituras
    idempotentes (el ajuste de stock lo es: lleva Idempotency-Key).
    """
    intento = 0
    while True:
        try:
            return llamada()
        except reintentar_en:
            if intento >= reintentos:
                raise
            dormir(espera_segundos * (2 ** intento) * (0.5 + azar()))
            intento += 1
