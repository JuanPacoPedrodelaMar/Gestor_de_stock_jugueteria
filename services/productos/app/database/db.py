"""
Configuración de la base de datos.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# La URL de conexión se toma de una variable de entorno para no hardcodear
# rutas ni credenciales en el repo. Por defecto, SQLite en un volumen local
# (útil para desarrollo sin Docker). En docker-compose se sobreescribe para
# apuntar a /data/jugueteria.db, montado como volumen persistente.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite:///./data/jugueteria.db"
)

# connect_args solo aplica a SQLite (check_same_thread=False porque FastAPI
# puede usar la conexión desde distintos hilos/tareas asíncronas). Si en el
# futuro se usa Postgres u otro motor, este bloque se ignora.
connect_args = (
    {"check_same_thread": False}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {}
)

_ES_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
_EN_MEMORIA = ":memory:" in SQLALCHEMY_DATABASE_URL or SQLALCHEMY_DATABASE_URL in ("sqlite://", "sqlite:///")
_SQLITE_EN_ARCHIVO = _ES_SQLITE and not _EN_MEMORIA

# Pool de conexiones. Con el valor por defecto de SQLAlchemy (5 + 10 de desborde) 150
# pedidos simultáneos agotaban las conexiones ("QueuePool limit ... reached"); con 20 + 60
# se resolvieron todos (ver README, "Rendimiento"). Solo aplica a SQLite en archivo: los
# motores en memoria usan otro tipo de pool que no acepta estos parámetros.
_opciones_pool = (
    {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "60")),
    }
    if _SQLITE_EN_ARCHIVO
    else {}
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args, **_opciones_pool)

if _SQLITE_EN_ARCHIVO:

    @event.listens_for(engine, "connect")
    def _configurar_sqlite(conexion, _registro):
        """Ajustes de SQLite para varios hilos: lectores concurrentes y espera ante el candado de escritura."""
        cursor = conexion.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")    # los lectores no bloquean al escritor
        cursor.execute("PRAGMA busy_timeout=5000")   # espera hasta 5 s en vez de fallar con "database is locked"
        cursor.execute("PRAGMA synchronous=NORMAL")  # seguro con WAL; menos fsync por commit
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependencia de FastAPI: abre una sesión de base de datos por request
    y la cierra automáticamente al finalizar (incluso si hay una excepción).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
