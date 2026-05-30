"""
ml_api.py — Endpoints de Machine Learning para MILPÍN AgTech v2.0

Endpoints:
    GET /api/ml/prediccion/{id_parcela}
        XGBoost (3 modelos): requiere_riego, lamina_ajustada_mm, riesgo_estres.
        Lee parcela + última recomendación desde BD.
        Si la BD no tiene datos suficientes, usa parámetros por defecto del tipo de suelo.

    GET /api/ml/anomalias?solo_anomalias=true&limit=50
        Isolation Forest sobre historial_riego (parcela × ciclo).
        Fallback a CSV sintético si la BD tiene < 50 registros.

    GET /api/ml/metricas
        Métricas de ambos modelos (XGBoost + Isolation Forest).
        Incluye disclaimer sobre datos sintéticos.

    GET /api/ml/drift?min_rows=50&last_n=2000
        Compara distribución de features de entrenamiento vs producción.
        PSI + KS por feature. Requiere referencia generada con train_eval_promote.py
        y al menos min_rows predicciones en el log de producción.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ml.inference.anomaly_detector import obtener_detector
from ml.inference.xgboost_riego import TIPO_SUELO_ENC, obtener_predictor
from database import get_db
from models import CultivoCatalogo, Parcela, Recomendacion

router = APIRouter(tags=["Machine Learning"])


# ── 4. Drift monitoring ───────────────────────────────────────────────────────

@router.get("/ml/drift")
async def ml_drift(
    min_rows: int = Query(default=50, ge=10, description="Mínimo de predicciones requeridas"),
    last_n:   int = Query(default=2000, ge=50, description="Usar solo las últimas N predicciones"),
):
    """
    Compara distribución de features de entrenamiento vs producción.

    Requiere:
        - data/snapshots/xgb_ref_dist.joblib (generado por train_eval_promote.py)
        - data/snapshots/xgb_prod_inputs.jsonl (log automático de predicciones)

    Retorna PSI + KS test por feature con clasificación OK / MONITOREAR / CRITICO.
    """
    from ml.monitoring.drift_check import check_drift, REF_PATH, PROD_LOG
    import sys
    from pathlib import Path

    # Asegurar que el repo root esté en sys.path (igual que main.py)
    repo_root = str(Path(__file__).parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    if not REF_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Referencia de entrenamiento no encontrada. "
                "Ejecutar: python ML/pipelines/train_eval_promote.py"
            ),
        )
    if not PROD_LOG.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Log de producción no encontrado. "
                "Se crea automáticamente cuando el modelo recibe predicciones."
            ),
        )

    import json
    import numpy as np

    def _numpy_to_python(obj):
        if isinstance(obj, np.bool_):    return bool(obj)
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        raise TypeError(f"No serializable: {type(obj)}")

    try:
        results = check_drift(min_prod_rows=min_rows, last_n=last_n)
        # Garantizar que no queden tipos numpy en la respuesta
        results = json.loads(json.dumps(results, default=_numpy_to_python))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al calcular drift: {exc}")

    n_critico    = sum(1 for r in results if r["status"] == "CRITICO")
    n_monitorear = sum(1 for r in results if r["status"] == "MONITOREAR")
    n_ok         = sum(1 for r in results if r["status"] == "OK")
    estado_global = "CRITICO" if n_critico > 0 else ("MONITOREAR" if n_monitorear > 0 else "OK")

    return {
        "estado_global":  estado_global,
        "n_critico":      n_critico,
        "n_monitorear":   n_monitorear,
        "n_ok":           n_ok,
        "features":       results,
        "config": {
            "min_rows": min_rows,
            "last_n":   last_n,
            "ref_path": str(REF_PATH),
            "prod_log": str(PROD_LOG),
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _defaults_por_tipo_suelo(tipo_suelo: Optional[str]) -> dict:
    """
    Valores por defecto de CC, PMP y profundidad de raíz por tipo de suelo.
    Fuente: FAO-56 Tabla 2 + parámetros del Valle del Yaqui.
    """
    ts = (tipo_suelo or "franco").lower().strip()
    defaults = {
        "arcilloso":      {"cc": 40.0, "pmp": 24.0, "prof": 0.60},
        "franco-arcilloso": {"cc": 34.0, "pmp": 19.0, "prof": 0.65},
        "franco":         {"cc": 29.5, "pmp": 15.0, "prof": 0.70},
        "franco-arenoso": {"cc": 22.0, "pmp": 11.0, "prof": 0.55},
    }
    return defaults.get(ts, defaults["franco"])


# ── 1. Predicción XGBoost por parcela ────────────────────────────────────────

@router.get("/ml/prediccion/{id_parcela}")
async def prediccion_xgboost(
    id_parcela: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Genera predicción XGBoost para una parcela.

    Pasos:
        1. Lee parcela de BD (parámetros edáficos, cultivo).
        2. Lee última recomendación FAO-56 (déficit, ETc, ETo, Kc).
           Si no hay recomendación, usa defaults conservadores.
        3. Llama a XGBoostRiego.predecir() con los parámetros obtenidos.
        4. Retorna predicción + metadatos del modelo.

    Nota: si XGBoost no está disponible, hace fallback a reglas FAO-56.
    """
    # 1. Obtener parcela
    result = await db.execute(
        select(Parcela).where(Parcela.id_parcela == id_parcela)
    )
    parcela = result.scalar_one_or_none()
    if parcela is None:
        raise HTTPException(status_code=404, detail="Parcela no encontrada")

    # 2. Obtener parámetros de suelo
    deflt = _defaults_por_tipo_suelo(parcela.tipo_suelo)
    cc_pct  = float(parcela.capacidad_campo or deflt["cc"] / 100.0) * 100.0
    pmp_pct = float(parcela.punto_marchitez or deflt["pmp"] / 100.0) * 100.0
    prof_m  = float((parcela.profundidad_raiz_cm or int(deflt["prof"] * 100))) / 100.0
    area_ha = float(parcela.area_ha or 5.0)
    tipo_suelo = str(parcela.tipo_suelo or "franco")

    # 3. Intentar leer última recomendación FAO-56 para extraer inputs del modelo
    rec_result = await db.execute(
        select(Recomendacion)
        .where(Recomendacion.id_parcela == id_parcela)
        .order_by(Recomendacion.fecha_generacion.desc())
        .limit(1)
    )
    ultima_rec = rec_result.scalar_one_or_none()

    if ultima_rec is not None:
        deficit_mm      = float(ultima_rec.deficit_acumulado_mm or 0.0)
        etc_mm          = float(ultima_rec.etc_calculada or 4.5)
        eto_mm          = float(ultima_rec.eto_referencia or 6.0)
        kc              = etc_mm / eto_mm if eto_mm > 0 else 0.75
        dias_sin_riego  = int(ultima_rec.dias_sin_riego or 7)
        params_json     = ultima_rec.parametros_json or {}
        humedad_actual  = float(params_json.get("humedad_actual_pct", (cc_pct + pmp_pct) / 2.0))
        fuente_params   = "ultima_recomendacion"
    else:
        # Fallback: valores conservadores basados en el tipo de suelo
        deficit_mm     = (cc_pct - pmp_pct) * prof_m * 10.0 * 0.40  # 40% del ADT
        etc_mm         = 5.0
        eto_mm         = 6.5
        kc             = 0.75
        dias_sin_riego = 7
        humedad_actual = cc_pct - (cc_pct - pmp_pct) * 0.40
        fuente_params  = "defaults_tipo_suelo"

    # 4. Predicción XGBoost
    predictor = obtener_predictor()
    pred = predictor.predecir(
        deficit_mm=deficit_mm,
        etc_mm=etc_mm,
        eto_mm=eto_mm,
        kc=kc,
        dias_sin_riego=dias_sin_riego,
        humedad_suelo_pct=humedad_actual,
        capacidad_campo_pct=cc_pct,
        punto_marchitez_pct=pmp_pct,
        profundidad_raiz_m=prof_m,
        area_ha=area_ha,
        tipo_suelo=tipo_suelo,
    )

    return {
        "id_parcela":         str(id_parcela),
        "nombre_parcela":     parcela.nombre_parcela,
        "tipo_suelo":         tipo_suelo,
        # Resultados del modelo
        "requiere_riego":     pred.requiere_riego,
        "probabilidad_riego": pred.probabilidad_riego,
        "lamina_ajustada_mm": pred.lamina_ajustada_mm,
        "riesgo_estres":      pred.riesgo_estres,
        "nivel_urgencia":     pred.nivel_urgencia,
        "confianza":          pred.confianza,
        "algoritmo":          pred.algoritmo,
        # Inputs usados (para trazabilidad)
        "inputs_usados": {
            "fuente":          fuente_params,
            "deficit_mm":      round(deficit_mm, 2),
            "etc_mm":          round(etc_mm, 3),
            "eto_mm":          round(eto_mm, 3),
            "kc":              round(kc, 3),
            "dias_sin_riego":  dias_sin_riego,
            "humedad_pct":     round(humedad_actual, 2),
            "cc_pct":          round(cc_pct, 2),
            "pmp_pct":         round(pmp_pct, 2),
        },
        "disclaimer": (
            "Modelo entrenado con datos sintéticos FAO-56. "
            "No sustituye el criterio agronómico del técnico de campo."
        ),
    }


