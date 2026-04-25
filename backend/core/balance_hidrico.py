"""
balance_hidrico.py — Motor agronómico de balance hídrico para MILPÍN AgTech v2.0

Implementa el método FAO-56 Penman-Monteith (Allen et al., 1998) para el cálculo
de evapotranspiración de referencia (ETo) y balance hídrico diario.

Referencia principal:
    Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998).
    Crop evapotranspiration — Guidelines for computing crop water requirements.
    FAO Irrigation and Drainage Paper 56. Rome, FAO.

Contexto geográfico por defecto: Valle del Yaqui, Sonora, México
    - Altitud: ~40 m.s.n.m. (Cd. Obregón)
    - Latitud: 27.37°N
"""

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    # Sólo para type hints — pandas se importa lazy dentro de la función
    # vectorizada para no forzar pandas como dependencia del API escalar.
    import pandas as pd


# ---------------------------------------------------------------------------
# Tablas FAO-56: Coeficientes de cultivo (Kc) por etapa fenológica
# Fuente: FAO-56, Tabla 12 (valores típicos para clima semiárido)
# Estructura: {cultivo: {etapas_dias: (ini, des, med, fin), kc: (kc_ini, kc_med, kc_fin)}}
# ---------------------------------------------------------------------------
KC_TABLE = {
    "maiz": {
        "duracion_etapas": (25, 40, 45, 30),   # días por etapa: ini, des, med, fin
        "kc": (0.30, 1.20, 0.60),               # Kc_ini, Kc_med, Kc_fin (FAO-56 Table 12)
    },
    "frijol": {
        "duracion_etapas": (20, 30, 40, 20),
        "kc": (0.40, 1.15, 0.35),
    },
    "algodon": {
        "duracion_etapas": (30, 50, 55, 45),
        "kc": (0.35, 1.20, 0.70),
    },
    "uva": {
        "duracion_etapas": (30, 60, 75, 50),
        "kc": (0.30, 0.85, 0.45),
    },
    "chile": {
        "duracion_etapas": (30, 35, 40, 20),
        "kc": (0.60, 1.05, 0.90),
    },
}


def _presion_atmosferica(altitud: float) -> float:
    """Presión atmosférica (kPa) en función de la altitud (m).
    FAO-56 Ecuación 7."""
    return 101.3 * ((293.0 - 0.0065 * altitud) / 293.0) ** 5.26


def _constante_psicrometrica(presion: float) -> float:
    """Constante psicrométrica γ (kPa/°C).
    FAO-56 Ecuación 8.  γ = 0.000665 * P"""
    return 0.000665 * presion


def _presion_saturacion(temp: float) -> float:
    """Presión de vapor de saturación e°(T) en kPa.
    FAO-56 Ecuación 11.  e°(T) = 0.6108 * exp(17.27*T / (T+237.3))"""
    return 0.6108 * np.exp(17.27 * temp / (temp + 237.3))


def _pendiente_curva_saturacion(temp: float) -> float:
    """Pendiente de la curva de presión de vapor de saturación Δ (kPa/°C).
    FAO-56 Ecuación 13.  Δ = 4098 * e°(T) / (T + 237.3)²"""
    es = _presion_saturacion(temp)
    return 4098.0 * es / (temp + 237.3) ** 2


def _radiacion_extraterrestre(latitud_grados: float, dia_del_ano: int) -> float:
    """Radiación extraterrestre Ra (MJ/m²/día).
    FAO-56 Ecuaciones 21-25.

    Parámetros:
        latitud_grados: latitud en grados decimales (positivo = norte)
        dia_del_ano: día juliano (1-366)
    """
    # Constante solar (MJ/m²/min)
    Gsc = 0.0820

    # Latitud en radianes
    phi = np.radians(latitud_grados)

    # Distancia relativa inversa Tierra-Sol (Ec. 23)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * dia_del_ano / 365.0)

    # Declinación solar (Ec. 24)
    delta = 0.409 * np.sin(2.0 * np.pi * dia_del_ano / 365.0 - 1.39)

    # Ángulo de puesta del sol (Ec. 25)
    ws = np.arccos(-np.tan(phi) * np.tan(delta))

    # Radiación extraterrestre (Ec. 21)
    Ra = (24.0 * 60.0 / np.pi) * Gsc * dr * (
        ws * np.sin(phi) * np.sin(delta)
        + np.cos(phi) * np.cos(delta) * np.sin(ws)
    )
    return float(Ra)


