"""
Schemas del servicio auth.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.usuario import RolUsuario

# DNI de un empleado: solo dígitos (7 u 8). Excluye comillas, "<>", ";", "--",
# saltos de línea y demás caracteres típicos de una inyección.
PATRON_DNI_EMPLEADO = r"^[0-9]{7,8}$"


class UsuarioCreate(BaseModel):
    """Alta de un usuario nuevo. Solo la puede hacer un admin (ver router)."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72, description="Mínimo 8 caracteres.")
    nombre: str = Field(..., min_length=1, max_length=120)
    rol: RolUsuario = RolUsuario.MIXTO
    dni: Optional[str] = Field(
        None,
        pattern=PATRON_DNI_EMPLEADO,
        description="DNI (7 u 8 dígitos). Obligatorio para los roles de empleado: es con lo que inician sesión.",
    )

    @model_validator(mode="after")
    def _dni_obligatorio_para_empleados(self):
        if self.rol != RolUsuario.ADMIN and not self.dni:
            raise ValueError("El DNI es obligatorio para los empleados (almacen, ventas, mixto).")
        return self


class UsuarioOut(BaseModel):
    id_usuario: int
    email: EmailStr
    nombre: str
    rol: RolUsuario
    activo: bool
    dni: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """
    Login con DNI (empleados) o con email (admin, o cualquier usuario). Hay que
    enviar uno de los dos.
    """
    email: Optional[EmailStr] = None
    dni: Optional[str] = Field(None, pattern=PATRON_DNI_EMPLEADO)
    password: str

    @field_validator("dni", mode="before")
    @classmethod
    def _dni_vacio_es_none(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor

    @model_validator(mode="after")
    def _uno_de_los_dos(self):
        if bool(self.email) == bool(self.dni):
            raise ValueError("Enviá el DNI o el email (uno solo de los dos).")
        return self

    @property
    def identificador(self) -> str:
        """Lo que se usa para buscar al usuario y para contar intentos fallidos."""
        return str(self.email or self.dni)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
