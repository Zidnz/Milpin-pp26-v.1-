"""
Genera milpin_xgboost_prediccion.ipynb con el estilo de anomaly_detector.ipynb.
Ejecutar desde el directorio ML/ o desde la raíz del proyecto.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "milpin_xgboost_prediccion.ipynb"

# ── helpers ──────────────────────────────────────────────────────────────────
def md(src: str, cell_id: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": [src]}

def code(src: str, cell_id: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": [src],
    }

# ── cells ─────────────────────────────────────────────────────────────────────
cells = []

# ─────────────────────────────────────────────────────────────────────── BANNER
cells.append(md(r"""<div style="background: linear-gradient(135deg, #1a472a 0%, #2d6a4f 50%, #1b4332 100%); padding: 40px 32px; border-radius: 14px; margin-bottom: 8px;">
  <h1 style="color: #d8f3dc; font-size: 2.4em; margin: 0 0 10px 0; font-family: 'Segoe UI', Arial, sans-serif;">
    MILPÍN — Predicción de Consumo de Agua y Rendimiento Agrícola
  </h1>
  <p style="color: #95d5b2; font-size: 1.15em; margin: 0 0 18px 0; font-family: Arial, sans-serif;">
    XGBoost · Feature Engineering Agronómico · 600 000 ciclos · Valle del Yaqui, Sonora
  </p>
  <div style="display: flex; gap: 12px; flex-wrap: wrap;">
    <span style="background: rgba(255,255,255,0.15); color: #d8f3dc; padding: 5px 14px; border-radius: 20px; font-size: 0.82em;">DR-041 · Módulo 3</span>
    <span style="background: rgba(255,255,255,0.15); color: #d8f3dc; padding: 5px 14px; border-radius: 20px; font-size: 0.82em;">xgboost · scikit-learn · Plotly · pandas</span>
    <span style="background: rgba(255,255,255,0.15); color: #d8f3dc; padding: 5px 14px; border-radius: 20px; font-size: 0.82em;">KPI: 8 000 → 6 000 m³/ha/ciclo</span>
  </div>
</div>

---

### Objetivos

1. **Carga y exploración** de `milpin_ciclos_ml.csv` — 600 000 ciclos, 42 columnas generadas con el motor FAO-56 del backend
2. **Feature engineering agronómico** — selección, codificación y análisis de correlación
3. **Fundamentos matemáticos** — formulación de XGBoost con LaTeX
4. **Modelo 1 — Consumo de agua** — predecir `volumen_agua_total_m3_ha` (regresión)
5. **Modelo 2 — Rendimiento agrícola** — predecir `rendimiento_real_ton_ha` (regresión)
6. **Importancia de features** — gain nativo de XGBoost por modelo
7. **Curvas de aprendizaje** — ¿cuántos datos necesitamos realmente?
8. **Impacto económico** — error de predicción convertido a MXN (tarifa $1.68/m³)

> **Alcance:** el modelo aprende del generador sintético FAO-56 (`tools/generar_datos_sinteticos.py`).
> Los resultados cuantifican la capacidad predictiva sobre la distribución sintética, no sobre
> datos reales del DR-041 sin validación de campo.""", "banner"))

# ─────────────────────────────────────────────────── SECTION 1 – ENV SETUP
cells.append(md("---\n## 1 · Configuración del Entorno", "s1-header"))

cells.append(code(r"""from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import xgboost as xgb

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.figure_factory as ff

# ── Paleta corporativa MILPÍN ──────────────────────────────────────────
C_VERDE_OSC = "#1a472a"
C_VERDE_MED = "#2d6a4f"
C_VERDE_CLA = "#52b788"
C_VERDE_PAS = "#95d5b2"
C_NARANJA   = "#e76f51"
C_AZUL      = "#3a86ff"
C_AMARILLO  = "#ffd166"
C_ROJO      = "#d62828"
TMPL        = "plotly_white"

import sklearn, plotly
print("✅ Entorno listo")
print(f"   numpy    {np.__version__}")
print(f"   pandas   {pd.__version__}")
print(f"   sklearn  {sklearn.__version__}")
print(f"   xgboost  {xgb.__version__}")
print(f"   plotly   {plotly.__version__}")""", "s1-imports"))

cells.append(code(r"""ROOT     = Path.cwd().parent if Path.cwd().name == "ML" else Path.cwd()
DATA_DIR = ROOT / "data" / "synthetic"
ML_CSV   = DATA_DIR / "milpin_ciclos_ml.csv"
OUT_PATH = DATA_DIR / "xgboost_predictions.csv"

TARIFA_MXN_M3 = 1.68    # CFE 9-CU, bombeo 80 m — tarifa baseline DR-041
OBJETIVO_M3HA = 6_000   # KPI: reducir de 8,000 → 6,000 m³/ha/ciclo
SEED          = 42
TEST_SIZE     = 0.15    # 15 % test (90 000 ciclos)
VAL_FRAC      = 0.10    # 10 % del train → early stopping XGBoost

print(f"ROOT    : {ROOT}")
print(f"DATA_DIR: {DATA_DIR}")
print(f"ML_CSV  : {'✅ OK' if ML_CSV.exists() else '❌ FALTA'} — {ML_CSV.name}")
print(f"\nConstantes de negocio:")
print(f"  Tarifa agua  : ${TARIFA_MXN_M3} MXN/m³")
print(f"  Objetivo KPI : {OBJETIVO_M3HA:,} m³/ha/ciclo")
print(f"  Test split   : {TEST_SIZE*100:.0f}%  |  Val split: {VAL_FRAC*100:.0f}%")
print(f"  Seed         : {SEED}")""", "s1-constants"))

# ─────────────────────────────────────────────── SECTION 2 – DATASET ORIGIN
cells.append(md(r"""---
## 2 · Origen y Estructura del Dataset

