"""
MILPÍN — Detector de anomalías en historial de riego
=====================================================

Usa Isolation Forest sobre features agregadas a nivel (parcela × ciclo)
para detectar comportamientos de riego estadísticamente atípicos.

LIMITACIÓN EXPLÍCITA
--------------------
Este modelo aprende qué es "normal" según las distribuciones de
generar_datos_sinteticos.py. Si --labels-file está disponible, el script
evalúa con precision/recall real contra el ground truth inyectado.

Lo que este ejercicio SÍ aporta:
  1. Evaluar que el detector recupera las etiquetas conocidas.
  2. Construir el pipeline de features reutilizable con datos reales.
  3. Explorar qué señales tienen mayor poder discriminativo en este dominio.

Lo que NO se puede afirmar: que el modelo detecta anomalías reales en DR-041.

Uso
---
    # Primero generar datos con anomalías:
    python tools/generar_datos_sinteticos.py --anomalias

    # Luego correr el detector:
    python tools/anomaly_detector.py
    python tools/anomaly_detector.py --contamination 0.15 --threshold 0.10
    python tools/anomaly_detector.py --no-labels   # si no hay labels

Features usadas (nivel parcela × ciclo)
-----------------------------------------
  vol_total_m3_ha  : volumen total aplicado en el ciclo
  n_eventos        : número de eventos de riego
  vol_media        : volumen promedio por evento
  vol_cv           : coef. variación (std/media); detecta eventos outlier
  max_gap_dias     : mayor hueco entre riegos consecutivos (días)
  costo_total_mxn  : costo energético total del ciclo
  sistema_riego_num: sistema codificado (gravedad=0 .. goteo=3)

El CV (vol_cv) es la feature más importante para SOBRE_RIEGO.
El max_gap_dias es la feature más importante para GAP_FALLA_EQUIPO.
El vol_total es la feature más importante para AGRICULTOR_INEFICIENTE.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

# Intentar importar scikit-learn; dar error descriptivo si no está
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import precision_score, recall_score, f1_score, classification_report
except ImportError as e:
    raise SystemExit(
        f"scikit-learn no disponible: {e}\n"
        "Instalar con: pip install scikit-learn"
    )

# ---------------------------------------------------------------------------
# Codificación de sistema de riego
# ---------------------------------------------------------------------------

SISTEMA_RIEGO_ENCODE = {
    "gravedad": 0,
    "aspersion": 1,
    "microaspersion": 2,
    "goteo": 3,
}


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def cargar_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_date(s: str) -> date:
    """Parsea 'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM:SS+00:00' a date."""
    return date.fromisoformat(s[:10])


def construir_features(
    riegos: list[dict],
) -> tuple[np.ndarray, list[tuple[str, str]], list[str]]:
    """
    Agrega historial_riego a nivel (id_parcela, ciclo_agricola) y
    construye una matriz de features X.

    Devuelve:
        X       : np.ndarray (n_pares, n_features)
        claves  : list of (id_parcela, ciclo_agricola) — índice de filas
        nombres : list of str — nombres de las columnas de X
    """
    # Agrupar por (parcela, ciclo)
    grupos: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in riegos:
        key = (r["id_parcela"], r["ciclo_agricola"])
        grupos[key].append(r)

    claves: list[tuple[str, str]] = []
    filas: list[list[float]] = []

    for (par_id, ciclo), eventos in grupos.items():
        vols = [float(e["volumen_m3_ha"]) for e in eventos]
        costos = [float(e["costo_energia_mxn"]) for e in eventos]
        fechas = sorted(_parse_date(e["fecha_riego"]) for e in eventos)

        # Volumen total y estadísticas
        vol_total = sum(vols)
        n_eventos = len(vols)
        vol_media = vol_total / n_eventos
        vol_std = float(np.std(vols)) if n_eventos > 1 else 0.0
        # CV: std/media — alto si hay eventos muy irregulares
        vol_cv = vol_std / vol_media if vol_media > 0 else 0.0

        # Gap máximo entre riegos consecutivos
        if len(fechas) > 1:
            gaps = [(fechas[i+1] - fechas[i]).days for i in range(len(fechas) - 1)]
            max_gap = max(gaps)
        else:
            max_gap = 0

        costo_total = sum(costos)

        # Sistema de riego del primer evento (todos deben ser el mismo en la parcela)
        sistema = SISTEMA_RIEGO_ENCODE.get(eventos[0].get("metodo_riego", "gravedad"), 0)

        claves.append((par_id, ciclo))
        filas.append([
            vol_total,
            float(n_eventos),
            vol_media,
            vol_cv,
            float(max_gap),
            costo_total,
            float(sistema),
        ])

    nombres = [
        "vol_total_m3_ha",
        "n_eventos",
        "vol_media_evento",
        "vol_cv",
        "max_gap_dias",
        "costo_total_mxn",
        "sistema_riego_num",
    ]

    X = np.array(filas, dtype=np.float64)
    return X, claves, nombres


# ---------------------------------------------------------------------------
# Entrenamiento y detección
# ---------------------------------------------------------------------------

def entrenar_y_detectar(
    X: np.ndarray,
    contamination: float = 0.10,
    n_estimators: int = 200,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Escala X y entrena Isolation Forest.

    Devuelve:
        predicciones : np.ndarray de int  (1 = normal, -1 = anomalía, conv. sklearn)
        scores       : np.ndarray de float (anomaly score; más negativo = más anómalo)
    """
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clf = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    clf.fit(X_scaled)
    predicciones = clf.predict(X_scaled)    # 1 = normal, -1 = anomalía
    scores = clf.score_samples(X_scaled)    # más negativo = más anómalo

    return predicciones, scores


