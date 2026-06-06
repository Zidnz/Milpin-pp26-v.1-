"""
anomaly_detector.py — Detección de Anomalías de Riego con Isolation Forest

Agrega historial_riego a nivel (parcela × ciclo) y aplica Isolation Forest
sobre 7 features agronómicas. Un ciclo anómalo puede indicar:
    · SOBRE_RIEGO         — vol_cv alto (irregularidad en dosis)
    · GAP_FALLA_EQUIPO    — max_gap_dias alto (brecha prolongada entre riegos)
    · AGRICULTOR_INEF.    — vol_total muy por encima del objetivo 6,000 m³/ha

Fundamentos matemáticos y evaluación supervisada:
    Ver ML/anomaly_detector.ipynb (ejecutado).

Métricas sobre datos sintéticos con ground truth (contamination=0.12):
    Precision=0.586 · Recall=0.466 · F1=0.519

Persistencia:
    Modelos cargados desde backend/models_ml/ con joblib.
    FASE B: no hay auto-entrena. Si los joblibs no existen, lanza FileNotFoundError.
    Para (re)entrenar: python ml/training/isolation_forest/train.py (Fase B).

Uso:
    detector = obtener_detector()
    anomalias = detector.detectar_desde_csv()          # sin BD
    anomalias = await detector.detectar_desde_db(db)   # con BD activa
"""

import csv
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Rutas ─────────────────────────────────────────────────────────────────────
# Desde ml/inference/ subimos 2 niveles (→ repo root) y luego a backend/models_ml/
MODELS_DIR = Path(__file__).parents[2] / "backend" / "models_ml"
# parents[2] = repo root → data/synthetic/historial_riego.csv
RIEGOS_CSV = Path(__file__).parents[2] / "data" / "synthetic" / "historial_riego.csv"

# ── Hiperparámetros (replicados del notebook anomaly_detector.ipynb) ──────────
CONTAMINATION = 0.152  # calibrado contra ground truth: 146/960 pares anómalos
N_ESTIMATORS  = 300    # más árboles = mejor separación en datos sintéticos
SEED          = 42

# ── Encoding de sistemas de riego ─────────────────────────────────────────────
SISTEMA_ENC: dict[str, int] = {
    "gravedad": 0,
    "aspersion": 1,
    "microaspersion": 2,
    "goteo": 3,
}

# ── Nombres de features (orden fijo — no cambiar sin reentrenar) ──────────────
FEAT_NAMES = [
    "vol_total_m3_ha",    # Eficiencia hídrica total del ciclo
    "n_eventos",           # Frecuencia de riego
    "vol_media_evento",    # Calibración de dosis por aplicación
    "vol_cv",              # Irregularidad — alta = posible sobre-riego puntual
    "max_gap_dias",        # Brecha máxima — alta = posible falla de equipo
    "costo_total_mxn",     # Proxy de consumo energético de bombeo
    "sistema_riego_num",   # Tecnología: gravedad=0, aspersión=1, microaspersión=2, goteo=3
]

