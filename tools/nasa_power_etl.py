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


# =============================================================================
# Utilidades geoespaciales
# =============================================================================
def centroide_de_geom(geom_json: Optional[dict]) -> Optional[tuple[float, float]]:
    """
    Retorna (lat, lon) del centroide del GeoJSON Polygon de la parcela.

    GeoJSON usa el orden (lon, lat) en las coordenadas, pero los APIs climáticos
    y la función FAO-56 esperan (lat, lon). Shapely internaliza esto como
    (x=lon, y=lat), así que `centroid.x` es lon y `centroid.y` es lat.

    Retorna None si la parcela no tiene geometría válida.
    """
    if not geom_json:
        return None
    try:
        poly = shape(geom_json)
        if not poly.is_valid or poly.is_empty:
            return None
        c = poly.centroid
        return (float(c.y), float(c.x))  # (lat, lon)
    except Exception:
        return None


# =============================================================================
# NASA POWER — descarga + parsing
# =============================================================================
def construir_url(lat: float, lon: float, anio_inicio: int, anio_fin: int) -> str:
    """Arma la URL GET del endpoint Daily/Point de NASA POWER."""
    params = {
        "parameters": ",".join(nasa_settings.variables),
        "community":  nasa_settings.api_community,
        "longitude":  lon,
        "latitude":   lat,
        "start":      f"{anio_inicio}0101",
        "end":        f"{anio_fin}1231",
        "format":     "JSON",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{nasa_settings.api_url}?{query}"


def _limpiar_centinela(valor):
    """NASA POWER usa -999 como centinela de dato faltante."""
    if valor is None:
        return None
    return None if valor == -999 else valor


def parsear_respuesta_nasa(datos_json: dict) -> pd.DataFrame:
    """
    Convierte el JSON de NASA POWER a DataFrame con 7 columnas:
        fecha (YYYY-MM-DD), t_max, t_min, humedad_rel, viento, radiacion, lluvia.

    Imputación de NaN (post-conversión del centinela -999):
        - Continuas (T, HR, viento, radiación): interpolación lineal hasta
          3 días consecutivos. Gaps > 3 días se dejan como NaN (el caller
          debe decidir si los descarta o no).
        - Precipitación: se rellena con 0.0. NO se interpola. Interpolar
          creatively llenaría los días sin medición fiable con lluvia
          ficticia que contamina cualquier balance hídrico posterior.
    """
    params = datos_json["properties"]["parameter"]
    t_max_raw  = params["T2M_MAX"]
    t_min_raw  = params["T2M_MIN"]
    hum_raw    = params["RH2M"]
    viento_raw = params["WS2M"]
    rad_raw    = params["ALLSKY_SFC_SW_DWN"]
    lluvia_raw = params["PRECTOTCORR"]

    fechas = sorted(t_max_raw.keys())
    filas = [
        {
            "fecha":       datetime.strptime(f, "%Y%m%d").strftime("%Y-%m-%d"),
            "t_max":       _limpiar_centinela(t_max_raw.get(f)),
            "t_min":       _limpiar_centinela(t_min_raw.get(f)),
            "humedad_rel": _limpiar_centinela(hum_raw.get(f)),
            "viento":      _limpiar_centinela(viento_raw.get(f)),
            "radiacion":   _limpiar_centinela(rad_raw.get(f)),
            "lluvia":      _limpiar_centinela(lluvia_raw.get(f)),
        }
        for f in fechas
    ]
    df = pd.DataFrame(filas)

    # Imputación diferenciada
    continuas = ["t_max", "t_min", "humedad_rel", "viento", "radiacion"]
    for col in continuas:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].interpolate(method="linear", limit=3)

    df["lluvia"] = pd.to_numeric(df["lluvia"], errors="coerce").fillna(0.0)
    return df