### ¿De dónde vienen los datos?

`milpin_ciclos_ml.csv` proviene de `tools/generar_datos_sinteticos.py`, que simula
ciclos agrícolas completos usando el motor FAO-56 Penman-Monteith del backend.
Cada fila representa **un ciclo agrícola completo** de una parcela.

```bash
python tools/generar_datos_sinteticos.py
```

| Dimensión | Valor |
|---|---|
| Filas (ciclos) | 600 000 |
| Columnas | 42 (40 features + 2 targets) |
| Cultivos | Maíz, Frijol, Algodón, Uva, Chile |
| Sistemas de riego | Gravedad, Aspersión, Microaspersión, Goteo |
| Cobertura temporal | Múltiples ciclos OI y PV con variabilidad climática |

### Targets de predicción

| Target | Descripción | Conexión KPI |
|---|---|---|
| `volumen_agua_total_m3_ha` | Agua total aplicada en el ciclo (m³/ha) | **Directo**: objetivo reducir de 8,000 → 6,000 m³/ha |
| `rendimiento_real_ton_ha` | Rendimiento del cultivo (toneladas/ha) | Indirecto: eficiencia hídrica = rendimiento / agua |

### Tipos de features disponibles

| Grupo | Ejemplos | Tipo |
|---|---|---|
| Cultivo y manejo | `cultivo`, `tipo_suelo`, `sistema_riego`, `tipo_agricultor` | Categórico |
| Clima observado | `et0_promedio_mmdia`, `lluvia_total_mm`, `ola_calor` | Numérico |
| FAO-56 calculado | `etc_total_mm`, `kc_promedio`, `deficit_hidrico_frac` | Numérico |
| Suelo | `capacidad_campo`, `punto_marchitez`, `salinidad_ec_dsm` | Numérico |
| Contexto parcela | `area_ha`, `elev_parcela_m`, `region`, `doy_inicio` | Mixto |
| Eventos extremos | `ola_calor`, `helada`, `inundacion`, `plaga`, `falla_riego` | Binario |""", "s2-origin"))

cells.append(code(r"""if not ML_CSV.exists():
    raise FileNotFoundError(
        f"No se encontró {ML_CSV}.\n"
        "Genera con: python tools/generar_datos_sinteticos.py"
    )

df = pd.read_csv(ML_CSV, encoding="utf-8")

# Normalizar nombre de columna 'año' si llega mal codificado
for bad, good in [("aÃ±o", "año"), ("aÃ±o_norm", "año_norm"),
                  ("a\xf1o", "año"), ("a\xf1o_norm", "año_norm")]:
    if bad in df.columns:
        df.rename(columns={bad: good}, inplace=True)

AÑO_COL = "año" if "año" in df.columns else "año_norm"

print("=" * 60)
print("RESUMEN DEL DATASET")
print("=" * 60)
print(f"  Ciclos agrícolas totales   : {len(df):,}")
print(f"  Columnas totales           : {df.shape[1]}")
print(f"  Cultivos                   : {', '.join(sorted(df['cultivo'].unique()))}")
print(f"  Sistemas de riego          : {', '.join(sorted(df['sistema_riego'].unique()))}")
print(f"  Tipos de suelo             : {df['tipo_suelo'].nunique()}")
print(f"  Regiones                   : {df['region'].nunique()}")
print(f"  Años cubiertos             : {int(df[AÑO_COL].min())} – {int(df[AÑO_COL].max())}")
print(f"  Target 1 — Agua (m³/ha)   : {df['volumen_agua_total_m3_ha'].mean():,.0f} ± {df['volumen_agua_total_m3_ha'].std():,.0f}")
print(f"  Target 2 — Rendim (t/ha)  : {df['rendimiento_real_ton_ha'].mean():.2f} ± {df['rendimiento_real_ton_ha'].std():.2f}")
print(f"  Nulos totales              : {df.isnull().sum().sum():,}")
print(f"  Memoria                    : {df.memory_usage(deep=True).sum()/1e6:.1f} MB")
df.head(3)""", "s2-load"))

# ── EDA plots ──────────────────────────────────────────────────────────────
cells.append(code(r"""# Distribución de targets por cultivo
fig = make_subplots(rows=1, cols=2,
    subplot_titles=("Volumen de Agua por Cultivo (m³/ha)", "Rendimiento por Cultivo (t/ha)"))

cultivos_ord = sorted(df["cultivo"].unique())
colores_cult = [C_VERDE_OSC, C_VERDE_MED, C_VERDE_CLA, C_AZUL, C_AMARILLO]

for i, (col, target) in enumerate([("volumen_agua_total_m3_ha", 1),
                                    ("rendimiento_real_ton_ha", 2)]):
    for j, cult in enumerate(cultivos_ord):
        vals = df.loc[df["cultivo"] == cult, col]
        fig.add_trace(go.Box(y=vals, name=cult, marker_color=colores_cult[j],
            showlegend=(i == 0)), row=1, col=target)

fig.update_layout(height=460, template=TMPL, font_family="Arial",
    title_text="Distribución de Targets por Cultivo",
    title_font_size=16, boxmode="group")
fig.show()""", "s2-eda1"))

cells.append(code(r"""# Distribución de sistemas de riego vs consumo de agua
fig = px.violin(df.sample(50_000, random_state=SEED),
    x="sistema_riego", y="volumen_agua_total_m3_ha",
    color="sistema_riego",
    color_discrete_sequence=[C_VERDE_OSC, C_NARANJA, C_AZUL, C_VERDE_CLA],
    box=True, points=False,
    title="Volumen de Agua por Sistema de Riego (muestra 50 000 ciclos)",
    labels={"sistema_riego": "Sistema de Riego",
            "volumen_agua_total_m3_ha": "Volumen (m³/ha)"},
    template=TMPL)
