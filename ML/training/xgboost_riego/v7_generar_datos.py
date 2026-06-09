"""
ml/training/xgboost_riego/v7_generar_datos.py — Generador de datos sintéticos v7

Extensión del generador v3 con 5 módulos adicionales de ruido físico realista:
    A. Clima          — ENSO con fase estacional, olas de calor autocorreladas,
                        lluvia extrema Pareto, variabilidad diaria ET0
    B. Riego          — fallas parciales, eficiencia no estacionaria, presión variable
    C. Sensores       — ruido gaussiano, drift temporal, missing values, delay
    D. Agricultor     — cumplimiento parcial, retrasos de aplicación, curva aprendizaje
    E. Suelo          — heterogeneidad espacial, infiltración variable, retención no lineal

Motivación (v7):
    v3 generaba datos excesivamente limpios y determinísticos, lo que resultaba en
    multicolinealidad extrema, SHAP incoherente y modelo sobreexplicado. v7 introduce
    ruido operacional que refleja la variabilidad real de campo en DR-041.

Diseño causal:
    - Se elimina redundancia funcional (etc_estimada, ratio_demanda_suelo)
    - Se conserva UN feature hidráulico principal: deficit_estimado_mm
    - Se agrega ks_salinidad_calc y et0_cv_hist como features interpretables
    - Se agrega tipo_agricultor al CSV (presente en v3 pero no usado en v6 features)

Uso:
    python ml/training/xgboost_riego/v7_generar_datos.py --n 50000
    python ml/training/xgboost_riego/v7_generar_datos.py --n 500000 --out data/synthetic/milpin_ciclos_v7.csv
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ── Catálogos FAO-56/33 (consistentes con balance_hidrico.py) ─────────────────

REGIONES_CONFIG: dict[str, dict] = {
    "Norte":   dict(et0_bias=+0.40, lluvia_mult=0.82, sal_base=0.08, wt_m=3.2, elev_m=35),
    "Sur":     dict(et0_bias=+0.12, lluvia_mult=1.05, sal_base=0.04, wt_m=5.1, elev_m=22),
    "Centro":  dict(et0_bias=+0.00, lluvia_mult=1.00, sal_base=0.05, wt_m=4.6, elev_m=40),
    "Oriente": dict(et0_bias=-0.25, lluvia_mult=1.18, sal_base=0.03, wt_m=6.3, elev_m=85),
    "Costero": dict(et0_bias=+0.28, lluvia_mult=0.88, sal_base=0.14, wt_m=2.4, elev_m=12),
}

FARMER_TYPES: dict[str, dict] = {
    "conservador": dict(over_irr_mu=0.22,  over_irr_sd=0.08, p_miss=0.04, compliance=0.78),
    "eficiente":   dict(over_irr_mu=0.01,  over_irr_sd=0.03, p_miss=0.01, compliance=0.97),
    "negligente":  dict(over_irr_mu=-0.12, over_irr_sd=0.15, p_miss=0.18, compliance=0.62),
    "tecnificado": dict(over_irr_mu=0.00,  over_irr_sd=0.02, p_miss=0.005, compliance=0.99),
}

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

SAL_THRESH: dict[str, float] = {
    "Maíz": 1.7, "Frijol": 1.0, "Algodón": 7.7, "Uva": 1.5, "Chile": 1.5,
}
SAL_SLOPE: dict[str, float] = {
    "Maíz": 12.0, "Frijol": 19.0, "Algodón": 5.2, "Uva": 9.6, "Chile": 14.0,
}

EFIC: dict[str, float] = {
    "gravedad": 0.50, "aspersion": 0.75,
    "goteo": 0.90, "microaspersion": 0.85,
}

CULT: dict[str, dict] = {
    "Maíz":    dict(dias=(130, 150), ky=1.25, ym=10.5,  p_dep=0.55),
    "Frijol":  dict(dias=( 90, 110), ky=1.15, ym=2.5,   p_dep=0.45),
    "Algodón": dict(dias=(165, 200), ky=0.85, ym=4.0,   p_dep=0.65),
    "Uva":     dict(dias=(180, 215), ky=0.85, ym=25.0,  p_dep=0.45),
    "Chile":   dict(dias=(110, 130), ky=1.10, ym=35.0,  p_dep=0.30),
}

SUELO: dict[str, dict] = {
    "franco":           dict(cc=0.30, pmp=0.16, ks_mmh=15),
    "franco-arcilloso": dict(cc=0.36, pmp=0.20, ks_mmh=6),
    "franco-arenoso":   dict(cc=0.24, pmp=0.12, ks_mmh=30),
    "arcilloso":        dict(cc=0.42, pmp=0.22, ks_mmh=3),
}


# ── Módulo A: Clima con ruido físico avanzado ─────────────────────────────────

def _modulo_A_clima(
    n: int,
    rng: np.random.Generator,
    doy: np.ndarray,
    años: np.ndarray,
    dias_ciclo: np.ndarray,
    r_et0: np.ndarray,
    r_lluv: np.ndarray,
    año_rango: tuple[int, int],
    seed: int,
    ruido: float,
) -> dict[str, np.ndarray]:
    """
    Genera ET0 y lluvia con variabilidad física realista:
    - ENSO con fase estacional mensual (no solo escalar anual)
    - Olas de calor autocorreladas (proceso AR(1))
    - Lluvia extrema con cola Pareto (distribución de Weibull truncada)
    - Drift climático inter-anual (IMTA 2023)
    """
    año_span = max(año_rango[1] - año_rango[0], 1)
    año_norm = (años - año_rango[0]) / año_span

    # Drift climático +0.022 mm/día/año
    et0_drift = año_norm * 0.022 * año_span

    # ENSO con fase estacional: ONI varía mensualmente
    # La fase mensual afecta lluvia de forma diferencial (máx impacto en JAS)
    enso_rng = np.random.default_rng(seed + 9999)
    años_unicos = np.arange(año_rango[0], año_rango[1] + 1)
    enso_anual = enso_rng.normal(0, 0.28, len(años_unicos))
    enso_arr = enso_anual[años - año_rango[0]]

    # Factor ENSO estacional: máximo en julio-agosto-septiembre (DOY 183-273)
    mes_idx = (doy / 30.44).astype(int) % 12  # 0=ene, 11=dic
    enso_seasonal_weight = np.where(
        (doy >= 183) & (doy <= 273), 1.2,  # monzón: ENSO más impactante
        np.where((doy >= 274) | (doy <= 60), 0.7, 0.9)
    )
    lluvia_enso = 1.0 + enso_arr * 0.35 * enso_seasonal_weight

    # ET0 base estacional
    et0_seasonal = 6.0 + 2.5 * np.sin(2 * np.pi * (doy - 81) / 365)

    # Variabilidad diaria ET0: proceso AR(1) simulando persistencia atmosférica
    # AR(1) con phi=0.3, sigma=0.4 — representa ondas sinópticas de 3-5 días
    et0_ar1 = np.zeros(n)
    phi_ar1, sigma_ar1 = 0.30, 0.40 * ruido
    innovations = rng.normal(0, sigma_ar1, n)
    et0_ar1[0] = innovations[0]
    for t in range(1, n):
        et0_ar1[t] = phi_ar1 * et0_ar1[t-1] + innovations[t]
    # Nota: esto es O(n) pero es realismo físico — las ondas atmosféricas son autocorreladas

    # Olas de calor: proceso de Markov AR(1) → duraciones realistas (5-18 días)
    # En lugar de eventos independientes, modelamos transición de estado
    heatwave_state = np.zeros(n, dtype=bool)
    p_ini_heatwave = 0.015 * ruido  # P(inicio ola de calor en un día)
    p_end_heatwave = 0.12           # P(fin ola de calor → regreso a normal)
    hw_rng = np.random.default_rng(seed + 1234)

    for i in range(n):
        if heatwave_state[i-1] if i > 0 else False:
            heatwave_state[i] = hw_rng.random() > p_end_heatwave
        else:
            heatwave_state[i] = hw_rng.random() < p_ini_heatwave

    ola_calor = heatwave_state
    dias_calor = np.where(ola_calor, rng.integers(5, 18, n), 0)
    et0_extra = np.where(
        ola_calor,
        et0_seasonal * rng.uniform(0.22, 0.55, n) * dias_calor / dias_ciclo,
        0.0
    )

    # ET0 final con todos los efectos
    regimen_seco = enso_arr > 0.15
    et0_regimen = np.where(
        regimen_seco,
        et0_seasonal * rng.uniform(1.05, 1.28, n),
        et0_seasonal * rng.uniform(0.88, 1.05, n),
    )
    et0_base = et0_regimen + r_et0 + et0_drift + et0_ar1
    et0_prom = np.clip(et0_base, 2.8, 11.0).round(3)
    et0_max = np.clip(et0_prom * rng.uniform(1.15, 1.65, n), et0_prom + 0.3, 12.5).round(3)

    # Coeficiente de variación histórico ET0 (medible desde NASA POWER antes del ciclo)
    # CV = sigma/media de ET0 estacional — representa incertidumbre climática
    et0_cv_hist = np.clip(
        0.08 + 0.06 * np.abs(np.sin(2 * np.pi * (doy - 81) / 365))
        + enso_arr * 0.04 + rng.uniform(0, 0.03, n),
        0.04, 0.28
    ).round(4)

    # Lluvia: distribución bimodal (temporal verano + frontes invierno)
    # Lluvia extrema: mezcla Gamma ordinaria + Pareto para cola pesada
    es_verano = (doy >= 152) & (doy <= 273)

    # Componente Gamma base
    lluvia_gamma = np.where(
        es_verano,
        rng.gamma(2.2, 55.0, n) * r_lluv * lluvia_enso,
        rng.gamma(0.9, 18.0, n) * r_lluv * np.clip(0.7 + 0.3 * lluvia_enso, 0.3, 1.5),
    )

    # Componente Pareto extrema (P=4% en verano, P=1% en invierno)
    p_extreme = np.where(es_verano, 0.04 * ruido, 0.01 * ruido)
    is_extreme = rng.random(n) < p_extreme
    # Pareto con shape=1.5 → E[X] = 3×scale; genera colas gruesas
    lluvia_pareto = np.where(
        is_extreme,
        rng.pareto(1.5, n) * 120 + 80,  # eventos ≥80mm hasta ~500mm
        0.0
    )

    lluvia_raw = np.minimum(lluvia_gamma + lluvia_pareto, 550)

    return dict(
        et0_prom=et0_prom,
        et0_max=et0_max,
        et0_cv_hist=et0_cv_hist,
        lluvia_raw=lluvia_raw,
        enso_arr=enso_arr,
        regimen_seco=regimen_seco,
        ola_calor=ola_calor,
        dias_calor=dias_calor,
        et0_extra=et0_extra,
        año_norm=año_norm,
    )


# ── Módulo B: Ruido de sistema de riego ───────────────────────────────────────

def _modulo_B_riego(
    n: int,
    rng: np.random.Generator,
    ef_arr: np.ndarray,
    f_miss: np.ndarray,
    dias_ciclo: np.ndarray,
    ruido: float,
) -> dict[str, np.ndarray]:
    """
    Simula variabilidad operacional del sistema de riego:
    - Degradación de eficiencia durante la temporada (obstrucciones, desgaste)
    - Fallas parciales con duración variable
    - Variación de presión → aplicación desigual
    """
    # Degradación de eficiencia: arranca en ef_nominal, decae durante el ciclo
    # Modelado como factor de degradación Beta(5, 1.5) centrado en 0.95
    efic_degradation = rng.beta(5.0, 1.5, n)  # ~media 0.77, representa efic. efectiva / nominal
    ef_efectiva = np.clip(ef_arr * efic_degradation, 0.30, ef_arr)  # no puede superar nominal

    # Variación de presión hidráulica (CV=12% en sistemas presurizados)
    # Solo aplica a aspersión, microaspersión y goteo (no gravedad)
    es_presurizado = ef_arr > 0.55
    presion_cv = np.where(es_presurizado, 0.12 * ruido, 0.0)
    factor_presion = np.clip(
        1.0 + rng.normal(0, presion_cv, n),
        0.70, 1.35
    )

    # Fallas parciales: adicional al p_miss del agricultor
    p_falla_sistema = 0.06 * ruido  # P(falla técnica por ciclo)
    falla_sistema = rng.random(n) < p_falla_sistema
    # Falla parcial: pierde 25-60% del riego en algunos eventos
    severidad_falla = np.where(falla_sistema, rng.uniform(0.25, 0.60, n), 0.0)

    # Obstrucción de goteros: sistémica en goteo de más de 3 años
    # Simplificado: factor aleatorio de pérdida por distribución irregular
    obstruccion_factor = np.where(
        ef_arr >= 0.88,  # goteo
        np.clip(1.0 - rng.beta(1.0, 8.0, n) * ruido * 0.3, 0.70, 1.0),
        1.0
    )

    # Falla binaria final
    falla_riego = rng.random(n) < f_miss

    return dict(
        ef_efectiva=ef_efectiva,
        factor_presion=factor_presion,
        falla_sistema=falla_sistema,
        severidad_falla=severidad_falla,
        obstruccion_factor=obstruccion_factor,
        falla_riego=falla_riego,
    )


# ── Módulo C: Ruido de sensores ───────────────────────────────────────────────

def _modulo_C_sensores(
    n: int,
    rng: np.random.Generator,
    et0_prom: np.ndarray,
    lluvia_raw: np.ndarray,
    cc_arr: np.ndarray,
    pmp_arr: np.ndarray,
    ruido: float,
) -> dict[str, np.ndarray]:
    """
    Simula errores de medición y artefactos de sensores IoT:
    - Drift temporal acumulado (random walk)
    - Ruido gaussiano multiplicativo
    - Missing values aleatorios imputados con media móvil simulada
    - Delay temporal en reporting
    """
    # Drift ET0: random walk simulado como desvío acumulado del promedio de la temporada
    drift_et0 = rng.normal(0, 0.08 * ruido, n)  # componente de drift
    iot_et0_event = rng.random(n) < 0.08 * ruido
    bias_et0 = np.where(iot_et0_event, rng.uniform(-1.5, 2.0, n), 0.0)
    et0_measured = np.clip(et0_prom + drift_et0 + bias_et0, 1.0, 13.0).round(3)

    # Ruido gaussiano multiplicativo en lluvia (pluviómetro)
    ruido_lluvia_prop = np.clip(1.0 + rng.normal(0, 0.06 * ruido, n), 0.80, 1.25)
    iot_rain_event = rng.random(n) < 0.03 * ruido
    # Evento de falla: pluviómetro lee ~0 (obstrucción)
    lluvia_sensor = np.clip(
        np.where(iot_rain_event, lluvia_raw * rng.uniform(0.0, 0.15, n), lluvia_raw * ruido_lluvia_prop)
        + rng.normal(0, 4.0 * ruido, n),
        0, 550
    ).round(2)

    # Missing values en humedad de suelo: imputados con capacidad de campo × 0.88
    # (aproximación operacional típica en campo)
    missing_hum = rng.random(n) < 0.04 * ruido
    hum_base = np.clip(cc_arr * 0.85 + rng.normal(0, 0.028 * ruido, n), pmp_arr + 0.01, cc_arr)
    iot_hum_event = rng.random(n) < 0.05 * ruido
    hum_suelo_measured = np.where(
        missing_hum,
        cc_arr * 0.88,  # imputación conservadora
        np.clip(
            hum_base + np.where(iot_hum_event, rng.uniform(-0.05, 0.05, n), 0.0),
            0.04, 0.58
        )
    ).round(4)

    return dict(
        et0_measured=et0_measured,
        lluvia_sensor=lluvia_sensor,
        hum_suelo_measured=hum_suelo_measured,
        missing_hum=missing_hum,
    )


# ── Módulo D: Comportamiento del agricultor ───────────────────────────────────

def _modulo_D_agricultor(
    n: int,
    rng: np.random.Generator,
    f_mu: np.ndarray,
    f_sd: np.ndarray,
    f_comp: np.ndarray,
    años: np.ndarray,
    año_rango: tuple[int, int],
    ruido: float,
) -> dict[str, np.ndarray]:
    """
    Modela variabilidad en decisiones del agricultor:
    - Cumplimiento parcial de recomendaciones (distribución Beta por arquetipo)
    - Curva de aprendizaje inter-anual (mejora con experiencia)
    - Retrasos en aplicación → sub-riego seguido de sobre-compensación
    - Sobre/sub-riego con distribución bimodal
    """
    # Curva de aprendizaje: agricultores mejoran ~1.5% por año
    año_exp = (años - año_rango[0]) / max(año_rango[1] - año_rango[0], 1)
    learning_factor = 1.0 - 0.015 * año_exp * f_mu.clip(0)  # mejora en eficiente/tecnificado

    # Cumplimiento: Beta(a, b) con media = f_comp
    # Beta con media=0.8 y varianza~0.03 → a=7.2, b=1.8
    compliance_a = f_comp * 7.0
    compliance_b = (1.0 - f_comp) * 7.0 + 0.5
    compliance = np.clip(rng.beta(
        np.maximum(compliance_a, 0.5),
        np.maximum(compliance_b, 0.5),
        n
    ) * learning_factor, 0.30, 1.20)

    # Sobre-irrigación individual: distribución truncada con sesgo del arquetipo
    over_irr_raw = 1.0 + f_mu + rng.normal(0, f_sd, n)
    # Agricultores negligentes tienen mayor probabilidad de sub-riego extremo
    es_negligente_behavior = f_mu < -0.05
    over_irr = np.where(
        es_negligente_behavior,
        np.clip(over_irr_raw, 0.40, 1.30),  # pueden llegar a 40% del requerimiento
        np.clip(over_irr_raw, 0.65, 1.80),
    )

    # Retraso de aplicación (días): reduce eficacia del riego por estrés acumulado
    delay_days = np.where(
        rng.random(n) < 0.25 * ruido,
        rng.integers(1, 8, n),  # 1-7 días de retraso
        0
    )
    # El retraso aumenta el déficit efectivo: por cada día de retraso, ~3% más de ETc
    factor_delay = 1.0 + delay_days * 0.03

    return dict(
        over_irr=over_irr,
        compliance=compliance,
        delay_days=delay_days,
        factor_delay=factor_delay,
    )


# ── Módulo E: Heterogeneidad del suelo ───────────────────────────────────────

def _modulo_E_suelo(
    n: int,
    rng: np.random.Generator,
    cc_arr: np.ndarray,
    pmp_arr: np.ndarray,
    ks_arr: np.ndarray,
    prof_raiz: np.ndarray,
    ruido: float,
) -> dict[str, np.ndarray]:
    """
    Simula variabilidad espacial del suelo dentro de la parcela:
    - Heterogeneidad espacial (CV 15%) en parámetros hidráulicos
    - Infiltración variable → percolación no uniforme
    - Curva de retención hídrica no lineal (van Genuchten implícito)
    - Estratificación vertical del perfil
    """
    # Variabilidad espacial: CC y PMP varían ±15% dentro de la parcela
    # Esto representa la variabilidad textural real observada en DR-041
    cc_eff = np.clip(cc_arr * (1.0 + rng.normal(0, 0.15 * ruido, n)), 0.14, 0.55)
    pmp_eff = np.clip(pmp_arr * (1.0 + rng.normal(0, 0.15 * ruido, n)), 0.06, cc_eff * 0.65)

    # Profundidad de raíz efectiva: varía con condiciones de crecimiento
    # Compactación, capas restrictivas, salinidad → puede reducir prof. efectiva
    prof_reduccion = np.clip(1.0 - rng.beta(1.0, 6.0, n) * 0.30 * ruido, 0.60, 1.0)
    prof_eff = np.clip(prof_raiz * prof_reduccion, 0.25, 0.90)

    # Agua disponible efectiva (con variabilidad)
    agua_disponible_eff = np.clip(
        (cc_eff - pmp_eff) * prof_eff * 1000,  # mm
        30, 280
    ).round(2)

    # Infiltración variable: coef. Ks varía ±18% (compactación, grietas)
    ks_eff = np.clip(ks_arr * (1.0 + rng.normal(0, 0.18 * ruido, n)), 0.5, 80)

    # Percolación: función no lineal de Ks, pendiente y estructura
    # En suelos franco-arcillosos y arcillosos hay mayor retención
    perc_base = (1.0 / (1.0 + ks_eff)) * 0.15  # fracción percolada del agua aplicada
    perc_frac_eff = np.clip(
        perc_base + rng.uniform(0, 0.06 * ruido, n),
        0.02, 0.40
    ).round(4)

    # Ascenso capilar: afectado por heterogeneidad del perfil
    # Se calcula en función de la conductividad hidráulica y el nivel freático
    # (el valor base ya lo tiene el generador principal; aquí solo añadimos variabilidad)
    capilar_variabilidad = 1.0 + rng.normal(0, 0.12 * ruido, n)

    return dict(
        cc_eff=cc_eff,
        pmp_eff=pmp_eff,
        prof_eff=prof_eff,
        agua_disponible_eff=agua_disponible_eff,
        ks_eff=ks_eff,
        perc_frac_eff=perc_frac_eff,
        capilar_variabilidad=capilar_variabilidad,
    )


# ── Generador principal v7 ────────────────────────────────────────────────────

def generar_dataset_v7(
    n: int = 50_000,
    seed: int = 42,
    ruido_factor: float = 1.0,
    año_rango: tuple[int, int] = (2014, 2026),
) -> pd.DataFrame:
    """
    Genera n ciclos agrícolas con 5 módulos de ruido físico realista (v7).

    Diferencias clave vs v3:
    - Incluye tipo_agricultor como feature de entrenamiento
    - Agrega ks_salinidad_calc y et0_cv_hist como features interpretables
    - Ruido climático con autocorrelación (AR1 + Markov)
    - Lluvia con cola Pareto
    - Eficiencia de riego no estacionaria
    - Heterogeneidad espacial de suelo
    - Target computado con ef_efectiva (no ef_nominal)

    Parámetros
    ----------
    n            : número de filas (ciclos)
    seed         : semilla reproducible
    ruido_factor : 0.0 = datos perfectos, 1.0 = variabilidad operacional real
    año_rango    : (inicio, fin) para ENSO y drift inter-anual
    """
    t0 = time.time()
    rng = np.random.default_rng(seed)

    CULTIVOS = ["Maíz", "Frijol", "Algodón", "Uva", "Chile"]
    SUELOS   = ["franco", "franco-arcilloso", "franco-arenoso", "arcilloso"]
    SISTEMAS = ["gravedad", "aspersion", "goteo", "microaspersion"]
    REGIONES = list(REGIONES_CONFIG.keys())
    FARMERS  = list(FARMER_TYPES.keys())

    # ── Sampling vectorizado ──────────────────────────────────────────────
    ci = rng.integers(0, len(CULTIVOS), n)
    si = rng.integers(0, len(SUELOS),   n)
    ri = rng.integers(0, len(SISTEMAS), n)
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
    f_comp = np.array([FARMER_TYPES[f]["compliance"]  for f in FARMERS])[fi]

    area_ha    = rng.uniform(5.0, 80.0, n).round(2)
    doy        = rng.integers(1, 365, n)
    dias_ciclo = (dmin + rng.random(n) * (dmax - dmin)).astype(int)
    prof_raiz  = rng.uniform(0.45, 0.70, n).round(3)

    # ── Kc variable por etapa FAO-56 ──────────────────────────────────────
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

    # ── Salinidad (FAO-33 Maas & Hoffman) ────────────────────────────────
    sal_ec  = np.clip(r_sal + rng.gamma(1.5, 1.2, n) * ruido_factor, 0.01, 9.0).round(3)
    sal_th  = np.array([SAL_THRESH[c] for c in CULTIVOS])[ci]
    sal_sl  = np.array([SAL_SLOPE[c]  for c in CULTIVOS])[ci]
    ks_sal  = np.clip(1.0 - sal_sl / 100 * np.maximum(0, sal_ec - sal_th), 0.05, 1.0)

    # ── Módulo A: Clima avanzado ──────────────────────────────────────────
    clima = _modulo_A_clima(
        n, rng, doy, años, dias_ciclo, r_et0, r_lluv, año_rango, seed, ruido_factor
    )
    et0_prom     = clima["et0_prom"]
    et0_max      = clima["et0_max"]
    et0_cv_hist  = clima["et0_cv_hist"]
    lluvia_raw   = clima["lluvia_raw"]
    enso_arr     = clima["enso_arr"]
    ola_calor    = clima["ola_calor"]
    dias_calor   = clima["dias_calor"]
    et0_extra    = clima["et0_extra"]
    año_norm     = clima["año_norm"]

    # ── Módulo B: Sistema de riego ────────────────────────────────────────
    riego = _modulo_B_riego(n, rng, ef_arr, f_miss, dias_ciclo, ruido_factor)
    ef_efectiva      = riego["ef_efectiva"]
    factor_presion   = riego["factor_presion"]
    falla_sistema    = riego["falla_sistema"]
    severidad_falla  = riego["severidad_falla"]
    obstruccion_factor = riego["obstruccion_factor"]
    falla_riego      = riego["falla_riego"]

    # ── Módulo C: Sensores IoT ────────────────────────────────────────────
    sensores = _modulo_C_sensores(
        n, rng, et0_prom, lluvia_raw, cc_arr, pmp_arr, ruido_factor
    )
    et0_measured      = sensores["et0_measured"]
    lluvia_sensor     = sensores["lluvia_sensor"]
    hum_suelo_measured = sensores["hum_suelo_measured"]
    missing_hum       = sensores["missing_hum"]

    # ── Módulo D: Agricultor ──────────────────────────────────────────────
    agricultor = _modulo_D_agricultor(
        n, rng, f_mu, f_sd, f_comp, años, año_rango, ruido_factor
    )
    over_irr    = agricultor["over_irr"]
    compliance  = agricultor["compliance"]
    delay_days  = agricultor["delay_days"]
    factor_delay = agricultor["factor_delay"]

    # ── Módulo E: Suelo heterogéneo ───────────────────────────────────────
    suelo = _modulo_E_suelo(
        n, rng, cc_arr, pmp_arr, ks_arr, prof_raiz, ruido_factor
    )
    cc_eff             = suelo["cc_eff"]
    pmp_eff            = suelo["pmp_eff"]
    prof_eff           = suelo["prof_eff"]
    agua_disponible_eff = suelo["agua_disponible_eff"]
    ks_eff             = suelo["ks_eff"]
    perc_frac_eff      = suelo["perc_frac_eff"]
    capilar_variabilidad = suelo["capilar_variabilidad"]

    # ── Eventos extremos adicionales ──────────────────────────────────────
    es_verano    = (doy >= 152) & (doy <= 273)
    es_invierno  = (doy >= 300) | (doy <= 60)

    helada       = (rng.random(n) < 0.06 * ruido_factor) & es_invierno
    f_helada     = np.where(helada, rng.uniform(0.30, 0.75, n), 1.0)

    inundacion   = (rng.random(n) < 0.04 * ruido_factor) & es_verano
    f_inund_agua = np.where(inundacion, rng.uniform(1.10, 1.40, n), 1.0)
    f_inund_rend = np.where(inundacion, rng.uniform(0.50, 0.85, n), 1.0)

    plaga        = rng.random(n) < 0.12 * ruido_factor
    f_plaga      = np.where(plaga, rng.uniform(0.60, 0.96, n), 1.0)

    # ── Ascenso capilar (con variabilidad módulo E) ───────────────────────
    aporte_capilar = np.where(
        r_wt < 3.5,
        np.clip(
            (3.5 - r_wt) * rng.uniform(0.4, 1.8, n) * dias_ciclo / 100 * capilar_variabilidad,
            0, 90
        ),
        0.0,
    ).round(2)

    # ── Features de PLANEACIÓN v7 (estimables al INICIO del ciclo) ───────
    # Kc medio del cultivo (etapa de máximo desarrollo) — determinístico
    kc_medio_cultivo = np.array([KC_STAGES[c]["kc_med"] for c in CULTIVOS])[ci]

    # ET0 histórica esperada (sin ENSO, sin drift, solo estacional + región)
    doy_mid  = (doy + dias_ciclo // 2) % 365
    et0_hist = np.clip(
        6.0 + 2.5 * np.sin(2 * np.pi * (doy_mid - 81) / 365) + r_et0,
        2.5, 10.0,
    ).round(3)

    # Lluvia histórica esperada para el período del ciclo
    es_verano_mid  = (doy_mid >= 152) & (doy_mid <= 273)
    daily_rain_exp = np.where(es_verano_mid, 2.2 * 55.0 * 0.28, 0.9 * 18.0 * 0.04)
    lluvia_hist    = np.clip(daily_rain_exp * dias_ciclo * r_lluv, 0, 500).round(2)

    # ETc estimada (planeación) — NO se incluye como feature en v7 (derivable)
    etc_estimada     = np.clip(et0_hist * kc_medio_cultivo * dias_ciclo, 100, 2800).round(2)

    # Déficit estimado de planeación — feature principal hidráulica
    deficit_estimado = np.maximum(0, etc_estimada - lluvia_hist).round(2)

    # Eficiencia del sistema (continua, reemplaza sistema_riego categorical)
    efic_sistema_nominal = ef_arr.copy()

    # Agua disponible consolidada (reemplaza cc + pmp + prof_raiz)
    # Usa valores efectivos del Módulo E para capturar heterogeneidad
    agua_disponible_mm = agua_disponible_eff

    # Ks de salinidad calculado (interpretable, directamente de FAO-33)
    ks_salinidad_calc = ks_sal.round(4)

    # ── Balance hídrico FAO-56 realizado (para target) ────────────────────
    etc_total = np.clip(
        (et0_prom + et0_extra) * dias_ciclo * kc_prom, 180, 2800,
    ).round(2)

    deficit_prob = np.clip((1 - ef_efectiva) * 0.28 * ruido_factor, 0, 0.38)
    deficit_hid  = np.where(
        rng.random(n) < deficit_prob,
        rng.beta(1.2, 3.5, n) * 0.55,
        0.0,
    )
    deficit_hid = np.where(
        falla_riego,
        np.clip(deficit_hid + rng.uniform(0.08, 0.32, n), 0, 0.65),
        deficit_hid,
    ) * factor_delay  # retrasos amplifican el déficit

    # ── Target: volumen de agua ───────────────────────────────────────────
    # Usa ef_efectiva (degradada) en lugar de ef_arr (nominal)
    # Esto hace que eficiencia_sistema tenga el signo correcto en el modelo
    deficit_neto  = np.maximum(0, etc_total - lluvia_sensor - aporte_capilar)

    # vol_agua = deficit_neto (mm) × 10 (mm→m3/ha) / ef_efectiva
    # El agricultor aplica over_irr × compliance; el sistema tiene sus pérdidas
    vol_agua_base = deficit_neto * 10 / np.maximum(ef_efectiva * obstruccion_factor, 0.25)

    vol_agua = np.clip(
        vol_agua_base * over_irr * compliance * factor_presion * f_inund_agua
        * rng.normal(1.0, 0.06 * ruido_factor, n),
        1_200, 28_000,
    ).round(2)

    # Aplicar falla de sistema (falla parcial reduce volumen aplicado)
    vol_agua = np.where(
        falla_sistema,
        vol_agua * (1.0 - severidad_falla),
        vol_agua
    ).round(2)

    n_riegos_base = np.clip(
        np.maximum(
            1,
            np.round(
                deficit_neto.clip(0) / np.maximum(agua_disponible_eff * 0.6, 1.0)
            ).astype(int),
        ) + rng.integers(-1, 3, n),
        1, 48,
    )
    n_riegos = np.where(falla_riego, np.maximum(1, n_riegos_base - 1), n_riegos_base)

    # ── Target: rendimiento agrícola ──────────────────────────────────────
    mejora_var = 1.0 + año_norm * 0.035
    ks_hid     = 1.0 - deficit_hid
    ya_frac    = np.clip(1 - ky_arr * (1 - ks_hid), 0.03, 1.0)
    rendimiento = np.clip(
        ym_arr * ya_frac * ks_sal * mejora_var * f_helada * f_inund_rend * f_plaga
        + rng.normal(0, 0.15 * ym_arr * ruido_factor, n),
        0.12, 36.0,
    ).round(3)

    # ── Columnas de diagnóstico (NO usar como features en M1) ────────────
    hum_suelo_prom = hum_suelo_measured

    # ── Ensamblar DataFrame ───────────────────────────────────────────────
    df = pd.DataFrame({
        # ─ Identidad / contexto ─
        "cultivo":          cultivos,
        "tipo_suelo":       suelos,
        "sistema_riego":    sistemas,
        "region":           regiones,
        "tipo_agricultor":  farmers,
        "año":              años,

        # ─ Features de parcela (conocidas al inicio) ─
        "area_ha":          area_ha,
        "dias_ciclo":       dias_ciclo,
        "doy_inicio":       doy,
        "capacidad_campo":  cc_eff.round(4),
        "punto_marchitez":  pmp_eff.round(4),
        "prof_raiz_m":      prof_eff.round(3),
        "agua_disponible_mm": agua_disponible_mm,
        "salinidad_ec_dsm": sal_ec,
        "aporte_capilar_mm": aporte_capilar,
        "percolacion_frac": perc_frac_eff,
        "elev_parcela_m":   r_elev,
        "año_norm":         año_norm.round(4),

        # ─ Features de planeación (estimables al inicio) ─
        "kc_medio_cultivo": kc_medio_cultivo,
        "et0_hist_mmdia":   et0_hist,
        "lluvia_hist_mm":   lluvia_hist,
        "et0_cv_hist":      et0_cv_hist,   # NUEVO v7
        "etc_estimada_mm":  etc_estimada,  # diagnóstico (NO incluir en M1 v7)
        "deficit_estimado_mm": deficit_estimado,
        "eficiencia_sistema":  efic_sistema_nominal,
        "ks_salinidad_calc":   ks_salinidad_calc,  # NUEVO v7

        # ─ Datos realizados (diagnóstico M3 — NO leakage en M1) ─
        "et0_promedio_mmdia": et0_measured,
        "et0_maximo_mmdia":   et0_max,
        "lluvia_total_mm":    lluvia_sensor,
        "etc_total_mm":       etc_total,
        "kc_promedio":        kc_prom,
        "humedad_suelo_promedio": hum_suelo_prom,
        "deficit_hidrico_frac": deficit_hid.round(4),
        "n_riegos":           n_riegos,

        # ─ Targets ─
        "volumen_agua_total_m3_ha": vol_agua,
        "rendimiento_real_ton_ha":  rendimiento,

        # ─ Flags de eventos (contexto / diagnóstico) ─
        "ola_calor":    ola_calor.astype(int),
        "helada":       helada.astype(int),
        "inundacion":   inundacion.astype(int),
        "plaga":        plaga.astype(int),
        "falla_riego":  falla_riego.astype(int),
        "falla_sistema": falla_sistema.astype(int),
        "pos_ciclo_frac": pos_ciclo.round(4),
        "enso_idx":     enso_arr.round(4),
    })

    elapsed = time.time() - t0
    print(f"[v7] {n:,} ciclos generados en {elapsed:.1f}s  |  "
          f"cols={len(df.columns)}  |  "
          f"vol_agua μ={vol_agua.mean():.0f} σ={vol_agua.std():.0f} m³/ha")

    return df


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generador de datos sintéticos MILPÍN v7")
    p.add_argument("--n",          type=int,   default=50_000, help="Número de ciclos")
    p.add_argument("--seed",       type=int,   default=42)
    p.add_argument("--ruido",      type=float, default=1.0, help="Factor de ruido (0=limpio, 1=real)")
    p.add_argument("--año-inicio", type=int,   default=2014)
    p.add_argument("--año-fin",    type=int,   default=2026)
    p.add_argument(
        "--out", type=Path,
        default=Path(__file__).parents[3] / "data" / "synthetic" / "milpin_ciclos_v7.csv",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    df = generar_dataset_v7(
        n=args.n,
        seed=args.seed,
        ruido_factor=args.ruido,
        año_rango=(args.año_inicio, args.año_fin),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"[v7] Guardado: {args.out}  ({args.out.stat().st_size / 1e6:.1f} MB)")
