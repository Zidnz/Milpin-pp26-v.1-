"""
FeaturePreprocessor — preprocesamiento compartido entre XGBoost e IsolationForest.

Estado: skeleton extraído de xgboost_riego.py y anomaly_detector.py.
La refactorización completa (Fase B) moverá la lógica aquí y los wrappers
importarán desde este módulo.
"""
from __future__ import annotations
import numpy as np
from typing import Dict, Any


FEATURE_ORDER_XGB = [
    "dias_desde_ultimo_riego",
    "deficit_hidrico_mm",
    "et0_acumulada",
    "t_max",
    "humedad_relativa",
    "kc_actual",
    "cc",
    "pmp",
]

FEATURE_ORDER_IFOREST = [
    "et0",
    "t_max",
    "t_min",
    "humedad_relativa",
    "viento_2m",
]


def build_xgb_feature_vector(data: Dict[str, Any]) -> np.ndarray:
    """Construye vector de features para XGBoost en el orden correcto."""
    return np.array([[data.get(f, 0.0) for f in FEATURE_ORDER_XGB]])


def build_iforest_feature_vector(data: Dict[str, Any]) -> np.ndarray:
    """Construye vector de features para IsolationForest."""
    return np.array([[data.get(f, 0.0) for f in FEATURE_ORDER_IFOREST]])