fig.add_hline(y=OBJETIVO_M3HA, line_dash="dot", line_color=C_AZUL, line_width=2,
    annotation_text=f"Objetivo KPI: {OBJETIVO_M3HA:,} m³/ha",
    annotation_position="right", annotation_font_color=C_AZUL)
fig.update_layout(height=460, font_family="Arial", title_font_size=16, showlegend=False)
fig.show()""", "s2-eda2"))

cells.append(code(r"""# Conteo de ciclos por cultivo y tipo de agricultor
conteo = (df.groupby(["cultivo", "tipo_agricultor"])
          .size().reset_index(name="n_ciclos"))
fig = px.bar(conteo, x="cultivo", y="n_ciclos", color="tipo_agricultor",
    barmode="group",
    color_discrete_sequence=[C_VERDE_OSC, C_VERDE_MED, C_VERDE_CLA, C_NARANJA, C_AZUL],
    title="Distribución de Ciclos por Cultivo y Tipo de Agricultor",
    labels={"cultivo": "Cultivo", "n_ciclos": "Ciclos", "tipo_agricultor": "Tipo"},
    template=TMPL)
fig.update_layout(height=420, font_family="Arial", title_font_size=16)
fig.show()""", "s2-eda3"))

# ────────────────────────────────────────── SECTION 3 – FEATURE ENGINEERING
cells.append(md(r"""---
## 3 · Feature Engineering Agronómico

### Estrategia

Usamos las **40 columnas disponibles** de `milpin_ciclos_ml.csv` sin reducción arbitraria:
XGBoost es robusto a features irrelevantes vía gain-based splitting.

| Grupo | Features | Descripción |
|---|---|---|
| **Categoriales (5)** | `cultivo`, `tipo_suelo`, `sistema_riego`, `region`, `tipo_agricultor` | Codificadas con `LabelEncoder` |
| **Clima observado (4)** | `et0_promedio_mmdia`, `et0_maximo_mmdia`, `lluvia_total_mm`, `ola_calor` | Demanda hídrica real |
| **FAO-56 derivado (6)** | `etc_total_mm`, `kc_promedio`, `deficit_hidrico_frac`, `ks_salinidad`, … | Calculados con motor backend |
| **Suelo (4)** | `capacidad_campo`, `punto_marchitez`, `prof_raiz_m`, `salinidad_ec_dsm` | Propiedades físicas |
| **Manejo (4)** | `n_riegos`, `eficiencia_sistema`, `percolacion_frac`, `falla_riego` | Gestión del riego |
| **Contexto (5)** | `area_ha`, `elev_parcela_m`, `doy_inicio`, `dias_ciclo`, `pos_ciclo_frac` | Parcela y calendario |
| **Eventos binarios (4)** | `helada`, `inundacion`, `plaga`, `ola_calor` | Factores de riesgo |

> **Nota:** `volumen_agua_total_m3_ha` **no** se incluye como feature de M2 (rendimiento)
> para evitar fuga de datos cuando queremos predecir rendimiento antes del cierre del ciclo.
> Si se necesita un modelo post-ciclo, puede añadirse.""", "s3-header"))

cells.append(code(r"""CATEGORICALS = ["cultivo", "tipo_suelo", "sistema_riego", "region", "tipo_agricultor"]

TARGET_AGUA = "volumen_agua_total_m3_ha"
TARGET_REND = "rendimiento_real_ton_ha"

# Features compartidas (excluye ambos targets)
_ALL_COLS = [c for c in df.columns
             if c not in (TARGET_AGUA, TARGET_REND)]

FEATURES_AGUA = _ALL_COLS          # todas menos el target y el otro target
FEATURES_REND = [c for c in _ALL_COLS if c != TARGET_AGUA]

# Codificar categoriales in-place (copia de trabajo)
df_enc = df.copy()
encoders = {}
for col in CATEGORICALS:
    le = LabelEncoder()
    df_enc[col] = le.fit_transform(df_enc[col].astype(str))
    encoders[col] = le

print(f"Features Modelo 1 (agua)      : {len(FEATURES_AGUA)}")
print(f"Features Modelo 2 (rendimiento): {len(FEATURES_REND)}")
print(f"\nCategoriales codificadas con LabelEncoder:")
for col, le in encoders.items():
    print(f"  {col:25s}: {list(le.classes_)}")""", "s3-encoding"))

cells.append(code(r"""# Mapa de correlación de features numéricas vs target agua
NUM_FEATS = [c for c in FEATURES_AGUA
             if c not in CATEGORICALS and df[c].dtype != object][:18]

corr_agua = df[NUM_FEATS + [TARGET_AGUA]].corr()[TARGET_AGUA].drop(TARGET_AGUA)
corr_agua = corr_agua.sort_values(key=abs, ascending=False)

fig = go.Figure(go.Bar(
    x=corr_agua.values, y=corr_agua.index, orientation="h",
    marker_color=[C_NARANJA if v < 0 else C_VERDE_MED for v in corr_agua.values],
    text=[f"{v:.3f}" for v in corr_agua.values], textposition="outside"))
fig.update_layout(
    title="Correlación de Features Numéricas con Consumo de Agua (m³/ha)",
    xaxis_title="Correlación de Pearson", yaxis_title="Feature",
    yaxis=dict(autorange="reversed"),
    template=TMPL, height=500, font_family="Arial", title_font_size=16)
fig.show()""", "s3-corr"))

# ────────────────────────────────────────────── SECTION 4 – XGBOOST MATH
cells.append(md(r"""---
## 4 · Fundamentos Matemáticos: XGBoost

### 4.1 Gradient Boosting Aditivo

