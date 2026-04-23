<div align="center">

<img src="imagenes/icono.jpeg" alt="MILPÍN Logo" width="120" style="border-radius:50%"/>

<h1>🌾 MILPÍN AgTech</h1>
<h3>Sistema Inteligente de Optimización de Riego — Valle del Yaqui, DR-041</h3>

<p>
  <img src="https://img.shields.io/badge/versión-pp26--v.1-4CAF50?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15+-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
</p>

<p>
  <img src="https://img.shields.io/badge/Whisper-STT-FF6B6B?style=for-the-badge&logo=openai&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-LLM-7BB395?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Leaflet-GIS-199900?style=for-the-badge&logo=leaflet&logoColor=white"/>
  <img src="https://img.shields.io/badge/scikit--learn-ML-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white"/>
</p>

<blockquote>
<strong>Meta principal:</strong> Reducir el consumo hídrico de <code>8,000 m³/ha/ciclo</code> a <code>6,000 m³/ha/ciclo</code> — un ahorro del <strong>25%</strong> equivalente a ~$1.68 MXN/m³.
</blockquote>

</div>

---

## 📋 Tabla de Contenidos

- [¿Qué es MILPÍN?](#-qué-es-milpín)
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

---

## 🌱 ¿Qué es MILPÍN?

**MILPÍN** es un ERP agrícola inteligente diseñado para los productores del **Distrito de Riego DR-041 (Valle del Yaqui, Sonora, México)**. Combina modelos agronómicos científicos, inteligencia artificial local y visualización geoespacial para brindar recomendaciones de riego precisas, controlables por voz.

> El nombre honra a la **milpa**, el sistema agrícola ancestral mesoamericano, fusionándolo con tecnología de punta.

**Usuarios objetivo:** Productores, técnicos de campo y administradores del módulo DR-041.

---

## ✨ Características principales

<table>
<tr>
<td width="50%">

### 🧠 Inteligencia Agronómica
- Motor **FAO-56 Penman-Monteith** para cálculo de evapotranspiración
- Fallback **Hargreaves** cuando los datos son incompletos
- Interpolación de coeficientes **Kc** por etapa fenológica
- Balance hídrico completo del suelo

</td>
<td width="50%">

### 🗣️ Asistente de Voz IA
- Reconocimiento de voz local con **OpenAI Whisper**
- Razonamiento con **Ollama LLM** (llama3.2, sin nube)
- Clasificación de 6 intents en español
- Memoria conversacional de 3 turnos

</td>
</tr>
<tr>
<td width="50%">

### 🗺️ GIS Interactivo
- Mapa vectorial con **Leaflet.js**
- Capas: lotes, ríos, canales, pozos, límites
- Rampa de color por NDVI/rendimiento
- GeoJSON de parcelas del DR-041

</td>
<td width="50%">

### 📊 Machine Learning
- **K-Means** para optimización de logística de almacenamiento
- **K-Means** para zonas de manejo diferenciado en campo
- **Filtrado colaborativo** (similitud coseno) para recomendaciones de mercado

</td>
</tr>
</table>

---

## 🏗️ Arquitectura del sistema

```mermaid
flowchart TB

    subgraph FRONTEND["FRONTEND (SPA)"]
        direction TB
        FE_TECH["index.html · Leaflet.js · Web Audio API · Vanilla JS"]

        subgraph FE_MODULES["Módulos"]
            BI["BI/R"]
            GIS["Mapas GIS"]
            COST["Costos / Prescripción"]
            SETT["Ajustes"]
        end

        VOICE_UI["🎤 MILPÍN FAB"]
    end

    subgraph BACKEND["BACKEND (FastAPI)"]
        direction TB

        subgraph APIS["APIs"]
            DB_API["db_api.py\nCRUD"]
            RIEGO_API["riego_api.py\nFAO-56"]
            ANALYTICS_API["analytics_api.py\nK-Means Clustering"]
        end

        subgraph VOICE_PIPELINE["voice_endpoint.py"]
            WHISPER["Whisper (STT)"]
            OLLAMA["Ollama LLM"]
            PARSER["Intent Parser (JSON)"]

            WHISPER --> OLLAMA --> PARSER
        end
    end

    subgraph DB["DATABASE"]
        direction TB
        DB_ENGINE["PostgreSQL 15+ / SQLite (dev)"]

        subgraph TABLES["Tablas"]
            USERS["usuarios"]
            PARCELAS["parcelas"]
            CULTIVOS["cultivos_catalogo"]
            RECOM["recomendaciones"]
            HIST["historial_riego"]
        end
    end

    FRONTEND -->|"HTTP / REST"| BACKEND
    BACKEND -->|"SQLAlchemy Async"| DB

    VOICE_UI --> BACKEND
    DB_API --> DB_ENGINE
    RIEGO_API --> DB_ENGINE
    ANALYTICS_API --> DB_ENGINE


## 🛠️ Stack tecnológico

### Backend

| Tecnología | Versión | Rol |
|-----------|---------|-----|
| **FastAPI** | 0.115.0 | Framework REST asíncrono |
| **SQLAlchemy** | 2.0 | ORM asíncrono |
| **asyncpg** | 0.30.0 | Driver PostgreSQL async |
| **Uvicorn** | 0.30.6 | Servidor ASGI |
| **OpenAI Whisper** | 20240930 | Speech-to-Text local |
| **Ollama** | latest | LLM local (llama3.2) |
| **scikit-learn** | 1.5.2 | K-Means clustering |
| **numpy** | 1.26.4 | Cálculos numéricos |
| **Pydantic** | 2.9.2 | Validación de datos |
| **httpx** | 0.27.2 | Cliente HTTP async |

### Frontend

| Tecnología | Rol |
|-----------|-----|
| **HTML5 / CSS3** | SPA estructurada con sistema de diseño propio |
| **Vanilla JavaScript** | Lógica de tabs, voz, filtrado colaborativo |
| **Leaflet.js 1.9.4** | Motor GIS interactivo |
| **Web Audio API** | Captura de micrófono y streaming de audio |

---

## 📁 Estructura del proyecto

```
milpin-pp26-v.1/
│
├── 📂 backend/
│   ├── main.py                  ← Punto de entrada FastAPI, CORS, routers
│   ├── database.py              ← Engine async, SessionLocal factory
│   ├── models.py                ← 5 modelos ORM (usuarios, parcelas, etc.)
│   ├── schema.sql               ← DDL PostgreSQL con datos semilla
│   ├── init_db.py               ← Script de inicialización de BD
│   ├── requirements.txt         ← Dependencias Python
│   │
│   ├── 📂 API/
│   │   ├── analytics_api.py     ← K-Means: /logistica_inteligente, /zonas_manejo
│   │   ├── db_api.py            ← CRUD: usuarios, cultivos, parcelas, riego
│   │   ├── riego_api.py         ← FAO-56: /balance_hidrico
│   │   └── voice_endpoint.py   ← Voz: /voice-command (Whisper + Ollama)
│   │
│   └── 📂 core/
│       ├── balance_hidrico.py   ← Motor Penman-Monteith / Hargreaves
│       ├── kmeans_model.py      ← Wrapper K-Means scikit-learn
│       └── llm_orchestrator.py ← Pipeline STT → LLM → JSON intent
│
├── 📂 frontend/
│   ├── index.html               ← SPA principal (4 tabs + FAB de voz)
│   ├── 📂 css/
│   │   └── styles.css           ← Sistema de diseño tierra (#7BB395, #4A3B28)
│   ├── 📂 src/
│   │   ├── voice_client.js      ← Web Audio API, grabación, envío
│   │   ├── map_engine.js        ← Leaflet, capas GeoJSON, rampa de color
│   │   └── ui_tabs.js           ← Routing de tabs, filtrado colaborativo
│   └── 📂 data/
│       └── lotes.geojson        ← Geometrías de parcelas DR-041
│
├── 📂 imagenes/                 ← Recursos visuales
├── 📂 tools/
│   └── geo_pipeline.py          ← Utilidades de procesamiento geodatos
├── requirements.txt             ← Dependencias top-level
└── .gitignore
```

---

## 📡 API Reference

### Balance Hídrico FAO-56

```http
GET /api/balance_hidrico
```

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `parcela_id` | UUID | ID de la parcela |
| `cultivo` | string | Nombre del cultivo |
| `dias_siembra` | int | Días desde siembra |
| `tmax` / `tmin` | float | Temperatura máx/mín (°C) |
| `humedad_rel` | float | Humedad relativa (%) |
| `viento` | float | Velocidad del viento (m/s) |
| `radiacion` | float | Radiación solar (MJ/m²/día) |
| `precipitacion` | float | Precipitación (mm) |
| `humedad_suelo` | float | Humedad actual del suelo |
| `capacidad_campo` | float | Capacidad de campo (m³/m³) |
| `punto_marchitez` | float | Punto de marchitez (m³/m³) |
| `profundidad_raiz` | float | Profundidad radicular (cm) |

**Respuesta:** `ETo`, `Kc`, `ETc`, `déficit`, `lámina recomendada (mm)`, `volumen (m³/ha)`, `costo (MXN)`

---

### Comando de Voz

```http
POST /api/voice-command
Content-Type: multipart/form-data

audio_file: <blob WebM>
```

**Respuesta:**
```json
{
  "intent": "navegar",
  "target": "mapas",
  "message": "Abriendo el mapa de parcelas.",
  "parameters": {}
}
```

| Intent | Acción |
|--------|--------|
| `navegar` | Cambia de pestaña |
| `ejecutar_analisis` | Lanza análisis de clustering |
| `llenar_prescripcion` | Completa formulario de costos |
| `consultar` | Responde preguntas sobre datos |
| `saludo` | Saludo conversacional |
| `desconocido` | Solicita aclaración |

---

### Clustering ML

```http
GET /api/logistica_inteligente   # Optimización de bodegas
GET /api/zonas_manejo            # Zonas de manejo diferenciado
```

---

### CRUD Principal

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/usuarios` | POST | Registrar productor |
| `/api/usuarios/{id}` | GET | Obtener usuario con parcelas |
| `/api/cultivos` | GET | Catálogo de cultivos (FAO-56) |
| `/api/parcelas` | POST | Registrar parcela |
| `/api/parcelas/{id}/kpi` | GET | KPI hídrico vs. baseline |
| `/api/riego` | POST | Registrar evento de riego |
| `/api/recomendaciones/{id}/feedback` | PATCH | Retroalimentación del productor |
| `/health` | GET | Estado del servicio |

---

## 🗄️ Base de datos

### Modelos principales

```
usuarios ──< parcelas >── cultivos_catalogo
                │
                ├──< recomendaciones
                │
                └──< historial_riego
```

### Cultivos precargados (semilla FAO-56)

| Cultivo | Kc inicial | Kc medio | Kc final | Ky |
|---------|-----------|---------|---------|-----|
| Trigo | 0.40 | 1.15 | 0.25 | 1.05 |
| Cártamo | 0.35 | 1.10 | 0.35 | 0.80 |
| Garbanzo | 0.40 | 1.00 | 0.35 | 0.85 |
| Maíz | 0.30 | 1.20 | 0.60 | 1.25 |
| Algodón | 0.35 | 1.20 | 0.70 | 0.85 |

### KPI de consumo hídrico

```sql
-- Vista v_kpi_consumo
SELECT
    nombre_parcela,
    volumen_total_m3_ha,
    8000 AS baseline_dr041_m3_ha,
    ROUND((1 - volumen_total_m3_ha / 8000.0) * 100, 2) AS ahorro_pct,
    (8000 - volumen_total_m3_ha) * area_ha * 1.68 AS ahorro_estimado_mxn
FROM v_kpi_consumo;
```

---

## 🚀 Instalación y uso

### Requisitos previos

- Python 3.12+
- PostgreSQL 15+ (o SQLite para desarrollo)
- [Ollama](https://ollama.ai) con el modelo `llama3.2` descargado
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
cp .env.example .env
# Editar .env con tu DATABASE_URL y configuración de Ollama

# 4. Inicializar la base de datos
python backend/init_db.py

# 5. Iniciar el servidor
uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
# Abrir directamente en el navegador
# (no requiere build, es HTML/JS puro)
open frontend/index.html

# O servir con live-server (recomendado para desarrollo)
npx live-server frontend --port=5500
```

### Variables de entorno

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/milpin
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest
```

---

## 🌐 Frontend (SPA)

La interfaz es una **Single Page Application** con 4 pestañas y un botón flotante de voz.

| Pestaña | Descripción |
|---------|-------------|
| **BI/R** | Inteligencia de mercado con filtrado colaborativo por similitud coseno |
| **Mapas** | Portal GIS con capas vectoriales de parcelas, ríos, canales y pozos |
| **Costos** | Prescripción de fertilización por zona de productividad |
| **Ajustes** | Configuración de voz, notificaciones y preferencias |

El **FAB (Floating Action Button)** 🎤 activa el asistente de voz MILPÍN en cualquier pestaña.

**Paleta de diseño:**

| Color | Hex | Uso |
|-------|-----|-----|
| Verde primario | `#7BB395` | Botones, acentos, activo |
| Tierra oscura | `#4A3B28` | Texto principal |
| Alerta | `#E63946` | Grabando, errores críticos |
| Fondo | `#F5F0E8` | Superficie principal |

---

## 🧮 Motor FAO-56

El corazón agronómico de MILPÍN implementa la **metodología FAO-56 Penman-Monteith** completa:

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

**Parámetros locales por defecto:**
- Latitud: 27.37°N (Cajeme, Valle del Yaqui)
- Altitud: 40 m (Cd. Obregón)
- Tarifa energética: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m)

---

## 🗣️ Asistente de voz MILPÍN AI

flowchart LR
    USER["Usuario"] --> AUDIO["Web Audio API"]
    AUDIO --> ENDPOINT["/voice-command"]
    ENDPOINT --> WHISPER["Whisper STT"]
    WHISPER --> TEXT["Texto"]
    TEXT --> OLLAMA["LLM"]
    OLLAMA --> PARSER["Intent Parser"]
    PARSER --> UI["Acción UI"]
    PARSER --> PARAMS["Parámetros"]

**Memoria conversacional:** Los últimos 3 turnos (6 mensajes) se mantienen en contexto para comandos encadenados como:
> *"Ve a mapas"* → *"Ahora ejecuta el clustering"* → *"¿Cuántos clusters encontró?"*

---

<div align="center">

---

<sub>Desarrollado para el Distrito de Riego DR-041 · Valle del Yaqui, Sonora, México</sub>

<sub>⚠️ MVP v1.0 — Fase 2 incluirá integración PostGIS y modelos de predicción climática</sub>

</div>
