# -*- coding: utf-8 -*-
"""
MILPIN Synthetic Dataset Generator  v3
======================================
Approach
--------
* Each parcel x cycle is assigned a TARGET annual gross consumption drawn
  from the FAO-56 ranges in the spec (e.g. Maiz 2025 => 8500-9500 m3/ha).
* That target is distributed across N irrigation events weighted by Kc,
  so sum(volumen_m3ha) per parcel per cycle matches the agronomic reality.
* KPIs compare PV-2025 vs PV-2026 (same season) for agronomic fairness.
"""

import csv
import os
import random
from collections import defaultdict
from datetime import date, timedelta
from uuid import uuid4

random.seed(42)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DB")
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def uid():
    return str(uuid4())


def rnd(lo, hi, dec=2):
    return round(random.uniform(lo, hi), dec)


def write_csv(name, rows, fieldnames):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    kb = os.path.getsize(path) / 1024
    print(f"  SAVED  {name:42s} {len(rows):>5} rows  {kb:>7.1f} KB")


# ---------------------------------------------------------------------------
# Crop catalogue (internal key -> params)
# ---------------------------------------------------------------------------

CROPS = {
    "Maiz": dict(
        id="C001", display="Maiz", cientifico="Zea mays",
        kc_i=0.30, kc_m=1.20, kc_f=0.60,
        d_ini=20, d_des=35, d_med=40, d_fin=30, dur=140,
        rng25=(8500, 9500), rng26=(6000, 7000),
    ),
    "Frijol": dict(
        id="C002", display="Frijol", cientifico="Phaseolus vulgaris",
        kc_i=0.40, kc_m=1.15, kc_f=0.35,
        d_ini=20, d_des=30, d_med=30, d_fin=20, dur=110,
        rng25=(8000, 9500), rng26=(6200, 7200),
    ),
    "Algodon": dict(
        id="C003", display="Algodon", cientifico="Gossypium hirsutum",
        kc_i=0.35, kc_m=1.20, kc_f=0.70,
        d_ini=30, d_des=50, d_med=55, d_fin=45, dur=180,
        rng25=(7500, 8800), rng26=(5800, 6800),
    ),
    "Uva": dict(
        id="C004", display="Uva", cientifico="Vitis vinifera",
        kc_i=0.30, kc_m=0.85, kc_f=0.45,
        d_ini=20, d_des=40, d_med=120, d_fin=35, dur=215,
        rng25=(8500, 10500), rng26=(6500, 7800),
    ),
    "Chile": dict(
        id="C005", display="Chile", cientifico="Capsicum annuum",
        kc_i=0.60, kc_m=1.05, kc_f=0.90,
        d_ini=25, d_des=35, d_med=40, d_fin=25, dur=125,
        rng25=(9000, 10500), rng26=(7000, 8000),
    ),
}

CROP_KEYS = list(CROPS.keys())

EFF_MAP = {
    "Gravedad":      0.65,
    "Aspersion":     0.80,
    "Microaspersion": 0.82,
    "Goteo":         0.90,
}

# Monthly ETo (mm/day) — Sonora / Yaqui Valley
ETO_BASE = {1: 3.5, 2: 4.5, 3: 6.0, 4: 7.5, 5: 8.5, 6: 9.0,
            7: 8.0, 8: 7.5, 9: 6.5, 10: 5.0, 11: 3.8, 12: 3.2}


# ---------------------------------------------------------------------------
# FAO-56 helpers
# ---------------------------------------------------------------------------

def eto_for_date(d: date) -> float:
    return round(ETO_BASE[d.month] + rnd(-0.35, 0.35), 2)


def kc_for_day(ck: str, day: int) -> float:
    c = CROPS[ck]
    t1 = c["d_ini"]
    t2 = t1 + c["d_des"]
    t3 = t2 + c["d_med"]
    if day <= t1:
        return c["kc_i"]
    if day <= t2:
        frac = (day - t1) / c["d_des"]
        return c["kc_i"] + frac * (c["kc_m"] - c["kc_i"])
    if day <= t3:
        return c["kc_m"]
    frac = min(1.0, (day - t3) / max(c["d_fin"], 1))
    return c["kc_m"] + frac * (c["kc_f"] - c["kc_m"])


