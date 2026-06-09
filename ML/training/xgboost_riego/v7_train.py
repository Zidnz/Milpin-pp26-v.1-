"""
ml/training/xgboost_riego/v7_train.py — Entrenamiento M1/M2 con v7 causal

Cambios respecto a train.py (v6):
    - Feature set reducido y causalmente limpio (18 vs 24)
    - Monotonic constraints explícitos en XGBoost
    - Separación train/val/test estratificada por (cultivo, region)
    - Encoding de categóricas con OrdinalEncoder (XGBoost nativo)
    - Early stopping sobre val, evaluación final sobre test
    - Guarda artefactos: modelo, encoder, feature_names, métricas

Uso:
    python ml/training/xgboost_riego/v7_train.py --model m1
    python ml/training/xgboost_riego/v7_train.py --model m2
    python ml/training/xgboost_riego/v7_train.py --model m1 --data data/synthetic/milpin_ciclos_v7.csv
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

from ml.monitoring.eval_metrics import metricas_regresion

CONFIG_V7_PATH = Path(__file__).parents[2] / "configs" / "xgboost_riego_v7.yaml"
DATA_DEFAULT   = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv"
OUTPUT_DIR     = Path(__file__).parent / "output" / "v7"


def cargar_config(model_key: str) -> dict:
    with open(CONFIG_V7_PATH) as f:
        cfg = yaml.safe_load(f)
    if model_key not in cfg:
        raise ValueError(f"Modelo '{model_key}' no encontrado en config. "
                         f"Disponibles: {list(cfg.keys())}")
    return cfg[model_key]


def _build_monotone_vector(
    features: list[str],
    constraints_map: dict[str, int],
) -> tuple[int, ...]:
    """
    Construye el vector de monotonic_constraints en el orden exacto de features.
    XGBoost requiere una tupla con la misma longitud que el número de features,
    donde 0 = sin constraint, +1 = monótona creciente, -1 = monótona decreciente.
    """
    return tuple(constraints_map.get(feat, 0) for feat in features)


def split_stratificado(
    df: pd.DataFrame,
    target: str,
    test_size: float = 0.15,
    val_size: float = 0.15,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    División estratificada por cultivo × region para evitar distribuciones sesgadas
    en train/val/test. Esto es crítico para modelos agronómicos donde algunas
    combinaciones cultivo/región son raras.
    """
    rng = np.random.default_rng(random_state)

    # Crear strato combinado
    if "cultivo" in df.columns and "region" in df.columns:
        strato = df["cultivo"].astype(str) + "_" + df["region"].astype(str)
    elif "cultivo" in df.columns:
        strato = df["cultivo"].astype(str)
    else:
        strato = pd.Series(["all"] * len(df), index=df.index)

    # Shuffle
    idx = rng.permutation(len(df))
    df_shuffled = df.iloc[idx].reset_index(drop=True)
    strato_shuffled = strato.iloc[idx].reset_index(drop=True)

    # Calcular tamaños
    n = len(df_shuffled)
    n_test = int(n * test_size)
    n_val  = int(n * val_size)

    # División proporcional por strato
    stratums = strato_shuffled.unique()
    idx_test, idx_val, idx_train = [], [], []

    for s in stratums:
        s_idx = np.where(strato_shuffled == s)[0]
        n_s   = len(s_idx)
        n_s_test = max(1, int(n_s * test_size))
        n_s_val  = max(1, int(n_s * val_size))

        idx_test.extend(s_idx[:n_s_test].tolist())
        idx_val.extend(s_idx[n_s_test:n_s_test + n_s_val].tolist())
        idx_train.extend(s_idx[n_s_test + n_s_val:].tolist())

    df_train = df_shuffled.iloc[idx_train].reset_index(drop=True)
    df_val   = df_shuffled.iloc[idx_val].reset_index(drop=True)
    df_test  = df_shuffled.iloc[idx_test].reset_index(drop=True)

    print(f"  Split estratificado: train={len(df_train):,} val={len(df_val):,} test={len(df_test):,}")
    return df_train, df_val, df_test


