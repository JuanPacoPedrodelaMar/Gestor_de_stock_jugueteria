"""
Capa de servicio de las solicitudes de stock (pedidos de reposición).

Una solicitud NO modifica el stock: es un aviso de un empleado de almacén para
que un admin reponga. Cuando llega la mercadería se registra un movimiento de
ingreso, como siempre (ver services/movimientos).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.producto import Producto
from app.models.solicitud_stock import ESTADO_PENDIENTE, SolicitudStock
from app.schemas.producto import SolicitudStockCreate


class ProductoNoDisponible(Exception):
    """El producto no existe o está dado de baja: no tiene sentido pedir reposición."""


class SolicitudYaResuelta(Exception):
    """La solicitud ya fue atendida o rechazada; no se puede resolver de nuevo."""


def crear_solicitud(db: Session, datos: SolicitudStockCreate, payload: dict) -> SolicitudStock:
    producto = db.query(Producto).filter(Producto.id_producto == datos.id_producto).first()
    if producto is None or producto.activo is False:
        raise ProductoNoDisponible()

    solicitud = SolicitudStock(
        id_producto=producto.id_producto,
        nombre_producto=producto.nombre,
        cantidad=datos.cantidad,
        nota=datos.nota or None,
        estado=ESTADO_PENDIENTE,
        solicitado_por=int(payload["sub"]),
        solicitante=payload.get("dni") or payload.get("email") or str(payload["sub"]),
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


def listar_solicitudes(db: Session, payload: dict, estado: Optional[str] = None) -> list[SolicitudStock]:
    """El admin ve todas; el resto, solo las que pidió él."""
    consulta = db.query(SolicitudStock)
    if payload.get("rol") != "admin":
        consulta = consulta.filter(SolicitudStock.solicitado_por == int(payload["sub"]))
    if estado:
        consulta = consulta.filter(SolicitudStock.estado == estado)
    return consulta.order_by(SolicitudStock.id_solicitud.desc()).all()


def resolver_solicitud(db: Session, id_solicitud: int, estado: str) -> Optional[SolicitudStock]:
    """Marca una solicitud pendiente como atendida/rechazada. None si no existe."""
    solicitud = db.query(SolicitudStock).filter(SolicitudStock.id_solicitud == id_solicitud).first()
    if solicitud is None:
        return None
    if solicitud.estado != ESTADO_PENDIENTE:
        raise SolicitudYaResuelta()
    solicitud.estado = estado
    db.commit()
    db.refresh(solicitud)
    return solicitud
