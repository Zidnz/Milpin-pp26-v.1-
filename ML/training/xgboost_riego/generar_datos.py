"""
ml/training/xgboost_riego/generar_datos.py — Generador de datos sintéticos v4

Genera milpin_ciclos_ml.csv: una fila por ciclo agrícola completo.
Fuente canónica para entrenar los modelos XGBoost de planeación de riego
(M1: consumo de agua m3/ha, M2: rendimiento ton/ha).

Arquitectura Camino C:
    - Esta capa (sintética) → entrenamiento ML (600K–1M filas)
    - ETL NASA POWER (real)  → clima_diario en PostgreSQL → frontend y FAO-56

Generador v3 — 10 módulos de complejidad sobre FAO-56:
    1. Regiones        — 5 micro-zonas del Valle del Yaqui (ET0/lluvia/salinidad)
    2. Arquetipos      — 4 tipos de agricultor (eficiente, conservador, negligente, tecnificado)
    3. Kc por etapa    — curva FAO-56 Fig.25 de 4 etapas (no Kc constante)
    4. ENSO            — variabilidad inter-anual reproducible por seed
    5. Drift climático — +0.022 mm/día/año (tendencia Sonora, IMTA 2023)
    6. Salinidad       — estrés independiente FAO-33 Maas & Hoffman 1977
    7. Ascenso capilar — nivel freático < 3.5 m reduce demanda de riego
    8. Eventos extremos — olas de calor, heladas, inundaciones, plagas
    9. Comportamiento  — sobre/sub irrigación según arquetipo + fallas
   10. Ruido IoT       — drift de sensores ET0, lluvia y humedad de suelo

Uso:
    # Benchmark rápido (< 30 s)
    python ml/training/xgboost_riego/generar_datos.py --n 10000

    # Recomendado: balance señal/tiempo
    python ml/training/xgboost_riego/generar_datos.py --n 50000

    # Producción (600K–1M filas; convergencia real a ~80K–150K con v3)
    python ml/training/xgboost_riego/generar_datos.py --n 1000000

    # Con salida personalizada
    python ml/training/xgboost_riego/generar_datos.py --n 500000 \\
        --out data/synthetic/milpin_ciclos_ml.csv \\
        --año-inicio 2014 --año-fin 2026

Nota sobre año_rango:
    Para ML se recomienda 2014–2026 (vs 2020–2026 del ETL real) porque
    una ventana más larga captura más ciclos ENSO y mayor variabilidad
    climática inter-anual, lo que mejora la generalización del modelo.
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── Catálogo FAO-56/33 (fuente de verdad — debe ser consistente con
#    backend/core/balance_hidrico.py y backend/core/llm_orchestrator.py) ──────

# 5 micro-regiones del Valle del Yaqui (DR-041)
# et0_bias: mm/día sobre media regional | lluvia_mult: multiplicador de lluvia
# sal_base: CE base dS/m | wt_m: nivel freático promedio (m) | elev_m: msnm
REGIONES_CONFIG: dict[str, dict] = {
    "Norte":   dict(et0_bias=+0.40, lluvia_mult=0.82, sal_base=0.08, wt_m=3.2, elev_m=35),
    "Sur":     dict(et0_bias=+0.12, lluvia_mult=1.05, sal_base=0.04, wt_m=5.1, elev_m=22),
    "Centro":  dict(et0_bias=+0.00, lluvia_mult=1.00, sal_base=0.05, wt_m=4.6, elev_m=40),
    "Oriente": dict(et0_bias=-0.25, lluvia_mult=1.18, sal_base=0.03, wt_m=6.3, elev_m=85),
    "Costero": dict(et0_bias=+0.28, lluvia_mult=0.88, sal_base=0.14, wt_m=2.4, elev_m=12),
}

# Arquetipos de agricultor
# over_irr_mu: sesgo de sobre-irrigación (fracción; negativo = sub-riego)
# over_irr_sd: varianza personal | p_miss: probabilidad de perder un riego
FARMER_TYPES: dict[str, dict] = {
    "conservador": dict(over_irr_mu=0.22,  over_irr_sd=0.08, p_miss=0.04),
    "eficiente":   dict(over_irr_mu=0.01,  over_irr_sd=0.03, p_miss=0.01),
    "negligente":  dict(over_irr_mu=-0.12, over_irr_sd=0.15, p_miss=0.18),
    "tecnificado": dict(over_irr_mu=0.00,  over_irr_sd=0.02, p_miss=0.005),
}

# Coeficiente de cultivo Kc por etapa fenológica (FAO-56 Allen et al. 1998 Tabla 11)
# f_ini/dev/med/fin: fracción del ciclo total que ocupa cada etapa (suma=1.0)
KC_STAGES: dict[str, dict] = {
    "Maíz":    dict(kc_ini=0.30, kc_dev=0.70, kc_med=1.20, kc_fin=0.60,
                    f_ini=0.10, f_dev=0.30, f_med=0.50, f_fin=0.10),
    "Frijol":  dict(kc_ini=0.40, kc_dev=0.70, kc_med=1.15, kc_fin=0.55,
                    f_ini=0.10, f_dev=0.35, f_med=0.40, f_fin=0.15),
    "Algodón": dict(kc_ini=0.45, kc_dev=0.75, kc_med=1.20, kc_fin=0.60,
                    f_ini=0.08, f_dev=0.30, f_med=0.45, f_fin=0.17),
    "Uva":     dict(kc_ini=0.30, kc_dev=0.65, kc_med=0.85, kc_fin=0.45,
                    f_ini=0.15, f_dev=0.35, f_med=0.35, f_fin=0.15),
    "Chile":   dict(kc_ini=0.40, kc_dev=0.75, kc_med=1.05, kc_fin=0.80,
                    f_ini=0.12, f_dev=0.30, f_med=0.45, f_fin=0.13),
}

# Umbrales de salinidad por cultivo (FAO-33 Maas & Hoffman 1977)
# thresh: CE umbral (dS/m) | slope: % reducción rendimiento por dS/m sobre umbral
SAL_THRESH: dict[str, float] = {
    "Maíz": 1.7, "Frijol": 1.0, "Algodón": 7.7, "Uva": 1.5, "Chile": 1.5,
}
SAL_SLOPE: dict[str, float] = {
    "Maíz": 12.0, "Frijol": 19.0, "Algodón": 5.2, "Uva": 9.6, "Chile": 14.0,
}


def generar_dataset(
    n: int = 50_000,
    seed: int = 42,
    ruido_factor: float = 1.0,
    año_rango: tuple[int, int] = (2014, 2026),
) -> pd.DataFrame:
    """
    Genera n ciclos agrícolas sintéticos aplicando FAO-56/33 con 10 módulos
    de complejidad estadística. Completamente vectorizado (sin bucles Python).

    Parámetros
    ----------
    n            : número de filas (ciclos) a generar
    seed         : semilla reproducible
    ruido_factor : 0.0 = datos perfectos (FAO puro), 1.0 = variabilidad real
    año_rango    : (inicio, fin) para variabilidad ENSO/drift inter-anual

    Retorna
    -------
    pd.DataFrame con columnas compatibles con milpin_ciclos_ml.csv
    (columnas v2 sin cambio de nombre) + columnas nuevas v3.
    """
    rng = np.random.default_rng(seed)

    CULTIVOS = ["Maíz", "Frijol", "Algodón", "Uva", "Chile"]
    SUELOS   = ["franco", "franco-arcilloso", "franco-arenoso", "arcilloso"]
    SISTEMAS = ["gravedad", "aspersion", "goteo", "microaspersion"]
    # Pesos derivados de data/synthetic/parcelas.csv (49/14/5/12 de 80 parcelas).
    # Refleja la realidad del DR-041 donde gravedad domina el área cultivada.
    SISTEMAS_P = [0.6125, 0.1750, 0.0625, 0.1500]
    REGIONES = list(REGIONES_CONFIG.keys())
    FARMERS  = list(FARMER_TYPES.keys())

    CULT = {
        "Maíz":    dict(dias=(130, 150), ky=1.25, ym=10.5,  p_dep=0.55),
        "Frijol":  dict(dias=( 90, 110), ky=1.15, ym=2.5,   p_dep=0.45),
        "Algodón": dict(dias=(165, 200), ky=0.85, ym=4.0,   p_dep=0.65),
        "Uva":     dict(dias=(180, 215), ky=0.85, ym=25.0,  p_dep=0.45),
        "Chile":   dict(dias=(110, 130), ky=1.10, ym=35.0,  p_dep=0.30),
    }
    SUELO = {
        "franco":           dict(cc=0.30, pmp=0.16, ks_mmh=15),
        "franco-arcilloso": dict(cc=0.36, pmp=0.20, ks_mmh=6),
        "franco-arenoso":   dict(cc=0.24, pmp=0.12, ks_mmh=30),
        "arcilloso":        dict(cc=0.42, pmp=0.22, ks_mmh=3),
    }
    # Eficiencias sincronizadas con EFICIENCIA_RIEGO en balance_hidrico.py.
    # v3 usaba gravedad=0.50; corregido a 0.65 para eliminar sesgo entre
    # entrenamiento e inferencia (el modelo aprendía volúmenes ~23% mayores
    # para parcelas de gravedad respecto a lo que calcula la API en prod).
    EFIC = {
        "gravedad": 0.65, "aspersion": 0.80,
        "goteo": 0.90, "microaspersion": 0.82,
    }

    # ── Sampling vectorizado con índices enteros ──────────────────────────
    ci = rng.integers(0, len(CULTIVOS), n)
    si = rng.integers(0, len(SUELOS),   n)
    # Muestreo ponderado: refleja distribución real DR-041 (gravedad dominante).
    ri = rng.choice(len(SISTEMAS), n, p=SISTEMAS_P)
    gi = rng.integers(0, len(REGIONES), n)
    fi = rng.integers(0, len(FARMERS),  n)

    cultivos = np.array(CULTIVOS)[ci]
    suelos   = np.array(SUELOS)[si]
    sistemas = np.array(SISTEMAS)[ri]
    regiones = np.array(REGIONES)[gi]
    farmers  = np.array(FARMERS)[fi]
    años     = rng.integers(año_rango[0], año_rango[1] + 1, n)

    ky_arr  = np.array([CULT[c]["ky"]      for c in CULTIVOS])[ci]
    ym_arr  = np.array([CULT[c]["ym"]      for c in CULTIVOS])[ci]
    dmin    = np.array([CULT[c]["dias"][0] for c in CULTIVOS])[ci]
    dmax    = np.array([CULT[c]["dias"][1] for c in CULTIVOS])[ci]
    cc_arr  = np.array([SUELO[s]["cc"]     for s in SUELOS])[si]
    pmp_arr = np.array([SUELO[s]["pmp"]    for s in SUELOS])[si]
    ks_arr  = np.array([SUELO[s]["ks_mmh"] for s in SUELOS])[si]
    ef_arr  = np.array([EFIC[s]            for s in SISTEMAS])[ri]

    r_et0  = np.array([REGIONES_CONFIG[r]["et0_bias"]    for r in REGIONES])[gi]
    r_lluv = np.array([REGIONES_CONFIG[r]["lluvia_mult"] for r in REGIONES])[gi]
    r_sal  = np.array([REGIONES_CONFIG[r]["sal_base"]    for r in REGIONES])[gi]
    r_wt   = np.array([REGIONES_CONFIG[r]["wt_m"]        for r in REGIONES])[gi]
    r_elev = np.array([REGIONES_CONFIG[r]["elev_m"]      for r in REGIONES])[gi]

    f_mu   = np.array([FARMER_TYPES[f]["over_irr_mu"] for f in FARMERS])[fi]
    f_sd   = np.array([FARMER_TYPES[f]["over_irr_sd"] for f in FARMERS])[fi]
    f_miss = np.array([FARMER_TYPES[f]["p_miss"]      for f in FARMERS])[fi]

    # area_ha dependiente del sistema: gravedad → parcelas grandes (infraestructura
    # de canal); goteo/microaspersión → parcelas pequeñas (inversión por ha mayor).
    # Rangos calibrados para DR-041 Módulo 3: lotes de canal 2-25 ha.
    # Ponderado con SISTEMAS_P → media sintética ~11 ha ≈ media real producción (~10 ha).
    # Versión anterior (gravedad 8-80) generaba media ~34 ha, causando drift PSI=10 falso.
    AREA_RANGO = {
        "gravedad":       (2.0,  25.0),
        "aspersion":      (2.0,  15.0),
        "goteo":          (1.0,  10.0),
        "microaspersion": (1.0,  12.0),
    }
    area_lo = np.array([AREA_RANGO[s][0] for s in SISTEMAS])[ri]
    area_hi = np.array([AREA_RANGO[s][1] for s in SISTEMAS])[ri]
    area_ha = (area_lo + rng.random(n) * (area_hi - area_lo)).round(2)
    doy        = rng.integers(1, 365, n)
    dias_ciclo = (dmin + rng.random(n) * (dmax - dmin)).astype(int)
    prof_raiz  = rng.uniform(0.45, 0.70, n).round(3)

    # ── Módulo 1+4+5: Variabilidad inter-anual (ENSO + drift climático) ──
    año_span = max(año_rango[1] - año_rango[0], 1)
    año_norm = (años - año_rango[0]) / año_span

    # Drift ET0: +0.022 mm/día/año (tendencia climática Sonora — IMTA 2023)
    et0_drift = año_norm * 0.022 * año_span

    # ENSO: índice anual reproducible
    años_unicos = np.arange(año_rango[0], año_rango[1] + 1)
    enso_rng    = np.random.default_rng(seed + 9999)
    enso_vals   = enso_rng.normal(0, 0.28, len(años_unicos))
    enso_arr    = enso_vals[años - año_rango[0]]
    lluvia_enso = 1.0 + enso_arr * 0.35

    mejora_var = 1.0 + año_norm * 0.035  # mejora varietales +0.35%/año

    # ── Módulo 1+2: ET0 multimodal (región + ENSO + drift) ───────────────
    et0_seasonal = 6.0 + 2.5 * np.sin(2 * np.pi * (doy - 81) / 365)
    regimen_seco = enso_arr > 0.15
    et0_regimen  = np.where(
        regimen_seco,
        et0_seasonal * rng.uniform(1.05, 1.28, n),
        et0_seasonal * rng.uniform(0.88, 1.05, n),
    )
    et0_base = et0_regimen + r_et0 + et0_drift + rng.normal(0, 0.55 * ruido_factor, n)
    et0_prom = np.clip(et0_base, 2.8, 11.0).round(3)
    et0_max  = np.clip(et0_prom * rng.uniform(1.15, 1.65, n), et0_prom + 0.3, 12.5).round(3)

    # IoT: drift sensor ET0 (8% registros con bias ±1.5 mm/d)
    iot_et0      = rng.random(n) < 0.08 * ruido_factor
    et0_measured = np.clip(
        et0_prom + np.where(iot_et0, rng.uniform(-1.5, 2.0, n), 0.0),
        1.0, 13.0,
    ).round(3)

    # ── Módulo 1: Lluvia (ENSO + regional + IoT pluviómetro) ─────────────
    es_verano  = (doy >= 152) & (doy <= 273)
    lluvia_raw = np.where(
        es_verano,
        rng.gamma(2.2, 55.0, n) * r_lluv * lluvia_enso,
        rng.gamma(0.9, 18.0, n) * r_lluv * np.clip(0.7 + 0.3 * lluvia_enso, 0.3, 1.5),
    )
    iot_rain = rng.random(n) < 0.03 * ruido_factor
    lluvia   = np.clip(
        np.where(iot_rain, lluvia_raw * rng.uniform(0.0, 0.25, n), lluvia_raw)
        + rng.normal(0, 4.0 * ruido_factor, n),
        0, 400,
    ).round(2)

    # ── Módulo 3: Kc variable por etapa FAO-56 ───────────────────────────
    # Beta(1.5, 1.5): más muestras en mid-season (realismo de campo)
    pos_ciclo = rng.beta(1.5, 1.5, n)
    kc_stage  = np.full(n, 0.7)

    for ci_k, cultivo in enumerate(CULTIVOS):
        mask = ci == ci_k
        if not mask.any():
            continue
        s   = KC_STAGES[cultivo]
        pos = pos_ciclo[mask]
        f1  = s["f_ini"]
        f2  = f1 + s["f_dev"]
        f3  = f2 + s["f_med"]
        kc_w = np.where(
            pos < f1, s["kc_ini"],
            np.where(
                pos < f2,
                s["kc_ini"] + (s["kc_med"] - s["kc_ini"]) * (pos - f1) / s["f_dev"],
                np.where(
                    pos < f3, s["kc_med"],
                    s["kc_med"] + (s["kc_fin"] - s["kc_med"]) * (pos - f2 - s["f_med"]) / s["f_fin"],
                ),
            ),
        )
        kc_stage[mask] = kc_w

    kc_prom = np.clip(
        kc_stage + rng.normal(0, 0.018 * ruido_factor, n), 0.22, 1.30,
    ).round(3)

    # ── Módulo 6: Salinidad (FAO-33 Maas & Hoffman 1977) ─────────────────
    sal_ec  = np.clip(r_sal + rng.gamma(1.5, 1.2, n) * ruido_factor, 0.01, 9.0).round(3)
    sal_th  = np.array([SAL_THRESH[c] for c in CULTIVOS])[ci]
    sal_sl  = np.array([SAL_SLOPE[c]  for c in CULTIVOS])[ci]
    ks_sal  = np.clip(1.0 - sal_sl / 100 * np.maximum(0, sal_ec - sal_th), 0.05, 1.0)

    # ── Módulo 8: Eventos extremos ────────────────────────────────────────
    ola_calor  = rng.random(n) < 0.10 * ruido_factor
    dias_calor = np.where(ola_calor, rng.integers(5, 18, n), 0)
    et0_extra  = np.where(
        ola_calor, et0_prom * rng.uniform(0.22, 0.55, n) * dias_calor / dias_ciclo, 0.0,
    )

    es_invierno = (doy >= 300) | (doy <= 60)
    helada      = (rng.random(n) < 0.06 * ruido_factor) & es_invierno
    f_helada    = np.where(helada, rng.uniform(0.30, 0.75, n), 1.0)

    inundacion   = (rng.random(n) < 0.04 * ruido_factor) & es_verano
    f_inund_agua = np.where(inundacion, rng.uniform(1.10, 1.40, n), 1.0)
    f_inund_rend = np.where(inundacion, rng.uniform(0.50, 0.85, n), 1.0)

    plaga   = rng.random(n) < 0.12 * ruido_factor
    f_plaga = np.where(plaga, rng.uniform(0.60, 0.96, n), 1.0)

    falla_riego = rng.random(n) < f_miss

    # ── Módulo 7: Ascenso capilar y percolación ───────────────────────────
    aporte_capilar = np.where(
        r_wt < 3.5,
        np.clip((3.5 - r_wt) * rng.uniform(0.4, 1.8, n) * dias_ciclo / 100, 0, 80),
        0.0,
    ).round(2)

    perc_frac = np.clip(
        (1 - ef_arr) * 0.35 + (ks_arr / 30.0) * 0.12 + rng.uniform(0, 0.06, n),
        0.02, 0.38,
    ).round(4)

    # ── Features de PLANEACIÓN (estimables al INICIO del ciclo) ─────────
    # Estas son las features que M1 usa como modelo de planeación.
    # No usan datos realizados: solo propiedades del cultivo, suelo y clima
    # histórico promedio. Sin ENSO, sin ruido, sin eventos ocurridos.

    # Kc medio del cultivo (etapa de máximo desarrollo) — determinístico
    kc_medio_cultivo = np.array([KC_STAGES[c]["kc_med"] for c in CULTIVOS])[ci]

    # ET₀ histórica esperada para el período del ciclo
    # Usa el punto medio del ciclo como referencia estacional, más sesgo regional.
    # Sin corrección ENSO (desconocido al inicio) y sin drift inter-anual.
    doy_mid  = (doy + dias_ciclo // 2) % 365
    et0_hist = np.clip(
        6.0 + 2.5 * np.sin(2 * np.pi * (doy_mid - 81) / 365) + r_et0,
        2.5, 10.0,
    ).round(3)

    # Lluvia histórica esperada para el período del ciclo
    # E[lluvia/día] en monzón (DOY 152-273): Gamma(2.2,55) × P(lluvia)=0.28 = 33.88 mm
    # E[lluvia/día] fuera de monzón: Gamma(0.9,18) × P(lluvia)=0.04 = 0.648 mm
    # Escala por r_lluv (multiplicador regional) — sin ENSO.
    es_verano_mid  = (doy_mid >= 152) & (doy_mid <= 273)
    daily_rain_exp = np.where(es_verano_mid, 2.2 * 55.0 * 0.28, 0.9 * 18.0 * 0.04)
    lluvia_hist    = np.clip(daily_rain_exp * dias_ciclo * r_lluv, 0, 500).round(2)

    # ETc estimada y déficit estimado
    etc_estimada    = np.clip(et0_hist * kc_medio_cultivo * dias_ciclo, 100, 2800).round(2)
    deficit_estimado = np.maximum(0, etc_estimada - lluvia_hist).round(2)

    # Features derivadas calculables al inicio
    agua_disp_mm    = (cc_arr - pmp_arr) * prof_raiz * 1000  # mm
    efic_sistema    = ef_arr.copy()
    ratio_dem_suelo = np.clip(etc_estimada / np.maximum(agua_disp_mm, 1.0), 0, 20).round(3)

    # ── Módulo 10: Balance hídrico FAO-56 (integra todos los módulos) ─────
    etc_total = np.clip(
        (et0_prom + et0_extra) * dias_ciclo * kc_prom, 180, 2800,
    ).round(2)

    hum_suelo = np.clip(
        cc_arr * 0.85 + rng.normal(0, 0.028 * ruido_factor, n),
        pmp_arr + 0.01, cc_arr,
    ).round(4)
    iot_hum   = rng.random(n) < 0.05 * ruido_factor
    hum_suelo_m = np.clip(
        hum_suelo + np.where(iot_hum, rng.uniform(-0.05, 0.05, n), 0.0),
        0.04, 0.58,
    ).round(4)

    deficit_prob = np.clip((1 - ef_arr) * 0.28 * ruido_factor, 0, 0.38)
    deficit_hid  = np.where(
        rng.random(n) < deficit_prob,
        rng.beta(1.2, 3.5, n) * 0.55,
        0.0,
    )
    deficit_hid = np.where(
        falla_riego,
        np.clip(deficit_hid + rng.uniform(0.08, 0.32, n), 0, 0.65),
        deficit_hid,
    ).round(4)

    agua_disp = agua_disp_mm  # alias — ya calculado en bloque de planeación

    # ── Módulo 9: Comportamiento del agricultor ───────────────────────────
    over_irr = np.clip(1.0 + f_mu + rng.normal(0, f_sd, n), 0.55, 1.70)

    n_riegos_base = np.clip(
        np.maximum(
            1,
            np.round(
                (etc_total - lluvia - aporte_capilar).clip(0) / (agua_disp * 0.6)
            ).astype(int),
        ) + rng.integers(-1, 3, n),
        1, 48,
    )
    n_riegos = np.where(falla_riego, np.maximum(1, n_riegos_base - 1), n_riegos_base)

    # ── Targets ───────────────────────────────────────────────────────────
    deficit_neto  = np.maximum(0, etc_total - lluvia - aporte_capilar)
    vol_agua_base = deficit_neto * 10 / ef_arr  # mm → m3/ha

    vol_agua = np.clip(
        vol_agua_base * over_irr * f_inund_agua
        * rng.normal(1.0, 0.07 * ruido_factor, n),
        1_200, 28_000,
    ).round(2)

    # FAO-33: estrés hídrico + salinidad + eventos extremos + mejora varietales
    ks_hid      = 1.0 - deficit_hid
    ya_frac     = np.clip(1 - ky_arr * (1 - ks_hid), 0.03, 1.0)
    rendimiento = np.clip(
        ym_arr * ya_frac * ks_sal
        * f_helada * f_inund_rend * f_plaga
        * mejora_var
        * rng.normal(1.0, 0.065 * ruido_factor, n),
        0.12, ym_arr * 1.22,
    ).round(3)

    # ── Output ────────────────────────────────────────────────────────────
    return pd.DataFrame({
        # Columnas v2 (backward compatible con milpin_ciclos_ml.csv anterior)
        "cultivo":                  cultivos,
        "tipo_suelo":               suelos,
        "sistema_riego":            sistemas,
        "area_ha":                  area_ha,
        "dias_ciclo":               dias_ciclo,
        "doy_inicio":               doy,
        "capacidad_campo":          cc_arr,
        "punto_marchitez":          pmp_arr,
        "prof_raiz_m":              prof_raiz,
        "et0_promedio_mmdia":       et0_measured,
        "et0_maximo_mmdia":         et0_max,
        "lluvia_total_mm":          lluvia,
        "etc_total_mm":             etc_total,
        "kc_promedio":              kc_prom,
        "humedad_suelo_promedio":   hum_suelo_m,
        "deficit_hidrico_frac":     deficit_hid,
        "n_riegos":                 n_riegos,
        "volumen_agua_total_m3_ha": vol_agua,
        "rendimiento_real_ton_ha":  rendimiento,
        # ── Features de planeación (inicio de ciclo, sin leakage) ────────
        # Usar estas como FEATURES_AGUA en M1. Las columnas de arriba
        # (et0_promedio_mmdia, lluvia_total_mm, etc_total_mm, n_riegos,
        # deficit_hidrico_frac, humedad_suelo_promedio) son datos realizados
        # — solo válidos para análisis retrospectivo (M3/diagnóstico).
        "kc_medio_cultivo":         kc_medio_cultivo.round(3),
        "et0_hist_mmdia":           et0_hist,
        "lluvia_hist_mm":           lluvia_hist,
        "etc_estimada_mm":          etc_estimada,
        "deficit_estimado_mm":      deficit_estimado,
        "agua_disponible_mm":       agua_disp_mm.round(2),
        "eficiencia_sistema":       efic_sistema.round(3),
        "ratio_demanda_suelo":      ratio_dem_suelo,
        # Columnas nuevas v3
        "region":                   regiones,
        "tipo_agricultor":          farmers,
        "año":                      años,
        "salinidad_ec_dsm":         sal_ec,
        "ks_salinidad":             ks_sal.round(4),
        "aporte_capilar_mm":        aporte_capilar,
        "percolacion_frac":         perc_frac,
        "pos_ciclo_frac":           pos_ciclo.round(3),
        "elev_parcela_m":           np.clip(r_elev + rng.normal(0, 9, n), 0, 200).round(1),        "año_norm":                 año_norm.round(4),
        "ola_calor":                ola_calor.astype(np.int8),
        "helada":                   helada.astype(np.int8),
        "inundacion":               inundacion.astype(np.int8),
        "plaga":                    plaga.astype(np.int8),
        "falla_riego":              falla_riego.astype(np.int8),
    })


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generador de datos sintéticos v3 para MILPÍN ML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python ml/training/xgboost_riego/generar_datos.py --n 50000
  python ml/training/xgboost_riego/generar_datos.py --n 1000000 --año-inicio 2014
        """,
    )
    ap.add_argument("--n",          type=int,   default=50_000,
                    help="Filas a generar (default: 50000)")
    ap.add_argument("--seed",       type=int,   default=42,
                    help="Semilla aleatoria reproducible (default: 42)")
    ap.add_argument("--ruido",      type=float, default=1.0,
                    help="Factor de ruido: 0=FAO puro, 1=variabilidad real (default: 1.0)")
    ap.add_argument("--año-inicio", type=int,   default=2014,
                    help="Año inicio para variabilidad ENSO/drift (default: 2014)")
    ap.add_argument("--año-fin",    type=int,   default=2026,
                    help="Año fin (default: 2026)")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_ml.csv",
        help="Ruta de salida del CSV (default: data/synthetic/milpin_ciclos_ml.csv)",
    )
    args = ap.parse_args()

    año_rango = (args.año_inicio, args.año_fin)
    print(f"Generando {args.n:,} ciclos | seed={args.seed} | "
          f"ruido={args.ruido} | años={año_rango[0]}-{año_rango[1]}")

    t0 = time.perf_counter()
    df = generar_dataset(
        n=args.n,
        seed=args.seed,
        ruido_factor=args.ruido,
        año_rango=año_rango,
    )
    elapsed = time.perf_counter() - t0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    mem_mb = df.memory_usage(deep=True).sum() / 1e6
    print(f"Generados en {elapsed:.1f}s | {df.shape[0]:,} filas x {df.shape[1]} cols | "
          f"{mem_mb:.1f} MB en RAM")
    print(f"Guardado: {args.out}")
    print()
    print("Distribucion por cultivo (targets principales):")
    print(
        df.groupby("cultivo")[["volumen_agua_total_m3_ha", "rendimiento_real_ton_ha"]]
        .agg(["mean", "std"])
        .round(1)
    )


if __name__ == "__main__":
    main()
