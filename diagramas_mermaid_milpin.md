# Diagramas UML — MILPÍN

## 1. DER

```mermaid
erDiagram
    usuarios ||--o{ parcelas : "posee"
    cultivos_catalogo ||--o{ parcelas : "cultivo_actual"
    cultivos_catalogo ||--o{ recomendaciones : "Kc"
    parcelas ||--o{ recomendaciones : "genera"
    parcelas ||--o{ historial_riego : "registra"
    parcelas ||--o{ costos_ciclo : "resume"
    parcelas ||--o{ clima_diario : "serie"
    recomendaciones ||--o{ historial_riego : "origina"

    usuarios {
        uuid id_usuario PK
        string nombre_completo
        string email UK
        string telefono
        string modulo_dr041
        bool activo
        datetime created_at
    }

    cultivos_catalogo {
        uuid id_cultivo PK
        string nombre_comun
        string nombre_cientifico
        numeric kc_inicial
        numeric kc_medio
        numeric kc_final
        numeric ky_total
        int dias_etapa_inicial
        int dias_etapa_desarrollo
        int dias_etapa_media
        int dias_etapa_final
        numeric rendimiento_potencial_ton
    }

    parcelas {
        uuid id_parcela PK
        uuid id_usuario FK
        uuid id_cultivo_actual FK
        string nombre_parcela
        jsonb geom
        numeric area_ha
        string tipo_suelo
        numeric conductividad_electrica
        int profundidad_raiz_cm
        numeric capacidad_campo
        numeric punto_marchitez
        string sistema_riego
        bool activo
    }

    recomendaciones {
        uuid id_recomendacion PK
        uuid id_parcela FK
        uuid id_cultivo FK
        datetime fecha_generacion
        date fecha_riego_sugerida
        numeric lamina_recomendada_mm
        numeric eto_referencia
        numeric etc_calculada
        numeric deficit_acumulado_mm
        int dias_sin_riego
        string nivel_urgencia
        string algoritmo_version
        string aceptada
        numeric lamina_ejecutada_mm
        jsonb parametros_json
    }

    historial_riego {
        uuid id_riego PK
        uuid id_parcela FK
        uuid id_recomendacion FK
        date fecha_riego
        numeric volumen_m3_ha
        numeric lamina_mm
        numeric duracion_horas
        string metodo_riego
        string origen_decision
        numeric costo_energia_mxn
        text observaciones
    }

    costos_ciclo {
        uuid id_costo PK
        uuid id_parcela FK
        string ciclo_agricola
        string cultivo
        numeric volumen_agua_total_m3
        numeric costo_agua_mxn
        numeric costo_fertilizantes_mxn
        numeric costo_agroquimicos_mxn
        numeric costo_semilla_mxn
        numeric costo_maquinaria_mxn
        numeric costo_mano_obra_mxn
        numeric ingreso_estimado_mxn
        numeric margen_contribucion_mxn
    }

    clima_diario {
        uuid id_parcela PK_FK
        date fecha PK
        numeric t_max
        numeric t_min
        numeric humedad_rel
        numeric viento
        numeric radiacion
        numeric lluvia
        numeric et0
    }
```

## 2. DFD (Nivel 0 y Nivel 1)

```mermaid
flowchart LR
    A([Agricultor]) -- "voz / HTTP / UI" --> M[MILPIN Backend\nFastAPI]
    N[(NASA POWER)] -- "clima diario" --> M
    O([Ollama LLM]) -- "intent JSON" --> M
    M -- "recomendaciones\nmapas / KPIs" --> A
```

```mermaid
flowchart TB
    subgraph Frontend
        UI[ui_tabs.js]
        MAP[map_engine.js\nLeaflet]
        VC[voice_client.js]
    end

    subgraph "Backend FastAPI"
        DB_API[db_api.py\n12 endpoints CRUD]
        RIEGO[riego_api.py\nFAO-56]
        VOZ[voice_endpoint.py]
        ANAL[analytics_api.py\nK-Means]
    end

    subgraph Core
        BH[balance_hidrico.py\nPenman-Monteith\nHargreaves]
        LLM[llm_orchestrator.py\nWhisper + Ollama]
        KM[kmeans_model.py]
    end

    PG[(PostgreSQL\n7 tablas)]
    NASA[(NASA POWER)]
    OLL([Ollama])

    UI --> DB_API & RIEGO
    MAP --> ANAL
    VC -- "POST audio" --> VOZ

    DB_API --> PG
    RIEGO --> BH
    RIEGO --> PG
    VOZ --> LLM
    ANAL --> KM
    LLM --> OLL
    BH -. "ETL" .-> NASA
```

## 3. Diagrama de Estados — Recomendación

