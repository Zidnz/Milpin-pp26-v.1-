# MILPÍN — CLAUDE.md

## 1. Qué es

ERP agrícola inteligente con GIS, ML y voz para optimizar el uso de agua
de riego en el Valle del Yaqui, Sonora (DR-041, foco en Módulo 3).

**KPI central:** reducir consumo de 8,000 m³/ha/ciclo → 6,000 m³/ha/ciclo
(ahorro objetivo 25%). Tarifa baseline: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m).

Es herramienta de apoyo a decisiones para agricultores, no sustituto del
juicio agronómico.

## 2. Estado real (2026-04-30)

Pre-MVP con core técnico sólido pero deuda acumulada. **La descripción que
circula en prompts antiguos ("PostgreSQL planeado") está desactualizada.**

Ya funciona:
- Backend FastAPI 2.0 con lifespan, 4 routers, SQLAlchemy async.
- Base de datos PostgreSQL 15 + **PostGIS 3.6** (instalado 2026-04-30).
- 7 modelos ORM, 14 endpoints CRUD, schema.sql con 2 vistas KPI, seeders.
- **`parcelas.geom` es `GEOMETRY(Polygon,4326)`** — migrado desde JSONB vía
  Alembic `0001_postgis_geom_jsonb_to_geometry`. Índice GIST activo.
- Nuevo endpoint `GET /api/parcelas/geojson` (GeoJSON FeatureCollection para Leaflet).
- Motor agronómico FAO-56 Penman-Monteith implementado a mano en
  `backend/core/balance_hidrico.py` (fiel a Allen et al. 1998), con
  Hargreaves como fallback.
- Pipeline de voz: Whisper STT → Ollama `llama3.2:latest` (NLU/intent) →
  Web Speech API para TTS.
- Clustering K-Means de parcelas (scikit-learn 1.5).
- Frontend vanilla JS + Leaflet 1.9.4, capas Esri World Imagery + OpenTopoMap.
  `map_engine.js` carga parcelas desde API PostGIS (fallback: lotes.geojson estático).
- Pipeline GIS con geopandas + shapely `make_valid` + Douglas-Peucker.

Falta para MVP:
- ~~PostGIS real (hoy la geometría es JSONB).~~ **RESUELTO 2026-04-30.**
- ~~Migraciones Alembic~~ **RESUELTO 2026-04-30** — `backend/migrations/` activo.
- ~~Tests automatizados.~~ **RESUELTO 2026-05-01** — 77 tests (42 unitarios FAO-56 + 35 e2e con SQLite). Ver `backend/tests/`.
- ~~Persistencia del loop recomendación→feedback (tablas existen, no se escriben).~~ **RESUELTO 2026-05-01** — `PATCH /recomendaciones/{id}/feedback` auto-inserta en `historial_riego` cuando `aceptada` es `"aceptada"` o `"modificada"`. Verificado con test `TestFeedbackLoop` (7 casos).
- Autenticación (cualquiera puede postear `id_usuario` en el body).
- ~~**Humedad inicial inventada.**~~ **RESUELTO 2026-05-06.** `propagar_balance_hidrico()` en `core/balance_hidrico.py` reemplaza `(CC+PMP)/2` con balance acumulado dia a dia desde el ultimo riego real. Conectado en `riego_api.py::get_balance_hidrico()` y `db_api.py::forecast_parcela()`. 9 tests unitarios nuevos en `TestPropagar` (51 total).

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
3. ~~**Backend duplicado.**~~ **RESUELTO.** `frontend/main.py` eliminado del repo.
4. **FAO-56 conectado a BD (resuelto 2026-04-25).** `riego_api.py` ahora lee
   parcela + cultivo + clima_diario por id, calcula balance hídrico, y
   persiste en `recomendaciones`. El endpoint legacy se movió a
   `/api/balance_hidrico_manual`. El loop recomendación→feedback está
   cableado (pendiente: probar end-to-end con datos reales).
5. ~~**Whisper carga al import.**~~ **RESUELTO 2026-04-30.** `import whisper`
   movido dentro de `_get_whisper()`. Startup bajó de ~45s a ~2s. Whisper
   y torch solo se cargan en el primer request de audio.
6. **CORS abierto.** `allow_origins=["*"]` — reemplazar por allowlist.
7. **Sin auth.** `id_usuario` entra como UUID en body; cualquiera crea
   parcelas a nombre de cualquiera.
8. ~~**Sin migraciones.** Introducir Alembic.~~ **RESUELTO 2026-04-30.** `backend/migrations/` + `alembic.ini` activos. Próximas migraciones: usar `alembic revision -m "descripcion"` + `alembic upgrade head`.
9. ~~**Recomendador BI falso.**~~ **RESUELTO 2026-05-06.**
   - El cosine similarity sobre matriz hardcoded fue eliminado de `ui_tabs.js`.
   - `frontend/src/bi_dashboard.js` reemplaza el tab BI con dashboard conectado a API real.
   - Nuevo módulo `backend/core/eto_forecast.py`: Ridge Regression sobre `clima_diario`
     (features: sin/cos doy, lags et0, t_max). Fallback a media(14d) si <60 registros.
   - Nuevo endpoint `GET /api/parcelas/{id}/forecast?dias_siembra=N&horizon=7`: proyecta
     ETo 7 días y corre FAO-56 forward para estimar fecha de próximo riego (±días).
   - Tab Riego muestra sección "Proyección 7 días" con timeline de déficit diario.

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
