"""
tools/nasa_power_etl.py — Pipeline ETL de datos climáticos NASA POWER.

Descarga series climáticas históricas (desde 1981) de NASA POWER para cada
parcela activa del sistema MILPÍN y calcula ET0 por Penman-Monteith FAO-56.

Arquitectura:
    [1] PostgreSQL (parcelas)
            ↓   SELECT parcelas activas con geom != NULL
    [2] Shapely (centroide GeoJSON → lat, lon)
            ↓
    [3] httpx async (NASA POWER API, comunidad AG)
            ↓   cache JSON crudo en data/raw/nasa_power/
    [4] pandas (parse + imputación de NaN)
            ↓
    [5] balance_hidrico.calcular_eto_penman_monteith_serie (mismo motor FAO-56
        que el API escalar — una sola fuente de verdad)
            ↓
    [6] Validación de sanidad (umbrales Valle del Yaqui)
            ↓
    [7] PostgreSQL (clima_diario) con INSERT ... ON CONFLICT DO NOTHING

Uso CLI:
    cd backend && python -m tools.nasa_power_etl              # todas las parcelas
    python -m tools.nasa_power_etl --limit 1                  # solo 1 parcela (smoke test)
    python -m tools.nasa_power_etl --parcela <uuid>           # una parcela específica
    python -m tools.nasa_power_etl --desde 2020 --hasta 2023  # override período

Notas de diseño:
    - Se ejecuta como CLI, no como endpoint FastAPI: el pipeline puede tardar
      minutos u horas, no queremos comprometer el event loop de uvicorn.
    - La escritura usa la misma AsyncSessionLocal del backend (un solo pool,
      un solo driver asyncpg/aiosqlite).
    - El caché se invalida manualmente: si cambiás la geometría de una parcela,
      borrá el JSON correspondiente para forzar re-descarga.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from shapely.geometry import shape
from sqlalchemy import select

# GeoAlchemy2: convierte WKBElement → shapely (disponible post-migración PostGIS)
try:
    from geoalchemy2.shape import to_shape as _wkb_to_shape
    _GEOALCHEMY2_OK = True
except ImportError:
    _GEOALCHEMY2_OK = False

# ── Import de módulos del backend ─────────────────────────────────────────────
# Este script se ejecuta desde la raíz del repo; agregamos backend/ al sys.path
# para que los imports funcionen tal como lo hace main.py al arrancar uvicorn.
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# database.py hace `load_dotenv()` sin path explícito, lo que lee `.env` del CWD.
# Al correr este ETL desde la raíz del repo, `.env` no se encuentra y cae al
# default `postgres@localhost`. Cargamos `backend/.env` antes de importar
# database.py para garantizar que DATABASE_URL se resuelva correctamente.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_DIR / ".env")

from database import AsyncSessionLocal, IS_SQLITE  # noqa: E402
from models import ClimaDiario, Parcela  # noqa: E402
from core.balance_hidrico import calcular_eto_penman_monteith_serie  # noqa: E402
from settings import nasa_settings  # noqa: E402


# ======================================================================