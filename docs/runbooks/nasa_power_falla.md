# Runbook: NASA POWER API falla

## Síntoma
`tools/nasa_power_etl.py` devuelve errores HTTP 5xx o timeout.

## Diagnóstico
```bash
curl "https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M,RH2M&community=AG&longitude=-110.0&latitude=27.5&start=20240101&end=20240101&format=JSON"
```

## Mitigación
1. Si el fallo es temporal (< 24h): el sistema usa la última ETo calculada.
2. Si fallo > 24h: activar fallback Hargreaves en `balance_hidrico.py` (requiere solo T_max, T_min, lat).
3. Recuperar datos perdidos: `python tools/recuperar_cache_nasa.py --desde YYYY-MM-DD`.

## Escalado
Si la API está caída > 3 días, revisar estado en https://power.larc.nasa.gov/
