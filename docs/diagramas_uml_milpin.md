# Diagramas UML — MILPÍN

## 1. Diagrama de Estados — Recomendación de Riego

```mermaid
stateDiagram-v2
    [*] --> pendiente : Motor FAO-56 genera recomendacion\n(riego_api.py INSERT recomendaciones)

    pendiente --> aceptada : POST /api/riego con id_recomendacion\n|lamina_real - lamina_rec| <= 2mm\n(db_api.py L305-311)
    pendiente --> modificada : POST /api/riego con id_recomendacion\n|lamina_real - lamina_rec| > 2mm\n(db_api.py L308-311)
    pendiente --> ignorada : PATCH /api/recomendaciones/{id}/feedback\naceptada = ignorada\n(db_api.py L371-395)
    pendiente --> aceptada : PATCH /api/recomendaciones/{id}/feedback\naceptada = aceptada

    aceptada --> [*]
    modificada --> [*]
    ignorada --> [*]
```

## 2. Diagrama de Casos de Uso

```mermaid
flowchart LR
    AGR([Agricultor])
    SYS([Sistema MILPIN])

    subgraph "Gestion de Parcelas"
        UC1(Crear parcela)
        UC2(Consultar parcela)
        UC3(Ver KPI hidrico\nvs baseline 8000 m3/ha)
    end

    subgraph "Riego"
        UC4(Registrar evento\nde riego)
        UC5(Consultar historial\nde riego)
        UC6(Dar feedback a\nrecomendacion)
    end

    subgraph "Motor Agronomico FAO-56"
        UC7(Calcular balance\nhidrico)
        UC8(Consultar curva Kc)
        UC9(Calculo manual\nlegacy)
    end

    subgraph "Analisis Espacial K-Means"
        UC10(Clustering\nlogistico)
        UC11(Zonas de\nmanejo)
    end

    subgraph "Voz"
        UC12(Enviar comando\npor voz)
    end

    subgraph "GIS"
        UC13(Ver mapa\ninteractivo Leaflet)
    end

    AGR --- UC1 & UC2 & UC3
    AGR --- UC4 & UC5 & UC6
    AGR --- UC7 & UC8 & UC9
    AGR --- UC10 & UC11
    AGR --- UC12
    AGR --- UC13

    SYS --- UC7
    SYS --- UC8

    UC12 -.-> UC7 : include
    UC12 -.-> UC13 : include
    UC7 -.-> UC6 : extend
    UC4 -.-> UC6 : extend
```

## 3. Diagrama de Procesos — Flujo de Riego Completo

```mermaid
flowchart TD
    A([Agricultor solicita\nbalance hidrico]) --> B{Parcela tiene\ncultivo asignado?}
    B -- No --> C([Error 400\nParcela en barbecho])
    B -- Si --> D[Leer cultivo de\ncultivos_catalogo\nobtener Kc por etapa]

    D --> E[Leer clima_diario\npara parcela y fecha]
    E --> F{Datos climaticos\ncompletos?}

    F -- "5 variables\n(tmax,tmin,HR,viento,rad)" --> G[Calcular ETo\nPenman-Monteith]
    F -- "Solo tmax + tmin" --> H[Calcular ETo\nHargreaves fallback]
    F -- "Sin datos" --> I([Error 404\nSin datos climaticos])

    G --> J[ETc = ETo x Kc]
    H --> J

    J --> K[Calcular balance hidrico\ndeficit, lamina bruta,\nvolumen m3/ha]
    K --> L[Calcular costo\nvolumen x tarifa 1.68 MXN/m3]
    L --> M[Consultar dias\nsin riego]
    M --> N{Deficit > 20mm?}

    N -- Si --> O[Urgencia: critico]
    N -- No --> P{Deficit > 8mm?}
    P -- Si --> Q[Urgencia: moderado]
    P -- No --> R[Urgencia: preventivo]

    O & Q & R --> S[INSERT recomendacion\nen BD con snapshot\nde parametros]

    S --> T([Retorna JSON\ncon recomendacion])

    T --> U{Agricultor\nresponde?}
    U -- "Riega segun\nrecomendacion" --> V[POST /api/riego\ncon id_recomendacion]
    U -- "Modifica lamina" --> V
    U -- "Ignora" --> W[PATCH feedback\naceptada = ignorada]

    V --> X{|lamina_real -\nlamina_rec| > 2mm?}
    X -- Si --> Y[Estado: modificada\nregistra lamina_ejecutada_mm]
    X -- No --> Z[Estado: aceptada]

    W & Y & Z --> AA([Fin del ciclo])
```

