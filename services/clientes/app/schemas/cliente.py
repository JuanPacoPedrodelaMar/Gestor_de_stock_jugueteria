"""
Schemas de Cliente.

Se acepta cualquier documento (no solo DNI argentino ni solo números), pero con
un juego de caracteres acotado: letras, números, espacio, punto, guion y barra.
Eso permite pasaportes y documentos extranjeros y sigue dejando afuera comillas,
"<>", ";", "--", "../", bytes nulos y saltos de línea (mismo criterio de
sanitización que el resto de la API).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PATRON_DOCUMENTO = r"^[0-9A-Za-z][0-9A-Za-z .\-/]*$"
# usuario@dominio.tld, sin espacios ni caracteres de control o de inyección.
PATRON_EMAIL = r"^[^@\s<>;=`\\{}\"'()]+@[^@\s<>;=`\\{}\"'()]+\.[^@\s<>;=`\\{}\"'()]+$"
# Teléfono internacional: opcional "+", dígitos, espacios, paréntesis y guiones
# (acepta "(0376) 412-3456" y "+54 376 4123456").
PATRON_TELEFONO = r"^\+?[0-9(][0-9 ()\-]{5,24}$"


class ClienteCreate(BaseModel):
    documento: str = Field(
        ...,
        min_length=1,
        max_length=30,
        pattern=PATRON_DOCUMENTO,
        description="DNI, pasaporte u otro documento. Puede repetirse entre clientes.",
    )
    email: Optional[str] = Field(None, max_length=120, pattern=PATRON_EMAIL, description="Opcional")
    telefono: Optional[str] = Field(None, max_length=30, pattern=PATRON_TELEFONO, description="Opcional")

    @field_validator("documento", "email", "telefono", mode="before")
    @classmethod
    def _recortar(cls, valor):
        """Quita espacios de los extremos; un opcional vacío cuenta como no enviado."""
        if isinstance(valor, str):
            valor = valor.strip()
        return valor

    @field_validator("email", "telefono", mode="before")
    @classmethod
    def _vacio_es_none(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor


class ClienteOut(BaseModel):
    id_cliente: int
    documento: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    fecha_alta: datetime

    model_config = ConfigDict(from_attributes=True)
