<div align="center">
<img src="imagenes/icono.jpeg" alt="MILPÍN Logo" width="120" style="border-radius:50%"/>
<h1>🌾 MILPÍN AgTech</h1>
<h3>Sistema Inteligente de Optimización de Riego — Valle del Yaqui, DR-041</h3>
<p>
  <img src="https://img.shields.io/badge/estado-pre--MVP-orange?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15+-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
</p>
<p>
  <img src="https://img.shields.io/badge/PostGIS-3.6-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Whisper-STT-FF6B6B?style=for-the-badge&logo=openai&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-LLM-7BB395?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Leaflet-GIS-199900?style=for-the-badge&logo=leaflet&logoColor=white"/>
  <img src="https://img.shields.io/badge/scikit--learn-ML-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white"/>
</p>
<p>
  <img src="https://img.shields.io/badge/tests-83%20passing-4CAF50?style=for-the-badge&logo=pytest&logoColor=white"/>
  <img src="https://img.shields.io/badge/Alembic-migraciones%20activas-blueviolet?style=for-the-badge"/>
</p>
<blockquote>
<strong>Meta principal:</strong> Reducir el consumo hídrico de <code>8,000 m³/ha/ciclo</code> a <code>6,000 m³/ha/ciclo</code> — un ahorro del <strong>25%</strong> equivalente a ~$1.68 MXN/m³ (tarifa CFE 9-CU, bombeo 80 m).
</blockquote>
</div>

---

## Tabla de Contenidos

