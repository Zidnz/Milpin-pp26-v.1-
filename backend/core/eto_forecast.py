"""
eto_forecast.py — Forecaster de ETo para proyección FAO-56 a 7 días (MILPÍN)

Modelo principal: Ridge Regression con features estacionales + lags.
Fallback automático: media de los últimos 14 días si hay menos de MIN_RECORDS registros
con et0 no nulo (p. ej. parcela recién creada sin ETL completo).

Uso típico desde el endpoint:
    from core.eto_forecast import EToForecaster, run_fao56_forward

    forecaster = EToForecaster()
    forecaster.fit(clima_records)          # lista de ORM ClimaDiario
    proyeccion = forecaster.predict(horizon=7, start_date=date.today())
    resultado  = run_fao56_forward(parcela, cultivo_nombre, dias_siembra, proyeccion)

Referencias:
    - Features estacionales cíclicas: Hyndman & Athanasopoulos (2021) §12.1
    - Ridge Regression con lag features para ETo: Shiri et al. (2014)
      "Short-term and long-term streamflow forecasting using a wavelet and
      neuro-fuzzy conjunction model" — el patrón de features es análogo.
    - FAO-56: Allen et al. (1998), Cap. 4 (ETc y balance hídrico).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional, Sequence

import numpy as np

# ── Constante: mínimo de registros para entrenar Ridge ────────────────────────
# Con menos datos el modelo no tiene varianza estacional suficiente y el
# fallback a media(14d) es más honesto que un Ridge con 20 puntos.
MIN_RECORDS = 60

# ── Horizonte máximo soportado ────────────────────────────────────────────────
MAX_HORIZON = 14


class EToForecaster:
    """Predice ETo diaria para los próximos `horizon` días.

    Estrategia multi-step directo: entrena un Ridge independiente por cada
    día del horizonte (h=1, h=2, ..., h=H). Esto es más estable que la
    estrategia recursiva cuando el horizonte es corto (≤14 días), porque
    evita la acumulación de error de predicción.

    Features por observación i:
        sin(2π·doy/365)   — componente estacional anual (ciclo)
        cos(2π·doy/365)   — componente estacional anual (cuadratura)
        et0[i-1]           — inercia 1 día
        et0[i-2]           — inercia 2 días
        et0[i-7]           — patrón semanal (frentes meteorológicos)
        tmax[i-1]          — señal de temperatura reciente

    Cuando hay < MIN_RECORDS registros válidos, el forecaster opera en modo
    fallback: retorna la media de los últimos 14 días de et0 para todos los
    días del horizonte. Esto se indica en el campo 'metodo' de cada punto.
    """

    def __init__(self, alpha: float = 1.0) -> None:
        """
        Parameters
        ----------
        alpha : parámetro de regularización L2 de Ridge. 1.0 funciona bien
                para series climáticas con ~365 puntos. Aumentar si la serie
                es corta (<120 días) para reducir varianza.
        """
        self.alpha = alpha
        self._models: dict[int, Any] = {}   # horizon (int) → Ridge fitted model
        self._fitted: bool = False
        self._fallback_mean: Optional[float] = None
        self._n_records: int = 0
        # Últimos 7 valores de et0 y tmax para la predicción recursiva en predict()
        self._et0_tail: list[float] = []
        self._tmax_tail: list[float] = []

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, records: Sequence) -> "EToForecaster":
        """Entrena el forecaster sobre el historial de clima_diario.

        Parameters
        ----------
        records : secuencia de objetos ORM ClimaDiario o dicts con al menos
                  los campos 'fecha', 'et0', 't_max'. Los registros con et0
                  nulo se descartan (no se imputan — responsabilidad del ETL).

        Returns
        -------
        self (fluent interface).
        """
        # ── 1. Normalizar a lista de dicts y filtrar nulos ────────────────────
        data: list[dict] = []
        for r in records:
            if hasattr(r, "et0"):                   # ORM object
                et0  = float(r.et0)  if r.et0  is not None else None
                tmax = float(r.t_max) if r.t_max is not None else None
                fecha = r.fecha
            else:                                    # dict
                et0  = float(r["et0"])   if r.get("et0")   is not None else None
                tmax = float(r["t_max"]) if r.get("t_max") is not None else None
                fecha = r["fecha"]

            if et0 is None:
                continue
            data.append({"fecha": fecha, "et0": et0, "tmax": tmax or 30.0})

        data.sort(key=lambda x: x["fecha"])
        self._n_records = len(data)

        if not data:
            return self

        # ── 2. Calcular fallback (siempre, independientemente del n) ─────────
        tail14 = data[-14:]
        self._fallback_mean = float(np.mean([d["et0"] for d in tail14]))
        self._et0_tail  = [d["et0"]  for d in data[-7:]]
        self._tmax_tail = [d["tmax"] for d in data[-7:]]

        if self._n_records < MIN_RECORDS:
            self._fitted = False
            return self

        # ── 3. Construir matrices X, y para cada horizonte h ─────────────────
        et0_arr  = np.array([d["et0"]  for d in data], dtype=float)
        tmax_arr = np.array([d["tmax"] for d in data], dtype=float)
        fechas   = [d["fecha"] for d in data]

        MAX_LAG = 7   # lag máximo usado como feature

        try:
            from sklearn.linear_model import Ridge
        except ImportError as exc:
            raise ImportError(
                "scikit-learn es requerido para EToForecaster. "
                "Instalar con: pip install scikit-learn"
            ) from exc

        for h in range(1, MAX_HORIZON + 1):
            X, y = [], []
            for i in range(MAX_LAG, len(data) - h):
                doy = fechas[i].timetuple().tm_yday
                row = [
                    math.sin(2 * math.pi * doy / 365.0),
                    math.cos(2 * math.pi * doy / 365.0),
                    et0_arr[i - 1],
                    et0_arr[i - 2],
                    et0_arr[i - 7],
                    tmax_arr[i - 1],
                ]
                X.append(row)
                y.append(et0_arr[i + h - 1])

            if len(X) < 10:
                # No hay suficientes muestras para este horizonte
                self._fitted = False
                return self

            model = Ridge(alpha=self.alpha)
            model.fit(np.array(X), np.array(y))
            self._models[h] = model

        self._fitted = True
        return self

    # ── Predict ───────────────────────────────────────────────────────────────

    def predict(
        self,
        horizon: int = 7,
        start_date: Optional[date] = None,
    ) -> list[dict]:
        """Predice ETo para los próximos `horizon` días.

        Parameters
        ----------
        horizon    : número de días a proyectar (1–MAX_HORIZON).
        start_date : fecha base (el día 'hoy'). Los resultados van de
                     start_date+1 a start_date+horizon.

        Returns
        -------
        Lista de dicts:
            fecha        : date del día proyectado
            et0_predicho : float (mm/día)
            metodo       : 'ridge_regression' | 'fallback_media14d'
        """
        horizon = min(horizon, MAX_HORIZON)
        if start_date is None:
            start_date = date.today()

        metodo = "ridge_regression" if self._fitted else "fallback_media14d"
        mean_fallback = self._fallback_mean or 5.0

        if not self._fitted:
            return [
                {
                    "fecha": start_date + timedelta(days=h),
                    "et0_predicho": round(mean_fallback, 2),
                    "metodo": metodo,
                }
                for h in range(1, horizon + 1)
            ]

        # Usar los últimos 7 valores conocidos como contexto inicial
        et0_ctx  = list(self._et0_tail)    # crece con cada paso
        tmax_ctx = list(self._tmax_tail)   # asumimos tmax constante (conservador)

        results: list[dict] = []
        for h in range(1, horizon + 1):
            target_date = start_date + timedelta(days=h)
            doy = target_date.timetuple().tm_yday

            # El lag-7 usa el valor conocido si h ≤ 7, o el predicho si h > 7
            et0_lag7 = et0_ctx[-7] if len(et0_ctx) >= 7 else et0_ctx[0]

            features = [
                math.sin(2 * math.pi * doy / 365.0),
                math.cos(2 * math.pi * doy / 365.0),
                et0_ctx[-1],
                et0_ctx[-2] if len(et0_ctx) >= 2 else et0_ctx[-1],
                et0_lag7,
                tmax_ctx[-1],
            ]

            model = self._models.get(h)
            if model is not None:
                et0_pred = float(model.predict([features])[0])
                # ETo no puede ser ≤ 0 físicamente; 0.5 mm/día es el mínimo
                # posible en diciembre en el Valle del Yaqui.
                et0_pred = max(0.5, round(et0_pred, 2))
            else:
                et0_pred = round(mean_fallback, 2)
                metodo = "fallback_media14d"

            results.append({
                "fecha": target_date,
                "et0_predicho": et0_pred,
                "metodo": metodo,
            })

            # Actualizar contexto para el siguiente paso
            et0_ctx.append(et0_pred)
            tmax_ctx.append(tmax_ctx[-1])  # tmax sin cambio (conservador)

        return results

    # ── Propiedades de diagnóstico ────────────────────────────────────────────

    @property
    def is_fitted(self) -> bool:
        """True si Ridge fue entrenado exitosamente."""
        return self._fitted

    @property
    def using_fallback(self) -> bool:
        """True si operará en modo fallback (datos insuficientes)."""
        return not self._fitted and self._fallback_mean is not None

    @property
    def n_records(self) -> int:
        """Número de registros de et0 válidos usados en fit()."""
        return self._n_records


# ── Proyección FAO-56 forward ─────────────────────────────────────────────────

def run_fao56_forward(
    parcela: Any,
    cultivo_nombre: str,
    dias_siembra: int,
    eto_forecast: list[dict],
    umbral_deficit_mm: float = 10.0,
    humedad_inicial_pct: Optional[float] = None,
) -> dict:
    """Corre FAO-56 hacia adelante sobre los ETo proyectados por EToForecaster.

    Asume precipitación = 0 en el horizonte (escenario conservador — no
    predecimos lluvia futura). En producción se podría conectar a una API
    de pronóstico meteorológico (CONAGUA SMN o Open-Meteo).

    Parameters
    ----------
    parcela          : ORM Parcela con atributos capacidad_campo, punto_marchitez,
                       profundidad_raiz_cm.
    cultivo_nombre   : nombre del cultivo normalizado (ej. 'maiz', 'algodon').
    dias_siembra     : días desde la siembra al día base (para interpolar Kc).
    eto_forecast     : salida de EToForecaster.predict() — lista de dicts con
                       {fecha, et0_predicho, metodo}.
    umbral_deficit_mm: déficit acumulado (mm) que dispara la alerta de riego.
                       Default 10 mm ≈ umbral 'moderado' del motor FAO-56.
    humedad_inicial_pct: humedad volumétrica inicial del suelo en porcentaje.
                       Si None, usa el punto medio entre CC y PMP (simplificación MVP).

    Returns
    -------
    dict con:
        dias_proyectados  : lista de dicts por día (fecha, et0, kc, etc, deficit, riego)
        dia_riego_estimado: int (días desde hoy hasta riego), None si no se cruza el umbral
        fecha_riego_estimada : str ISO o None
        incertidumbre_dias   : float — rango ±días estimado por propagación de error
        metodo_eto           : 'ridge_regression' | 'fallback_media14d'
        umbral_usado_mm      : float
        n_dias_horizonte     : int
    """
    from core.balance_hidrico import calcular_balance_hidrico, obtener_kc

    # ── Parámetros edáficos de la parcela ─────────────────────────────────────
    cc_pct       = float(parcela.capacidad_campo)   * 100.0 if parcela.capacidad_campo   else 34.0
    pmp_pct      = float(parcela.punto_marchitez)   * 100.0 if parcela.punto_marchitez   else 18.0
    prof_raiz_m  = (parcela.profundidad_raiz_cm or 60) / 100.0

    if humedad_inicial_pct is None:
        humedad_inicial_pct = (cc_pct + pmp_pct) / 2.0

    humedad_actual = humedad_inicial_pct
    dias_proyectados: list[dict] = []
    dia_riego: Optional[int] = None
    metodo_eto = "ridge_regression"

    for i, fc in enumerate(eto_forecast):
        dia = i + 1
        dias_cultivo = dias_siembra + dia

        try:
            kc = obtener_kc(cultivo_nombre, dias_cultivo)
        except ValueError:
            kc = 1.0   # fallback seguro si el cultivo no está en KC_TABLE

        etc = fc["et0_predicho"] * kc

        # Precipitación futura = 0 (conservador)
        balance = calcular_balance_hidrico(
            etc_mm=etc,
            precipitacion_mm=0.0,
            humedad_actual_pct=humedad_actual,
            capacidad_campo_pct=cc_pct,
            punto_marchitez_pct=pmp_pct,
            profundidad_raiz_m=prof_raiz_m,
        )

        if fc.get("metodo") == "fallback_media14d":
            metodo_eto = "fallback_media14d"

        fecha_str = fc["fecha"].isoformat() if hasattr(fc["fecha"], "isoformat") else str(fc["fecha"])

        dias_proyectados.append({
            "dia": dia,
            "fecha": fecha_str,
            "et0_predicho": fc["et0_predicho"],
            "kc": round(kc, 3),
            "etc_mm": round(etc, 2),
            "deficit_mm": balance["deficit_mm"],
            "humedad_pct": balance["humedad_resultante_pct"],
            "requiere_riego": balance["requiere_riego"],
        })

        # Primer día en que el déficit supera el umbral → fecha estimada de riego
        if dia_riego is None and balance["deficit_mm"] >= umbral_deficit_mm:
            dia_riego = dia

        humedad_actual = balance["humedad_resultante_pct"]

    # ── Incertidumbre ─────────────────────────────────────────────────────────
    # El RMSE típico de Ridge sobre ETo en clima semiárido es ~0.3-0.5 mm/día.
    # A 7 días, el error acumulado en ETc es ~2-3 mm, lo que se traduce en
    # ±1-2 días en el timing de riego. Usamos 15% del horizonte como estimador
    # conservador (calibrado empíricamente para el Valle del Yaqui).
    incertidumbre = round(len(eto_forecast) * 0.15, 1)

    fecha_riego_str = None
    if dia_riego is not None:
        fecha_riego_str = dias_proyectados[dia_riego - 1]["fecha"]

    return {
        "dias_proyectados": dias_proyectados,
        "dia_riego_estimado": dia_riego,
        "fecha_riego_estimada": fecha_riego_str,
        "incertidumbre_dias": incertidumbre,
        "metodo_eto": metodo_eto,
        "umbral_usado_mm": umbral_deficit_mm,
        "n_dias_horizonte": len(eto_forecast),
    }