def _radiacion_extraterrestre_array(
    latitud_grados: float,
    dia_del_ano,
):
    """Versión vectorizada de _radiacion_extraterrestre.

    Acepta `dia_del_ano` como escalar, lista o ndarray. No hace cast a float
    para poder operar sobre series largas. Usa exactamente las mismas
    fórmulas FAO-56 Ec. 21-25 que la versión escalar, garantizando que el
    API punto-a-punto y el ETL produzcan resultados idénticos.
    """
    Gsc = 0.0820
    phi = np.radians(latitud_grados)
    J   = np.asarray(dia_del_ano, dtype=float)

    dr      = 1.0 + 0.033 * np.cos(2.0 * np.pi * J / 365.0)
    delta_s = 0.409 * np.sin(2.0 * np.pi * J / 365.0 - 1.39)

    # Guardar contra latitudes extremas donde -tan(phi)*tan(delta) > 1
    arg = -np.tan(phi) * np.tan(delta_s)
    arg = np.clip(arg, -1.0, 1.0)
    ws  = np.arccos(arg)

    Ra = (24.0 * 60.0 / np.pi) * Gsc * dr * (
        ws * np.sin(phi) * np.sin(delta_s)
        + np.cos(phi) * np.cos(delta_s) * np.sin(ws)
    )
    return Ra