# ---------------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------------

def evaluar(
    claves: list[tuple[str, str]],
    predicciones: np.ndarray,
    labels: list[dict],
    threshold_score: Optional[float] = None,
    scores: Optional[np.ndarray] = None,
) -> None:
    """
    Compara predicciones del detector con el ground truth de labels.
    Imprime precision, recall, F1 y detalle por tipo de anomalía.

    predicciones sklearn: 1=normal, -1=anomalía
    ground truth: 0=normal, 1=anomalía (convención binaria estándar)
    """
    # Ground truth: construir set de pares anómalos
    pares_anomalos: set[tuple[str, str]] = set()
    tipo_por_par: dict[tuple[str, str], str] = {}
    for l in labels:
        par = (l["id_parcela"], l["ciclo_agricola"])
        pares_anomalos.add(par)
        tipo_por_par[par] = l["tipo_anomalia"]

    y_true = np.array([1 if k in pares_anomalos else 0 for k in claves])
    # Convertir convención sklearn (-1/1) a binaria (1/0)
    y_pred = np.array([1 if p == -1 else 0 for p in predicciones])

    print("\n" + "="*60)
    print("EVALUACIÓN vs. GROUND TRUTH")
    print("="*60)
    print(f"\nTotal pares (parcela × ciclo) : {len(claves)}")
    print(f"Anómalos en labels            : {y_true.sum()} ({y_true.mean()*100:.1f}%)")
    print(f"Detectados como anómalos      : {y_pred.sum()} ({y_pred.mean()*100:.1f}%)")

    prec = precision_score(y_true, y_pred, zero_division=0)
    rec  = recall_score(y_true, y_pred, zero_division=0)
    f1   = f1_score(y_true, y_pred, zero_division=0)
    print(f"\nPrecision : {prec:.3f}  (de los que el modelo flagea, ¿cuántos son realmente anómalos?)")
    print(f"Recall    : {rec:.3f}  (de los anómalos reales, ¿cuántos detecta?)")
    print(f"F1        : {f1:.3f}")

    # Detalle por tipo de anomalía
    print("\n── Recall por tipo de anomalía ──────────────────────────")
    tipos = sorted(set(tipo_por_par.values()))
    for tipo in tipos:
        pares_tipo = {k for k, t in tipo_por_par.items() if t == tipo}
        detectados = sum(1 for i, k in enumerate(claves) if k in pares_tipo and y_pred[i] == 1)
        total_tipo = len(pares_tipo)
        rec_tipo = detectados / total_tipo if total_tipo > 0 else 0
        print(f"  {tipo:<30}: {detectados}/{total_tipo} = {rec_tipo:.2%}")

    print("\n── Nota de interpretación ───────────────────────────────")
    print("  Recall alto + Precision baja → el modelo es conservador")
    print("  (flagea muchos normales). Subir contamination si hay")
    print("  muchos falsos positivos, bajarla si pierde anómalos reales.")
    print("="*60)


# ---------------------------------------------------------------------------
# Escritura de resultados
# ---------------------------------------------------------------------------

def guardar_reporte(
    out_path: Path,
    claves: list[tuple[str, str]],
    predicciones: np.ndarray,
    scores: np.ndarray,
    nombres_features: list[str],
    X: np.ndarray,
    labels: Optional[list[dict]] = None,
) -> None:
    """Escribe anomaly_report.csv con scores y predicciones por (parcela, ciclo)."""
    pares_anomalos: set[tuple[str, str]] = set()
    tipo_por_par: dict[tuple[str, str], str] = {}
    if labels:
        for l in labels:
            par = (l["id_parcela"], l["ciclo_agricola"])
            pares_anomalos.add(par)
            tipo_por_par[par] = l["tipo_anomalia"]

    filas = []
    for i, (par_id, ciclo) in enumerate(claves):
        fila: dict = {
            "id_parcela": par_id,
            "ciclo_agricola": ciclo,
            "anomalia_predicha": int(predicciones[i] == -1),
            "anomaly_score": round(float(scores[i]), 5),
        }
        for j, nombre in enumerate(nombres_features):
            fila[nombre] = round(float(X[i, j]), 4)
        if labels is not None:
            k = (par_id, ciclo)
            fila["ground_truth"] = int(k in pares_anomalos)
            fila["tipo_anomalia_real"] = tipo_por_par.get(k, "")
        filas.append(fila)

    # Ordenar por score (más anómalos primero)
    filas.sort(key=lambda f: f["anomaly_score"])

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)

    print(f"\n[ok] Reporte guardado en: {out_path}")
    print(f"     {len([f for f in filas if f['anomalia_predicha']])} anomalías "
          f"de {len(filas)} pares totales")


