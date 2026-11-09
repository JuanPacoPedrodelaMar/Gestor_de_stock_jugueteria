"""
Modelo de la entidad Usuario (servicio auth).
"""
import enum

from sqlalchemy import Column, Integer, String, Boolean, Enum
from app.database.db import Base


class RolUsuario(str, enum.Enum):
    """
    Roles del sistema:

    - admin: acceso total (incluida la auditoría y la gestión de usuarios).
    - almacen: empleado de depósito. Carga productos nuevos, puede eliminar un
      producto que cargó él mismo durante los primeros minutos (ventana de
      arrepentimiento) y solicita reposición de stock. No registra movimientos.
    - ventas: empleado de atención al cliente. Solo registra movimientos (no
      puede editarlos ni borrarlos) y consulta clientes. No toca el catálogo.
    - mixto: suma los permisos de almacen y de ventas.

    El rol genérico "empleado" que existía antes se migró a "mixto" (ver
    app/database/migraciones.py), que es el que conserva sus permisos.
    """
    ADMIN = "admin"
    ALMACEN = "almacen"
    VENTAS = "ventas"
    MIXTO = "mixto"


# Roles que no son admin: se identifican con su DNI al iniciar sesión.
ROLES_EMPLEADO = (RolUsuario.ALMACEN, RolUsuario.VENTAS, RolUsuario.MIXTO)

# Todos los roles válidos, como strings (para requerir_rol).
TODOS_LOS_ROLES = tuple(r.value for r in RolUsuario)


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    rol = Column(Enum(RolUsuario), nullable=False, default=RolUsuario.MIXTO)
    activo = Column(Boolean, nullable=False, default=True, server_default="1")

    # DNI del empleado: es lo que usa para iniciar sesión y lo que se registra
    # como "empleado" en cada movimiento (viaja en el token, el usuario no lo
    # escribe). Único; opcional solo para el admin, que también puede entrar con email.
    dni = Column(String(8), nullable=True, unique=True, index=True)
