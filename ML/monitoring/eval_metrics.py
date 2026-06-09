"""
Métricas de evaluación estándar para los modelos MILPÍN.
Centraliza cálculos para que train.py y los tests usen la misma lógica.
"""

from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    mean_absolute_error,
    r2_score,
)
import numpy as np


def metricas_clasificacion(y_true, y_pred) -> dict:
    return {
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
    }


def metricas_regresion(y_true, y_pred) -> dict:
    return {
        "mae": mean_absolute_error(y_true, y_pred),
        "r2": r2_score(y_true, y_pred),
        "rmse": float(np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))),
    }
