"""
conftest.py - Fixtures para tests de MILPIN AgTech v2.0

Estrategia: SQLite + aiosqlite (no mock, BD real).
Los patches de tipos PG-exclusivos se aplican en _patch_metadata_for_sqlite()
llamada dentro del fixture, porque pytest puede usar el .pyc cacheado para
el modulo pero si ejecuta el codigo de los fixtures en runtime.
"""

import os
import sys
import uuid
from datetime import date

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TEST_DB_URL = "sqlite+aiosqlite://"
os.environ["DATABASE_URL"] = _TEST_DB_URL

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import models  # noqa: E402
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402


def _patch_metadata_for_sqlite():
    """Adapta Base.metadata para SQLite: JSONB->JSON, Geometry->Text, quita gen_random_uuid."""
    from sqlalchemy.dialects.postgresql import JSONB
    from geoalchemy2 import Geometry

    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            if isinstance(col.type, Geometry):
                col.type = Text()
            if col.server_default is not None:
                try:
                    if "gen_random_uuid" in str(col.server_default.arg):
                        col.server_default = None
                except Exception:
                    pass


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    _patch_metadata_for_sqlite()
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def seeded(db_session: AsyncSession):
    id_usuario = uuid.uuid4()
    id_cultivo = uuid.uuid4()
    id_parcela = uuid.uuid4()
    hoy = date.today()

    usuario = models.Usuario(
        id_usuario=id_usuario,
        nombre_completo="Test Agricultor",
        email=f"test_{id_usuario}@milpin-test.com",
        modulo_dr041="Modulo 3",
    )
    cultivo = models.CultivoCatalogo(
        id_cultivo=id_cultivo,
        nombre_comun="Maiz",
        nombre_cientifico="Zea mays",
        kc_inicial=0.30,
        kc_medio=1.20,
        kc_final=0.60,
        ky_total=1.25,
        dias_etapa_inicial=25,
        dias_etapa_desarrollo=40,
        dias_etapa_media=45,
        dias_etapa_final=30,
        rendimiento_potencial_ton=10.0,
    )
    parcela = models.Parcela(
        id_parcela=id_parcela,
        id_usuario=id_usuario,
        id_cultivo_actual=id_cultivo,
        nombre_parcela="Lote Test Norte",
        geom=None,
        area_ha=5.0,
        tipo_suelo="franco-arcilloso",
        profundidad_raiz_cm=60,
        capacidad_campo=0.34,
        punto_marchitez=0.18,
        sistema_riego="gravedad",
    )
    clima_vals = {
        "t_max": 38.0,
        "t_min": 22.0,
        "humedad_rel": 35.0,
        "viento": 2.5,
        "radiacion": 22.0,
        "lluvia": 0.0,
    }
    clima = models.ClimaDiario(
        id_parcela=id_parcela,
        fecha=hoy,
        **clima_vals,
    )
    db_session.add_all([usuario, cultivo, parcela, clima])
    await db_session.commit()

    return {
        "id_usuario": id_usuario,
        "id_cultivo": id_cultivo,
        "id_parcela": id_parcela,
        "fecha": hoy,
        "clima": clima_vals,
    }
