# MILPÍN AgTech

ERP agrícola inteligente con GIS, ML y voz para optimizar el uso del agua
de riego en el Valle del Yaqui, Sonora (DR-041, foco en Módulo 3).

**KPI central:** reducir consumo de 8,000 m³/ha/ciclo → 6,000 m³/ha/ciclo
(ahorro objetivo 25%). Tarifa baseline: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m).

Es herramienta de apoyo a decisiones para agricultores, no sustituto del
juicio agronómico.

---

## Estado actual (2026-04-30)

Pre-MVP con core técnico sólido. Los bloqueadores de geometría y migraciones
quedaron resueltos esta semana; lo que falta es autenticación, tests y
persistencia end-to-end del loop recomendación→feedback.

**Ya funciona:**

- Backend FastAPI 2.0 con lifespan, 4 routers, SQLAlchemy 2.0 async.
- PostgreSQL 15 + **PostGIS 3.6**. `parcelas.geom` es `GEOMETRY(Polygon,4326)`
  migrado desde JSONB vía Alembic `0001_postgis_geom_jsonb_to_geometry`.
  Índice GIST activo.
- 7 modelos ORM, 14 endpoints CRUD, 2 vistas KPI, seeders.
- `GET /api/parcelas/geojson` — GeoJSON FeatureCollection listo para Leaflet.
- Motor agronómico FAO-56 Penman-Monteith en `backend/core/balance_hidrico.py`
  (Allen et al. 1998), con Hargreaves como fallback cuando faltan datos de
  radiación o humedad.
- Pipeline de voz: Whisper STT (carga lazy, startup ~2 s) →
  Ollama `llama3.2:latest` (NLU/intent) → Web Speech API (TTS).
- Clustering K-Means de parcelas (scikit-learn 1.5).
- Frontend vanilla JS + Leaflet 1.9.4, capas Esri World Imagery + OpenTopoMap.
  `map_engine.js` carga parcelas desde la API PostGIS (fallback: `lotes.geojson`).
- Pipeline GIS con geopandas + shapely `make_valid` + Douglas-Peucker.
- Alembic activo: `backend/migrations/` + `alembic.ini`. Próximas migraciones
  con `alembic revision -m "descripcion"` + `alembic upgrade head`.

**Falta para MVP:**

- Autenticación — `id_usuario` entra como UUID en body; cualquiera puede
  crear parcelas a nombre de cualquiera.
- Tests automatizados de backend.
- Loop recomendación→feedback end-to-end con datos reales (las tablas existen,
  los endpoints están, no se ha probado con flujo completo).

---

## Deuda técnica vigente

1. **Credenciales expuestas.** `backend/.env` contiene la password de postgres
   en texto plano y aparentemente no está en `.gitignore`. Rotar y agregar al
   `.gitignore`.
2. **Path traversal en voz.** `voice_endpoint.py` usa
   `temp_path = f"temp_{audio_file.filename}"` sin sanitizar. Sin límite de
   tamaño ni validación de content-type.
3. **CORS abierto.** `allow_origins=["*"]` — reemplazar por allowlist.
4. **Sin autenticación.** Ver arriba.
5. **Recomendador BI falso.** `frontend/src/ui_tabs.js` hace cosine similarity
   sobre una matriz 4×3×3 hardcoded. Es demo, no ML real.
6. **`schema.sql` desalineado.** El DDL todavía documenta la fase JSONB; el
   runtime ya usa GeoAlchemy2. `backend/models.py` es la fuente de verdad real.
7. **Stub muerto.** `frontend/main.py` neutralizado con `RuntimeError`. Pendiente
   `git rm frontend/main.py`.
8. **Catálogo duplicado.** La lista de cultivos válidos vive en constantes en 6
   archivos distintos; debería leerse desde la tabla `cultivos_catalogo` en runtime.

---

## Stack

### Backend

| Capa | Tecnología |
|---|---|
| Runtime | Python 3.12, FastAPI 0.115, Uvicorn, Pydantic 2.9 |
| ORM / DB | SQLAlchemy 2.0 async, asyncpg (prod), aiosqlite (dev fallback) |
| GIS | PostGIS 3.6, GeoAlchemy2, geopandas, shapely |
| ML | scikit-learn 1.5, numpy 1.26, pandas |
| Agronómico | FAO-56 Penman-Monteith + Hargreaves (código propio, Allen 1998) |
| Voz | openai-whisper 20240930 (`base`, carga lazy), Ollama `llama3.2:latest` |
| Migraciones | Alembic |

### Frontend

| Capa | Tecnología |
|---|---|
| UI | HTML5 + vanilla JS (sin bundler), CSS3 |
| Mapas | Leaflet 1.9.4 vía unpkg |
| Voz cliente | Web Speech API (STT en navegador + TTS) |

**Reglas duras:** no introducir React/Vue/Angular. No reemplazar FastAPI por
Django/Flask. No agregar dependencias sin justificación explícita.

---

## Estructura

