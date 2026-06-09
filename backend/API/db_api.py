"""
db_api.py — Endpoints CRUD para las tablas del MVP de MILPÍN AgTech v2.0

Endpoints disponibles:
    POST   /api/usuarios                        → Crear usuario
    GET    /api/usuarios/{id}                   → Obtener usuario con sus parcelas

    GET    /api/cultivos                        → Listar catálogo de cultivos
    GET    /api/cultivos/{id}                   → Obtener cultivo por ID

    POST   /api/parcelas                        → Crear parcela
    GET    /api/parcelas                        → Listar todas las parcelas activas
    GET    /api/parcelas/{id}                   → Obtener parcela con historial reciente
    GET    /api/parcelas/{id}/kpi               → KPI de consumo vs baseline DR-041
    GET    /api/parcelas/{id}/forecast          → Proyección FAO-56 a N días con Ridge ETo

    POST   /api/riego                           → Registrar evento de riego
    GET    /api/riego/parcela/{id}              → Historial de riego de una parcela

    POST   /api/recomendaciones                 → Guardar recomendación del motor FAO-56
    GET    /api/recomendaciones/{id}            → Obtener recomendación
    PATCH  /api/recomendaciones/{id}/feedback   → Registrar feedback del agricultor

    POST   /api/costos                          → Registrar costos de un ciclo agrícola
    GET    /api/costos/parcela/{id}             → Costos por ciclo de una parcela
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from security import (
    TokenOut,
    create_access_token,
    get_current_admin,
    get_current_user,
    get_optional_user,
    hash_password,
    verify_password,
)
from core.balance_hidrico import obtener_curva_kc
from database import get_db
from models import CostoCiclo, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion, Usuario

# GeoAlchemy2: conversión WKBElement ↔ dict GeoJSON
try:
    from geoalchemy2.shape import from_shape, to_shape
    from shapely.geometry import shape as shapely_shape
    _POSTGIS_OK = True
except ImportError:
    _POSTGIS_OK = False


def _geom_from_geojson(geom_dict: Optional[dict]):
    """Convierte un dict GeoJSON a WKBElement de GeoAlchemy2 (SRID 4326).
    Devuelve None si el dict es None o GeoAlchemy2 no está disponible."""
    if geom_dict is None or not _POSTGIS_OK:
        return None
    try:
        return from_shape(shapely_shape(geom_dict), srid=4326)
    except Exception:
        return None


def _geom_to_geojson(geom) -> Optional[dict]:
    """Convierte WKBElement de GeoAlchemy2 a dict GeoJSON.
    Devuelve None si la geometría es None o hay error."""
    if geom is None or not _POSTGIS_OK:
        return None
    try:
        return json.loads(to_shape(geom).geojson)
    except Exception:
        return None

router = APIRouter(tags=["Base de Datos MVP"])

# ── ETL background helper ─────────────────────────────────────────────────────

# Ruta al raíz del repositorio: backend/API/db_api.py → ../../
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


async def _etl_parcela_background(parcela_id: uuid.UUID) -> None:
    """
    Dispara el ETL de NASA POWER para una parcela recién creada.

    Corre como BackgroundTask de FastAPI: la respuesta HTTP ya fue enviada
    antes de que esta función arranque, así que el usuario no espera.

    Descarga solo los últimos 5 años para que la primera carga sea rápida
    (una sola request HTTP a NASA POWER, ~5-30 s según su latencia).
    Para datos históricos completos, corre manualmente desde la raíz del repo:
        .\backend\venv\Scripts\python.exe tools\nasa_power_etl.py --parcela <uuid>
    """
    anio_desde = datetime.now().year - 4  # últimos 5 años
    anio_hasta = datetime.now().year

    # Usamos ruta directa al script porque tools/ no tiene __init__.py
    # y `python -m tools.nasa_power_etl` fallaría sin él.
    etl_script = _REPO_ROOT / "tools" / "nasa_power_etl.py"
    cmd = [
        sys.executable, str(etl_script),
        "--parcela", str(parcela_id),
        "--desde", str(anio_desde),
        "--hasta", str(anio_hasta),
    ]
    print(f"[ETL] Iniciando descarga NASA POWER para parcela {parcela_id} "
          f"({anio_desde}–{anio_hasta})...")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            print(f"[ETL] ✓ Parcela {parcela_id} — clima descargado.")
        else:
            print(f"[ETL] ✗ Parcela {parcela_id} — error (rc={proc.returncode}):\n"
                  f"{stdout.decode(errors='replace')[:600]}")
    except Exception as exc:
        print(f"[ETL] ✗ Parcela {parcela_id} — excepción: {exc}")


# ── Schemas Pydantic (request / response) ─────────────────────────────────────

class UsuarioCreate(BaseModel):
    nombre_completo: str
    email: str
    password: str = Field(..., min_length=6, description="Contraseña en texto plano (se hashea en servidor).")
    telefono: Optional[str] = None
    modulo_dr041: Optional[str] = None
    rol: str = "agricultor"

class UsuarioOut(BaseModel):
    id_usuario: uuid.UUID
    nombre_completo: str
    email: str
    modulo_dr041: Optional[str]
    activo: bool
    rol: str = "agricultor"
    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    password: Optional[str] = None


class RegisterRequest(BaseModel):
    nombre_completo: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=6)
    telefono: Optional[str] = None
    modulo_dr041: Optional[str] = None


class CultivoOut(BaseModel):
    id_cultivo: uuid.UUID
    nombre_comun: str
    nombre_cientifico: Optional[str]
    kc_inicial: float
    kc_medio: float
    kc_final: float
    ky_total: float
    dias_etapa_inicial: int
    dias_etapa_desarrollo: int
    dias_etapa_media: int
    dias_etapa_final: int
    rendimiento_potencial_ton: Optional[float]
    model_config = {"from_attributes": True}


class ParcelaCreate(BaseModel):
    id_cultivo_actual: Optional[uuid.UUID] = None
    nombre_parcela: Optional[str] = None
    geom: Optional[dict] = Field(None, description="GeoJSON Polygon del lote")
    area_ha: Optional[float] = None
    tipo_suelo: Optional[str] = None
    conductividad_electrica: Optional[float] = None
    profundidad_raiz_cm: Optional[int] = None
    capacidad_campo: Optional[float] = Field(None, description="m³/m³ — ej: 0.34")
    punto_marchitez: Optional[float] = Field(None, description="m³/m³ — ej: 0.18")
    sistema_riego: Optional[str] = None

class ParcelaOut(BaseModel):
    id_parcela: uuid.UUID
    id_usuario: uuid.UUID
    nombre_parcela: Optional[str]
    geom_geojson: Optional[dict] = None   # GeoJSON Polygon serializado desde PostGIS
    area_ha: Optional[float]
    tipo_suelo: Optional[str]
    conductividad_electrica: Optional[float]
    profundidad_raiz_cm: Optional[int]
    capacidad_campo: Optional[float]
    punto_marchitez: Optional[float]
    agua_disponible_mm: Optional[float]
    sistema_riego: Optional[str]
    activo: bool
    cultivo_nombre: Optional[str] = None
    model_config = {"from_attributes": True}


def _to_parcela_out(p: Parcela) -> ParcelaOut:
    """Serializa un ORM Parcela a ParcelaOut, convirtiendo geom WKB → GeoJSON dict."""
    out = ParcelaOut.model_validate(p)
    out.geom_geojson = _geom_to_geojson(p.geom)
    if p.cultivo_actual is not None:
        out.cultivo_nombre = p.cultivo_actual.nombre_comun
    return out


class RiegoCreate(BaseModel):
    id_parcela: uuid.UUID
    id_recomendacion: Optional[uuid.UUID] = None
    fecha_riego: date
    # ciclo_agricola se autocalcula desde fecha_riego si no se envía.
    ciclo_agricola: Optional[str] = None
    volumen_m3_ha: Optional[float] = None
    lamina_mm: Optional[float] = None
    duracion_horas: Optional[float] = None
    metodo_riego: Optional[str] = None
    origen_decision: str = "manual"
    costo_energia_mxn: Optional[float] = None
    observaciones: Optional[str] = None

class RiegoOut(BaseModel):
    id_riego: uuid.UUID
    id_parcela: uuid.UUID
    id_recomendacion: Optional[uuid.UUID]
    fecha_riego: date
    ciclo_agricola: Optional[str]
    ciclo_vol_target_m3_ha: Optional[float]
    volumen_m3_ha: Optional[float]
    lamina_mm: Optional[float]
    metodo_riego: Optional[str]
    origen_decision: Optional[str]
    costo_energia_mxn: Optional[float]
    observaciones: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class RecomendacionCreate(BaseModel):
    id_parcela: uuid.UUID
    id_cultivo: Optional[uuid.UUID] = None
    fecha_riego_sugerida: Optional[date] = None
    lamina_recomendada_mm: Optional[float] = None
    eto_referencia: Optional[float] = None
    etc_calculada: Optional[float] = None
    deficit_acumulado_mm: Optional[float] = None
    dias_sin_riego: Optional[int] = None
    nivel_urgencia: Optional[str] = None
    algoritmo_version: str = "fao56-mvp-v1.0"
    parametros_json: Optional[dict] = None

class RecomendacionOut(BaseModel):
    id_recomendacion: uuid.UUID
    id_parcela: uuid.UUID
    id_cultivo: Optional[uuid.UUID]
    fecha_generacion: datetime
    fecha_riego_sugerida: Optional[date]
    lamina_recomendada_mm: Optional[float]
    eto_referencia: Optional[float]
    etc_calculada: Optional[float]
    deficit_acumulado_mm: Optional[float]
    dias_sin_riego: Optional[int]
    nivel_urgencia: Optional[str]
    algoritmo_version: Optional[str]
    aceptada: str
    lamina_ejecutada_mm: Optional[float]
    parametros_json: Optional[dict]
    model_config = {"from_attributes": True}

class FeedbackRecomendacion(BaseModel):
    aceptada: str = Field(..., pattern="^(aceptada|modificada|ignorada)$")
    lamina_ejecutada_mm: Optional[float] = None
    notas: Optional[str] = None


# ── Endpoints: usuarios ───────────────────────────────────────────────────────

@router.post("/usuarios", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
async def crear_usuario(
    data: UsuarioCreate,
    db: AsyncSession = Depends(get_db),
    _admin: Usuario = Depends(get_current_admin),
):
    """Crea un usuario (solo admins). Para auto-registro usar POST /auth/register."""
    existe = await db.execute(select(Usuario).where(Usuario.email == data.email))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Email '{data.email}' ya está registrado.")
    payload = data.model_dump()
    plain_pw = payload.pop("password")
    usuario = Usuario(id_usuario=uuid.uuid4(), hashed_password=hash_password(plain_pw), **payload)
    db.add(usuario)
    await db.flush()
    return usuario


@router.get("/usuarios", response_model=list[UsuarioOut])
async def listar_usuarios(
    db: AsyncSession = Depends(get_db),
):
    """Lista usuarios activos (público — requerido para la pantalla de login demo)."""
    resultado = await db.execute(
        select(Usuario)
        .where(Usuario.activo == True)
        .order_by(Usuario.nombre_completo)
    )
    return resultado.scalars().all()


@router.get("/usuarios/{id_usuario}", response_model=UsuarioOut)
async def obtener_usuario(id_usuario: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.id_usuario == id_usuario))
    usuario = resultado.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return usuario


class NombreUpdate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120, strip_whitespace=True)


@router.patch("/usuarios/{id_usuario}/nombre", response_model=UsuarioOut)
async def actualizar_nombre_usuario(
    id_usuario: uuid.UUID,
    data: NombreUpdate,
    db: AsyncSession = Depends(get_db),
):
    resultado = await db.execute(select(Usuario).where(Usuario.id_usuario == id_usuario))
    usuario = resultado.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    usuario.nombre_completo = data.nombre
    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.post("/auth/login", response_model=TokenOut)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Autentica al usuario. Si se envía password, se valida contra el hash.
    Si no se envía password (flujo dataset-demo), se permite el acceso
    siempre que el usuario exista y esté activo (CLAUDE.md §5.7).
    """
    email = data.email.strip().lower()
    resultado = await db.execute(
        select(Usuario).where(func.lower(Usuario.email) == email)
    )
    usuario = resultado.scalar_one_or_none()
    if not usuario or not usuario.activo:
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    if data.password:
        if not usuario.hashed_password or not verify_password(data.password, usuario.hashed_password):
            raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    return TokenOut(
        access_token=create_access_token(usuario.id_usuario, usuario.rol),
        id_usuario=usuario.id_usuario,
        nombre_completo=usuario.nombre_completo,
        email=usuario.email,
        rol=usuario.rol,
    )


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Registro público: crea un nuevo usuario con contraseña y retorna el JWT.

    El rol siempre es 'agricultor'. Para crear admins usar POST /api/usuarios
    con un token de admin.
    """
    email = data.email.strip().lower()
    existe = await db.execute(select(Usuario).where(func.lower(Usuario.email) == email))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"El email '{email}' ya está registrado.")

    usuario = Usuario(
        id_usuario=uuid.uuid4(),
        nombre_completo=data.nombre_completo.strip(),
        email=email,
        telefono=data.telefono,
        modulo_dr041=data.modulo_dr041,
        rol="agricultor",
        hashed_password=hash_password(data.password),
    )
    db.add(usuario)
    await db.flush()

    return TokenOut(
        access_token=create_access_token(usuario.id_usuario, usuario.rol),
        id_usuario=usuario.id_usuario,
        nombre_completo=usuario.nombre_completo,
        email=usuario.email,
        rol=usuario.rol,
    )


# ── Endpoints: cultivos_catalogo ──────────────────────────────────────────────

@router.get("/cultivos", response_model=list[CultivoOut])
async def listar_cultivos(db: AsyncSession = Depends(get_db)):
    """Lista todos los cultivos del catálogo FAO-56."""
    resultado = await db.execute(select(CultivoCatalogo).order_by(CultivoCatalogo.nombre_comun))
    return resultado.scalars().all()


@router.get("/cultivos/{id_cultivo}", response_model=CultivoOut)
async def obtener_cultivo(id_cultivo: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(
        select(CultivoCatalogo).where(CultivoCatalogo.id_cultivo == id_cultivo)
    )
    cultivo = resultado.scalar_one_or_none()
    if not cultivo:
        raise HTTPException(status_code=404, detail="Cultivo no encontrado en el catálogo.")
    return cultivo


# ── Endpoints: parcelas ───────────────────────────────────────────────────────

@router.get("/parcelas", response_model=list[ParcelaOut])
async def listar_parcelas(
    id_usuario: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[Usuario] = Depends(get_optional_user),
):
    """Lista parcelas activas.

    - Con JWT de agricultor: solo devuelve sus propias parcelas.
    - Con JWT de admin: devuelve todas (filtrable con ?id_usuario=).
    - Sin JWT: retorna todas (backward compat con Leaflet map).
    """
    stmt = (
        select(Parcela)
        .options(selectinload(Parcela.cultivo_actual))
        .where(Parcela.activo == True)
        .order_by(Parcela.nombre_parcela)
    )
    if current_user is not None and current_user.rol != "admin":
        stmt = stmt.where(Parcela.id_usuario == current_user.id_usuario)
    elif id_usuario is not None:
        stmt = stmt.where(Parcela.id_usuario == id_usuario)
    resultado = await db.execute(stmt)
    return [_to_parcela_out(p) for p in resultado.scalars().all()]


@router.get("/parcelas/geojson", response_model=None)
async def parcelas_geojson(
    id_usuario: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna todas las parcelas activas como GeoJSON FeatureCollection.

    Diseñado para consumo directo por Leaflet en map_engine.js:
        L.geoJSON(await fetch('/api/parcelas/geojson').then(r => r.json()))

    Incluye ndvi estimado derivado del déficit acumulado (recomendaciones más
    reciente por parcela) y la conductividad eléctrica edáfica:
        ndvi = 0.80 - deficit_acumulado_mm / 250 - MAX(0, CE - 4) * 0.06
    Rango forzado a [0.10, 0.90]. Parcelas sin recomendación asumen déficit=40 mm.
    """
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type',     'Feature',
                    'geometry', ST_AsGeoJSON(p.geom)::json,
                    'properties', json_build_object(
                        'id_parcela',         p.id_parcela::text,
                        'nombre',             COALESCE(p.nombre_parcela, 'Sin nombre'),
                        'cultivo',            c.nombre_comun,
                        'area_ha',            p.area_ha,
                        'tipo_suelo',         p.tipo_suelo,
                        'sistema_riego',      p.sistema_riego,

                        -- NDVI proxy: déficit hídrico + salinidad edáfica
                        -- Parcelas sin recomendación previa → déficit asumido 40 mm
                        'ndvi', GREATEST(0.10, LEAST(0.90,
                            0.80
                            - COALESCE(r.deficit_acumulado_mm, 40.0) / 250.0
                            - GREATEST(0.0,
                                COALESCE(p.conductividad_electrica, 2.0) - 4.0
                              ) * 0.06
                        )),

                        'deficit_hidrico',    ROUND(COALESCE(r.deficit_acumulado_mm, 0)::numeric, 1),
                        'dias_sin_riego',     r.dias_sin_riego,
                        'nivel_urgencia',     r.nivel_urgencia,
                        'consumo_ciclo_m3ha', CASE
                            WHEN r.etc_calculada IS NOT NULL
                            THEN ROUND((r.etc_calculada * 10)::numeric, 0)::int
                            ELSE NULL
                        END
                    )
                )
            ) FILTER (WHERE p.geom IS NOT NULL), '[]'::json)
        ) AS fc
        FROM parcelas p
        LEFT JOIN cultivos_catalogo c
               ON c.id_cultivo = p.id_cultivo_actual
        -- Última recomendación por parcela (LATERAL evita subquery correlacionada)
        LEFT JOIN LATERAL (
            SELECT deficit_acumulado_mm,
                   dias_sin_riego,
                   nivel_urgencia,
                   etc_calculada
            FROM   recomendaciones
            WHERE  id_parcela = p.id_parcela
            ORDER  BY fecha_generacion DESC
            LIMIT  1
        ) r ON true
        WHERE p.activo = true
          AND (CAST(:id_usuario AS uuid) IS NULL OR p.id_usuario = CAST(:id_usuario AS uuid));
    """)
    result = await db.execute(sql, {"id_usuario": str(id_usuario) if id_usuario else None})
    return result.scalar_one()


_MILPIN_VOL_TARGET_M3_HA = 6_000.0
"""Volumen objetivo MILPÍN por ciclo (m³/ha). KPI: reducir 25% vs. baseline
DR-041 de 8,000 m³/ha/ciclo. Se persiste en historial_riego.ciclo_vol_target_m3_ha
para que Power BI y el detector de anomalías tengan el target en cada fila."""


def _ciclo_agricola(fecha: date) -> str:
    """Infiere el ciclo agrícola del Valle del Yaqui (DR-041) desde una fecha.

    Convención DR-041:
        OI (Otoño-Invierno): oct–mar → el año del label es el de cierre (marzo).
            Oct–Dic YYYY  →  OI-{YYYY+1}
            Ene–Mar YYYY  →  OI-{YYYY}
        PV (Primavera-Verano): abr–sep → año del período.
            Abr–Sep YYYY  →  PV-{YYYY}
    """
    m = fecha.month
    if m >= 10:
        return f"OI-{fecha.year + 1}"
    elif m <= 3:
        return f"OI-{fecha.year}"
    return f"PV-{fecha.year}"


def _suelo_franco_arcilloso() -> tuple[float, float]:
    """Genera CC y PMP con variación realista para suelo franco-arcilloso
    del Valle del Yaqui, Sonora.

    Rangos basados en FAO-56 Annex 5 y Hillel (1998) para Loam / Clay-Loam:
        CC:  0.27 – 0.42 m³/m³  (µ = 0.34, σ = 0.025)
        PMP: CC - diferencia     (diferencia µ = 0.16, σ = 0.015)
    Restricción dura: CC − PMP ≥ 0.08 (agua disponible mínima viable).

    Returns: (capacidad_campo, punto_marchitez) en m³/m³, 4 decimales.
    """
    cc = random.gauss(0.34, 0.025)
    cc = round(max(0.27, min(0.42, cc)), 4)

    diff = random.gauss(0.16, 0.015)
    diff = max(0.08, min(0.22, diff))

    pmp = round(max(0.10, cc - diff), 4)
    return cc, pmp


@router.post("/parcelas", response_model=ParcelaOut, status_code=status.HTTP_201_CREATED)
async def crear_parcela(
    data: ParcelaCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Registra un nuevo lote de cultivo. El dueño es el usuario autenticado (JWT).

    Tras crear la parcela, dispara automáticamente el ETL de NASA POWER como
    tarea en background para descargar los datos climáticos de los últimos 5
    años. La respuesta se devuelve inmediatamente; el ETL corre en paralelo.
    """
    payload = data.model_dump()
    payload["id_usuario"] = current_user.id_usuario
    # Separar geom: el dict GeoJSON no se puede pasar directamente al ORM,
    # hay que convertirlo a WKBElement de GeoAlchemy2.
    geom_dict = payload.pop("geom", None)
    geom_wkb = _geom_from_geojson(geom_dict)

    # Si el usuario no envió datos edáficos, generar valores realistas para
    # suelo franco-arcilloso del Valle del Yaqui en lugar de dejar NULL.
    # NULL rompe el cálculo FAO-56 silenciosamente (usa fallbacks hardcoded).
    if payload.get("capacidad_campo") is None or payload.get("punto_marchitez") is None:
        cc_gen, pmp_gen = _suelo_franco_arcilloso()
        if payload.get("capacidad_campo") is None:
            payload["capacidad_campo"] = cc_gen
        if payload.get("punto_marchitez") is None:
            payload["punto_marchitez"] = pmp_gen

    parcela = Parcela(id_parcela=uuid.uuid4(), geom=geom_wkb, **payload)
    db.add(parcela)
    await db.flush()

    # Si vino con geom, recalcular area_ha desde la geometría real
    if geom_wkb is not None:
        await db.execute(
            text(
                "UPDATE parcelas SET area_ha = ROUND((ST_Area(geom::geography)/10000.0)::numeric, 4) "
                "WHERE id_parcela = :pid"
            ),
            {"pid": str(parcela.id_parcela)},
        )
        await db.refresh(parcela)

    # Disparar ETL en background — solo si la parcela tiene geometría válida
    # (sin coordenadas no hay centroide para llamar a NASA POWER)
    if geom_wkb is not None:
        background_tasks.add_task(_etl_parcela_background, parcela.id_parcela)

    return _to_parcela_out(parcela)


