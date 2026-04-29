"""
riego_api.py — Endpoints de riego y balance hídrico para MILPIN AgTech v2.0

Endpoints:
    GET  /api/balance_hidrico?parcela_id=<uuid>&fecha=<YYYY-MM-DD>&dias_siembra=<int>
         -> Lee datos de BD (parcela + clima_diario + cultivo), calcula FAO-56,
            persiste la recomendacion en `recomendaciones` y retorna el resultado.

    GET  /api/balance_hidrico_manual?parcela_id=...&cultivo=...&tmax=...
         -> Endpoint legacy: recibe todos los parametros por query string.
            No lee de BD ni persiste. Util para pruebas rapidas.

    GET  /api/kc/{cultivo}
         -> Curva Kc completa por cultivo (FAO-56 Tabla 12).
"""

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.balance_hidrico import (
    calcular_balance_hidrico,
    calcular_costo_riego,
    calcular_eto_hargreaves,
    calcular_eto_penman_monteith,
    obtener_curva_kc,
    obtener_kc,
)
from database import get_db
from models import ClimaDiario, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion

router = APIRouter()


# -- Helpers -------------------------------------------------------------------

async def _dias_sin_riego(
    db: AsyncSession, id_parcela: uuid.UUID, fecha_ref: date
) -> int:
    """Dias transcurridos desde el ultimo riego registrado para la parcela."""
    resultado = await db.execute(
        select(HistorialRiego.fecha_riego)
        .where(
            HistorialRiego.id_parcela == id_parcela,
            HistorialRiego.fecha_riego <= fecha_ref,
        )
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(1)
    )
    ultimo = resultado.scalar_one_or_none()
    if ultimo is None:
        return 999  # Sin riego registrado
    return (fecha_ref - ultimo).days


def _clasificar_urgencia(requiere_riego: bool, deficit_mm: float) -> str:
    """Clasifica urgencia segun deficit hidrico.

    Criterios:
        critico:    deficit > 20 mm y requiere riego
        moderado:   deficit > 8 mm y requiere riego
        preventivo: todo lo demas
    """
    if requiere_riego and deficit_mm > 20.0:
        return "critico"
    elif requiere_riego and deficit_mm > 8.0:
        return "moderado"
    return "preventivo"


# ── Endpoint principal: lee de BD, calcula, persiste ──────────────────────────

