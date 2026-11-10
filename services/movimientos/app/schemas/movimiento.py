"""
Schemas de Movimiento.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CategoriaMovimiento = Literal["venta", "ingreso", "estropeo", "devolucion"]


class MovimientoCreate(BaseModel):
    """Schema usado en el POST /api/v1/movimientos (única forma de crear un movimiento)."""

    categoria_movimiento: CategoriaMovimiento = Field(
        ..., description="venta | ingreso | estropeo | devolucion"
    )
    cantidad_movida: int = Field(
        ..., gt=0, le=1_000_000, description="Cantidad movida, siempre positiva (hasta 1.000.000); el signo lo define la categoría"
    )
    id_producto: int = Field(..., description="ID del producto afectado (servicio de Productos)")
    id_cliente: Optional[int] = Field(
        None, ge=1, description="ID del cliente (opcional). Se crea en el servicio de Clientes (POST /api/v1/clientes)."
    )
    # No hay campo de empleado: el DNI del empleado lo toma el servidor del token.
    # Si un cliente de la API lo manda igual, se ignora (no se puede falsear).


class MovimientoOut(BaseModel):
    """Schema de salida: lo que la API devuelve al cliente."""

    id_movimiento: int
    fecha_hora: datetime
    categoria_movimiento: str
    cantidad_movida: int
    id_producto: int
    id_cliente: Optional[int] = None
    cliente_documento: Optional[str] = Field(
        None, description="Documento del cliente al momento del movimiento (copia; el dato vivo está en Clientes)."
    )
    dni_cliente: Optional[str] = Field(None, description="Solo en movimientos anteriores a la tabla de clientes.")
    dni_empleado: Optional[str] = Field(None, description="DNI del empleado que lo registró (del token).")
    estado: Literal["pendiente", "confirmado"] = Field(
        "confirmado",
        description=(
            "confirmado: el stock ya fue ajustado. pendiente: se guardó la solicitud pero "
            "todavía no se confirmó el ajuste de stock (reintentar con la misma Idempotency-Key)."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class CantidadMovimientosOut(BaseModel):
    """Cantidad de movimientos de un producto (la usa Productos antes de dar de baja)."""

    id_producto: int
    cantidad: int


class ReconciliacionOut(BaseModel):
    """Resultado de POST /api/v1/movimientos/reconciliar."""

    revisados: int
    confirmados: int
    descartados: int
    sin_resolver: int
