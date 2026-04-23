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
<strong>Meta principal:</strong> Reducir el consumo hídrico de <code>8,000 m³/ha/ciclo</code> a <code>6,000 m³/ha/ciclo</code>.
</blockquote>

</div>

---

## 📋 Tabla de Contenidos
- Arquitectura del sistema
- Stack tecnológico
- API Reference
- Asistente de voz

---

## 🏗️ Arquitectura del sistema

```mermaid
flowchart TB

    subgraph FRONTEND["FRONTEND (SPA)"]
        FE_TECH["HTML · Leaflet · Web Audio API"]

        subgraph FE_MODULES["Módulos"]
            BI["BI"]
            GIS["Mapas"]
            COST["Costos"]
            SETT["Ajustes"]
        end

        VOICE_UI["🎤 Voz"]
    end

    subgraph BACKEND["BACKEND (FastAPI)"]
        DB_API["CRUD"]
        RIEGO_API["FAO-56"]
        ANALYTICS_API["K-Means"]

        WHISPER["Whisper"]
        OLLAMA["LLM"]
        PARSER["Parser"]

        WHISPER --> OLLAMA --> PARSER
    end

    subgraph DB["DATABASE"]
        DB_ENGINE["PostgreSQL"]
    end

    FRONTEND --> BACKEND
    BACKEND --> DB
