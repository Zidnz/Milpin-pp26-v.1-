"""Evaluación del modelo XGBoost entrenado en train.py."""
import joblib
import pandas as pd
from pathlib import Path
from ml.monitoring.eval_metrics import metricas_clasificacion

MODEL_PATH = Path(__file__).parent / "output" / "xgb_requiere_riego.joblib"


def evaluar(data_path: Path, target_col: str = "requiere_riego") -> dict:
    model = joblib.load(MODEL_PATH)
    df = pd.read_csv(data_path)
    features = model.feature_names_in_.tolist()
    X = df[features].fillna(0)
    y = df[target_col]
    y_pred = model.predict(X)
    metricas = metricas_clasificacion(y, y_pred)
    print(metricas)
    return metricas