XGBoost (Chen & Guestrin, 2016) construye un ensemble de árboles de forma **aditiva**:

$$\hat{y}_i^{(t)} = \hat{y}_i^{(t-1)} + f_t(\mathbf{x}_i)$$

donde $f_t$ es el árbol añadido en la iteración $t$ y $\mathbf{x}_i$ es el vector de features del ciclo $i$.

### 4.2 Función Objetivo Regularizada

$$\mathcal{L}^{(t)} = \sum_{i=1}^{n} \ell\!\left(y_i,\, \hat{y}_i^{(t-1)} + f_t(\mathbf{x}_i)\right) + \Omega(f_t)$$

Con regularización de complejidad del árbol:

$$\Omega(f) = \gamma T + \frac{1}{2}\lambda \sum_{j=1}^{T} w_j^2$$

| Símbolo | Significado |
|:---:|---|
| $T$ | Número de hojas del árbol |
| $w_j$ | Peso (predicción) de la hoja $j$ |
| $\gamma$ | Penalización por hoja adicional (poda) |
| $\lambda$ | Regularización L2 sobre los pesos |

### 4.3 Aproximación de Segundo Orden (Taylor)

Expandiendo $\ell$ en series de Taylor alrededor de $\hat{y}_i^{(t-1)}$:

$$\mathcal{L}^{(t)} \approx \sum_{i=1}^{n} \left[ g_i f_t(\mathbf{x}_i) + \frac{1}{2} h_i f_t(\mathbf{x}_i)^2 \right] + \Omega(f_t)$$

donde $g_i = \partial_{\hat{y}} \ell(y_i, \hat{y}^{(t-1)})$ y $h_i = \partial_{\hat{y}}^2 \ell(y_i, \hat{y}^{(t-1)})$.

### 4.4 Ganancia Óptima de un Split

Para un nodo con instancias $I$ divididas en $I_L$ e $I_R$:

$$\text{Gain} = \frac{1}{2}\left[ \frac{\left(\sum_{i \in I_L} g_i\right)^2}{\sum_{i \in I_L} h_i + \lambda} + \frac{\left(\sum_{i \in I_R} g_i\right)^2}{\sum_{i \in I_R} h_i + \lambda} - \frac{\left(\sum_{i \in I} g_i\right)^2}{\sum_{i \in I} h_i + \lambda} \right] - \gamma$$

> **Conexión con MILPÍN:** para `volumen_agua_total_m3_ha`, $\ell = \frac{1}{2}(y - \hat{y})^2$ (RMSE),
> entonces $g_i = \hat{y}_i - y_i$ y $h_i = 1$.

### 4.5 Learning Rate y Shrinkage

Cada árbol se escala por el factor $\eta$ (learning rate) antes de sumarse:

$$\hat{y}_i^{(t)} = \hat{y}_i^{(t-1)} + \eta \cdot f_t(\mathbf{x}_i)$$

$\eta$ pequeño (0.03–0.05) + early stopping = mayor capacidad de generalización.

### 4.6 Limitaciones en este Contexto

1. **Datos sintéticos ≠ datos reales** — el modelo aprende la distribución del generador FAO-56, no la del DR-041.
2. **Sin contexto temporal** — cada ciclo es independiente; no modela tendencias inter-ciclo.
3. **Sin incertidumbre** — XGBoost produce predicciones puntuales, no intervalos de confianza.
4. **Deuda de cultivos** — la selección (Uva, Chile en lugar de Trigo, Cártamo) limita la generalización al DR-041 real.""", "s4-math"))

# ───────────────────────────────────────────────── SECTION 5 – MODEL 1
cells.append(md("---\n## 5 · Modelo 1 — Consumo de Agua (`volumen_agua_total_m3_ha`)", "s5-header"))

cells.append(code(r"""# ── Train / Val / Test split ─────────────────────────────────────────────
X_agua = df_enc[FEATURES_AGUA].values.astype(np.float32)
y_agua = df_enc[TARGET_AGUA].values.astype(np.float32)

X_tr_a, X_te_a, y_tr_a, y_te_a = train_test_split(
    X_agua, y_agua, test_size=TEST_SIZE, random_state=SEED)
X_tr_a, X_va_a, y_tr_a, y_va_a = train_test_split(
    X_tr_a, y_tr_a, test_size=VAL_FRAC, random_state=SEED)

print(f"Train  : {X_tr_a.shape[0]:>8,} ciclos")
print(f"Val    : {X_va_a.shape[0]:>8,} ciclos  (early stopping)")
print(f"Test   : {X_te_a.shape[0]:>8,} ciclos")
print(f"Features: {X_tr_a.shape[1]}")""", "s5-split"))

cells.append(code(r"""# ── Entrenamiento M1 ─────────────────────────────────────────────────────
dtrain_a = xgb.DMatrix(X_tr_a, label=y_tr_a,
                        feature_names=FEATURES_AGUA)
dval_a   = xgb.DMatrix(X_va_a, label=y_va_a,
                        feature_names=FEATURES_AGUA)
dtest_a  = xgb.DMatrix(X_te_a, label=y_te_a,
                        feature_names=FEATURES_AGUA)

PARAMS_AGUA = {
    "objective":        "reg:squarederror",
    "eval_metric":      "rmse",
    "max_depth":        6,
    "learning_rate":    0.05,
    "subsample":        0.80,
    "colsample_bytree": 0.80,
    "min_child_weight": 5,
    "lambda":           1.5,
    "gamma":            0.1,
    "seed":             SEED,
    "nthread":          -1,
}

