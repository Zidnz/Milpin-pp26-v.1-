# MILPÍN — CLAUDE.md

## 1. Qué es

DSS agrícola inteligente con GIS, ML y voz para optimizar el uso de agua
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
- ~~Persistencia del loop recomendación→feedback (tablas existen, no se escriben).~~ **RESUELTO 2026-05-01** — `PATCH /recomendaciones/{id}/feedback` auto-inserta en `historial_riego` cuando `aceptada` es `"aceptada"` o `"modificada"`. Verificado con test `TestFeedbackLoop` (7 casos).
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

**Deuda estructural:** la fuente de verdad debería ser la tabla
`cultivos_catalogo` leída en runtime, no constantes duplicadas en 6 lugares.

## 5. Deuda técnica conocida (priorizada)

Fase A — higiene y consolidación (hacer antes de features nuevas):

1. ~~**Credenciales filtradas.**~~ **RESUELTO 2026-05-30.** `.env` nunca fue
   commiteado (historial limpio). `.gitignore` raíz ya cubría `.env` y `.env.*`.
   Creado `backend/.env.example` con placeholders. Pendiente: rotar Groq API key
   (`gsk_...`) como precaución, ya que apareció en sesión de Claude Code.
2. ~~**Path traversal en voz.**~~ **RESUELTO** (fecha desconocida). `voice_endpoint.py`
   usa `tempfile.gettempdir()` + `uuid.uuid4().hex` para la ruta temporal; el
   nombre del archivo del cliente nunca toca el filesystem. Además valida
   content-type (allowlist), extensión (allowlist) y tamaño máximo (25 MB).
3. ~~**Backend duplicado.**~~ **RESUELTO.** `frontend/main.py` eliminado del repo.
4. **FAO-56 conectado a BD (resuelto 2026-04-25).** `riego_api.py` ahora lee
   parcela + cultivo + clima_diario por id, calcula balance hídrico, y
   persiste en `recomendaciones`. El endpoint legacy se movió a
   `/api/balance_hidrico_manual`. El loop recomendación→feedback está
   cableado (pendiente: probar end-to-end con datos reales).
5. ~~**Whisper carga al import.**~~ **RESUELTO 2026-04-30.** `import whisper`
   movido dentro de `_get_whisper()`. Startup bajó de ~45s a ~2s. Whisper
   y torch solo se cargan en el primer request de audio.
