"""
train_eval_promote.py — Pipeline de entrenamiento, evaluación y promoción

Pasos:
    1. Carga datos sintéticos (milpin_ciclos_ml.csv).
    2. Mapea columnas al espacio de features de inferencia (11 features producción).
    3. Guarda distribución de referencia en data/snapshots/xgb_ref_dist.joblib
       (usada por ml/monitoring/drift_check.py para comparar vs producción).
    4. Lee métricas del modelo activo en backend/models_ml/xgb_metricas.joblib
       y evalúa el promote gate.

Nota: El entrenamiento del modelo corre en ml/training/xgboost_riego/train.py.
Este pipeline asume que los joblibs en backend/models_ml/ ya fueron generados.

Uso:
    python ml/pipelines/train_eval_promote.py
    python ml/pipelines/train_eval_promote.py --data data/synthetic/milpin_ciclos_ml.csv
"""

import argparse
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT     = Path(__file__).parents[2]
DATA_DEFAULT  = REPO_ROOT / "data" / "synthetic" / "milpin_ciclos_ml.csv"
MODELS_DIR    = REPO_ROOT / "backend" / "models_ml"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
REF_PATH      = SNAPSHOTS_DIR / "xgb_ref_dist.joblib"

TIPO_SUELO_ENC: dict[str, int] = {
    "arcilloso":        0,
    "franco-arcilloso": 1,
    "franco":           2,
    "franco-arenoso":   3,
}

# Umbrales de promote gate para el modelo 3-model (producción actual)
PROMOTE_GATE = {
    "requiere_riego":  {"metric": "test_f1",  "op": ">=", "threshold": 0.80},
    "lamina_ajustada": {"metric": "test_mae", "op": "<=", "threshold": 15.0},
    "riesgo_estres":   {"metric": "test_mae", "op": "<=", "threshold": 0.12},
}


def guardar_ref_dist(df: pd.DataFrame) -> None:
    """
    Mapea columnas del CSV sintético a las 11 features de inferencia
    y guarda el array de valores como distribución de referencia.
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    tipo_enc = df["tipo_suelo"].map(TIPO_SUELO_ENC).fillna(2).values

    # dias_ciclo / n_riegos aproxima días entre riegos a nivel de ciclo
    dias_sin_riego = (df["dias_ciclo"] / df["n_riegos"].replace(0, 1)).values

    ref = {
        "deficit_mm":          df["deficit_estimado_mm"].values.astype(float),
        "etc_mm":              df["etc_estimada_mm"].values.astype(float),
        "eto_mm":              df["et0_hist_mmdia"].values.astype(float),
        "kc":                  df["kc_medio_cultivo"].values.astype(float),
        "dias_sin_riego":      dias_sin_riego.astype(float),
        "humedad_suelo_pct":   (df["humedad_suelo_promedio"].values * 100).astype(float),
        "capacidad_campo_pct": (df["capacidad_campo"].values * 100).astype(float),
        "punto_marchitez_pct": (df["punto_marchitez"].values * 100).astype(float),
        "profundidad_raiz_m":  df["prof_raiz_m"].values.astype(float),
        "area_ha":             df["area_ha"].values.astype(float),
        "tipo_suelo_enc":      tipo_enc.astype(float),
    }

    joblib.dump(ref, REF_PATH)
    print(f"  Referencia guardada: {REF_PATH}  ({len(df):,} filas de entrenamiento)")


def evaluar_promote_gate(metricas: dict) -> bool:
    """
    Verifica si el modelo activo en backend/models_ml/ pasa los umbrales mínimos.
    Retorna True si pasa, False si falla algún umbral.
    """
    passed = True
    for model_key, gate in PROMOTE_GATE.items():
        valor = metricas.get(model_key, {}).get(gate["metric"])
        if valor is None:
            print(f"  {model_key}: métrica '{gate['metric']}' no encontrada — SKIP")
            continue
        if gate["op"] == ">=":
            ok = valor >= gate["threshold"]
        else:
            ok = valor <= gate["threshold"]
        label = "PASS" if ok else "FAIL"
        print(
            f"  {model_key}: {gate['metric']}={valor:.4f} "
            f"{gate['op']} {gate['threshold']} → {label}"
        )
        passed = passed and ok
    return passed


def main(data_path: Path = DATA_DEFAULT) -> None:
    print("=== MILPÍN — train_eval_promote ===\n")

    if not data_path.exists():
        raise FileNotFoundError(
            f"Dataset no encontrado: {data_path}\n"
            "Generarlo con: python tools/generar_datos_sinteticos.py"
        )

    df = pd.read_csv(data_path)
    print(f"Dataset : {data_path.name}  ({len(df):,} filas, {len(df.columns)} columnas)")

    # Paso 1: guardar distribución de referencia para drift monitoring
    print("\n[1/2] Guardando distribución de referencia...")
    guardar_ref_dist(df)

    # Paso 2: evaluar promote gate con métricas del modelo activo
    print("\n[2/2] Evaluando promote gate...")
    metrics_path = MODELS_DIR / "xgb_metricas.joblib"
    if not metrics_path.exists():
        print(f"  WARN: {metrics_path} no encontrado.")
        print("  Entrenar primero: python ml/training/xgboost_riego/train.py")
        print("\nResultado: SKIP (modelo no entrenado)")
        return

    metricas = joblib.load(metrics_path)
    passed = evaluar_promote_gate(metricas)

    status = "PASS — modelo listo para producción" if passed else "FAIL — no cumple umbrales"
    print(f"\nResultado: {status}")
    if not passed:
        print("  → Reentrenar: python ml/training/xgboost_riego/train.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data", type=Path, default=DATA_DEFAULT,
        help="Path al CSV de entrenamiento (default: data/synthetic/milpin_ciclos_ml.csv)",
    )
    args = parser.parse_args()
    main(data_path=args.data)
