"""
Modelo SolicitudStock: pedido de reposición que hace un empleado de almacén
cuando un producto necesita más stock. No modifica el stock: es un aviso que
un admin atiende (el stock cambia recién cuando se registra el ingreso, como
cualquier otro movimiento).
"""
from sqlalchemy import Column, DateTime, Integer, String, func

from app.database.db import Base

ESTADO_PENDIENTE = "pendiente"
ESTADO_ATENDIDA = "atendida"
ESTADO_RECHAZADA = "rechazada"


class SolicitudStock(Base):
    __tablename__ = "solicitudes_stock"

    id_solicitud = Column(Integer, primary_key=True, index=True, autoincrement=True)
    id_producto = Column(Integer, nullable=False, index=True)
    # Nombre del producto al momento de pedir: la solicitud se entiende aunque
    # el producto se dé de baja después.
    nombre_producto = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    nota = Column(String(200), nullable=True)

    estado = Column(String, nullable=False, default=ESTADO_PENDIENTE, server_default=ESTADO_PENDIENTE, index=True)

    # Quién la pidió: id del usuario (para filtrar "mis solicitudes") y su DNI
    # (o email si no tiene) para mostrarlo.
    solicitado_por = Column(Integer, nullable=False, index=True)
    solicitante = Column(String, nullable=False)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
