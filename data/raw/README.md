# data/raw/

Cache de datos de origen externo. **No editar manualmente.**

- `nasa_power/` — respuestas JSON de la API NASA POWER (por parcela/fecha)
- `shapefiles/` — shapefiles originales DR-041 Módulo 3

Estos archivos se regeneran con:
    python tools/nasa_power_etl.py