# ---------------------------------------------------------------------------
# Feature importance (aproximada)
# ---------------------------------------------------------------------------

def feature_importance_aproximada(
    X: np.ndarray,
    predicciones: np.ndarray,
    nombres: list[str],
) -> None:
    """
    Proxy de importancia: diferencia de medias entre anómalos y normales,
    normalizada por la desviación global. Equivalente a un efecto Cohen's d.

    No es la importancia real del modelo (IsolationForest no la expone),
    pero es interpretable y útil para entender qué feature impulsa las detecciones.
    """
    anomalos = X[predicciones == -1]
    normales = X[predicciones == 1]

    print("\n── Feature importance aproximada (Cohen's d) ────────────")
    print(f"  {'Feature':<25} {'Normal_μ':>10} {'Anómalo_μ':>10} {'Cohen d':>9}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*9}")

    importancias = []
    for j, nombre in enumerate(nombres):
        mu_norm = normales[:, j].mean() if len(normales) > 0 else 0
        mu_anom = anomalos[:, j].mean() if len(anomalos) > 0 else 0
        std_global = X[:, j].std() + 1e-9
        d = abs(mu_anom - mu_norm) / std_global
        importancias.append((nombre, mu_norm, mu_anom, d))

    importancias.sort(key=lambda x: -x[3])
    for nombre, mu_n, mu_a, d in importancias:
        print(f"  {nombre:<25} {mu_n:>10.2f} {mu_a:>10.2f} {d:>9.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=str,
                    default=str(Path(__file__).resolve().parent.parent / "data" / "synthetic"),
                    help="Directorio con CSVs sintéticos")
    ap.add_argument("--contamination", type=float, default=0.12,
                    help="Fracción esperada de anomalías (default 0.12)")
    ap.add_argument("--n-estimators", type=int, default=200,
                    help="Número de árboles del Isolation Forest")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-labels", action="store_true",
                    help="No cargar anomalias_labels.csv (datos sin inyección)")
    ap.add_argument("--out", type=str, default=None,
                    help="Ruta del reporte CSV (default: data-dir/anomaly_report.csv)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    out_path = Path(args.out) if args.out else data_dir / "anomaly_report.csv"

    # ── Cargar datos ──────────────────────────────────────────────────────
    riegos_path = data_dir / "historial_riego.csv"
    if not riegos_path.exists():
        raise SystemExit(f"No se encontró {riegos_path}. "
                         "Ejecuta primero generar_datos_sinteticos.py")

    print(f"\nMILPÍN — Detector de anomalías (seed={args.seed})")
    print(f"Datos: {data_dir}")
    riegos = cargar_csv(riegos_path)
    print(f"  historial_riego: {len(riegos)} eventos")

    labels: list[dict] = []
    if not args.no_labels:
        labels_path = data_dir / "anomalias_labels.csv"
        if labels_path.exists():
            labels = cargar_csv(labels_path)
            print(f"  anomalias_labels: {len(labels)} pares etiquetados")
        else:
            print("  [aviso] anomalias_labels.csv no encontrado — "
                  "corriendo sin evaluación. Usa --anomalias al generar datos.")

    # ── Feature engineering ───────────────────────────────────────────────
    print("\nConstruyendo features (parcela × ciclo)...")
    X, claves, nombres_features = construir_features(riegos)
    print(f"  Matriz: {X.shape[0]} pares × {X.shape[1]} features")

    # ── Entrenamiento ─────────────────────────────────────────────────────
    print(f"\nEntrenando Isolation Forest "
          f"(contamination={args.contamination}, n_estimators={args.n_estimators})...")
    predicciones, scores = entrenar_y_detectar(
        X,
        contamination=args.contamination,
        n_estimators=args.n_estimators,
        random_state=args.seed,
    )
    n_anomalos = (predicciones == -1).sum()
    print(f"  Anomalías detectadas: {n_anomalos} ({n_anomalos/len(predicciones)*100:.1f}%)")

    # ── Feature importance ────────────────────────────────────────────────
    feature_importance_aproximada(X, predicciones, nombres_features)

    # ── Evaluación ────────────────────────────────────────────────────────
    if labels:
        evaluar(claves, predicciones, labels)
    else:
        print("\n[sin labels] — no se puede evaluar precision/recall.")
        print("  Para obtener evaluación, genera los datos con --anomalias.")

    # ── Guardar reporte ───────────────────────────────────────────────────
    guardar_reporte(out_path, claves, predicciones, scores,
                    nombres_features, X,
                    labels=labels if labels else None)


if __name__ == "__main__":
    main()