# ── 2. Detección de anomalías ────────────────────────────────────────────────

@router.get("/ml/anomalias")
async def anomalias_deteccion(
    solo_anomalias: bool = Query(
        default=True,
        description="Si True, retorna solo los pares (parcela × ciclo) anómalos.",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Máximo de resultados a retornar.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Detecta ciclos de riego anómalos usando Isolation Forest.

    Estrategia de datos:
        1. Intenta leer historial_riego desde PostgreSQL.
        2. Si hay < 50 registros, hace fallback a historial_riego.csv sintético.

    Features usadas por ciclo (parcela × ciclo):
        vol_total_m3_ha, n_eventos, vol_media_evento, vol_cv,
        max_gap_dias, costo_total_mxn, sistema_riego_num

    Retorna pares ordenados por anomaly_score (más anómalos primero).
    """
    detector = obtener_detector()

    if not detector.entrenado:
        raise HTTPException(
            status_code=503,
            detail="Modelo de anomalías no disponible. Reinicia el servidor.",
        )

    try:
        resultados = await detector.detectar_desde_db(
            db=db, solo_anomalias=solo_anomalias
        )
    except Exception as exc:
        # Si falla la BD, intentar CSV directamente
        import logging
        logging.getLogger(__name__).warning(
            "anomalias_deteccion: error en BD, fallback a CSV — %s", exc
        )
        resultados = detector.detectar_desde_csv(solo_anomalias=solo_anomalias)

    total_retornados = len(resultados[:limit])
    total_anomalias  = sum(1 for r in resultados if r["es_anomalia"])

    return {
        "total_pares_analizados": len(resultados),
        "total_anomalias":        total_anomalias,
        "pct_anomalias":          round(
            total_anomalias / len(resultados) * 100 if resultados else 0, 2
        ),
        "resultados": resultados[:limit],
        "config_modelo": {
            "contamination": 0.12,
            "n_estimators":  160,
            "features":      [
                "vol_total_m3_ha",
                "n_eventos",
                "vol_media_evento",
                "vol_cv",
                "max_gap_dias",
                "costo_total_mxn",
                "sistema_riego_num",
            ],
        },
        "disclaimer": (
            "Modelo entrenado con datos sintéticos. "
            "Precision=0.586 · Recall=0.466 · F1=0.519 contra ground truth sintético. "
            "Validar con datos reales del DR-041 antes de uso operativo."
        ),
    }


# ── 3. Métricas de modelos ────────────────────────────────────────────────────

@router.get("/ml/metricas")
async def ml_metricas():
    """
    Retorna métricas de los modelos de ML actualmente cargados.

    Incluye:
        · XGBoost (3 modelos): clasificador, regresor lámina, regresor estrés
        · Isolation Forest: precision, recall, f1 vs ground truth sintético

    Los valores son sobre datos sintéticos FAO-56, no sobre datos reales del DR-041.
    """
    predictor = obtener_predictor()
    detector  = obtener_detector()

    return {
        "xgboost_riego": {
            "descripcion": (
                "3 modelos: P(requiere_riego), lamina_ajustada_mm, riesgo_estres. "
                "Entrenados con 4,000 muestras sintéticas FAO-56."
            ),
            "metricas":  predictor.metricas,
            "entrenado": predictor.entrenado,
            "features":  [
                "deficit_mm", "etc_mm", "eto_mm", "kc",
                "dias_sin_riego", "humedad_suelo_pct",
                "capacidad_campo_pct", "punto_marchitez_pct",
                "profundidad_raiz_m", "area_ha", "tipo_suelo_enc",
            ],
        },
        "isolation_forest": {
            "descripcion": (
                "Detección de anomalías a nivel (parcela × ciclo). "
                "Entrenado con historial_riego.csv sintético."
            ),
            "metricas":  detector.metricas,
            "entrenado": detector.entrenado,
            "features":  [
                "vol_total_m3_ha", "n_eventos", "vol_media_evento",
                "vol_cv", "max_gap_dias", "costo_total_mxn", "sistema_riego_num",
            ],
        },
        "disclaimer": (
            "Todos los modelos están entrenados con datos sintéticos generados por "
            "tools/generar_datos_sinteticos.py sobre el motor FAO-56. "
            "Las métricas representan el desempeño sobre ese generador, "
            "NO sobre datos reales del DR-041."
        ),
    }