@router.get("/parcelas/{id_parcela}", response_model=ParcelaOut)
async def obtener_parcela(id_parcela: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(
        select(Parcela)
        .options(selectinload(Parcela.cultivo_actual))
        .where(Parcela.id_parcela == id_parcela, Parcela.activo == True)
    )
    parcela = resultado.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    return _to_parcela_out(parcela)


@router.patch("/parcelas/{id_parcela}/nombre", response_model=ParcelaOut)
async def actualizar_nombre_parcela(
    id_parcela: uuid.UUID,
    data: NombreUpdate,
    db: AsyncSession = Depends(get_db),
):
    resultado = await db.execute(
        select(Parcela).where(Parcela.id_parcela == id_parcela, Parcela.activo == True)
    )
    parcela = resultado.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    parcela.nombre_parcela = data.nombre
    await db.commit()
    await db.refresh(parcela)
    return _to_parcela_out(parcela)


@router.get("/parcelas/{id_parcela}/kpi")
async def kpi_parcela(
    id_parcela: uuid.UUID,
    dias_siembra: Optional[int] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    KPI hidrico de la parcela: consumo actual vs. baseline DR-041 (8,000 m3/ha/ciclo).

    Prioridad de ventana temporal:
      1. fecha_desde / fecha_hasta (rango explícito del usuario) — máxima prioridad.
         El baseline se escala proporcionalmente: 8000 * días_rango / 365.
      2. dias_siembra (ciclo agronómico inferido o recibido).
      3. Fallback: últimos 365 días (evita el corte artificial por año calendario).
    """
    BASELINE_DR041 = 8000.0   # m3/ha/ciclo — DR-041 baseline
    TARIFA_M3 = 1.68           # MXN/m3 — CFE 9-CU (bombeo desde 80m)

    # -- 1. Parcela -------------------------------------------------------
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    # -- 2. Nombre del cultivo (informativo, no bloquea si no existe) -------
    nombre_cultivo = None
    ciclo_total_dias = None
    if parcela.id_cultivo_actual is not None:
        cult_res = await db.execute(
            select(CultivoCatalogo).where(
                CultivoCatalogo.id_cultivo == parcela.id_cultivo_actual
            )
        )
        cultivo = cult_res.scalar_one_or_none()
        if cultivo:
            nombre_cultivo = cultivo.nombre_comun
            try:
                curva = obtener_curva_kc(cultivo.nombre_comun)
                ciclo_total_dias = curva["ciclo_total_dias"]
            except ValueError:
                pass

    # -- 3. Determinar ventana temporal ------------------------------------
    # Duración estándar de un ciclo agrícola DR-041 (promedio OI/PV).
    # Se usa como denominador para prorratear el baseline cuando el ciclo
    # está en curso. No usar 365 — el baseline es POR CICLO, no por año.
    CICLO_DIAS_STD = 167   # (sep15 - abr1 = 167 días, aprox igual para OI)

    modo = "rango_fechas"
    fraccion_ciclo = None
    baseline_proporcional = BASELINE_DR041
    ciclo_en_curso = False

    if fecha_desde is not None or fecha_hasta is not None:
        # Prioridad 1: rango explícito del usuario
        fd = fecha_desde or (date.today() - timedelta(days=365))
        fh_solicitado = fecha_hasta or date.today()

        # Si el ciclo aún no terminó, limitar los datos hasta hoy y
        # prorratear el baseline por fracción del ciclo transcurrida.
        if fh_solicitado > date.today():
            ciclo_en_curso = True
            fh = date.today()
            dias_ciclo_total = max(1, (fh_solicitado - fd).days)
            dias_transcurridos = max(1, (fh - fd).days)
            fraccion_ciclo = min(1.0, dias_transcurridos / dias_ciclo_total)
            baseline_proporcional = round(BASELINE_DR041 * fraccion_ciclo, 1)
        else:
            # Ciclo histórico completo: comparar contra baseline completo
            fh = fh_solicitado
            baseline_proporcional = BASELINE_DR041

        filtro_fecha = [
            HistorialRiego.fecha_riego >= fd,
            HistorialRiego.fecha_riego <= fh,
        ]
        modo = "rango_fechas"
    else:
        # Prioridad 2: dias_siembra (agronómico)
        if dias_siembra is None and parcela.id_cultivo_actual is not None:
            rec_res = await db.execute(
                select(Recomendacion)
                .where(Recomendacion.id_parcela == id_parcela)
                .order_by(Recomendacion.fecha_riego_sugerida.desc())
                .limit(1)
            )
            rec = rec_res.scalar_one_or_none()
            if rec and rec.parametros_json and "dias_siembra" in rec.parametros_json:
                dias_siembra = int(rec.parametros_json["dias_siembra"])

        if dias_siembra is not None and ciclo_total_dias is not None and dias_siembra >= 0:
            fraccion_ciclo = min(1.0, dias_siembra / ciclo_total_dias)
            baseline_proporcional = round(BASELINE_DR041 * fraccion_ciclo, 1)
            fecha_inicio_ciclo = date.today() - timedelta(days=dias_siembra)
            filtro_fecha = [HistorialRiego.fecha_riego >= fecha_inicio_ciclo]
            modo = "ciclo_agronomico"
            fd = fecha_inicio_ciclo
            fh = date.today()
        else:
            # Prioridad 3: fallback últimos 365 días
            fd = date.today() - timedelta(days=365)
            fh = date.today()
            dias_rango = 365
            baseline_proporcional = BASELINE_DR041
            filtro_fecha = [
                HistorialRiego.fecha_riego >= fd,
                HistorialRiego.fecha_riego <= fh,
            ]
            modo = "ultimos_365_dias"

    # -- 4. Suma de volumen (solo riegos reales: volumen > 0) ---------------
    filtro_base = [
        HistorialRiego.id_parcela == id_parcela,
        HistorialRiego.volumen_m3_ha > 0,
        *filtro_fecha,
    ]
    vol_res = await db.execute(
        select(func.sum(HistorialRiego.volumen_m3_ha)).where(*filtro_base)
    )
    volumen_total = float(vol_res.scalar() or 0.0)

    # -- 5. KPIs -----------------------------------------------------------
    ahorro_m3 = max(0.0, baseline_proporcional - volumen_total)
    ahorro_pct = (ahorro_m3 / baseline_proporcional) * 100 if baseline_proporcional > 0 else 0
    ahorro_mxn = ahorro_m3 * TARIFA_M3

    respuesta = {
        "id_parcela": str(id_parcela),
        "nombre_parcela": parcela.nombre_parcela,
        "cultivo": nombre_cultivo,
        "volumen_aplicado_m3_ha": round(volumen_total, 2),
        "baseline_dr041_m3_ha": BASELINE_DR041,
        "baseline_proporcional": round(baseline_proporcional, 1),
        "ahorro_m3_ha": round(ahorro_m3, 2),
        "ahorro_pct": round(ahorro_pct, 2),
        "ahorro_estimado_mxn": round(ahorro_mxn, 2),
        "tarifa_m3_mxn": TARIFA_M3,
        "meta_cumplida": ahorro_pct >= 25.0,
        "normalizado": ciclo_en_curso,   # True solo si ciclo en curso (baseline prorrateado)
        "ciclo_en_curso": ciclo_en_curso,
        "modo": modo,
        "fecha_desde": fd.isoformat(),
        "fecha_hasta": fh.isoformat(),
    }

    if fraccion_ciclo is not None:
        respuesta["fraccion_ciclo"] = round(fraccion_ciclo, 3)
        respuesta["dias_siembra_efectivo"] = dias_siembra
        respuesta["ciclo_total_dias"] = ciclo_total_dias
        respuesta["fraccion_ciclo"] = round(fraccion_ciclo, 3)

    return respuesta


# ── Endpoints: historial_riego ────────────────────────────────────────────────

@router.post("/riego", response_model=RiegoOut, status_code=status.HTTP_201_CREATED)
async def registrar_riego(
    data: RiegoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Registra un evento de riego ejecutado. Requiere JWT del dueño de la parcela.

    Si se proporciona id_recomendacion, actualiza automáticamente el estado
    de la recomendación a 'aceptada' (o 'modificada' si la lámina difiere).
    """
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    if current_user.rol != "admin" and parcela.id_usuario != current_user.id_usuario:
        raise HTTPException(status_code=403, detail="Sin acceso a esta parcela.")

    payload = data.model_dump()
    # Autocalcular ciclo_agricola si el cliente no lo envió
    if not payload.get("ciclo_agricola"):
        payload["ciclo_agricola"] = _ciclo_agricola(data.fecha_riego)
    # Siempre fijar el target MILPÍN (no depende del cliente)
    payload["ciclo_vol_target_m3_ha"] = _MILPIN_VOL_TARGET_M3_HA

    riego = HistorialRiego(id_riego=uuid.uuid4(), **payload)
    db.add(riego)

    # Actualizar feedback de la recomendación si viene vinculada
    if data.id_recomendacion:
        rec_res = await db.execute(
            select(Recomendacion).where(
                Recomendacion.id_recomendacion == data.id_recomendacion
            )
        )
        rec = rec_res.scalar_one_or_none()
        if rec and rec.aceptada == "pendiente":
            # Determinar si aceptó o modificó la lámina
            if data.lamina_mm and rec.lamina_recomendada_mm:
                diferencia = abs(float(data.lamina_mm) - float(rec.lamina_recomendada_mm))
                rec.aceptada = "modificada" if diferencia > 2.0 else "aceptada"
                if rec.aceptada == "modificada":
                    rec.lamina_ejecutada_mm = data.lamina_mm
            else:
                rec.aceptada = "aceptada"

    await db.flush()
    return riego


@router.get("/riego/parcela/{id_parcela}", response_model=list[RiegoOut])
async def historial_riego_parcela(
    id_parcela: uuid.UUID,
    limite: int = 20,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """Retorna el historial de riego de una parcela (más reciente primero).

    Parámetros opcionales:
      fecha_desde — filtra eventos >= esta fecha (ISO 8601, ej: 2025-10-15)
      fecha_hasta — filtra eventos <= esta fecha
    """
    filtros = [HistorialRiego.id_parcela == id_parcela]
    if fecha_desde is not None:
        filtros.append(HistorialRiego.fecha_riego >= fecha_desde)
    if fecha_hasta is not None:
        filtros.append(HistorialRiego.fecha_riego <= fecha_hasta)

    resultado = await db.execute(
        select(HistorialRiego)
        .where(*filtros)
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(limite)
    )
    return resultado.scalars().all()


# ── Endpoints: recomendaciones ────────────────────────────────────────────────

@router.post(
    "/recomendaciones", response_model=RecomendacionOut, status_code=status.HTTP_201_CREATED
)
async def guardar_recomendacion(
    data: RecomendacionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Persiste una recomendación generada por el motor FAO-56.

    Requiere JWT del dueño de la parcela (o admin). El motor FAO-56 en
    riego_api.py persiste directamente vía ORM, no llama a este endpoint.
    """
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    if current_user.rol != "admin" and parcela.id_usuario != current_user.id_usuario:
        raise HTTPException(status_code=403, detail="Sin acceso a esta parcela.")

    rec = Recomendacion(id_recomendacion=uuid.uuid4(), **data.model_dump())
    db.add(rec)
    await db.flush()
    return rec


@router.get("/recomendaciones/parcela/{id_parcela}")
async def recomendaciones_por_parcela(
    id_parcela: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Devuelve el estado de recomendaciones para una parcela:
      - activa: la recomendacion pendiente mas reciente (None si no hay)
      - historial: las ultimas 5 recomendaciones cerradas (aceptada/modificada/ignorada)

    El frontend usa este endpoint para renderizar el tab de Riego.
    """
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    # Valores edáficos de la parcela como fallback para recomendaciones antiguas
    # que no tienen cc_pct/humedad_actual_pct en parametros_json.
    # capacidad_campo y punto_marchitez se guardan en BD como fracción (0–1);
    # los multiplicamos × 100 para que el frontend reciba porcentaje (0–100).
    _cc_fallback  = float(parcela.capacidad_campo or 0.34) * 100.0
    _pmp_fallback = float(parcela.punto_marchitez or 0.18) * 100.0

    # Recomendacion pendiente mas reciente
    res_activa = await db.execute(
        select(Recomendacion)
        .where(
            Recomendacion.id_parcela == id_parcela,
            Recomendacion.aceptada == "pendiente",
        )
        .order_by(Recomendacion.fecha_generacion.desc())
        .limit(1)
    )
    activa = res_activa.scalar_one_or_none()

    # Ultimas 5 cerradas
    res_hist = await db.execute(
        select(Recomendacion)
        .where(
            Recomendacion.id_parcela == id_parcela,
            Recomendacion.aceptada != "pendiente",
        )
        .order_by(Recomendacion.fecha_generacion.desc())
        .limit(5)
    )
    historial = res_hist.scalars().all()

    def _fmt(r: Recomendacion) -> dict:
        pj = r.parametros_json or {}

        # cc_pct: preferir el snapshot guardado; si no existe (rec antigua),
        # usar el valor actual de la parcela como fallback.
        cc_pct = pj.get("cc_pct") or _cc_fallback

        # humedad_actual_pct: ídem. Si falta en el snapshot (recomendaciones
        # generadas antes del 2026-05-06), estimar con el punto medio CC+PMP.
        # El flag humedad_estimada avisa al frontend que es un valor aproximado.
        hum_pct = pj.get("humedad_actual_pct")
        humedad_estimada = hum_pct is None
        if hum_pct is None:
            hum_pct = round((_cc_fallback + _pmp_fallback) / 2.0, 2)

        return {
            "id_recomendacion": str(r.id_recomendacion),
            "fecha_generacion": r.fecha_generacion.isoformat(),
            "fecha_riego_sugerida": r.fecha_riego_sugerida.isoformat() if r.fecha_riego_sugerida else None,
            "lamina_recomendada_mm": float(r.lamina_recomendada_mm) if r.lamina_recomendada_mm else None,
            "eto_referencia": float(r.eto_referencia) if r.eto_referencia else None,
            "etc_calculada": float(r.etc_calculada) if r.etc_calculada else None,
            "deficit_acumulado_mm": float(r.deficit_acumulado_mm) if r.deficit_acumulado_mm else None,
            "dias_sin_riego": r.dias_sin_riego,
            "nivel_urgencia": r.nivel_urgencia,
            "aceptada": r.aceptada,
            "lamina_ejecutada_mm": float(r.lamina_ejecutada_mm) if r.lamina_ejecutada_mm else None,
            # ── Campos extraídos de parametros_json (con fallbacks) ──
            "cultivo": pj.get("cultivo"),
            "parcela_nombre": pj.get("parcela"),
            "kc": pj.get("kc"),
            "precipitacion_mm": pj.get("precipitacion_mm"),
            "humedad_actual_pct": hum_pct,
            "humedad_estimada": humedad_estimada,
            "cc_pct": cc_pct,
            "dias_siembra": pj.get("dias_siembra"),
            "parametros_json": pj,
        }

    return {
        "id_parcela": str(id_parcela),
        "activa": _fmt(activa) if activa else None,
        "historial": [_fmt(r) for r in historial],
    }


@router.get("/recomendaciones/{id_recomendacion}", response_model=RecomendacionOut)
async def obtener_recomendacion(
    id_recomendacion: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    resultado = await db.execute(
        select(Recomendacion).where(Recomendacion.id_recomendacion == id_recomendacion)
    )
    rec = resultado.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada.")
    return rec


@router.patch("/recomendaciones/{id_recomendacion}/feedback", response_model=RecomendacionOut)
async def feedback_recomendacion(
    id_recomendacion: uuid.UUID,
    feedback: FeedbackRecomendacion,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_optional_user),
):
    """
    Registra la respuesta del agricultor a una recomendacion.

    - aceptada / modificada: actualiza el estado Y auto-inserta en historial_riego
      con el volumen real aplicado. Alimenta v_kpi_consumo.
    - ignorada: actualiza el estado Y auto-inserta en historial_riego con
      volumen_m3_ha = 0. Necesario para:
        1. Calcular tasa de adopcion real en el dashboard BI.
        2. Registrar el evento de no-riego para analisis de comportamiento.
        3. No afecta propagar_balance_hidrico (esa funcion solo usa riegos
           con volumen > 0 via la consulta de ultimo riego real).

    Idempotente: rechaza con 409 si la recomendacion ya fue cerrada.
    """
    resultado = await db.execute(
        select(Recomendacion).where(Recomendacion.id_recomendacion == id_recomendacion)
    )
    rec = resultado.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recomendacion no encontrada.")

    # Verificar propiedad: la recomendación pertenece a una parcela del usuario
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == rec.id_parcela))
    parcela = p_res.scalar_one_or_none()
    if current_user.rol != "admin" and (
        parcela is None or parcela.id_usuario != current_user.id_usuario
    ):
        raise HTTPException(status_code=403, detail="Sin acceso a esta recomendación.")

    if rec.aceptada != "pendiente":
        raise HTTPException(
            status_code=409,
            detail=f"Recomendacion ya cerrada con estado '{rec.aceptada}'.",
        )

    rec.aceptada = feedback.aceptada
    if feedback.lamina_ejecutada_mm is not None:
        rec.lamina_ejecutada_mm = feedback.lamina_ejecutada_mm

    # Insertar en historial_riego para los tres casos de feedback.
    # "ignorada" registra volumen = 0 para que el dashboard lo cuente
    # correctamente al calcular tasa de adopcion y KPIs de ciclo.
    fecha_riego = rec.fecha_riego_sugerida or date.today()
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == rec.id_parcela))
    parcela = p_res.scalar_one_or_none()

    if feedback.aceptada in ("aceptada", "modificada"):
        lamina_mm = (
            feedback.lamina_ejecutada_mm
            if feedback.lamina_ejecutada_mm is not None
            else (float(rec.lamina_recomendada_mm) if rec.lamina_recomendada_mm else None)
        )
        volumen_m3_ha = round(lamina_mm * 10.0, 2) if lamina_mm is not None else None
        costo_energia_mxn = None
        if volumen_m3_ha is not None and parcela and parcela.area_ha:
            costo_energia_mxn = round(volumen_m3_ha * float(parcela.area_ha) * 1.68, 2)

        riego = HistorialRiego(
            id_riego=uuid.uuid4(),
            id_parcela=rec.id_parcela,
            id_recomendacion=rec.id_recomendacion,
            fecha_riego=fecha_riego,
            ciclo_agricola=_ciclo_agricola(fecha_riego),
            ciclo_vol_target_m3_ha=_MILPIN_VOL_TARGET_M3_HA,
            lamina_mm=lamina_mm,
            volumen_m3_ha=volumen_m3_ha,
            metodo_riego=parcela.sistema_riego if parcela else None,
            origen_decision="sistema",
            costo_energia_mxn=costo_energia_mxn,
            observaciones=feedback.notas or None,
        )
        db.add(riego)

    elif feedback.aceptada == "ignorada":
        # Registro de no-riego: volumen = 0, sin costo.
        # La consulta _estimar_humedad_actual filtra por ultimo riego con
        # volumen > 0, por lo que este registro no altera el balance hidrico.
        obs = feedback.notas or "Recomendacion ignorada por el agricultor."
        riego = HistorialRiego(
            id_riego=uuid.uuid4(),
            id_parcela=rec.id_parcela,
            id_recomendacion=rec.id_recomendacion,
            fecha_riego=fecha_riego,
            ciclo_agricola=_ciclo_agricola(fecha_riego),
            ciclo_vol_target_m3_ha=_MILPIN_VOL_TARGET_M3_HA,
            lamina_mm=0.0,
            volumen_m3_ha=0.0,
            metodo_riego=None,
            origen_decision="sistema",
            costo_energia_mxn=0.0,
            observaciones=obs,
        )
        db.add(riego)

    await db.flush()
    return rec