6. ~~**CORS abierto.**~~ **RESUELTO** (fecha desconocida). `main.py` usa
   `ALLOWED_ORIGINS` con lista explícita (localhost:3000/5500/5501/8080 + file://).
   No hay wildcard. `exception_handler` también propaga el header correcto en 500s.
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

## 6. Estructura del proyecto

Reestructurada 2026-05-16 según sección 18 de `MILPIN_Auditoria_ML_MLOps_v1.docx`.
Separación explícita de entrenamiento, inferencia, datos y orquestación.

```
milpin/
├── backend/                          # Sin cambios mayores
│   ├── main.py                       # app FastAPI 2.0 con lifespan
│   ├── .env                          # en .gitignore — usar .env.example como plantilla
│   ├── schema.sql                    # DDL + 2 vistas KPI + seed
│   ├── init_db.py                    # seeders
│   ├── models.py                     # modelos ORM
│   ├── database.py                   # IS_SQLITE flag para fallback dev
│   ├── settings.py
│   ├── migrations/                   # Alembic activo desde 2026-04-30
│   ├── tests/                        # 77+ tests (FAO-56 unitarios + e2e)
│   ├── API/
│   │   ├── riego_api.py              # endpoint FAO-56
│   │   ├── voice_endpoint.py         # STT Whisper + text-command; sanitización OK
│   │   ├── db_api.py
│   │   ├── ml_api.py
│   │   └── actuadores_api.py
│   └── core/
│       ├── balance_hidrico.py        # FAO-56 + KC_TABLE (fuente de verdad agro)
│       ├── eto_forecast.py           # Ridge Regression forecast 7 días
│       ├── llm_orchestrator.py       # VALID_CULTIVOS + Ollama client
│       ├── actuador_control.py
│       ├── xgboost_riego.py          # ⚠ RE-EXPORT TEMPORAL → ml/inference/
│       └── anomaly_detector.py       # ⚠ RE-EXPORT TEMPORAL → ml/inference/
│
├── ml/                               # Separación ML (nueva desde 2026-05-16)
│   ├── training/                     # Código de entrenamiento — nunca importa backend/
│   │   ├── xgboost_riego/
│   │   │   ├── train.py
│   │   │   ├── eval.py
│   │   │   ├── promote.py            # promote gate con umbrales en configs/
│   │   │   └── generar_datos.py
│   │   ├── isolation_forest/
│   │   │   └── train.py             # stub, Fase B
│   │   └── eto_ridge/
│   │       └── train.py             # stub, Fase B
│   ├── inference/                    # Wrappers de inferencia (singletons)
│   │   ├── xgboost_riego.py          # ← movido desde backend/core/
│   │   ├── anomaly_detector.py       # ← movido desde backend/core/
│   │   └── feature_preprocessor.py
│   ├── feature_store/
│   │   ├── views/                    # Definiciones YAML de features
│   │   │   ├── parcela_static.yaml
│   │   │   ├── parcela_daily.yaml
│   │   │   └── parcela_ciclo.yaml
│   │   └── builders/                 # Lógica de materialización (stub)
│   ├── monitoring/
│   │   ├── drift.py                  # PSI, KS — detección de drift
│   │   └── eval_metrics.py           # métricas compartidas
│   ├── pipelines/
│   │   └── train_eval_promote.py     # ref dist + promote gate (activo)
│   │   # nasa_power_daily, features_materialize, batch_scoring eliminados (eran stubs)
│   ├── experiments/                  # Notebooks experimentales
│   │   ├── eda_milpin.ipynb
│   │   ├── xgboost_v3_diversity.ipynb
│   │   └── anomaly_detector.ipynb
│   ├── configs/                      # Hyperparámetros declarativos YAML
│   │   ├── xgboost_riego.yaml
│   │   ├── isolation_forest.yaml
│   │   └── eto_ridge.yaml
│   └── tests/
│       ├── test_preprocessor.py
│       ├── test_drift.py
│       └── test_promote_gate.py
│
├── data/
│   ├── raw/                          # Cache NASA POWER, SHP originales
│   ├── synthetic/                    # CSVs sintéticos (fuente de verdad)
│   │   ├── milpin_ciclos_ml.csv      # dataset ML principal
│   │   └── (otros CSVs generados por tools/generar_datos_sinteticos.py)
│   ├── snapshots/                    # Parquets Feature Store (DVC)
│   └── README.md
│
├── tools/                            # Scripts CLI (no ML, no backend)
│   ├── nasa_power_etl.py             # Ingestor NASA POWER
│   ├── geo_pipeline.py               # geopandas + make_valid + Douglas-Peucker
│   ├── importar_csv_postgres.py
│   ├── recuperar_cache_nasa.py
│   ├── generar_datos_sinteticos.py
│   └── cargar_datos_sinteticos.py
│
├── frontend/                         # Sin cambios
│   ├── index.html
│   ├── src/
│   │   ├── map_engine.js
│   │   ├── ui_tabs.js
│   │   ├── bi_dashboard.js
│   │   ├── voice_client.js
│   │   ├── auth.js
│   │   └── admin_panel.js
│   ├── css/styles.css
│   └── data/                         # GeoJSON estáticos (fallback)
│
├── docs/                             # Documentación canónica (reemplaza doc/)
│   ├── ARCHITECTURE.md
│   ├── AGRONOMY.md                   # FAO-56/33 referenciado
│   ├── MLOPS.md
│   ├── SECURITY.md
│   └── runbooks/
│       ├── nasa_power_falla.md
│       └── drift_alerta.md
│
├── infra/                            # Docker, Prefect, MLflow, Grafana
│   ├── docker-compose.yml            # postgres+postgis, minio, mlflow, grafana
│   ├── prefect/
│   └── grafana/
│
├── pyproject.toml                    # (pendiente: reemplazar requirements.txt)
├── alembic.ini                       # (copia raíz; el canónico está en backend/)
├── CLAUDE.md
└── README.md
```

### Regla de imports entre capas

```
frontend  →  backend/API  →  backend/core (agro puro)
                          →  ml/inference (read-only)
ml/training  →  data/     →  ml/configs/
ml/training  NO importa backend/
```

### Re-exports temporales (eliminar en Fase B)
`backend/core/xgboost_riego.py` y `backend/core/anomaly_detector.py` son
re-exports temporales. No agregar lógica nueva allí. El código real vive en
`ml/inference/`.

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
