"""
ml/ — Capa de Machine Learning de MILPÍN AgTech.

Estructura:
    ml/training/   — entrenamiento (nunca importa backend/)
    ml/inference/  — wrappers de inferencia read-only (importados por backend/)
    ml/monitoring/ — drift detection (PSI, KS)
    ml/feature_store/ — definiciones YAML de features
    ml/pipelines/  — Prefect flows (stubs, Fase C/D)
    ml/configs/    — hiperparámetros declarativos YAML
"""
