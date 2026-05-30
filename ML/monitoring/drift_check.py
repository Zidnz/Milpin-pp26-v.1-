"""
drift_check.py — Compara distribución de features de entrenamiento vs producción.

Carga:
    Referencia : data/snapshots/xgb_ref_dist.joblib
                 Guardado por ml/pipelines/train_eval_promote.py
    Producción : data/snapshots/xgb_prod_inputs.jsonl
                 Escrito por ml/inference/xgboost_riego.py en cada predicción

Métricas por feature numérica:
    PSI  < 0.10  -> estable
    PSI  0.10-0.20 -> monitorear
    PSI  > 0.20  -> reentrenar
    KS p < 0.05  -> distribuciones estadísticamente distintas

Uso:
    python ml/monitoring/drift_check.py
    python ml/monitoring/drift_check.py --min-rows 100 --last-n 1000
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np

# Asegura que la raíz del repo esté en sys.path al correr el script directamente
_REPO_ROOT = Path(__file__).parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ML.monitoring.drift import calcular_ks, calcular_psi

REPO_ROOT = Path(__file__).parents[2]
REF_PATH  = REPO_ROOT / "data" / "snapshots" / "xgb_ref_dist.joblib"
PROD_LOG  = REPO_ROOT / "data" / "snapshots" / "xgb_prod_inputs.jsonl"

# Solo features numéricas — tipo_suelo_enc se excluye (ordinal de baja cardinalidad)
NUMERIC_FEATURES = [
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
]


def check_drift(min_prod_rows: int = 50, last_n: int = 2000) -> list[dict]:
    """
    Compara referencia vs producción para cada feature numérica.

    Returns lista de dicts con keys:
        feature, psi, ks_stat, ks_p, drift_ks, status, prod_n
    """
    if not REF_PATH.exists():
        raise FileNotFoundError(
            f"Referencia no encontrada: {REF_PATH}\n"
            "Generar con: python ml/pipelines/train_eval_promote.py"
        )
    if not PROD_LOG.exists():
        raise FileNotFoundError(
            f"Log de producción no encontrado: {PROD_LOG}\n"
            "Se crea automáticamente cuando el modelo recibe predicciones."
        )

    ref: dict = joblib.load(REF_PATH)

    with PROD_LOG.open(encoding="utf-8") as f:
        lines = f.readlines()
    lines = lines[-last_n:]

    if len(lines) < min_prod_rows:
        raise ValueError(
            f"Log de producción insuficiente: {len(lines)} filas "
            f"(mínimo {min_prod_rows}). Esperar más predicciones."
        )

    prod_records = [json.loads(line) for line in lines]

    results = []
    for feat in NUMERIC_FEATURES:
        if feat not in ref:
            continue
        ref_arr  = np.asarray(ref[feat], dtype=float)
        prod_arr = np.array(
            [r[feat] for r in prod_records if feat in r and r[feat] is not None],
            dtype=float,
        )
        if len(prod_arr) < min_prod_rows:
            continue

        psi    = calcular_psi(ref_arr, prod_arr)
        ks     = calcular_ks(ref_arr, prod_arr)
        status = "CRITICO" if psi > 0.2 else ("MONITOREAR" if psi > 0.1 else "OK")

        results.append({
            "feature":  str(feat),
            "psi":      float(round(psi, 4)),
            "ks_stat":  float(round(ks["statistic"], 4)),
            "ks_p":     float(round(ks["p_value"], 4)),
            "drift_ks": bool(ks["drift"]),
            "status":   str(status),
            "prod_n":   int(len(prod_arr)),
            "ref_n":    int(len(ref_arr)),
        })

    return results


def _print_report(results: list[dict]) -> None:
    header = f"{'Feature':<25} {'PSI':>6}  {'Status':>10}  {'KS-stat':>8}  {'KS-p':>8}  {'Drift?':>7}  {'N prod':>7}"
    print(f"\n{header}")
    print("-" * len(header))
    for r in results:
        drift_flag = "SI" if r["drift_ks"] else "no"
        print(
            f"{r['feature']:<25} {r['psi']:>6.4f}  {r['status']:>10}  "
            f"{r['ks_stat']:>8.4f}  {r['ks_p']:>8.4f}  {drift_flag:>7}  {r['prod_n']:>7}"
        )

    criticos   = [r for r in results if r["status"] == "CRITICO"]
    monitoreár = [r for r in results if r["status"] == "MONITOREAR"]

    print()
    if criticos:
        print(f"CRITICO ({len(criticos)} features): {[r['feature'] for r in criticos]}")
        print("  -> Reentrenar: python ml/training/xgboost_riego/train.py")
    elif monitoreár:
        print(f"MONITOREAR ({len(monitoreár)} features): {[r['feature'] for r in monitoreár]}")
        print("  -> Revisar tendencia en próximos días.")
    else:
        print("OK: todas las features dentro de límites de estabilidad (PSI < 0.10).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drift monitoring — XGBoost Riego")
    parser.add_argument(
        "--min-rows", type=int, default=50,
        help="Mínimo de predicciones de producción requeridas (default: 50)",
    )
    parser.add_argument(
        "--last-n", type=int, default=2000,
        help="Usar solo las últimas N predicciones del log (default: 2000)",
    )
    args = parser.parse_args()

    print("=== MILPÍN — Drift Monitor (XGBoost Riego) ===")
    print(f"Referencia : {REF_PATH}")
    print(f"Producción : {PROD_LOG}  (últimas {args.last_n} filas, mín {args.min_rows})")

    results = check_drift(min_prod_rows=args.min_rows, last_n=args.last_n)
    _print_report(results)


if __name__ == "__main__":
    main()
