"""
Capa de Rutas de las solicitudes de stock (pedidos de reposición).

- Pedir reposición: empleado de almacén o mixto.
- Ver las solicitudes: admin (todas) y almacén/mixto (las propias).
- Atender o rechazar: solo admin.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.jwt_auth import requerir_rol
from app.database.db import get_db
from app.schemas.producto import SolicitudStockCreate, SolicitudStockOut, SolicitudStockResolver
from app.services import solicitud_service

router = APIRouter(prefix="/api/v1/solicitudes-stock", tags=["Solicitudes de stock"])


@router.post("", response_model=SolicitudStockOut, status_code=status.HTTP_201_CREATED)
def pedir_stock(
    datos: SolicitudStockCreate,
    db: Session = Depends(get_db),
    payload: dict = Depends(requerir_rol("almacen", "mixto")),
):
    """POST /api/v1/solicitudes-stock -> 201. Pide reponer un producto (no cambia el stock)."""
    try:
        return solicitud_service.crear_solicitud(db, datos, payload)
    except solicitud_service.ProductoNoDisponible:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe un producto activo con id_producto={datos.id_producto}.",
        )


@router.get("", response_model=List[SolicitudStockOut], status_code=status.HTTP_200_OK)
def listar_solicitudes(
    estado: Optional[str] = Query(None, pattern="^(pendiente|atendida|rechazada)$"),
    db: Session = Depends(get_db),
    payload: dict = Depends(requerir_rol("admin", "almacen", "mixto")),
):
    """GET /api/v1/solicitudes-stock -> 200. El admin ve todas; almacén y mixto, solo las suyas."""
    return solicitud_service.listar_solicitudes(db, payload, estado)


@router.patch(
    "/{id_solicitud}",
    response_model=SolicitudStockOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(requerir_rol("admin"))],
)
def resolver_solicitud(id_solicitud: int, datos: SolicitudStockResolver, db: Session = Depends(get_db)):
    """PATCH /api/v1/solicitudes-stock/{id} -> 200, 404 o 409 (ya resuelta). Solo admin."""
    try:
        solicitud = solicitud_service.resolver_solicitud(db, id_solicitud, datos.estado)
    except solicitud_service.SolicitudYaResuelta:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esa solicitud ya fue resuelta.")
    if solicitud is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró la solicitud {id_solicitud}.",
        )
    return solicitud
