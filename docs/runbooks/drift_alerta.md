# Runbook: Alerta de drift en modelos ML

## Síntoma
`ml/monitoring/drift.py` reporta PSI > 0.2 o KS p-value < 0.05 en producción.

## Diagnóstico
1. Identificar la feature con mayor PSI.
2. Revisar si hubo cambio en datos de entrada (nueva fuente, bug en ETL).
3. Comparar distribuciones referencia vs. producción.

## Acción
- PSI 0.1-0.2: monitorear, no reentrenar aún.
- PSI > 0.2: activar pipeline `ml/pipelines/train_eval_promote.py`.
- Si el promote gate falla: mantener modelo actual, investigar causa raíz.
