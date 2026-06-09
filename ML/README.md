# ML — MILPÍN AgTech

Carpeta centralizada para todo lo relacionado con Machine Learning y análisis
exploratorio del proyecto. Separada del backend de producción por diseño:
el código de `backend/core/` es el que la API consume en runtime; lo que
vive aquí es experimentación, entrenamiento y diagnóstico.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `milpin_xgboost_prediccion.ipynb` | Notebook principal. Dos modelos XGBoost: M1 predice consumo de agua (m³/ha), M2 predice rendimiento (ton/ha). Incluye SHAP para interpretabilidad. |
| `eda_milpin.ipynb` | Análisis exploratorio sobre exportaciones de la BD (usuarios, parcelas, recomendaciones, historial, costos). Lee desde `../data/synthetic/`. |
| `milpin_ciclos_ml.csv` | Dataset de entrenamiento. 800 ciclos sintéticos — 160 por cultivo (Maíz, Frijol, Algodón, Uva, Chile). Generado con FAO-56 del motor agronómico. |
| `generar_ciclos_ml.py` | Script que genera `milpin_ciclos_ml.csv`. Usa `backend/core/balance_hidrico.py` internamente. Correr desde aquí si se necesita regenerar el dataset. |
| `anomaly_detector.py` | Detector de anomalías sobre ciclos agrícolas (Isolation Forest + reglas heurísticas). Standalone, no tiene dependencias de la API. |

---

## Cómo correr los notebooks

### milpin_xgboost_prediccion.ipynb

El path del CSV es relativo: `pd.read_csv("milpin_ciclos_ml.csv")`.
Abrir el notebook **desde esta misma carpeta** (`ML/`) o ajustar el kernel
al directorio correcto.

```bash
cd ML/
jupyter notebook milpin_xgboost_prediccion.ipynb
```

Dependencias: `xgboost`, `shap`, `scikit-learn`, `matplotlib`, `seaborn`.
Están en `requirements.txt` en la raíz del proyecto.

### eda_milpin.ipynb

Lee desde `DATA_DIR = Path('..') / 'data' / 'synthetic'`. Ese path resuelve
a `data/synthetic/` en la raíz del repo, igual que antes (cuando el notebook
vivía en `backend/`). No hay que cambiar nada.

```bash
cd ML/
jupyter notebook eda_milpin.ipynb
```

---

## Relación con el backend de producción

`generar_ciclos_ml.py` importa directamente `balance_hidrico.py`:

```python
# dentro de generar_ciclos_ml.py
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from core.balance_hidrico import calcular_balance_hidrico_diario
```

Si se mueve este script, ajustar ese `sys.path`.

El modelo entrenado en `milpin_xgboost_prediccion.ipynb` **no está conectado
aún a la API**. El único ML en producción hoy es:
- `backend/core/eto_forecast.py` — Ridge Regression para proyección de ETo 7 días
- `backend/core/balance_hidrico.py` — K-Means de parcelas + motor FAO-56

Integrar XGBoost a la API es deuda técnica pendiente (Fase B del roadmap).

---

## Nota sobre el CSV duplicado

`tools/milpin_ciclos_ml.csv` es un duplicado idéntico (mismo md5) al CSV aquí.
Puede eliminarse sin consecuencias.