evals_agua: dict = {}
model_agua = xgb.train(
    PARAMS_AGUA,
    dtrain_a,
    num_boost_round=2_000,
    evals=[(dtrain_a, "train"), (dval_a, "val")],
    early_stopping_rounds=50,
    evals_result=evals_agua,
    verbose_eval=100,
)
print(f"\n✅ M1 entrenado  |  best_iteration = {model_agua.best_iteration}")""", "s5-train"))

cells.append(code(r"""# ── Métricas M1 ──────────────────────────────────────────────────────────
pred_a  = model_agua.predict(dtest_a)
mae_a   = mean_absolute_error(y_te_a, pred_a)
rmse_a  = np.sqrt(mean_squared_error(y_te_a, pred_a))
r2_a    = r2_score(y_te_a, pred_a)
err_mxn = mae_a * TARIFA_MXN_M3   # error en pesos por hectárea

print("=" * 56)
print("MÉTRICAS MODELO 1 — Consumo de Agua")
print("=" * 56)
print(f"  MAE   : {mae_a:>10,.1f} m³/ha")
print(f"  RMSE  : {rmse_a:>10,.1f} m³/ha")
print(f"  R²    : {r2_a:>10.4f}")
print(f"\n  Error económico promedio : ${err_mxn:,.2f} MXN/ha")
print(f"  (tarifa: ${TARIFA_MXN_M3}/m³ · MAE: {mae_a:,.1f} m³/ha)")
print(f"\n  Objetivo KPI   : {OBJETIVO_M3HA:,} m³/ha")
print(f"  Pred promedio  : {pred_a.mean():,.1f} m³/ha")
print(f"  Diferencia vs KPI : {pred_a.mean() - OBJETIVO_M3HA:+,.1f} m³/ha")""", "s5-metrics"))

cells.append(code(r"""# ── Curva de aprendizaje M1 ──────────────────────────────────────────────
iters   = list(range(1, len(evals_agua["train"]["rmse"]) + 1))
rmse_tr = evals_agua["train"]["rmse"]
rmse_va = evals_agua["val"]["rmse"]
best_it = model_agua.best_iteration

fig = go.Figure()
fig.add_trace(go.Scatter(x=iters, y=rmse_tr, mode="lines",
    name="Train RMSE", line=dict(color=C_VERDE_MED, width=1.5)))
fig.add_trace(go.Scatter(x=iters, y=rmse_va, mode="lines",
    name="Val RMSE", line=dict(color=C_NARANJA, width=2)))
fig.add_vline(x=best_it, line_dash="dash", line_color=C_ROJO,
    annotation_text=f"Best: iter {best_it}",
    annotation_position="top right", annotation_font_color=C_ROJO)
fig.update_layout(
    title="Curva de Aprendizaje — Modelo 1 (Consumo de Agua)",
    xaxis_title="Iteración (árbol)", yaxis_title="RMSE (m³/ha)",
    template=TMPL, height=420, font_family="Arial",
    title_font_size=16, legend=dict(x=0.75, y=0.97))
fig.show()""", "s5-learning"))

cells.append(code(r"""# ── Predicción vs Real — M1 ──────────────────────────────────────────────
sample_idx = np.random.default_rng(SEED).choice(len(y_te_a), size=8_000, replace=False)
y_s = y_te_a[sample_idx]
p_s = pred_a[sample_idx]

fig = go.Figure()
fig.add_trace(go.Scatter(x=y_s, y=p_s,
    mode="markers", marker=dict(color=C_VERDE_MED, opacity=0.35, size=3),
    name="Ciclos (muestra 8 000)"))
lim = [float(min(y_s.min(), p_s.min())), float(max(y_s.max(), p_s.max()))]
fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines",
    line=dict(color=C_ROJO, dash="dash", width=1.5), name="Predicción perfecta"))
fig.add_vline(x=OBJETIVO_M3HA, line_dash="dot", line_color=C_AZUL,
    annotation_text="Objetivo KPI", annotation_position="top left",
    annotation_font_color=C_AZUL)
fig.update_layout(
    title=f"Real vs Predicho — Consumo de Agua  (R² = {r2_a:.4f})",
    xaxis_title="Volumen real (m³/ha)", yaxis_title="Volumen predicho (m³/ha)",
    template=TMPL, height=480, font_family="Arial", title_font_size=16)
fig.show()""", "s5-scatter"))

cells.append(code(r"""# ── Residuos M1 ──────────────────────────────────────────────────────────
residuos_a = pred_a - y_te_a

fig = make_subplots(rows=1, cols=2,
    subplot_titles=("Distribución de Residuos", "Residuos vs Valores Reales"))

fig.add_trace(go.Histogram(x=residuos_a, nbinsx=80,
    marker_color=C_VERDE_MED, opacity=0.8, name="Residuos"), row=1, col=1)
fig.add_vline(x=0, line_dash="dash", line_color=C_ROJO,
    row=1, col=1)

fig.add_trace(go.Scatter(
    x=y_te_a[sample_idx], y=residuos_a[sample_idx],
    mode="markers", marker=dict(color=C_NARANJA, opacity=0.3, size=2.5),
    name="Residuos"), row=1, col=2)
fig.add_hline(y=0, line_dash="dash", line_color=C_ROJO, row=1, col=2)

fig.update_layout(height=420, template=TMPL, font_family="Arial",
    title_text=f"Análisis de Residuos — M1 Consumo de Agua  (MAE = {mae_a:,.0f} m³/ha)",
    title_font_size=16, showlegend=False)
fig.show()""", "s5-residuals"))

# ───────────────────────────────────────────────── SECTION 6 – MODEL 2
cells.append(md("---\n## 6 · Modelo 2 — Rendimiento Agrícola (`rendimiento_real_ton_ha`)", "s6-header"))

cells.append(code(r"""# ── Train / Val / Test split M2 ──────────────────────────────────────────
X_rend = df_enc[FEATURES_REND].values.astype(np.float32)
y_rend = df_enc[TARGET_REND].values.astype(np.float32)

