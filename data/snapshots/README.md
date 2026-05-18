# data/snapshots/

Snapshots del Feature Store offline (formato Parquet), versionados con DVC.

Cada snapshot corresponde a un cohort de entrenamiento y tiene asociado un
`dvc-hash` registrado en el MLflow run correspondiente.

No commitar estos archivos a git directamente — usar `dvc push`.