# Schemas: costos_ciclo

class CostoCicloCreate(BaseModel):
    id_parcela: uuid.UUID
    ciclo_agricola: str = Field(..., description="Formato OI-YYYY o PV-YYYY")
    cultivo: str | None = None
    volumen_agua_total_m3: float | None = None
    costo_agua_mxn: float | None = None
    costo_fertilizantes_mxn: float | None = None
    costo_agroquimicos_mxn: float | None = None
    costo_semilla_mxn: float | None = None
    costo_maquinaria_mxn: float | None = None
    costo_mano_obra_mxn: float | None = None
    ingreso_estimado_mxn: float | None = None
    margen_contribucion_mxn: float | None = None

class CostoCicloOut(BaseModel):
    id_costo: uuid.UUID
    id_parcela: uuid.UUID
    ciclo_agricola: str
    cultivo: str | None
    volumen_agua_total_m3: float | None
    costo_agua_mxn: float | None
    costo_fertilizantes_mxn: float | None
    costo_agroquimicos_mxn: float | None
    costo_semilla_mxn: float | None
    costo_maquinaria_mxn: float | None
    costo_mano_obra_mxn: float | None
    ingreso_estimado_mxn: float | None
    margen_contribucion_mxn: float | None
    model_config = {"from_attributes": True}


