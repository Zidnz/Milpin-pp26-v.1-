"""
ML/generar_ciclos_ml.py — v4: balance hídrico FAO-56 emergente + 42 features
==============================================================================

Genera milpin_ciclos_ml.csv: una fila por ciclo agrícola completo.

Mejoras vs versiones anteriores
---------------------------------
v1/v2  deficit_hid inyectado aleatoriamente — no emergente del sistema.
v3     Diversidad estadística buena pero balance parcialmente artificioal.
v4 (este archivo):
  - Déficit EMERGENTE: Dr(t) = Dr(t-1) + ETc - lluvia - aporte_capilar.
    No se inyecta, resulta del balance hídrico día a día.
  - Percolación real: Dr post-riego = max(0, Dr - lamina_efectiva).
    Ya no es Dr=0 exacto después del riego.
  - Salinidad (FAO-29): Ks_sal = max(0, 1 - b*(ECe-ECe_thr)/100).
    Reduce ETa independientemente del estrés hídrico.
  - Arquetipos de agricultor: eficiente / moderado / sub_optimo / ineficiente.
    Controlan over_irr_factor y miss_prob para capturar varianza operacional.
  - ENSO + deriva climática: índice ENSO por año modifica lluvia y ETo.
  - 5 regiones DR-041: factores multiplicativos sobre baseline climático.
  - Eventos extremos multiplicativos: ola_calor / helada / inundacion / plaga / falla_riego.
  - Vectorizado numpy: procesa N ciclos en paralelo, loop sólo sobre días.
    600 000 filas en < 60 s en un equipo estándar.
  - 42 columnas que replican la estructura de la versión anterior del CSV.

Uso
---
    python ML/generar_ciclos_ml.py
    python ML/generar_ciclos_ml.py --n 120000 --out data/synthetic/milpin_ciclos_ml.csv
    python ML/generar_ciclos_ml.py --n 120000 --chunk 30000   # menos RAM por lote
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Catálogos FAO-56 / FAO-33 / FAO-29
# ---------------------------------------------------------------------------

CULTIVOS: dict[str, dict] = {
    "Maíz": {
        "kc": (0.30, 1.20, 0.60), "etapas": (25, 40, 45, 30),
        "ky": 1.25, "rend_pot": 10.0, "rend_min": 5.0, "rend_max": 12.0,
        "ec_thr": 1.7, "ec_b": 12.0,   # salinidad umbral (dS/m) y pendiente (% / dS/m)
    },
    "Frijol": {
        "kc": (0.40, 1.15, 0.35), "etapas": (20, 30, 40, 20),
        "ky": 1.15, "rend_pot": 2.0, "rend_min": 0.8, "rend_max": 2.5,
        "ec_thr": 1.0, "ec_b": 19.0,
    },
    "Algodón": {
        "kc": (0.35, 1.20, 0.70), "etapas": (30, 50, 55, 45),
        "ky": 0.85, "rend_pot": 3.5, "rend_min": 1.5, "rend_max": 4.5,
        "ec_thr": 7.7, "ec_b": 5.2,
    },
    "Uva": {
        "kc": (0.30, 0.85, 0.45), "etapas": (30, 60, 75, 50),
        "ky": 0.85, "rend_pot": 22.5, "rend_min": 12.0, "rend_max": 28.0,
        "ec_thr": 1.5, "ec_b": 9.6,
    },
    "Chile": {
        "kc": (0.60, 1.05, 0.90), "etapas": (30, 35, 40, 20),
        "ky": 1.10, "rend_pot": 30.0, "rend_min": 15.0, "rend_max": 40.0,
        "ec_thr": 1.5, "ec_b": 14.0,
    },
}

# CC y PMP (m³/m³), aporte capilar base (mm/día por metro de profundidad)
SUELOS: dict[str, dict] = {
    "arcilloso":        {"cc": 0.42, "pmp": 0.22, "cap_base": 0.55},
    "franco-arcilloso": {"cc": 0.36, "pmp": 0.20, "cap_base": 0.40},
    "franco":           {"cc": 0.30, "pmp": 0.16, "cap_base": 0.25},
    "franco-arenoso":   {"cc": 0.24, "pmp": 0.12, "cap_base": 0.10},
}

EFICIENCIA_RIEGO: dict[str, float] = {
    "gravedad": 0.62, "aspersion": 0.75, "microaspersion": 0.85, "goteo": 0.92,
}

# Probabilidad de sistema por cultivo (basada en estadísticas CONAGUA DR-041)
PROB_RIEGO: dict[str, dict] = {
    "Maíz":    {"gravedad": 0.70, "aspersion": 0.20, "microaspersion": 0.03, "goteo": 0.07},
    "Frijol":  {"gravedad": 0.60, "aspersion": 0.25, "microaspersion": 0.05, "goteo": 0.10},
    "Algodón": {"gravedad": 0.75, "aspersion": 0.15, "microaspersion": 0.03, "goteo": 0.07},
    "Uva":     {"gravedad": 0.10, "aspersion": 0.15, "microaspersion": 0.15, "goteo": 0.60},
    "Chile":   {"gravedad": 0.30, "aspersion": 0.20, "microaspersion": 0.15, "goteo": 0.35},
}

# Regiones DR-041: multiplicadores sobre baseline climático del Módulo 3 (Obregón)
REGIONES: dict[str, dict] = {
    "Módulo 1": {"et0_mult": 1.06, "lluvia_mult": 0.83, "elev_mu": 48, "elev_sd": 10},
    "Módulo 2": {"et0_mult": 1.03, "lluvia_mult": 0.91, "elev_mu": 40, "elev_sd": 8},
    "Módulo 3": {"et0_mult": 1.00, "lluvia_mult": 1.00, "elev_mu": 32, "elev_sd": 7},
    "Módulo 4": {"et0_mult": 0.97, "lluvia_mult": 1.10, "elev_mu": 25, "elev_sd": 6},
    "Módulo 5": {"et0_mult": 0.94, "lluvia_mult": 1.20, "elev_mu": 18, "elev_sd": 5},
}

# ENSO index por año (+= El Niño: menos lluvia, más ET0; -= La Niña: más lluvia)
ENSO_INDEX: dict[int, float] = {
    2014: 0.0, 2015: 1.3, 2016: 0.8, 2017: -0.7, 2018: -0.5,
    2019: 0.3, 2020: -0.9, 2021: -0.8, 2022: 0.6, 2023: 1.1, 2024: 0.1,
}

# Arquetipos de agricultor: factor de sobre-riego y probabilidad de no regar
FARMER_TYPES: dict[str, dict] = {
    "eficiente":   {"over_irr": 1.00, "noise_sd": 0.05, "miss_p": 0.00},
    "moderado":    {"over_irr": 1.06, "noise_sd": 0.09, "miss_p": 0.03},
    "sub_optimo":  {"over_irr": 1.15, "noise_sd": 0.13, "miss_p": 0.09},
    "ineficiente": {"over_irr": 1.30, "noise_sd": 0.18, "miss_p": 0.18},
}
FARMER_PROBS = [0.18, 0.40, 0.27, 0.15]   # dist. en el DR-041

AÑOS = list(range(2014, 2025))             # 11 años de simulación

SUELO_PROBS = [0.28, 0.35, 0.27, 0.10]    # arcilloso, franco-arcilloso, franco, franco-arenoso


# ---------------------------------------------------------------------------
# Helpers FAO-56
# ---------------------------------------------------------------------------

def _kc_curve(info: dict) -> np.ndarray:
    """Curva Kc diaria (ddc) para el cultivo según FAO-56 Fig. 25."""
    kc_ini, kc_med, kc_fin = info["kc"]
    d_ini, d_des, d_med, d_fin = info["etapas"]
    dias = d_ini + d_des + d_med + d_fin

    fin_ini = d_ini
    fin_des = fin_ini + d_des
    fin_med = fin_des + d_med

    kc = np.empty(dias, dtype=np.float32)
    for d in range(dias):
        ddc = d + 1
        if ddc <= fin_ini:
            kc[d] = kc_ini
        elif ddc <= fin_des:
            t = (ddc - fin_ini) / d_des
            kc[d] = kc_ini + t * (kc_med - kc_ini)
        elif ddc <= fin_med:
            kc[d] = kc_med
        else:
            t = (ddc - fin_med) / max(d_fin, 1)
            kc[d] = kc_med + t * (kc_fin - kc_med)
    return kc


def _clima_matrix(
    n: int,
    dias: int,
    doy_inicio: np.ndarray,
    et0_mult: np.ndarray,
    lluvia_mult: np.ndarray,
    enso: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Genera matrices de clima vectorizadas (n, dias):
      - et0_matrix  : ETo diaria (mm/día)
      - lluvia_matrix: precipitación diaria (mm)

    Modelo: sinusoide estacional Valle del Yaqui + ENSO + ruido gaussiano.
    """
    days = np.arange(dias, dtype=np.int32)[np.newaxis, :]              # (1, dias)
    doy = ((doy_inicio[:, np.newaxis] + days - 1) % 365) + 1           # (n, dias)

    # ETo: sinusoide anual (Valle del Yaqui: mín ~2.5mm ene, máx ~7mm jun)
    # Calibrado para media anual ≈ 4.75 mm/día → ~1730 mm/año (CONAGUA Obregón)
    fase = 0.5 * (1.0 + np.sin(2.0 * np.pi * (doy - 80) / 365.0))
    et0 = (2.5 + 4.5 * fase) * et0_mult[:, np.newaxis]
    et0 *= (1.0 + enso[:, np.newaxis] * 0.07)   # El Niño → más calor → más ET0
    et0 += rng.normal(0, 0.5, (n, dias))
    et0 = np.clip(et0, 1.0, 10.0).astype(np.float32)

    # Lluvia: monzón jul-sep (DOY 182-273) + invierno raro
    monsoon = (doy >= 182) & (doy <= 273)
    base_prob = np.where(monsoon, 0.28, 0.04)
    prob = base_prob * lluvia_mult[:, np.newaxis]
    prob *= np.maximum(0.05, 1.0 - enso[:, np.newaxis] * 0.22)  # El Niño → menos lluvia
    prob = np.clip(prob, 0.0, 0.65)

    has_rain = rng.random((n, dias)) < prob
    amt_m = np.minimum(rng.exponential(7.0, (n, dias)), 45.0)   # monzón
    amt_o = np.minimum(rng.exponential(3.0, (n, dias)), 15.0)   # otra época
    lluvia = np.where(has_rain & monsoon, amt_m,
                      np.where(has_rain & ~monsoon, amt_o, 0.0)).astype(np.float32)

    return et0, lluvia