```text
backend/
  main.py             # app FastAPI 2.0 con lifespan
  database.py         # IS_SQLITE flag para fallback dev
  models.py           # 7 modelos ORM (fuente de verdad real del schema)
  schema.sql          # DDL + 2 vistas KPI + seed  ⚠ desalineado con models.py
  init_db.py          # seeders
  alembic.ini
  migrations/
    versions/
      0001_postgis_geom_jsonb_to_geometry.py
  API/
    analytics_api.py
    db_api.py          # 14 endpoints CRUD
    riego_api.py       # endpoints FAO-56 + /parcelas/geojson
    voice_endpoint.py  # ⚠ path traversal sin sanitizar
  core/
    balance_hidrico.py  # FAO-56 + KC_TABLE + Hargreaves fallback
    kmeans_model.py
    llm_orchestrator.py # VALID_CULTIVOS + Ollama client
  tests/

frontend/
  index.html
  css/
    styles.css
  src/
    map_engine.js       # carga GeoJSON desde API PostGIS
    ui_tabs.js          # ⚠ recomendador BI hardcoded (demo)
    voice_client.js
  data/
    lotes.geojson       # fallback estático de geometrías

tools/
  generar_datos_sinteticos.py
  nasa_power_etl.py    # ETL NASA POWER → clima_diario
  geo_pipeline.py      # geopandas + make_valid + Douglas-Peucker

doc/
  diagramas_mermaid_milpin.md
  diagramas_uml_milpin.md
  data~origin_main
```

---

## Módulos UI

- **Mapas** — visor GIS con Leaflet; geometrías desde PostGIS vía `/api/parcelas/geojson`.
- **Riego** — recomendación FAO-56 por parcela, con historial y feedback.
- **BI/R** — demo de inteligencia de mercado con datos hardcodeados (no ML real).
- **Ajustes** — voz y preferencias.

---

## Endpoints

### GIS

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/parcelas/geojson` | GeoJSON FeatureCollection para Leaflet |

### Agronómico

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/balance_hidrico` | Calcula FAO-56 y persiste en `recomendaciones` |
| `GET` | `/api/balance_hidrico_manual` | Cálculo sin persistir (legacy) |
| `GET` | `/api/kc/{cultivo}` | Coeficientes Kc por cultivo |

### Voz

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/text-command` | Principal — Web Speech API en navegador |
| `POST` | `/api/voice-command` | Fallback — Whisper STT en servidor |

### CRUD

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/usuarios` | Crear usuario |
| `GET` | `/api/usuarios/{id}` | Obtener usuario con sus parcelas |
| `GET` | `/api/cultivos` | Listar catálogo |
| `GET` | `/api/cultivos/{id}` | Obtener cultivo |
| `POST` | `/api/parcelas` | Crear parcela |
| `GET` | `/api/parcelas` | Listar parcelas activas |
| `GET` | `/api/parcelas/{id}` | Parcela con historial reciente |
| `GET` | `/api/parcelas/{id}/kpi` | KPI consumo vs. baseline DR-041 |
| `POST` | `/api/riego` | Registrar evento de riego |
| `GET` | `/api/riego/parcela/{id}` | Historial de riego |
| `POST` | `/api/recomendaciones` | Guardar recomendación |
| `GET` | `/api/recomendaciones/{id}` | Obtener recomendación |
| `PATCH` | `/api/recomendaciones/{id}/feedback` | Registrar feedback del agricultor |
| `POST` | `/api/costos` | Registrar costos de ciclo |
| `GET` | `/api/costos/parcela/{id}` | Costos por ciclo |
| `GET` | `/health` | Health check |

---

## Base de datos

### Tablas

| Tabla | Descripción |
|---|---|
| `usuarios` | Agricultores y operadores |
| `cultivos_catalogo` | Parámetros FAO-56 (Kc) y FAO-33 (Ky) por especie |
| `parcelas` | Lotes con atributos edáficos y geometría PostGIS |
| `recomendaciones` | Recomendaciones de riego del motor FAO-56 con feedback |
| `historial_riego` | Eventos de riego ejecutados (fuente del KPI) |
| `costos_ciclo` | Resumen económico por parcela y ciclo |
| `clima_diario` | Series climáticas NASA POWER por parcela y día |

### Vistas KPI

- `v_agua_disponible`
- `v_kpi_consumo`

### Cultivos soportados

Maíz, Frijol, Algodón, Uva, Chile.

> **Nota:** Uva y Chile son cultivos de alto valor pero no dominantes del DR-041
> real (donde predominan trigo, cártamo, garbanzo). El catálogo puede necesitar
> revisión si el proyecto llega a validarse con agricultores reales.

---

## Instalación

### Requisitos

- Python 3.12+
- PostgreSQL 15+ con PostGIS 3.6
- Ollama con `llama3.2:latest` instalado (para voz/NLU)

### Backend

```bash
python -m venv venv
venv\Scripts\activate
pip install -r backend/requirements.txt
python backend/init_db.py
uvicorn backend.main:app --reload --port 8000
```

### Migraciones

```bash
cd backend
alembic upgrade head
```

### Variables de entorno (`backend/.env`)

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/milpin_mvp
MILPIN_OLLAMA_URL=http://localhost:11434/api/chat
MILPIN_OLLAMA_MODEL=llama3.2:latest
GROQ_API_KEY=
```

> **⚠ Seguridad:** rotar las credenciales y agregar `.env` al `.gitignore`
> antes de cualquier push a repositorio no privado.

---

## Notas

- `backend/models.py` es la fuente de verdad del schema en runtime.
  `backend/schema.sql` está desalineado y documenta la fase pre-PostGIS.
- `balance_hidrico_manual` es un endpoint legacy que no persiste datos.
- El usuario de prueba seeded es Ramón Valenzuela Torres
  (`rvalenzuela@dr041-dev.com`, Módulo 3).