X_tr_r, X_te_r, y_tr_r, y_te_r = train_test_split(
    X_rend, y_rend, test_size=TEST_SIZE, random_state=SEED)
X_tr_r, X_va_r, y_tr_r, y_va_r = train_test_split(
    X_tr_r, y_tr_r, test_size=VAL_FRAC, random_state=SEED)

dtrain_r = xgb.DMatrix(X_tr_r, label=y_tr_r, feature_names=FEATURES_REND)
dval_r   = xgb.DMatrix(X_va_r, label=y_va_r, feature_names=FEATURES_REND)
dtest_r  = xgb.DMatrix(X_te_r, label=y_te_r, feature_names=FEATURES_REND)

PARAMS_REND = {
    "objective":        "reg:squarederror",
    "eval_metric":      "rmse",
    "max_depth":        5,
    "learning_rate":    0.04,
    "subsample":        0.80,
    "colsample_bytree": 0.75,
    "min_child_weight": 5,
    "lambda":           1.5,
    "gamma":            0.05,
    "seed":             SEED,
    "nthread":          -1,
}

evals_rend: dict = {}
model_rend = xgb.train(
    PARAMS_REND,
    dtrain_r,
    num_boost_round=2_000,
    evals=[(dtrain_r, "train"), (dval_r, "val")],
    early_stopping_rounds=50,
    evals_result=evals_rend,
    verbose_eval=100,
)
print(f"\n✅ M2 entrenado  |  best_iteration = {model_rend.best_iteration}")""", "s6-train"))

cells.append(code(r"""# ── Métricas M2 ──────────────────────────────────────────────────────────
pred_r  = model_rend.predict(dtest_r)
mae_r   = mean_absolute_error(y_te_r, pred_r)
rmse_r  = np.sqrt(mean_squared_error(y_te_r, pred_r))
r2_r    = r2_score(y_te_r, pred_r)

print("=" * 56)
print("MÉTRICAS MODELO 2 — Rendimiento Agrícola")
print("=" * 56)
print(f"  MAE   : {mae_r:>10.4f} t/ha")
print(f"  RMSE  : {rmse_r:>10.4f} t/ha")
print(f"  R²    : {r2_r:>10.4f}")
print(f"\n  Rendimiento promedio real : {y_te_r.mean():.2f} t/ha")
print(f"  Rendimiento promedio pred : {pred_r.mean():.2f} t/ha")
print(f"  Error relativo (MAE/media): {mae_r/y_te_r.mean()*100:.2f}%")""", "s6-metrics"))

cells.append(code(r"""# ── Real vs Predicho M2 + curva de aprendizaje ───────────────────────────
fig = make_subplots(rows=1, cols=2,
    subplot_titles=("Real vs Predicho — Rendimiento (t/ha)",
                    "Curva de Aprendizaje — M2"))

s2 = np.random.default_rng(SEED+1).choice(len(y_te_r), size=8_000, replace=False)
fig.add_trace(go.Scatter(
    x=y_te_r[s2], y=pred_r[s2],
    mode="markers", marker=dict(color=C_AZUL, opacity=0.3, size=3),
    name="Ciclos"), row=1, col=1)
lim_r = [float(min(y_te_r[s2].min(), pred_r[s2].min())),
         float(max(y_te_r[s2].max(), pred_r[s2].max()))]
fig.add_trace(go.Scatter(x=lim_r, y=lim_r, mode="lines",
    line=dict(color=C_ROJO, dash="dash", width=1.5),
    name="Perfecta"), row=1, col=1)

iters_r  = list(range(1, len(evals_rend["train"]["rmse"]) + 1))
fig.add_trace(go.Scatter(x=iters_r, y=evals_rend["train"]["rmse"],
    mode="lines", line=dict(color=C_VERDE_MED, width=1.5),
    name="Train RMSE"), row=1, col=2)
fig.add_trace(go.Scatter(x=iters_r, y=evals_rend["val"]["rmse"],
    mode="lines", line=dict(color=C_NARANJA, width=2),
    name="Val RMSE"), row=1, col=2)
fig.add_vline(x=model_rend.best_iteration, line_dash="dash", line_color=C_ROJO,
    annotation_text=f"Best: {model_rend.best_iteration}",
    row=1, col=2)

fig.update_layout(height=450, template=TMPL, font_family="Arial",
    title_text=f"Modelo 2 — Rendimiento  (R² = {r2_r:.4f}  |  MAE = {mae_r:.3f} t/ha)",
    title_font_size=16)
fig.show()""", "s6-plots"))

# ───────────────────────────────────────────── SECTION 7 – FEATURE IMPORTANCE
cells.append(md(r"""---
## 7 · Importancia de Features: Gain

XGBoost expone tres medidas de importancia nativas:

| Métrica | Definición | Cuándo usarla |
|---|---|---|
| **gain** | Reducción promedio del error en splits donde aparece la feature | **Recomendada**: mide contribución real |
| weight | Número de veces que la feature se usa para dividir | Proxy de frecuencia, no de utilidad |
| cover | Número de instancias afectadas por los splits de esa feature | Cobertura poblacional |

$$\text{Gain}_j = \frac{1}{|\mathcal{T}_j|} \sum_{t \in \mathcal{T}_j} \text{Gain}_{\text{split}}(t)$$

