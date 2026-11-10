"""
Worker de Alertas de Stock Bajo.

Consume el evento "movimiento.registrado" (ver services/movimientos/EVENTOS.md)
y evalúa si corresponde generar una alerta de stock bajo (stock_actual <=
stock_minimo, ver alertas.py). Expone GET /health (ver health.py). Es idempotente por
id_movimiento (ver alertas.py) e implementa reintentos con backoff y una
dead-letter queue (DLQ) final para mensajes que fallan reiteradamente.

Topología de colas (ver también services/worker-alertas/README.md):

    stock.events (exchange topic)  --movimiento.registrado-->  alertas.stock.bajo
                                                                       |
                                                          (nack en error, requeue=False)
                                                                       v
    stock.events.dlx (exchange direct) <--alertas.stock.bajo.retry-- alertas.stock.bajo.retry
                                                                       |
                                                        (TTL de la cola: reintento con backoff)
                                                                       v
    stock.events.dlx --alertas.stock.bajo.reintentar--> alertas.stock.bajo (vuelve a intentarse)

    Tras MAX_REINTENTOS, el mensaje se publica manualmente en:
    stock.events.dlx --alertas.stock.bajo.dlq--> alertas.stock.bajo.dlq (inspección manual)
"""
import json
import logging
import os
import time

import pika

import health
import observabilidad
from alertas import (
    evaluar_y_generar_alerta,
    inicializar_db,
    marcar_como_procesado,
    ya_fue_procesado,
)

observabilidad.configurar_logging("worker-alertas")
logger = logging.getLogger("worker-alertas")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672/")
ALERTAS_DB_PATH = os.getenv("ALERTAS_DB_PATH", "/app/data/alertas_procesadas.db")
MAX_REINTENTOS = int(os.getenv("MAX_REINTENTOS", "5"))
RETRY_TTL_MS = int(os.getenv("RETRY_TTL_MS", "5000"))  # backoff fijo de 5s entre reintentos
HEALTH_PORT = int(os.getenv("WORKER_HEALTH_PORT", "8003"))
HEARTBEAT_SEGUNDOS = float(os.getenv("WORKER_HEARTBEAT_SEGUNDOS", "10"))

EXCHANGE_EVENTOS = "stock.events"
EXCHANGE_DLX = "stock.events.dlx"

COLA_PRINCIPAL = "alertas.stock.bajo"
COLA_RETRY = "alertas.stock.bajo.retry"
COLA_DLQ = "alertas.stock.bajo.dlq"

ROUTING_KEY_EVENTO = "movimiento.registrado"
ROUTING_KEY_RETRY = "alertas.stock.bajo.retry"
ROUTING_KEY_REINTENTAR = "alertas.stock.bajo.reintentar"
ROUTING_KEY_DLQ = "alertas.stock.bajo.dlq"


def declarar_topologia(canal):
    """Declara exchanges/colas/bindings de forma idempotente (seguro llamarlo siempre al iniciar)."""
    canal.exchange_declare(exchange=EXCHANGE_EVENTOS, exchange_type="topic", durable=True)
    canal.exchange_declare(exchange=EXCHANGE_DLX, exchange_type="direct", durable=True)

    # Cola principal: si un mensaje se rechaza (nack, requeue=False), Rabbit
    # lo dead-letterea hacia la cola de reintentos.
    canal.queue_declare(
        queue=COLA_PRINCIPAL,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": ROUTING_KEY_RETRY,
        },
    )
    canal.queue_bind(queue=COLA_PRINCIPAL, exchange=EXCHANGE_EVENTOS, routing_key=ROUTING_KEY_EVENTO)
    # También recibe los mensajes que vuelven desde la cola de reintentos.
    canal.queue_bind(queue=COLA_PRINCIPAL, exchange=EXCHANGE_DLX, routing_key=ROUTING_KEY_REINTENTAR)

    # Cola de reintentos: no tiene consumidor propio, solo demora el mensaje
    # (TTL) y lo vuelve a dead-letterear hacia la cola principal.
    canal.queue_declare(
        queue=COLA_RETRY,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_TTL_MS,
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": ROUTING_KEY_REINTENTAR,
        },
    )
    canal.queue_bind(queue=COLA_RETRY, exchange=EXCHANGE_DLX, routing_key=ROUTING_KEY_RETRY)

    # DLQ final: mensajes que superaron MAX_REINTENTOS, para inspección manual.
    canal.queue_declare(queue=COLA_DLQ, durable=True)
    canal.queue_bind(queue=COLA_DLQ, exchange=EXCHANGE_DLX, routing_key=ROUTING_KEY_DLQ)


