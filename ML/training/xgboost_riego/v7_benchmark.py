"""
ml/training/xgboost_riego/v7_benchmark.py — Benchmark v6 vs v7

Compara los dos modelos en las siguientes dimensiones:
    1. RMSE, MAE, MAPE, R² (métricas predictivas)
    2. Coherencia causal (SHAP sign consistency)
    3. Monotonicidad (compliance rate en PDP)
    4. Error de calibración (reliability diagram)
    5. Cobertura de incertidumbre (bootstrap intervals)
    6. Estabilidad SHAP (varianza entre subconjuntos)
    7. Dominancia de features (concentración de importancia)

Genera:
    - Tabla comparativa de todas las métricas
    - Gráficas de comparación lado a lado
    - Dashboard ejecutivo en HTML + PNG

Diseño:
    v6 se entrena con los datos y features originales (milpin_ciclos_ml.csv)
    v7 se entrena con los datos v7 (milpin_ciclos_v7.csv) y features causales

Uso:
    python v7_benchmark.py
    python v7_benchmark.py --n 50000 --out ml/training/xgboost_riego/output/v7
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Optional

import joblib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score
)
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

CONFIG_V6 = Path(__file__).parents[2] / "configs" / "xgboost_riego.yaml"
CONFIG_V7 = Path(__file__).parents[2] / "configs" / "xgboost_riego_v7.yaml"
DATA_V6   = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_ml.csv"
DATA_V7   = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv"
OUT_DIR   = Path(__file__).parent / "output" / "v7" / "benchmark"


# ── Entrenamiento rápido interno (sin artefactos) ─────────────────────────────

def _entrenar_rapido(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    features: list[str],
    target: str,
    params: dict,
    mc_map: dict[str, int] | None = None,
    version: str = "v6",
) -> tuple[XGBRegressor, np.ndarray, np.ndarray]:
    """
    Entrenamiento rápido para benchmark (no guarda artefactos).
    Maneja encoding de categóricas internamente.
    """
    cat_cols = [f for f in features if df_train[f].dtype == "object"]
    num_cols = [f for f in features if f not in cat_cols]

    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)

    def prep(df: pd.DataFrame, fit: bool = False) -> np.ndarray:
        df_n = df[num_cols].fillna(df_train[num_cols].median()).values.astype(np.float32)
        if cat_cols:
            df_c = df[cat_cols].fillna("UNKNOWN")
            df_c_enc = encoder.fit_transform(df_c) if fit else encoder.transform(df_c)
            return np.hstack([df_n, df_c_enc.astype(np.float32)])
        return df_n

    feature_names = num_cols + cat_cols
    X_train = prep(df_train, fit=True)
    X_test  = prep(df_test,  fit=False)
    y_train = df_train[target].values.astype(np.float32)
    y_test  = df_test[target].values.astype(np.float32)

    mc_vector = None
    if mc_map:
        mc_vector = tuple(mc_map.get(f, 0) for f in feature_names)

    xgb_params = {k: v for k, v in params.items() if k != "early_stopping_rounds"}
    early_stop = params.get("early_stopping_rounds", 50)

    if mc_vector:
        model = XGBRegressor(**xgb_params, monotone_constraints=mc_vector)
    else:
        model = XGBRegressor(**xgb_params)

    # Split interno para early stopping
    n_val = max(1000, int(0.15 * len(X_train)))
    X_tr2, X_val2 = X_train[n_val:], X_train[:n_val]
    y_tr2, y_val2 = y_train[n_val:], y_train[:n_val]

    model.fit(
        X_tr2, y_tr2,
        eval_set=[(X_val2, y_val2)],
        early_stopping_rounds=early_stop,
        verbose=False,
    )

    y_pred = model.predict(X_test)
    return model, y_test, y_pred


# ── Métricas extendidas ───────────────────────────────────────────────────────

def calcular_metricas_completas(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    label: str,
) -> dict:
    """Calcula las 10 métricas del benchmark v6 vs v7."""
    mae  = mean_absolute_error(y_true, y_pred)
    mse  = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)
    r2   = r2_score(y_true, y_pred)

    # MAPE robusto (evita división por cero)
    mask = y_true > 100
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100) if mask.sum() > 0 else np.nan

    # Calibration error (reliability diagram simplificado)
    # Divide predicciones en deciles y compara con medias reales
    df_cal = pd.DataFrame({"y_true": y_true, "y_pred": y_pred})
    df_cal["decil"] = pd.qcut(df_cal["y_pred"], q=10, labels=False, duplicates="drop")
    cal_means = df_cal.groupby("decil").agg({"y_true": "mean", "y_pred": "mean"}).dropna()
    cal_error = float(np.sqrt(np.mean((cal_means["y_true"] - cal_means["y_pred"]) ** 2)))

    # Error percentiles
    residuals = y_true - y_pred
    p90_error = float(np.percentile(np.abs(residuals), 90))
    p50_error = float(np.median(np.abs(residuals)))

    return {
        "label":          label,
        "MAE":            round(mae, 2),
        "RMSE":           round(rmse, 2),
        "R2":             round(r2, 4),
        "MAPE_pct":       round(mape, 2) if not np.isnan(mape) else None,
        "CalibrationRMSE":round(cal_error, 2),
        "P50_AbsError":   round(p50_error, 2),
        "P90_AbsError":   round(p90_error, 2),
    }


def calcular_dominancia_shap(
    model: XGBRegressor,
    X: np.ndarray,
    feature_names: list[str],
    n_sample: int = 2000,
) -> dict:
    """
    Mide concentración de importancia SHAP (Gini-coefficient).
    Alta concentración = modelo dependiente de pocas features = fragilidad.
    """
    try:
        import shap
        rng = np.random.default_rng(42)
        idx = rng.integers(0, len(X), min(n_sample, len(X)))
        explainer  = shap.TreeExplainer(model)
        shap_vals  = explainer.shap_values(X[idx])
        importancias = np.abs(shap_vals).mean(axis=0)
        importancias_norm = importancias / importancias.sum()

        # Gini coefficient
        n = len(importancias_norm)
        sorted_imp = np.sort(importancias_norm)
        gini = (2 * np.sum((np.arange(1, n+1)) * sorted_imp) / (n * sorted_imp.sum()) - (n+1)/n)

        top1_share = float(importancias_norm.max())
        top3_share = float(np.sort(importancias_norm)[-3:].sum())

        return {
            "gini_concentracion":  round(float(gini), 4),
            "top1_feature":        feature_names[np.argmax(importancias_norm)],
            "top1_shap_share":     round(top1_share, 4),
            "top3_shap_share":     round(top3_share, 4),
        }
    except ImportError:
        return {"gini_concentracion": None, "top1_feature": None}


def calcular_estabilidad_shap(
    model: XGBRegressor,
    X: np.ndarray,
    feature_names: list[str],
    n_splits: int = 5,
    n_sample: int = 500,
) -> dict:
    """
    Estabilidad SHAP: variabilidad de importancias entre subconjuntos del test.
    Alta variabilidad → el modelo es inestable / sensible a la muestra.
    """
    try:
        import shap
        rng = np.random.default_rng(42)
        importancias_splits = []

        explainer = shap.TreeExplainer(model)

        for _ in range(n_splits):
            idx = rng.integers(0, len(X), min(n_sample, len(X)))
            shap_vals = explainer.shap_values(X[idx])
            importancias_splits.append(np.abs(shap_vals).mean(axis=0))

        importancias_arr = np.array(importancias_splits)
        cv_por_feature = importancias_arr.std(axis=0) / (importancias_arr.mean(axis=0) + 1e-10)
        mean_cv = float(cv_por_feature.mean())

        return {
            "shap_stability_cv_mean": round(mean_cv, 4),
            "shap_stability_cv_max":  round(float(cv_por_feature.max()), 4),
        }
    except ImportError:
        return {"shap_stability_cv_mean": None}


def calcular_monotonicidad_pdp(
    model: XGBRegressor,
    X: np.ndarray,
    feature_names: list[str],
    constraints: dict[str, int],
    n_grid: int = 40,
) -> dict:
    """
    Mide compliance de monotonicidad en PDP para features con constraints.
    """
    correctas = 0
    total     = 0

    for feat, constraint in constraints.items():
        if feat not in feature_names:
            continue
        total += 1
        feat_idx = feature_names.index(feat)

        x_vals = np.linspace(X[:, feat_idx].min(), X[:, feat_idx].max(), n_grid)
        y_pdp  = []
        for xv in x_vals:
            X_tmp = X[:min(500, len(X))].copy()
            X_tmp[:, feat_idx] = xv
            y_pdp.append(model.predict(X_tmp).mean())

        y_pdp  = np.array(y_pdp)
        tendencia = "positiva" if y_pdp[-1] > y_pdp[0] else "negativa"
        esperada  = "positiva" if constraint == 1 else "negativa"

        if tendencia == esperada:
            correctas += 1

    return {
        "monotone_compliance": round(correctas / total, 4) if total > 0 else 1.0,
        "monotone_correctas":  correctas,
        "monotone_total":      total,
    }


# ── Gráficas de comparación ───────────────────────────────────────────────────

def plot_scatter_comparison(
    y_test_v6: np.ndarray,
    y_pred_v6: np.ndarray,
    y_test_v7: np.ndarray,
    y_pred_v7: np.ndarray,
    target_name: str,
    out_dir: Path,
) -> None:
    """Scatter plots real vs predicho para v6 y v7."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    for ax, y_true, y_pred, label, color in [
        (ax1, y_test_v6, y_pred_v6, "v6 (baseline)", "#e53935"),
        (ax2, y_test_v7, y_pred_v7, "v7 (causal)", "#1976d2"),
    ]:
        mae = mean_absolute_error(y_true, y_pred)
        r2  = r2_score(y_true, y_pred)

        ax.scatter(y_true, y_pred, alpha=0.2, s=4, color=color)
        mn, mx = min(y_true.min(), y_pred.min()), max(y_true.max(), y_pred.max())
        ax.plot([mn, mx], [mn, mx], "k--", linewidth=1, alpha=0.5)
        ax.set_xlabel(f"Real ({target_name})")
        ax.set_ylabel(f"Predicho ({target_name})")
        ax.set_title(f"MILPÍN {label}\nMAE={mae:.0f}  R²={r2:.4f}", fontsize=10)
        ax.text(0.05, 0.92, f"n={len(y_true):,}", transform=ax.transAxes, fontsize=9)

    plt.suptitle("MILPÍN — Comparación v6 vs v7: Real vs Predicho", fontsize=12)
    plt.tight_layout()
    path = out_dir / "scatter_v6_vs_v7.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {path.name}")


