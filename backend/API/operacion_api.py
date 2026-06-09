"""
operacion_api.py — Endpoints de operación MILPÍN AgTech v2.0

Endpoints:
    GET /api/operacion/triage      → Lista priorizada de parcelas por urgencia FAO-56
    GET /api/parcelas/{id}/clima   → Serie climática reciente (pulso climático W6)
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import ClimaDiario, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion

router = APIRouter(tags=["Operacion"])

BASELINE_M3HA = 8_000.0
META_M3HA     = 6_000.0


def _urgencia_rank(u: Optional[str]) -> int:
    return {"critico": 0, "moderado": 1, "preventivo": 2}.get(u or "", 3)


def _etapa_from_parametros(parametros: Optional[dict], cultivo: Optional[CultivoCatalogo]) -> str:
    if not parametros or not cultivo:
        return "desconocida"
    dias = parametros.get("dias_siembra") or parametros.get("dias_desde_siembra")
    if dias is None:
        return "desconocida"
    dias = int(dias)
    if dias < cultivo.dias_etapa_inicial:
        return "inicial"
    dias -= cultivo.dias_etapa_inicial
    if dias < cultivo.dias_etapa_desarrollo:
        return "desarrollo"
    dias -= cultivo.dias_etapa_desarrollo
    if dias < cultivo.dias_etapa_media:
        return "media"
    dias -= cultivo.dias_etapa_media
    if dias < cultivo.dias_etapa_final:
        return "final"
    return "cosecha"


@router.get("/operacion/triage")
async def get_triage(
    ciclo: str = Query("PV-2026"),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista priorizada de parcelas activas para la cola de triage operacional.
    Ordenada por nivel_urgencia (critico→moderado→preventivo) y déficit desc.
    Responde simultáneamente a W1 (banner), W2 (triage), W3 (minimap color),
    W4 (drift), W8 (footer cumplimiento).
    """
    today = date.today()

    parcelas_result = await db.execute(select(Parcela).where(Parcela.activo == True))
    parcelas = parcelas_result.scalars().all()

    if not parcelas:
        return _empty_response(ciclo)

    ids = [p.id_parcela for p in parcelas]

    # Última recomendación por parcela (bulk, evita N+1)
    sub_rec = (
        select(
            Recomendacion.id_parcela,
            func.max(Recomendacion.fecha_generacion).label("max_fecha"),
        )
        .where(Recomendacion.id_parcela.in_(ids))
        .group_by(Recomendacion.id_parcela)
        .subquery()
    )
    recs_q = await db.execute(
        select(Recomendacion).join(
            sub_rec,
            and_(
                Recomendacion.id_parcela == sub_rec.c.id_parcela,
                Recomendacion.fecha_generacion == sub_rec.c.max_fecha,
            ),
        )
    )
    rec_map = {str(r.id_parcela): r for r in recs_q.scalars().all()}

    # Última fecha de clima por parcela
    clima_q = await db.execute(
        select(ClimaDiario.id_parcela, func.max(ClimaDiario.fecha).label("f"))
        .where(ClimaDiario.id_parcela.in_(ids))
        .group_by(ClimaDiario.id_parcela)
    )
    clima_map = {str(r.id_parcela): r.f for r in clima_q}

    # Última fecha de riego por parcela
    riego_q = await db.execute(
        select(HistorialRiego.id_parcela, func.max(HistorialRiego.fecha_riego).label("f"))
        .where(HistorialRiego.id_parcela.in_(ids))
        .group_by(HistorialRiego.id_parcela)
    )
    riego_map = {str(r.id_parcela): r.f for r in riego_q}

    # Consumo total del ciclo por parcela
    consumo_q = await db.execute(
        select(
            HistorialRiego.id_parcela,
            func.sum(HistorialRiego.volumen_m3_ha).label("total"),
        )
        .where(
            and_(
                HistorialRiego.id_parcela.in_(ids),
                HistorialRiego.ciclo_agricola == ciclo,
            )
        )
        .group_by(HistorialRiego.id_parcela)
    )
    consumo_map = {str(r.id_parcela): float(r.total or 0) for r in consumo_q}

    # Catálogo de cultivos
    cult_q = await db.execute(select(CultivoCatalogo))
    cult_map = {str(c.id_cultivo): c for c in cult_q.scalars().all()}

    items = []
    for p in parcelas:
        pid   = str(p.id_parcela)
        rec   = rec_map.get(pid)
        clima_ultima = clima_map.get(pid)
        riego_ultima = riego_map.get(pid)
        consumo_m3ha = consumo_map.get(pid, 0.0)

        clima_stale = (today - clima_ultima).days if clima_ultima else None
        riego_stale = (today - riego_ultima).days if riego_ultima else None
        rec_stale   = None
        if rec and rec.fecha_generacion:
            rd = rec.fecha_generacion.date() if hasattr(rec.fecha_generacion, "date") else rec.fecha_generacion
            rec_stale = (today - rd).days

        urgencia       = rec.nivel_urgencia if rec else None
        deficit        = float(rec.deficit_acumulado_mm or 0) if rec else 0.0
        lamina         = float(rec.lamina_recomendada_mm or 0) if rec else 0.0
        dias_sin_riego = int(rec.dias_sin_riego or 0) if rec and rec.dias_sin_riego else (riego_stale or 0)

        cultivo_obj    = cult_map.get(str(p.id_cultivo_actual)) if p.id_cultivo_actual else None
        cultivo_nombre = cultivo_obj.nombre_comun if cultivo_obj else None

        etapa = _etapa_from_parametros(
            rec.parametros_json if rec else None,
            cultivo_obj,
        )

        items.append({
            "id_parcela":           pid,
            "nombre":               p.nombre_parcela or f"P-{pid[:6].upper()}",
            "cultivo":              cultivo_nombre,
            "sistema_riego":        p.sistema_riego,
            "etapa_fenologica":     etapa,
            "dias_sin_riego":       dias_sin_riego,
            "nivel_urgencia":       urgencia,
            "deficit_acumulado_mm": round(deficit, 1),
            "lamina_recomendada_mm": round(lamina, 1),
            "id_recomendacion":     str(rec.id_recomendacion) if rec else None,
            "clima_stale_dias":     clima_stale,
            "riego_stale_dias":     riego_stale,
            "rec_stale_dias":       rec_stale,
            "consumo_ciclo_m3ha":   round(consumo_m3ha, 0),
        })

    items.sort(key=lambda x: (_urgencia_rank(x["nivel_urgencia"]), -x["deficit_acumulado_mm"]))

    critico    = sum(1 for i in items if i["nivel_urgencia"] == "critico")
    moderado   = sum(1 for i in items if i["nivel_urgencia"] == "moderado")
    preventivo = sum(1 for i in items if i["nivel_urgencia"] == "preventivo")
    sin_datos  = sum(1 for i in items if i["nivel_urgencia"] is None)

    consumos     = [i["consumo_ciclo_m3ha"] for i in items if i["consumo_ciclo_m3ha"] > 0]
    consumo_prom = sum(consumos) / len(consumos) if consumos else 0.0
    ahorro_pct   = max(0.0, (BASELINE_M3HA - consumo_prom) / BASELINE_M3HA * 100) if consumo_prom else 0.0
    cumplen      = sum(1 for i in items if 0 < i["consumo_ciclo_m3ha"] <= META_M3HA)
    parciales    = sum(1 for i in items if META_M3HA < i["consumo_ciclo_m3ha"] < BASELINE_M3HA)
    fuera_meta   = sum(1 for i in items if i["consumo_ciclo_m3ha"] >= BASELINE_M3HA)

    return {
        "modulo":    "Módulo 3",
        "actualizado": datetime.utcnow().isoformat() + "Z",
        "resumen": {
            "critico":       critico,
            "moderado":      moderado,
            "preventivo":    preventivo,
            "sin_datos":     sin_datos,
            "total_activas": len(items),
        },
        "cumplimiento_ciclo": {
            "ciclo":                  ciclo,
            "consumo_promedio_m3_ha": round(consumo_prom, 0),
            "baseline_m3_ha":         BASELINE_M3HA,
            "meta_m3_ha":             META_M3HA,
            "ahorro_pct":             round(ahorro_pct, 1),
            "cumplen_meta":           cumplen,
            "parciales":              parciales,
            "fuera_meta":             fuera_meta,
        },
        "parcelas": items,
    }


