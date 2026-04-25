-- =============================================================================
-- MILPÍN AgTech v2.0 — Esquema DDL para PostgreSQL 14+ / 16
-- Base de datos: milpin_mvp
--
-- Cómo ejecutar en pgAdmin 4:
--   1. Abre pgAdmin 4 → conecta a tu servidor PostgreSQL 16
--   2. Clic derecho en "Databases" → Create → Database → nombre: milpin_mvp
--   3. Clic derecho en milpin_mvp → Query Tool
--   4. Pega TODO este script → F5 (Run)
--
-- Notas:
--   - gen_random_uuid() es nativa desde PostgreSQL 13. No requiere pgcrypto.
--   - parcelas.geom se almacena como JSONB (GeoJSON) en el MVP.
--     Se migra a GEOMETRY(Polygon,4326) con PostGIS en la Fase 2.
-- =============================================================================


-- =============================================================================
-- 1. usuarios
-- =============================================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_completo  VARCHAR(120) NOT NULL,
    email            VARCHAR(120) NOT NULL,
    telefono         VARCHAR(20),
    modulo_dr041     VARCHAR(50),
    activo           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_usuarios_email UNIQUE (email)
);

COMMENT ON TABLE  usuarios              IS 'Agricultores, técnicos y administradores del ERP MILPÍN.';
COMMENT ON COLUMN usuarios.modulo_dr041 IS 'Módulo de riego dentro del DR-041 (ej. Módulo 3).';


-- =============================================================================
-- 2. cultivos_catalogo
-- =============================================================================
CREATE TABLE IF NOT EXISTS cultivos_catalogo (
    id_cultivo                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_comun              VARCHAR(80)  NOT NULL,
    nombre_cientifico         VARCHAR(120),

    -- Coeficientes de cultivo Kc — FAO-56 Tabla 12
    kc_inicial                NUMERIC(4,2) NOT NULL,
    kc_medio                  NUMERIC(4,2) NOT NULL,
    kc_final                  NUMERIC(4,2) NOT NULL,

    -- Factor de sensibilidad al estrés hídrico — FAO-33 Tabla 25
    ky_total                  NUMERIC(4,2) NOT NULL,

    -- Duración de etapas fenológicas (días)
    dias_etapa_inicial        INTEGER      NOT NULL,
    dias_etapa_desarrollo     INTEGER      NOT NULL,
    dias_etapa_media          INTEGER      NOT NULL,
    dias_etapa_final          INTEGER      NOT NULL,

    -- Rendimiento potencial máximo en condiciones óptimas
    rendimiento_potencial_ton NUMERIC(8,2)
);

COMMENT ON TABLE  cultivos_catalogo                 IS 'Catálogo FAO-56/33 de especies del Valle del Yaqui.';
COMMENT ON COLUMN cultivos_catalogo.kc_inicial      IS 'Coeficiente de cultivo etapa inicial (FAO-56 Tabla 12).';
COMMENT ON COLUMN cultivos_catalogo.kc_medio        IS 'Kc en etapa de máximo desarrollo hídrico.';
COMMENT ON COLUMN cultivos_catalogo.ky_total        IS 'Factor de sensibilidad al estrés hídrico total (FAO-33 Tabla 25).';

-- Datos semilla: catálogo definitivo MILPÍN (5 cultivos objetivo)
INSERT INTO cultivos_catalogo
    (nombre_comun, nombre_cientifico,
     kc_inicial, kc_medio, kc_final, ky_total,
     dias_etapa_inicial, dias_etapa_desarrollo, dias_etapa_media, dias_etapa_final,
     rendimiento_potencial_ton)
VALUES
    ('Maíz',    'Zea mays',             0.30, 1.20, 0.60, 1.25, 25, 40, 45, 30, 10.0),
    ('Frijol',  'Phaseolus vulgaris',   0.40, 1.15, 0.35, 1.15, 20, 30, 40, 20,  2.0),
    ('Algodón', 'Gossypium hirsutum',   0.35, 1.20, 0.70, 0.85, 30, 50, 55, 45,  3.5),
    ('Uva',     'Vitis vinifera',       0.30, 0.85, 0.45, 0.85, 30, 60, 75, 50, 22.5),
    ('Chile',   'Capsicum annuum',      0.60, 1.05, 0.90, 1.10, 30, 35, 40, 20, 30.0)
