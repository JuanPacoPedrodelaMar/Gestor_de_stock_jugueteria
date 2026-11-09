"""
Capa de servicio de Clientes (lógica de negocio, sin HTTP).

Cada cliente se identifica por `id_cliente`, que asigna el sistema. El
documento no es único ni se valida como DNI argentino: puede haber clientes de
otros países o documentos repetidos, y el ID es lo que los distingue.
"""
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.cliente import Cliente


def crear_cliente(db: Session, datos, creado_por_dni: Optional[str] = None) -> Cliente:
    """Alta de un cliente. No se verifica unicidad: el documento puede repetirse."""
    cliente = Cliente(
        documento=datos.documento,
        email=datos.email,
        telefono=datos.telefono,
        creado_por_dni=creado_por_dni,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def obtener_cliente(db: Session, id_cliente: int) -> Optional[Cliente]:
    return db.query(Cliente).filter(Cliente.id_cliente == id_cliente).first()


def _escapar_like(texto: str) -> str:
    """Los comodines de LIKE (% y _) escritos por el usuario se buscan literalmente."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def buscar_clientes(db: Session, q: Optional[str] = None, limite: int = 50) -> list[Cliente]:
    """
    Busca por id (coincidencia exacta si el texto es un número, con o sin "#"),
    por documento, por email o por teléfono (contiene el texto, sin distinguir
    mayúsculas). Sin texto devuelve los últimos clientes dados de alta.
    """
    consulta = db.query(Cliente)
    texto = (q or "").strip()
    if texto:
        patron = f"%{_escapar_like(texto)}%"
        condiciones = [
            Cliente.documento.ilike(patron, escape="\\"),
            Cliente.email.ilike(patron, escape="\\"),
            Cliente.telefono.ilike(patron, escape="\\"),
        ]
        sin_numeral = texto.lstrip("#")
        if sin_numeral.isdigit() and len(sin_numeral) <= 9:
            condiciones.append(Cliente.id_cliente == int(sin_numeral))
        consulta = consulta.filter(or_(*condiciones))
    return consulta.order_by(Cliente.id_cliente.desc()).limit(limite).all()
