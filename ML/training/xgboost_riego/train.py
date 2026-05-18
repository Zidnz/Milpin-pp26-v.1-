"""
Entrenamiento XGBoost — predicción de riego.

Lee features desde data/synthetic/ o Feature Store.
Hyperparámetros en ml/configs/xgboost_riego.yaml.

Uso:
    python ml/training/xgboost_riego/train.py [--data data/synthetic/milpin_ciclos_ml.csv]
"""
import argparse
import yaml
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split

CONFIG_PATH = Path(__file__).parents[2] / "configs" / "xgboost_riego.yaml"
DATA_DEFAULT = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_ml.csv"


def cargar_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def entrenar(data_path: Path = DATA_DEFAULT):
    config = cargar_config()
    df = pd.read_csv(data_path)

    features = config["features"]
    target = config["target"]

    X = df[features].fillna(0)
    y = df[target]

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=config["params"]["random_state"]
    )

    model = XGBClassifier(**config["params"])
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    joblib.dump(model, out_dir / "xgb_requiere_riego.joblib")
    print(f"Modelo guardado en {out_dir}/xgb_requiere_riego.joblib")
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_DEFAULT)
    args = parser.parse_args()
    entrenar(args.data)