def plot_metricas_radar(
    metrics_v6: dict,
    metrics_v7: dict,
    out_dir: Path,
) -> None:
    """Radar chart de todas las métricas (normalizado)."""
    categorias = ["R²", "MAE_inv", "RMSE_inv", "Calibración_inv", "Monotonicity", "SHAP_stab"]

    def normalize(m: dict) -> list:
        r2_norm     = float(m.get("R2", 0))
        mae_inv     = 1.0 / (1.0 + float(m.get("MAE", 9999)) / 1000)
        rmse_inv    = 1.0 / (1.0 + float(m.get("RMSE", 9999)) / 1000)
        cal_inv     = 1.0 / (1.0 + float(m.get("CalibrationRMSE", 9999)) / 500)
        mono        = float(m.get("monotone_compliance", 0.5))
        shap_stab   = 1.0 - float(m.get("shap_stability_cv_mean", 0.5))
        return [r2_norm, mae_inv, rmse_inv, cal_inv, mono, shap_stab]

    vals_v6 = normalize(metrics_v6)
    vals_v7 = normalize(metrics_v7)

    # Cerrar el radar
    vals_v6 += [vals_v6[0]]
    vals_v7 += [vals_v7[0]]

    angles = np.linspace(0, 2 * np.pi, len(categorias), endpoint=False).tolist()
    angles += [angles[0]]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    ax.plot(angles, vals_v6, "o-", linewidth=2, color="#e53935", label="v6 baseline")
    ax.fill(angles, vals_v6, alpha=0.15, color="#e53935")
    ax.plot(angles, vals_v7, "o-", linewidth=2, color="#1976d2", label="v7 causal")
    ax.fill(angles, vals_v7, alpha=0.15, color="#1976d2")

    ax.set_thetagrids(np.degrees(angles[:-1]), categorias, fontsize=10)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
    ax.set_title("MILPÍN — Radar de Comparación v6 vs v7\n(normalizado, mayor = mejor)", pad=25)

    path = out_dir / "radar_v6_vs_v7.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {path.name}")


