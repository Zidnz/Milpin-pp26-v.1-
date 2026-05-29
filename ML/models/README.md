# ml/models/

Este directorio **no almacena binarios de modelos** (sin `.joblib`, sin `.pkl`).

Los modelos entrenados viven en el **MLflow Model Registry** (ver `infra/docker-compose.yml`
para levantar el servidor MLflow local).

Los archivos `.joblib` del legacy (`backend/models_ml/`) se mantienen temporalmente
para no romper `backend/core/xgboost_riego.py` y `backend/core/anomaly_detector.py`
mientras se completa la migración a `ml/inference/` (ver sección 18.3 de la auditoría).

## Cómo registrar un modelo nuevo

```bash
# Desde ml/training/xgboost_riego/train.py — ejemplo
import mlflow
mlflow.sklearn.log_model(model, "xgb_riego", registered_model_name="xgb_riego_v1")
```
