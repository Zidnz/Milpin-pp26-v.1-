"""
ml/inference/xgboost_riego.py — Wrapper de inferencia XGBoost para MILPÍN AgTech v2.0

Tres predictores entrenados sobre features agronómicos derivados de FAO-56:
    1. XGBClassifier  → P(requiere_riego) — probabilidad 0-1
    2. XGBRegressor   → lamina_ajustada_mm — lámina de riego óptima
    3. XGBRegressor   → riesgo_estres — score de estrés hídrico 0-1

FASE B (2026-05-16):
    - El bloque auto-entrena fue eliminado. Este módulo es inferencia pura.
    - Para (re)entrenar: usar ml/training/xgboost_riego/train.py
    - Los modelos se cargan desde MODELS_DIR (backend/models_ml/ por defecto).
    - Si los joblibs no existen, se lanza FileNotFoundError con instrucciones claras.

LIMITACIÓN CONOCIDA:
    Con datos sintéticos XGBoost aprende a aproximar FAO-56, no a mejorar sobre él.
    El valor real aparece con ≥500 eventos reales en historial_riego + recomendaciones.

Uso:
    predictor = obtener_predictor()
    pred = predictor.predecir(deficit_mm=45.0, etc_mm=6.2, eto_mm=7.5, ...)
    print(pred.requiere_riego, pred.lamina_ajustada_mm, pred.riesgo_estres)
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Rutas de persistencia ─────────────────────────────────────────────────────
# Desde ml/inference/ subimos 2 niveles (→ repo root) y luego a backend/models_ml/
MODELS_DIR = Path(__file__).parents[2] / "backend" / "models_ml"
PROD_LOG   = Path(__file__).parents[2] / "data" / "snapshots" / "xgb_prod_inputs.jsonl"

# ── Features de entrada (orden fijo — no cambiar sin reentrenar) ──────────────
FEATURE_NAMES = [
    "deficit_mm",
    "etc_mm",
    "eto_mm",
    "kc",
    "dias_sin_riego",
    "humedad_suelo_pct",
    "capacidad_campo_pct",
    "punto_marchitez_pct",
    "profundidad_raiz_m",
    "area_ha",
    "tipo_suelo_enc",
]

# ── Encoding de tipos de suelo (Valle del Yaqui) ──────────────────────────────
TIPO_SUELO_ENC: dict[str, int] = {
    "arcilloso": 0,
    "franco-arcilloso": 1,
    "franco": 2,
    "franco-arenoso": 3,
}


# ── Dataclass de salida ───────────────────────────────────────────────────────

@dataclass
class PrediccionRiego:
    """Resultado de los tres modelos XGBoost para una parcela."""
    requiere_riego: bool                # decisión binaria (threshold 0.50)
    probabilidad_riego: float           # P(riego=1) — XGBClassifier
    lamina_ajustada_mm: float           # lámina recomendada — XGBRegressor
    riesgo_estres: float                # score 0-1 de estrés hídrico — XGBRegressor
    nivel_urgencia: str                 # "critico" | "moderado" | "preventivo"
    algoritmo: str                      # "fao56+xgboost-v1" | "fao56-solo"
    confianza: float                    # alias de probabilidad_riego (para API)


# ── Singleton ─────────────────────────────────────────────────────────────────
_instancia_global: Optional["XGBoostRiego"] = None


def obtener_predictor() -> "XGBoostRiego":
    """Retorna la instancia singleton de XGBoostRiego (lazy init)."""
    global _instancia_global
    if _instancia_global is None:
        _instancia_global = XGBoostRiego()
    return _instancia_global


# ── Clase principal ───────────────────────────────────────────────────────────

class XGBoostRiego:
    """
    Wrapper de inferencia para los tres modelos XGBoost de riego.

    Carga los modelos desde MODELS_DIR al instanciar.
    Si los archivos .joblib no existen, lanza FileNotFoundError con instrucciones
    claras para correr el entrenamiento.

    Para entrenar desde cero:
        python ml/training/xgboost_riego/train.py
    """

    def __init__(self):
        self._clf = None
        self._reg_lamina = None
        self._reg_estres = None
        self._metricas: dict = {}
        self._entrenado: bool = False
        self._cargar_modelos()

    # ── Carga desde disco ─────────────────────────────────────────────────────

    def _cargar_modelos(self) -> None:
        """Carga los tres modelos desde MODELS_DIR. Falla explícitamente si no existen."""
        import joblib

        path_clf     = MODELS_DIR / "xgb_requiere_riego.joblib"
        path_lamina  = MODELS_DIR / "xgb_lamina_ajustada.joblib"
        path_estres  = MODELS_DIR / "xgb_riesgo_estres.joblib"
        path_metrics = MODELS_DIR / "xgb_metricas.joblib"

        missing = [p for p in (path_clf, path_lamina, path_estres) if not p.exists()]
        if missing:
            names = ", ".join(p.name for p in missing)
            raise FileNotFoundError(
                f"Modelos XGBoost no encontrados en {MODELS_DIR}: {names}\n"
                "Para entrenarlos: python ml/training/xgboost_riego/train.py"
            )

        logger.info("XGBoostRiego: cargando modelos desde %s", MODELS_DIR)
        self._clf        = joblib.load(path_clf)
        self._reg_lamina = joblib.load(path_lamina)
        self._reg_estres = joblib.load(path_estres)
        if path_metrics.exists():
            self._metricas = joblib.load(path_metrics)
        self._entrenado = True
        logger.info("XGBoostRiego: modelos cargados OK")

    # ── Predicción ────────────────────────────────────────────────────────────

    def predecir(
        self,
        deficit_mm: float,
        etc_mm: float,
        eto_mm: float,
        kc: float,
        dias_sin_riego: int,
        humedad_suelo_pct: float,
        capacidad_campo_pct: float,
        punto_marchitez_pct: float,
        profundidad_raiz_m: float,
        area_ha: float = 5.0,
        tipo_suelo: str = "franco",
    ) -> PrediccionRiego:
        """
        Genera las tres predicciones para una parcela.

        Si los modelos no están disponibles, hace fallback a reglas FAO-56 puras
        para garantizar que el sistema siempre retorna una respuesta válida.
        """
        if not self._entrenado:
            return self._fallback_fao56(
                deficit_mm=deficit_mm,
                etc_mm=etc_mm,
                humedad_suelo_pct=humedad_suelo_pct,
                capacidad_campo_pct=capacidad_campo_pct,
                punto_marchitez_pct=punto_marchitez_pct,
                profundidad_raiz_m=profundidad_raiz_m,
            )

        tipo_enc = float(TIPO_SUELO_ENC.get(tipo_suelo.lower().strip(), 2))

        X = np.array([[
            deficit_mm,
            etc_mm,
            eto_mm,
            kc,
            float(dias_sin_riego),
            humedad_suelo_pct,
            capacidad_campo_pct,
            punto_marchitez_pct,
            profundidad_raiz_m,
            area_ha,
            tipo_enc,
        ]], dtype=np.float32)

        prob     = float(self._clf.predict_proba(X)[0][1])
        requiere = prob >= 0.50

        lamina  = float(np.clip(self._reg_lamina.predict(X)[0], 0.0, 250.0))
        riesgo  = float(np.clip(self._reg_estres.predict(X)[0], 0.0, 1.0))
        urgencia = self._clasificar_urgencia(prob, riesgo, dias_sin_riego)

        self._log_inputs({
            "deficit_mm":          deficit_mm,
            "etc_mm":              etc_mm,
            "eto_mm":              eto_mm,
            "kc":                  kc,
            "dias_sin_riego":      float(dias_sin_riego),
            "humedad_suelo_pct":   humedad_suelo_pct,
            "capacidad_campo_pct": capacidad_campo_pct,
            "punto_marchitez_pct": punto_marchitez_pct,
            "profundidad_raiz_m":  profundidad_raiz_m,
            "area_ha":             area_ha,
            "tipo_suelo_enc":      tipo_enc,
        })

        return PrediccionRiego(
            requiere_riego=requiere,
            probabilidad_riego=round(prob, 4),
            lamina_ajustada_mm=round(lamina, 2),
            riesgo_estres=round(riesgo, 4),
            nivel_urgencia=urgencia,
            algoritmo="fao56+xgboost-v1",
            confianza=round(prob, 4),
        )

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def _log_inputs(features: dict) -> None:
        """Añade un registro de features al log de producción (para drift monitoring)."""
        try:
            PROD_LOG.parent.mkdir(parents=True, exist_ok=True)
            with PROD_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(features) + "\n")
        except Exception as exc:
            logger.warning("_log_inputs: no se pudo escribir en %s — %s", PROD_LOG, exc)

    @staticmethod
    def _clasificar_urgencia(prob: float, riesgo: float, dias_sin_riego: int) -> str:
        if prob >= 0.80 or riesgo >= 0.80 or dias_sin_riego >= 20:
            return "critico"
        elif prob >= 0.55 or riesgo >= 0.50:
            return "moderado"
        else:
            return "preventivo"

    @staticmethod
    def _fallback_fao56(
        deficit_mm: float,
        etc_mm: float,
        humedad_suelo_pct: float,
        capacidad_campo_pct: float,
        punto_marchitez_pct: float,
        profundidad_raiz_m: float,
    ) -> PrediccionRiego:
        """Fallback a reglas FAO-56 puras cuando XGBoost no está disponible."""
        adt_mm = (capacidad_campo_pct - punto_marchitez_pct) * profundidad_raiz_m * 10.0
        agua_actual_mm = max(
            0.0, (humedad_suelo_pct - punto_marchitez_pct) * profundidad_raiz_m * 10.0
        )
        riesgo = float(np.clip(1.0 - (agua_actual_mm / max(adt_mm, 0.01)), 0.0, 1.0))

        umbral_pct = punto_marchitez_pct + 0.50 * (capacidad_campo_pct - punto_marchitez_pct)
        requiere = humedad_suelo_pct < umbral_pct
        prob = float(np.clip(riesgo, 0.0, 1.0))

        return PrediccionRiego(
            requiere_riego=requiere,
            probabilidad_riego=round(prob, 4),
            lamina_ajustada_mm=round(max(0.0, deficit_mm), 2),
            riesgo_estres=round(riesgo, 4),
            nivel_urgencia="moderado" if requiere else "preventivo",
            algoritmo="fao56-solo",
            confianza=round(prob, 4),
        )

    def reentrenar_con_datos_reales(
        self,
        X: np.ndarray,
        y_riego: np.ndarray,
        y_lamina: np.ndarray,
        y_estres: np.ndarray,
    ) -> None:
        """
        Reentrena los modelos con datos reales de historial_riego + recomendaciones.
        Raises NotImplementedError hasta que ml/training/xgboost_riego/train.py soporte
        datos reales (mínimo 100 muestras, recomendado 500+).
        """
        if len(X) < 100:
            raise ValueError(
                f"Datos insuficientes: {len(X)} muestras. "
                "Mínimo 100 requerido, recomendado 500+."
            )
        raise NotImplementedError(
            "Pipeline de reentrenamiento con datos reales pendiente en "
            "ml/training/xgboost_riego/train.py. "
            f"Datos disponibles: {len(X)} muestras."
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def metricas(self) -> dict:
        return self._metricas

    @property
    def entrenado(self) -> bool:
        return self._entrenado