def etapa_for_day(ck: str, day: int) -> str:
    c = CROPS[ck]
    t1 = c["d_ini"]
    t2 = t1 + c["d_des"]
    t3 = t2 + c["d_med"]
    if day <= t1:
        return "Inicial"
    if day <= t2:
        return "Desarrollo"
    if day <= t3:
        return "Media"
    return "Final"


# ---------------------------------------------------------------------------
# CSV 1 — cultivos_catalogo.csv
# ---------------------------------------------------------------------------

def build_cultivos():
    rows = []
    for ck, c in CROPS.items():
        mid25 = (c["rng25"][0] + c["rng25"][1]) / 2
        mid26 = (c["rng26"][0] + c["rng26"][1]) / 2
        aho = round((mid25 - mid26) / mid25 * 100, 1)
        rows.append(dict(
            id_cultivo=c["id"],
            nombre_comun=c["display"],
            nombre_cientifico=c["cientifico"],
            kc_inicial=c["kc_i"],
            kc_medio=c["kc_m"],
            kc_final=c["kc_f"],
            dias_etapa_inicial=c["d_ini"],
            dias_etapa_desarrollo=c["d_des"],
            dias_etapa_media=c["d_med"],
            dias_etapa_final=c["d_fin"],
            duracion_total_dias=c["dur"],
            consumo_objetivo_m3ha=int(mid26),
            consumo_promedio_2025=int(mid25),
            consumo_promedio_2026=int(mid26),
            ahorro_objetivo_pct=aho,
            cultivo_prioritario=True,
        ))
    write_csv("cultivos_catalogo.csv", rows, list(rows[0].keys()))
    return rows


# ---------------------------------------------------------------------------
# CSV 2 — ciclos_agricolas.csv
# ---------------------------------------------------------------------------

CICLOS = [
    dict(id_ciclo="CIC-2025-PV", ciclo="PV-2025", anio=2025,
         fecha_inicio="2025-03-01", fecha_fin="2025-10-15",
         temporada="Primavera-Verano", milpin_activo=False),
    dict(id_ciclo="CIC-2025-OI", ciclo="OI-2025", anio=2025,
         fecha_inicio="2025-10-20", fecha_fin="2026-04-30",
         temporada="Otono-Invierno", milpin_activo=False),
    dict(id_ciclo="CIC-2026-PV", ciclo="PV-2026", anio=2026,
         fecha_inicio="2026-03-01", fecha_fin="2026-10-20",
         temporada="Primavera-Verano", milpin_activo=True),
]


def build_ciclos():
    write_csv("ciclos_agricolas.csv", CICLOS, list(CICLOS[0].keys()))


# ---------------------------------------------------------------------------
# CSV 3 — parcelas.csv
# ---------------------------------------------------------------------------

MODULOS = ["Modulo 3A", "Modulo 3B", "Modulo 3C", "Modulo 3D"]
SUELOS  = ["Franco-arcilloso", "Franco", "Arcillo-limoso", "Franco-arenoso", "Limoso"]

# 2025 parcel-level system pool (80 entries, shuffled)
POOL_2025 = (["Gravedad"] * 45 + ["Aspersion"] * 18 +
             ["Microaspersion"] * 12 + ["Goteo"] * 5)
POOL_2026 = (["Gravedad"] * 20 + ["Aspersion"] * 22 +
             ["Microaspersion"] * 20 + ["Goteo"] * 18)
random.shuffle(POOL_2025)
random.shuffle(POOL_2026)

BASE_LAT, BASE_LON = 27.48, -110.01


