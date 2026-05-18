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
    obtener_curva_kc_desde_catalogo,
    obtener_kc,
    obtener_kc_desde_catalogo,
    propagar_balance_hidrico,
)
from database import get_db
from models import ClimaDiario, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion

router = APIRouter()


# -- Helpers -------------------------------------------------------------------

async def _dias_sin_riego(
    db: AsyncSession, id_parcela: uuid.UUID, fecha_ref: date
) -> int:
    """Dias transcurridos desde el ultimo riego real (volumen > 0) para la parcela.

    Se excluyen los registros de no-riego (volumen = 0, decision 'ignorada')
    para no reportar 0 dias sin riego cuando el agricultor ignoro la ultima
    recomendacion.
    """
    resultado = await db.execute(
        select(HistorialRiego.fecha_riego)
        .where(
            HistorialRiego.id_parcela == id_parcela,
            HistorialRiego.fecha_riego <= fecha_ref,
            HistorialRiego.volumen_m3_ha > 0,
        )
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(1)
    )
    ultimo = resultado.scalar_one_or_none()
    if ultimo is None:
        return 999  # Sin riego real registrado
    return (fecha_ref - ultimo).days


async def _estimar_humedad_actual(
    db: AsyncSession,
    id_parcela: uuid.UUID,
    cc_pct: float,
    pmp_pct: float,
    prof_raiz_m: float,
    cultivo_nombre: str,
    dias_siembra_ref: int,
    fecha_ref: date,
) -> tuple:
    """Estima la humedad actual del suelo propagando el balance hidrico
    desde el ultimo riego registrado hasta fecha_ref.

    Flujo:
        1. Busca el ultimo evento de riego en historial_riego.
        2. Si no hay riego, devuelve el punto medio CC+PMP (fallback conservador).
        3. Si hay riego, lee clima_diario entre esa fecha y fecha_ref.
        4. Llama a propagar_balance_hidrico() con esos datos.

    Returns
    -------
    (humedad_actual_pct: float, propagacion_meta: dict)
        donde propagacion_meta contiene dias_propagados, etc_acumulada_mm,
        lluvia_acumulada_mm, deficit_acumulado_mm, metodo y advertencias.
    """
    # 1. Ultimo riego con agua real (volumen > 0).
    # Se excluyen los registros de "ignorada" (volumen = 0) para no
    # confundir al propagador: un no-riego no recarga el suelo.
    res_riego = await db.execute(
        select(HistorialRiego.fecha_riego, HistorialRiego.lamina_mm)
        .where(
            HistorialRiego.id_parcela == id_parcela,
            HistorialRiego.fecha_riego <= fecha_ref,
            HistorialRiego.volumen_m3_ha > 0,
        )
        .order_by(HistorialRiego.fecha_riego.desc())
        .limit(1)
    )
    ultimo_riego = res_riego.first()

    if ultimo_riego is None:
        # Sin historial de riego: fallback al punto medio
        humedad_mid = (cc_pct + pmp_pct) / 2.0
        deficit = max(0.0, (cc_pct - humedad_mid) * prof_raiz_m * 10.0)
        return humedad_mid, {
            "dias_propagados": 0,
            "etc_acumulada_mm": 0.0,
            "lluvia_acumulada_mm": 0.0,
            "deficit_acumulado_mm": round(deficit, 2),
            "metodo": "fallback_midpoint",
            "advertencias": [
                "Sin historial de riego para esta parcela. "
                "Se uso el punto medio CC+PMP como humedad inicial."
            ],
        }

    fecha_ultimo_riego = ultimo_riego.fecha_riego

    # 2. Clima del periodo de propagacion
    res_clima = await db.execute(
        select(ClimaDiario)
        .where(
            ClimaDiario.id_parcela == id_parcela,
            ClimaDiario.fecha > fecha_ultimo_riego,
            ClimaDiario.fecha <= fecha_ref,
        )
        .order_by(ClimaDiario.fecha.asc())
    )
    clima_periodo = res_clima.scalars().all()

    # 3. Propagar
    resultado = propagar_balance_hidrico(
        fecha_ultimo_riego=fecha_ultimo_riego,
        fecha_ref=fecha_ref,
        cc_pct=cc_pct,
        pmp_pct=pmp_pct,
        prof_raiz_m=prof_raiz_m,
        cultivo_nombre=cultivo_nombre,
        dias_siembra_ref=dias_siembra_ref,
        clima_records=clima_periodo,
    )

    return resultado["humedad_actual_pct"], resultado


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

    # Kc desde el ORM CultivoCatalogo — fuente de verdad es la BD, no KC_TABLE.
    # obtener_kc_desde_catalogo() lee kc_inicial/kc_medio/kc_final y
    # dias_etapa_* directamente del objeto; cualquier cambio en cultivos_catalogo
    # se refleja sin modificar balance_hidrico.py.
    kc = obtener_kc_desde_catalogo(cultivo, dias_siembra)

    # -- 3. Clima del dia -----------------------------------------------------
    # Busca el registro más reciente disponible en o antes de la fecha
    # solicitada. Evita 404 cuando el ETL no cubre la fecha exacta (lag de
    # NASA POWER, parcela recién creada, anio_fin < hoy).
    res_cl = await db.execute(
        select(ClimaDiario)
        .where(
            ClimaDiario.id_parcela == parcela_id,
            ClimaDiario.fecha <= fecha,
        )
        .order_by(ClimaDiario.fecha.desc())
        .limit(1)
    )
    clima = res_cl.scalar_one_or_none()

    metodo_eto = "penman_monteith"
    advertencia = None

    if clima is None:
        raise HTTPException(
            404,
            f"Sin datos climáticos para parcela {parcela_id}. "
            "El ETL aún no corrió para esta parcela. "
            f"Comando: cd backend && python -m tools.nasa_power_etl --parcela {parcela_id}",
        )

    # dia_del_ano calculado sobre la fecha real del dato (consistencia FAO-56).
    fecha_clima_usada = clima.fecha
    dias_desfase = (fecha - fecha_clima_usada).days
    dia_del_ano = fecha_clima_usada.timetuple().tm_yday

    if dias_desfase > 0:
        advertencia = (
            f"Sin datos climáticos para {fecha}. "
            f"Se usaron los más recientes: {fecha_clima_usada} "
            f"({dias_desfase} {'día' if dias_desfase == 1 else 'días'} de desfase). "
            "Recomendación orientativa — corre el ETL para mayor precisión."
        )

    precipitacion = float(clima.lluvia or 0.0)

    if clima.et0 is not None:
        # ETo pre-calculada por el ETL de NASA POWER — evita recalcular
        eto = float(clima.et0)
        metodo_eto = "et0_precalculado"
    elif all(
        v is not None for v in [
            clima.t_max, clima.t_min, clima.humedad_rel, clima.viento, clima.radiacion,
        ]
    ):
        # Datos crudos completos → Penman-Monteith en vivo
        eto = calcular_eto_penman_monteith(
            tmax=float(clima.t_max),
            tmin=float(clima.t_min),
            humedad_rel=float(clima.humedad_rel),
            viento_ms=float(clima.viento),
            radiacion_solar_mj=float(clima.radiacion),
            dia_del_ano=dia_del_ano,
        )
    elif clima.t_max is not None and clima.t_min is not None:
        # Datos parciales → Hargreaves fallback
        metodo_eto = "hargreaves"
        advertencia = (
            f"clima_diario para {fecha_clima_usada} tiene datos incompletos "
            "(faltan HR, viento o radiación). Se usó Hargreaves como respaldo."
        )
        eto = calcular_eto_hargreaves(
            tmax=float(clima.t_max),
            tmin=float(clima.t_min),
            dia_del_ano=dia_del_ano,
        )
    else:
        raise HTTPException(
            404,
            f"No hay datos climáticos utilizables para parcela {parcela_id} en fecha {fecha}. "
            "El registro existe pero no tiene et0 ni temperatura.",
        )

    # -- 4. Calculo del balance -----------------------------------------------
    etc = eto * kc

    # Convertir CC y PMP de m³/m³ (BD) a porcentaje para el motor
    cc_pct = float(parcela.capacidad_campo) * 100.0 if parcela.capacidad_campo else 34.0
    pmp_pct = float(parcela.punto_marchitez) * 100.0 if parcela.punto_marchitez else 18.0
    prof_raiz_m = (parcela.profundidad_raiz_cm or 60) / 100.0

    # Humedad actual: balance acumulado desde el ultimo riego real
    humedad_actual_pct, propagacion_meta = await _estimar_humedad_actual(
        db=db,
        id_parcela=parcela.id_parcela,
        cc_pct=cc_pct,
        pmp_pct=pmp_pct,
        prof_raiz_m=prof_raiz_m,
        cultivo_nombre=cultivo.nombre_comun,
        dias_siembra_ref=dias_siembra,
        fecha_ref=fecha,
    )

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
            "humedad_metodo": propagacion_meta.get("metodo", "desconocido"),
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
        "fecha_clima_usada": fecha_clima_usada.isoformat(),
        "dias_desfase_clima": dias_desfase,
        "metodo_eto": metodo_eto,
        "eto_mm": round(eto, 2),
        "kc": round(kc, 3),
        "etc_mm": round(etc, 2),
        "balance": balance,
        "costo": costo,
        "dias_sin_riego": dias_sin,
        "nivel_urgencia": nivel_urgencia,
        "persistido": True,
        "propagacion_hidrica": propagacion_meta,
    }

    if advertencia:
        resultado["advertencia"] = advertencia

    return resultado