def contar_reintentos_previos(properties) -> int:
    """
    Cuántas veces ya falló este mensaje en la cola principal.

    RabbitMQ agrega el header 'x-death', pero NO guarda un registro por cada
    muerte: guarda UNA entrada por cada par (cola, razón) con un campo `count`
    que se va incrementando. Con esta topología el mensaje pasa por dos pares
    ((principal, rejected) y (retry, expired)), así que `len(x-death)` vale como
    máximo 2 y jamás llegaría a MAX_REINTENTOS: el mensaje se reintentaría para
    siempre sin ir a la DLQ. Lo correcto es sumar el `count` de la entrada de la
    cola principal rechazada (cada `nack` del worker incrementa ese contador).
    """
    headers = properties.headers or {}
    entradas = [e for e in (headers.get("x-death") or []) if isinstance(e, dict)]
    if not entradas:
        return 0
    rechazos = [
        int(e.get("count", 1)) for e in entradas
        if e.get("queue") == COLA_PRINCIPAL and e.get("reason") == "rejected"
    ]
    if rechazos:
        return sum(rechazos)
    # Entradas sin cola/razón reconocibles (otra topología): criterio conservador,
    # el mayor contador observado.
    return max(int(e.get("count", 1)) for e in entradas)


class PayloadInvalido(Exception):
    """El mensaje no se puede interpretar: reintentarlo no lo arregla (va directo a la DLQ)."""


def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def interpretar_payload(body) -> dict:
    """Decodifica y valida el evento. Levanta PayloadInvalido ante cualquier defecto."""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as error:  # incluye UnicodeDecodeError y JSONDecodeError
        raise PayloadInvalido(f"No es JSON válido: {error}") from error
    if not isinstance(payload, dict):
        raise PayloadInvalido("El mensaje no es un objeto JSON.")
    for campo in ("id_movimiento", "id_producto", "stock_actual", "stock_minimo"):
        if not _es_entero(payload.get(campo)):
            raise PayloadInvalido(f"Falta el campo entero '{campo}' o tiene un tipo inválido.")
    return payload


def _enviar_a_dlq(canal, body, motivo: str) -> None:
    canal.basic_publish(
        exchange=EXCHANGE_DLX,
        routing_key=ROUTING_KEY_DLQ,
        body=body,
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=2, headers={"x-motivo-dlq": motivo[:200]}
        ),
    )


def _contar(resultado: str) -> None:
    observabilidad.REGISTRO.inc(
        "worker_mensajes_total", "Mensajes procesados por el worker según el resultado.", {"resultado": resultado}
    )


def procesar_mensaje(canal, method, properties, body, conexion_idempotencia):
    # Un mensaje que no se puede interpretar nunca se va a poder procesar: se
    # manda directo a la DLQ (con el motivo) y se confirma. Antes la excepción
    # salía del consumidor, el proceso moría y el mensaje volvía a entregarse:
    # un bucle de caídas.
    try:
        payload = interpretar_payload(body)
    except PayloadInvalido as error:
        logger.error("Mensaje inválido, se envía a la DLQ: %s", error, extra={"evento": "mensaje_invalido"})
        _enviar_a_dlq(canal, body, f"payload_invalido: {error}")
        canal.basic_ack(delivery_tag=method.delivery_tag)
        _contar("invalido")
        return

    id_movimiento = payload["id_movimiento"]
    # Correlación: se retoma el ID del pedido que originó el movimiento.
    token_rid = observabilidad.fijar_request_id(observabilidad.request_id_entrante(payload.get("request_id")))
    try:
        _procesar_validado(canal, method, properties, body, payload, id_movimiento, conexion_idempotencia)
    finally:
        observabilidad.restablecer_request_id(token_rid)