def build_parcelas():
    rows = []
    par_info = {}
    for i in range(1, 81):
        pid     = f"PAR-{i:03d}"
        ck      = random.choice(CROP_KEYS)
        sup     = rnd(5.0, 45.0, 1)
        sr25    = POOL_2025[i - 1]
        sr26    = POOL_2026[i - 1]
        eff25   = EFF_MAP[sr25]
        eff26   = EFF_MAP[sr26]
        suelo   = random.choice(SUELOS)
        cc      = rnd(0.28, 0.42, 3)
        pmp     = rnd(0.12, 0.18, 3)
        ce      = rnd(0.8, 3.5, 2)
        prof    = random.choice([40, 50, 60, 70, 80, 90])
        lat     = round(BASE_LAT + rnd(-0.30, 0.30), 5)
        lon     = round(BASE_LON + rnd(-0.40, 0.40), 5)

        rows.append(dict(
            id_parcela=pid,
            nombre_parcela=f"Parcela {pid}",
            modulo_dr041=random.choice(MODULOS),
            superficie_ha=sup,
            cultivo_actual=CROPS[ck]["display"],
            sistema_riego_2025=sr25,
            sistema_riego_2026=sr26,
            eficiencia_riego_2025=eff25,
            eficiencia_riego_2026=eff26,
            tipo_suelo=suelo,
            conductividad_electrica=ce,
            profundidad_raiz_cm=prof,
            capacidad_campo=cc,
            punto_marchitez=pmp,
            latitud=lat,
            longitud=lon,
            activo=True,
            adopcion_milpin=True,
            anio_registro=2025,
        ))
        par_info[pid] = dict(
            ck=ck, display=CROPS[ck]["display"],
            sup=sup,
            sr25=sr25, eff25=eff25,
            sr26=sr26, eff26=eff26,
        )

    write_csv("parcelas.csv", rows, list(rows[0].keys()))
    return par_info


# ---------------------------------------------------------------------------
# CSV 4 — historial_riego.csv   (MAIN TABLE)
# ---------------------------------------------------------------------------

ORIG_2025 = ["Manual", "Manual", "Manual",
             "Experiencia del operador", "Tradicion"]
ORIG_2026 = ["MILPIN", "MILPIN", "MILPIN",
             "FAO-56 automatizado", "Manual"]

ALERTS_2025 = [
    "Sobre-riego detectado", "Deficit acumulado",
    "Eficiencia baja", "", "", "",
]
ALERTS_2026 = ["", "", "", "", "Deficit leve", ""]