def _empty_response(ciclo: str) -> dict:
    return {
        "modulo": "Módulo 3",
        "actualizado": datetime.utcnow().isoformat() + "Z",
        "resumen": {"critico": 0, "moderado": 0, "preventivo": 0, "sin_datos": 0, "total_activas": 0},
        "cumplimiento_ciclo": {
            "ciclo": ciclo,
            "consumo_promedio_m3_ha": 0,
            "baseline_m3_ha": BASELINE_M3HA,
            "meta_m3_ha": META_M3HA,
            "ahorro_pct": 0,
            "cumplen_meta": 0,
            "parciales": 0,
            "fuera_meta": 0,
        },
        "parcelas": [],
    }


@router.get("/parcelas/{id_parcela}/clima")
async def get_clima_parcela(
    id_parcela: uuid.UUID,
    dias: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """
    Serie climática reciente por parcela.
    Usada por W6 (pulso climático, sparklines 14 días).
    """
    desde = date.today() - timedelta(days=dias)
    result = await db.execute(
        select(ClimaDiario)
        .where(
            and_(
                ClimaDiario.id_parcela == id_parcela,
                ClimaDiario.fecha >= desde,
            )
        )
        .order_by(ClimaDiario.fecha)
    )
    rows = result.scalars().all()
    return [
        {
            "fecha":  r.fecha.isoformat(),
            "t_max":  float(r.t_max)  if r.t_max  is not None else None,
            "eto":    float(r.et0)    if r.et0    is not None else None,
            "lluvia": float(r.lluvia) if r.lluvia is not None else None,
        }
        for r in rows
    ]