def _procesar_validado(canal, method, properties, body, payload, id_movimiento, conexion_idempotencia):
    if ya_fue_procesado(conexion_idempotencia, id_movimiento):
        logger.info("id_movimiento=%s ya fue procesado antes; se descarta sin reprocesar.", id_movimiento)
        canal.basic_ack(delivery_tag=method.delivery_tag)
        _contar("duplicado")
        return

    try:
        genero_alerta = evaluar_y_generar_alerta(payload)
        marcar_como_procesado(conexion_idempotencia, id_movimiento, payload["id_producto"], genero_alerta)
        canal.basic_ack(delivery_tag=method.delivery_tag)
        _contar("alerta" if genero_alerta else "sin_alerta")
    except Exception:
        logger.exception("Error procesando id_movimiento=%s", id_movimiento)
        intentos_previos = contar_reintentos_previos(properties)

        if intentos_previos >= MAX_REINTENTOS:
            logger.error(
                "id_movimiento=%s superó MAX_REINTENTOS=%s; se envía a la DLQ final.",
                id_movimiento, MAX_REINTENTOS,
            )
            _enviar_a_dlq(canal, body, f"max_reintentos_{MAX_REINTENTOS}")
            canal.basic_ack(delivery_tag=method.delivery_tag)
            _contar("dlq")
        else:
            _contar("reintento")
            # requeue=False: NO vuelve a la misma cola directamente, cae por
            # dead-lettering en la cola de reintentos (con el TTL de backoff).
            canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    # Healthcheck HTTP: arranca ANTES de conectar a RabbitMQ para que, mientras
    # espera al broker, responda 503 "starting" en lugar de no responder.
    # Tolera 3 latidos perdidos antes de declararse "unhealthy".
    estado_salud = health.EstadoSalud(tolerancia_segundos=HEARTBEAT_SEGUNDOS * 3)
    health.iniciar_servidor(estado_salud, HEALTH_PORT)

    conexion_idempotencia = inicializar_db(ALERTAS_DB_PATH)

    parametros = pika.URLParameters(RABBITMQ_URL)
    while True:
        try:
            conexion = pika.BlockingConnection(parametros)
            break
        except pika.exceptions.AMQPConnectionError:
            logger.warning("RabbitMQ no disponible todavía, reintentando en 3s...")
            time.sleep(3)

    canal = conexion.channel()
    declarar_topologia(canal)
    canal.basic_qos(prefetch_count=10)

    def callback(ch, method, properties, body):
        procesar_mensaje(ch, method, properties, body, conexion_idempotencia)

    canal.basic_consume(queue=COLA_PRINCIPAL, on_message_callback=callback)

    def latir():
        # Corre dentro del loop de la conexión (el mismo que procesa mensajes):
        # si ese loop se traba o la conexión cae, el latido se detiene.
        estado_salud.latido()
        conexion.call_later(HEARTBEAT_SEGUNDOS, latir)

    estado_salud.marcar_consumiendo()
    conexion.call_later(HEARTBEAT_SEGUNDOS, latir)

    logger.info("Worker de Alertas escuchando en la cola '%s'...", COLA_PRINCIPAL)
    try:
        canal.start_consuming()
    except KeyboardInterrupt:
        canal.stop_consuming()
        conexion.close()
    finally:
        estado_salud.marcar_detenido()


if __name__ == "__main__":
    main()