async def descargar_clima(
    id_parcela: uuid.UUID,
    lat: float,
    lon: float,
    anio_inicio: int,
    anio_fin: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> Optional[dict]:
    """
    Descarga el JSON crudo de NASA POWER para una parcela. Reusa caché en disco
    si existe. El semáforo limita concurrencia para no gatillar rate limits.

    Cache key: `clima_{id_parcela}.json`. Si cambiás el período o las
    coordenadas de la parcela, invalidá manualmente borrando el archivo.
    """
    archivo = Path(nasa_settings.raw_dir) / f"clima_{id_parcela}.json"

    if archivo.exists():
        print(f"    [cache] {id_parcela} — {archivo.name}")
        with archivo.open("r", encoding="utf-8") as f:
            return json.load(f)

    archivo.parent.mkdir(parents=True, exist_ok=True)
    url = construir_url(lat, lon, anio_inicio, anio_fin)
    print(f"    [API]   {id_parcela} — GET NASA POWER...")

    async with sem:
        try:
            r = await client.get(url, timeout=nasa_settings.request_timeout_s)
            r.raise_for_status()
            datos = r.json()
        except httpx.HTTPStatusError as e:
            print(f"    ✗ HTTP {e.response.status_code} para {id_parcela}")
            return None
        except httpx.RequestError as e:
            print(f"    ✗ Red para {id_parcela}: {e}")
            return None

        with archivo.open("w", encoding="utf-8") as f:
            json.dump(datos, f)
        print(f"    ✓ {id_parcela} cacheado en {archivo.name}")

        # Pausa cortés — evita rate limit de NASA POWER
        await asyncio.sleep(nasa_settings.courtesy_sleep_s)
        return datos


# =============================================================================
# Validación de sanidad
# =============================================================================
def validar_et0(df: pd.DataFrame, id_parcela: uuid.UUID, nombre: str) -> None:
    """
    Emite alertas en stderr si ET0 está fuera de rangos plausibles para la
    región (Valle del Yaqui). No aborta el pipeline — es diagnóstico.
    """
    et0 = df["et0"].dropna()
    if et0.empty:
        print(f"    ⚠ {nombre}: ET0 vacía después del cálculo")
        return

    media    = et0.mean()
    p99      = et0.quantile(0.99)
    et0_max  = et0.max()
    anomalos = int((et0 > nasa_settings.et0_umbral_pico).sum())

    print(f"    ET0 — media: {media:5.2f} mm/día | máx: {et0_max:5.2f} | "
          f"P99: {p99:5.2f} | días>{nasa_settings.et0_umbral_pico}: {anomalos}")

    if p99 > nasa_settings.et0_umbral_pico:
        print(f"    ⚠ ANOMALÍA: P99 ET0 = {p99:.2f} excede umbral "
              f"({nasa_settings.et0_umbral_pico} mm/día). Probable ruido en "
              f"ALLSKY_SFC_SW_DWN. Revisar caché crudo.")

    if not (nasa_settings.et0_media_min < media < nasa_settings.et0_media_max):
        print(f"    ⚠ SESGO: ET0 media ({media:.2f}) fuera de rango "
              f"({nasa_settings.et0_media_min}–{nasa_settings.et0_media_max} "
              f"mm/día) esperado para Valle del Yaqui.")


# =============================================================================
# Persistencia
# =============================================================================
async def bulk_upsert_clima(
    session,
    id_parcela: uuid.UUID,
    df: pd.DataFrame,
) -> int:
    """
    Inserta las filas climáticas en `clima_diario` con on-conflict-do-nothing
    sobre la PK compuesta (id_parcela, fecha). Es idempotente: re-correr el
    ETL no duplica filas.

    Usa el dialecto específico según la BD detectada al arranque
    (IS_SQLITE viene de backend/database.py).
    """
    if df.empty:
        return 0

    registros = []
    for _, row in df.iterrows():
        registros.append({
            "id_parcela":  id_parcela,
            "fecha":       pd.to_datetime(row["fecha"]).date(),
            "t_max":       _to_float_or_none(row.get("t_max")),
            "t_min":       _to_float_or_none(row.get("t_min")),
            "humedad_rel": _to_float_or_none(row.get("humedad_rel")),
            "viento":      _to_float_or_none(row.get("viento")),
            "radiacion":   _to_float_or_none(row.get("radiacion")),
            "lluvia":      _to_float_or_none(row.get("lluvia")),
            "et0":         _to_float_or_none(row.get("et0")),
        })

    if IS_SQLITE:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

    stmt = dialect_insert(ClimaDiario).values(registros)
    stmt = stmt.on_conflict_do_nothing(index_elements=["id_parcela", "fecha"])
    await session.execute(stmt)
    return len(registros)


def _to_float_or_none(v):
    """pd.NA y NaN → None para que SQLAlchemy los serialice como NULL."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


# =============================================================================
# Pipeline por parcela
# =============================================================================
async def procesar_parcela(
    parcela: Parcela,
    anio_inicio: int,
    anio_fin: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> None:
    nombre = parcela.nombre_parcela or str(parcela.id_parcela)
    print(f"\n  [{parcela.id_parcela}] {nombre}")

    coords = centroide_de_geom(parcela.geom)
    if coords is None:
        print(f"  ✗ Sin geometría válida — skip")
        return
    lat, lon = coords
    print(f"  Centroide: lat={lat:.4f}, lon={lon:.4f}")

    datos = await descargar_clima(
        parcela.id_parcela, lat, lon, anio_inicio, anio_fin, client, sem,
    )
    if datos is None:
        return

    try:
        df = parsear_respuesta_nasa(datos)
    except KeyError as e:
        print(f"  ✗ JSON de NASA no tiene la variable {e}. Skip.")
        return

    print(f"    Parseados: {len(df)} días")

    # ET0 vectorizada — misma implementación FAO-56 que el API escalar
    df["et0"] = calcular_eto_penman_monteith_serie(df, latitud=lat)

    validar_et0(df, parcela.id_parcela, nombre)

    # Escritura en BD — cada parcela en su propia sesión/transacción para que
    # un fallo en una no tire el commit de las demás
    async with AsyncSessionLocal() as session:
        try:
            n = await bulk_upsert_clima(session, parcela.id_parcela, df)
            await session.commit()
            print(f"    ✓ {n} filas upserted en clima_diario")
        except Exception as e:
            await session.rollback()
            print(f"    ✗ Error persistiendo {parcela.id_parcela}: {e}")


# =============================================================================
# Pipeline principal
# =============================================================================
async def run_etl(
    anio_inicio: int,
    anio_fin: int,
    limit: Optional[int] = None,
    parcela_id: Optional[uuid.UUID] = None,
    max_concurrent: int = 3,
) -> None:
    print("=" * 64)
    print("NASA POWER ETL — MILPÍN AgTech v2.0")
    print(f"Período       : {anio_inicio}–{anio_fin}")
    print(f"Variables     : {', '.join(nasa_settings.variables)}")
    print(f"Cache crudo   : {nasa_settings.raw_dir}")
    print(f"BD            : {'SQLite (dev)' if IS_SQLITE else 'PostgreSQL'}")
    print(f"Concurrencia  : {max_concurrent} requests simultáneos")
    print("=" * 64)

    # Cargar parcelas activas con geometría
    async with AsyncSessionLocal() as session:
        q = select(Parcela).where(Parcela.activo == True)  # noqa: E712
        if parcela_id:
            q = q.where(Parcela.id_parcela == parcela_id)
        if limit:
            q = q.limit(limit)
        result = await session.execute(q)
        parcelas = list(result.scalars().all())

    if not parcelas:
        print("No hay parcelas activas que procesar.")
        return

    print(f"\nProcesando {len(parcelas)} parcela(s)...")

    sem = asyncio.Semaphore(max_concurrent)
    async with httpx.AsyncClient() as client:
        tareas = [
            procesar_parcela(p, anio_inicio, anio_fin, client, sem)
            for p in parcelas
        ]
        await asyncio.gather(*tareas)

    print("\n" + "=" * 64)
    print("✓ ETL completado")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NASA POWER ETL para MILPÍN")
    p.add_argument(
        "--limit", type=int, default=None,
        help="Limitar cantidad de parcelas procesadas (útil para smoke tests)."
    )
    p.add_argument(
        "--parcela", type=str, default=None,
        help="UUID de una parcela específica. Si se pasa, ignora --limit."
    )
    p.add_argument(
        "--desde", type=int, default=None,
        help=f"Año inicio. Default: {nasa_settings.anio_inicio}"
    )
    p.add_argument(
        "--hasta", type=int, default=None,
        help=f"Año fin. Default: {nasa_settings.anio_fin}"
    )
    p.add_argument(
        "--concurrencia", type=int, default=3,
        help="Requests concurrentes contra NASA POWER. Default: 3."
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    anio_inicio = args.desde if args.desde else nasa_settings.anio_inicio
    anio_fin    = args.hasta if args.hasta else nasa_settings.anio_fin
    parcela_id  = uuid.UUID(args.parcela) if args.parcela else None

    asyncio.run(run_etl(
        anio_inicio=anio_inicio,
        anio_fin=anio_fin,
        limit=args.limit,
        parcela_id=parcela_id,
        max_concurrent=args.concurrencia,
    ))


if __name__ == "__main__":
    main()
