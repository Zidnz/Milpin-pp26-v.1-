<div align="center">
<img src="imagenes/icono.jpeg" alt="MILPÍN Logo" width="120" style="border-radius:50%"/>
<h1>MILPÍN AgTech</h1>
<h3>Sistema Inteligente de Optimización de Riego — Valle del Yaqui, DR-041</h3>
<p>
  <img src="https://img.shields.io/badge/estado-pre--MVP-orange?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15+-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
</p>
<p>
  <img src="https://img.shields.io/badge/PostGIS-3.6-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/XGBoost-modelos%20entrenados-F7931E?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Whisper-STT-FF6B6B?style=for-the-badge&logo=openai&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-LLM-7BB395?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Leaflet-GIS-199900?style=for-the-badge&logo=leaflet&logoColor=white"/>
</p>
<p>
  <img src="https://img.shields.io/badge/tests-108%20backend%20%2B%207%20ML-4CAF50?style=for-the-badge&logo=pytest&logoColor=white"/>
  <img src="https://img.shields.io/badge/Alembic-4%20migraciones-blueviolet?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/routers-6%20FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
</p>
<blockquote>
<strong>Meta principal:</strong> Reducir el consumo hídrico de <code>8,000 m³/ha/ciclo</code> a <code>6,000 m³/ha/ciclo</code> — un ahorro del <strong>25%</strong> equivalente a ~$1.68 MXN/m³ (tarifa CFE 9-CU, bombeo 80 m).
</blockquote>
</div>

---

> **ADVERTENCIA: Proyecto académico — datos sintéticos intencionalmente.**
> MILPÍN es un sistema de apoyo a decisiones desarrollado como proyecto de ciencia de datos aplicada.
> **No se llevará a producción.** Todos los datos de parcelas, usuarios, clima e historial son sintéticos
> y generados por los scripts de `tools/` y `ML/training/`. El motor agronómico FAO-56 es real y preciso;
> los datos que lo alimentan son ficticios pero agronómicamente plausibles para el Valle del Yaqui.

---

## Tabla de Contenidos

