"""
Modelo de la entidad Cliente.

Cada cliente se identifica por `id_cliente`, un número que asigna el sistema.
El `documento` (DNI, pasaporte, DNI extranjero, lo que tenga) es un dato más:
NO es único ni se valida como DNI argentino, porque puede haber clientes de
otros países y documentos que se repiten. El email y el teléfono son opcionales.
"""
from sqlalchemy import Column, DateTime, Integer, String, func

from app.database.db import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente = Column(Integer, primary_key=True, index=True, autoincrement=True)
    documento = Column(String(30), nullable=False, index=True)  # sin unicidad a propósito
    email = Column(String(120), nullable=True, index=True)
    telefono = Column(String(30), nullable=True)
    fecha_alta = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # DNI del empleado que lo dio de alta (viene del token).
    creado_por_dni = Column(String(8), nullable=True)
