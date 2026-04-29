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

    POST   /api/riego                           → Registrar evento de riego
    GET    /api/riego/parcela/{id}              → Historial de riego de una parcela

    POST   /api/recomendaciones                 → Guardar recomendación del motor FAO-56
    GET    /api/recomendaciones/{id}            → Obtener recomendación
    PATCH  /api/recomendaciones/{id}/feedback   → Registrar feedback del agricultor

    POST   /api/costos                          → Registrar costos de un ciclo agrícola
    GET    /api/costos/parcela/{id}             → Costos por ciclo de una parcela
"""

import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import CostoCiclo, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion, Usuario

router = APIRouter(tags=["Base de Datos MVP"])


# ── Schemas Pydantic (request / response) ─────────────────────────────────────

class UsuarioCreate(BaseModel):
    nombre_completo: str
    email: str
    telefono: Optional[str] = None
    modulo_dr041: Optional[str] = None

class UsuarioOut(BaseModel):
    id_usuario: uuid.UUID
    nombre_completo: str
    email: str
    modulo_dr041: Optional[str]
    activo: bool
    model_config = {"from_attributes": True}


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
    id_usuario: uuid.UUID
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
    area_ha: Optional[float]
    tipo_suelo: Optional[str]
    conductividad_electrica: Optional[float]
    profundidad_raiz_cm: Optional[int]
    capacidad_campo: Optional[float]
    punto_marchitez: Optional[float]
    agua_disponible_mm: Optional[float]
    sistema_riego: Optional[str]
    activo: bool
    model_config = {"from_attributes": True}


class RiegoCreate(BaseModel):
    id_parcela: uuid.UUID
    id_recomendacion: Optional[uuid.UUID] = None
    fecha_riego: date
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


# ── Endpoints: usuarios ───────────────────────────────────────────────────────

@router.post("/usuarios", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
async def crear_usuario(data: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    """Registra un nuevo agricultor o técnico en el sistema."""
    # Verificar email único
    existe = await db.execute(select(Usuario).where(Usuario.email == data.email))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Email '{data.email}' ya está registrado.")
    usuario = Usuario(id_usuario=uuid.uuid4(), **data.model_dump())
    db.add(usuario)
    await db.flush()
    return usuario


@router.get("/usuarios/{id_usuario}", response_model=UsuarioOut)
async def obtener_usuario(id_usuario: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(select(Usuario).where(Usuario.id_usuario == id_usuario))
    usuario = resultado.scalar_one_or_none()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return usuario


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
async def listar_parcelas(db: AsyncSession = Depends(get_db)):
    """Lista todas las parcelas activas. Usado por el tab de Costos para el selector."""
    resultado = await db.execute(
        select(Parcela).where(Parcela.activo == True).order_by(Parcela.nombre_parcela)
    )
    return resultado.scalars().all()


@router.post("/parcelas", response_model=ParcelaOut, status_code=status.HTTP_201_CREATED)
async def crear_parcela(data: ParcelaCreate, db: AsyncSession = Depends(get_db)):
    """Registra un nuevo lote de cultivo asociado a un usuario."""
    # Verificar que el usuario existe
    usuario = await db.execute(select(Usuario).where(Usuario.id_usuario == data.id_usuario))
    if not usuario.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    parcela = Parcela(id_parcela=uuid.uuid4(), **data.model_dump())
    db.add(parcela)
    await db.flush()
    return parcela


@router.get("/parcelas/{id_parcela}", response_model=ParcelaOut)
async def obtener_parcela(id_parcela: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resultado = await db.execute(
        select(Parcela).where(Parcela.id_parcela == id_parcela, Parcela.activo == True)
    )
    parcela = resultado.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")
    return parcela


@router.get("/parcelas/{id_parcela}/kpi")
async def kpi_parcela(id_parcela: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    KPI hídrico de la parcela: consumo actual vs. baseline DR-041 (8,000 m³/ha/ciclo).

    Calcula el ahorro estimado en m³/ha y en pesos MXN (tarifa $1.68/m³).
    """
    # Verificar que la parcela existe
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = p_res.scalar_one_or_none()
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    # Suma de volumen del año en curso
    anno_actual = date.today().year
    vol_res = await db.execute(
        select(func.sum(HistorialRiego.volumen_m3_ha))
        .where(
            HistorialRiego.id_parcela == id_parcela,
            func.extract("year", HistorialRiego.fecha_riego) == anno_actual,
        )
    )
    volumen_total = float(vol_res.scalar() or 0.0)

    BASELINE_DR041 = 8000.0   # m³/ha/ciclo
    TARIFA_M3 = 1.68           # MXN/m³ — CFE 9-CU (bombeo desde 80m)

    ahorro_m3 = max(0.0, BASELINE_DR041 - volumen_total)
    ahorro_pct = (ahorro_m3 / BASELINE_DR041) * 100 if BASELINE_DR041 > 0 else 0
    ahorro_mxn = ahorro_m3 * TARIFA_M3

    return {
        "id_parcela": str(id_parcela),
        "nombre_parcela": parcela.nombre_parcela,
        "anno": anno_actual,
        "volumen_aplicado_m3_ha": round(volumen_total, 2),
        "baseline_dr041_m3_ha": BASELINE_DR041,
        "ahorro_m3_ha": round(ahorro_m3, 2),
        "ahorro_pct": round(ahorro_pct, 2),
        "ahorro_estimado_mxn": round(ahorro_mxn, 2),
        "tarifa_m3_mxn": TARIFA_M3,
        "meta_cumplida": ahorro_pct >= 25.0,  # KPI objetivo: 25% de ahorro
    }