@router.get("/balance_hidrico", tags=["Motor FAO-56"])
async def get_balance_hidrico(
    parcela_id: uuid.UUID,
    dias_siembra: int,
    fecha: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """Calcula el balance hídrico para una parcela leyendo de la BD.

    Flujo:
        1. Lee datos edáficos de `parcelas` (CC, PMP, profundidad raíz, etc.)
        2. Obtiene el cultivo asociado de `cultivos_catalogo` (Kc por etapa)
        3. Lee el registro climático de `clima_diario` para la fecha indicada
        4. Calcula ETo (Penman-Monteith o Hargreaves fallback), ETc, balance
        5. Persiste el resultado en `recomendaciones`
        6. Retorna el JSON completo
    """
    if fecha is None:
        fecha = date.today()

    # ── 1. Parcela ────────────────────────────────────────────────────────────
    res = await db.execute(
        select(Parcela).where(Parcela.id_parcela == parcela_id)
    )
    parcela = res.scalar_one_or_none()
    if parcela is None:
        raise HTTPException(404, f"Parcela {parcela_id} no encontrada.")

    if parcela.id_cultivo_actual is None:
        raise HTTPException(
            400,
            f"Parcela {parcela_id} no tiene cultivo asignado (barbecho). "
            "Asigna un cultivo antes de calcular balance hídrico.",
        )

    # -- 2. Cultivo (Kc) ------------------------------------------------------
    res_c = await db.execute(
        select(CultivoCatalogo).where(
            CultivoCatalogo.id_cultivo == parcela.id_cultivo_actual
        )
    )
    cultivo = res_c.scalar_one_or_none()
    if cultivo is None:
        raise HTTPException(
            404,
            f"Cultivo {parcela.id_cultivo_actual} referenciado por la parcela no existe.",
        )

    nombre_cultivo = cultivo.nombre_comun.lower()

    try:
        kc = obtener_kc(nombre_cultivo, dias_siembra)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # -- 3. Clima del dia -----------------------------------------------------
    res_cl = await db.execute(
        select(ClimaDiario).where(
            ClimaDiario.id_parcela == parcela_id,
            ClimaDiario.fecha == fecha,
        )
    )
    clima = res_cl.scalar_one_or_none()

    metodo_eto = "penman_monteith"
    advertencia = None
    dia_del_ano = fecha.timetuple().tm_yday

    if clima is not None and all(
        v is not None for v in [
            clima.t_max, clima.t_min, clima.humedad_rel, clima.viento, clima.radiacion,
        ]
    ):
        # Datos completos → Penman-Monteith
        eto = calcular_eto_penman_monteith(
            tmax=float(clima.t_max),
            tmin=float(clima.t_min),
            humedad_rel=float(clima.humedad_rel),
            viento_ms=float(clima.viento),
            radiacion_solar_mj=float(clima.radiacion),
            dia_del_ano=dia_del_ano,
        )
        precipitacion = float(clima.lluvia or 0.0)
    elif clima is not None and clima.t_max is not None and clima.t_min is not None:
        # Datos parciales → Hargreaves fallback
        metodo_eto = "hargreaves"
        advertencia = (
            f"clima_diario para {fecha} tiene datos incompletos. "
            "Se usó Hargreaves como respaldo."
        )
        eto = calcular_eto_hargreaves(
            tmax=float(clima.t_max),
            tmin=float(clima.t_min),
            dia_del_ano=dia_del_ano,
        )
        precipitacion = float(clima.lluvia or 0.0)
    else:
        raise HTTPException(
            404,
            f"No hay datos climáticos para parcela {parcela_id} en fecha {fecha}. "
            "Ejecuta el ETL de NASA POWER o verifica los datos seed.",
        )

    # -- 4. Calculo del balance -----------------------------------------------
    etc = eto * kc

    # Convertir CC y PMP de m³/m³ (BD) a porcentaje para el motor
    cc_pct = float(parcela.capacidad_campo) * 100.0 if parcela.capacidad_campo else 34.0
    pmp_pct = float(parcela.punto_marchitez) * 100.0 if parcela.punto_marchitez else 18.0
    prof_raiz_m = (parcela.profundidad_raiz_cm or 60) / 100.0

    # Humedad actual estimada: punto medio entre CC y PMP (simplificación MVP)
    # En producción esto vendría de sensores o del balance acumulado
    humedad_actual_pct = (cc_pct + pmp_pct) / 2.0

    balance = calcular_balance_hidrico(
        etc_mm=etc,
        precipitacion_mm=precipitacion,
        humedad_actual_pct=humedad_actual_pct,
        capacidad_campo_pct=cc_pct,
        punto_marchitez_pct=pmp_pct,
        profundidad_raiz_m=prof_raiz_m,
    )

    costo = calcular_costo_riego(volumen_m3=balance["volumen_m3_ha"])

    # -- 5. Dias sin riego + urgencia ------------------------------------------
    dias_sin = await _dias_sin_riego(db, parcela.id_parcela, fecha)
    nivel_urgencia = _clasificar_urgencia(balance["requiere_riego"], balance["deficit_mm"])

    # -- 6. Persistir recomendacion --------------------------------------------
    recomendacion = Recomendacion(
        id_recomendacion=uuid.uuid4(),
        id_parcela=parcela.id_parcela,
        id_cultivo=cultivo.id_cultivo,
        fecha_riego_sugerida=fecha,
        lamina_recomendada_mm=balance["lamina_bruta_mm"],
        eto_referencia=round(eto, 3),
        etc_calculada=round(etc, 3),
        deficit_acumulado_mm=balance["deficit_mm"],
        dias_sin_riego=dias_sin,
        nivel_urgencia=nivel_urgencia,
        algoritmo_version="fao56-mvp-v1.0",
        aceptada="pendiente",
        parametros_json={
            "fecha": fecha.isoformat(),
            "dias_siembra": dias_siembra,
            "kc": round(kc, 3),
            "metodo_eto": metodo_eto,
            "humedad_actual_pct": round(humedad_actual_pct, 2),
            "cc_pct": round(cc_pct, 2),
            "pmp_pct": round(pmp_pct, 2),
            "prof_raiz_m": prof_raiz_m,
            "precipitacion_mm": precipitacion,
            "cultivo": cultivo.nombre_comun,
            "parcela": parcela.nombre_parcela,
        },
    )
    db.add(recomendacion)
    # El commit lo hace get_db al salir del context manager

    # -- 7. Respuesta ----------------------------------------------------------
    resultado = {
        "id_recomendacion": str(recomendacion.id_recomendacion),
        "parcela_id": str(parcela.id_parcela),
        "parcela_nombre": parcela.nombre_parcela,
        "cultivo": cultivo.nombre_comun,
        "fecha_calculo": fecha.isoformat(),
        "dias_siembra": dias_siembra,
        "metodo_eto": metodo_eto,
        "eto_mm": round(eto, 2),
        "kc": round(kc, 3),
        "etc_mm": round(etc, 2),
        "balance": balance,
        "costo": costo,
        "dias_sin_riego": dias_sin,
        "nivel_urgencia": nivel_urgencia,
        "persistido": True,
    }

    if advertencia:
        resultado["advertencia"] = advertencia

    return resultado


# -- Endpoint legacy (sin BD, parametros manuales) ----------------------------

@router.get("/balance_hidrico_manual", tags=["Motor FAO-56"])
async def get_balance_hidrico_manual(
    parcela_id: str,
    cultivo: str,
    dias_siembra: int,
    tmax: float,
    tmin: float,
    humedad_rel: Optional[float] = None,
    viento: Optional[float] = None,
    radiacion: Optional[float] = None,
    precipitacion: float = 0.0,
    humedad_suelo: float = 30.0,
    capacidad_campo: float = 38.0,
    punto_marchitez: float = 18.0,
    profundidad_raiz: float = 0.6,
):
    """Endpoint legacy: calcula balance hídrico con parámetros manuales.

    No lee de BD ni persiste. Útil para pruebas rápidas y para el frontend
    actual que aún no usa el endpoint principal.
    """
    dia_del_ano = date.today().timetuple().tm_yday
    metodo_eto = "penman_monteith"
    advertencia = None

    if humedad_rel is not None and viento is not None and radiacion is not None:
        eto = calcular_eto_penman_monteith(
            tmax=tmax, tmin=tmin, humedad_rel=humedad_rel,
            viento_ms=viento, radiacion_solar_mj=radiacion,
            dia_del_ano=dia_del_ano,
        )
    else:
        metodo_eto = "hargreaves"
        advertencia = (
            "Datos incompletos. Se usó Hargreaves como respaldo."
        )
        eto = calcular_eto_hargreaves(tmax=tmax, tmin=tmin, dia_del_ano=dia_del_ano)

    try:
        kc = obtener_kc(cultivo, dias_siembra)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    etc = eto * kc
    balance = calcular_balance_hidrico(
        etc_mm=etc, precipitacion_mm=precipitacion,
        humedad_actual_pct=humedad_suelo, capacidad_campo_pct=capacidad_campo,
        punto_marchitez_pct=punto_marchitez, profundidad_raiz_m=profundidad_raiz,
    )
    costo = calcular_costo_riego(volumen_m3=balance["volumen_m3_ha"])

    resultado = {
        "parcela_id": parcela_id,
        "fecha_calculo": date.today().isoformat(),
        "metodo_eto": metodo_eto,
        "eto_mm": round(eto, 2),
        "kc": round(kc, 2),
        "etc_mm": round(etc, 2),
        "balance": balance,
        "costo": costo,
        "persistido": False,
    }
    if advertencia:
        resultado["advertencia"] = advertencia
    return resultado


# -- Curva Kc ------------------------------------------------------------------

@router.get("/kc/{cultivo}", tags=["Motor FAO-56"])
async def get_curva_kc(cultivo: str):
    """Retorna la curva completa de Kc (todas las etapas fenológicas)
    para un cultivo dado, según FAO-56 Tabla 12."""
    try:
        curva = obtener_curva_kc(cultivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return curva
