# MILPÍN — AGENTS.md

## 1. Qué es

ERP agrícola inteligente con GIS, ML y voz para optimizar el uso de agua
de riego en el Valle del Yaqui, Sonora (DR-041, foco en Módulo 3).

**KPI central:** reducir consumo de 8,000 m³/ha/ciclo → 6,000 m³/ha/ciclo
(ahorro objetivo 25%). Tarifa baseline: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m).

Es herramienta de apoyo a decisiones para agricultores, no sustituto del
juicio agronómico.

## 2. Estado real (2026-04-22)

Pre-MVP con core técnico sólido pero deuda acumulada. **La descripción que
circula en prompts antiguos ("PostgreSQL planeado") está desactualizada.**

Ya funciona:
- Backend FastAPI 2.0 con lifespan, 4 routers, SQLAlchemy async.
- Base de datos PostgreSQL: 5 modelos ORM, 12 endpoints CRUD, schema.sql
  con 2 vistas KPI, seeders (`init_db.py`).
- Motor agronómico FAO-56 Penman-Monteith implementado a mano en
  `backend/core/balance_hidrico.py` (fiel a Allen et al. 1998), con
  Hargreaves como fallback.
- Pipeline de voz: Whisper STT → Ollama `llama3.2:latest` (NLU/intent) →
  Web Speech API para TTS.
- Clustering K-Means de parcelas (scikit-learn 1.5).
- Frontend vanilla JS + Leaflet 1.9.4, capas Esri World Imagery + OpenTopoMap.
- Pipeline GIS con geopandas + shapely `make_valid` + Douglas-Peucker.

Falta para MVP:
- PostGIS real (hoy la geometría es JSONB).
- Autenticación (cualquiera puede postear `id_usuario` en el body).
- Migraciones Alembic (hoy se cambia `models.py` con `drop_all_tables()`).
- Tests automatizados.
- Persistencia del loop recomendación→feedback (tablas existen, no se escriben).

## 3. Stack — no cambiar sin justificación fuerte

| Capa | Tecnología |
|---|---|
| Backend | Python 3.10+, FastAPI 0.115, Uvicorn, Pydantic 2.9 |
| ORM/DB | SQLAlchemy 2.0 async, asyncpg (prod), aiosqlite (dev fallback) |
| ML | scikit-learn 1.5, numpy 1.26 |
| Agronómico | FAO-56 Penman-Monteith + Hargreaves (código propio) |
| Voz | openai-whisper 20240930 (`base`), Ollama `llama3.2:latest`, Web Speech API |
| Frontend | HTML5 + vanilla JS (sin bundler), CSS3, Leaflet 1.9.4 vía unpkg |
| GIS | geopandas, shapely, GeoJSON |

**Reglas duras:**
- No introducir React/Vue/Angular en el frontend.
- No reemplazar FastAPI por Django/Flask.
- No proponer frameworks que no estén ya en el repo sin justificación explícita.
- Mantener compatibilidad con FastAPI y Leaflet es regla dura del proyecto.

## 4. Catálogo de cultivos (fuente de verdad)

Los 5 cultivos oficiales son: **Maíz, Frijol, Algodón, Uva, Chile.**

Previamente existían Trigo, Cártamo y Garbanzo (formato beta/demo); fueron
eliminados de:
- `backend/core/balance_hidrico.py::KC_TABLE`
- `backend/core/llm_orchestrator.py::VALID_CULTIVOS`
- `backend/init_db.py::CULTIVOS_SEMILLA`
- `backend/schema.sql` (seed)
- `frontend/index.html` (select-cultivo)
- `tools/generar_datos_sinteticos.py::CATALOGO_CULTIVOS`

**Nota crítica:** Uva y Chile no son cultivos dominantes del DR-041 real
(los reales son trigo/maíz/cártamo/algodón/garbanzo). La selección
favorece cultivos de alto valor. Si en algún momento el proyecto se valida
con agricultores reales, este catálogo probablemente necesite volver a
discutirse.

