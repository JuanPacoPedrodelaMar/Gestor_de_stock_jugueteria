"""
Configuración de la base de datos del servicio de Clientes.

Base propia e independiente (cada servicio es dueño de sus datos): ningún otro
servicio lee estas tablas; Movimientos consulta a Clientes solo por HTTP
(ver services/movimientos/app/clients/clientes_client.py).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/clientes.db")

connect_args = (
    {"check_same_thread": False}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependencia de FastAPI: abre una sesión por request y la cierra al finalizar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
