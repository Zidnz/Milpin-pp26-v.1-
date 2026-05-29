"""
ml/training/xgboost_riego/v7_causal_validation.py — Validación causal post-entrenamiento

Implementa las 7 validaciones requeridas por v7:
    1. SHAP global (beeswarm + bar chart)
    2. SHAP por cultivo
    3. SHAP interaction values (top pares)
    4. Permutation importance (sklearn)
    5. Partial Dependence Plots (PDP)
    6. Individual Conditional Expectation (ICE)
    7. Ablation study (impacto por feature group)

Validaciones físicas específicas:
    A. eficiencia_sistema → monotonicidad negativa (SHAP + PDP)
    B. deficit_estimado_mm → monotonicidad positiva (SHAP + PDP)
    C. lluvia_hist_mm → monotonicidad negativa
    D. et0_hist_mmdia → monotonicidad positiva

Genera:
    - PNG de cada validación
    - JSON de resultados de monotonicidad
    - Reporte de violaciones causales

Uso:
    python v7_causal_validation.py --model m1_agua_v7
    python v7_causal_validation.py --model m1_agua_v7 --data data/synthetic/milpin_ciclos_v7.csv
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Optional

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance, PartialDependenceDisplay
from sklearn.preprocessing import OrdinalEncoder

warnings.filterwarnings("ignore", category=UserWarning)

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    print("WARNING: shap no instalado. `pip install shap`. Análisis SHAP omitido.")

OUTPUT_DIR = Path(__file__).parent / "output" / "v7"
DATA_DEFAULT = Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cargar_artefactos(
    model_key: str,
    out_dir: Path,
) -> tuple:
    """Carga modelo, encoder y metadata desde artefactos de v7_train.py."""
    model_path   = out_dir / f"{model_key}_model.joblib"
    encoder_path = out_dir / f"{model_key}_encoder.joblib"
    metrics_path = out_dir / f"{model_key}_metrics.json"

    if not model_path.exists():
        raise FileNotFoundError(
            f"Modelo no encontrado: {model_path}\n"
            f"Ejecutar: python v7_train.py --model {model_key}"
        )

    model   = joblib.load(model_path)
    encoder = joblib.load(encoder_path)

    with open(metrics_path) as f:
        meta = json.load(f)

    return model, encoder, meta


def _preparar_X(
    df: pd.DataFrame,
    feature_names: list[str],
    encoder: OrdinalEncoder,
    n_sample: int = 5000,
    seed: int = 42,
) -> tuple[np.ndarray, list[str]]:
    """Prepara matriz X para análisis (muestra de n_sample filas)."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(df), min(n_sample, len(df)))
    df_s = df.iloc[idx].reset_index(drop=True)

    cat_cols = [f for f in feature_names if f in df_s.select_dtypes("object").columns]
    num_cols = [f for f in feature_names if f not in cat_cols]

    df_num = df_s[num_cols].fillna(df_s[num_cols].median()).values.astype(np.float32)
    if cat_cols:
        df_cat = df_s[cat_cols].fillna("UNKNOWN")
        df_cat_enc = encoder.transform(df_cat).astype(np.float32)
        X = np.hstack([df_num, df_cat_enc])
    else:
        X = df_num

    return X, df_s


# ── 1. SHAP Global ────────────────────────────────────────────────────────────