def preparar_features(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    df_test: pd.DataFrame,
    features: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, OrdinalEncoder, list[str]]:
    """
    Prepara features: encode categóricas, reordena columnas, maneja NaN.
    Retorna arrays numpy + encoder ajustado en train.
    """
    cat_cols = [f for f in features if df_train[f].dtype == "object"]
    num_cols = [f for f in features if f not in cat_cols]

    # El encoder se ajusta SOLO en train (no leakage de val/test)
    encoder = OrdinalEncoder(
        handle_unknown="use_encoded_value",
        unknown_value=-1,
    )

    def transform_df(df: pd.DataFrame, fit: bool = False) -> np.ndarray:
        df_num  = df[num_cols].fillna(df_train[num_cols].median()).values.astype(np.float32)
        if cat_cols:
            df_cat  = df[cat_cols].fillna("UNKNOWN")
            if fit:
                df_cat_enc = encoder.fit_transform(df_cat).astype(np.float32)
            else:
                df_cat_enc = encoder.transform(df_cat).astype(np.float32)
            return np.hstack([df_num, df_cat_enc])
        return df_num

    X_train = transform_df(df_train, fit=True)
    X_val   = transform_df(df_val,   fit=False)
    X_test  = transform_df(df_test,  fit=False)

    # Nombres de features en el orden usado
    feature_names = num_cols + cat_cols

    return X_train, X_val, X_test, encoder, feature_names