def calcular_eto_penman_monteith_serie(
    df: "pd.DataFrame",
    latitud: float = 27.37,
    altitud: float = 40.0,
) -> "pd.Series":
    """Versión vectorizada de Penman-Monteith FAO-56 para ETL masivo.

    Aplica la misma ecuación FAO-56 Ec. 6 que `calcular_eto_penman_monteith`,
    pero operando sobre arrays numpy para procesar miles de días en una sola
    llamada. Reutiliza las funciones privadas del módulo (`_presion_saturacion`,
    `_pendiente_curva_saturacion`, `_presion_atmosferica`, etc.) para garantizar
    consistencia numérica con el API escalar.

    Caso de uso típico: pipeline de ingesta NASA POWER en `tools/nasa_power_etl.py`.

    Parámetros
    ----------
    df : DataFrame con columnas [fecha, t_max, t_min, humedad_rel, viento, radiacion].
         No debe contener NaN en estas columnas — manejar antes de llamar.
         La columna `fecha` puede ser string "YYYY-MM-DD" o datetime.
    latitud : latitud en grados decimales (positivo = norte). Default: 27.37 (Valle del Yaqui).
    altitud : m.s.n.m. del sitio. Default: 40m (Cd. Obregón).

    Retorna
    -------
    pd.Series con ET0 en mm/día, indexada igual que `df`, nombre 'et0'.

    Raises
    ------
    ImportError : si pandas no está instalado.
    KeyError    : si falta alguna columna requerida.
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "pandas es requerido para calcular_eto_penman_monteith_serie. "
            "Instalar con: pip install pandas"
        ) from e

    T_max = df["t_max"].to_numpy(dtype=float)
    T_min = df["t_min"].to_numpy(dtype=float)
    T_med = (T_max + T_min) / 2.0
    HR    = df["humedad_rel"].to_numpy(dtype=float)
    u2    = df["viento"].to_numpy(dtype=float)
    Rs    = df["radiacion"].to_numpy(dtype=float)
    J     = pd.to_datetime(df["fecha"]).dt.dayofyear.to_numpy()

    # ── Presiones de vapor (FAO-56 Ec. 11, 12, 17) ────────────────────────────
    es_max = _presion_saturacion(T_max)
    es_min = _presion_saturacion(T_min)
    es     = (es_max + es_min) / 2.0
    ea     = (HR / 100.0) * es

    # ── Pendiente de la curva de presión de vapor (FAO-56 Ec. 13) ────────────
    delta = _pendiente_curva_saturacion(T_med)

    # ── Constante psicrométrica γ con altitud real (FAO-56 Ec. 7, 8) ─────────
    P     = _presion_atmosferica(altitud)
    gamma = _constante_psicrometrica(P)

    # ── Radiación neta (FAO-56 Ec. 21-40) ────────────────────────────────────
    Ra  = _radiacion_extraterrestre_array(latitud, J)
    Rso = (0.75 + 2e-5 * altitud) * Ra               # FAO-56 Ec. 37
    Rns = (1.0 - 0.23) * Rs                          # FAO-56 Ec. 38 (albedo 0.23)

    sigma = 4.903e-9
    with np.errstate(invalid="ignore", divide="ignore"):
        # Relación Rs/Rso saturada en 1.0 — cielos totalmente despejados
        Rs_Rso_ratio = np.minimum(Rs / np.maximum(Rso, 0.01), 1.0)

    Rnl = (sigma
           * ((T_max + 273.16) ** 4 + (T_min + 273.16) ** 4) / 2.0
           * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0)))
           * (1.35 * Rs_Rso_ratio - 0.35))

    Rn = Rns - Rnl
    G  = 0.0  # flujo de calor del suelo despreciable en promedios diarios

    # ── Penman-Monteith FAO-56 (Ec. 6) ───────────────────────────────────────
    numerador   = (0.408 * delta * (Rn - G)
                   + gamma * (900.0 / (T_med + 273.0)) * u2 * (es - ea))
    denominador = delta + gamma * (1.0 + 0.34 * u2)
    ET0         = np.maximum(numerador / denominador, 0.0)

    return pd.Series(ET0, index=df.index, name="et0")


def calcular_eto_penman_monteith(
    tmax: float,
    tmin: float,
    humedad_rel: float,
    viento_ms: float,
    radiacion_solar_mj: float,
    altitud: float = 40.0,
    latitud: float = 27.37,
    dia_del_ano: int = 1,
) -> float:
    """Evapotranspiración de referencia ETo (mm/día) por el método FAO-56
    Penman-Monteith (Allen et al., 1998, Ecuación 6).

    ETo = [0.408 Δ (Rn - G) + γ (900/(T+273)) u₂ (es - ea)] /
          [Δ + γ (1 + 0.34 u₂)]

    Parámetros:
        tmax: temperatura máxima diaria (°C)
        tmin: temperatura mínima diaria (°C)
        humedad_rel: humedad relativa media (%)
        viento_ms: velocidad del viento a 2m (m/s)
        radiacion_solar_mj: radiación solar incidente Rs (MJ/m²/día)
        altitud: elevación del sitio (m). Default: 40m (Cd. Obregón)
        latitud: latitud del sitio (°N). Default: 27.37 (Valle del Yaqui)
        dia_del_ano: día juliano 1-366. Default: 1

    Retorna:
        ETo en mm/día (float)
    """
    # Temperatura media
    tmean = (tmax + tmin) / 2.0

    # Presión atmosférica y constante psicrométrica (FAO-56 Ec. 7, 8)
    P = _presion_atmosferica(altitud)
    gamma = _constante_psicrometrica(P)

    # Pendiente de la curva de presión de saturación (FAO-56 Ec. 13)
    delta = _pendiente_curva_saturacion(tmean)

    # Presión de vapor de saturación media (FAO-56 Ec. 12)
    es = (_presion_saturacion(tmax) + _presion_saturacion(tmin)) / 2.0

    # Presión de vapor real ea (FAO-56 Ec. 17 — método con HR media)
    ea = es * (humedad_rel / 100.0)

    # Radiación extraterrestre y radiación neta
    Ra = _radiacion_extraterrestre(latitud, dia_del_ano)

    # Radiación de cielo despejado Rso (FAO-56 Ec. 37)
    Rso = (0.75 + 2e-5 * altitud) * Ra

    # Radiación neta de onda corta Rns (FAO-56 Ec. 38; albedo = 0.23)
    Rns = (1.0 - 0.23) * radiacion_solar_mj

    # Radiación neta de onda larga Rnl (FAO-56 Ec. 39)
    # Usa la constante de Stefan-Boltzmann: 4.903e-9 MJ/m²/día/K⁴
    sigma = 4.903e-9
    # Evitar división por cero si Rso es muy pequeño
    Rs_Rso_ratio = min(radiacion_solar_mj / max(Rso, 0.01), 1.0)
    Rnl = sigma * (
        ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0
    ) * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * Rs_Rso_ratio - 0.35)

    # Radiación neta (FAO-56 Ec. 40)
    Rn = Rns - Rnl

    # Flujo de calor del suelo G ≈ 0 para cálculos diarios (FAO-56 recomendación)
    G = 0.0

    # Ecuación FAO-56 Penman-Monteith (Ec. 6)
    numerador = (
        0.408 * delta * (Rn - G)
        + gamma * (900.0 / (tmean + 273.0)) * viento_ms * (es - ea)
    )
    denominador = delta + gamma * (1.0 + 0.34 * viento_ms)

    eto = numerador / denominador

    # ETo no puede ser negativo
    return float(max(eto, 0.0))


def calcular_eto_hargreaves(
    tmax: float,
    tmin: float,
    latitud: float = 27.37,
    dia_del_ano: int = 1,
) -> float:
    """Evapotranspiración de referencia ETo (mm/día) por el método de
    Hargreaves-Samani (1985). Método empírico usado como respaldo cuando
    no se dispone de datos de humedad, viento o radiación.

    FAO-56 Ecuación 52:
        ETo = 0.0023 * (Tmean + 17.8) * (Tmax - Tmin)^0.5 * Ra

    Parámetros:
        tmax: temperatura máxima diaria (°C)
        tmin: temperatura mínima diaria (°C)
        latitud: latitud del sitio (°N). Default: 27.37
        dia_del_ano: día juliano 1-366. Default: 1

    Retorna:
        ETo en mm/día (float)
    """
    tmean = (tmax + tmin) / 2.0

    # Radiación extraterrestre Ra (MJ/m²/día) — se convierte a mm/día equivalentes
    # 1 MJ/m²/día = 0.408 mm/día de evaporación (FAO-56)
    Ra = _radiacion_extraterrestre(latitud, dia_del_ano)

    # Hargreaves usa Ra en mm/día equivalentes
    Ra_mm = Ra * 0.408

    td = tmax - tmin
    if td < 0:
        td = 0.0

    eto = 0.0023 * (tmean + 17.8) * np.sqrt(td) * Ra_mm

    return float(max(eto, 0.0))


def obtener_kc(cultivo: str, dias_desde_siembra: int) -> float:
    """Coeficiente de cultivo Kc según FAO-56 Tabla 12, con interpolación
    lineal en la etapa de desarrollo y la etapa final.

    Etapas fenológicas (FAO-56):
        1. Inicial: Kc = Kc_ini (constante)
        2. Desarrollo: interpolación lineal de Kc_ini → Kc_med
        3. Mediados de temporada: Kc = Kc_med (constante)
        4. Final: interpolación lineal de Kc_med → Kc_fin

    Parámetros:
        cultivo: nombre del cultivo en minúsculas (trigo, maiz, etc.)
        dias_desde_siembra: días transcurridos desde la siembra

    Retorna:
        Kc (float). Si el cultivo no existe, lanza ValueError.
    """
    cultivo = cultivo.lower().strip()
    if cultivo not in KC_TABLE:
        cultivos_validos = ", ".join(KC_TABLE.keys())
        raise ValueError(
            f"Cultivo '{cultivo}' no encontrado. Cultivos disponibles: {cultivos_validos}"
        )

    info = KC_TABLE[cultivo]
    d_ini, d_des, d_med, d_fin = info["duracion_etapas"]
    kc_ini, kc_med, kc_fin = info["kc"]

    # Acumular días por etapa
    fin_ini = d_ini
    fin_des = fin_ini + d_des
    fin_med = fin_des + d_med
    fin_fin = fin_med + d_fin

    if dias_desde_siembra < 0:
        return kc_ini

    if dias_desde_siembra <= fin_ini:
        # Etapa inicial: Kc constante
        return kc_ini

    elif dias_desde_siembra <= fin_des:
        # Etapa de desarrollo: interpolación lineal Kc_ini → Kc_med
        progreso = (dias_desde_siembra - fin_ini) / d_des
        return kc_ini + (kc_med - kc_ini) * progreso

    elif dias_desde_siembra <= fin_med:
        # Mediados de temporada: Kc constante en su máximo
        return kc_med

    elif dias_desde_siembra <= fin_fin:
        # Etapa final: interpolación lineal Kc_med → Kc_fin
        progreso = (dias_desde_siembra - fin_med) / d_fin
        return kc_med + (kc_fin - kc_med) * progreso

    else:
        # Post-cosecha: se asume Kc final
        return kc_fin


def obtener_curva_kc(cultivo: str) -> dict:
    """Retorna la curva Kc completa de un cultivo con rangos de días por etapa.

    Parámetros:
        cultivo: nombre del cultivo

    Retorna:
        dict con las etapas, sus rangos de días y valores de Kc
    """
    cultivo = cultivo.lower().strip()
    if cultivo not in KC_TABLE:
        cultivos_validos = ", ".join(KC_TABLE.keys())
        raise ValueError(
            f"Cultivo '{cultivo}' no encontrado. Cultivos disponibles: {cultivos_validos}"
        )

    info = KC_TABLE[cultivo]
    d_ini, d_des, d_med, d_fin = info["duracion_etapas"]
    kc_ini, kc_med, kc_fin = info["kc"]

    fin_ini = d_ini
    fin_des = fin_ini + d_des
    fin_med = fin_des + d_med
    fin_fin = fin_med + d_fin

    return {
        "cultivo": cultivo,
        "ciclo_total_dias": fin_fin,
        "etapas": [
            {
                "nombre": "inicial",
                "dias": f"1-{fin_ini}",
                "duracion_dias": d_ini,
                "kc": kc_ini,
            },
            {
                "nombre": "desarrollo",
                "dias": f"{fin_ini + 1}-{fin_des}",
                "duracion_dias": d_des,
                "kc_inicio": kc_ini,
                "kc_fin": kc_med,
            },
            {
                "nombre": "mediados",
                "dias": f"{fin_des + 1}-{fin_med}",
                "duracion_dias": d_med,
                "kc": kc_med,
            },
            {
                "nombre": "final",
                "dias": f"{fin_med + 1}-{fin_fin}",
                "duracion_dias": d_fin,
                "kc_inicio": kc_med,
                "kc_fin": kc_fin,
            },
        ],
    }


def calcular_balance_hidrico(
    etc_mm: float,
    precipitacion_mm: float,
    humedad_actual_pct: float,
    capacidad_campo_pct: float,
    punto_marchitez_pct: float,
    profundidad_raiz_m: float = 0.6,
) -> dict:
    """Calcula el balance hídrico diario del suelo y determina la necesidad de riego.

    El agua disponible total (ADT) se define como la diferencia entre capacidad
    de campo y punto de marchitez permanente. El umbral de riego se establece
    en el 50% del agua disponible (criterio común FAO-56 para cultivos de
    sensibilidad media al estrés hídrico).

    Parámetros:
        etc_mm: evapotranspiración del cultivo ETc (mm/día)
        precipitacion_mm: precipitación del día (mm)
        humedad_actual_pct: humedad volumétrica actual del suelo (%)
        capacidad_campo_pct: capacidad de campo del suelo (%)
        punto_marchitez_pct: punto de marchitez permanente (%)
        profundidad_raiz_m: profundidad efectiva de raíces (m). Default: 0.6m

    Retorna:
        dict con: lamina_neta_mm, lamina_bruta_mm, volumen_m3_ha,
                  requiere_riego, deficit_mm, humedad_resultante_pct
    """
    # Agua disponible total (ADT) en la zona radicular
    # ADT = (CC - PMP) * profundidad_raiz * 10  [mm]
    adt_mm = (capacidad_campo_pct - punto_marchitez_pct) * profundidad_raiz_m * 10.0

    # Umbral de riego: 50% del agua disponible (criterio FAO para estrés medio)
    # Humedad umbral = PMP + 0.5 * (CC - PMP)
    umbral_riego_pct = punto_marchitez_pct + 0.50 * (capacidad_campo_pct - punto_marchitez_pct)

    # Humedad resultante después de ETc y precipitación
    # Convertir ETc y precipitación a cambio en humedad volumétrica (%)
    # Δθ(%) = Δlámina(mm) / (profundidad(m) * 10)
    delta_lamina = precipitacion_mm - etc_mm
    delta_humedad = delta_lamina / (profundidad_raiz_m * 10.0)
    humedad_resultante = humedad_actual_pct + delta_humedad

    # No puede exceder capacidad de campo (escurrimiento) ni bajar de PMP
    humedad_resultante = min(humedad_resultante, capacidad_campo_pct)
    humedad_resultante = max(humedad_resultante, punto_marchitez_pct)

    # Déficit: cuánto falta para llegar a capacidad de campo
    deficit_mm = max(0.0, (capacidad_campo_pct - humedad_resultante) * profundidad_raiz_m * 10.0)

    # Lámina neta de riego: agua necesaria para llevar el suelo a CC
    lamina_neta_mm = max(0.0, (capacidad_campo_pct - humedad_actual_pct) * profundidad_raiz_m * 10.0)

    # Lámina bruta: considera eficiencia de aplicación del 75% (riego por surcos/aspersión)
    eficiencia_riego = 0.75
    lamina_bruta_mm = lamina_neta_mm / eficiencia_riego

    # Volumen por hectárea: 1 mm = 10 m³/ha
    volumen_m3_ha = lamina_bruta_mm * 10.0

    # Decisión de riego: ¿la humedad actual está por debajo del umbral?
    requiere_riego = humedad_actual_pct < umbral_riego_pct

    return {
        "lamina_neta_mm": round(lamina_neta_mm, 2),
        "lamina_bruta_mm": round(lamina_bruta_mm, 2),
        "volumen_m3_ha": round(volumen_m3_ha, 2),
        "requiere_riego": requiere_riego,
        "deficit_mm": round(deficit_mm, 2),
        "humedad_resultante_pct": round(humedad_resultante, 2),
    }


def calcular_costo_riego(
    volumen_m3: float,
    profundidad_pozo_m: float = 80.0,
    eficiencia_bomba: float = 0.65,
    costo_kwh: float = 5.0,
) -> dict:
    """Estima el costo energético de bombeo para riego.

    La energía necesaria para elevar un volumen de agua desde una profundidad
    dada se calcula con:
        E (kWh) = V(m³) * H(m) * ρ * g / (η * 3,600,000)
    donde ρ*g = 9810 N/m³ (peso específico del agua).

    Parámetros:
        volumen_m3: volumen de agua a bombear (m³)
        profundidad_pozo_m: profundidad dinámica del pozo (m). Default: 80m
        eficiencia_bomba: eficiencia electromecánica (0-1). Default: 0.65
        costo_kwh: costo de energía eléctrica (MXN/kWh). Default: 5.0
                   Ref: CFE tarifa 9-CU agrícola, horario intermedio 2025-2026

    Retorna:
        dict con: energia_kwh, costo_pesos, costo_por_m3
    """
    # Energía hidráulica: E = V * H * ρ * g / (η * 3,600,000)
    # ρ*g = 9810 N/m³ (peso específico del agua), 3,600,000 J/kWh
    energia_kwh = (volumen_m3 * profundidad_pozo_m * 9810.0) / (
        eficiencia_bomba * 3_600_000.0
    )

    costo_pesos = energia_kwh * costo_kwh
    costo_por_m3 = costo_pesos / max(volumen_m3, 0.001)

    return {
        "energia_kwh": round(energia_kwh, 2),
        "costo_pesos": round(costo_pesos, 2),
        "costo_por_m3": round(costo_por_m3, 4),
    }
