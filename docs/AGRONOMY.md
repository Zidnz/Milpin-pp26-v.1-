# Motor Agronómico FAO-56

## Referencia
Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998).
*Crop evapotranspiration — Guidelines for computing crop water requirements.*
FAO Irrigation and Drainage Paper 56.

## Implementación
`backend/core/balance_hidrico.py` implementa Penman-Monteith completo.
Hargreaves como fallback cuando faltan datos de radiación solar o humedad.

## Cultivos soportados
Maíz, Frijol, Algodón, Uva, Chile.
Coeficientes Kc en `balance_hidrico.py::KC_TABLE`.

## Balance hídrico
`propagar_balance_hidrico()` calcula humedad inicial desde el último riego
real registrado en `historial_riego`, eliminando la inicialización
con `(CC+PMP)/2` que era el valor inventado anterior.

## KPI objetivo
8,000 m³/ha/ciclo → 6,000 m³/ha/ciclo (−25%).
Tarifa baseline: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m).
