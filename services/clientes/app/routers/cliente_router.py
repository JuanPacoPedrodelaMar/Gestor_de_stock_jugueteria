"""
Capa de Rutas de Clientes.

Los clientes los usan quienes atienden ventas: admin, ventas y mixto (un
empleado de almacén no ve datos de clientes). Cada cliente tiene un id que
asigna el sistema; el documento no es único ni se valida como DNI argentino,
así que se pueden cargar personas de otros países o documentos repetidos.
El email y el teléfono son opcionales.

El historial de movimientos de un cliente NO está acá: lo tiene el servicio de
Movimientos (GET /api/v1/movimientos?id_cliente=N), que es dueño de esos datos.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.jwt_auth import requerir_rol
from app.database.db import get_db
from app.schemas.cliente import ClienteCreate, ClienteOut
from app.services import cliente_service

router = APIRouter(prefix="/api/v1/clientes", tags=["Clientes"])

ROLES_CLIENTES = ("admin", "ventas", "mixto")


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def crear_cliente(
    datos: ClienteCreate,
    db: Session = Depends(get_db),
    credenciales: tuple[str, dict] = Depends(requerir_rol(*ROLES_CLIENTES)),
):
    """POST /api/v1/clientes -> 201. El id lo asigna el sistema; el documento puede repetirse."""
    _, payload = credenciales
    return cliente_service.crear_cliente(db, datos, creado_por_dni=payload.get("dni"))


@router.get("", response_model=List[ClienteOut], status_code=status.HTTP_200_OK)
def buscar_clientes(
    q: Optional[str] = Query(
        None,
        max_length=60,
        description="Texto a buscar en id, documento, email o teléfono. Sin texto: los últimos dados de alta.",
    ),
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _credenciales: tuple[str, dict] = Depends(requerir_rol(*ROLES_CLIENTES)),
):
    """GET /api/v1/clientes?q=... -> 200. Búsqueda de clientes."""
    return cliente_service.buscar_clientes(db, q, limite)


@router.get("/{id_cliente}", response_model=ClienteOut, status_code=status.HTTP_200_OK)
def obtener_cliente(
    id_cliente: int,
    db: Session = Depends(get_db),
    _credenciales: tuple[str, dict] = Depends(requerir_rol(*ROLES_CLIENTES)),
):
    """GET /api/v1/clientes/{id} -> 200 o 404. También lo consulta Movimientos para validar un id_cliente."""
    cliente = cliente_service.obtener_cliente(db, id_cliente)
    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró un cliente con id_cliente={id_cliente}.",
        )
    return cliente
