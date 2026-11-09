"""
Modelo de la entidad Producto.

Capa de Persistencia.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Float, Boolean
from app.database.db import Base


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Producto(Base):
    __tablename__ = "productos"

    id_producto = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String, nullable=False, index=True)
    marca = Column(String, nullable=True)
    precio_venta = Column(Float, nullable=False)
    stock_actual = Column(Integer, nullable=False, default=0)
    stock_minimo = Column(Integer, nullable=False, default=0)
    categoria = Column(String, nullable=True)

    # Soft delete: un producto con movimientos asociados no se borra
    # físicamente (perdería trazabilidad del historial de stock). En su
    # lugar se marca activo=False y se excluye de los listados por defecto.
    # Ver services/productos/README.md para la justificación completa.
    activo = Column(Boolean, nullable=False, default=True, server_default="1")

    # Autoría y alta: quién cargó el producto (id del usuario en auth) y cuándo.
    # Permiten la "ventana de arrepentimiento": un empleado puede eliminar un
    # producto que él mismo cargó durante los primeros minutos; pasado ese
    # tiempo, solo un admin. NULL en productos anteriores a este campo (solo
    # los puede eliminar un admin).
    creado_por = Column(Integer, nullable=True, index=True)
    fecha_creacion = Column(DateTime(timezone=True), nullable=True, default=ahora_utc)
