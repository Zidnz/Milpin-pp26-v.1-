"""
env.py — Configuración de Alembic para MILPÍN AgTech.

Usa SQLAlchemy síncrono (psycopg2) para las migraciones aunque el runtime
de la app usa asyncpg. La URL se lee desde backend/.env y se convierte
automáticamente: postgresql+asyncpg → postgresql+psycopg2.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# ── Añadir backend/ al path para poder importar database y models ─────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Cargar .env ───────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# ── Importar Base y todos los modelos (para autogenerate) ─────────────────────
from database import Base  # noqa: E402
import models  # noqa: E402, F401  — registra todos los ORM en Base.metadata

# ── Config de Alembic ─────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ── Resolver URL de conexión: asyncpg → psycopg2 ──────────────────────────────
def get_sync_url() -> str:
    """
    Lee DATABASE_URL del entorno y convierte el driver a psycopg2 para uso
    síncrono de Alembic. Si la variable no está definida, usa la del alembic.ini.
    """
    url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    # asyncpg es el driver async del runtime; Alembic necesita el driver sync
    return url.replace("postgresql+asyncpg", "postgresql+psycopg2")


def run_migrations_offline() -> None:
    """
    Modo offline: genera SQL sin conexión a la BD.
    Útil para revisar las sentencias antes de aplicarlas.
    """
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # GeoAlchemy2: comparar tipos correctamente en autogenerate
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Modo online: aplica migraciones sobre la conexión activa.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