def shap_global(
    model,
    X: np.ndarray,
    feature_names: list[str],
    out_dir: Path,
    title_suffix: str = "",
) -> dict:
    """
    Calcula SHAP values globales y genera:
    - Beeswarm plot (distribución por feature)
    - Bar chart (importancia media |SHAP|)

    Retorna dict con importancias medias por feature.
    """
    if not SHAP_AVAILABLE:
        return {}

    print("  Calculando SHAP global...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X)  # (n_samples, n_features)

    # Beeswarm
    fig_bees, ax = plt.subplots(figsize=(10, 8))
    shap.summary_plot(
        shap_vals, X,
        feature_names=feature_names,
        plot_type="dot",
        show=False,
        max_display=20,
    )
    plt.title(f"MILPÍN v7 — SHAP Global (Beeswarm){title_suffix}", pad=12)
    plt.tight_layout()
    fig_bees = plt.gcf()
    bees_path = out_dir / f"shap_global_beeswarm{title_suffix.replace(' ', '_')}.png"
    fig_bees.savefig(bees_path, dpi=150, bbox_inches="tight")
    plt.close()

    # Bar chart
    fig_bar, ax = plt.subplots(figsize=(8, 7))
    shap.summary_plot(
        shap_vals, X,
        feature_names=feature_names,
        plot_type="bar",
        show=False,
        max_display=20,
    )
    plt.title(f"MILPÍN v7 — SHAP Importancia Media{title_suffix}", pad=12)
    plt.tight_layout()
    fig_bar = plt.gcf()
    bar_path = out_dir / f"shap_global_bar{title_suffix.replace(' ', '_')}.png"
    fig_bar.savefig(bar_path, dpi=150, bbox_inches="tight")
    plt.close()

    # Importancias medias
    mean_abs_shap = np.abs(shap_vals).mean(axis=0)
    importancias = dict(zip(feature_names, mean_abs_shap.tolist()))

    print(f"    Guardado: {bees_path.name}, {bar_path.name}")
    return importancias


# ── 2. SHAP por Cultivo ───────────────────────────────────────────────────────

def shap_por_cultivo(
    model,
    df_sample: pd.DataFrame,
    X: np.ndarray,
    feature_names: list[str],
    out_dir: Path,
) -> dict:
    """
    SHAP desagregado por cultivo.
    Detecta si las relaciones causales cambian según el tipo de cultivo.
    """
    if not SHAP_AVAILABLE or "cultivo" not in df_sample.columns:
        return {}

    print("  Calculando SHAP por cultivo...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X)

    cultivos = df_sample["cultivo"].unique()
    results  = {}

    fig, axes = plt.subplots(
        1, len(cultivos), figsize=(5 * len(cultivos), 5), sharey=True
    )
    if len(cultivos) == 1:
        axes = [axes]

    for ax, cultivo in zip(axes, cultivos):
        mask = (df_sample["cultivo"] == cultivo).values
        if mask.sum() < 10:
            continue

        shap_c    = shap_vals[mask]
        mean_abs  = np.abs(shap_c).mean(axis=0)
        top5_idx  = np.argsort(mean_abs)[-5:][::-1]
        top5_feat = [feature_names[i] for i in top5_idx]
        top5_val  = mean_abs[top5_idx]

        colors = ["#1976d2" if v >= 0 else "#d32f2f" for v in top5_val]
        ax.barh(range(5), top5_val, color=colors)
        ax.set_yticks(range(5))
        ax.set_yticklabels(top5_feat, fontsize=8)
        ax.set_title(cultivo, fontsize=10)
        ax.set_xlabel("|SHAP| medio")
        results[cultivo] = dict(zip(top5_feat, top5_val.tolist()))

    plt.suptitle("MILPÍN v7 — SHAP por Cultivo (Top 5)", fontsize=12, y=1.02)
    plt.tight_layout()
    path = out_dir / "shap_por_cultivo.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Guardado: {path.name}")
    return results


# ── 3. SHAP Interaction Values ────────────────────────────────────────────────

def shap_interactions(
    model,
    X: np.ndarray,
    feature_names: list[str],
    out_dir: Path,
    n_interactions: int = 500,
) -> pd.DataFrame:
    """
    Calcula SHAP interaction values (costoso: usar muestra pequeña).
    Los pares con mayor interacción pueden revelar compensaciones internas.
    """
    if not SHAP_AVAILABLE:
        return pd.DataFrame()

    print(f"  Calculando SHAP interactions (n={n_interactions})...")
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(X), min(n_interactions, len(X)))
    X_s = X[idx]

    explainer      = shap.TreeExplainer(model)
    shap_interaction = explainer.shap_interaction_values(X_s)  # (n, p, p)

    # Importancia de interacción: media de |SHAP_interaction[i, j]| para i ≠ j
    mean_int = np.abs(shap_interaction).mean(axis=0)
    np.fill_diagonal(mean_int, 0)  # diagonal = efectos individuales, no interacciones

    # DataFrame de pares ordenados por importancia
    rows = []
    p = len(feature_names)
    for i in range(p):
        for j in range(i + 1, p):
            rows.append({
                "feature_1":   feature_names[i],
                "feature_2":   feature_names[j],
                "interaction": float(mean_int[i, j]),
            })
    df_int = pd.DataFrame(rows).sort_values("interaction", ascending=False).head(20)

    # Heatmap de interacciones
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(mean_int, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(p))
    ax.set_yticks(range(p))
    ax.set_xticklabels(feature_names, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(feature_names, fontsize=7)
    plt.colorbar(im, ax=ax, label="|SHAP interaction| medio")
    ax.set_title("MILPÍN v7 — SHAP Interaction Values", fontsize=11)
    plt.tight_layout()
    path = out_dir / "shap_interactions.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"    Guardado: {path.name}")
    print(f"    Top 5 interacciones:")
    for _, row in df_int.head(5).iterrows():
        print(f"      {row['feature_1']} × {row['feature_2']}: {row['interaction']:.4f}")

    return df_int


# ── 4. Permutation Importance ─────────────────────────────────────────────────

def permutation_importance_plot(
    model,
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    out_dir: Path,
    n_repeats: int = 20,
) -> pd.DataFrame:
    """
    Permutation importance: mide el incremento de RMSE al permutar cada feature.
    Más robusto que la importancia por ganancia de XGBoost.
    """
    print(f"  Calculando Permutation Importance (n_repeats={n_repeats})...")
    perm = permutation_importance(
        model, X, y,
        n_repeats=n_repeats,
        random_state=42,
        n_jobs=-1,
        scoring="neg_root_mean_squared_error",
    )

    df_perm = pd.DataFrame({
        "feature":   feature_names,
        "importancia_media": perm.importances_mean,
        "importancia_sd":    perm.importances_std,
    }).sort_values("importancia_media", ascending=False)

    fig, ax = plt.subplots(figsize=(8, max(5, len(feature_names) * 0.4)))
    ax.barh(
        df_perm["feature"][:20],
        df_perm["importancia_media"][:20],
        xerr=df_perm["importancia_sd"][:20],
        color="#1976d2", capsize=4, alpha=0.8,
    )
    ax.axvline(x=0, color="gray", linewidth=0.8)
    ax.set_xlabel("Incremento en RMSE (permutación)")
    ax.set_title("MILPÍN v7 — Permutation Importance")
    ax.invert_yaxis()
    plt.tight_layout()
    path = out_dir / "permutation_importance.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Guardado: {path.name}")
    return df_perm