```mermaid
stateDiagram-v2
    [*] --> pendiente : FAO-56 genera recomendacion

    pendiente --> aceptada : Agricultor acepta\n(PATCH feedback o POST riego\nlamina ≈ recomendada)
    pendiente --> modificada : Agricultor modifica\n(POST riego, |lamina_real - lamina_rec| > 2mm)
    pendiente --> ignorada : Agricultor ignora\n(PATCH feedback aceptada=ignorada)

    aceptada --> [*]
    modificada --> [*]
    ignorada --> [*]
```

## 4. Casos de Uso

```mermaid
flowchart LR
    AGR([Agricultor])

    subgraph "Gestion de Parcelas"
        UC1(Crear parcela)
        UC2(Consultar parcela)
        UC3(Ver KPI hidrico)
    end

    subgraph "Gestion de Riego"
        UC4(Registrar riego)
        UC5(Ver historial riego)
        UC6(Dar feedback\na recomendacion)
    end

    subgraph "Motor Agronomico"
        UC7(Calcular balance\nhidrico FAO-56)
        UC8(Consultar curva Kc)
    end

    subgraph "Analisis Espacial"
        UC9(Clustering logistico)
        UC10(Zonas de manejo)
    end

    subgraph "Pipeline de Voz"
        UC11(Comando por voz)
    end

    subgraph "Visualizacion GIS"
        UC12(Ver mapa interactivo)
    end

    AGR --- UC1 & UC2 & UC3
    AGR --- UC4 & UC5 & UC6
    AGR --- UC7 & UC8
    AGR --- UC9 & UC10
    AGR --- UC11
    AGR --- UC12

    UC11 -.-> UC7 : include
    UC11 -.-> UC12 : include
    UC7 -.-> UC6 : extend
```

## 5. Diagrama de Secuencia — Balance Hídrico

```mermaid
sequenceDiagram
    actor AGR as Agricultor
    participant FE as Frontend
    participant API as riego_api.py
    participant DB as PostgreSQL
    participant FAO as balance_hidrico.py

    AGR->>FE: Solicita balance hidrico
    FE->>API: GET /api/balance_hidrico?parcela_id&dias_siembra&fecha

    API->>DB: SELECT parcela WHERE id_parcela
    DB-->>API: Parcela (CC, PMP, prof_raiz, id_cultivo_actual)

    alt id_cultivo_actual IS NULL
        API-->>FE: 400 Parcela en barbecho
    end

    API->>DB: SELECT cultivo WHERE id_cultivo
    DB-->>API: CultivoCatalogo (Kc etapas)

    API->>FAO: obtener_kc(cultivo, dias_siembra)
    FAO-->>API: kc

    API->>DB: SELECT clima_diario WHERE id_parcela AND fecha
    DB-->>API: ClimaDiario (tmax, tmin, HR, viento, rad, lluvia)

    alt 5 variables completas
        API->>FAO: calcular_eto_penman_monteith()
        FAO-->>API: ETo
    else Solo tmax + tmin
        API->>FAO: calcular_eto_hargreaves()
        FAO-->>API: ETo (fallback)
    end

    API->>FAO: calcular_balance_hidrico(ETc, precip, humedad, CC, PMP, prof)
    FAO-->>API: deficit_mm, lamina_bruta_mm, requiere_riego, volumen_m3_ha

    API->>DB: SELECT historial_riego ORDER BY fecha DESC LIMIT 1
    DB-->>API: dias_sin_riego

    API->>DB: INSERT INTO recomendaciones
    DB-->>API: ok

    API-->>FE: JSON resultado
    FE-->>AGR: Muestra recomendacion
```

## 6. Diagrama de Secuencia — Pipeline de Voz

```mermaid
sequenceDiagram
    actor AGR as Agricultor
    participant FE as voice_client.js
    participant API as voice_endpoint.py
    participant WH as Whisper
    participant OL as Ollama
    participant VAL as llm_orchestrator.py

    AGR->>FE: Habla por microfono
    FE->>API: POST /api/voice-command (audio .webm)

    API->>WH: transcribe(audio, language=es)
    WH-->>API: texto transcrito

    API->>VAL: interpretar_comando_voz(audio_path)
    VAL->>OL: POST /api/chat (system_prompt + history + texto)
    OL-->>VAL: JSON raw

    VAL->>VAL: _parsear_y_validar(raw)
    Note over VAL: Valida intent, target, cultivo\ncontra whitelists

    VAL-->>API: {intent, target, message, parameters}
    API-->>FE: JSON + transcripcion

    alt intent = navegar
        FE->>FE: Cambia tab activa
    else intent = ejecutar_analisis
        FE->>API: GET /api/logistica_inteligente
    else intent = llenar_prescripcion
        FE->>FE: Rellena formulario
    end
```