## 4. Diagrama de Componentes

```mermaid
flowchart TB
    subgraph "Frontend (HTML + Vanilla JS)"
        IDX[index.html\nSPA entry point]
        MAP[map_engine.js\nLeaflet 1.9.4\nEsri + OpenTopoMap]
        TABS[ui_tabs.js\nNavegacion tabs\nRecomendador BI fake]
        VOZC[voice_client.js\nWeb Speech API TTS\nGrabacion audio]
    end

    subgraph "Backend FastAPI (main.py)"
        direction TB
        subgraph "API Layer (4 routers)"
            DB_API[db_api.py\n12 endpoints CRUD\nusuarios parcelas\nriego recomendaciones\ncultivos]
            RIEGO_API[riego_api.py\n3 endpoints\nbalance_hidrico\nbalance_hidrico_manual\nkc/cultivo]
            VOZ_API[voice_endpoint.py\n1 endpoint\nPOST voice-command]
            ANAL_API[analytics_api.py\n2 endpoints\nlogistica_inteligente\nzonas_manejo]
        end

        subgraph "Core (logica de negocio)"
            BH[balance_hidrico.py\ncalcular_eto_penman_monteith\ncalcular_eto_hargreaves\ncalcular_balance_hidrico\nobtener_kc\ncalcular_costo_riego]
            LLM_ORC[llm_orchestrator.py\ninterpretar_comando_voz\nWhisper STT\nOllama NLU\nValidacion esquema]
            KMEANS[kmeans_model.py\nejecutar_clustering_logistico\nejecutar_clustering_terreno]
        end

        subgraph "Data Layer"
            MODELS[models.py\n7 modelos ORM\nUsuario Parcela\nCultivoCatalogo\nRecomendacion\nHistorialRiego\nCostoCiclo ClimaDiario]
            DATABASE[database.py\nSQLAlchemy async\nasyncpg prod\naiosqlite dev]
        end
    end

    subgraph "Servicios Externos"
        PG[(PostgreSQL\n7 tablas + 2 vistas KPI)]
        OLLAMA([Ollama Server\nllama3.2 latest])
        NASA[(NASA POWER API\nMERRA-2)]
    end

    subgraph "Tools (offline)"
        ETL[nasa_power_etl.py\nIngesta clima diario]
        GEO[geo_pipeline.py\ngeopandas + shapely\nmake_valid + Douglas-Peucker]
        SEED[init_db.py\nSeeders datos prueba]
        SYNTH[generar_datos_sinteticos.py]
    end

    IDX --> MAP & TABS & VOZC

    TABS -- "fetch /api/*" --> DB_API
    TABS -- "fetch /api/balance_hidrico" --> RIEGO_API
    MAP -- "fetch /api/logistica" --> ANAL_API
    VOZC -- "POST audio" --> VOZ_API

    DB_API --> MODELS
    RIEGO_API --> BH
    RIEGO_API --> MODELS
    VOZ_API --> LLM_ORC
    ANAL_API --> KMEANS

    MODELS --> DATABASE
    DATABASE --> PG
    LLM_ORC --> OLLAMA
    ETL --> NASA
    ETL --> PG
    GEO -. "GeoJSON" .-> MAP
    SEED --> PG
```