- [¿Qué es MILPÍN?](#-qué-es-milpín)
- [Estado del proyecto](#-estado-del-proyecto)
- [Deuda técnica vigente](#-deuda-técnica-vigente)
- [Arquitectura del sistema](#-arquitectura-del-sistema)
- [Stack tecnológico](#-stack-tecnológico)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [API Reference](#-api-reference)
- [Base de datos y migraciones](#-base-de-datos-y-migraciones)
- [Machine Learning](#-machine-learning)
- [Power BI](#-power-bi)
- [Instalación y uso](#-instalación-y-uso)
- [Motor FAO-56](#-motor-fao-56)
- [Asistente de voz](#-asistente-de-voz)

---

## ¿Qué es MILPÍN?

**MILPÍN** es un DSS (Decision Support System) agrícola inteligente para los productores del **Distrito de Riego DR-041 (Valle del Yaqui, Sonora, México)**. Combina modelos agronómicos científicos (FAO-56), machine learning supervisado y no supervisado, visualización geoespacial y un asistente de voz en español.

> El nombre honra a la **milpa**, el sistema agrícola ancestral mesoamericano, fusionándolo con tecnología de datos.

**Usuarios objetivo del prototipo:** Productores, técnicos de campo y administradores del módulo DR-041.

---

## Estado del proyecto

**Fase actual: Pre-MVP — bloqueador único: autenticación**

### Implementado y funcionando

| Componente | Detalle | Fecha |
|---|---|---|
| Backend FastAPI 2.0 | Lifespan, **6 routers**, SQLAlchemy 2.0 async | — |
| PostgreSQL 15 + **PostGIS 3.6** | `parcelas.geom` es `GEOMETRY(Polygon,4326)` con índice GIST. Migrado desde JSONB vía Alembic. | 2026-04-30 |
| 7 modelos ORM, 14+ endpoints CRUD | 2 vistas KPI, seeders, `schema.sql` | — |
| `GET /api/parcelas/geojson` | GeoJSON FeatureCollection listo para Leaflet, servido desde PostGIS | 2026-04-30 |
| Motor agronómico FAO-56 | Penman-Monteith (`balance_hidrico.py`), Hargreaves como fallback. Lee parcela + cultivo + clima de BD, persiste en `recomendaciones`. | — |
| **4 migraciones Alembic activas** | `0001` JSONB→geometry, `0002` columna `rol` en usuarios, `0003` rangos de rendimiento en cultivos, `0004` columna `ciclo_agricola` en `historial_riego` | 2026-04-30 / 2026-05-16 |
| **108 tests backend** | 51 unitarios FAO-56 + 32 e2e SQLite + 11 ML + 14 actuadores. Ejecutar con `pytest backend/tests/`. | 2026-05-06+ |
| **7 tests ML** | drift, preprocessor, promote_gate en `ML/tests/` | 2026-05-16 |
| **Loop recomendación→feedback** | `PATCH /recomendaciones/{id}/feedback` auto-inserta en `historial_riego` cuando `aceptada` es `"aceptada"` o `"modificada"`. Verificado con `TestFeedbackLoop` (7 casos). | 2026-05-01 |
| **Humedad inicial real** | `propagar_balance_hidrico()` reemplaza `(CC+PMP)/2` con balance acumulado desde último riego. 9 tests en `TestPropagar`. | 2026-05-06 |
| **Dashboard BI real** | `bi_dashboard.js` conectado a API real (cosine similarity hardcoded eliminado de `ui_tabs.js`). | 2026-05-06 |
| **Forecast ETo 7 días** | `backend/core/eto_forecast.py`: Ridge Regression (sin/cos doy, lags ETo, T_max). Fallback a media(14 d) si < 60 registros. | 2026-05-06 |
| **XGBoost entrenado** | 3 modelos: `xgb_requiere_riego`, `xgb_lamina_ajustada`, `xgb_riesgo_estres`. Archivos `.joblib` en `ML/models/` y `backend/models_ml/`. | 2026-05-16 |
| **Isolation Forest entrenado** | Detección de anomalías en historial de riego. Archivos `.joblib` en `ML/models/`. | 2026-05-16 |
| **ml_api.py** | 3 endpoints: `GET /api/ml/prediccion/{id}`, `/api/ml/anomalias`, `/api/ml/metricas`. Fallback a CSV sintético si BD < 50 registros. | 2026-05-16 |
| **actuadores_api.py** | 5 endpoints para control de actuadores físicos de riego. | 2026-05-16 |
| **Módulo ML separado** | `ML/` con training, inference, configs YAML, monitoring, pipelines, experiments, feature_store. | 2026-05-16 |
| **Power BI** | Medidas DAX y Power Query M en `MILPIN_PowerBI/`. Conectado a CSVs sintéticos. Proyecto PBIR eliminado del repo; dashboards en-app vía `bi_dashboard.js` + `bi_operacion.js`. | — |
| **Vista de carga de trabajo técnica** | `GET /api/tecnico/carga-trabajo` agrega parcelas activas con última recomendación pendiente, ordenadas por urgencia. Frontend: `tecnico_workload.js`. | 2026-05-18 |
| **Dashboard operacional v2** | `bi_operacion.js` — vista de operación con pulso climático. `GET /api/operacion/triage` (lista priorizada FAO-56) y `GET /api/parcelas/{id}/clima` (serie climática W6). Router: `operacion_api.py`. | 2026-05-19 |
| Pipeline de voz | Whisper STT carga lazy (startup ~2 s) → Ollama `llama3.2:latest` → Web Speech API TTS | 2026-04-30 |
| Clustering K-Means | scikit-learn 1.5, zonas de manejo y logística | — |
| Frontend GIS | Vanilla JS + Leaflet 1.9.4, capas Esri + OpenTopoMap + límites Cajeme. `map_engine.js` carga desde PostGIS (fallback: `lotes.geojson`). | — |

### Pendiente para MVP

| Ítem | Descripción |
|---|---|
| **Autenticación** | `id_usuario` entra como UUID en body; cualquiera puede crear parcelas a nombre de cualquiera. Bloqueador principal. Migración `0002` ya agrega columna `rol` (agricultor/admin). |
| CORS restringido | `allow_origins=["*"]` — reemplazar por allowlist. |
| Seguridad en voz | Path traversal en `voice_endpoint.py` (`temp_{audio_file.filename}` sin sanitizar), sin límite de tamaño ni validación de content-type. |

---


## Arquitectura del sistema

```mermaid
flowchart TB
    subgraph FRONTEND["FRONTEND (SPA)"]
        direction TB
        FE_TECH["index.html · Leaflet.js · Web Audio API · Vanilla JS"]
        subgraph FE_MODULES["Módulos JS"]
            BI["bi_dashboard.js"]
            GIS["map_engine.js"]
            RIEGO["ui_tabs.js"]
            VOICE["voice_client.js"]
            AUTH["auth.js"]
            ADMIN["admin_panel.js"]
        end
    end

    subgraph BACKEND["BACKEND (FastAPI — 6 routers)"]
        direction TB
        subgraph APIS["APIs"]
            DB_API["db_api.py — CRUD 14 endpoints"]
            RIEGO_API["riego_api.py — FAO-56 + /geojson + forecast"]
            ML_API["ml_api.py — XGBoost + IForest + métricas"]
            ACT_API["actuadores_api.py — control físico"]
            VOICE_EP["voice_endpoint.py — STT pipeline"]
            OPER_API["operacion_api.py — triage FAO-56 + pulso climático"]
        end
        subgraph CORE["core/"]
            BH["balance_hidrico.py — FAO-56"]
            ETO["eto_forecast.py — Ridge Regression"]
            LLM["llm_orchestrator.py — Ollama/Groq"]
            ACT["actuador_control.py"]
        end
    end

    subgraph ML_MODULE["ML/ (separado de backend)"]
        direction TB
        subgraph INFERENCE["inference/"]
            XGB["xgboost_riego.py"]
            IFOR["anomaly_detector.py"]
            FEAT["feature_preprocessor.py"]
        end
        subgraph TRAINING["training/"]
            TXGB["xgboost_riego/train.py"]
            TIFOR["isolation_forest/train.py"]
            TETO["eto_ridge/train.py"]
        end
        MODELS["models/ — .joblib entrenados"]
        MONITOR["monitoring/ — drift.py, eval_metrics.py"]
    end

    subgraph DB["DATABASE"]
        direction TB
        DB_ENGINE["PostgreSQL 15 + PostGIS 3.6"]
        TABLES["7 tablas + 2 vistas KPI"]
    end

    FRONTEND -->|"HTTP / REST"| BACKEND
    BACKEND -->|"SQLAlchemy Async + asyncpg"| DB
    ML_API --> INFERENCE
    INFERENCE --> MODELS
```

---

## Stack tecnológico

### Backend

| Tecnología | Versión | Rol |
|---|---|---|
| **FastAPI** | 0.115.0 | Framework REST asíncrono |
| **SQLAlchemy** | 2.0.36 | ORM asíncrono |
| **asyncpg** | 0.30.0 | Driver PostgreSQL async |
| **aiosqlite** | 0.20.0 | Driver SQLite async (fallback dev / tests) |
| **Alembic** | latest | Migraciones de schema (4 activas) |
| **GeoAlchemy2** | latest | Tipos PostGIS en ORM |
| **Uvicorn** | 0.30.6 | Servidor ASGI |
| **OpenAI Whisper** | 20240930 | STT local — carga **lazy** |
| **Web Speech API** | Browser | STT nativo en cliente (path principal) |
| **Ollama** | latest | LLM local (`llama3.2:latest`) |
| **Groq** | cloud | LLM cloud alternativo (opcional) |
| **XGBoost** | latest | 3 modelos de riego entrenados |
| **scikit-learn** | 1.5.2 | K-Means + Isolation Forest + Ridge Regression |
| **numpy** | 1.26.4 | Cálculos numéricos |
| **pandas** | 2.2.3 | DataFrames para ETL y ML |
| **geopandas + shapely** | 2.0.6 | Pipeline GIS (`make_valid`, Douglas-Peucker) |
| **Pydantic** | 2.9.2 | Validación de datos |
| **pytest / pytest-asyncio** | latest | 108 tests backend + 7 ML |

### Frontend

| Tecnología | Rol |
|---|---|
| **HTML5 / CSS3** | SPA estructurada con sistema de diseño propio |
| **JavaScript (Vanilla)** | Lógica de tabs, voz, GIS, BI |
| **Leaflet.js 1.9.4** | Motor GIS — carga desde API PostGIS |
| **Web Audio API** | Captura de micrófono (fallback voz) |

**Reglas duras:** no introducir React/Vue/Angular. No reemplazar FastAPI por Django/Flask. No agregar dependencias sin justificación explícita.

---

## Estructura del proyecto

```text
milpin/
├── backend/
│   ├── main.py                    # FastAPI 2.0 con lifespan, CORS, 6 routers
│   ├── database.py                # Engine async, IS_SQLITE flag para fallback dev
│   ├── models.py                  # 7 modelos ORM — fuente de verdad del schema
│   ├── schema.sql                 # DDL + 2 vistas KPI + seed  [WARN] desalineado con models.py
│   ├── init_db.py                 # seeders (--reset, --check)
│   ├── settings.py
│   ├── alembic.ini
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── .env                       # [WARN] contiene secretos — rotar, verificar gitignore
│   ├── API/
│   │   ├── db_api.py              # CRUD: 14 endpoints + forecast parcela
│   │   ├── riego_api.py           # FAO-56 + /parcelas/geojson + balance hídrico
│   │   ├── ml_api.py              # XGBoost predicción + Isolation Forest anomalías + métricas
│   │   ├── actuadores_api.py      # Control de actuadores físicos de riego
│   │   ├── operacion_api.py       # Triage FAO-56 priorizado + serie climática W6
│   │   └── voice_endpoint.py      # [WARN] path traversal sin sanitizar
│   ├── core/
│   │   ├── balance_hidrico.py     # FAO-56 Penman-Monteith + KC_TABLE + propagar_balance_hidrico()
│   │   ├── eto_forecast.py        # Ridge Regression forecast ETo 7 días
│   │   ├── llm_orchestrator.py    # VALID_CULTIVOS + Ollama/Groq client
│   │   └── actuador_control.py    # Lógica de control de actuadores
│   ├── models_ml/                 # [WARN] DUPLICADO — mismo contenido que ML/models/. Eliminar.
│   │   └── *.joblib               # 7 archivos de modelos entrenados
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_postgis_geom_jsonb_to_geometry.py  # JSONB → GEOMETRY(Polygon,4326)
│   │       ├── 0002_usuarios_add_rol.py                # columna rol (agricultor/admin)
│   │       └── 0003_cultivos_catalogo_rendimiento.py   # rangos rendimiento min/max ton/ha
│   └── tests/
│       ├── conftest.py                 # fixtures SQLite async
│       ├── test_fao56_unit.py          # 51 tests unitarios (FAO-56 + TestPropagar)
│       ├── test_riego_e2e.py           # 32 tests e2e (endpoints + BD SQLite)
│       ├── test_ml.py                  # 11 tests integración ml_api
│       ├── test_actuadores.py          # 14 tests actuadores_api
│       ├── grabar.py                   # script grabación audio (manual)
│       ├── generar_audios_tts.py       # generación TTS para test cases
│       ├── run_tests.py                # runner personalizado
│       ├── test_cases.json             # casos de prueba voz
│       └── audio/                      # 50 archivos MP3 para pruebas de voz
│
├── ML/                            # Módulo ML separado de backend (desde 2026-05-16)
│   ├── inference/
│   │   ├── xgboost_riego.py       # Wrapper singleton XGBoost (3 modelos)
│   │   ├── anomaly_detector.py    # Wrapper singleton Isolation Forest
│   │   └── feature_preprocessor.py
│   ├── training/
│   │   ├── xgboost_riego/
│   │   │   ├── train.py           # Entrenamiento XGBoost
│   │   │   ├── eval.py            # Evaluación
│   │   │   ├── promote.py         # Promote gate con umbrales YAML
│   │   │   ├── generar_datos.py   # Generación de datos sintéticos ML
│   │   │   ├── v7_train.py        # Entrenamiento v7 (anti-leakage)
│   │   │   ├── v7_generar_datos.py
│   │   │   ├── v7_benchmark.py
│   │   │   ├── v7_causal_validation.py
│   │   │   └── v7_leakage_detector.py
│   │   ├── isolation_forest/
│   │   │   └── train.py
│   │   └── eto_ridge/
│   │       └── train.py
│   ├── models/                    # Modelos entrenados (fuente de verdad)
│   │   ├── xgb_requiere_riego.joblib
│   │   ├── xgb_lamina_ajustada.joblib
│   │   ├── xgb_riesgo_estres.joblib
│   │   ├── xgb_metricas.joblib
│   │   ├── iforest_model.joblib
│   │   ├── iforest_scaler.joblib
│   │   └── iforest_metricas.joblib
│   ├── experiments/               # Notebooks de exploración y análisis
│   │   ├── eda_milpin.ipynb
│   │   ├── eda_parcelas_usuarios_cultivos.ipynb
│   │   ├── anomaly_detector.ipynb
│   │   ├── balance_hidrico_visualizacion.ipynb
│   │   ├── distribucion_consumo_agua.ipynb
│   │   ├── eda_kpi_powerbi.ipynb
│   │   ├── eda_powerbi_verificacion.ipynb
│   │   ├── fao56_visualizacion.ipynb
│   │   ├── milpin_datos_sinteticos_auditoria.ipynb
│   │   ├── milpin_xgboost_prediccion_v3.ipynb
│   │   ├── milpin_xgboost_v4.ipynb … v7.ipynb
│   │   ├── generar_ciclos_ml.py
│   │   └── ImagenesML/            # Gráficas generadas por notebooks
│   ├── images/                    # Imágenes exportadas (SHAP, learning curves, etc.)
│   ├── patch_notebooks.py
│   ├── configs/
│   │   ├── xgboost_riego.yaml
│   │   ├── xgboost_riego_v7.yaml
│   │   ├── isolation_forest.yaml
│   │   └── eto_ridge.yaml
│   ├── monitoring/
│   │   ├── drift.py               # PSI, KS — detección de drift
│   │   └── eval_metrics.py
│   ├── feature_store/
│   │   ├── views/                 # Definiciones YAML de features
│   │   │   ├── parcela_static.yaml
│   │   │   ├── parcela_daily.yaml
│   │   │   └── parcela_ciclo.yaml
│   │   └── builders/              # Vacío — pendiente implementación
│   ├── pipelines/                 # Stubs Prefect (pendientes Fase C/D)
│   │   ├── nasa_power_daily.py
│   │   ├── features_materialize.py
│   │   ├── train_eval_promote.py
│   │   └── batch_scoring.py
│   └── tests/
│       ├── test_drift.py          # 3 tests
│       ├── test_preprocessor.py   # 2 tests
│       └── test_promote_gate.py   # 2 tests
│
├── data/
│   ├── synthetic/                 # Fuente de verdad — datos 100% sintéticos
│   │   ├── usuarios.csv
│   │   ├── parcelas.csv
│   │   ├── cultivos_catalogo.csv
│   │   ├── historial_riego.csv
│   │   ├── recomendaciones.csv
│   │   ├── costos_ciclo.csv
│   │   ├── milpin_ciclos_ml.csv   # Dataset ML principal
│   │   ├── anomalias_labels.csv   # Labels para evaluación Isolation Forest
│   │   └── anomaly_report.csv     # Reporte de anomalías detectadas
│   ├── raw/nasa_power/            # Cache NASA POWER (~75 archivos JSON por parcela)
│   └── snapshots/                 # Parquets Feature Store (vacío en dev)
│
├── frontend/
│   ├── index.html                 # SPA principal (4 tabs + FAB de voz)
│   ├── css/styles.css             # Sistema de diseño tierra (#7BB395, #4A3B28)
│   ├── src/
│   │   ├── map_engine.js          # Leaflet + GeoJSON desde PostGIS
│   │   ├── ui_tabs.js             # Lógica de tabs
│   │   ├── bi_dashboard.js        # Dashboard BI conectado a API real
│   │   ├── bi_operacion.js        # Dashboard operacional v2 (triage + pulso climático)
│   │   ├── tecnico_workload.js    # Vista de carga de trabajo técnica
│   │   ├── voice_client.js        # Web Speech API + fallback Whisper
│   │   ├── auth.js                # Lógica de autenticación (en desarrollo)
│   │   └── admin_panel.js         # Panel admin (en desarrollo)
│   ├── data/
│   │   ├── lotes.geojson          # Fallback estático geometrías parcelas
│   │   └── cajeme_limits.geojson  # Límites municipales Cajeme
│   └── imagenes/
│       ├── milpin-logo.png
│       └── milpin-logo-transparente.png
│
├── tools/                         # Scripts CLI
│   ├── nasa_power_etl.py          # Ingestor NASA POWER → clima_diario
│   ├── geo_pipeline.py            # geopandas + make_valid + Douglas-Peucker
│   ├── generar_datos_sinteticos.py # Generador de datos sintéticos
│   ├── cargar_datos_sinteticos.py  # Carga CSVs sintéticos a PostgreSQL
│   ├── importar_csv_postgres.py    # Importador genérico CSV → PostgreSQL
│   ├── recuperar_cache_nasa.py     # Recuperación de caché NASA POWER
│   └── add_eda_sections.py         # Utilidad para notebooks EDA
│
├── docs/                          # Documentación técnica y académica
│   ├── ARCHITECTURE.md
│   ├── AGRONOMY.md                # FAO-56/33 referenciado
│   ├── MLOPS.md
│   ├── SECURITY.md
│   ├── diagramas_mermaid_milpin.md
│   ├── diagramas_uml_milpin.md
│   ├── runbooks/
│   │   ├── nasa_power_falla.md
│   │   └── drift_alerta.md
│   └── *.docx / *.pdf             # Documentos académicos de entrega (v2–v4)
│
├── manifests/                     # Manifiestos de despliegue (Kubernetes/Docker)
│
├── MILPIN_PowerBI/                # Scripts y archivo Power BI
│   ├── milpin_dashboard.pbix      # Archivo Power BI (requiere ajustar rutas de CSVs)
│   ├── medidas_DAX.txt
│   ├── power_query_M.txt
│   └── GUIA_CONFIGURACION.txt
│
├── infra/
│   ├── docker-compose.yml         # postgres+postgis, minio, mlflow, grafana
│   ├── grafana/                   # Vacío — pendiente configuración
│   └── prefect/                   # Vacío — pendiente configuración
│
├── imagenes/                      # Assets gráficos
│   └── *.jpeg / *.png             # Logos, cultivos, capturas
│
├── CLAUDE.md                      # Instrucciones para Claude Code
├── AGENTS.md
├── MILPIN_PlanNegocios_Revisado.docx
├── MILPIN_Requerimientos_Negocio.docx
├── MILPIN_Tecnico_v6.docx
├── MILPIN_Vision_Solucion.docx
├── generar_doc_ml.py
├── requirements.txt               # Requirements raíz (redundante con backend/)
└── .gitignore
```

> **Deuda estructural pendiente:**
> - `backend/models_ml/` — duplicado de `ML/models/`, eliminar
> - `milpin_env/` — entorno virtual commiteado, agregar a `.gitignore` y hacer `git rm -r --cached`

---

## API Reference

### GIS

```http
GET /api/parcelas/geojson
```

GeoJSON FeatureCollection con todas las parcelas activas, generada desde PostGIS. `map_engine.js` consume este endpoint; fallback a `lotes.geojson` si falla.

---

### Balance Hídrico FAO-56

```http
GET /api/balance_hidrico?parcela_id=<uuid>&dias_siembra=<int>&fecha=<YYYY-MM-DD>
```

Lee edáfica de `parcelas`, cultivo de `cultivos_catalogo` y clima de `clima_diario`. Calcula ETo (Penman-Monteith o Hargreaves), ETc y balance hídrico. **Persiste en `recomendaciones`** antes de responder.

**Respuesta incluye:** `id_recomendacion`, `eto_mm`, `kc`, `etc_mm`, `balance`, `costo`, `nivel_urgencia` (`critico` / `moderado` / `preventivo`), `persistido: true`.

---

### Forecast ETo 7 días

```http
GET /api/parcelas/{id}/forecast?dias_siembra=<int>&horizon=7
```

Ridge Regression sobre `clima_diario` (features: sin/cos doy, lags ETo, T_max). Corre FAO-56 forward y estima fecha del próximo riego. Fallback a media(14 d) si < 60 registros.

---

### Machine Learning

```http
GET /api/ml/prediccion/{id_parcela}
```

Tres modelos XGBoost en paralelo: `requiere_riego` (bool), `lamina_ajustada_mm` (float), `riesgo_estres` (clasificación). Lee parcela + última recomendación de BD. Si no hay datos suficientes, usa defaults por tipo de suelo.

```http
GET /api/ml/anomalias?solo_anomalias=true&limit=50
```

Isolation Forest sobre `historial_riego`. Fallback a CSV sintético si BD < 50 registros. `solo_anomalias=false` incluye todos los registros con su score.

```http
GET /api/ml/metricas
```

Métricas de XGBoost e Isolation Forest. Incluye disclaimer explícito sobre datos sintéticos.

---

### Actuadores

```http
POST /api/actuadores/activar
GET  /api/actuadores/estado
POST /api/actuadores/desactivar
GET  /api/actuadores/historial
POST /api/actuadores/programar
```

---

### Operación

```http
GET /api/operacion/triage
```

Lista priorizada de parcelas ordenadas por urgencia FAO-56 (`critico` → `moderado` → `preventivo`). Incluye días desde último riego, balance hídrico actual y recomendación pendiente. Consumido por `bi_operacion.js`.

```http
GET /api/parcelas/{id}/clima
```

Pulso climático W6: serie climática de los últimos 6 días para la parcela (ETo, T_max, precipitación). Fallback si no hay registros: vacío con flag `sin_datos`.

---

### Comandos de Voz

```http
POST /api/text-command    # PRINCIPAL — texto Web Speech API → LLM
POST /api/voice-command   # FALLBACK — audio WebM → Whisper STT → LLM
```

**Intents soportados:** `navegar`, `ejecutar_analisis`, `llenar_prescripcion`, `consultar`, `saludo`, `desconocido`.

> **ADVERTENCIA - Seguridad:** `voice-command` no sanitiza el nombre del archivo (path traversal). Deuda técnica #3.

---

### Curvas Kc y CRUD

```http
GET /api/kc/{cultivo}                          # Coeficientes Kc por etapa fenológica
GET /api/balance_hidrico_manual?...            # Legacy sin BD
POST /api/usuarios / GET /api/usuarios/{id}
POST /api/parcelas / GET /api/parcelas / GET /api/parcelas/{id}
GET /api/parcelas/{id}/kpi                     # KPI consumo vs. baseline DR-041
POST /api/riego / GET /api/riego/parcela/{id}
POST /api/recomendaciones / GET /api/recomendaciones/{id}
PATCH /api/recomendaciones/{id}/feedback       # Loop feedback → historial_riego
POST /api/costos / GET /api/costos/parcela/{id}
GET /health
```

---

## Base de datos y migraciones

### 7 tablas + 2 vistas

| Tabla | Descripción |
|---|---|
| `usuarios` | Agricultores/técnicos/admins. Columna `rol` (agricultor/admin) — migración `0002`. |
| `cultivos_catalogo` | Parámetros FAO-56 (Kc, etapas) y FAO-33 (Ky). Rangos rendimiento min/max — migración `0003`. |
| `parcelas` | Lotes con atributos edáficos. `geom` es `GEOMETRY(Polygon,4326)` con índice GIST — migración `0001`. |
| `recomendaciones` | Recomendaciones FAO-56 con estado de feedback del agricultor. |
| `historial_riego` | Eventos de riego ejecutados — fuente del KPI de consumo hídrico. |
| `costos_ciclo` | Resumen económico por parcela y ciclo agrícola. |
| `clima_diario` | Series climáticas diarias por parcela (fuente: NASA POWER o sintético). |

| Vista | Descripción |
|---|---|
| `v_agua_disponible` | ADT (mm) = (CC - PMP) × profundidad_raiz × 10 |
| `v_kpi_consumo` | Consumo anual vs. baseline DR-041 (8,000 m³/ha) y ahorro estimado en MXN |

> `backend/models.py` es la fuente de verdad del schema en runtime. `schema.sql` está desalineado (aún documenta JSONB).

### Migraciones Alembic

```bash
cd backend
alembic upgrade head                          # aplica las 4 migraciones
alembic revision -m "descripcion_cambio"      # crea nueva migración
```

| Migración | Descripción |
|---|---|
| `0001_postgis_geom_jsonb_to_geometry` | `parcelas.geom`: JSONB → `GEOMETRY(Polygon,4326)` + índice GIST |
| `0002_usuarios_add_rol` | Columna `rol` en `usuarios` (agricultor/admin, default: agricultor) |
| `0003_cultivos_catalogo_rendimiento` | Columnas `rendimiento_min_ton` y `rendimiento_max_ton` en `cultivos_catalogo` |
| `0004_historial_riego_ciclo_agricola` | Columna `ciclo_agricola` en `historial_riego` |

### Cultivos precargados

| Cultivo | Kc inicial | Kc medio | Kc final | Ky |
|---|---|---|---|---|
| Maíz | 0.30 | 1.20 | 0.60 | 1.25 |
| Frijol | 0.40 | 1.15 | 0.35 | 1.15 |
| Algodón | 0.35 | 1.20 | 0.70 | 0.85 |
| Uva | 0.30 | 0.85 | 0.45 | 0.85 |
| Chile | 0.60 | 1.05 | 0.90 | 1.10 |

> **Nota:** Uva y Chile son cultivos de alto valor pero no dominantes en el DR-041 real (predominan trigo, cártamo, garbanzo). El catálogo es una decisión académica para el prototipo.

---

## Machine Learning

El módulo `ML/` está separado de `backend/` con una regla de imports explícita: `ML/training/` nunca importa desde `backend/`.

### Modelos entrenados (`.joblib` en `ML/models/`)

| Modelo | Tipo | Target |
|---|---|---|
| `xgb_requiere_riego` | XGBoost clasificación | ¿La parcela necesita riego hoy? |
| `xgb_lamina_ajustada` | XGBoost regresión | Lámina de riego recomendada (mm) |
| `xgb_riesgo_estres` | XGBoost clasificación | Nivel de estrés hídrico |
| `iforest_model` | Isolation Forest | Detección de anomalías en historial |

Todos los modelos fueron entrenados sobre datos sintéticos generados por `tools/generar_datos_sinteticos.py` y `ML/training/xgboost_riego/generar_datos.py`. Las métricas están guardadas en los archivos `.joblib` de métricas y son accesibles vía `GET /api/ml/metricas`.

### Datos sintéticos (proyecto académico)

Los datos que alimentan los modelos y la BD son **100% sintéticos** generados programáticamente con distribuciones plausibles para el Valle del Yaqui. Esto es intencional — es un proyecto académico y no se llevará a producción. Los archivos están en `data/synthetic/`.

---

## Power BI

El directorio `MILPIN_PowerBI/` contiene el archivo Power BI y los scripts de configuración:

- `milpin_dashboard.pbix` — archivo Power BI Desktop (requiere ajustar rutas a los CSVs de `data/synthetic/`)
- `medidas_DAX.txt` — medidas calculadas DAX (referencia)
- `power_query_M.txt` — transformaciones Power Query (referencia)
- `GUIA_CONFIGURACION.txt` — instrucciones paso a paso (~30-45 min)

Los reportes consumen los CSVs de `data/synthetic/`. Actualizar las rutas en Power Query M para apuntar a la ruta local del repo.

> **Nota:** El proyecto PBIR (`pbir/`) fue eliminado del repositorio. El dashboard en-app está implementado como `bi_dashboard.js` y `bi_operacion.js` conectados directamente a la API REST.

---

## Instalación y uso

### Requisitos previos

- Python 3.12+
- PostgreSQL 15+ con extensión **PostGIS 3.6**
- Ollama con `llama3.2:latest` (`ollama pull llama3.2:latest`)
- ffmpeg (incluido vía `imageio-ffmpeg`)

### Backend

```bash
# 1. Clonar el repositorio
git clone https://github.com/Zidnz/Milpin-pp26-v.1-.git
cd Milpin-pp26-v.1-

# 2. Crear entorno virtual e instalar dependencias
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
pip install -r backend/requirements.txt

# 3. Configurar variables de entorno
# Copiar y editar backend/.env con DATABASE_URL y configuración de Ollama

# 4. Inicializar la base de datos
python backend/init_db.py            # Crea tablas + seed
python backend/init_db.py --reset    # DROP + CREATE + seed (destructivo)
python backend/init_db.py --check    # Solo verifica conexión

# 5. Aplicar migraciones Alembic
cd backend && alembic upgrade head   # aplica las 4 migraciones

# 6. Cargar datos sintéticos (opcional para desarrollo)
python tools/cargar_datos_sinteticos.py

# 7. Iniciar el servidor
uvicorn backend.main:app --reload --port 8000
```

### Tests

```bash
# Todos los tests backend (108)
pytest backend/tests/

# Por suite
pytest backend/tests/test_fao56_unit.py    # 51 unitarios FAO-56
pytest backend/tests/test_riego_e2e.py     # 32 e2e endpoints
pytest backend/tests/test_ml.py            # 11 integración ML
pytest backend/tests/test_actuadores.py    # 14 actuadores

# Tests del módulo ML (7)
pytest ML/tests/
```

Los tests e2e usan SQLite con `aiosqlite` — no mockean la BD.

### Frontend

```bash
open frontend/index.html
# O con live-server:
npx live-server frontend --port=5500
```

### Variables de entorno (`backend/.env`)

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/milpin_mvp
MILPIN_OLLAMA_URL=http://localhost:11434/api/chat
MILPIN_OLLAMA_MODEL=llama3.2:latest
GROQ_API_KEY=                     # opcional
```

---

## Motor FAO-56

El corazón agronómico implementa **FAO-56 Penman-Monteith** (Allen et al., 1998):

```
ETo = [0.408·Δ·(Rn - G) + γ·(900/(T+273))·u₂·(es - ea)]
      ─────────────────────────────────────────────────────
                    [Δ + γ·(1 + 0.34·u₂)]
```

Si los datos de radiación o humedad son insuficientes, cae a **Hargreaves** como fallback. `propagar_balance_hidrico()` calcula la humedad inicial acumulando balance día a día desde el último riego real — no usa la estimación `(CC+PMP)/2`.

**Parámetros locales por defecto:**
- Latitud: 27.37°N (Cajeme, Valle del Yaqui)
- Altitud: 40 m (Cd. Obregón)
- Tarifa energética: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m)

---

## Asistente de voz

```mermaid
flowchart LR
    USER["Usuario habla"]
    USER --> WSA["Web Speech API\n(STT nativo — path principal)"]
    WSA --> TEXT_CMD["POST /api/text-command"]
    USER --> |fallback| AUDIO["Web Audio API"]
    AUDIO --> VOICE_CMD["POST /api/voice-command"]
    VOICE_CMD --> WHISPER["Whisper STT\n(carga lazy ~2 s)"]
    WHISPER --> LLM
    TEXT_CMD --> LLM["Ollama llama3.2\n(local)"]
    LLM --> PARSER["Intent Parser (JSON)"]
    PARSER --> UI["Acción en UI"]
```

**Memoria conversacional:** últimos 3 turnos (6 mensajes).

---

## Paleta de diseño

| Color | Hex | Uso |
|---|---|---|
| Verde primario | `#7BB395` | Botones, acentos, estado activo |
| Tierra oscura | `#4A3B28` | Texto principal |
| Alerta | `#E63946` | Grabando, errores críticos |
| Fondo | `#F5F0E8` | Superficie principal |

---

<div align="center">

---

<sub>Proyecto académico — Ciencia de Datos aplicada al agro · Valle del Yaqui, Sonora, México</sub>

<sub>Pre-MVP · Datos sintéticos intencionalmente · PostGIS OK · 4 Migraciones OK · 108+7 Tests OK · XGBoost entrenado OK · IForest entrenado OK · 6 Routers OK · Dashboard Operacional OK</sub>

</div>