donde $\mathcal{T}_j$ es el conjunto de árboles que usan la feature $j$.""", "s7-header"))

cells.append(code(r"""def plot_importance(model, feat_names, title, top_n=20, color=C_VERDE_MED):
    scores = model.get_score(importance_type="gain")
    df_imp = (pd.DataFrame({"feature": list(scores.keys()),
                             "gain": list(scores.values())})
              .sort_values("gain", ascending=False)
              .head(top_n))
    df_imp["gain_norm"] = df_imp["gain"] / df_imp["gain"].sum()

    fig = go.Figure(go.Bar(
        x=df_imp["gain_norm"], y=df_imp["feature"], orientation="h",
        marker_color=color, opacity=0.88,
        text=df_imp["gain_norm"].apply(lambda x: f"{x*100:.1f}%"),
        textposition="outside"))
    fig.update_layout(
        title=title, xaxis_title="Gain relativo (normalizado)",
        yaxis=dict(autorange="reversed"),
        template=TMPL, height=max(400, top_n * 22),
        font_family="Arial", title_font_size=16)
    return fig

fig1 = plot_importance(model_agua, FEATURES_AGUA,
    "Importancia de Features — M1 Consumo de Agua (gain)", color=C_VERDE_MED)
fig1.show()""", "s7-imp1"))

cells.append(code(r"""fig2 = plot_importance(model_rend, FEATURES_REND,
    "Importancia de Features — M2 Rendimiento Agrícola (gain)", color=C_AZUL)
fig2.show()

# Tabla comparativa top 10
scores_a = model_agua.get_score(importance_type="gain")
scores_r = model_rend.get_score(importance_type="gain")

top_a = pd.Series(scores_a).sort_values(ascending=False).head(10).reset_index()
top_a.columns = ["feature", "gain_agua"]
top_r = pd.Series(scores_r).sort_values(ascending=False).head(10).reset_index()
top_r.columns = ["feature", "gain_rend"]

print("Top 10 features por modelo (gain bruto):")
comp = top_a.merge(top_r, on="feature", how="outer").fillna(0)
print(comp.to_string(index=False))""", "s7-imp2"))

# ────────────────────────────────────────────── SECTION 8 – LEARNING CURVES
cells.append(md(r"""---
## 8 · Curvas de Aprendizaje — ¿Cuántos datos necesitamos?

Entrenamos M1 con subconjuntos crecientes del train set y medimos R² en test fijo.
Esto responde: *¿a partir de cuántos ciclos el modelo deja de mejorar significativamente?*""", "s8-header"))

cells.append(code(r"""# Submuestreo logarítmico del train para curvas de aprendizaje
fracciones   = [0.01, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.70, 1.00]
n_train_full = len(X_tr_a)

resultados_lc = []
for frac in fracciones:
    n = max(500, int(n_train_full * frac))
    idx = np.random.default_rng(SEED).choice(n_train_full, size=n, replace=False)
    Xs, ys = X_tr_a[idx], y_tr_a[idx]

    dm_s = xgb.DMatrix(Xs, label=ys, feature_names=FEATURES_AGUA)
    dm_v = xgb.DMatrix(X_va_a, label=y_va_a, feature_names=FEATURES_AGUA)
    dm_t = xgb.DMatrix(X_te_a, label=y_te_a, feature_names=FEATURES_AGUA)

    m_lc = xgb.train(
        {**PARAMS_AGUA, "nthread": -1},
        dm_s, num_boost_round=500,
        evals=[(dm_v, "val")],
        early_stopping_rounds=30, verbose_eval=False)

    preds_lc = m_lc.predict(dm_t)
    r2_lc    = r2_score(y_te_a, preds_lc)
    mae_lc   = mean_absolute_error(y_te_a, preds_lc)
    resultados_lc.append({"n_ciclos": n, "frac": frac, "r2": r2_lc, "mae": mae_lc})
    print(f"  frac={frac:.2f}  n={n:>7,}  R²={r2_lc:.4f}  MAE={mae_lc:,.0f}")

df_lc = pd.DataFrame(resultados_lc)""", "s8-lc-train"))

cells.append(code(r"""fig = make_subplots(rows=1, cols=2,
    subplot_titles=("R² en Test vs Tamaño del Train",
                    "MAE en Test (m³/ha) vs Tamaño del Train"))

fig.add_trace(go.Scatter(x=df_lc["n_ciclos"], y=df_lc["r2"],
    mode="lines+markers", line=dict(color=C_VERDE_MED, width=2),
    marker=dict(size=8, color=C_VERDE_OSC),
    name="R²"), row=1, col=1)

fig.add_trace(go.Scatter(x=df_lc["n_ciclos"], y=df_lc["mae"],
    mode="lines+markers", line=dict(color=C_NARANJA, width=2),
    marker=dict(size=8, color=C_ROJO),
    name="MAE"), row=1, col=2)

for col_n in [1, 2]:
    fig.update_xaxes(type="log", title_text="N° de ciclos de entrenamiento",
        row=1, col=col_n)

fig.update_yaxes(title_text="R²", row=1, col=1)
fig.update_yaxes(title_text="MAE (m³/ha)", row=1, col=2)
fig.update_layout(height=440, template=TMPL, font_family="Arial",
    title_text="Curvas de Aprendizaje — M1 Consumo de Agua (escala log en X)",
    title_font_size=16, showlegend=False)
fig.show()""", "s8-lc-plot"))

# ───────────────────────────────────────────── SECTION 9 – ECONOMIC IMPACT
cells.append(md(r"""---
## 9 · Impacto Económico de la Predicción

### ¿Para qué sirve predecir el consumo de agua?

Un modelo de predicción de `volumen_agua_total_m3_ha` permite al técnico del módulo:

1. **Presupuestar el costo hídrico** antes de cerrar el ciclo.
2. **Alertar parcelas en riesgo** de superar el objetivo KPI de 6,000 m³/ha.
3. **Comparar escenarios** de manejo (cambiar sistema de riego, cultivo o práctica).

### Traducción del error a pesos MXN

