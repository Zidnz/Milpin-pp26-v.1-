"""
ml/training/xgboost_riego/v7_leakage_detector.py — Detector de leakage proxy

Detecta automáticamente:
    1. Correlación lineal/Spearman > umbral con el target
    2. Dependencia funcional entre features (reconstruibilidad)
    3. Proxies del target (alta MI con target, no justificada causalmente)
    4. Duplicidad semántica (alta correlación entre features)
    5. Features derivadas que contienen datos realizados

Genera:
    - Tabla de riesgo de leakage (DataFrame)
    - Heatmap de correlación
    - Reporte textual de recomendaciones

Uso:
    from v7_leakage_detector import LeakageDetector
    ld = LeakageDetector(df, target="volumen_agua_total_m3_ha")
    reporte = ld.run_full_audit()
    ld.plot_heatmap()
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.feature_selection import mutual_info_regression
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import LabelEncoder


# ── Constantes ────────────────────────────────────────────────────────────────

# Features que por definición física son realizadas (no disponibles al inicio)
REALIZED_FEATURES = {
    "et0_promedio_mmdia", "et0_maximo_mmdia", "lluvia_total_mm", "etc_total_mm",
    "kc_promedio", "humedad_suelo_promedio", "deficit_hidrico_frac", "n_riegos",
    "demanda_neta_mm", "agua_neta_req_m3ha", "vol_teorico_m3ha",
    "riego_bruto_mm", "deficit_agua_mm",
}

# Umbral de correlación para marcar peligro de leakage
CORR_THRESHOLD_DANGER = 0.95
CORR_THRESHOLD_WARN   = 0.80

# Umbral de mutual information (relativo al valor máximo observado)
MI_RELATIVE_THRESHOLD = 0.85

# Umbral para detectar dependencia funcional lineal (R² de regresión)
R2_FUNCTIONAL_THRESHOLD = 0.98


class LeakageDetector:
    """
    Auditor automático de leakage proxy para modelos de planeación agrícola.

    El detector distingue tres niveles de riesgo:
    - CRITICO:  feature realizada o correlación >0.95 con target
    - ALTO:     dependencia funcional de otras features O correlación 0.80-0.95
    - MEDIO:    alta MI con target, alta correlación inter-feature
    - BAJO:     sospechoso pero sin evidencia fuerte
    """

    def __init__(
        self,
        df: pd.DataFrame,
        target: str,
        candidate_features: Optional[list[str]] = None,
        corr_threshold_danger: float = CORR_THRESHOLD_DANGER,
        corr_threshold_warn: float   = CORR_THRESHOLD_WARN,
        mi_relative_threshold: float = MI_RELATIVE_THRESHOLD,
        r2_functional_threshold: float = R2_FUNCTIONAL_THRESHOLD,
        random_state: int = 42,
    ):
        self.df      = df.copy()
        self.target  = target
        self.rng     = np.random.default_rng(random_state)

        # Features a auditar: todas las numéricas excepto el target
        if candidate_features is not None:
            self.features = [f for f in candidate_features if f in df.columns]
        else:
            self.features = [
                c for c in df.columns
                if c != target and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]
            ]

        self.thr_danger  = corr_threshold_danger
        self.thr_warn    = corr_threshold_warn
        self.thr_mi_rel  = mi_relative_threshold
        self.thr_r2_func = r2_functional_threshold

        self._results: Optional[pd.DataFrame] = None
        self._corr_matrix: Optional[pd.DataFrame] = None

    # ── Métodos de auditoría ──────────────────────────────────────────────

    def _encode_df(self) -> pd.DataFrame:
        """Codifica categóricas para cálculos numéricos."""
        df_enc = self.df[self.features + [self.target]].copy()
        for col in df_enc.select_dtypes("object").columns:
            le = LabelEncoder()
            df_enc[col] = le.fit_transform(df_enc[col].astype(str))
        return df_enc.fillna(0)

    def _check_realized(self, feature: str) -> tuple[str, str]:
        """Marca features realizadas (conocidas solo al fin del ciclo)."""
        if feature in REALIZED_FEATURES:
            return "CRITICO", "Feature realizada — no disponible al inicio del ciclo"
        return "OK", ""

    def _check_correlation_with_target(
        self, df_enc: pd.DataFrame, feature: str
    ) -> tuple[str, str, float, float]:
        """
        Calcula correlación Pearson y Spearman con el target.
        Alta correlación con el target puede indicar leakage o proxy.
        """
        x = df_enc[feature].values
        y = df_enc[self.target].values

        if np.std(x) < 1e-10:
            return "OK", "varianza=0", 0.0, 0.0

        pearson_r = np.corrcoef(x, y)[0, 1]
        spearman_r, _ = spearmanr(x, y)

        max_corr = max(abs(pearson_r), abs(spearman_r))

        if max_corr >= self.thr_danger:
            nivel = "CRITICO"
            msg = f"Correlación extrema con target: Pearson={pearson_r:.3f}, Spearman={spearman_r:.3f}"
        elif max_corr >= self.thr_warn:
            nivel = "ALTO"
            msg = f"Correlación alta con target: Pearson={pearson_r:.3f}, Spearman={spearman_r:.3f}"
        else:
            nivel = "OK"
            msg = f"Pearson={pearson_r:.3f}, Spearman={spearman_r:.3f}"

        return nivel, msg, float(pearson_r), float(spearman_r)

    def _check_mutual_information(
        self, df_enc: pd.DataFrame, feature: str, mi_scores: np.ndarray, mi_features: list[str]
    ) -> tuple[str, str, float]:
        """
        Mutual Information relativa al máximo observado.
        Alta MI sugiere que la feature es un proxy del target.
        """
        if feature not in mi_features:
            return "OK", "feature no en MI list", 0.0

        idx = mi_features.index(feature)
        mi_val = mi_scores[idx]
        mi_max = mi_scores.max() if mi_scores.max() > 0 else 1e-10
        mi_rel = mi_val / mi_max

        if mi_rel >= self.thr_mi_rel:
            return "ALTO", f"MI relativa={mi_rel:.3f} (mi={mi_val:.3f}) — posible proxy del target", mi_val
        elif mi_rel >= 0.60:
            return "MEDIO", f"MI relativa={mi_rel:.3f}", mi_val
        return "OK", f"MI relativa={mi_rel:.3f}", mi_val

    def _check_functional_dependency(
        self, df_enc: pd.DataFrame, feature: str, other_features: list[str]
    ) -> tuple[str, str, float]:
        """
        Detecta si 'feature' puede ser reconstruida linealmente a partir de otras.
        R² > 0.98 indica dependencia funcional casi perfecta.
        """
        if len(other_features) < 2:
            return "OK", "pocas features para regresión", 0.0

        X_others = df_enc[other_features].values
        y_feat   = df_enc[feature].values

        if np.std(y_feat) < 1e-10:
            return "OK", "varianza=0 en feature", 0.0

        # Muestra aleatoria de 10K filas para velocidad
        n_sample = min(10_000, len(X_others))
        idx_sample = self.rng.integers(0, len(X_others), n_sample)
        X_s = X_others[idx_sample]
        y_s = y_feat[idx_sample]

        try:
            reg = LinearRegression().fit(X_s, y_s)
            r2  = reg.score(X_s, y_s)
        except Exception:
            return "OK", "error en regresión", 0.0

        if r2 >= self.thr_r2_func:
            return "ALTO", f"R²={r2:.4f} — derivable de otras features (dependencia funcional)", float(r2)
        elif r2 >= 0.90:
            return "MEDIO", f"R²={r2:.4f} — parcialmente reconstructible", float(r2)
        return "OK", f"R²={r2:.4f}", float(r2)

    def _check_inter_feature_correlation(
        self, df_enc: pd.DataFrame, feature: str, corr_matrix: pd.DataFrame
    ) -> tuple[str, str, list[str]]:
        """
        Detecta pares de features con correlación > umbral.
        Indica redundancia semántica o duplicidad.
        """
        if feature not in corr_matrix.index:
            return "OK", "", []

        corr_row = corr_matrix.loc[feature].drop(feature, errors="ignore")
        high_corr = corr_row[corr_row.abs() >= self.thr_danger]

        if len(high_corr) > 0:
            partners = high_corr.index.tolist()
            return "ALTO", f"Correlación ≥{self.thr_danger:.2f} con: {', '.join(partners)}", partners

        warn_corr = corr_row[corr_row.abs() >= self.thr_warn]
        if len(warn_corr) > 0:
            partners = warn_corr.index.tolist()
            return "MEDIO", f"Correlación ≥{self.thr_warn:.2f} con: {', '.join(partners)}", partners

        return "OK", "sin correlación problemática", []

    # ── Auditoría completa ────────────────────────────────────────────────

    def run_full_audit(self) -> pd.DataFrame:
        """
        Ejecuta auditoría completa de leakage.

        Returns
        -------
        pd.DataFrame con columnas:
            feature, nivel_riesgo, score_leakage, pearson_target, spearman_target,
            mi_target, r2_funcional, correlaciones_altas, motivo
        """
        print(f"\n{'='*70}")
        print("MILPÍN v7 — Auditoría de Leakage Proxy")
        print(f"Target: {self.target}  |  Features auditadas: {len(self.features)}")
        print(f"{'='*70}\n")

        df_enc = self._encode_df()

        # Matriz de correlación entre features
        corr_matrix = df_enc[self.features].corr(method="spearman")
        self._corr_matrix = corr_matrix

        # Mutual information (costoso: sample a 20K)
        n_mi = min(20_000, len(df_enc))
        idx_mi = self.rng.integers(0, len(df_enc), n_mi)
        X_mi = df_enc[self.features].iloc[idx_mi].values
        y_mi = df_enc[self.target].iloc[idx_mi].values

        print("Calculando Mutual Information...")
        try:
            mi_scores = mutual_info_regression(X_mi, y_mi, random_state=42)
            mi_computed = True
        except Exception as e:
            print(f"  Warning: MI no disponible — {e}")
            mi_scores  = np.zeros(len(self.features))
            mi_computed = False

        rows = []
        for feat in self.features:
            # Test 1: ¿Es feature realizada?
            nivel_r, msg_r = self._check_realized(feat)

            # Test 2: Correlación con target
            nivel_c, msg_c, pearson_r, spearman_r = self._check_correlation_with_target(df_enc, feat)

            # Test 3: Mutual Information
            nivel_m, msg_m, mi_val = self._check_mutual_information(
                df_enc, feat, mi_scores, self.features
            )

            # Test 4: Dependencia funcional (solo si no es ya CRITICO)
            other_feats = [f for f in self.features if f != feat]
            if nivel_r == "OK":
                nivel_f, msg_f, r2_val = self._check_functional_dependency(df_enc, feat, other_feats)
            else:
                nivel_f, msg_f, r2_val = "N/A", "skipped (feature realizada)", 0.0

            # Test 5: Correlación inter-feature
            nivel_i, msg_i, partners = self._check_inter_feature_correlation(df_enc, feat, corr_matrix)

            # Nivel de riesgo final: el más alto encontrado
            niveles = [nivel_r, nivel_c, nivel_m, nivel_f, nivel_i]
            priority = {"CRITICO": 4, "ALTO": 3, "MEDIO": 2, "BAJO": 1, "OK": 0, "N/A": 0}
            nivel_final = max(niveles, key=lambda x: priority.get(x, 0))

            # Score compuesto de leakage [0, 1]
            score = (
                (1.0 if nivel_r == "CRITICO" else 0.0) * 0.40 +
                min(abs(pearson_r), 1.0) * 0.25 +
                min(abs(spearman_r), 1.0) * 0.15 +
                min(r2_val, 1.0) * 0.20
            )

            motivo_parts = []
            if nivel_r != "OK": motivo_parts.append(f"[REALIZADO] {msg_r}")
            if nivel_c not in ("OK",): motivo_parts.append(f"[CORR] {msg_c}")
            if nivel_m not in ("OK",): motivo_parts.append(f"[MI] {msg_m}")
            if nivel_f not in ("OK", "N/A"): motivo_parts.append(f"[FUNC] {msg_f}")
            if nivel_i not in ("OK",): motivo_parts.append(f"[INTER] {msg_i}")

            rows.append({
                "feature":             feat,
                "nivel_riesgo":        nivel_final,
                "score_leakage":       round(score, 4),
                "pearson_target":      round(pearson_r, 4),
                "spearman_target":     round(spearman_r, 4),
                "mi_target":           round(mi_val, 4) if mi_computed else None,
                "r2_funcional":        round(r2_val, 4),
                "correlaciones_altas": ", ".join(partners),
                "recomendacion":       "ELIMINAR" if nivel_final == "CRITICO" else
                                       "REVISAR" if nivel_final == "ALTO" else
                                       "MONITOREAR" if nivel_final == "MEDIO" else "OK",
                "motivo":              " | ".join(motivo_parts) if motivo_parts else "Sin problemas detectados",
            })

        results_df = pd.DataFrame(rows).sort_values(
            ["score_leakage"], ascending=False
        ).reset_index(drop=True)
        self._results = results_df

        # Imprimir resumen
        self._print_summary(results_df)
        return results_df

    def _print_summary(self, df: pd.DataFrame) -> None:
        """Imprime tabla resumen en consola."""
        print(f"\n{'─'*70}")
        print("TABLA DE RIESGO DE LEAKAGE")
        print(f"{'─'*70}")
        print(f"{'FEATURE':<30} {'RIESGO':<10} {'SCORE':>7} {'PEARSON':>9} {'R2_FUNC':>9}  RECOM.")
        print(f"{'─'*70}")

        for _, row in df.iterrows():
            nivel = row["nivel_riesgo"]
            color_marker = {
                "CRITICO": "🔴",
                "ALTO":    "🟠",
                "MEDIO":   "🟡",
                "OK":      "🟢",
            }.get(nivel, "⚪")
            print(
                f"{color_marker} {row['feature']:<28} {nivel:<10} "
                f"{row['score_leakage']:>7.3f} {row['pearson_target']:>9.3f} "
                f"{row['r2_funcional']:>9.3f}  {row['recomendacion']}"
            )

        print(f"\n{'─'*70}")
        counts = df["nivel_riesgo"].value_counts()
        print("Resumen:")
        for nivel in ["CRITICO", "ALTO", "MEDIO", "OK"]:
            cnt = counts.get(nivel, 0)
            print(f"  {nivel:<10}: {cnt:>3} features")

        criticos = df[df["recomendacion"] == "ELIMINAR"]["feature"].tolist()
        revisar  = df[df["recomendacion"] == "REVISAR"]["feature"].tolist()

        if criticos:
            print(f"\n⚠ ELIMINAR inmediatamente: {criticos}")
        if revisar:
            print(f"⚠ REVISAR antes de entrenar: {revisar}")
        print()

    # ── Visualizaciones ───────────────────────────────────────────────────

    def plot_heatmap(
        self,
        out_path: Optional[Path] = None,
        max_features: int = 30,
    ) -> plt.Figure:
        """
        Genera heatmap de correlación entre features.
        Features marcadas por riesgo se destacan en el eje.
        """
        if self._corr_matrix is None:
            raise RuntimeError("Ejecutar run_full_audit() primero")

        feats = self.features[:max_features]
        corr  = self._corr_matrix.loc[feats, feats]

        risk_colors = {}
        if self._results is not None:
            for _, row in self._results.iterrows():
                nivel = row["nivel_riesgo"]
                risk_colors[row["feature"]] = {
                    "CRITICO": "#d32f2f",
                    "ALTO":    "#f57c00",
                    "MEDIO":   "#f9a825",
                    "OK":      "#388e3c",
                }.get(nivel, "#666666")

        fig, ax = plt.subplots(figsize=(14, 12))
        im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")

        ax.set_xticks(range(len(feats)))
        ax.set_yticks(range(len(feats)))
        ax.set_xticklabels(feats, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(feats, fontsize=8)

        # Colorear etiquetas por nivel de riesgo
        for tick, feat in zip(ax.get_xticklabels(), feats):
            tick.set_color(risk_colors.get(feat, "#333333"))
        for tick, feat in zip(ax.get_yticklabels(), feats):
            tick.set_color(risk_colors.get(feat, "#333333"))

        # Anotar celdas con correlaciones extremas
        for i in range(len(feats)):
            for j in range(len(feats)):
                val = corr.values[i, j]
                if abs(val) >= 0.95 and i != j:
                    ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                            fontsize=6, color="white", fontweight="bold")

        plt.colorbar(im, ax=ax, label="Correlación de Spearman")
        ax.set_title(
            f"MILPÍN v7 — Heatmap de Correlación entre Features\n"
            f"Etiquetas: Rojo=CRITICO, Naranja=ALTO, Amarillo=MEDIO, Verde=OK",
            fontsize=11, pad=15
        )

        patches = [
            mpatches.Patch(color="#d32f2f", label="CRITICO"),
            mpatches.Patch(color="#f57c00", label="ALTO"),
            mpatches.Patch(color="#f9a825", label="MEDIO"),
            mpatches.Patch(color="#388e3c", label="OK"),
        ]
        ax.legend(handles=patches, loc="upper right", bbox_to_anchor=(1.28, 1.0), fontsize=9)

        plt.tight_layout()

        if out_path:
            fig.savefig(out_path, dpi=150, bbox_inches="tight")
            print(f"[LeakageDetector] Heatmap guardado: {out_path}")

        return fig

    def plot_leakage_scores(self, out_path: Optional[Path] = None) -> plt.Figure:
        """Bar chart de score de leakage por feature."""
        if self._results is None:
            raise RuntimeError("Ejecutar run_full_audit() primero")

        df_plot = self._results.sort_values("score_leakage", ascending=True).tail(30)
        colors_map = {
            "CRITICO": "#d32f2f",
            "ALTO":    "#f57c00",
            "MEDIO":   "#f9a825",
            "OK":      "#388e3c",
        }
        colors = [colors_map.get(n, "#999999") for n in df_plot["nivel_riesgo"]]

        fig, ax = plt.subplots(figsize=(10, max(6, len(df_plot) * 0.35)))
        bars = ax.barh(df_plot["feature"], df_plot["score_leakage"], color=colors)
        ax.axvline(x=0.5, color="red", linestyle="--", alpha=0.6, label="Umbral peligro")
        ax.axvline(x=0.3, color="orange", linestyle="--", alpha=0.4, label="Umbral advertencia")
        ax.set_xlabel("Score de Leakage [0=seguro, 1=leakage total]")
        ax.set_title("MILPÍN v7 — Scores de Leakage por Feature")
        ax.legend(fontsize=9)
        plt.tight_layout()

        if out_path:
            fig.savefig(out_path, dpi=150, bbox_inches="tight")

        return fig

    def save_report(self, out_path: Path) -> None:
        """Guarda el reporte completo en CSV."""
        if self._results is None:
            raise RuntimeError("Ejecutar run_full_audit() primero")
        self._results.to_csv(out_path, index=False)
        print(f"[LeakageDetector] Reporte guardado: {out_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_audit_from_csv(
    data_path: Path,
    target: str = "volumen_agua_total_m3_ha",
    features_v7: Optional[list[str]] = None,
    out_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Carga CSV y ejecuta auditoría completa.
    Guarda heatmap, barplot y CSV de resultados en out_dir.
    """
    print(f"Cargando {data_path} ...")
    df = pd.read_csv(data_path, nrows=50_000)  # muestra para velocidad
    print(f"  {len(df):,} filas cargadas")

    detector = LeakageDetector(
        df=df,
        target=target,
        candidate_features=features_v7,
    )

    results = detector.run_full_audit()

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        detector.save_report(out_dir / "leakage_report.csv")
        detector.plot_heatmap(out_path=out_dir / "leakage_heatmap.png")
        detector.plot_leakage_scores(out_path=out_dir / "leakage_scores.png")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auditoría de Leakage Proxy — MILPÍN v7")
    parser.add_argument(
        "--data", type=Path,
        default=Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv",
    )
    parser.add_argument("--target", default="volumen_agua_total_m3_ha")
    parser.add_argument(
        "--out", type=Path,
        default=Path(__file__).parents[3] / "data" / "synthetic" / "leakage_audit",
    )
    args = parser.parse_args()

    run_audit_from_csv(args.data, target=args.target, out_dir=args.out)