# ── 5. Partial Dependence Plots ───────────────────────────────────────────────

def pdp_plots(
    model,
    X: np.ndarray,
    feature_names: list[str],
    features_to_plot: list[str],
    out_dir: Path,
    n_samples: int = 2000,
) -> dict[str, dict]:
    """
    PDP para features físicamente críticas.
    Mide monotonicidad de la relación feature → predicción.

    Retorna dict con:
        {feature: {"monotona": bool, "direccion": "+1" | "-1", "violaciones": int}}
    """
    print(f"  Calculando PDPs para: {features_to_plot}")
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(X), min(n_samples, len(X)))
    X_s = X[idx]

    resultados = {}
    n_feats = len(features_to_plot)
    fig, axes = plt.subplots(
        (n_feats + 2) // 3, 3,
        figsize=(15, max(4, ((n_feats + 2) // 3) * 4))
    )
    axes = axes.flatten()

    for i, feat in enumerate(features_to_plot):
        if feat not in feature_names:
            print(f"    WARNING: {feat} no está en feature_names, omitiendo")
            continue

        feat_idx = feature_names.index(feat)
        ax = axes[i]

        # Grid de valores para la feature
        x_vals = np.linspace(X_s[:, feat_idx].min(), X_s[:, feat_idx].max(), 50)
        y_means = []

        for xv in x_vals:
            X_tmp = X_s.copy()
            X_tmp[:, feat_idx] = xv
            y_pred = model.predict(X_tmp)
            y_means.append(y_pred.mean())

        y_means = np.array(y_means)

        # Detectar monotonicidad
        diffs = np.diff(y_means)
        violaciones_pos = int((diffs < -0.01 * y_means.mean()).sum())  # baja cuando debería subir
        violaciones_neg = int((diffs > +0.01 * y_means.mean()).sum())  # sube cuando debería bajar

        # Color según monotonicidad observada
        tendencia = "positiva" if y_means[-1] > y_means[0] else "negativa"
        color = "#1976d2" if tendencia == "positiva" else "#c62828"

        ax.plot(x_vals, y_means, color=color, linewidth=2)
        ax.fill_between(x_vals, y_means, alpha=0.15, color=color)
        ax.set_xlabel(feat, fontsize=9)
        ax.set_ylabel("Predicción media", fontsize=8)
        ax.set_title(f"PDP — {feat}\n(tendencia: {tendencia})", fontsize=9)
        ax.grid(alpha=0.3)

        resultados[feat] = {
            "tendencia":     tendencia,
            "y_min":         float(y_means.min()),
            "y_max":         float(y_means.max()),
            "rango_relativo": float((y_means.max() - y_means.min()) / max(y_means.mean(), 1.0)),
            "violaciones_mono_pos": violaciones_pos,
            "violaciones_mono_neg": violaciones_neg,
        }

    # Ocultar subplots vacíos
    for j in range(n_feats, len(axes)):
        axes[j].set_visible(False)

    plt.suptitle("MILPÍN v7 — Partial Dependence Plots (features físicas)", fontsize=12)
    plt.tight_layout()
    path = out_dir / "pdp_fisicas.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Guardado: {path.name}")
    return resultados


# ── 6. ICE Plots ──────────────────────────────────────────────────────────────

def ice_plots(
    model,
    X: np.ndarray,
    feature_names: list[str],
    features_to_plot: list[str],
    out_dir: Path,
    n_ice_lines: int = 100,
    n_pdp_samples: int = 1000,
) -> None:
    """
    ICE (Individual Conditional Expectation) plots.
    Muestra cómo la predicción cambia para individuos específicos,
    revelando heterogeneidad y posibles interacciones no-lineales.
    """
    print(f"  Generando ICE plots para: {features_to_plot}")
    rng = np.random.default_rng(42)

    idx_all  = rng.integers(0, len(X), min(n_pdp_samples, len(X)))
    idx_ice  = rng.integers(0, len(X), min(n_ice_lines, len(X)))
    X_all    = X[idx_all]
    X_ice    = X[idx_ice]

    n_feats = len(features_to_plot)
    fig, axes = plt.subplots(
        (n_feats + 1) // 2, 2,
        figsize=(14, max(5, ((n_feats + 1) // 2) * 5))
    )
    axes = axes.flatten()

    for i, feat in enumerate(features_to_plot):
        if feat not in feature_names:
            continue

        feat_idx = feature_names.index(feat)
        ax = axes[i]

        x_vals = np.linspace(X_all[:, feat_idx].min(), X_all[:, feat_idx].max(), 40)

        # ICE lines (individuos)
        for j in range(len(X_ice)):
            y_ice = []
            for xv in x_vals:
                X_tmp = X_ice[j:j+1].copy()
                X_tmp[0, feat_idx] = xv
                y_ice.append(model.predict(X_tmp)[0])
            ax.plot(x_vals, y_ice, alpha=0.15, color="#90caf9", linewidth=0.8)

        # PDP encima (línea gruesa)
        y_pdp = []
        for xv in x_vals:
            X_tmp = X_all.copy()
            X_tmp[:, feat_idx] = xv
            y_pdp.append(model.predict(X_tmp).mean())
        ax.plot(x_vals, y_pdp, color="#1565c0", linewidth=2.5, label="PDP (media)")

        ax.set_xlabel(feat, fontsize=9)
        ax.set_ylabel("Predicción", fontsize=8)
        ax.set_title(f"ICE — {feat}", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    for j in range(n_feats, len(axes)):
        axes[j].set_visible(False)

    plt.suptitle("MILPÍN v7 — ICE Plots (Individual Conditional Expectation)", fontsize=12)
    plt.tight_layout()
    path = out_dir / "ice_plots.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Guardado: {path.name}")


# ── 7. Ablation Study ─────────────────────────────────────────────────────────

def ablation_study(
    model,
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    feature_groups: dict[str, list[str]],
    out_dir: Path,
) -> pd.DataFrame:
    """
    Ablation study: evalúa el impacto de eliminar grupos de features.
    Permite cuantificar la contribución de cada módulo al rendimiento.

    Parámetros
    ----------
    feature_groups : dict de {nombre_grupo: [lista de features en el grupo]}
    """
    from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error

    print("  Ejecutando ablation study...")
    y_base  = model.predict(X)
    mae_base = mean_absolute_error(y, y_base)
    rmse_base = np.sqrt(mean_squared_error(y, y_base))
    r2_base  = r2_score(y, y_base)

    rows = [{
        "grupo":        "Baseline (todas)",
        "features_eliminadas": "ninguna",
        "MAE":          round(mae_base, 2),
        "RMSE":         round(rmse_base, 2),
        "R2":           round(r2_base, 4),
        "delta_MAE":    0.0,
        "delta_R2":     0.0,
    }]

    for grupo, feats in feature_groups.items():
        feats_in_model = [f for f in feats if f in feature_names]
        if not feats_in_model:
            continue

        # Reemplazar features del grupo con su media (ablación suave)
        X_ablated = X.copy()
        for feat in feats_in_model:
            fidx = feature_names.index(feat)
            X_ablated[:, fidx] = X[:, fidx].mean()

        y_pred  = model.predict(X_ablated)
        mae_abl = mean_absolute_error(y, y_pred)
        rmse_abl = np.sqrt(mean_squared_error(y, y_pred))
        r2_abl  = r2_score(y, y_pred)

        rows.append({
            "grupo":              grupo,
            "features_eliminadas": ", ".join(feats_in_model),
            "MAE":                round(mae_abl, 2),
            "RMSE":               round(rmse_abl, 2),
            "R2":                 round(r2_abl, 4),
            "delta_MAE":          round(mae_abl - mae_base, 2),
            "delta_R2":           round(r2_abl - r2_base, 4),
        })

    df_abl = pd.DataFrame(rows)

    # Barplot del delta MAE
    fig, ax = plt.subplots(figsize=(9, 5))
    grupos = df_abl.iloc[1:]["grupo"]
    deltas = df_abl.iloc[1:]["delta_MAE"]
    colors = ["#d32f2f" if d > 0 else "#1976d2" for d in deltas]
    ax.bar(grupos, deltas, color=colors, alpha=0.8)
    ax.axhline(0, color="gray", linewidth=1)
    ax.set_ylabel("Incremento en MAE (m³/ha)")
    ax.set_title("MILPÍN v7 — Ablation Study\n(impacto de eliminar grupos de features)")
    plt.xticks(rotation=20, ha="right", fontsize=9)
    plt.tight_layout()
    path = out_dir / "ablation_study.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"    Guardado: {path.name}")
    print("\n  Resultados ablation:")
    print(df_abl.to_string(index=False))
    return df_abl


# ── Validación física de monotonicidad ────────────────────────────────────────

def validar_monotonicidad(
    pdp_results: dict[str, dict],
    constraints_esperadas: dict[str, int],
) -> dict:
    """
    Verifica que las tendencias observadas en PDP coinciden con los
    monotonic constraints físicos esperados.

    Retorna reporte con número de violaciones y detalles.
    """
    violaciones = []
    correctas   = []

    for feat, constraint in constraints_esperadas.items():
        if feat not in pdp_results:
            continue

        resultado = pdp_results[feat]
        tendencia_obs = resultado["tendencia"]
        tendencia_esp = "positiva" if constraint == 1 else "negativa"

        if tendencia_obs != tendencia_esp:
            violaciones.append({
                "feature":       feat,
                "constraint_fisico": tendencia_esp,
                "tendencia_pdp":     tendencia_obs,
                "rango_relativo": resultado["rango_relativo"],
            })
        else:
            correctas.append(feat)

    reporte = {
        "total_constraints":    len(constraints_esperadas),
        "correctas":            len(correctas),
        "violaciones":          len(violaciones),
        "compliance_rate":      len(correctas) / max(len(constraints_esperadas), 1),
        "features_correctas":   correctas,
        "features_violadas":    violaciones,
    }

    print(f"\n  {'─'*50}")
    print(f"  VALIDACIÓN DE MONOTONICIDAD")
    print(f"  {'─'*50}")
    print(f"  Compliance: {reporte['compliance_rate']:.1%}  "
          f"({reporte['correctas']}/{reporte['total_constraints']} constraints)")

    if violaciones:
        print(f"\n  ⚠ VIOLACIONES FÍSICAS:")
        for v in violaciones:
            print(f"    {v['feature']}: esperado={v['constraint_fisico']}, "
                  f"observado={v['tendencia_pdp']} "
                  f"(rango={v['rango_relativo']:.3f})")
    else:
        print("  ✓ Sin violaciones — coherencia física perfecta")

    return reporte


# ── Pipeline completo ─────────────────────────────────────────────────────────

def run_validacion_completa(
    model_key: str = "m1_agua_v7",
    data_path: Path = DATA_DEFAULT,
    out_dir: Path = OUTPUT_DIR,
    n_sample: int = 5000,
) -> dict:
    """
    Ejecuta las 7 validaciones causales y genera todas las gráficas.

    Returns
    -------
    dict con resultados consolidados de todas las validaciones
    """
    print(f"\n{'='*65}")
    print(f"MILPÍN v7 — Validación Causal: {model_key}")
    print(f"{'='*65}")

    out_dir = Path(out_dir) / "validacion_causal"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Cargar artefactos ──────────────────────────────────────────────
    model, encoder, meta = _cargar_artefactos(model_key, Path(out_dir).parent)
    feature_names = meta["features"]
    target        = meta["target"]

    # ── Cargar datos ───────────────────────────────────────────────────
    print(f"\nCargando {data_path}...")
    df = pd.read_csv(data_path)

    X, df_sample = _preparar_X(df, feature_names, encoder, n_sample=n_sample)
    y = df_sample[target].values.astype(np.float32)

    # ── 1. SHAP Global ─────────────────────────────────────────────────
    print("\n[1/7] SHAP Global")
    importancias_shap = shap_global(model, X, feature_names, out_dir)

    # ── 2. SHAP por cultivo ────────────────────────────────────────────
    print("\n[2/7] SHAP por Cultivo")
    shap_cultivo = shap_por_cultivo(model, df_sample, X, feature_names, out_dir)

    # ── 3. SHAP Interactions ───────────────────────────────────────────
    print("\n[3/7] SHAP Interaction Values")
    df_interactions = shap_interactions(model, X, feature_names, out_dir, n_interactions=300)

    # ── 4. Permutation Importance ──────────────────────────────────────
    print("\n[4/7] Permutation Importance")
    df_perm = permutation_importance_plot(model, X, y, feature_names, out_dir)

    # ── 5. PDPs ────────────────────────────────────────────────────────
    # Features críticas para validación física
    features_pdp = [
        "deficit_estimado_mm",
        "eficiencia_sistema",
        "lluvia_hist_mm",
        "et0_hist_mmdia",
        "salinidad_ec_dsm",
        "aporte_capilar_mm",
        "agua_disponible_mm",
    ]
    features_pdp = [f for f in features_pdp if f in feature_names]

    print("\n[5/7] Partial Dependence Plots")
    pdp_results = pdp_plots(model, X, feature_names, features_pdp, out_dir)

    # ── 6. ICE Plots ───────────────────────────────────────────────────
    features_ice = [
        "deficit_estimado_mm",
        "eficiencia_sistema",
        "lluvia_hist_mm",
        "et0_hist_mmdia",
    ]
    features_ice = [f for f in features_ice if f in feature_names]

    print("\n[6/7] ICE Plots")
    ice_plots(model, X, feature_names, features_ice, out_dir)

    # ── 7. Ablation Study ──────────────────────────────────────────────
    feature_groups = {
        "Grupo_Hidráulico":  ["deficit_estimado_mm", "eficiencia_sistema"],
        "Grupo_Climático":   ["et0_hist_mmdia", "lluvia_hist_mm", "kc_medio_cultivo"],
        "Grupo_Suelo":       ["agua_disponible_mm", "percolacion_frac", "aporte_capilar_mm"],
        "Grupo_Salinidad":   ["salinidad_ec_dsm", "ks_salinidad_calc"],
        "Grupo_Comportamiento": ["tipo_agricultor"],
    }

    print("\n[7/7] Ablation Study")
    df_ablation = ablation_study(model, X, y, feature_names, feature_groups, out_dir)

    # ── Validación física de monotonicidad ─────────────────────────────
    constraints_esperadas = {
        "deficit_estimado_mm": +1,
        "et0_hist_mmdia":      +1,
        "eficiencia_sistema":  -1,
        "lluvia_hist_mm":      -1,
        "aporte_capilar_mm":   -1,
    }
    reporte_mono = validar_monotonicidad(pdp_results, constraints_esperadas)

    # ── Consolidar resultados ──────────────────────────────────────────
    resultados = {
        "model_key":           model_key,
        "version":             "7.0",
        "shap_importancias":   importancias_shap,
        "shap_por_cultivo":    shap_cultivo,
        "top_interactions":    df_interactions.head(10).to_dict("records")
                               if not df_interactions.empty else [],
        "pdp_resultados":      pdp_results,
        "monotonic_validation": reporte_mono,
        "ablation_results":    df_ablation.to_dict("records"),
    }

    # Guardar JSON
    results_path = out_dir / "causal_validation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*65}")
    print("RESUMEN DE VALIDACIÓN CAUSAL")
    print(f"{'='*65}")
    print(f"  Compliance monotónico: {reporte_mono['compliance_rate']:.1%}")
    print(f"  Violaciones físicas:   {reporte_mono['violaciones']}")
    if importancias_shap:
        top_feat = max(importancias_shap, key=importancias_shap.get)
        print(f"  Feature más importante (SHAP): {top_feat} = {importancias_shap[top_feat]:.4f}")
    print(f"\n  Resultados guardados: {results_path}")
    print(f"{'='*65}\n")

    return resultados


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validación Causal — MILPÍN v7")
    parser.add_argument(
        "--model", default="m1_agua_v7",
        choices=["m1_agua_v7", "m2_rendimiento_v7"],
    )
    parser.add_argument("--data",    type=Path, default=DATA_DEFAULT)
    parser.add_argument("--out",     type=Path, default=OUTPUT_DIR)
    parser.add_argument("--n",       type=int,  default=5000, help="Muestra para análisis")
    args = parser.parse_args()

    run_validacion_completa(
        model_key=args.model,
        data_path=args.data,
        out_dir=args.out,
        n_sample=args.n,
    )