- [¿Qué es MILPÍN?](#-qué-es-milpín)
- [Estado del proyecto](#-estado-del-proyecto)
- [Deuda técnica vigente](#-deuda-técnica-vigente)
- [Características principales](#-características-principales)
- [Arquitectura del sistema](#-arquitectura-del-sistema)
- [Stack tecnológico](#-stack-tecnológico)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [API Reference](#-api-reference)
- [Base de datos](#-base-de-datos)
- [Instalación y uso](#-instalación-y-uso)
- [Frontend (SPA)](#-frontend-spa)
- [Motor FAO-56](#-motor-fao-56)
- [Asistente de voz MILPÍN AI](#-asistente-de-voz-milpín-ai)
- [Roadmap de interfaz](#️-roadmap-de-interfaz)

---

## ¿Qué es MILPÍN?

**MILPÍN** es un DDS (Decision Support System) agrícola inteligente diseñado para los productores del **Distrito de Riego DR-041 (Valle del Yaqui, Sonora, México)**. Combina modelos agronómicos científicos, inteligencia artificial local y visualización geoespacial para brindar recomendaciones de riego precisas, controlables por voz.

> El nombre honra a la **milpa**, el sistema agrícola ancestral mesoamericano, fusionándolo con tecnología de punta.

**Usuarios objetivo:** Productores, técnicos de campo y administradores del módulo DR-041.

---

##  Estado del proyecto

**Fase actual: Pre-MVP — core técnico sólido, bloqueador único: autenticación**

### ✔ Implementado y funcionando

| Componente | Detalle | Fecha |
|---|---|---|
| Backend FastAPI 2.0 | Lifespan, 4 routers, SQLAlchemy 2.0 async | — |
| PostgreSQL 15 + **PostGIS 3.6** | `parcelas.geom` es `GEOMETRY(Polygon,4326)` con índice GIST. Migrado desde JSONB vía Alembic `0001_postgis_geom_jsonb_to_geometry`. | 2026-04-30 |
| 7 modelos ORM, 14 endpoints CRUD | 2 vistas KPI, seeders, `schema.sql` | — |
| `GET /api/parcelas/geojson` | GeoJSON FeatureCollection listo para Leaflet, servido desde PostGIS | 2026-04-30 |
| Motor agronómico FAO-56 | Penman-Monteith (`balance_hidrico.py`), Hargreaves como fallback. Conectado a BD: lee parcela + cultivo + clima, persiste en `recomendaciones`. | — |
| **Alembic activo** | `backend/migrations/` + `alembic.ini`. Próximas migraciones con `alembic revision -m "descripcion"` + `alembic upgrade head`. | 2026-04-30 |
| **83 tests** | 51 unitarios FAO-56/propagación (`test_fao56_unit.py`) + 32 e2e con SQLite/aiosqlite (`test_riego_e2e.py`). Ejecutar con `pytest backend/tests/`. | 2026-05-06 |
| **Loop recomendación→feedback completo** | `PATCH /recomendaciones/{id}/feedback` actualiza estado y auto-inserta en `historial_riego` cuando `aceptada` es `"aceptada"` o `"modificada"`. Verificado con `TestFeedbackLoop` (7 casos). | 2026-05-01 |
| **Humedad inicial real** | `propagar_balance_hidrico()` en `balance_hidrico.py` reemplaza la estimación `(CC+PMP)/2` con un balance acumulado día a día desde el último riego real. Conectado en `riego_api.py` y `db_api.py`. 9 tests en `TestPropagar`. | 2026-05-06 |
| **Dashboard BI real** | `frontend/src/bi_dashboard.js` reemplaza el tab BI (que usaba cosine similarity hardcoded) por un dashboard conectado a la API real. Cosine similarity sobre matriz estática eliminado de `ui_tabs.js`. | 2026-05-06 |
| **Forecast ETo 7 días** | `backend/core/eto_forecast.py`: Ridge Regression sobre `clima_diario` (features: sin/cos doy, lags ETo, T_max). Fallback a media(14 d) si < 60 registros. Endpoint `GET /api/parcelas/{id}/forecast?dias_siembra=N&horizon=7` proyecta déficit diario. Tab Riego muestra sección "Proyección 7 días". | 2026-05-06 |
| **Vista de carga de trabajo técnica** | `GET /api/tecnico/carga-trabajo` agrega todas las parcelas activas con su última recomendación pendiente, ordenadas por urgencia (`critico → moderado → preventivo → sin_recomendacion`). Frontend: nuevo módulo `tecnico_workload.js` con KPI row, filtros por urgencia y tarjetas por parcela. Acceso: Admin Panel → Carga de trabajo · Riego. | 2026-05-18 |
| Pipeline de voz | Whisper STT **carga lazy** (startup ~2 s vs. ~45 s anterior) → Ollama `llama3.2:latest` → Web Speech API TTS | 2026-04-30 |
| Clustering K-Means | scikit-learn 1.5, zonas de manejo y logística | — |
| Frontend GIS | Vanilla JS + Leaflet 1.9.4, capas Esri World Imagery + OpenTopoMap. `map_engine.js` carga parcelas desde API PostGIS (fallback: `lotes.geojson` estático). | — |
| Pipeline GIS | geopandas + shapely `make_valid` + Douglas-Peucker | — |

---

##  Características principales

<table>
<tr>
<td width="50%">

### Inteligencia Agronómica

- Motor **FAO-56 Penman-Monteith** para cálculo de evapotranspiración
- Fallback **Hargreaves** cuando los datos son incompletos
- Interpolación de coeficientes **Kc** por etapa fenológica
- Balance hídrico completo del suelo
- Resultados **persistidos en BD** con feedback del agricultor

</td>
<td width="50%">

### Asistente de Voz IA

- STT doble: **Web Speech API** (browser, sin latencia de red) vía `/api/text-command` + **Whisper** (fallback local, carga lazy)
- Razonamiento con **Ollama** (local, sin internet) o **Groq** (nube, rápido)
- Clasificación de 6 intents en español
- Memoria conversacional de 3 turnos

</td>
</tr>
<tr>
<td width="50%">

### GIS Interactivo

- Mapa vectorial con **Leaflet.js**
- Geometrías desde **PostGIS** vía `GET /api/parcelas/geojson`
- Capas: lotes, ríos, canales, pozos, límites
- Rampa de color por NDVI/rendimiento
- Fallback estático a `lotes.geojson`

</td>
<td width="50%">

### Machine Learning

- **K-Means** para optimización de logística de almacenamiento
- **K-Means** para zonas de manejo diferenciado en campo
- **Ridge Regression** para forecast de ETo a 7 días (`eto_forecast.py`) con features estacionales + lags
- **Dashboard BI** conectado a API real — cosine similarity hardcoded eliminado
- **83 tests** automatizados (pytest)

</td>
</tr>
</table>

---

## Arquitectura del sistema

```mermaid
flowchart TB
    subgraph FRONTEND["FRONTEND (SPA)"]
        direction TB
        FE_TECH["index.html · Leaflet.js · Web Audio API · Vanilla JS"]
        subgraph FE_MODULES["Módulos"]
            BI["BI/R"]
            GIS["Mapas GIS"]
            RIEGO["Riego FAO-56"]
            SETT["Ajustes"]
        end
        VOICE_UI["🎤 MILPÍN FAB"]
    end

    subgraph BACKEND["BACKEND (FastAPI)"]
        direction TB
        subgraph APIS["APIs"]
            DB_API["db_api.py\nCRUD 14 endpoints"]
            RIEGO_API["riego_api.py\nFAO-56 + /geojson"]
            ANALYTICS_API["analytics_api.py\nK-Means Clustering"]
        end
        subgraph VOICE_PIPELINE["voice_endpoint.py"]
            TEXT_CMD["text-command\n(principal)"]
            WHISPER["Whisper STT\n(fallback, lazy)"]
            OLLAMA["Ollama LLM"]
            PARSER["Intent Parser (JSON)"]
            TEXT_CMD --> OLLAMA
            WHISPER --> OLLAMA
            OLLAMA --> PARSER
        end
    end

    subgraph DB["DATABASE"]
        direction TB
        DB_ENGINE["PostgreSQL 15 + PostGIS 3.6"]
        subgraph TABLES["Tablas"]
            USERS["usuarios"]
            PARCELAS["parcelas\n(geom GEOMETRY Polygon 4326)"]
            CULTIVOS["cultivos_catalogo"]
            RECOM["recomendaciones"]
            HIST["historial_riego"]
            COSTOS["costos_ciclo"]
            CLIMA["clima_diario"]
        end
        subgraph VIEWS["Vistas"]
            V_AGUA["v_agua_disponible"]
            V_KPI["v_kpi_consumo"]
        end
    end

    FRONTEND -->|"HTTP / REST"| BACKEND
    BACKEND -->|"SQLAlchemy Async + asyncpg"| DB
    VOICE_UI --> BACKEND
    DB_API --> DB_ENGINE
    RIEGO_API --> DB_ENGINE
    ANALYTICS_API --> DB_ENGINE
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
| **Alembic** | latest | Migraciones de schema |
| **GeoAlchemy2** | latest | Tipos PostGIS en ORM |
| **Uvicorn** | 0.30.6 | Servidor ASGI |
| **OpenAI Whisper** | 20240930 | STT local — carga **lazy**, solo en primer request de audio |
| **Web Speech API** | Browser | STT nativo en cliente — path principal (sin latencia de red) |
| **Ollama** | latest | LLM local (`llama3.2:latest`, sin internet) |
| **Groq** | cloud | LLM cloud alternativo (alta velocidad) |
| **scikit-learn** | 1.5.2 | K-Means clustering |
| **numpy** | 1.26.4 | Cálculos numéricos |
| **pandas** | 2.2.3 | DataFrames para ETL |
| **geopandas + shapely** | 2.0.6 | Pipeline GIS (`make_valid`, Douglas-Peucker) |
| **Pydantic** | 2.9.2 | Validación de datos |
| **pytest / pytest-asyncio** | latest | 77 tests (42 unitarios + 35 e2e) |

### Frontend

| Tecnología | Rol |
|---|---|
| **HTML5 / CSS3** | SPA estructurada con sistema de diseño propio |
| **JavaScript** | Lógica de tabs, voz, filtrado colaborativo |
| **Leaflet.js 1.9.4** | Motor GIS interactivo — carga desde API PostGIS |
| **Web Audio API** | Captura de micrófono y streaming de audio (fallback voz) |

**Reglas duras:** no introducir React/Vue/Angular. No reemplazar FastAPI por Django/Flask. No agregar dependencias sin justificación explícita contra el stack actual.

---

## 📁 Estructura del proyecto

```text
├── backend/                          # Sin cambios mayores
│   ├── main.py                       # app FastAPI 2.0 con lifespan
│   ├── .env                          # ⚠ contiene secretos, rotar
│   ├── schema.sql                    # DDL + 2 vistas KPI + seed
│   ├── init_db.py                    # seeders
│   ├── models.py                     # modelos ORM
│   ├── database.py                   # IS_SQLITE flag para fallback dev
│   ├── settings.py
│   ├── migrations/                   # Alembic activo desde 2026-04-30
│   ├── tests/                        # 77+ tests (FAO-56 unitarios + e2e)
│   ├── API/
│   │   ├── riego_api.py              # endpoint FAO-56
│   │   ├── voice_endpoint.py         # ⚠ path traversal sin sanitizar
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
│   ├── pipelines/                    # Prefect flows (stubs, Fase C/D)
│   │   ├── nasa_power_daily.py
│   │   ├── features_materialize.py
│   │   ├── train_eval_promote.py
│   │   └── batch_scoring.py
│   ├── models/                       # Solo metadata (apunta a MLflow registry)
│   │   └── README.md
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

## API Reference

### GIS

```http
GET /api/parcelas/geojson
```

Devuelve una **GeoJSON FeatureCollection** con todas las parcelas activas, generada directamente desde PostGIS. `map_engine.js` consume este endpoint; si falla, cae al archivo estático `lotes.geojson`.

---

### Balance Hídrico FAO-56 (principal — lee de BD, persiste)

```http
GET /api/balance_hidrico?parcela_id=<uuid>&dias_siembra=<int>&fecha=<YYYY-MM-DD>
```

Lee datos edáficos de `parcelas`, cultivo de `cultivos_catalogo` y clima de `clima_diario`. Calcula ETo (Penman-Monteith o Hargreaves fallback), ETc y balance hídrico completo, y **persiste el resultado en `recomendaciones`** antes de responder.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `parcela_id` | UUID | ID de la parcela — lee edáfica, cultivo y clima de BD |
| `dias_siembra` | int | Días desde siembra (determina etapa fenológica y Kc) |
| `fecha` | date | Fecha de cálculo (default: hoy) |

**Respuesta incluye:** `id_recomendacion`, `eto_mm`, `kc`, `etc_mm`, `balance` (déficit, lámina, volumen), `costo`, `dias_sin_riego`, `nivel_urgencia` (`critico` / `moderado` / `preventivo`), `persistido: true`.

---

### Curvas Kc por cultivo

```http
GET /api/kc/{cultivo}
```

Devuelve coeficientes Kc y duración de etapas fenológicas para un cultivo del catálogo.

---

### Forecast ETo 7 días (Ridge Regression)

```http
GET /api/parcelas/{id}/forecast?dias_siembra=<int>&horizon=7
```

Proyecta ETo para los próximos `horizon` días usando Ridge Regression entrenada sobre `clima_diario` (features: sin/cos del día del año, lags de ETo, T_max). Si la parcela tiene menos de 60 registros con ETo no nulo, el modelo cae automáticamente a la media de los últimos 14 días. Corre FAO-56 forward sobre la proyección y estima la **fecha del próximo riego** (±días). La sección "Proyección 7 días" del tab Riego consume este endpoint.

---

### Carga de trabajo técnica

```http
GET /api/tecnico/carga-trabajo?id_usuario=<uuid>
```

Agrega todas las parcelas activas con su última recomendación pendiente, ordenadas por urgencia. Diseñado para la vista de operaciones de riego del técnico de campo.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `id_usuario` | UUID (opcional) | Filtra por propietario. Sin filtro devuelve todas las parcelas del sistema. |

**Respuesta:**

```json
{
  "fecha_consulta": "2026-05-18",
  "resumen": { "total": 12, "critico": 2, "moderado": 5, "preventivo": 4, "sin_recomendacion": 1 },
  "parcelas": [
    {
      "id_parcela": "...",
      "nombre_parcela": "Lote Norte",
      "propietario": "Ramón Valenzuela Torres",
      "cultivo": "Maíz",
      "area_ha": 5.2,
      "sistema_riego": "gravedad",
      "nivel_urgencia": "critico",
      "dias_sin_riego": 12,
      "deficit_acumulado_mm": 45.2,
      "lamina_recomendada_mm": 80.0,
      "fecha_riego_sugerida": "2026-05-18",
      "id_recomendacion": "..."
    }
  ]
}
```

---

### Balance Hídrico manual (legacy — sin BD)

```http
GET /api/balance_hidrico_manual?parcela_id=...&cultivo=...&tmax=...&tmin=...&...
```

Recibe todos los parámetros por query string. No lee de BD ni persiste. Útil para pruebas rápidas.

---

### Comandos de Voz

```http
POST /api/text-command    # PRINCIPAL — texto del Web Speech API → LLM (sin audio)
POST /api/voice-command   # FALLBACK — audio WebM → Whisper STT → LLM
```

`/text-command` es el path principal: el navegador transcribe localmente con Web Speech API y solo envía texto al servidor, eliminando el round-trip de audio y la latencia de Whisper.

**Respuesta de ambos endpoints:**

```json
{
  "intent": "navegar",
  "target": "mapas",
  "message": "Abriendo el mapa de parcelas.",
  "parameters": {}
}
```

| Intent | Acción |
|---|---|
| `navegar` | Cambia de pestaña |
| `ejecutar_analisis` | Lanza análisis de clustering |
| `llenar_prescripcion` | Completa formulario de costos |
| `consultar` | Responde preguntas sobre datos |
| `saludo` | Saludo conversacional |
| `desconocido` | Solicita aclaración |

> **⚠ Seguridad:** `voice-command` no sanitiza el nombre del archivo (path traversal). Sin límite de tamaño ni validación de content-type — deuda técnica pendiente.

---

### Clustering ML

```http
GET /api/logistica_inteligente   # Optimización de bodegas
GET /api/zonas_manejo            # Zonas de manejo diferenciado
```

---

### CRUD Principal

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/usuarios` | POST | Crear usuario |
| `/api/usuarios/{id}` | GET | Obtener usuario con sus parcelas |
| `/api/cultivos` | GET | Listar catálogo de cultivos |
| `/api/cultivos/{id}` | GET | Obtener cultivo por ID |
| `/api/parcelas` | POST | Crear parcela |
| `/api/parcelas` | GET | Listar todas las parcelas activas |
| `/api/parcelas/{id}` | GET | Obtener parcela con historial reciente |
| `/api/parcelas/{id}/kpi` | GET | KPI de consumo vs. baseline DR-041 |
| `/api/parcelas/geojson` | GET | GeoJSON FeatureCollection para Leaflet |
| `/api/parcelas/{id}/forecast` | GET | Forecast ETo 7 días + fecha estimada de próximo riego |
| `/api/riego` | POST | Registrar evento de riego |
| `/api/riego/parcela/{id}` | GET | Historial de riego de una parcela |
| `/api/recomendaciones` | POST | Guardar recomendación del motor FAO-56 |
| `/api/recomendaciones/{id}` | GET | Obtener recomendación por ID |
| `/api/recomendaciones/{id}/feedback` | PATCH | Feedback del agricultor (aceptada/rechazada/modificada) |
| `/api/costos` | POST | Registrar costos de un ciclo agrícola |
| `/api/costos/parcela/{id}` | GET | Costos por ciclo de una parcela |
| `/api/tecnico/carga-trabajo` | GET | Parcelas ordenadas por urgencia de riego para técnicos |
| `/health` | GET | Estado del servicio |

---

## Base de datos

### Esquema completo (7 tablas + 2 vistas)

```mermaid
erDiagram
    USUARIOS ||--o{ PARCELAS : tiene
    CULTIVOS_CATALOGO ||--o{ PARCELAS : define
    PARCELAS ||--o{ RECOMENDACIONES : genera
    PARCELAS ||--o{ HISTORIAL_RIEGO : registra
    PARCELAS ||--o{ COSTOS_CICLO : acumula
    PARCELAS ||--o{ CLIMA_DIARIO : registra
    RECOMENDACIONES ||--o| HISTORIAL_RIEGO : origina
    CULTIVOS_CATALOGO ||--o{ RECOMENDACIONES : referencia
```

| Tabla | Descripción |
|---|---|
| `usuarios` | Agricultores, técnicos y administradores |
| `cultivos_catalogo` | Parámetros FAO-56 (Kc) y FAO-33 (Ky) por especie |
| `parcelas` | Lotes con atributos edáficos. `geom` es `GEOMETRY(Polygon,4326)` con índice GIST |
| `recomendaciones` | Recomendaciones del motor FAO-56 con estado de feedback del agricultor |
| `historial_riego` | Eventos de riego ejecutados — fuente del KPI de consumo |
| `costos_ciclo` | Resumen económico por parcela y ciclo agrícola |
| `clima_diario` | Series climáticas diarias por parcela (fuente: NASA POWER) |

| Vista | Descripción |
|---|---|
| `v_agua_disponible` | ADT (mm) = (CC - PMP) × profundidad_raiz × 10 |
| `v_kpi_consumo` | Consumo anual por parcela vs. baseline DR-041 (8,000 m³/ha) |

> `backend/models.py` es la fuente de verdad del schema en runtime. `backend/schema.sql` está desalineado (aún documenta la fase JSONB; el runtime ya usa GeoAlchemy2).

### Migraciones Alembic

```bash
cd backend
alembic upgrade head                          # aplica todas las migraciones
alembic revision -m "descripcion_cambio"      # crea nueva migración
```

Migración activa: `0001_postgis_geom_jsonb_to_geometry` — convierte `parcelas.geom` de JSONB a `GEOMETRY(Polygon,4326)` y crea índice GIST.

### Cultivos precargados (semilla FAO-56)

| Cultivo | Kc inicial | Kc medio | Kc final | Ky |
|---|---|---|---|---|
| Maíz | 0.30 | 1.20 | 0.60 | 1.25 |
| Frijol | 0.40 | 1.15 | 0.35 | 1.15 |
| Algodón | 0.35 | 1.20 | 0.70 | 0.85 |
| Uva | 0.30 | 0.85 | 0.45 | 0.85 |
| Chile | 0.60 | 1.05 | 0.90 | 1.10 |

> **Nota:** Uva y Chile son cultivos de alto valor pero no dominantes en el DR-041 real (donde predominan trigo, cártamo, garbanzo). El catálogo puede necesitar revisión si el proyecto se valida con agricultores reales.

### KPI de consumo hídrico

```sql
-- Vista v_kpi_consumo (schema.sql)
SELECT
    p.id_parcela,
    p.nombre_parcela,
    EXTRACT(YEAR FROM h.fecha_riego)::INT              AS anno,
    ROUND(SUM(h.volumen_m3_ha), 2)                     AS volumen_total_m3_ha,
    8000.0                                              AS baseline_dr041_m3_ha,
    ROUND((1.0 - SUM(h.volumen_m3_ha) / 8000.0) * 100, 2) AS ahorro_pct,
    ROUND((8000.0 - SUM(h.volumen_m3_ha)) * 1.68, 2)  AS ahorro_estimado_mxn
FROM historial_riego h
JOIN parcelas p ON p.id_parcela = h.id_parcela
GROUP BY p.id_parcela, p.nombre_parcela, EXTRACT(YEAR FROM h.fecha_riego);
```

---

## Instalación y uso

### Requisitos previos

- Python 3.12+
- PostgreSQL 15+ con extensión **PostGIS 3.6**
- Ollama con el modelo `llama3.2:latest` descargado (`ollama pull llama3.2:latest`)
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
# ⚠ Asegurarse de que .env esté en .gitignore

# 4. Inicializar la base de datos
python backend/init_db.py            # Crea tablas + seed
python backend/init_db.py --reset    # DROP + CREATE + seed (destructivo)
python backend/init_db.py --check    # Solo verifica conexión

# 5. Aplicar migraciones Alembic
cd backend && alembic upgrade head

# 6. Iniciar el servidor
uvicorn backend.main:app --reload --port 8000
```

### Tests

```bash
pytest backend/tests/                    # todos los tests
pytest backend/tests/test_fao56_unit.py  # solo unitarios FAO-56
pytest backend/tests/test_riego_e2e.py   # solo e2e
```

Los tests e2e usan SQLite con `aiosqlite` como backend — no mockean la BD.

### Frontend

```bash
# No requiere build — abrir directamente
open frontend/index.html

# O servir con live-server para desarrollo
npx live-server frontend --port=5500
```

### Variables de entorno (`backend/.env`)

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/milpin_mvp
MILPIN_OLLAMA_URL=http://localhost:11434/api/chat
MILPIN_OLLAMA_MODEL=llama3.2:latest
GROQ_API_KEY=                     # opcional — LLM cloud alternativo
```

> **⚠ Seguridad:** rotar las credenciales y agregar `.env` al `.gitignore` antes de cualquier push a repositorio no privado.

---

## Frontend (SPA)

La interfaz es una **Single Page Application** con 4 pestañas principales, sub-vistas de administración y un botón flotante de voz.

| Pestaña | Descripción | Estado |
|---|---|---|
| **BI/R** | Dashboard de inteligencia de negocio conectado a API real (`bi_dashboard.js`) | Funcional |
| **Mapas** | Portal GIS con capas vectoriales desde PostGIS, ríos, canales y pozos | Funcional |
| **Riego** | Recomendación FAO-56 por parcela, historial, feedback y proyección 7 días | Funcional |
| **Ajustes** | Configuración de voz, notificaciones y preferencias | Funcional |
| **Panel Admin** *(sub-vista)* | Vista global de todas las parcelas — solo para `rol=admin` | Funcional |
| **Carga de Trabajo** *(sub-vista)* | Parcelas ordenadas por urgencia de riego con KPIs, filtros y acceso directo — accesible desde Panel Admin | Funcional |

El **FAB (Floating Action Button)** 🎤 activa el asistente de voz MILPÍN en cualquier pestaña.

**Paleta de diseño:**

| Color | Hex | Uso |
|---|---|---|
| Verde primario | `#7BB395` | Botones, acentos, estado activo |
| Tierra oscura | `#4A3B28` | Texto principal |
| Alerta | `#E63946` | Grabando, errores críticos |
| Fondo | `#F5F0E8` | Superficie principal |

---

## Motor FAO-56

El corazón agronómico de MILPÍN implementa la **metodología FAO-56 Penman-Monteith** completa (Allen et al., 1998):

```
ETo = [0.408·Δ·(Rn - G) + γ·(900/(T+273))·u₂·(es - ea)]
      ─────────────────────────────────────────────────────
                    [Δ + γ·(1 + 0.34·u₂)]
```

**Donde:**
- `ETo` = Evapotranspiración de referencia (mm/día)
- `Δ` = Pendiente de la curva de presión de vapor
- `Rn` = Radiación neta en la superficie del cultivo
- `γ` = Constante psicrométrica
- `u₂` = Velocidad del viento a 2 m
- `es - ea` = Déficit de presión de vapor

Si los datos de radiación o humedad son insuficientes, el motor cae a **Hargreaves** como fallback.

**Parámetros locales por defecto:**
- Latitud: 27.37°N (Cajeme, Valle del Yaqui)
- Altitud: 40 m (Cd. Obregón)
- Tarifa energética: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m)

**Catálogo de cultivos soportados:** Maíz, Frijol, Algodón, Uva, Chile — con coeficientes Kc y duración de etapas fenológicas definidos en `balance_hidrico.py::KC_TABLE`.

> **Deuda estructural:** `KC_TABLE` y `VALID_CULTIVOS` están duplicados en 6 archivos. La fuente de verdad debería ser la tabla `cultivos_catalogo` leída en runtime.

---
