"""
actuadores_api.py — Endpoints REST para control de actuadores de riego — MILPÍN AgTech v2.0

Expone el sistema FAO-56 + XGBoost como API REST de control de actuadores.
El prefijo /api es agregado por main.py al registrar el router.

Endpoints:
    POST  /api/actuadores/{id_parcela}/activar      → Evaluar + generar comando de riego
    GET   /api/actuadores/{id_parcela}/estado        → Estado actual del actuador (en memoria)
    POST  /api/actuadores/{id_parcela}/detener       → Detener/cancelar riego activo
    GET   /api/actuadores/modelo/metricas            → Métricas del modelo XGBoost
    POST  /api/actuadores/modelo/reentrenar          → Diagnóstico de datos para reentrenamiento
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.actuador_control import (
    detener_actuador,
    evaluar_y_comandar,
    obtener_estado_parcela,
)
from database import get_db

router = APIRouter(tags=["Control de Actuadores (FAO-56 + XGBoost)"])


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class ActivarRequest(BaseModel):
    """Parámetros para activar el pipeline de evaluación de riego."""
    dias_siembra: int = Field(
        default=60, ge=0, le=365,
        description="Días desde la siembra — determina Kc FAO-56 (etapa fenológica)"
    )
    dias_sin_riego: int = Field(
        default=0, ge=0, le=60,
        description="Días desde el último riego — afecta urgencia y riesgo de estrés"
    )
    humedad_suelo_pct: Optional[float] = Field(
        default=None, ge=0.0, le=100.0,
        description="Humedad volumétrica actual del suelo (%). None = promedio CC/PMP"
    )
    precipitacion_mm: float = Field(
        default=0.0, ge=0.0,
        description="Precipitación del día (mm)"
    )
    forzar: bool = Field(
        default=False,
        description=(
            "Si True, genera el comando de riego aunque el modelo diga que no se requiere. "
            "Útil para riegos preventivos o pruebas de actuador."
        )
    )


class ComandoOut(BaseModel):
    """Respuesta completa del pipeline FAO-56 + XGBoost."""
    id_comando: str
    id_parcela: str
    accion: str
    duracion_min: float
    volumen_objetivo_m3: float
    lamina_objetivo_mm: float
    caudal_ls: float
    estado: str
    confianza_xgboost: float
    riesgo_estres: float
    nivel_urgencia: str
    algoritmo: str
    eto_mm: float
    kc: float
    etc_mm: float
    deficit_mm: float
    timestamp_generacion: str
    id_historial_riego: Optional[str]
    observaciones: Optional[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/actuadores/{id_parcela}/activar",
    response_model=ComandoOut,
    summary="Activar pipeline FAO-56 + XGBoost para una parcela",
    description=(
        "Ejecuta el pipeline completo de decisión de riego:\n\n"
        "1. **FAO-56** calcula ETo (Penman-Monteith o Hargreaves), Kc, ETc y balance hídrico.\n"
        "2. **XGBoost** predice P(requiere_riego), lamina_ajustada_mm y riesgo_estres.\n"
        "3. Si el modelo decide regar, persiste en `historial_riego` con `origen_decision='sistema'`.\n\n"
        "**Acción='standby'**: el sistema evaluó que no se requiere riego hoy.\n"
        "**Acción='abrir'**: se recomienda regar. El evento queda en historial.\n\n"
        "> Nota: ejecución física es simulada (no hay hardware real en esta versión)."
    ),
)
async def activar_actuador(
    id_parcela: uuid.UUID,
    body: ActivarRequest,
    db: AsyncSession = Depends(get_db),
) -> ComandoOut:
    try:
        comando = await evaluar_y_comandar(
            id_parcela=id_parcela,
            db=db,
            dias_siembra=body.dias_siembra,
            dias_sin_riego=body.dias_sin_riego,
            humedad_suelo_pct=body.humedad_suelo_pct,
            precipitacion_mm=body.precipitacion_mm,
            forzar=body.forzar,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error en pipeline de control: {exc}"
        )

    return ComandoOut(
        id_comando=comando.id_comando,
        id_parcela=comando.id_parcela,
        accion=comando.accion,
        duracion_min=comando.duracion_min,
        volumen_objetivo_m3=comando.volumen_objetivo_m3,
        lamina_objetivo_mm=comando.lamina_objetivo_mm,
        caudal_ls=comando.caudal_ls,
        estado=comando.estado,
        confianza_xgboost=comando.confianza_xgboost,
        riesgo_estres=comando.riesgo_estres,
        nivel_urgencia=comando.nivel_urgencia,
        algoritmo=comando.algoritmo,
        eto_mm=comando.eto_mm,
        kc=comando.kc,
        etc_mm=comando.etc_mm,
        deficit_mm=comando.deficit_mm,
        timestamp_generacion=comando.timestamp_generacion,
        id_historial_riego=comando.id_historial_riego,
        observaciones=comando.observaciones,
    )


@router.get(
    "/actuadores/{id_parcela}/estado",
    summary="Estado actual del actuador de una parcela",
    description=(
        "Retorna el último comando generado para la parcela (almacenado en memoria).\n\n"
        "> Estado se pierde al reiniciar el backend. "
        "En producción IoT: consultar directamente el broker MQTT o PLC."
    ),
)
async def estado_actuador(id_parcela: uuid.UUID):
    estado = obtener_estado_parcela(str(id_parcela))
    if not estado:
        return {
            "id_parcela": str(id_parcela),
            "estado": "inactivo",
            "mensaje": "Sin comandos previos para esta parcela en la sesión actual.",
        }
    return {"id_parcela": str(id_parcela), **estado}


@router.post(
    "/actuadores/{id_parcela}/detener",
    summary="Detener riego activo de una parcela",
    description=(
        "Marca el actuador de la parcela como 'cancelado' en memoria.\n\n"
        "En producción IoT: enviar señal de cierre al actuador físico (válvula/bomba)."
    ),
)
async def detener_riego(id_parcela: uuid.UUID):
    resultado = detener_actuador(str(id_parcela))
    return {"id_parcela": str(id_parcela), **resultado}


@router.get(
    "/actuadores/modelo/metricas",
    summary="Métricas del modelo XGBoost activo",
    description=(
        "Retorna las métricas de rendimiento del modelo XGBoost cargado.\n\n"
        "**Importante**: con datos sintéticos FAO-56, las métricas muestran cuán bien "
        "XGBoost aproxima el motor agronómico, NO su precisión sobre campo real."
    ),
)
async def metricas_modelo():
    try:
        from ml.inference.xgboost_riego import MODELS_DIR, obtener_predictor
        predictor = obtener_predictor()
        metricas = predictor.metricas

        if not metricas:
            return {
                "estado": "sin_modelo",
                "mensaje": "El modelo aún no ha sido entrenado.",
            }

        es_sintetico = metricas.get("tipo_datos") == "sintetico-fao56"

        return {
            "estado": "ok",
            "tipo_datos": metricas.get("tipo_datos", "desconocido"),
            "n_muestras_entrenamiento": metricas.get("n_muestras_entrenamiento"),
            "features": [
                "deficit_mm", "etc_mm", "eto_mm", "kc", "dias_sin_riego",
                "humedad_suelo_pct", "capacidad_campo_pct", "punto_marchitez_pct",
                "profundidad_raiz_m", "area_ha", "tipo_suelo_enc",
            ],
            "modelos": {
                "clasificador_requiere_riego": metricas.get("clasificador", {}),
                "regresor_lamina_mm":          metricas.get("lamina", {}),
                "regresor_riesgo_estres":       metricas.get("estres", {}),
            },
            "modelos_dir": str(MODELS_DIR),
            "advertencia": (
                "Modelo entrenado con datos sintéticos FAO-56. "
                "Las métricas reflejan la aproximación al motor agronómico, "
                "no la precisión sobre datos reales de campo. "
                "Usar POST /actuadores/modelo/reentrenar para ver cuándo habrá "
                "suficientes datos reales."
            ) if es_sintetico else None,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error cargando modelo: {exc}")


@router.post(
    "/actuadores/modelo/reentrenar",
    summary="Diagnóstico de datos para reentrenamiento XGBoost",
    description=(
        "Evalúa cuántos datos reales hay disponibles en `historial_riego` y "
        "`recomendaciones` para reentrenar el modelo.\n\n"
        "El reentrenamiento completo requiere **mínimo 100 registros** con feedback "
        "(recomendado 500+). Mientras tanto, el modelo sintético FAO-56 sigue activo."
    ),
)
async def diagnostico_reentrenamiento(
    db: AsyncSession = Depends(get_db),
    n_minimo: int = Query(
        default=500, ge=100,
        description="Mínimo de feedbacks requeridos para reentrenar"
    ),
):
    from models import HistorialRiego, Recomendacion

    # Contar datos disponibles
    res_riego = await db.execute(
        select(func.count()).select_from(HistorialRiego)
    )
    n_riego = int(res_riego.scalar() or 0)

    res_feedback = await db.execute(
        select(func.count()).select_from(Recomendacion)
        .where(Recomendacion.aceptada.in_(["aceptada", "modificada"]))
    )
    n_feedback = int(res_feedback.scalar() or 0)

    res_sistema = await db.execute(
        select(func.count()).select_from(HistorialRiego)
        .where(HistorialRiego.origen_decision == "sistema")
    )
    n_sistema = int(res_sistema.scalar() or 0)

    listo = n_feedback >= n_minimo

    return {
        "listo_para_reentrenamiento": listo,
        "datos_disponibles": {
            "eventos_riego_total": n_riego,
            "eventos_origen_sistema": n_sistema,
            "recomendaciones_con_feedback": n_feedback,
            "minimo_requerido": n_minimo,
            "faltante": max(0, n_minimo - n_feedback),
        },
        "mensaje": (
            f"✓ Suficientes datos ({n_feedback} feedbacks). "
            "Ejecutar tools/retrain_pipeline.py para reentrenar con datos reales."
        ) if listo else (
            f"Datos insuficientes: {n_feedback}/{n_minimo} feedbacks disponibles. "
            f"Faltan {max(0, n_minimo - n_feedback)} registros con feedback. "
            "El modelo sintético FAO-56 sigue activo."
        ),
        "proximos_pasos": [
            "Usar el sistema para que los agricultores acepten/rechacen recomendaciones",
            f"Cuando haya {n_minimo}+ feedbacks, ejecutar tools/retrain_pipeline.py",
            "Llamar nuevamente a este endpoint para confirmar que el modelo se actualizó",
        ],
    }
