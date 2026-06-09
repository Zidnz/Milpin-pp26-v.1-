"""
Entrenamiento XGBoost v7 — predicción de volumen de riego (m³/ha).

Lee features y monotone_constraints desde ml/configs/xgboost_riego_v7.yaml.
Modelo M1 (planeación al inicio del ciclo, sin features realizadas).

Uso:
    python ml/training/xgboost_riego/train.py [--data data/synthetic/milpin_ciclos_v7.csv]
"""
import argparse
import yaml
import joblib
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

CONFIG_PATH = Path(__file__).parents[2] / "configs" / "xgboost_riego_v7.yaml"
DATA_DEFAULT = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv"
MODEL_KEY = "m1_agua_v7"


def cargar_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _build_monotone_tuple(features: list[str], constraints: dict) -> tuple:
    """Convierte dict {feature: signo} a tupla ordenada por posición en features."""
    return tuple(constraints.get(f, 0) for f in features)


def entrenar(data_path: Path = DATA_DEFAULT):
    cfg = cargar_config()[MODEL_KEY]
    df = pd.read_csv(data_path)

    features: list[str] = cfg["features"]
    target: str = cfg["target"]
    params: dict = cfg["params"].copy()
    monotone_constraints: dict = cfg.get("monotone_constraints", {})

    # Codificar categóricas con LabelEncoder (XGBoost nativo no acepta strings)
    df_model = df[features + [target]].copy()
    for col in df_model.select_dtypes("object").columns:
        le = LabelEncoder()
        df_model[col] = le.fit_transform(df_model[col].astype(str))
    df_model = df_model.fillna(0)

    X = df_model[features]
    y = df_model[target]

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=params["random_state"]
    )

    params["monotone_constraints"] = _build_monotone_tuple(features, monotone_constraints)

    model = XGBRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100,
    )

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "xgb_agua_v7.joblib"
    joblib.dump(model, out_path)
    print(f"Modelo guardado en {out_path}")
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_DEFAULT)
    args = parser.parse_args()
    entrenar(args.data)