# Endpoints: costos_ciclo

@router.post("/costos", response_model=CostoCicloOut, status_code=status.HTTP_201_CREATED)
async def registrar_costo_ciclo(
    data: CostoCicloCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Registra el resumen economico de un ciclo agricola. Calcula margen si no se provee."""
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    if current_user.rol != "admin" and parcela.id_usuario != current_user.id_usuario:
        raise HTTPException(status_code=403, detail="Sin acceso a esta parcela.")

    payload = data.model_dump()

    if payload.get("margen_contribucion_mxn") is None and payload.get("ingreso_estimado_mxn") is not None:
        costos_directos = sum(
            payload.get(k) or 0.0
            for k in (
                "costo_agua_mxn", "costo_fertilizantes_mxn", "costo_agroquimicos_mxn",
                "costo_semilla_mxn", "costo_maquinaria_mxn", "costo_mano_obra_mxn",
            )
        )
        payload["margen_contribucion_mxn"] = payload["ingreso_estimado_mxn"] - costos_directos

    costo = CostoCiclo(id_costo=uuid.uuid4(), **payload)
    db.add(costo)
    await db.flush()
    return costo


@router.get("/costos/parcela/{id_parcela}", response_model=list[CostoCicloOut])
async def costos_por_parcela(id_parcela: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retorna todos los ciclos de una parcela ordenados del mas reciente al mas antiguo."""
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    resultado = await db.execute(
        select(CostoCiclo)
        .where(CostoCiclo.id_parcela == id_parcela)
        .order_by(CostoCiclo.ciclo_agricola.desc())
    )
    return resultado.scalars().all()


# ── Endpoint: carga de trabajo técnico de riego ───────────────────────────────

@router.get("/tecnico/carga-trabajo")
async def carga_trabajo_tecnico(
    id_usuario: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Vista de carga de trabajo para técnicos de riego.

    Retorna todas las parcelas activas con su última recomendación pendiente,
    ordenadas por urgencia (crítico → moderado → preventivo → sin recomendación).

    Parámetros opcionales:
      id_usuario — filtra por propietario (sin filtro = todas las parcelas del sistema).
    """
    # --- 1. Parcelas activas con propietario y cultivo ---
    stmt = (
        select(Parcela, Usuario, CultivoCatalogo)
        .join(Usuario, Parcela.id_usuario == Usuario.id_usuario)
        .outerjoin(CultivoCatalogo, Parcela.id_cultivo_actual == CultivoCatalogo.id_cultivo)
        .where(Parcela.activo == True)
        .order_by(Parcela.nombre_parcela)
    )
    if id_usuario is not None:
        stmt = stmt.where(Parcela.id_usuario == id_usuario)

    parcelas_res = await db.execute(stmt)
    parcelas_rows = parcelas_res.all()

    if not parcelas_rows:
        return {
            "fecha_consulta": date.today().isoformat(),
            "resumen": {"total": 0, "critico": 0, "moderado": 0, "preventivo": 0, "sin_recomendacion": 0},
            "parcelas": [],
        }

    parcela_ids = [row.Parcela.id_parcela for row in parcelas_rows]

    # --- 2. Todas las recomendaciones pendientes; Python-side: más reciente por parcela ---
    recs_res = await db.execute(
        select(Recomendacion)
        .where(
            Recomendacion.aceptada == "pendiente",
            Recomendacion.id_parcela.in_(parcela_ids),
        )
        .order_by(Recomendacion.fecha_generacion.desc())
    )
    rec_por_parcela: dict[str, Recomendacion] = {}
    for r in recs_res.scalars().all():
        pid = str(r.id_parcela)
        if pid not in rec_por_parcela:
            rec_por_parcela[pid] = r

    # --- 3. Construir lista de items ---
    URGENCIA_ORDEN = {"critico": 0, "moderado": 1, "preventivo": 2}

    items = []
    for row in parcelas_rows:
        p: Parcela = row.Parcela
        u: Usuario = row.Usuario
        c: Optional[CultivoCatalogo] = row.CultivoCatalogo
        r: Optional[Recomendacion] = rec_por_parcela.get(str(p.id_parcela))

        items.append({
            "id_parcela":            str(p.id_parcela),
            "nombre_parcela":        p.nombre_parcela or f"Parcela {str(p.id_parcela)[:8]}",
            "id_usuario":            str(p.id_usuario),
            "propietario":           u.nombre_completo,
            "cultivo":               c.nombre_comun if c else None,
            "area_ha":               float(p.area_ha) if p.area_ha else None,
            "sistema_riego":         p.sistema_riego,
            "nivel_urgencia":        r.nivel_urgencia if r else None,
            "dias_sin_riego":        r.dias_sin_riego if r else None,
            "deficit_acumulado_mm":  float(r.deficit_acumulado_mm) if r and r.deficit_acumulado_mm else None,
            "lamina_recomendada_mm": float(r.lamina_recomendada_mm) if r and r.lamina_recomendada_mm else None,
            "fecha_riego_sugerida":  r.fecha_riego_sugerida.isoformat() if r and r.fecha_riego_sugerida else None,
            "id_recomendacion":      str(r.id_recomendacion) if r else None,
            "aceptada":              r.aceptada if r else None,
            "fecha_generacion":      r.fecha_generacion.isoformat() if r else None,
        })

    # Sort by urgency first, then alphabetically by name
    items.sort(key=lambda x: (URGENCIA_ORDEN.get(x["nivel_urgencia"], 3), x["nombre_parcela"].lower()))

    # --- 4. Resumen ---
    conteo = {"critico": 0, "moderado": 0, "preventivo": 0, "sin_recomendacion": 0}
    for item in items:
        k = item["nivel_urgencia"] or "sin_recomendacion"
        if k in conteo:
            conteo[k] += 1

    return {
        "fecha_consulta": date.today().isoformat(),
        "resumen":        {"total": len(items), **conteo},
        "parcelas":       items,
    }


# Endpoint: proyeccion FAO-56 a N dias con Ridge Regression sobre ETo

@router.get("/parcelas/{id_parcela}/forecast", tags=["Forecast"])
async def forecast_parcela(
    id_parcela: uuid.UUID,
    dias_siembra: int,
    horizon: int = 7,
    umbral_deficit_mm: float = 10.0,
    db: AsyncSession = Depends(get_db),
):
    """Proyeccion FAO-56 a horizon dias usando Ridge Regression para predecir ETo.

    Flujo:
        1. Lee parcela y cultivo actual.
        2. Lee toda la serie de clima_diario disponible.
        3. Entrena EToForecaster (Ridge). Fallback a media(14d) si <60 registros.
        4. Predice ETo para los proximos horizon dias.
        5. Corre FAO-56 forward: ETc, balance hidrico y deficit dia a dia.
        6. Detecta el primer dia en que deficit supera umbral_deficit_mm.
        7. Retorna JSON con detalle diario + estimacion de fecha de riego.

    Parameters
    ----------
    dias_siembra      : dias desde la siembra (para interpolar Kc en FAO-56).
    horizon           : dias a proyectar (1-14). Default: 7.
    umbral_deficit_mm : deficit acumulado que dispara alerta de riego (mm). Default 10.
    """
    from core.eto_forecast import EToForecaster, run_fao56_forward

    # Clamp horizon a rango seguro
    horizon = max(1, min(horizon, 14))

    # -- 1. Parcela y cultivo -----------------------------------------------
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    if parcela.id_cultivo_actual is None:
        raise HTTPException(
            status_code=400,
            detail="La parcela no tiene cultivo asignado (barbecho). "
                   "Asigna un cultivo antes de proyectar.",
        )

    cult_res = await db.execute(
        select(CultivoCatalogo).where(
            CultivoCatalogo.id_cultivo == parcela.id_cultivo_actual
        )
    )
    cultivo = cult_res.scalar_one_or_none()
    if cultivo is None:
        raise HTTPException(status_code=404, detail="Cultivo referenciado no existe.")

    nombre_cultivo = cultivo.nombre_comun

    # -- 2. Serie historica de clima_diario ---------------------------------
    from models import ClimaDiario
    clima_res = await db.execute(
        select(ClimaDiario)
        .where(ClimaDiario.id_parcela == id_parcela)
        .order_by(ClimaDiario.fecha.asc())
    )
    serie_clima = clima_res.scalars().all()

    if not serie_clima:
        raise HTTPException(
            status_code=404,
            detail=f"Sin datos climaticos para parcela {id_parcela}. "
                   "Corre el ETL antes de proyectar: "
                   f"python -m tools.nasa_power_etl --parcela {id_parcela}",
        )

    # -- 3. Entrenar EToForecaster ------------------------------------------
    forecaster = EToForecaster()
    forecaster.fit(serie_clima)

    # -- 4. Humedad inicial: ultimo riego real o punto medio ----------------
    cc_pct = float(parcela.capacidad_campo) * 100.0 if parcela.capacidad_campo else 34.0
    pmp_pct = float(parcela.punto_marchitez) * 100.0 if parcela.punto_marchitez else 18.0

    ultimo_riego_res = await db.execute(
        select(HistorialRiego.fecha_riego, HistorialRiego.lamina_mm)
        .where(
            HistorialRiego.id_parcela == id_parcela,
            HistorialRiego.volumen_m3_ha > 0,
        )
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(1)
    )
    ultimo_riego = ultimo_riego_res.first()

    if ultimo_riego is not None:
        # Tomar CC como punto de partida post-riego (suelo recien irrigado)
        humedad_inicial_pct = cc_pct
    else:
        humedad_inicial_pct = (cc_pct + pmp_pct) / 2.0  # fallback: punto medio

    # -- 5. Predecir ETo y correr FAO-56 forward ----------------------------
    eto_proyectado = forecaster.predict(horizon=horizon, start_date=date.today())

    resultado = run_fao56_forward(
        parcela=parcela,
        cultivo_nombre=nombre_cultivo,
        dias_siembra=dias_siembra,
        eto_forecast=eto_proyectado,
        umbral_deficit_mm=umbral_deficit_mm,
        humedad_inicial_pct=humedad_inicial_pct,
    )

    # -- 6. Respuesta -------------------------------------------------------
    respuesta = {
        "id_parcela": str(id_parcela),
        "cultivo": nombre_cultivo,
        "dias_siembra": dias_siembra,
        **resultado,
    }

    if forecaster.using_fallback:
        respuesta["advertencia"] = (
            "Menos de 60 registros climaticos disponibles. "
            "Se uso la media de los ultimos 14 dias como proxy de ETo. "
            "La proyeccion es orientativa — corre el ETL para mayor precision."
        )

    return respuesta


# ── PATCH: renombrar parcela ───────────────────────────────────────────────────
class RenombrePayload(BaseModel):
    nombre: str


@router.patch("/parcelas/{id_parcela}/nombre")
async def renombrar_parcela(
    id_parcela: uuid.UUID,
    body: RenombrePayload,
    db: AsyncSession = Depends(get_db),
):
    """Renombra una parcela del usuario."""
    resultado = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = resultado.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    nombre = body.nombre.strip()[:100]
    if not nombre:
        raise HTTPException(status_code=400, detail="Nombre vacío.")
    parcela.nombre_parcela = nombre
    await db.commit()
    return {"id_parcela": str(id_parcela), "nombre_parcela": nombre}


@router.patch("/usuarios/{id_usuario}/nombre")
async def renombrar_usuario(
    id_usuario: uuid.UUID,
    body: RenombrePayload,
    db: AsyncSession = Depends(get_db),
):
    """Actualiza el nombre completo del usuario."""
    resultado = await db.execute(select(Usuario).where(Usuario.id_usuario == id_usuario))
    usuario = resultado.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    nombre = body.nombre.strip()[:120]
    if not nombre:
        raise HTTPException(status_code=400, detail="Nombre vacío.")
    usuario.nombre_completo = nombre
    await db.commit()
    return {"id_usuario": str(id_usuario), "nombre_completo": nombre}
