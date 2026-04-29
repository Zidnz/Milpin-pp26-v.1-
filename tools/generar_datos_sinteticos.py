"""
MILPÍN — Generador de datos sintéticos
=======================================

Produce CSVs listos para cargar en la base de datos a partir de los rangos
estadísticos definidos en:
  - docs: milpin_db_design.docx
  - params: Parámetros Estadísticos para Generación de Datos Sintéticos.xlsx

Diseño
------
- Reproducible: np.random.default_rng(seed)
- Distribuciones respetando el xlsx:
    * Normal truncada   -> _sample_truncnormal
    * Lognormal         -> _sample_lognormal (convierte μ/σ aritméticos a log)
    * Uniforme          -> _sample_uniform
- Restricciones físicas:
    * capacidad_campo > punto_marchitez  (rechazo)
    * kc_medio > kc_inicial y kc_medio > kc_final
    * deficit truncado en 0
- Geometría: polígonos rectangulares alrededor del Valle del Yaqui (GeoJSON
  guardado en JSONB -- coherente con models.py::Parcela.geom como JSON).
- Salida: CSVs en data/synthetic/. Los UUIDs se generan en Python para poder
  referenciar FKs sin round-trip a la BD.

Uso
---
    python tools/generar_datos_sinteticos.py                # defaults: 5 anos / 80 parcelas
    python tools/generar_datos_sinteticos.py --usuarios 20 --parcelas 80

Luego, en Postgres:
    \\copy usuarios             FROM 'data/synthetic/usuarios.csv'             CSV HEADER;
    \\copy cultivos_catalogo    FROM 'data/synthetic/cultivos_catalogo.csv'    CSV HEADER;
    \\copy parcelas             FROM 'data/synthetic/parcelas.csv'             CSV HEADER;
    \\copy recomendaciones      FROM 'data/synthetic/recomendaciones.csv'      CSV HEADER;
    \\copy historial_riego      FROM 'data/synthetic/historial_riego.csv'      CSV HEADER;
    \\copy costos_ciclo         FROM 'data/synthetic/costos_ciclo.csv'         CSV HEADER;

Notas de calibración
--------------------
- Cultivos: se unen los sembrados actualmente en el schema (Trigo, Cártamo,
  Garbanzo, Maíz, Algodón) con los definidos en el xlsx (Frijol, Uva, Chile).
  Esto deja 8 cultivos y da pie para ampliar el catálogo cuando se resuelva la
  deuda técnica.
- Tarifa CFE 9-CU baseline: 1.68 MXN/m3. El xlsx sugiere 2-4 MXN/m3 para
  bombeo 80m; el script permite mover esta constante.
- Defaults calibrados para una narrativa pre-MVP: 80 parcelas durante 5 anos,
  24,000 riegos, 20,800 recomendaciones semanales y 800 costos de ciclo.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------

VALLE_YAQUI_LAT = 27.3670           # centro Ciudad Obregón / DR-041 Módulo 3
VALLE_YAQUI_LON = -109.9310
METROS_POR_GRADO_LAT = 111_000.0
METROS_POR_GRADO_LON = 111_000.0 * math.cos(math.radians(VALLE_YAQUI_LAT))
TARIFA_MXN_M3 = 1.68                # CFE 9-CU a 80m de bombeo (baseline)
BASELINE_M3_HA_CICLO = 8_000.0
ALGORITMO_VERSION = "fao56-v0.2"

MODULOS_DR041 = ["Módulo 1", "Módulo 2", "Módulo 3", "Módulo 4", "Módulo 5"]
TIPOS_SUELO = [
    "arcilloso", "franco-arcilloso", "franco", "franco-limoso",
    "franco-arenoso", "arenoso",
]
SISTEMAS_RIEGO = ["gravedad", "goteo", "aspersion", "microaspersion"]
NIVELES_URGENCIA = ["critico", "moderado", "preventivo"]
ESTADOS_ACEPTADA = ["aceptada", "modificada", "ignorada", "pendiente"]
ORIGENES_DECISION = ["sistema", "manual", "voz"]

# ---------------------------------------------------------------------------
# Catálogo de cultivos
# Unión de los cultivos sembrados en init_db.py con los del xlsx.
# Los parámetros Kc / Ky / días / rendimiento vienen de:
#   - FAO-56 Tabla 12 (Kc) y FAO-33 Tabla 25 (Ky)
#   - Hoja "6. cultivos" del xlsx para rendimiento potencial
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CultivoBase:
    nombre_comun: str
    nombre_cientifico: str
    kc_inicial: float
    kc_medio: float
    kc_final: float
    ky_total: float
    dias_inicial: int
    dias_desarrollo: int
    dias_media: int
    dias_final: int
    rendimiento_mu: float       # ton/ha media
    rendimiento_sigma: float    # ton/ha desviación

CATALOGO_CULTIVOS: list[CultivoBase] = [
    # Rendimiento μ/σ de la hoja "6. cultivos" del xlsx; Kc/Ky de FAO-56/33.
    CultivoBase("Maíz",    "Zea mays",           0.30, 1.20, 0.60, 1.25,  25, 40, 45, 30, 10.00, 1.00),
    CultivoBase("Frijol",  "Phaseolus vulgaris", 0.40, 1.15, 0.35, 1.15,  20, 30, 40, 20,  2.00, 0.25),
    CultivoBase("Algodón", "Gossypium hirsutum", 0.35, 1.20, 0.70, 0.85,  30, 50, 55, 45,  3.50, 0.75),
    CultivoBase("Uva",     "Vitis vinifera",     0.30, 0.85, 0.45, 0.85,  30, 60, 75, 50, 22.50, 3.75),
    CultivoBase("Chile",   "Capsicum annuum",    0.60, 1.05, 0.90, 1.10,  30, 35, 40, 20, 30.00, 5.00),
]


# ---------------------------------------------------------------------------
# Helpers de distribución
# ---------------------------------------------------------------------------

def _sample_truncnormal(rng: np.random.Generator, mu: float, sigma: float,
                        lo: float, hi: float, size: int) -> np.ndarray:
    """Normal truncada por rechazo. Evita depender de scipy."""
    out = np.empty(size)
    n_drawn = 0
    while n_drawn < size:
        candidates = rng.normal(mu, sigma, size=size * 2)
        valid = candidates[(candidates >= lo) & (candidates <= hi)]
        take = min(len(valid), size - n_drawn)
        out[n_drawn:n_drawn + take] = valid[:take]
        n_drawn += take
    return out


def _sample_lognormal(rng: np.random.Generator, mu: float, sigma: float,
                      lo: float, hi: float, size: int) -> np.ndarray:
    """
    Lognormal parametrizada por la media/desviación ARITMÉTICAS de la variable
    (no del log). Conversión:
        σ_log² = ln(1 + σ²/μ²)
        μ_log  = ln(μ) - σ_log²/2
    Se trunca a [lo, hi] por rechazo.
    """
    if mu <= 0:
        raise ValueError("Lognormal requiere mu > 0")
    sigma_log = math.sqrt(math.log(1.0 + (sigma ** 2) / (mu ** 2)))
    mu_log = math.log(mu) - (sigma_log ** 2) / 2.0

    out = np.empty(size)
    n_drawn = 0
    while n_drawn < size:
        candidates = rng.lognormal(mu_log, sigma_log, size=size * 2)
        valid = candidates[(candidates >= lo) & (candidates <= hi)]
        take = min(len(valid), size - n_drawn)
        out[n_drawn:n_drawn + take] = valid[:take]
        n_drawn += take
    return out


def _uuid() -> str:
    return str(uuid.uuid4())


def _polygon_para_parcela(rng: np.random.Generator, area_ha: float) -> dict:
    """
    Devuelve un polígono GeoJSON (lon/lat, EPSG:4326) para una parcela de
    `area_ha` hectáreas, centrado aleatoriamente dentro de un radio de ~10km
    del centro del Valle del Yaqui. Parcela rectangular con ratio 1:1.5.
    """
    area_m2 = area_ha * 10_000.0
    ratio = 1.5
    # lado corto x lado largo: area = lc * ll, ll = ratio * lc
    lc_m = math.sqrt(area_m2 / ratio)
    ll_m = ratio * lc_m

    d_lat_total = ll_m / METROS_POR_GRADO_LAT
    d_lon_total = lc_m / METROS_POR_GRADO_LON

    # offset aleatorio del centro (hasta ~10km)
    offset_lat = rng.uniform(-0.09, 0.09)
    offset_lon = rng.uniform(-0.09, 0.09)
    cx = VALLE_YAQUI_LON + offset_lon
    cy = VALLE_YAQUI_LAT + offset_lat

    # leve rotación ignorada para simplicidad -- polígono axis-aligned
    half_lat = d_lat_total / 2
    half_lon = d_lon_total / 2
    ring = [
        [round(cx - half_lon, 6), round(cy - half_lat, 6)],
        [round(cx + half_lon, 6), round(cy - half_lat, 6)],
        [round(cx + half_lon, 6), round(cy + half_lat, 6)],
        [round(cx - half_lon, 6), round(cy + half_lat, 6)],
        [round(cx - half_lon, 6), round(cy - half_lat, 6)],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


# ---------------------------------------------------------------------------
# Generadores por entidad
# ---------------------------------------------------------------------------

NOMBRES = [
    "Ramón Valenzuela", "María Fernández", "Juan Carlos Ortiz", "Luis Miranda",
    "Rosa Herrera", "Jesús Soto", "Guadalupe Ríos", "Alejandro Castillo",
    "Norma Reyes", "Sergio Bojórquez", "Patricia Durán", "Humberto Lugo",
    "Claudia Navarro", "Ernesto Zamora", "Beatriz Gaxiola", "Francisco Acosta",
    "Silvia Ibarra", "Raúl Monge", "Leticia Romo", "Miguel Parra",
]


def generar_usuarios(rng: np.random.Generator, n: int) -> list[dict]:
    filas = []
    for i in range(n):
        nombre = NOMBRES[i % len(NOMBRES)]
        sufijo = "" if i < len(NOMBRES) else f" {i // len(NOMBRES) + 1}"
        nombre_completo = f"{nombre}{sufijo}"
        email_user = (nombre.lower()
                      .replace(" ", ".")
                      .replace("á", "a").replace("é", "e").replace("í", "i")
                      .replace("ó", "o").replace("ú", "u"))
        filas.append({
            "id_usuario": _uuid(),
            "nombre_completo": nombre_completo,
            "email": f"{email_user}{i:03d}@dr041-dev.com",
            "telefono": f"+52644{rng.integers(1_000_000, 9_999_999):07d}",
            "modulo_dr041": rng.choice(MODULOS_DR041),
            "activo": True,
            "created_at": _timestamp_hace(rng, max_dias=720),
        })
    return filas


def generar_cultivos_catalogo() -> list[dict]:
    return [
        {
            "id_cultivo": _uuid(),
            "nombre_comun": c.nombre_comun,
            "nombre_cientifico": c.nombre_cientifico,
            "kc_inicial": round(c.kc_inicial, 2),
            "kc_medio": round(c.kc_medio, 2),
            "kc_final": round(c.kc_final, 2),
            "ky_total": round(c.ky_total, 2),
            "dias_etapa_inicial": c.dias_inicial,
            "dias_etapa_desarrollo": c.dias_desarrollo,
            "dias_etapa_media": c.dias_media,
            "dias_etapa_final": c.dias_final,
            "rendimiento_potencial_ton": round(c.rendimiento_mu, 2),
        }
        for c in CATALOGO_CULTIVOS
    ]


def generar_parcelas(rng: np.random.Generator, n: int,
                     usuarios: Sequence[dict],
                     cultivos: Sequence[dict]) -> list[dict]:
    # xlsx sheet 1
    areas = _sample_lognormal(rng, mu=15.0, sigma=11.25, lo=5.0, hi=50.0, size=n)
    ce    = _sample_lognormal(rng, mu=2.5,  sigma=1.75,  lo=1.0, hi=8.0,  size=n)
    raiz  = _sample_truncnormal(rng, mu=90.0, sigma=42.5, lo=30, hi=200, size=n)

    # CC y PMP: muestreo correlacionado con rechazo de CC <= PMP
    cc = np.empty(n); pmp = np.empty(n)
    i = 0
    while i < n:
        cc_i  = rng.normal(0.28, 0.08)
        pmp_i = rng.normal(0.14, 0.05)
        if 0.10 <= cc_i <= 0.45 and 0.03 <= pmp_i <= 0.25 and cc_i > pmp_i + 0.05:
            cc[i] = cc_i; pmp[i] = pmp_i
            i += 1

    filas = []
    for idx in range(n):
        uid = rng.choice(usuarios)["id_usuario"]
        cultivo = rng.choice(cultivos)
        cultivo_actual = cultivo["nombre_comun"]
        filas.append({
            "id_parcela": _uuid(),
            "id_usuario": uid,
            "id_cultivo_actual": cultivo["id_cultivo"],
            "nombre_parcela": f"Lote {cultivo_actual[:3]}-{idx+1:03d}",
            "geom": json.dumps(_polygon_para_parcela(rng, float(areas[idx]))),
            "area_ha": round(float(areas[idx]), 4),
            "tipo_suelo": rng.choice(TIPOS_SUELO),
            "conductividad_electrica": round(float(ce[idx]), 2),
            "profundidad_raiz_cm": int(round(raiz[idx])),
            "capacidad_campo": round(float(cc[idx]), 4),
            "punto_marchitez": round(float(pmp[idx]), 4),
            "sistema_riego": rng.choice(SISTEMAS_RIEGO),
            "activo": True,
            "created_at": _timestamp_hace(rng, max_dias=540),
        })
    return filas


def generar_recomendaciones(rng: np.random.Generator,
                            parcelas: Sequence[dict],
                            cultivos: Sequence[dict],
                            por_parcela: int) -> list[dict]:
    n = len(parcelas) * por_parcela
    eto = _sample_truncnormal(rng, mu=7.0, sigma=2.5, lo=2.0, hi=12.0, size=n)
    # etc se deriva de eto, no se muestrea independiente (consistencia física)
    deficit = _sample_truncnormal(rng, mu=45.0, sigma=37.5, lo=0.0, hi=150.0, size=n)
    lamina  = _sample_truncnormal(rng, mu=50.0, sigma=35.0, lo=10.0, hi=150.0, size=n)

    cultivos_by_name = {c["nombre_comun"]: c for c in cultivos}
    filas = []
    k = 0
    for parcela in parcelas:
        for _ in range(por_parcela):
            # kc efectivo aleatorio entre kc_inicial y kc_medio
            nombre_cultivo = rng.choice(list(cultivos_by_name.keys()))
            c = cultivos_by_name[nombre_cultivo]
            kc = rng.uniform(c["kc_inicial"], c["kc_medio"])
            etc = float(eto[k]) * kc

            fecha_gen = _timestamp_hace(rng, max_dias=5 * 365)
            dias_a_futuro = int(rng.integers(1, 8))
            fecha_riego_sug = (datetime.fromisoformat(fecha_gen)
                               + timedelta(days=dias_a_futuro)).date().isoformat()

            aceptada = rng.choice(ESTADOS_ACEPTADA, p=[0.55, 0.15, 0.10, 0.20])
            urgencia = _clasificar_urgencia(float(deficit[k]))

            params_json = {
                "eto_mm": round(float(eto[k]), 3),
                "kc": round(kc, 3),
                "cultivo": nombre_cultivo,
                "humedad_suelo_pct": round(rng.uniform(0.15, 0.40), 3),
                "profundidad_raiz_cm": int(parcela["profundidad_raiz_cm"]),
            }

            filas.append({
                "id_recomendacion": _uuid(),
                "id_parcela": parcela["id_parcela"],
                "id_cultivo": c["id_cultivo"],
                "fecha_generacion": fecha_gen,
                "fecha_riego_sugerida": fecha_riego_sug,
                "lamina_recomendada_mm": round(float(lamina[k]), 2),
                "eto_referencia": round(float(eto[k]), 3),
                "etc_calculada": round(etc, 3),
                "deficit_acumulado_mm": round(float(deficit[k]), 2),
                "dias_sin_riego": int(rng.integers(3, 18)),
                "nivel_urgencia": urgencia,
                "algoritmo_version": ALGORITMO_VERSION,
                "aceptada": aceptada,
                "lamina_ejecutada_mm": _lamina_ejecutada(aceptada, float(lamina[k]), rng),
                "parametros_json": json.dumps(params_json, ensure_ascii=False),
            })
            k += 1
    return filas


CICLOS_AGRICOLAS: list[tuple[str, date, date]] = [
    # (etiqueta, fecha_inicio_aprox, fecha_fin_aprox)
    # OI = Otoño-Invierno (oct-mar), PV = Primavera-Verano (abr-sep)
    ("OI-2021", date(2020, 10, 15), date(2021,  3, 15)),
    ("PV-2021", date(2021,  4,  1), date(2021,  9, 15)),
    ("OI-2022", date(2021, 10, 15), date(2022,  3, 15)),
    ("PV-2022", date(2022,  4,  1), date(2022,  9, 15)),
    ("OI-2023", date(2022, 10, 15), date(2023,  3, 15)),
    ("PV-2023", date(2023,  4,  1), date(2023,  9, 15)),
    ("OI-2024", date(2023, 10, 15), date(2024,  3, 15)),
    ("PV-2024", date(2024,  4,  1), date(2024,  9, 15)),
    ("OI-2025", date(2024, 10, 15), date(2025,  3, 15)),
    ("PV-2025", date(2025,  4,  1), date(2025,  9, 15)),
]

# Eficiencia de aplicación por sistema de riego (fracción útil del agua aplicada)
EFICIENCIA_RIEGO = {
    "gravedad": 0.55,
    "aspersion": 0.75,
    "microaspersion": 0.80,
    "goteo": 0.90,
}


def generar_historial_riego(rng: np.random.Generator,
                            parcelas: Sequence[dict],
                            recomendaciones: Sequence[dict],
                            por_parcela: int) -> list[dict]:
    """
    Genera historial de riego estructurado POR CICLO AGRÍCOLA.

    Lógica de calibración:
    - Target por ciclo: truncnormal(μ=8000, σ=1500, [4000, 13000]) m³/ha
      ajustado por eficiencia del sistema de riego.
    - Parcelas con goteo tienden a ~6500 m³/ha; gravedad a ~9500 m³/ha.
    - Cada ciclo tiene 12-25 eventos de riego (según duración del cultivo).
    - La lámina por evento se reparte para que la suma ≈ target del ciclo.
    - ~20% de ciclos "bien manejados" caen bajo la meta de 6,000 m³/ha.

    Esto produce ~80 parcelas × 10 ciclos × ~18 eventos ≈ 14,400 filas
    (vs las 24,000 anteriores), pero con estructura temporal real.
    """
    reco_by_parcela: dict[str, list[str]] = {}
    for r in recomendaciones:
        reco_by_parcela.setdefault(r["id_parcela"], []).append(r["id_recomendacion"])

    filas = []
    for parcela in parcelas:
        recos = reco_by_parcela.get(parcela["id_parcela"], [])
        sistema = parcela["sistema_riego"]
        eficiencia = EFICIENCIA_RIEGO.get(sistema, 0.65)

        for ciclo_label, ciclo_ini, ciclo_fin in CICLOS_AGRICOLAS:
            # ── Target de volumen para este ciclo ────────────────────────
            # Sistemas ineficientes → más agua bruta; eficientes → menos.
            # Base: 8000 m³/ha es el promedio DR-041 (gravedad domina).
            # Ajuste: target_bruto = necesidad_neta / eficiencia
            #   necesidad_neta ~ 4500 m³/ha (ETc acumulada típica)
            #   pero modelamos el total bruto directamente:
            mu_ciclo = 4500.0 / eficiencia  # gravedad→8182, goteo→5000
            sigma_ciclo = 1200.0
            vol_ciclo_target = float(
                _sample_truncnormal(rng, mu=mu_ciclo, sigma=sigma_ciclo,
                                    lo=3500.0, hi=13000.0, size=1)[0]
            )

            # ── Número de eventos de riego en el ciclo ───────────────────
            dias_ciclo = (ciclo_fin - ciclo_ini).days
            # goteo: riegos frecuentes y pequeños; gravedad: pocos y grandes
            if sistema == "goteo":
                n_eventos = int(rng.integers(18, 30))
            elif sistema in ("aspersion", "microaspersion"):
                n_eventos = int(rng.integers(14, 22))
            else:  # gravedad
                n_eventos = int(rng.integers(8, 16))

            # ── Repartir el volumen entre eventos (Dirichlet) ────────────
            # Distribución no uniforme: algunos riegos son más grandes.
            proporciones = rng.dirichlet(np.ones(n_eventos) * 2.0)
            volumenes_m3_ha = proporciones * vol_ciclo_target

            # ── Fechas de riego ordenadas dentro del ciclo ───────────────
            offsets = sorted(rng.integers(0, dias_ciclo, size=n_eventos))

            for i in range(n_eventos):
                vol_m3_ha = float(volumenes_m3_ha[i])
                lam_mm = vol_m3_ha / 10.0  # inversa: 10 m³/ha = 1 mm
                fecha = ciclo_ini + timedelta(days=int(offsets[i]))

                # Duración proporcional al volumen aplicado
                dur_base = vol_m3_ha / 50.0  # ~1h por cada 50 m³/ha
                duracion = max(1.0, min(24.0, dur_base * rng.uniform(0.7, 1.3)))

                # Costo energía: tarifa × vol_absoluto (m³ totales, no por ha)
                costo = vol_m3_ha * parcela["area_ha"] * TARIFA_MXN_M3
                costo *= rng.uniform(0.85, 1.15)

                filas.append({
                    "id_riego": _uuid(),
                    "id_parcela": parcela["id_parcela"],
                    "ciclo_agricola": ciclo_label,
                    "id_recomendacion": (rng.choice(recos)
                                         if recos and rng.random() < 0.6 else ""),
                    "fecha_riego": fecha.isoformat(),
                    "volumen_m3_ha": round(vol_m3_ha, 2),
                    "lamina_mm": round(lam_mm, 2),
                    "duracion_horas": round(duracion, 2),
                    "metodo_riego": sistema,
                    "origen_decision": rng.choice(
                        ORIGENES_DECISION, p=[0.5, 0.3, 0.2]),
                    "costo_energia_mxn": round(costo, 2),
                    "ciclo_vol_target_m3_ha": round(vol_ciclo_target, 2),
                    "observaciones": "",
                    "created_at": datetime(
                        fecha.year, fecha.month, fecha.day,
                        int(rng.integers(5, 20)),
                        int(rng.integers(0, 60)),
                        tzinfo=timezone.utc,
                    ).isoformat(timespec="seconds"),
                })
    return filas


def generar_costos_ciclo(rng: np.random.Generator,
                         parcelas: Sequence[dict],
                         cultivos: Sequence[dict],
                         ciclos_por_parcela: int) -> list[dict]:
    """
    Tabla costos_ciclo: resumen economico por parcela y ciclo agricola.
    """
    n = len(parcelas) * ciclos_por_parcela
    vol_agua  = _sample_truncnormal(rng, mu=8000, sigma=2500, lo=3000, hi=13000, size=n)
    costo_fer = _sample_truncnormal(rng, mu=9000, sigma=3000, lo=3000, hi=15000, size=n)
    costo_agr = _sample_truncnormal(rng, mu=6000, sigma=2000, lo=2000, hi=10000, size=n)
    costo_maq = _sample_truncnormal(rng, mu=10000, sigma=3500, lo=4000, hi=18000, size=n)
    costo_obra = _sample_truncnormal(rng, mu=8000, sigma=2750, lo=3000, hi=14000, size=n)
    costo_sem = _sample_lognormal(rng, mu=4500, sigma=1625, lo=1500, hi=8000, size=n)

    rendimiento_por_cultivo = {
        c["nombre_comun"]: (next(cb for cb in CATALOGO_CULTIVOS
                                 if cb.nombre_comun == c["nombre_comun"]))
        for c in cultivos
    }
    # precios de mercado en MXN/ton (órdenes de magnitud SIAP ~2025)
    precio_ton = {
        "Maíz": 6_000,
        "Frijol": 18_000,
        "Algodón": 60_000,     # fibra sin hueso
        "Uva": 25_000,         # uva de mesa para exportación
        "Chile": 15_000,       # chile verde fresco
    }

    ciclos_labels = [
        "OI-2021", "PV-2021", "OI-2022", "PV-2022", "OI-2023",
        "PV-2023", "OI-2024", "PV-2024", "OI-2025", "PV-2025",
    ]
    filas = []
    k = 0
    for parcela in parcelas:
        for j in range(ciclos_por_parcela):
            ciclo = ciclos_labels[j % len(ciclos_labels)]
            nombre_cultivo = rng.choice(list(rendimiento_por_cultivo.keys()))
            cb = rendimiento_por_cultivo[nombre_cultivo]

            rend_ton_ha = float(rng.normal(cb.rendimiento_mu, cb.rendimiento_sigma))
            rend_ton_ha = max(0.1, rend_ton_ha)
            ingreso = rend_ton_ha * parcela["area_ha"] * precio_ton[nombre_cultivo]

            v_total = float(vol_agua[k]) * parcela["area_ha"]  # m3 absolutos
            c_agua  = v_total * TARIFA_MXN_M3

            costos_totales = (c_agua + float(costo_fer[k]) + float(costo_agr[k])
                              + float(costo_sem[k]) + float(costo_maq[k])
                              + float(costo_obra[k])) * parcela["area_ha"] / parcela["area_ha"]
            # nota: el xlsx da costos por hectárea, los multiplico por area_ha
            # para el total del ciclo. Reescribo limpio:
            costos_totales = (
                c_agua
                + (float(costo_fer[k]) + float(costo_agr[k]) + float(costo_sem[k])
                   + float(costo_maq[k]) + float(costo_obra[k])) * parcela["area_ha"]
            )
            margen = ingreso - costos_totales

            filas.append({
                "id_costo": _uuid(),
                "id_parcela": parcela["id_parcela"],
                "ciclo_agricola": ciclo,
                "cultivo": nombre_cultivo,
                "volumen_agua_total_m3": round(v_total, 2),
                "costo_agua_mxn": round(c_agua, 2),
                "costo_fertilizantes_mxn": round(float(costo_fer[k]) * parcela["area_ha"], 2),
                "costo_agroquimicos_mxn":  round(float(costo_agr[k]) * parcela["area_ha"], 2),
                "costo_semilla_mxn":       round(float(costo_sem[k]) * parcela["area_ha"], 2),
                "costo_maquinaria_mxn":    round(float(costo_maq[k]) * parcela["area_ha"], 2),
                "costo_mano_obra_mxn":     round(float(costo_obra[k]) * parcela["area_ha"], 2),
                "ingreso_estimado_mxn":    round(ingreso, 2),
                "margen_contribucion_mxn": round(margen, 2),
            })
            k += 1
    return filas


# ---------------------------------------------------------------------------
# Utilidades de tiempo y clasificación
# ---------------------------------------------------------------------------

def _timestamp_hace(rng: np.random.Generator, max_dias: int) -> str:
    dias = int(rng.integers(0, max_dias))
    horas = int(rng.integers(0, 24))
    mins = int(rng.integers(0, 60))
    ts = datetime.now(timezone.utc) - timedelta(days=dias, hours=horas, minutes=mins)
    return ts.isoformat(timespec="seconds")


def _fecha_hace(rng: np.random.Generator, max_dias: int) -> str:
    dias = int(rng.integers(0, max_dias))
    return (date.today() - timedelta(days=dias)).isoformat()


def _clasificar_urgencia(deficit_mm: float) -> str:
    if deficit_mm > 80:
        return "critico"
    if deficit_mm > 30:
        return "moderado"
    return "preventivo"


def _lamina_ejecutada(aceptada: str, lamina_recomendada: float,
                      rng: np.random.Generator) -> str:
    if aceptada == "aceptada":
        return f"{lamina_recomendada:.2f}"
    if aceptada == "modificada":
        return f"{max(0.0, lamina_recomendada * rng.uniform(0.75, 1.25)):.2f}"
    return ""


# ---------------------------------------------------------------------------
# Escritura de CSV
# ---------------------------------------------------------------------------

def escribir_csv(path: Path, filas: list[dict]) -> None:
    if not filas:
        print(f"  [skip] {path.name} (sin filas)")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)
    print(f"  [ok]   {path.name}: {len(filas):>5} filas")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--usuarios",  type=int, default=20)
    ap.add_argument("--parcelas",  type=int, default=80)
    ap.add_argument("--recos-por-parcela",    type=int, default=260)
    ap.add_argument("--riegos-por-parcela",   type=int, default=300)
    ap.add_argument("--ciclos-por-parcela",   type=int, default=10)
    ap.add_argument("--seed",      type=int, default=42)
    ap.add_argument("--out",       type=str,
                    default=str(Path(__file__).resolve().parent.parent
                                / "data" / "synthetic"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    print(f"\nMILPÍN — Generador de datos sintéticos (seed={args.seed})")
    print(f"Salida: {out_dir}\n")

    print("[1/5] cultivos_catalogo")
    cultivos = generar_cultivos_catalogo()
    escribir_csv(out_dir / "cultivos_catalogo.csv", cultivos)

    print("[2/5] usuarios")
    usuarios = generar_usuarios(rng, args.usuarios)
    escribir_csv(out_dir / "usuarios.csv", usuarios)

    print("[3/5] parcelas")
    parcelas = generar_parcelas(rng, args.parcelas, usuarios, cultivos)
    escribir_csv(out_dir / "parcelas.csv", parcelas)

    print("[4/5] recomendaciones")
    recos = generar_recomendaciones(rng, parcelas, cultivos,
                                    args.recos_por_parcela)
    escribir_csv(out_dir / "recomendaciones.csv", recos)

    print("[5/5] historial_riego (por ciclo agrícola)")
    riegos = generar_historial_riego(rng, parcelas, recos,
                                     args.riegos_por_parcela)
    escribir_csv(out_dir / "historial_riego.csv", riegos)

    print("[+]   costos_ciclo")
    costos = generar_costos_ciclo(rng, parcelas, cultivos,
                                  args.ciclos_por_parcela)
    escribir_csv(out_dir / "costos_ciclo.csv", costos)

    # Sanity checks rápidos
    print("\n=== Sanity checks ===")
    areas = [p["area_ha"] for p in parcelas]
    print(f"  area_ha          -> min={min(areas):.2f}  med={np.median(areas):.2f}  max={max(areas):.2f}")
    cc_vs_pmp = all(p["capacidad_campo"] > p["punto_marchitez"] for p in parcelas)
    print(f"  CC > PMP siempre -> {cc_vs_pmp}")

    # Volumen por ciclo (la métrica correcta vs baseline)
    from collections import defaultdict
    vol_por_ciclo: dict[tuple[str, str], float] = defaultdict(float)
    for r in riegos:
        vol_por_ciclo[(r["id_parcela"], r["ciclo_agricola"])] += r["volumen_m3_ha"]
    vols_ciclo = list(vol_por_ciclo.values())
    vols_arr = np.array(vols_ciclo)
    bajo_meta = (vols_arr <= 6000).sum()
    print(f"  total riegos      -> {len(riegos)} filas ({len(riegos)/len(parcelas):.0f} por parcela)")
    print(f"  vol m³/ha/ciclo   -> min={vols_arr.min():.0f}  media={vols_arr.mean():.0f}  "
          f"max={vols_arr.max():.0f}  (baseline={BASELINE_M3_HA_CICLO:.0f})")
    print(f"  bajo meta 6000    -> {bajo_meta}/{len(vols_ciclo)} ({bajo_meta/len(vols_ciclo)*100:.1f}%)")

    pct_aceptada = sum(1 for r in recos if r["aceptada"] == "aceptada") / len(recos)
    print(f"  %recos aceptadas  -> {pct_aceptada:.1%}")
    print()


if __name__ == "__main__":
    main()