# -- Endpoint legacy: todos los parametros por query string, sin BD -----------

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
    humedad_actual_pct: float = 60.0,
    capacidad_campo_pct: float = 34.0,
    punto_marchitez_pct: float = 18.0,
    profundidad_raiz_m: float = 0.60,
):
    """Calcula el balance hidrico recibiendo todos los parametros por query string.

    No lee de BD ni persiste la recomendacion. Util para pruebas rapidas y
    demos sin dependencia de datos semilla.
    """
    try:
        kc = obtener_kc(cultivo, dias_siembra)
    except ValueError as e:
        raise HTTPException(400, str(e))

    dia_del_ano = date.today().timetuple().tm_yday
    metodo_eto = "penman_monteith"

    if (
        humedad_rel is not None
        and viento is not None
        and radiacion is not None
    ):
        eto = calcular_eto_penman_monteith(
            tmax=tmax,
            tmin=tmin,
            humedad_rel=humedad_rel,
            viento_ms=viento,
            radiacion_solar_mj=radiacion,
            dia_del_ano=dia_del_ano,
        )
    else:
        metodo_eto = "hargreaves"
        eto = calcular_eto_hargreaves(
            tmax=tmax,
            tmin=tmin,
            dia_del_ano=dia_del_ano,
        )

    etc = eto * kc

    balance = calcular_balance_hidrico(
        etc_mm=etc,
        precipitacion_mm=precipitacion,
        humedad_actual_pct=humedad_actual_pct,
        capacidad_campo_pct=capacidad_campo_pct,
        punto_marchitez_pct=punto_marchitez_pct,
        profundidad_raiz_m=profundidad_raiz_m,
    )

    costo = calcular_costo_riego(volumen_m3=balance["volumen_m3_ha"])

    return {
        "parcela_id": parcela_id,
        "cultivo": cultivo,
        "fecha_calculo": date.today().isoformat(),
        "metodo_eto": metodo_eto,
        "eto_mm": round(eto, 2),
        "kc": round(kc, 3),
        "etc_mm": round(etc, 2),
        "balance": balance,
        "costo": costo,
        "persistido": False,
    }


