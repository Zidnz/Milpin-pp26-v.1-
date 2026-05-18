# Arquitectura MILPÍN

## Visión general

```
Frontend (Leaflet + vanilla JS)
        │  HTTP REST
        ▼
Backend FastAPI (Python 3.10+)
  ├── API/          # Routers HTTP
  ├── core/         # Motor agronómico FAO-56
  └── ml → imports → ml/inference/   # Wrappers ML
        │
        ▼
PostgreSQL 15 + PostGIS 3.6
  ├── parcelas (geom GEOMETRY(Polygon,4326), índice GIST)
  ├── clima_diario
  ├── recomendaciones
  └── historial_riego
```

## Separación backend / ml

`backend/` contiene solo código HTTP y motor agronómico.
`ml/` contiene entrenamiento, inferencia, feature store y pipelines.

El backend importa de `ml.inference` (read-only).
El entrenamiento (`ml/training/`) **nunca** importa de `backend/`.

## GIS

- Geometrías: `GEOMETRY(Polygon, 4326)` en PostGIS.
- Leaflet carga GeoJSON desde `GET /api/parcelas/geojson`.
- Fallback estático: `frontend/data/lotes.geojson`.

## Voz

```
Audio → Whisper (STT) → Ollama llama3.2 (NLU/intent) → acción API → Web Speech API (TTS)
```

Ver `backend/API/voice_endpoint.py` y `backend/core/llm_orchestrator.py`.