ON CONFLICT DO NOTHING;


-- =============================================================================
-- 3. parcelas
-- =============================================================================
CREATE TABLE IF NOT EXISTS parcelas (
    id_parcela               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Claves foráneas
    id_usuario               UUID         NOT NULL
        REFERENCES usuarios(id_usuario) ON DELETE RESTRICT,
    id_cultivo_actual        UUID
        REFERENCES cultivos_catalogo(id_cultivo) ON DELETE SET NULL,

    -- Identificación
    nombre_parcela           VARCHAR(100),

    -- Geometría MVP: GeoJSON como JSONB
    -- Fase 2: cambiar a GEOMETRY(Polygon, 4326) con PostGIS
    geom                     JSONB,
    area_ha                  NUMERIC(10,4),

    -- Parámetros edáficos (determinan el agua disponible del suelo)
    tipo_suelo               VARCHAR(50),
    conductividad_electrica  NUMERIC(6,2),
    profundidad_raiz_cm      INTEGER,
    capacidad_campo          NUMERIC(6,4),
    punto_marchitez          NUMERIC(6,4),

    -- Sistema de riego
    sistema_riego            VARCHAR(30),

    activo                   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  parcelas                           IS 'Lotes de cultivo con atributos edáficos. Geometría como GeoJSON en el MVP.';
COMMENT ON COLUMN parcelas.geom                      IS 'GeoJSON Polygon. Migrar a GEOMETRY(Polygon,4326) con PostGIS en Fase 2.';
COMMENT ON COLUMN parcelas.capacidad_campo           IS 'Humedad volumétrica a capacidad de campo (m3/m3). Ej: 0.34';
COMMENT ON COLUMN parcelas.punto_marchitez           IS 'Humedad volumétrica en punto de marchitez permanente (m3/m3). Ej: 0.18';
COMMENT ON COLUMN parcelas.conductividad_electrica   IS 'CE en dS/m. Valor > 4 dS/m indica estres salino activo.';

-- Índice de búsqueda por usuario
CREATE INDEX IF NOT EXISTS idx_parcelas_usuario
    ON parcelas (id_usuario);

-- Vista: agua disponible total por parcela (mm)
-- ADT = (Capacidad de Campo - Punto Marchitez) x profundidad_raiz_cm x 10
CREATE OR REPLACE VIEW v_agua_disponible AS
SELECT
    id_parcela,
    nombre_parcela,
    ROUND(
        (capacidad_campo - punto_marchitez) * profundidad_raiz_cm * 10,
        2
    ) AS agua_disponible_mm
FROM parcelas
WHERE activo = TRUE
  AND capacidad_campo    IS NOT NULL
  AND punto_marchitez    IS NOT NULL
  AND profundidad_raiz_cm IS NOT NULL;

COMMENT ON VIEW v_agua_disponible IS
    'ADT (mm) = (CC - PMP) x profundidad_raiz_cm x 10. Lamina maxima que puede absorber el suelo.';


-- =============================================================================
-- 4. recomendaciones
-- (se crea ANTES que historial_riego porque historial_riego tiene FK opcional aquí)
-- =============================================================================
CREATE TABLE IF NOT EXISTS recomendaciones (
    id_recomendacion      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Claves foráneas
    id_parcela            UUID         NOT NULL
        REFERENCES parcelas(id_parcela) ON DELETE RESTRICT,
    id_cultivo            UUID
        REFERENCES cultivos_catalogo(id_cultivo) ON DELETE SET NULL,

    -- Outputs del motor FAO-56
    fecha_generacion      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fecha_riego_sugerida  DATE,
    lamina_recomendada_mm NUMERIC(8,2),
    eto_referencia        NUMERIC(8,3),
    etc_calculada         NUMERIC(8,3),
    deficit_acumulado_mm  NUMERIC(8,2),
    dias_sin_riego        INTEGER,

    -- Clasificación y trazabilidad
    nivel_urgencia        VARCHAR(20)
        CONSTRAINT ck_reco_urgencia
        CHECK (nivel_urgencia IN ('critico', 'moderado', 'preventivo')),
    algoritmo_version     VARCHAR(30) DEFAULT 'fao56-mvp-v1.0',

    -- Feedback del agricultor
    aceptada              VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CONSTRAINT ck_reco_aceptada
        CHECK (aceptada IN ('pendiente', 'aceptada', 'modificada', 'ignorada')),
    lamina_ejecutada_mm   NUMERIC(8,2),

    -- Snapshot completo de inputs del modelo (para trazabilidad)
    parametros_json       JSONB
);

COMMENT ON TABLE  recomendaciones              IS 'Recomendaciones de riego generadas por el motor FAO-56 de MILPIN.';
COMMENT ON COLUMN recomendaciones.aceptada     IS 'Feedback: pendiente | aceptada | modificada | ignorada.';
COMMENT ON COLUMN recomendaciones.parametros_json IS 'Snapshot de todos los inputs del modelo al momento del calculo.';

CREATE INDEX IF NOT EXISTS idx_reco_parcela_fecha
    ON recomendaciones (id_parcela, fecha_generacion DESC);

-- Índice parcial: solo recomendaciones pendientes de respuesta
CREATE INDEX IF NOT EXISTS idx_reco_pendientes
    ON recomendaciones (id_parcela, fecha_generacion)
    WHERE aceptada = 'pendiente';


-- =============================================================================
-- 5. historial_riego
-- =============================================================================
CREATE TABLE IF NOT EXISTS historial_riego (
    id_riego          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Claves foráneas
    id_parcela        UUID         NOT NULL
        REFERENCES parcelas(id_parcela) ON DELETE RESTRICT,
    id_recomendacion  UUID
        REFERENCES recomendaciones(id_recomendacion) ON DELETE SET NULL,

    -- Datos del evento de riego
    fecha_riego       DATE         NOT NULL,
    volumen_m3_ha     NUMERIC(10,2),
    lamina_mm         NUMERIC(8,2),
    duracion_horas    NUMERIC(6,2),
    metodo_riego      VARCHAR(30)
        CONSTRAINT ck_riego_metodo
        CHECK (metodo_riego IN ('gravedad', 'goteo', 'aspersion', 'microaspersion')),
    origen_decision   VARCHAR(20)
        CONSTRAINT ck_riego_origen
        CHECK (origen_decision IN ('sistema', 'manual', 'voz')),
    costo_energia_mxn NUMERIC(10,2),
    observaciones     TEXT,

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  historial_riego               IS 'Eventos de riego ejecutados. KPI: volumen_m3_ha vs. baseline 8,000 m3/ha/ciclo DR-041.';
COMMENT ON COLUMN historial_riego.volumen_m3_ha IS 'Volumen aplicado en m3/ha. Comparar contra baseline 8,000 m3/ha/ciclo del DR-041.';
COMMENT ON COLUMN historial_riego.costo_energia_mxn IS 'Costo de bombeo = volumen x area_ha x tarifa. Baseline: $1.68 MXN/m3 (CFE 9-CU, 80m).';

CREATE INDEX IF NOT EXISTS idx_riego_parcela_fecha
    ON historial_riego (id_parcela, fecha_riego DESC);


-- =============================================================================
-- 6. costos_ciclo
-- =============================================================================
CREATE TABLE IF NOT EXISTS costos_ciclo (
    id_costo                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_parcela                UUID         NOT NULL
        REFERENCES parcelas(id_parcela) ON DELETE RESTRICT,
    ciclo_agricola            VARCHAR(20)  NOT NULL,
    cultivo                   VARCHAR(80),
    volumen_agua_total_m3     NUMERIC(12,2),
    costo_agua_mxn            NUMERIC(12,2),
    costo_fertilizantes_mxn   NUMERIC(12,2),
    costo_agroquimicos_mxn    NUMERIC(12,2),
    costo_semilla_mxn         NUMERIC(12,2),
    costo_maquinaria_mxn      NUMERIC(12,2),
    costo_mano_obra_mxn       NUMERIC(12,2),
    ingreso_estimado_mxn      NUMERIC(12,2),
    margen_contribucion_mxn   NUMERIC(12,2)
);

COMMENT ON TABLE costos_ciclo IS 'Resumen economico por parcela y ciclo agricola.';
COMMENT ON COLUMN costos_ciclo.volumen_agua_total_m3 IS 'Volumen total absoluto de agua aplicado durante el ciclo.';
COMMENT ON COLUMN costos_ciclo.margen_contribucion_mxn IS 'Ingreso estimado menos costos directos del ciclo.';

CREATE INDEX IF NOT EXISTS idx_costos_ciclo_parcela
    ON costos_ciclo (id_parcela, ciclo_agricola);


-- =============================================================================
-- 7. clima_diario
-- =============================================================================
-- Serie climática diaria por parcela. Fuente primaria: NASA POWER API
-- (modelo MERRA-2 + CERES), granularidad punto-geográfico × día.
-- Alimentada por tools/nasa_power_etl.py. ON CONFLICT DO NOTHING permite
-- re-ejecutar el ETL sin duplicar filas.
-- =============================================================================
CREATE TABLE IF NOT EXISTS clima_diario (
    id_parcela  UUID        NOT NULL
        REFERENCES parcelas(id_parcela) ON DELETE CASCADE,
    fecha       DATE        NOT NULL,

    -- Variables meteorológicas NASA POWER
    t_max        NUMERIC(5,2),  -- Temperatura máxima diaria a 2m (°C)
    t_min        NUMERIC(5,2),  -- Temperatura mínima diaria a 2m (°C)
    humedad_rel  NUMERIC(5,2),  -- Humedad relativa media a 2m (%)
    viento       NUMERIC(5,2),  -- Viento medio a 2m (m/s)
    radiacion    NUMERIC(6,3),  -- Radiación solar superficial (MJ/m²/día)
    lluvia       NUMERIC(6,2),  -- Precipitación total diaria corregida (mm)

    -- Valor derivado persistido
    et0          NUMERIC(5,2),  -- ET0 FAO-56 Penman-Monteith (mm/día)

    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (id_parcela, fecha)
);

COMMENT ON TABLE  clima_diario           IS 'Series climáticas diarias por parcela. Fuente: NASA POWER API. ET0 calculada con FAO-56 Penman-Monteith.';
COMMENT ON COLUMN clima_diario.et0       IS 'Evapotranspiración de referencia (mm/día). Calculada con core.balance_hidrico.calcular_eto_penman_monteith_serie.';
COMMENT ON COLUMN clima_diario.radiacion IS 'ALLSKY_SFC_SW_DWN de NASA POWER. Valores pico > 12 mm/día de ET0 derivada sugieren ruido satelital.';
COMMENT ON COLUMN clima_diario.lluvia    IS 'PRECTOTCORR. NaN se imputa como 0, NO se interpola (interpolar crearía lluvia ficticia).';

-- Índice para queries de series temporales (últimos N días de una parcela)
CREATE INDEX IF NOT EXISTS idx_clima_parcela_fecha
    ON clima_diario (id_parcela, fecha DESC);


-- =============================================================================
-- Vista KPI: consumo anual por parcela vs. baseline DR-041
-- =============================================================================
CREATE OR REPLACE VIEW v_kpi_consumo AS
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

COMMENT ON VIEW v_kpi_consumo IS
    'KPI de ahorro hidrico por parcela y año vs. baseline DR-041 (8,000 m3/ha/ciclo).
     Tarifa base: $1.68 MXN/m3 (CFE 9-CU, bombeo desde 80m de profundidad).';


-- =============================================================================
-- Verificación final: listar tablas y vistas creadas
-- =============================================================================
SELECT
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'usuarios', 'cultivos_catalogo', 'parcelas',
      'recomendaciones', 'historial_riego', 'clima_diario',
      'costos_ciclo', 'v_agua_disponible', 'v_kpi_consumo'
  )
ORDER BY table_type, table_name;