# -- Endpoint curva Kc por nombre (legacy, usa KC_TABLE) ----------------------

@router.get("/kc/{cultivo}", tags=["Motor FAO-56"])
async def get_curva_kc(cultivo: str):
    """Retorna la curva Kc completa de un cultivo (FAO-56 Tabla 12).

    Lee desde KC_TABLE (hardcodeado). Para obtener la curva desde la BD
    (fuente de verdad), usa GET /api/cultivos/{id_cultivo}/kc.

    Incluye las 4 etapas fenologicas con sus rangos de dias y Kc.
    """
    try:
        return obtener_curva_kc(cultivo)
    except ValueError as e:
        raise HTTPException(400, str(e))


# -- Endpoint curva Kc por id desde BD (fuente de verdad) ---------------------

@router.get("/cultivos/{id_cultivo}/kc", tags=["Motor FAO-56"])
async def get_curva_kc_desde_bd(
    id_cultivo: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Retorna la curva Kc completa de un cultivo leyendo desde cultivos_catalogo.

    A diferencia de GET /kc/{cultivo} (KC_TABLE hardcodeado), este endpoint
    usa la BD como fuente de verdad: refleja cualquier actualización en los
    parámetros FAO-56 sin necesidad de modificar código.
    """
    res = await db.execute(
        select(CultivoCatalogo).where(CultivoCatalogo.id_cultivo == id_cultivo)
    )
    cultivo = res.scalar_one_or_none()
    if cultivo is None:
        raise HTTPException(404, f"Cultivo {id_cultivo} no encontrado en cultivos_catalogo.")
    return obtener_curva_kc_desde_catalogo(cultivo)


# -- Endpoint: listar todos los cultivos del catálogo -------------------------

@router.get("/cultivos", tags=["Motor FAO-56"])
async def get_cultivos(db: AsyncSession = Depends(get_db)):
    """Lista todos los cultivos registrados en cultivos_catalogo.

    Retorna los parámetros FAO-56 completos (Kc, Ky, etapas fenológicas,
    rendimiento potencial) para cada especie. Útil para poblar selects en
    el frontend sin hardcodear el catálogo en el cliente.
    """
    res = await db.execute(select(CultivoCatalogo))
    cultivos = res.scalars().all()
    return [
        {
            "id_cultivo": str(c.id_cultivo),
            "nombre_comun": c.nombre_comun,
            "nombre_cientifico": c.nombre_cientifico,
            "kc_inicial": float(c.kc_inicial),
            "kc_medio": float(c.kc_medio),
            "kc_final": float(c.kc_final),
            "ky_total": float(c.ky_total),
            "dias_etapa_inicial": c.dias_etapa_inicial,
            "dias_etapa_desarrollo": c.dias_etapa_desarrollo,
            "dias_etapa_media": c.dias_etapa_media,
            "dias_etapa_final": c.dias_etapa_final,
            "ciclo_total_dias": c.ciclo_total_dias,
            "rendimiento_potencial_ton": float(c.rendimiento_potencial_ton) if c.rendimiento_potencial_ton else None,
        }
        for c in cultivos
    ]