def gen_riegos(ciclo_id: str, start_d: date, end_d: date,
               optimized: bool, par_info: dict) -> list:
    """
    For every parcel, assign a FAO-56-calibrated annual target
    and distribute it across N events weighted by Kc profile.
    """
    rows = []
    is_oi   = "OI" in ciclo_id
    total_d = (end_d - start_d).days

    for pid, info in par_info.items():
        ck      = info["ck"]
        c       = CROPS[ck]
        sup     = info["sup"]
        sr      = info["sr26"] if optimized else info["sr25"]
        eff     = info["eff26"] if optimized else info["eff25"]

        # --- Target gross volume (m3/ha) for this parcel x cycle ----------
        lo, hi  = c["rng26"] if optimized else c["rng25"]
        # Winter cycle: ETo ~35 % lower than summer
        if is_oi:
            lo, hi = int(lo * 0.63), int(hi * 0.63)
        target_gross = rnd(lo, hi, 0)   # m3/ha total for the cycle

        # --- Decide number of events --------------------------------------
        max_possible = max(4, total_d // 8)
        if optimized:
            n_ev = min(random.randint(10, 15), max_possible)
        else:
            n_ev = min(random.randint(8, 14), max_possible)

        # --- Space events across crop growth period -----------------------
        crop_span = min(c["dur"], total_d - 10)
        if crop_span < 20:
            crop_span = total_d - 10
        pool = list(range(5, crop_span))
        if len(pool) < n_ev:
            n_ev = max(3, len(pool))
        event_days = sorted(random.sample(pool, n_ev))

        # --- Kc profile weights -------------------------------------------
        kc_raw = [
            max(0.20, kc_for_day(ck, d) + rnd(-0.04, 0.04))
            for d in event_days
        ]
        kc_sum  = sum(kc_raw)
        weights = [k / kc_sum for k in kc_raw]

        prev_day = 0
        for idx, day in enumerate(event_days):
            evt_date = start_d + timedelta(days=day)
            etapa    = etapa_for_day(ck, day)
            kc       = round(kc_raw[idx], 3)
            eto      = eto_for_date(evt_date)
            etc      = round(eto * kc, 3)

            # Event share of annual target (add 5-15 % noise around weight)
            noise     = rnd(0.88, 1.12)
            vol_m3ha  = round(target_gross * weights[idx] * noise, 1)
            vol_m3ha  = max(40.0, vol_m3ha)

            lamina_bruta = round(vol_m3ha / 10.0, 2)      # mm applied
            lamina_neta  = round(lamina_bruta * eff, 2)   # mm crop-available

            # Interval since last event (days) — needed for FAO-56 check
            interval = max(1, day - prev_day)
            prev_day = day

            # Expected net depth from ETc over interval
            lamina_fao_net = round(etc * interval, 2)
            lamina_fao_brt = round(lamina_fao_net / eff, 2) if eff > 0 else lamina_fao_net

            # Over-irrigation % relative to what FAO-56 would have applied
            if lamina_fao_brt > 0:
                sobre = (lamina_bruta - lamina_fao_brt) / lamina_fao_brt * 100
            else:
                sobre = 0.0

            # Clamp to realistic ranges
            if optimized:
                sobre = round(max(0.0, min(sobre, 10.0)), 1)
            else:
                sobre = round(max(8.0, min(sobre, 32.0)), 1)

            deficit = round(max(0.0, lamina_fao_net - lamina_neta), 2)

            vol_total    = round(vol_m3ha * sup, 1)
            costo_agua   = round(vol_total * 1.68, 2)
            # kWh = m3 * rho*g*H / (pump_eff * 3 600 000)
            # rho=1000, g=9.81, H=80 m, pump_eff=0.70 → factor ≈ 0.3086 kWh/m3
            energia_kwh  = round(vol_total * 0.3086, 1)
            costo_energia = round(energia_kwh * 2.30, 2)

            if optimized:
                origen = random.choice(ORIG_2026)
                cumpl  = random.random() < 0.78
                alerta = random.choice(ALERTS_2026)
            else:
                origen = random.choice(ORIG_2025)
                cumpl  = random.random() < 0.24
                alerta = random.choice(ALERTS_2025)

            rows.append(dict(
                id_riego=uid(),
                id_parcela=pid,
                id_ciclo=ciclo_id,
                fecha_riego=evt_date.isoformat(),
                cultivo=info["display"],
                etapa_fenologica=etapa,
                eto_mm=eto,
                kc=kc,
                etc_mm=etc,
                lamina_neta_mm=lamina_neta,
                lamina_bruta_mm=lamina_bruta,
                eficiencia_riego=eff,
                volumen_m3ha=vol_m3ha,
                volumen_total_m3=vol_total,
                sobre_riego_pct=sobre,
                deficit_hidrico_mm=deficit,
                metodo_riego=sr,
                costo_agua_mxn=costo_agua,
                costo_energia_mxn=costo_energia,
                energia_kwh=energia_kwh,
                origen_decision=origen,
                cumplimiento_fao56=cumpl,
                alerta=alerta,
            ))

    return rows


def build_historial(par_info: dict):
    rows  = []
    rows += gen_riegos("CIC-2025-PV", date(2025, 3, 1),  date(2025, 10, 15), False, par_info)
    rows += gen_riegos("CIC-2025-OI", date(2025, 10, 20), date(2026, 4, 30),  False, par_info)
    rows += gen_riegos("CIC-2026-PV", date(2026, 3, 1),  date(2026, 10, 20), True,  par_info)
    write_csv("historial_riego.csv", rows, list(rows[0].keys()))
    return rows


# ---------------------------------------------------------------------------
# CSV 5 — recomendaciones.csv
# ---------------------------------------------------------------------------

ALGORITMOS  = ["MILPIN-v1.2", "MILPIN-v1.3", "MILPIN-v2.0"]
MIGRACIONES = [
    "Gravedad -> Goteo", "Aspersion -> Goteo",
    "Gravedad -> Microaspersion", "Microaspersion -> Goteo",
    "Mantener sistema actual",
]
EXPLICACIONES = [
    ("Balance hidrico acumulado indica deficit de {d:.1f} mm. "
     "Riego preventivo recomendado en {dias} dias."),
    ("ETo proyectada {e:.1f} mm/dia (horizonte 7 dias). "
     "Kc={k:.2f} etapa {etapa}. Aplicar lamina {lam:.0f} mm."),
    ("FAO-56 detecta inicio etapa media con Kc={k:.2f}. "
     "Incrementar lamina un {pct:.0f}% respecto evento anterior."),
    ("Patron historico + indices climaticos: riego optimo en "
     "{dias} dias evita estres hidrico en etapa {etapa}."),
    ("Optimizacion turno nocturno 22-06 h: reduce evaporacion "
     "estimada 12-15%. Deficit actual {d:.1f} mm."),
    ("Deficit acumulado {d:.1f} mm supera umbral critico. "
     "Riego urgente antes de {dias} dias para evitar dano."),
    ("Score optimizacion {sc:.2f}: migracion {migr} proyecta "
     "ahorro {pct:.0f}% consumo anual con payback < 2 ciclos."),
]


def build_recomendaciones(par_info: dict):
    rows = []
    for pid, info in par_info.items():
        ck  = info["ck"]
        sup = info["sup"]

        for ciclo in CICLOS:
            cid      = ciclo["id_ciclo"]
            is_2026  = ciclo["anio"] == 2026
            n_recs   = random.randint(3, 6) if not is_2026 else random.randint(5, 10)

            start    = date.fromisoformat(ciclo["fecha_inicio"])
            end      = date.fromisoformat(ciclo["fecha_fin"])
            span     = (end - start).days

            eff      = info["eff26"] if is_2026 else info["eff25"]
            sr       = info["sr26"]  if is_2026 else info["sr25"]

            for _ in range(n_recs):
                offset   = random.randint(5, span - 5)
                fgen     = start + timedelta(days=offset)
                friego   = fgen  + timedelta(days=random.randint(1, 5))
                etapa    = etapa_for_day(ck, offset)
                kc       = round(kc_for_day(ck, offset) + rnd(-0.04, 0.04), 3)
                eto      = eto_for_date(fgen)
                etc      = round(eto * kc, 3)
                deficit  = rnd(5.0, 28.0)
                lam_rec  = round(deficit + rnd(3, 10), 2)

                # Gross depth with current system vs optimal (goteo 90 %)
                lam_cur  = round(lam_rec / eff,  2)
                lam_opt  = round(lam_rec / 0.90, 2)
                aho_m3   = round(max(0.0, (lam_cur - lam_opt) * 10.0 * sup), 1)
                aho_mxn  = round(aho_m3 * 1.68,   2)
                aho_kwh  = round(aho_m3 * 0.3086, 2)

                if is_2026:
                    aceptada  = random.choices(
                        ["aceptada", "rechazada", "modificada"],
                        weights=[70, 12, 18])[0]
                    confianza = rnd(0.74, 0.97)
                    score     = rnd(0.72, 0.96)
                    urgencia  = random.choices(
                        ["Alta", "Media", "Baja"], weights=[18, 52, 30])[0]
                else:
                    aceptada  = random.choices(
                        ["aceptada", "rechazada", "modificada", "sin_respuesta"],
                        weights=[28, 32, 20, 20])[0]
                    confianza = rnd(0.38, 0.76)
                    score     = rnd(0.32, 0.70)
                    urgencia  = random.choices(
                        ["Alta", "Media", "Baja"], weights=[42, 38, 20])[0]

                pct_sav  = round((1.0 - eff / 0.90) * 100, 0) if eff < 0.90 else 0.0
                migr_sug = random.choice(MIGRACIONES)
                dias_sug = random.randint(2, 6)
                tmpl     = random.choice(EXPLICACIONES)
                try:
                    expl = tmpl.format(
                        d=deficit, e=eto, k=kc, etapa=etapa,
                        lam=lam_rec, dias=dias_sug, pct=pct_sav,
                        sc=score, migr=migr_sug,
                    )
                except (KeyError, ValueError):
                    expl = tmpl.split("{")[0].strip()

                rows.append(dict(
                    id_recomendacion=uid(),
                    id_parcela=pid,
                    id_ciclo=cid,
                    fecha_generacion=fgen.isoformat(),
                    fecha_riego_sugerida=friego.isoformat(),
                    lamina_recomendada_mm=lam_rec,
                    eto_referencia=eto,
                    etc_calculada=etc,
                    deficit_acumulado_mm=round(deficit, 2),
                    nivel_urgencia=urgencia,
                    algoritmo_version=random.choice(ALGORITMOS),
                    aceptada=aceptada,
                    ahorro_estimado_m3=aho_m3,
                    ahorro_mxn=aho_mxn,
                    ahorro_kwh=aho_kwh,
                    prioridad_tecnificacion=random.choice(["Alta", "Media", "Baja"]),
                    migracion_sugerida=migr_sug,
                    score_optimizacion=round(score, 3),
                    confianza_modelo=round(confianza, 3),
                    explicacion_ia=expl,
                ))

    write_csv("recomendaciones.csv", rows, list(rows[0].keys()))
    return rows


# ---------------------------------------------------------------------------
# CSV 6 — kpis_dashboard.csv
# (PV-2025 vs PV-2026 — same season, agronomically fair comparison)
# ---------------------------------------------------------------------------

def build_kpis(riego_rows: list, par_info: dict):

    rpv25 = [r for r in riego_rows if r["id_ciclo"] == "CIC-2025-PV"]
    rpv26 = [r for r in riego_rows if r["id_ciclo"] == "CIC-2026-PV"]

    def flt(rows, col):
        return [float(r[col]) for r in rows]

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    def pct_true(rows):
        return round(
            100 * sum(1 for r in rows if str(r["cumplimiento_fao56"]) == "True")
            / len(rows), 1) if rows else 0.0

    # -- Consumo promedio m3/ha: avg of per-parcel cycle totals ---------------
    def consumo_por_parcela(rows):
        par_vol = defaultdict(float)
        for r in rows:
            par_vol[r["id_parcela"]] += float(r["volumen_total_m3"])
        return [par_vol[p] / par_info[p]["sup"] for p in par_vol]

    cons_pv25 = round(avg(consumo_por_parcela(rpv25)), 0)
    cons_pv26 = round(avg(consumo_por_parcela(rpv26)), 0)

    vol_pv25  = round(sum(flt(rpv25, "volumen_total_m3")), 0)
    vol_pv26  = round(sum(flt(rpv26, "volumen_total_m3")), 0)

    cost_pv25 = round(sum(flt(rpv25, "costo_agua_mxn")), 0)
    cost_pv26 = round(sum(flt(rpv26, "costo_agua_mxn")), 0)

    kwh_pv25  = round(sum(flt(rpv25, "energia_kwh")), 0)
    kwh_pv26  = round(sum(flt(rpv26, "energia_kwh")), 0)

    cumpl_pv25 = pct_true(rpv25)
    cumpl_pv26 = pct_true(rpv26)

    goteo_pv25 = round(100 * sum(1 for r in rpv25 if r["metodo_riego"] == "Goteo") / len(rpv25), 1)
    goteo_pv26 = round(100 * sum(1 for r in rpv26 if r["metodo_riego"] == "Goteo") / len(rpv26), 1)

    eff_pv25   = round(avg(flt(rpv25, "eficiencia_riego")) * 100, 1)
    eff_pv26   = round(avg(flt(rpv26, "eficiencia_riego")) * 100, 1)

    alert_kws  = ("Sobre-riego detectado", "Eficiencia baja")
    al_pv25    = sum(1 for r in rpv25 if any(k in str(r["alerta"]) for k in alert_kws))
    al_pv26    = sum(1 for r in rpv26 if any(k in str(r["alerta"]) for k in alert_kws))

    def cph(rows):
        par_cost = defaultdict(float)
        for r in rows:
            par_cost[r["id_parcela"]] += float(r["costo_agua_mxn"]) + float(r["costo_energia_mxn"])
        return round(avg([par_cost[p] / par_info[p]["sup"] for p in par_cost]), 0)

    cph_pv25 = cph(rpv25)
    cph_pv26 = cph(rpv26)

    def mejora(a, b, higher_is_better=False):
        if a == 0:
            return 0.0
        raw = ((b - a) / a * 100) if higher_is_better else ((a - b) / a * 100)
        return round(raw, 1)

    kpis = [
        dict(kpi="consumo_promedio_m3ha",
             valor_2025=cons_pv25, valor_2026=cons_pv26,
             mejora_pct=mejora(cons_pv25, cons_pv26)),
        dict(kpi="ahorro_total_m3",
             valor_2025=vol_pv25,  valor_2026=vol_pv26,
             mejora_pct=mejora(vol_pv25, vol_pv26)),
        dict(kpi="ahorro_economico_mxn",
             valor_2025=cost_pv25, valor_2026=cost_pv26,
             mejora_pct=mejora(cost_pv25, cost_pv26)),
        dict(kpi="ahorro_energia_kwh",
             valor_2025=kwh_pv25,  valor_2026=kwh_pv26,
             mejora_pct=mejora(kwh_pv25, kwh_pv26)),
        dict(kpi="cumplimiento_fao56_pct",
             valor_2025=cumpl_pv25, valor_2026=cumpl_pv26,
             mejora_pct=mejora(cumpl_pv25, cumpl_pv26, higher_is_better=True)),
        dict(kpi="adopcion_goteo_pct",
             valor_2025=goteo_pv25, valor_2026=goteo_pv26,
             mejora_pct=mejora(goteo_pv25, goteo_pv26, higher_is_better=True)),
        dict(kpi="eficiencia_promedio_pct",
             valor_2025=eff_pv25,  valor_2026=eff_pv26,
             mejora_pct=mejora(eff_pv25, eff_pv26, higher_is_better=True)),
        dict(kpi="alertas_criticas",
             valor_2025=al_pv25,   valor_2026=al_pv26,
             mejora_pct=mejora(al_pv25, al_pv26)),
        dict(kpi="costo_promedio_ha_mxn",
             valor_2025=cph_pv25,  valor_2026=cph_pv26,
             mejora_pct=mejora(cph_pv25, cph_pv26)),
        dict(kpi="volumen_total_agua_m3",
             valor_2025=vol_pv25,  valor_2026=vol_pv26,
             mejora_pct=mejora(vol_pv25, vol_pv26)),
    ]
    write_csv("kpis_dashboard.csv", kpis, list(kpis[0].keys()))
    return kpis


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nMILPIN Dataset Generator v3")
    print("=" * 55)

    build_cultivos()
    build_ciclos()
    par_info   = build_parcelas()
    riego_rows = build_historial(par_info)
    build_recomendaciones(par_info)
    kpis       = build_kpis(riego_rows, par_info)

    # -- Quick sanity print --------------------------------------------------
    rpv25 = [r for r in riego_rows if r["id_ciclo"] == "CIC-2025-PV"]
    rpv26 = [r for r in riego_rows if r["id_ciclo"] == "CIC-2026-PV"]
    roi25 = [r for r in riego_rows if r["id_ciclo"] == "CIC-2025-OI"]

    def _avg(rows, col):
        v = [float(r[col]) for r in rows]
        return round(sum(v) / len(v), 1) if v else 0

    print("\n--- Sanity check (PV-2025 vs PV-2026, same season) ---")
    print(f"  Records   PV-2025={len(rpv25)}  OI-2025={len(roi25)}  PV-2026={len(rpv26)}")
    print(f"  Avg vol m3/ha/event  PV-2025={_avg(rpv25,'volumen_m3ha')}  "
          f"PV-2026={_avg(rpv26,'volumen_m3ha')}")
    print(f"  Avg sobre-riego %    PV-2025={_avg(rpv25,'sobre_riego_pct')}  "
          f"PV-2026={_avg(rpv26,'sobre_riego_pct')}")
    print(f"  Avg efficiency %     PV-2025={round(_avg(rpv25,'eficiencia_riego')*100,1)}  "
          f"PV-2026={round(_avg(rpv26,'eficiencia_riego')*100,1)}")

    fao25 = round(100 * sum(1 for r in rpv25 if str(r["cumplimiento_fao56"]) == "True") / len(rpv25), 1)
    fao26 = round(100 * sum(1 for r in rpv26 if str(r["cumplimiento_fao56"]) == "True") / len(rpv26), 1)
    print(f"  FAO-56 compliance %  PV-2025={fao25}  PV-2026={fao26}")

    from collections import defaultdict
    def _consumo(rows):
        pv = defaultdict(float)
        ps = {}
        for r in rows:
            pv[r["id_parcela"]] += float(r["volumen_total_m3"])
            ps[r["id_parcela"]] = par_info[r["id_parcela"]]["sup"]
        vals = [pv[p] / ps[p] for p in pv]
        return round(sum(vals) / len(vals), 0)

    print(f"  Avg consumo m3/ha/ciclo  PV-2025={_consumo(rpv25)}  PV-2026={_consumo(rpv26)}")
    print("\n  KPI Summary (PV-2025 vs PV-2026):")
    for k in kpis:
        arrow = "+" if float(str(k["mejora_pct"])) >= 0 else ""
        print(f"    {k['kpi']:35s}  2025={str(k['valor_2025']):>12}  "
              f"2026={str(k['valor_2026']):>12}  mejora={arrow}{k['mejora_pct']}%")

    print(f"\nAll files saved to: {OUT}")