def entrenar_v7(
    data_path: Path = DATA_DEFAULT,
    model_key: str = "m1_agua_v7",
    out_dir: Path = OUTPUT_DIR,
    verbose: bool = True,
) -> tuple[XGBRegressor, dict]:
    """
    Entrena modelo v7 con constraints monotónicas y split estratificado.

    Returns
    -------
    (modelo entrenado, dict con métricas y artefactos)
    """
    t0 = time.time()
    cfg = cargar_config(model_key)

    features   = cfg["features"]
    target     = cfg["target"]
    params     = cfg["params"]
    mc_map     = cfg.get("monotone_constraints", {})
    gate       = cfg.get("promote_gate", {})

    print(f"\n{'='*65}")
    print(f"MILPÍN v7 — Entrenamiento: {model_key}")
    print(f"Target: {target}  |  Features: {len(features)}")
    print(f"{'='*65}")

    # ── Cargar datos ──────────────────────────────────────────────────────
    print(f"\nCargando datos: {data_path}")
    df = pd.read_csv(data_path)
    print(f"  {len(df):,} filas, {len(df.columns)} columnas")

    # Verificar que todas las features existen
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"Features faltantes en CSV: {missing}\n"
                         f"¿Generaste los datos con v7_generar_datos.py?")

    # ── Split estratificado ───────────────────────────────────────────────
    df_train, df_val, df_test = split_estratificado(
        df, target,
        random_state=params.get("random_state", 42)
    )

    # ── Preparar features ─────────────────────────────────────────────────
    X_train, X_val, X_test, encoder, feature_names = preparar_features(
        df_train, df_val, df_test, features
    )

    y_train = df_train[target].values.astype(np.float32)
    y_val   = df_val[target].values.astype(np.float32)
    y_test  = df_test[target].values.astype(np.float32)

    # ── Construir vector de monotonic constraints ─────────────────────────
    mc_vector = _build_monotone_vector(feature_names, mc_map)
    mc_nonzero = sum(1 for x in mc_vector if x != 0)
    print(f"\n  Monotonic constraints activos: {mc_nonzero}/{len(mc_vector)}")
    for feat, constraint in zip(feature_names, mc_vector):
        if constraint != 0:
            sign = "↑(+1)" if constraint == 1 else "↓(-1)"
            print(f"    {feat}: {sign}")

    # ── Configurar y entrenar XGBoost ──────────────────────────────────────
    xgb_params = {k: v for k, v in params.items()
                  if k not in ("early_stopping_rounds",)}
    early_stopping = params.get("early_stopping_rounds", 50)

    model = XGBRegressor(
        **xgb_params,
        monotone_constraints=mc_vector,
        enable_categorical=False,  # OrdinalEncoder ya maneja categóricas
    )

    print(f"\n  Entrenando XGBRegressor con {params.get('n_estimators', 2000)} estimadores...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        early_stopping_rounds=early_stopping,
        verbose=False,
    )

    best_iter = model.best_iteration
    print(f"  Best iteration: {best_iter}")

    # ── Evaluación en test (sin leakage) ──────────────────────────────────
    y_pred_test  = model.predict(X_test)
    y_pred_train = model.predict(X_train)
    y_pred_val   = model.predict(X_val)

    metrics_test = metricas_regresion(y_test, y_pred_test)
    metrics_val  = metricas_regresion(y_val,  y_pred_val)

    print(f"\n  {'─'*50}")
    print(f"  MÉTRICAS TEST:")
    print(f"    MAE:  {metrics_test['mae']:.1f}  (gate: ≤{gate.get('max_mae_m3_ha', gate.get('max_mae_ton_ha', 'N/A'))})")
    print(f"    RMSE: {metrics_test['rmse']:.1f}")
    print(f"    R²:   {metrics_test['r2']:.4f}  (gate: ≥{gate.get('min_r2', 'N/A')})")
    print(f"    MAPE: {metrics_test.get('mape', 'N/A')}")
    print(f"  {'─'*50}")

    # ── Promote gate ──────────────────────────────────────────────────────
    mae_key  = "max_mae_m3_ha" if "m3_ha" in target else "max_mae_ton_ha"
    passes_gate = True

    if mae_key in gate and metrics_test["mae"] > gate[mae_key]:
        print(f"  ✗ GATE FALLIDO: MAE={metrics_test['mae']:.1f} > {gate[mae_key]}")
        passes_gate = False

    if "min_r2" in gate and metrics_test["r2"] < gate["min_r2"]:
        print(f"  ✗ GATE FALLIDO: R²={metrics_test['r2']:.4f} < {gate['min_r2']}")
        passes_gate = False

    if passes_gate:
        print(f"  ✓ PROMOTE GATE PASADO — modelo listo para producción")
    else:
        print(f"  ⚠ PROMOTE GATE FALLIDO — revisar antes de promover")

    # ── Guardar artefactos ────────────────────────────────────────────────
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_path   = out_dir / f"{model_key}_model.joblib"
    encoder_path = out_dir / f"{model_key}_encoder.joblib"
    metrics_path = out_dir / f"{model_key}_metrics.json"

    joblib.dump(model,   model_path)
    joblib.dump(encoder, encoder_path)

    artefacts = {
        "model_key":        model_key,
        "version":          "7.0",
        "features":         feature_names,
        "target":           target,
        "monotone_constraints": dict(zip(feature_names, mc_vector)),
        "best_iteration":   int(best_iter) if best_iter else None,
        "n_train":          int(len(y_train)),
        "n_val":            int(len(y_val)),
        "n_test":           int(len(y_test)),
        "metrics_test":     {k: float(v) if v is not None else None
                             for k, v in metrics_test.items()},
        "metrics_val":      {k: float(v) if v is not None else None
                             for k, v in metrics_val.items()},
        "promotes_gate":    passes_gate,
        "elapsed_s":        round(time.time() - t0, 1),
    }

    with open(metrics_path, "w") as f:
        json.dump(artefacts, f, indent=2, ensure_ascii=False)

    print(f"\n  Artefactos guardados en {out_dir}/")
    print(f"    {model_path.name}")
    print(f"    {encoder_path.name}")
    print(f"    {metrics_path.name}")
    print(f"\n  Tiempo total: {artefacts['elapsed_s']:.1f}s")

    return model, artefacts


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entrenamiento MILPÍN v7")
    parser.add_argument(
        "--model", default="m1_agua_v7",
        choices=["m1_agua_v7", "m2_rendimiento_v7"],
        help="Clave del modelo en xgboost_riego_v7.yaml"
    )
    parser.add_argument(
        "--data", type=Path, default=DATA_DEFAULT,
        help="Ruta al CSV de datos v7"
    )
    parser.add_argument(
        "--out", type=Path, default=OUTPUT_DIR,
        help="Directorio de salida para artefactos"
    )
    args = parser.parse_args()

    model, artefacts = entrenar_v7(
        data_path=args.data,
        model_key=args.model,
        out_dir=args.out,
    )