# ---------------------------------------------------------------------------
# Simulación vectorizada de un cultivo
# ---------------------------------------------------------------------------

def simular_cultivo(
    cultivo_nombre: str,
    n: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Simula n ciclos agrícolas completos para un cultivo.
    Todos los n ciclos se procesan en paralelo; el loop es solo sobre días.

    Retorna DataFrame con 42 columnas (misma estructura que milpin_ciclos_ml.csv).
    """
    info     = CULTIVOS[cultivo_nombre]
    dias     = sum(info["etapas"])
    kc_curve = _kc_curve(info)                      # (dias,)

    suelo_nombres = list(SUELOS.keys())
    sistemas_cult  = list(PROB_RIEGO[cultivo_nombre].keys())
    probs_sis      = list(PROB_RIEGO[cultivo_nombre].values())
    regiones       = list(REGIONES.keys())
    farmer_names   = list(FARMER_TYPES.keys())

    # ── Muestras categóricas ────────────────────────────────────────────────
    suelo_idx   = rng.choice(len(suelo_nombres), n, p=SUELO_PROBS)
    sistema_idx = rng.choice(len(sistemas_cult), n, p=probs_sis)
    region_idx  = rng.integers(0, len(regiones), n)
    farmer_idx  = rng.choice(len(farmer_names), n, p=FARMER_PROBS)
    año_arr     = rng.choice(AÑOS, n)

    suelo_arr   = [suelo_nombres[i] for i in suelo_idx]
    sistema_arr = [sistemas_cult[i] for i in sistema_idx]
    region_arr  = [regiones[i] for i in region_idx]
    farmer_arr  = [farmer_names[i] for i in farmer_idx]

    # ── Parámetros edáficos ──────────────────────────────────────────────────
    cc_v     = np.array([SUELOS[s]["cc"]       for s in suelo_arr], dtype=np.float32)
    pmp_v    = np.array([SUELOS[s]["pmp"]      for s in suelo_arr], dtype=np.float32)
    cap_base = np.array([SUELOS[s]["cap_base"] for s in suelo_arr], dtype=np.float32)

    prof_raiz = np.clip(rng.normal(0.55, 0.12, n), 0.25, 1.20).astype(np.float32)
    TAW = (cc_v - pmp_v) * prof_raiz * 1000.0          # mm agua total disponible
    p_v = np.clip(rng.uniform(0.45, 0.62, n), 0.35, 0.70).astype(np.float32)
    RAW = (p_v * TAW).astype(np.float32)

    area_ha    = rng.uniform(5.0, 80.0, n).astype(np.float32)
    doy_inicio = rng.integers(1, 366, n)

    # ── Parámetros de manejo ────────────────────────────────────────────────
    ef_v      = np.array([EFICIENCIA_RIEGO[s] for s in sistema_arr], dtype=np.float32)
    over_irr  = np.array([FARMER_TYPES[f]["over_irr"] for f in farmer_arr], dtype=np.float32)
    noise_sd  = np.array([FARMER_TYPES[f]["noise_sd"] for f in farmer_arr], dtype=np.float32)
    miss_prob = np.array([FARMER_TYPES[f]["miss_p"]   for f in farmer_arr], dtype=np.float32)

    # Percolación: función de eficiencia (sistemas ineficientes pierden más)
    perc_frac = np.clip(0.06 + (1.0 - ef_v) * 0.18 + rng.normal(0, 0.025, n), 0.02, 0.30).astype(np.float32)

    # ── Salinidad (FAO-29) ──────────────────────────────────────────────────
    ec_thr = info["ec_thr"]
    ec_b   = info["ec_b"]
    salin  = np.clip(rng.lognormal(np.log(1.8), 0.55, n), 0.2, 14.0).astype(np.float32)
    ks_sal = np.where(salin > ec_thr,
                      np.maximum(0.0, 1.0 - ec_b * (salin - ec_thr) / 100.0),
                      1.0).astype(np.float32)

    # ── Ascenso capilar ─────────────────────────────────────────────────────
    water_table_m = rng.uniform(0.8, 6.0, n).astype(np.float32)
    cap_factor    = np.maximum(0.0, 1.0 - water_table_m / 5.0)
    # Aporte diario (mm/día), distribuido uniformemente sobre el ciclo
    cap_diario = cap_base * cap_factor * prof_raiz * 0.20   # mm/día
    aporte_capilar_mm = (cap_diario * dias).astype(np.float32)

    # ── Región y clima ──────────────────────────────────────────────────────
    et0_mult   = np.array([REGIONES[r]["et0_mult"]    for r in region_arr], dtype=np.float32)
    lluvia_mult= np.array([REGIONES[r]["lluvia_mult"] for r in region_arr], dtype=np.float32)
    elev_mu    = np.array([REGIONES[r]["elev_mu"]     for r in region_arr], dtype=np.float32)
    elev_sd    = np.array([REGIONES[r]["elev_sd"]     for r in region_arr], dtype=np.float32)
    enso       = np.array([ENSO_INDEX.get(int(y), 0.0) for y in año_arr], dtype=np.float32)
    elev_arr   = np.clip(rng.normal(0, 1, n).astype(np.float32) * elev_sd + elev_mu, 5.0, 200.0)

    # ── Eventos extremos ────────────────────────────────────────────────────
    ola_calor  = (rng.random(n) < 0.09).astype(np.float32)
    helada     = (rng.random(n) < 0.06).astype(np.float32)
    inundacion = (rng.random(n) < 0.03).astype(np.float32)
    plaga      = (rng.random(n) < 0.08).astype(np.float32)
    falla_r    = (rng.random(n) < 0.05).astype(np.float32)

    # Ola de calor → ET0 +20-40% durante el evento (ya en et0_mult)
    et0_mult_hot = et0_mult * (1.0 + ola_calor * rng.uniform(0.18, 0.38, n).astype(np.float32))

    # ── Matrices de clima ───────────────────────────────────────────────────
    et0_mat, lluvia_mat = _clima_matrix(
        n, dias, doy_inicio, et0_mult_hot, lluvia_mult, enso, rng)

    # ── Balance hídrico vectorizado ─────────────────────────────────────────
    Dr        = np.zeros(n, dtype=np.float32)    # déficit inicial (suelo a CC)
    vol_total = np.zeros(n, dtype=np.float32)    # m³/ha acumulado
    etc_total = np.zeros(n, dtype=np.float32)    # ETc acumulada (mm)
    eta_total = np.zeros(n, dtype=np.float32)    # ETa real (con estrés)
    n_riegos  = np.zeros(n, dtype=np.int32)
    kc_sum    = np.zeros(n, dtype=np.float32)
    hum_sum   = np.zeros(n, dtype=np.float32)

    # Falla de equipo: aumenta prob de no regar
    miss_eff  = np.minimum(miss_prob + falla_r * 0.25, 0.60)

    for day in range(dias):
        kc_d     = kc_curve[day]                       # escalar (fijo para el cultivo)
        et0_d    = et0_mat[:, day]                     # (n,)
        lluvia_d = lluvia_mat[:, day] + cap_diario     # + ascenso capilar diario (n,)

        etc = et0_d * kc_d

        # Estrés hídrico (FAO-56 Ks) + salinidad (FAO-29 Ks_sal)
        Ks_hid = np.clip((TAW - Dr) / (TAW - RAW + 0.01), 0.0, 1.0)
        Ks_tot = Ks_hid * ks_sal
        eta    = etc * Ks_tot

        # Balance diario
        Dr = np.clip(Dr + etc - lluvia_d, 0.0, TAW)

        # Humedad volumétrica
        theta  = cc_v - (Dr / (prof_raiz * 1000.0 + 0.01))
        hum_sum += np.clip(theta, pmp_v, cc_v)

        etc_total += etc
        eta_total += eta
        kc_sum    += kc_d

        # ── Evento de riego ────────────────────────────────────────────────
        riego_mask = (Dr >= RAW)
        # El agricultor puede no regar (miss_prob o falla equipo)
        riego_mask &= (rng.random(n).astype(np.float32) >= miss_eff)

        if riego_mask.any():
            # Lámina neta: repone déficit × factor agricultor ± ruido
            noise     = (1.0 + rng.normal(0.0, 1.0, n).astype(np.float32) * noise_sd)
            lam_neta  = Dr * over_irr * np.maximum(0.05, noise)
            lam_neta  = np.where(riego_mask, lam_neta, 0.0)

            # Agua que entra a la zona radicular (descontando percolación)
            lam_ef    = lam_neta * (1.0 - perc_frac)
            # Agua bruta aplicada (lamina neta / eficiencia del sistema)
            lam_bruta = lam_neta / ef_v
            vol_ev    = lam_bruta * 10.0   # mm → m³/ha  (1 mm = 10 m³/ha)

            vol_total  += np.where(riego_mask, vol_ev, 0.0)
            n_riegos   += riego_mask.astype(np.int32)

            # Dr post-riego: se descuenta sólo la lámina efectiva (no toda)
            Dr = np.where(riego_mask, np.maximum(0.0, Dr - lam_ef), Dr)

    # ── Features agregadas del ciclo ────────────────────────────────────────
    et0_prom     = et0_mat.mean(axis=1)
    et0_maximo   = et0_mat.max(axis=1)
    lluvia_total = lluvia_mat.sum(axis=1)
    kc_prom      = kc_sum / dias
    hum_prom     = hum_sum / dias
    deficit_hid  = np.maximum(0.0, 1.0 - eta_total / np.maximum(etc_total, 0.01))

    # ── Baseline histórico regional (estimación pre-simulación) ─────────────
    et0_hist_mu   = 7.2 * et0_mult          # mm/día media histórica regional
    lluvia_hist_d = 260.0 * lluvia_mult / 365.0  # mm/día baseline anual
    etc_est       = info["kc"][1] * et0_hist_mu * dias   # ETc estimada sin simulación
    deficit_est   = np.maximum(0.0, etc_est - lluvia_hist_d * dias)

    # ── Target 1: consumo de agua ────────────────────────────────────────────
    vol_m3_ha = vol_total  # ya en m³/ha (no multiplicar por área)

    # ── Target 2: rendimiento (FAO-33) ──────────────────────────────────────
    ky  = info["ky"]
    ym  = info["rend_pot"]
    ya  = ym * (1.0 - ky * deficit_hid)
    ya  = np.clip(ya, info["rend_min"] * 0.65, info["rend_max"])

    # Eventos extremos reducen rendimiento multiplicativamente
    ya *= (1.0 - helada     * rng.uniform(0.08, 0.42, n).astype(np.float32))
    ya *= (1.0 - inundacion * rng.uniform(0.05, 0.22, n).astype(np.float32))
    ya *= (1.0 - plaga      * rng.uniform(0.08, 0.28, n).astype(np.float32))
    # Ruido agronómico de manejo
    ya *= (1.0 + rng.normal(0.0, 0.07, n).astype(np.float32))
    ya  = np.clip(ya, info["rend_min"] * 0.50, info["rend_max"] * 1.05)

    # ── Features adicionales ────────────────────────────────────────────────
    pos_ciclo_frac = (doy_inicio / 365.0).astype(np.float32)
    año_norm       = ((año_arr - min(AÑOS)) / max(max(AÑOS) - min(AÑOS), 1)).astype(np.float32)

    # ── Construcción del DataFrame (42 columnas, orden igual al CSV original) ─
    df = pd.DataFrame({
        "cultivo":                cultivo_nombre,
        "tipo_suelo":             suelo_arr,
        "sistema_riego":          sistema_arr,
        "area_ha":                np.round(area_ha, 2),
        "dias_ciclo":             dias,
        "doy_inicio":             doy_inicio,
        "capacidad_campo":        np.round(cc_v, 3),
        "punto_marchitez":        np.round(pmp_v, 3),
        "prof_raiz_m":            np.round(prof_raiz, 2),
        "et0_promedio_mmdia":     np.round(et0_prom, 3),
        "et0_maximo_mmdia":       np.round(et0_maximo, 3),
        "lluvia_total_mm":        np.round(lluvia_total, 2),
        "etc_total_mm":           np.round(etc_total, 2),
        "kc_promedio":            np.round(kc_prom, 3),
        "humedad_suelo_promedio": np.round(hum_prom, 4),
        "deficit_hidrico_frac":   np.round(deficit_hid, 4),
        "n_riegos":               n_riegos,
        "volumen_agua_total_m3_ha": np.round(vol_m3_ha, 2),
        "rendimiento_real_ton_ha":  np.round(ya, 3),
        "kc_medio_cultivo":       round(info["kc"][1], 3),
        "et0_hist_mmdia":         np.round(et0_hist_mu, 3),
        "lluvia_hist_mm":         np.round(lluvia_hist_d * dias, 1),
        "etc_estimada_mm":        np.round(etc_est, 1),
        "deficit_estimado_mm":    np.round(deficit_est, 1),
        "agua_disponible_mm":     np.round(TAW, 1),
        "eficiencia_sistema":     np.round(ef_v, 2),
        "ratio_demanda_suelo":    np.round(etc_total / np.maximum(TAW, 1.0), 3),
        "region":                 region_arr,
        "tipo_agricultor":        farmer_arr,
        "año":                    año_arr.astype(int),
        "salinidad_ec_dsm":       np.round(salin, 2),
        "ks_salinidad":           np.round(ks_sal, 4),
        "aporte_capilar_mm":      np.round(aporte_capilar_mm, 2),
        "percolacion_frac":       np.round(perc_frac, 3),
        "pos_ciclo_frac":         np.round(pos_ciclo_frac, 4),
        "elev_parcela_m":         np.round(elev_arr, 1),
        "año_norm":               np.round(año_norm, 4),
        "ola_calor":              ola_calor.astype(int),
        "helada":                 helada.astype(int),
        "inundacion":             inundacion.astype(int),
        "plaga":                  plaga.astype(int),
        "falla_riego":            falla_r.astype(int),
    })

    return df


# ---------------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------------

def generar_dataset(
    n_por_cultivo: int = 120_000,
    seed: int = 42,
    chunk_size: int = 40_000,
) -> pd.DataFrame:
    """
    Genera n_por_cultivo ciclos por cada uno de los 5 cultivos.
    Procesa en lotes (chunk_size) para controlar el uso de RAM.
    """
    partes: list[pd.DataFrame] = []
    rng_global = np.random.default_rng(seed)

    for cultivo in CULTIVOS:
        restante = n_por_cultivo
        lote = 0
        while restante > 0:
            n_lote = min(chunk_size, restante)
            # Seed derivado del cultivo + lote para reproducibilidad
            seed_lote = int(rng_global.integers(0, 2**31))
            rng_lote  = np.random.default_rng(seed_lote)

            t0 = time.perf_counter()
            df_lote = simular_cultivo(cultivo, n_lote, rng_lote)
            dt = time.perf_counter() - t0

            partes.append(df_lote)
            restante -= n_lote
            lote += 1
            print(f"  {cultivo:10s} lote {lote} ({n_lote:>6,} ciclos)  "
                  f"{dt:.1f}s  acum={n_por_cultivo - restante:>7,}/{n_por_cultivo:,}")

    df = pd.concat(partes, ignore_index=True)
    # Mezcla aleatoria final (elimina sesgo de cultivo por posición)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def sanity_checks(df: pd.DataFrame) -> None:
    print("\n=== Sanity checks v4 ===")
    print(f"  Filas totales          : {len(df):,}")
    print(f"  Columnas               : {len(df.columns)}")
    print(f"  Nulos                  : {df.isnull().sum().sum()}")
    print(f"  CC > PMP               : {(df['capacidad_campo'] > df['punto_marchitez']).all()}")
    print(f"  deficit_hid in [0,1]   : {df['deficit_hidrico_frac'].between(0,1).all()}")
    print(f"  vol_agua > 0           : {(df['volumen_agua_total_m3_ha'] > 0).all()}")
    print(f"  n_riegos > 0           : {(df['n_riegos'] > 0).all()}")

    print(f"\n  volumen_agua_total_m3_ha:")
    print(f"    media={df['volumen_agua_total_m3_ha'].mean():,.0f}  "
          f"std={df['volumen_agua_total_m3_ha'].std():,.0f}  "
          f"min={df['volumen_agua_total_m3_ha'].min():,.0f}  "
          f"max={df['volumen_agua_total_m3_ha'].max():,.0f}")

    print(f"\n  rendimiento_real_ton_ha:")
    print(f"    media={df['rendimiento_real_ton_ha'].mean():.2f}  "
          f"std={df['rendimiento_real_ton_ha'].std():.2f}  "
          f"min={df['rendimiento_real_ton_ha'].min():.2f}  "
          f"max={df['rendimiento_real_ton_ha'].max():.2f}")

    bajo_kpi = (df["volumen_agua_total_m3_ha"] <= 6000).sum()
    print(f"\n  Ciclos bajo meta 6000 m³/ha : {bajo_kpi:,} "
          f"({bajo_kpi/len(df)*100:.1f}%)")

    print(f"\n  Distribución tipo_agricultor:")
    for ta, cnt in df["tipo_agricultor"].value_counts().items():
        print(f"    {ta:15s}: {cnt:>7,} ({cnt/len(df)*100:.1f}%)")

    print(f"\n  Correlación deficit_hid → rendimiento : "
          f"{df['deficit_hidrico_frac'].corr(df['rendimiento_real_ton_ha']):.3f}")
    print(f"  Correlación vol_agua → deficit_hid    : "
          f"{df['volumen_agua_total_m3_ha'].corr(df['deficit_hidrico_frac']):.3f}")
    print(f"  Correlación eficiencia → vol_agua     : "
          f"{df['eficiencia_sistema'].corr(df['volumen_agua_total_m3_ha']):.3f}")

    print(f"\n  Comparativa por sistema de riego (vol m³/ha media):")
    print(df.groupby("sistema_riego")["volumen_agua_total_m3_ha"]
          .mean().round(0).sort_values(ascending=False).to_string())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=120_000,
        help="Ciclos por cultivo (default 120 000 → 600 000 total)"
    )
    parser.add_argument(
        "--out", type=str,
        default=str(Path(__file__).resolve().parent.parent / "data" / "synthetic" / "milpin_ciclos_ml.csv"),
        help="Ruta de salida del CSV"
    )
    parser.add_argument(
        "--seed", type=int, default=42
    )
    parser.add_argument(
        "--chunk", type=int, default=40_000,
        help="Ciclos por lote (reduce RAM; default 40 000)"
    )
    args = parser.parse_args()

    n_total = args.n * len(CULTIVOS)
    print(f"\nMILPIN generar_ciclos_ml.py v4")
    print(f"  {args.n:,} ciclos × {len(CULTIVOS)} cultivos = {n_total:,} filas totales")
    print(f"  Salida: {args.out}")
    print(f"  Seed: {args.seed}  |  Chunk: {args.chunk:,}\n")

    t_start = time.perf_counter()
    df = generar_dataset(n_por_cultivo=args.n, seed=args.seed, chunk_size=args.chunk)
    t_gen = time.perf_counter() - t_start

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")

    print(f"\nGuardado: {out}")
    print(f"Tiempo de generacion: {t_gen:.1f}s  |  {n_total/t_gen:,.0f} ciclos/s")

    sanity_checks(df)