**Deuda estructural:** la fuente de verdad debería ser la tabla
`cultivos_catalogo` leída en runtime, no constantes duplicadas en 6 lugares.

## 5. Deuda técnica conocida (priorizada)

Fase A — higiene y consolidación (hacer antes de features nuevas):

1. **Credenciales filtradas.** `backend/.env` tiene password postgres
   (`v1530066`) en texto plano y no parece estar en `.gitignore`. Rotar y
   ignorar.
2. **Path traversal en voz.** `backend/API/voice_endpoint.py` hace
   `temp_path = f"temp_{audio_file.filename}"` sin sanitizar. Además no
   hay límite de tamaño ni validación de content-type.
3. **Backend duplicado.** `frontend/main.py` es un stub sin BD mal
   ubicado; el real es `backend/main.py`. Borrar el stub.
4. **FAO-56 desconectado de la BD.** `backend/API/riego_api.py::get_balance_hidrico`
   recibe 13 query params (tmax, tmin, humedad_suelo...) en vez de leer de la
   parcela por id. `parcela_id` llega pero nunca se usa para `SELECT`. Nunca
   se escribe en `recomendaciones`. El loop recomendación→feedback existe en
   BD pero no se activa.
5. **Whisper carga al import.** `whisper.load_model("base")` a nivel módulo
   bloquea startup ~30-60s y consume ~150MB aunque no se use voz. Lazy load.
6. **CORS abierto.** `allow_origins=["*"]` — reemplazar por allowlist.
7. **Sin auth.** `id_usuario` entra como UUID en body; cualquiera crea
   parcelas a nombre de cualquiera.
8. **Sin migraciones.** Introducir Alembic.
9. **Recomendador BI falso.** `frontend/src/ui_tabs.js` hace cosine
   similarity sobre matriz 4×3×3 hardcoded. Es demo, no ML.

Usuario de prueba seeded: Ramón Valenzuela Torres (rvalenzuela@dr041-dev.com,
Módulo 3).

## 6. Estructura esperada

```
backend/
  main.py                      # app FastAPI 2.0 con lifespan
  .env                         # ⚠ contiene secretos, rotar
  schema.sql                   # DDL + 2 vistas KPI + seed
  init_db.py                   # seeders
  models.py                    # 5 modelos ORM
  database.py                  # IS_SQLITE flag para fallback dev
  API/
    riego_api.py               # endpoint FAO-56 (deuda: query params)
    voice_endpoint.py          # ⚠ path traversal sin sanitizar
    ...
  core/
    balance_hidrico.py         # FAO-56 + KC_TABLE
    llm_orchestrator.py        # VALID_CULTIVOS + Ollama client
frontend/
  index.html
  src/
    map_engine.js
    ui_tabs.js                 # recomendador fake
    voice_client.js
  main.py                      # ⚠ stub muerto, borrar
tools/
  geo_pipeline.py              # geopandas + make_valid + Douglas-Peucker
  generar_datos_sinteticos.py
```

## 7. Cómo colaborar con Omar

- Estilo directo, sin rodeos, sin halago. Omar pide rigor intelectual, no
  validación.
- Señalar supuestos no cuestionados y sesgos de confirmación de frente.
- Cuando se proponga una mejora, nombrar también el costo/trade-off.
- Si el usuario asume algo que el código contradice, citar archivo específico.
- Perfil técnico: intermedio bajo en Python/SQL, básico en R. Explicar el
  "por qué" además del "qué" en temas de backend/DevOps (FastAPI async,
  SQLAlchemy, PostGIS, Alembic). En ML/estadística ir más directo pero
  siempre conectando al problema de negocio.
- Omar viene de Business Development en Veolia (agua, LatAm); usar ese
  puente dominio↔técnica en las explicaciones.

## 8. Antes de tocar el repo

- Leer el código, no asumir desde el prompt.
- Verificar contra `backend/schema.sql` y `backend/models.py` antes de
  afirmar qué existe en BD.
- No introducir dependencias nuevas sin justificarlas contra el stack actual.
- No mockear la BD en tests — usar SQLite con `aiosqlite` como fallback real.
