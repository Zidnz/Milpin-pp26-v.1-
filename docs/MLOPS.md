# MLOps MILPÍN

## Stack (target)
- Entrenamiento: `ml/training/<modelo>/train.py`
- Registry: MLflow (ver `infra/docker-compose.yml`)
- Orquestación: Prefect (`ml/pipelines/`)
- Feature Store: `ml/feature_store/` + definiciones YAML en `views/`
- Monitoreo: PSI + KS (`ml/monitoring/drift.py`)
- Versionado de datos: DVC (`data/snapshots/`)

## Flujo de vida de un modelo
1. Experimento en `ml/experiments/*.ipynb`
2. Código maduro → `ml/training/<modelo>/train.py`
3. Promote gate → `ml/training/<modelo>/promote.py`
4. Registro en MLflow → `ml/models/` (solo apuntador, sin joblib)
5. Inferencia en producción → `ml/inference/<modelo>.py`
6. Monitoreo continuo → `ml/monitoring/drift.py` vía Prefect

## Estado actual (2026-05-16)
- Los modelos `.joblib` siguen en `backend/models_ml/` (legacy).
- `ml/inference/` tiene los wrappers; `backend/core/` tiene re-exports temporales.
- Fase B completa la migración: elimina re-exports y joblibs de `backend/`.