# ── Endpoints: historial_riego ────────────────────────────────────────────────

@router.post("/riego", response_model=RiegoOut, status_code=status.HTTP_201_CREATED)
async def registrar_riego(data: RiegoCreate, db: AsyncSession = Depends(get_db)):
    """
    Registra un evento de riego ejecutado.

    Si se proporciona id_recomendacion, actualiza automáticamente el estado
    de la recomendación a 'aceptada' (o 'modificada' si la lámina difiere).
    """
    # Verificar que la parcela existe
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

    riego = HistorialRiego(id_riego=uuid.uuid4(), **data.model_dump())
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
    db: AsyncSession = Depends(get_db),
):
    """Retorna el historial de riego de una parcela (más reciente primero)."""
    resultado = await db.execute(
        select(HistorialRiego)
        .where(HistorialRiego.id_parcela == id_parcela)
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(limite)
    )
    return resultado.scalars().all()


# ── Endpoints: recomendaciones ────────────────────────────────────────────────

@router.post(
    "/recomendaciones", response_model=RecomendacionOut, status_code=status.HTTP_201_CREATED
)
async def guardar_recomendacion(data: RecomendacionCreate, db: AsyncSession = Depends(get_db)):
    """
    Persiste una recomendación generada por el motor FAO-56.

    Este endpoint es llamado internamente por riego_api.py después de
    calcular el balance hídrico, para guardar el resultado con trazabilidad.
    """
    # Verificar que la parcela existe
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

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
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

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
            "cultivo": r.parametros_json.get("cultivo") if r.parametros_json else None,
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
):
    """Registra la respuesta del agricultor a una recomendacion (aceptada/modificada/ignorada)."""
    resultado = await db.execute(
        select(Recomendacion).where(Recomendacion.id_recomendacion == id_recomendacion)
    )
    rec = resultado.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recomendacion no encontrada.")

    rec.aceptada = feedback.aceptada
    if feedback.lamina_ejecutada_mm is not None:
        rec.lamina_ejecutada_mm = feedback.lamina_ejecutada_mm

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
async def registrar_costo_ciclo(data: CostoCicloCreate, db: AsyncSession = Depends(get_db)):
    """Registra el resumen economico de un ciclo agricola. Calcula margen si no se provee."""
    p_res = await db.execute(select(Parcela).where(Parcela.id_parcela == data.id_parcela))
    if not p_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Parcela no encontrada.")

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