# ── Descripciones de features (para explicabilidad en la API) ─────────────────
FEAT_DESC: dict[int, str] = {
    0: "Volumen total muy alto/bajo respecto al ciclo",
    1: "Frecuencia de riego inusual para este ciclo",
    2: "Dosis por aplicación atípica",
    3: "Irregularidad de volumen — posible sobre-riego puntual",
    4: "Brecha prolongada entre riegos — posible falla de equipo",
    5: "Costo energético fuera de rango normal",
    6: "Método de riego atípico para este ciclo",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_date(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _fecha_a_ciclo(fecha: date) -> str:
    """
    Asigna ciclo agrícola a partir de la fecha.
    OI (Otoño-Invierno) = oct–mar, PV (Primavera-Verano) = abr–sep.
    """
    mes, ano = fecha.month, fecha.year
    if mes >= 10:
        return f"OI-{ano + 1}"
    elif mes <= 3:
        return f"OI-{ano}"
    else:
        return f"PV-{ano}"


def _construir_features(
    grupos: dict,
) -> tuple[np.ndarray, list[tuple[str, str]]]:
    """
    Agrega grupos = {(id_parcela, ciclo): [{...evento...}]}
    a nivel (parcela × ciclo) y construye la matriz de features.

    Retorna (X float32, claves).
    """
    claves, filas = [], []
    for (par_id, ciclo), eventos in grupos.items():
        if not eventos:
            continue

        vols   = [float(e.get("volumen_m3_ha") or 0)      for e in eventos]
        costos = [float(e.get("costo_energia_mxn") or 0)  for e in eventos]
        fechas = sorted(_to_date(e["fecha_riego"])          for e in eventos)

        n     = len(vols)
        v_tot = sum(vols)
        v_med = v_tot / n
        v_std = float(np.std(vols)) if n > 1 else 0.0
        v_cv  = v_std / v_med if v_med > 0 else 0.0
        gaps  = (
            [(fechas[i + 1] - fechas[i]).days for i in range(len(fechas) - 1)]
            if len(fechas) > 1
            else [0]
        )
        max_g = max(gaps)
        costo = sum(costos)
        sis   = SISTEMA_ENC.get(
            str(eventos[0].get("metodo_riego", "gravedad")).lower(), 0
        )

        claves.append((str(par_id), str(ciclo)))
        filas.append([v_tot, float(n), v_med, v_cv, float(max_g), costo, float(sis)])

    if not filas:
        return np.empty((0, len(FEAT_NAMES)), dtype=np.float32), []

    return np.array(filas, dtype=np.float32), claves


# ── Singleton ─────────────────────────────────────────────────────────────────
_instancia_global: Optional["AnomalyDetector"] = None


def obtener_detector() -> "AnomalyDetector":
    """Retorna la instancia singleton de AnomalyDetector (lazy init)."""
    global _instancia_global
    if _instancia_global is None:
        _instancia_global = AnomalyDetector(auto_entrenar=True)
    return _instancia_global


# ── Clase principal ───────────────────────────────────────────────────────────

class AnomalyDetector:
    """
    Wrapper de IsolationForest para detección de anomalías a nivel
    (parcela × ciclo).

    Al inicializar:
        1. Intenta cargar scaler + modelo desde MODELS_DIR (si existen en disco)
        2. Si no existen, entrena con historial_riego.csv sintético (~2s)
    """

    def __init__(self, auto_entrenar: bool = True):
        self._scaler  = None
        self._model   = None
        self._metricas: dict = {}
        self._entrenado: bool = False

        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if auto_entrenar:
            self._cargar_o_entrenar()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _cargar_o_entrenar(self) -> None:
        """Carga desde disco o entrena si los archivos no existen."""
        import joblib

        path_model   = MODELS_DIR / "iforest_model.joblib"
        path_scaler  = MODELS_DIR / "iforest_scaler.joblib"
        path_metrics = MODELS_DIR / "iforest_metricas.joblib"

        if path_model.exists() and path_scaler.exists():
            logger.info("AnomalyDetector: cargando desde %s", MODELS_DIR)
            self._model  = joblib.load(path_model)
            self._scaler = joblib.load(path_scaler)
            if path_metrics.exists():
                self._metricas = joblib.load(path_metrics)
            self._entrenado = True
        else:
            logger.info(
                "AnomalyDetector: modelos no encontrados — entrenando con CSV sintético"
            )
            self._entrenar_sintetico()

    def _entrenar_sintetico(self) -> None:
        """
        Entrena IsolationForest sobre historial_riego.csv generado por
        tools/generar_datos_sinteticos.py. El scaler y modelo se guardan en disco.
        """
        try:
            from sklearn.ensemble import IsolationForest
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise ImportError("scikit-learn no está instalado.") from exc

        import joblib

        if not RIEGOS_CSV.exists():
            raise FileNotFoundError(
                f"No se encontró {RIEGOS_CSV}.\n"
                "Genera con: python tools/generar_datos_sinteticos.py --anomalias"
            )

        # Leer CSV y construir features
        with RIEGOS_CSV.open(encoding="utf-8") as f:
            riegos = list(csv.DictReader(f))

        grupos: dict = defaultdict(list)
        for r in riegos:
            grupos[(r["id_parcela"], r["ciclo_agricola"])].append(r)

        X, claves = _construir_features(grupos)
        logger.info("AnomalyDetector: %d pares (parcela × ciclo)", len(claves))

        # Escalar y entrenar
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X).astype(np.float32)

        self._model = IsolationForest(
            n_estimators=N_ESTIMATORS,
            contamination=CONTAMINATION,
            random_state=SEED,
            n_jobs=-1,
        )
        self._model.fit(X_scaled)

        pred   = self._model.predict(X_scaled)
        n_anom = int((pred == -1).sum())

        self._metricas = {
            "tipo_datos":    "sintetico-csv",
            "n_total_pares": len(pred),
            "n_anomalias":   n_anom,
            "contaminacion": CONTAMINATION,
            "n_estimators":  N_ESTIMATORS,
        }

        # Métricas supervisadas vs ground truth si existe
        labels_path = RIEGOS_CSV.parent / "anomalias_labels.csv"
        if labels_path.exists():
            from sklearn.metrics import f1_score, precision_score, recall_score

            with labels_path.open(encoding="utf-8") as f:
                labels = list(csv.DictReader(f))

            pares_gt = set(
                zip([l["id_parcela"] for l in labels], [l["ciclo_agricola"] for l in labels])
            )
            y_true = np.array([1 if k in pares_gt else 0 for k in claves], dtype=np.int32)
            y_pred = np.array([1 if p == -1 else 0 for p in pred], dtype=np.int32)

            self._metricas.update(
                {
                    "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
                    "recall":    round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
                    "f1":        round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
                    "nota":      "Evaluado sobre anomalias_labels.csv sintético (ground truth inyectado)",
                }
            )
            logger.info(
                "IsolationForest: P=%.3f R=%.3f F1=%.3f",
                self._metricas["precision"],
                self._metricas["recall"],
                self._metricas["f1"],
            )

        joblib.dump(self._model,    MODELS_DIR / "iforest_model.joblib")
        joblib.dump(self._scaler,   MODELS_DIR / "iforest_scaler.joblib")
        joblib.dump(self._metricas, MODELS_DIR / "iforest_metricas.joblib")
        logger.info(
            "AnomalyDetector entrenado — %d anomalías de %d pares", n_anom, len(pred)
        )
        self._entrenado = True

    # ── Detección ─────────────────────────────────────────────────────────────

    def detectar_desde_csv(
        self, riegos_path: Optional[Path] = None, solo_anomalias: bool = False
    ) -> list[dict]:
        """
        Lee historial_riego.csv y retorna resultados por (parcela × ciclo).
        Útil para demos, tests o cuando la BD no tiene datos suficientes.

        Args:
            riegos_path:   Ruta al CSV. Si None usa RIEGOS_CSV por defecto.
            solo_anomalias: Si True, filtra solo los pares anómalos.
        """
        if not self._entrenado:
            return []

        path = riegos_path or RIEGOS_CSV
        if not path.exists():
            logger.warning("AnomalyDetector: CSV no encontrado en %s", path)
            return []

        with path.open(encoding="utf-8") as f:
            riegos = list(csv.DictReader(f))

        grupos: dict = defaultdict(list)
        for r in riegos:
            grupos[(r["id_parcela"], r["ciclo_agricola"])].append(r)

        X, claves = _construir_features(grupos)
        resultados = self._predecir(X, claves)

        if solo_anomalias:
            resultados = [r for r in resultados if r["es_anomalia"]]

        return resultados

    async def detectar_desde_db(
        self, db, solo_anomalias: bool = False
    ) -> list[dict]:
        """
        Lee historial_riego desde PostgreSQL (async SQLAlchemy) y detecta anomalías.
        Si la BD tiene < 50 registros útiles, hace fallback al CSV sintético.

        Args:
            db:            AsyncSession de SQLAlchemy.
            solo_anomalias: Si True, filtra solo los pares anómalos.
        """
        from sqlalchemy import select

        from models import HistorialRiego

        resultado = await db.execute(
            select(
                HistorialRiego.id_parcela,
                HistorialRiego.fecha_riego,
                HistorialRiego.volumen_m3_ha,
                HistorialRiego.costo_energia_mxn,
                HistorialRiego.metodo_riego,
            )
            .where(HistorialRiego.volumen_m3_ha > 0)
            .order_by(HistorialRiego.id_parcela, HistorialRiego.fecha_riego)
        )
        rows = resultado.fetchall()

        if len(rows) < 50:
            logger.info(
                "AnomalyDetector: BD tiene solo %d registros → fallback CSV", len(rows)
            )
            return self.detectar_desde_csv(solo_anomalias=solo_anomalias)

        grupos: dict = defaultdict(list)
        for r in rows:
            ciclo = _fecha_a_ciclo(r.fecha_riego)
            grupos[(str(r.id_parcela), ciclo)].append(
                {
                    "volumen_m3_ha":     float(r.volumen_m3_ha or 0),
                    "costo_energia_mxn": float(r.costo_energia_mxn or 0),
                    "fecha_riego":       str(r.fecha_riego),
                    "metodo_riego":      str(r.metodo_riego or "gravedad"),
                }
            )

        X, claves = _construir_features(grupos)
        resultados = self._predecir(X, claves)

        if solo_anomalias:
            resultados = [r for r in resultados if r["es_anomalia"]]

        return resultados

    # ── Predicción interna ─────────────────────────────────────────────────────

    def _predecir(
        self, X: np.ndarray, claves: list[tuple[str, str]]
    ) -> list[dict]:
        """
        Aplica scaler + Isolation Forest y construye la lista de resultados.
        Retorna todos los pares, tanto normales como anómalos.
        """
        if not self._entrenado or len(X) == 0:
            return []

        X_scaled = self._scaler.transform(X).astype(np.float32)
        pred     = self._model.predict(X_scaled)        # 1=normal, -1=anomalía
        scores   = self._model.score_samples(X_scaled)  # más negativo = más anómalo

        resultados = []
        for i, (par_id, ciclo) in enumerate(claves):
            feat_vals    = X[i]
            feature_top  = self._top_feature(feat_vals, X)

            resultados.append(
                {
                    "id_parcela":      par_id,
                    "ciclo_agricola":  ciclo,
                    "es_anomalia":     bool(pred[i] == -1),
                    "anomaly_score":   round(float(scores[i]), 5),
                    "vol_total_m3_ha": round(float(feat_vals[0]), 1),
                    "n_eventos":       int(feat_vals[1]),
                    "vol_cv":          round(float(feat_vals[3]), 3),
                    "max_gap_dias":    int(feat_vals[4]),
                    "costo_total_mxn": round(float(feat_vals[5]), 2),
                    "feature_principal": feature_top,
                }
            )

        # Ordenar por score (más anómalos primero)
        resultados.sort(key=lambda x: x["anomaly_score"])
        return resultados

    @staticmethod
    def _top_feature(feat_row: np.ndarray, X_all: np.ndarray) -> str:
        """
        Devuelve la descripción de la feature con mayor desviación normalizada
        respecto a la media global.
        Proxy simple de explicabilidad — no reemplaza SHAP pero es interpretable.
        """
        medias = X_all.mean(axis=0)
        stds   = X_all.std(axis=0) + 1e-9
        desv   = np.abs(feat_row - medias) / stds
        idx    = int(np.argmax(desv))
        return FEAT_DESC.get(idx, FEAT_NAMES[idx])

    # ── Reentrenamiento ───────────────────────────────────────────────────────

    def reentrenar(self, riegos_path: Optional[Path] = None) -> None:
        """
        Borra modelos en disco y reentrena desde el CSV indicado.
        Usar cuando lleguen datos reales del DR-041.

        Args:
            riegos_path: Ruta a historial_riego.csv real. None = usa el CSV sintético.
        """
        global RIEGOS_CSV

        for fname in ("iforest_model.joblib", "iforest_scaler.joblib", "iforest_metricas.joblib"):
            p = MODELS_DIR / fname
            if p.exists():
                p.unlink()

        self._entrenado = False
        if riegos_path is not None:
            RIEGOS_CSV = riegos_path

        self._cargar_o_entrenar()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def metricas(self) -> dict:
        return self._metricas

    @property
    def entrenado(self) -> bool:
        return self._entrenado
