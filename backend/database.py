"""
database.py — Configuración del motor de base de datos para MILPÍN AgTech v2.0

Motor: PostgreSQL 15+ con SQLAlchemy 2.0 async.
La URL de conexión se lee desde la variable de entorno DATABASE_URL.

Configuración recomendada en .env:
    DATABASE_URL=postgresql+asyncpg://milpin:milpin_pass@localhost:5432/milpin_mvp

Para desarrollo rápido sin PostgreSQL (SQLite):
    DATABASE_URL=sqlite+aiosqlite:///./milpin_dev.db
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

# ── URL de conexión ──────────────────────────────────────────────────────────
# Cambia el valor por defecto a tu configuración local si no usas .env
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://milpin:milpin_pass@localhost:5432/milpin_mvp",
)

# Detectar si se está usando SQLite (para desarrollo sin PostgreSQL)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# ── Motor async ──────────────────────────────────────────────────────────────
engine_kwargs: dict = {
    "echo": False,       # Poner True para ver SQL en consola durante debug
    "pool_pre_ping": True,
}

if not IS_SQLITE:
    # Pool de conexiones para PostgreSQL (no aplica a SQLite)
    engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
    })

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

# ── Factory de sesiones async ─────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ── Base declarativa para los modelos ORM ────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Dependency para inyectar sesión en endpoints FastAPI ─────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency de FastAPI para obtener una sesión de base de datos.

    Uso en un endpoint:
        @router.get("/endpoint")
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(MiModelo))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Función para crear todas las tablas (usada en init_db.py y tests) ─────────
async def create_all_tables() -> None:
    """Crea todas las tablas definidas en models.py si no existen."""
    # Importar aquí para evitar importaciones circulares
    import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """Elimina todas las tablas. USAR SOLO EN DESARROLLO / TESTS."""
    import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