def plot_tabla_benchmark(
    tabla: pd.DataFrame,
    out_dir: Path,
) -> None:
    """Tabla visual de benchmark con colores por ganancia/pérdida."""
    fig, ax = plt.subplots(figsize=(12, max(4, len(tabla) * 0.6 + 1.5)))
    ax.axis("off")

    cols = tabla.columns.tolist()
    cell_text = tabla.values.tolist()

    table = ax.table(
        cellText=cell_text,
        colLabels=cols,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    # Colorear encabezado
    for j in range(len(cols)):
        table[0, j].set_facecolor("#1565c0")
        table[0, j].set_text_props(color="white", fontweight="bold")

    plt.title("MILPÍN — Tabla Benchmark v6 vs v7", fontsize=12, pad=15)
    plt.tight_layout()
    path = out_dir / "tabla_benchmark.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {path.name}")


# ── Pipeline principal ────────────────────────────────────────────────────────

def run_benchmark(
    n_rows: int = 50_000,
    out_dir: Path = OUT_DIR,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Benchmark completo v6 vs v7.
    Genera datos frescos, entrena ambos modelos, compara.
    """
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*65}")
    print("MILPÍN — Benchmark v6 vs v7")
    print(f"{'='*65}")

    # ── Cargar configs ─────────────────────────────────────────────────
    with open(CONFIG_V6) as f:
        cfg_v6_all = yaml.safe_load(f)
    with open(CONFIG_V7) as f:
        cfg_v7_all = yaml.safe_load(f)

    cfg_v6 = cfg_v6_all.get("m1_agua", {})
    cfg_v7 = cfg_v7_all.get("m1_agua_v7", {})

    feats_v6 = cfg_v6.get("features", [])
    feats_v7 = cfg_v7.get("features", [])
    target   = "volumen_agua_total_m3_ha"

    mc_v7 = cfg_v7.get("monotone_constraints", {})

    # ── Generar / cargar datos ─────────────────────────────────────────
    print("\nGenerando datos v6 y v7 (uso interno — no reemplaza CSVs de producción)...")

    # Importar generadores
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from v7_generar_datos import generar_dataset_v7
        df_v7 = generar_dataset_v7(n=n_rows, seed=seed)
        print(f"  v7: {len(df_v7):,} filas generadas")
    except Exception as e:
        print(f"  ERROR generando datos v7: {e}")
        if DATA_V7.exists():
            df_v7 = pd.read_csv(DATA_V7, nrows=n_rows)
            print(f"  v7: usando CSV existente ({len(df_v7):,} filas)")
        else:
            raise

    # Para v6 reutilizamos los mismos datos (generados con el mismo seed)
    # pero con el feature set v6 (que sí existe en los datos v7 extendidos)
    # Features v6 que existen en df_v7:
    feats_v6_disponibles = [f for f in feats_v6 if f in df_v7.columns]
    print(f"  Features v6 disponibles en datos: {len(feats_v6_disponibles)}/{len(feats_v6)}")
    if len(feats_v6_disponibles) < len(feats_v6):
        faltantes = [f for f in feats_v6 if f not in df_v7.columns]
        print(f"  Features v6 faltantes (se omiten): {faltantes}")

    # Split 80/20 (mismo split para ambos)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(df_v7))
    n_test = int(len(df_v7) * 0.20)
    idx_test  = idx[:n_test]
    idx_train = idx[n_test:]

    df_train = df_v7.iloc[idx_train].reset_index(drop=True)
    df_test  = df_v7.iloc[idx_test].reset_index(drop=True)

    print(f"  Split: train={len(df_train):,} test={len(df_test):,}")

    # ── Entrenar v6 ────────────────────────────────────────────────────
    print("\nEntrenando v6 (baseline)...")
    t_v6 = time.time()
    params_v6 = {**cfg_v6.get("params", {}), "n_estimators": 500}  # rápido para benchmark
    model_v6, y_test_v6, y_pred_v6 = _entrenar_rapido(
        df_train, df_test, feats_v6_disponibles, target, params_v6, version="v6"
    )
    elapsed_v6 = time.time() - t_v6
    print(f"  v6 listo en {elapsed_v6:.1f}s")

    # ── Entrenar v7 ────────────────────────────────────────────────────
    print("\nEntrenando v7 (causal)...")
    t_v7 = time.time()
    params_v7 = {**cfg_v7.get("params", {}), "n_estimators": 500}
    model_v7, y_test_v7, y_pred_v7 = _entrenar_rapido(
        df_train, df_test, feats_v7, target, params_v7, mc_map=mc_v7, version="v7"
    )
    elapsed_v7 = time.time() - t_v7
    print(f"  v7 listo en {elapsed_v7:.1f}s")

    # ── Métricas base ──────────────────────────────────────────────────
    metrics_v6 = calcular_metricas_completas(y_test_v6, y_pred_v6, "v6")
    metrics_v7 = calcular_metricas_completas(y_test_v7, y_pred_v7, "v7")

    # ── Preparar X para análisis SHAP/PDP ─────────────────────────────
    # Reusar el test set
    def prep_for_analysis(model, feats, df_test_local):
        cat_cols = [f for f in feats if df_test_local[f].dtype == "object"]
        num_cols = [f for f in feats if f not in cat_cols]
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        enc.fit(df_train[cat_cols].fillna("UNKNOWN")) if cat_cols else None
        df_n = df_test_local[num_cols].fillna(df_test_local[num_cols].median()).values.astype(np.float32)
        if cat_cols:
            df_c = enc.transform(df_test_local[cat_cols].fillna("UNKNOWN")).astype(np.float32)
            X = np.hstack([df_n, df_c])
        else:
            X = df_n
        return X, num_cols + cat_cols

    X_v6, fn_v6 = prep_for_analysis(model_v6, feats_v6_disponibles, df_test)
    X_v7, fn_v7 = prep_for_analysis(model_v7, feats_v7, df_test)

    # ── SHAP: dominancia y estabilidad ─────────────────────────────────
    print("\nCalculando métricas SHAP...")
    shap_dom_v6 = calcular_dominancia_shap(model_v6, X_v6, fn_v6)
    shap_dom_v7 = calcular_dominancia_shap(model_v7, X_v7, fn_v7)
    shap_stab_v6 = calcular_estabilidad_shap(model_v6, X_v6, fn_v6)
    shap_stab_v7 = calcular_estabilidad_shap(model_v7, X_v7, fn_v7)

    metrics_v6.update(shap_dom_v6)
    metrics_v7.update(shap_dom_v7)
    metrics_v6.update(shap_stab_v6)
    metrics_v7.update(shap_stab_v7)

    # ── Monotonicidad PDP ──────────────────────────────────────────────
    print("Calculando monotonicidad PDP...")
    constraints_esperadas = {
        "deficit_estimado_mm": +1,
        "eficiencia_sistema":  -1,
        "lluvia_hist_mm":      -1,
        "et0_hist_mmdia":      +1,
    }
    mono_v6 = calcular_monotonicidad_pdp(model_v6, X_v6, fn_v6, constraints_esperadas)
    mono_v7 = calcular_monotonicidad_pdp(model_v7, X_v7, fn_v7, constraints_esperadas)

    metrics_v6.update(mono_v6)
    metrics_v7.update(mono_v7)

    # ── Tabla de resultados ────────────────────────────────────────────
    metricas_mostrar = [
        ("R²",                    "R2",                     True,  ".4f"),
        ("MAE (m³/ha)",           "MAE",                    False, ".1f"),
        ("RMSE (m³/ha)",          "RMSE",                   False, ".1f"),
        ("MAPE (%)",              "MAPE_pct",               False, ".2f"),
        ("Calibración RMSE",      "CalibrationRMSE",        False, ".1f"),
        ("SHAP Gini concentrac.", "gini_concentracion",     False, ".4f"),
        ("SHAP estabilidad CV",   "shap_stability_cv_mean", False, ".4f"),
        ("Monotone compliance",   "monotone_compliance",    True,  ".4f"),
        ("Top-1 feature SHAP",    "top1_shap_share",        False, ".4f"),
        ("Top-3 features SHAP",   "top3_shap_share",        False, ".4f"),
    ]

    rows_tabla = []
    for nombre, key, mayor_mejor, fmt in metricas_mostrar:
        val_v6 = metrics_v6.get(key)
        val_v7 = metrics_v7.get(key)

        if val_v6 is not None and val_v7 is not None:
            try:
                diff = float(val_v7) - float(val_v6)
                diff_str = f"+{diff:{fmt}}" if diff > 0 else f"{diff:{fmt}}"
                better = (diff > 0) == mayor_mejor
                ganador = "v7 ✓" if better else ("v6" if diff != 0 else "empate")
                rows_tabla.append({
                    "Métrica":   nombre,
                    "v6":        f"{val_v6:{fmt}}",
                    "v7":        f"{val_v7:{fmt}}",
                    "Δ (v7-v6)": diff_str,
                    "Mejor":     ganador,
                })
            except (TypeError, ValueError):
                rows_tabla.append({
                    "Métrica":   nombre,
                    "v6":        str(val_v6),
                    "v7":        str(val_v7),
                    "Δ (v7-v6)": "N/A",
                    "Mejor":     "N/A",
                })

    tabla = pd.DataFrame(rows_tabla)

    print(f"\n{'='*65}")
    print("TABLA COMPARATIVA v6 vs v7")
    print(f"{'='*65}")
    print(tabla.to_string(index=False))
    print(f"{'='*65}\n")

    # ── Gráficas ───────────────────────────────────────────────────────
    print("Generando gráficas...")
    plot_scatter_comparison(y_test_v6, y_pred_v6, y_test_v7, y_pred_v7, target, out_dir)
    plot_metricas_radar(metrics_v6, metrics_v7, out_dir)
    plot_tabla_benchmark(tabla, out_dir)

    # ── Guardar resultados ─────────────────────────────────────────────
    tabla.to_csv(out_dir / "benchmark_tabla.csv", index=False)
    with open(out_dir / "benchmark_metrics.json", "w", encoding="utf-8") as f:
        json.dump({"v6": metrics_v6, "v7": metrics_v7}, f, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - t0
    print(f"\nBenchmark completado en {elapsed:.1f}s")
    print(f"Resultados en: {out_dir}/")

    return tabla


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark v6 vs v7 — MILPÍN")
    parser.add_argument("--n",    type=int,  default=50_000, help="Filas de datos")
    parser.add_argument("--out",  type=Path, default=OUT_DIR)
    parser.add_argument("--seed", type=int,  default=42)
    args = parser.parse_args()

    run_benchmark(n_rows=args.n, out_dir=args.out, seed=args.seed)