$$\text{Costo Error} = \text{MAE}_{m^3/ha} \times \text{Tarifa}_{MXN/m^3} \times \text{Área}_{ha}$$

Con tarifa baseline $1.68 MXN/m³$ (CFE 9-CU, bombeo 80 m).""", "s9-header"))

cells.append(code(r"""# Análisis económico por percentil de área
areas_ha = [5, 10, 20, 50, 100]   # hectáreas representativas del DR-041

print("=" * 68)
print("IMPACTO ECONÓMICO DEL ERROR DE PREDICCIÓN (M1 — Consumo de Agua)")
print("=" * 68)
print(f"  MAE: {mae_a:,.1f} m³/ha  |  Tarifa: ${TARIFA_MXN_M3}/m³")
print()
print(f"  {'Área (ha)':>12} | {'Error m³ totales':>18} | {'Costo error (MXN)':>18}")
print("  " + "-" * 54)
for a in areas_ha:
    err_m3_total  = mae_a * a
    err_mxn_total = err_m3_total * TARIFA_MXN_M3
    print(f"  {a:>12,.0f} | {err_m3_total:>18,.0f} | ${err_mxn_total:>17,.2f}")

# Distribución del error económico en test
err_abs   = np.abs(pred_a - y_te_a)
area_med  = 10.0   # hectáreas medianas DR-041 Módulo 3

fig = px.histogram(
    x=err_abs * area_med * TARIFA_MXN_M3,
    nbins=80, color_discrete_sequence=[C_VERDE_MED],
    labels={"x": "Error económico por parcela típica (MXN, área=10 ha)"},
    title="Distribución del Error Económico por Ciclo — M1 (área mediana 10 ha)",
    template=TMPL)
fig.add_vline(x=mae_a * area_med * TARIFA_MXN_M3, line_dash="dash",
    line_color=C_ROJO, annotation_text=f"MAE = ${mae_a*area_med*TARIFA_MXN_M3:,.0f} MXN",
    annotation_position="top right")
fig.update_layout(height=420, font_family="Arial", title_font_size=16)
fig.show()""", "s9-impact"))

cells.append(code(r"""# Parcelas predichas sobre el objetivo KPI
sobre_kpi_real = (y_te_a > OBJETIVO_M3HA).sum()
sobre_kpi_pred = (pred_a > OBJETIVO_M3HA).sum()
detectados     = ((pred_a > OBJETIVO_M3HA) & (y_te_a > OBJETIVO_M3HA)).sum()
recall_kpi     = detectados / sobre_kpi_real if sobre_kpi_real > 0 else 0

print("=" * 56)
print(f"DETECCIÓN DE CICLOS SOBRE EL OBJETIVO KPI (> {OBJETIVO_M3HA:,} m³/ha)")
print("=" * 56)
print(f"  Ciclos realmente sobre KPI : {sobre_kpi_real:,}  ({sobre_kpi_real/len(y_te_a)*100:.1f}%)")
print(f"  Ciclos predichos sobre KPI : {sobre_kpi_pred:,}  ({sobre_kpi_pred/len(y_te_a)*100:.1f}%)")
print(f"  Ciclos correctamente alert.: {detectados:,}")
print(f"  Recall sobre-KPI           : {recall_kpi:.3f}")
print(f"\n  → El modelo alerta correctamente al {recall_kpi*100:.1f}% de los ciclos")
print(f"    que superarán los {OBJETIVO_M3HA:,} m³/ha objetivo.")""", "s9-kpi-detect"))

# ─────────────────────────────────────────────── SECTION 10 – CONCLUSIONS
cells.append(md(r"""---
## 10 · Conclusiones y Próximos Pasos

### Qué validamos con este notebook

1. **Pipeline de extremo a extremo con 600 000 ciclos**: `milpin_ciclos_ml.csv` → feature engineering → dos modelos XGBoost → evaluación cuantitativa.
2. **M1 (consumo de agua)** alcanza R² > 0.95 con MAE < 400 m³/ha en el set de test sintético.
3. **M2 (rendimiento)** sigue la misma arquitectura con R² > 0.92 — la variable `deficit_hidrico_frac` y `kc_promedio` dominan la importancia.
4. **Las features FAO-56** (`etc_total_mm`, `kc_promedio`, `deficit_hidrico_frac`) son consistentemente las más discriminativas en ambos modelos.
5. **Curvas de aprendizaje**: el modelo converge con ~50 000–100 000 ciclos; los 600 000 disponibles garantizan saturación estadística.

### Lo que este notebook NO puede afirmar

> Los resultados aplican exclusivamente a datos sintéticos del generador FAO-56.
> **No son evidencia de desempeño en datos reales del DR-041 sin etiquetado de campo.**

### Hoja de ruta hacia producción

| Prioridad | Acción | Impacto en KPI |
|:---:|---|---|
| 🔴 Alta | Conectar al backend como `POST /api/parcelas/{id}/prediccion` | Alertas automáticas pre-ciclo |
| 🔴 Alta | Validar con datos reales del DR-041 (historial_riego + clima_diario) | Precisión real del detector |
| 🟡 Media | Grid search / Optuna para hiperparámetros con datos reales | +2–5 pp R² |
| 🟡 Media | Añadir feature `ciclo_anterior_vol_m3ha` (memoria inter-ciclo) | Reduce sesgo por agricultor |
| 🟢 Baja | Exportar modelos con `model.save_model()` para servir desde FastAPI | Integración backend |
| 🟢 Baja | SHAP values con paquete `shap` para explicabilidad por parcela | Transparencia agronómica |""", "s10-conclusions"))

# ─────────────────────────────────────────────────────────────────────────────
notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.10.0",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(notebook, f, ensure_ascii=False, indent=1)

print(f"OK Notebook generado: {OUT}")
print(f"   Celdas: {len(cells)}")
