"""
test_fao56_unit.py -- Tests unitarios del motor agronomico FAO-56

Sin BD, sin red. Solo matematica.

Clases:
    TestKc              -- Interpolacion de coeficientes de cultivo
    TestPenmanMonteith  -- ETo Penman-Monteith: rango fisico y monotonia
    TestHargreaves      -- ETo Hargreaves: fallback, coherencia con PM
    TestBalanceHidrico  -- Balance hidrico con valores calculados a mano
    TestCostoRiego      -- Costo de bombeo: sanity check vs baseline DR-041
"""

import math
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.balance_hidrico import (
    calcular_balance_hidrico,
    calcular_costo_riego,
    calcular_eto_hargreaves,
    calcular_eto_penman_monteith,
    obtener_kc,
    obtener_curva_kc,
)


class TestKc:
    """
    Maiz: duracion_etapas=(25, 40, 45, 30), kc=(0.30, 1.20, 0.60)
    Etapas:
        Inicial:    dias  1-25   -> Kc constante = 0.30
        Desarrollo: dias 26-65   -> lineal 0.30 -> 1.20
        Mediados:   dias 66-110  -> Kc constante = 1.20
        Final:      dias 111-140 -> lineal 1.20 -> 0.60
    """

    def test_kc_etapa_inicial_primer_dia(self):
        assert obtener_kc("maiz", 1) == pytest.approx(0.30, abs=1e-6)

    def test_kc_etapa_inicial_ultimo_dia(self):
        assert obtener_kc("maiz", 25) == pytest.approx(0.30, abs=1e-6)

    def test_kc_desarrollo_inicio(self):
        # progreso = (26-25)/40 = 0.025
        esperado = 0.30 + (1.20 - 0.30) * (1 / 40)
        assert obtener_kc("maiz", 26) == pytest.approx(esperado, rel=1e-4)

    def test_kc_desarrollo_mitad(self):
        # progreso = (45-25)/40 = 0.50
        esperado = 0.30 + (1.20 - 0.30) * 0.50
        assert obtener_kc("maiz", 45) == pytest.approx(esperado, rel=1e-4)

    def test_kc_desarrollo_fin(self):
        assert obtener_kc("maiz", 65) == pytest.approx(1.20, abs=1e-6)

    def test_kc_mediados(self):
        assert obtener_kc("maiz", 66) == pytest.approx(1.20, abs=1e-6)
        assert obtener_kc("maiz", 88) == pytest.approx(1.20, abs=1e-6)
        assert obtener_kc("maiz", 110) == pytest.approx(1.20, abs=1e-6)

    def test_kc_final_inicio(self):
        # progreso = (111-110)/30 = 1/30
        esperado = 1.20 + (0.60 - 1.20) * (1 / 30)
        assert obtener_kc("maiz", 111) == pytest.approx(esperado, rel=1e-4)

    def test_kc_final_ultimo_dia(self):
        assert obtener_kc("maiz", 140) == pytest.approx(0.60, abs=1e-4)

    def test_kc_post_cosecha(self):
        assert obtener_kc("maiz", 200) == pytest.approx(0.60, abs=1e-4)

    def test_kc_dia_cero(self):
        assert obtener_kc("maiz", 0) == pytest.approx(0.30, abs=1e-6)

    def test_kc_cultivos_validos(self):
        for cultivo in ["maiz", "frijol", "algodon", "uva", "chile"]:
            kc = obtener_kc(cultivo, 30)
            assert 0.0 < kc <= 1.50, f"{cultivo}: Kc={kc} fuera de rango fisico"

    def test_kc_normaliza_acentos(self):
        assert obtener_kc("Maiz", 30) == pytest.approx(obtener_kc("maiz", 30), abs=1e-6)
        assert obtener_kc("Algodon", 50) == pytest.approx(obtener_kc("algodon", 50), abs=1e-6)

    def test_kc_cultivo_invalido(self):
        with pytest.raises(ValueError, match="no encontrado"):
            obtener_kc("trigo", 30)

    def test_obtener_curva_kc_estructura(self):
        curva = obtener_curva_kc("maiz")
        assert curva["ciclo_total_dias"] == 140
        etapas = {e["nombre"] for e in curva["etapas"]}
        assert etapas == {"inicial", "desarrollo", "mediados", "final"}


class TestPenmanMonteith:
    """
    Valle del Yaqui verano: tmax=38, tmin=22, hr=35%, viento=2.5, Rg=22 MJ/m2/dia
    La funcion recibe Rg (solar bruta), no Rn (neta). La conversion interna
    Rg->Rn reduce el valor; con Rg=22 en lat 27N la ETo es ~7-8 mm/dia.
    """

    VERANO = dict(tmax=38.0, tmin=22.0, humedad_rel=35.0, viento_ms=2.5,
                  radiacion_solar_mj=22.0, dia_del_ano=200)

    def test_retorna_float_positivo(self):
        eto = calcular_eto_penman_monteith(**self.VERANO)
        assert isinstance(eto, float)
        assert eto > 0

    def test_rango_fisico_verano_sonora(self):
        """ETo PM con Rg=22 MJ/m2 en lat 27N: entre 6 y 12 mm/dia."""
        eto = calcular_eto_penman_monteith(**self.VERANO)
        assert 6.0 <= eto <= 12.0, f"ETo={eto:.2f} fuera de rango"

    def test_rango_fisico_invierno(self):
        invierno = dict(tmax=20.0, tmin=8.0, humedad_rel=60.0, viento_ms=1.5,
                        radiacion_solar_mj=12.0, dia_del_ano=15)
        eto_inv = calcular_eto_penman_monteith(**invierno)
        eto_ver = calcular_eto_penman_monteith(**self.VERANO)
        assert eto_inv < eto_ver

    def test_monotonia_temperatura(self):
        base = self.VERANO.copy()
        eto_base = calcular_eto_penman_monteith(**base)
        caliente = base.copy()
        caliente["tmax"] = 45.0
        caliente["tmin"] = 28.0
        assert calcular_eto_penman_monteith(**caliente) > eto_base

    def test_monotonia_viento(self):
        base = self.VERANO.copy()
        alto = base.copy()
        alto["viento_ms"] = 6.0
        assert calcular_eto_penman_monteith(**alto) > calcular_eto_penman_monteith(**base)

    def test_mayor_humedad_reduce_eto(self):
        base = self.VERANO.copy()
        humedo = base.copy()
        humedo["humedad_rel"] = 80.0
        assert calcular_eto_penman_monteith(**humedo) < calcular_eto_penman_monteith(**base)


class TestHargreaves:

    def test_retorna_float_positivo(self):
        eto = calcular_eto_hargreaves(tmax=38.0, tmin=22.0, dia_del_ano=200)
        assert isinstance(eto, float)
        assert eto > 0

    def test_rango_fisico_verano(self):
        """Hargreaves en verano Sonora: entre 6 y 12 mm/dia."""
        eto = calcular_eto_hargreaves(tmax=38.0, tmin=22.0, dia_del_ano=200)
        assert 6.0 <= eto <= 12.0, f"Hargreaves ETo={eto:.2f} fuera de rango"

    def test_mayor_temperatura_mayor_eto(self):
        eto_bajo = calcular_eto_hargreaves(tmax=25.0, tmin=10.0, dia_del_ano=180)
        eto_alto = calcular_eto_hargreaves(tmax=40.0, tmin=25.0, dia_del_ano=180)
        assert eto_alto > eto_bajo

    def test_hargreaves_coherente_con_pm(self):
        """PM y Hargreaves no deben divergir mas de un factor 2."""
        eto_pm = calcular_eto_penman_monteith(
            tmax=38.0, tmin=22.0, humedad_rel=35.0,
            viento_ms=2.5, radiacion_solar_mj=22.0, dia_del_ano=200,
        )
        eto_hg = calcular_eto_hargreaves(tmax=38.0, tmin=22.0, dia_del_ano=200)
        ratio = eto_pm / eto_hg
        assert 0.5 <= ratio <= 2.0, f"PM/Hargreaves ratio={ratio:.2f}"


class TestBalanceHidrico:
    """
    Suelo franco-arcilloso tipico Valle del Yaqui:
        CC=34%, PMP=18%, prof_raiz=0.6m
        ADT = (34-18)*0.6*10 = 96mm
        umbral = 18 + 0.5*16 = 26%

    Escenario A — gravedad (eficiencia=0.65), humedad=25%, ETc=8mm, precip=0:
        requiere_riego = True
        lamina_neta = (34-25)*6 = 54mm
        lamina_bruta = 54/0.65 ≈ 83.08mm
        volumen = 830.8 m3/ha

    Escenario B — goteo (eficiencia=0.90), mismas condiciones edáficas:
        lamina_neta = 54mm (idéntica — depende solo del suelo)
        lamina_bruta = 54/0.90 = 60mm
        volumen = 600.0 m3/ha
        ahorro vs gravedad = (830.8-600)/830.8 ≈ 27.8%
    """

    SUELO = dict(capacidad_campo_pct=34.0, punto_marchitez_pct=18.0, profundidad_raiz_m=0.6)

    def _balance(self, humedad, etc=8.0, precip=0.0, sistema_riego="gravedad"):
        return calcular_balance_hidrico(
            etc_mm=etc,
            precipitacion_mm=precip,
            humedad_actual_pct=humedad,
            sistema_riego=sistema_riego,
            **self.SUELO,
        )

    def test_requiere_riego_bajo_umbral(self):
        assert self._balance(humedad=25.0)["requiere_riego"] is True

    def test_no_requiere_riego_sobre_umbral(self):
        assert self._balance(humedad=30.0)["requiere_riego"] is False

    def test_lamina_neta_escenario_a(self):
        # Lámina neta no depende del sistema de riego — solo del suelo
        assert self._balance(humedad=25.0)["lamina_neta_mm"] == pytest.approx(54.0, abs=0.01)

    def test_lamina_bruta_gravedad(self):
        # gravedad: eficiencia=0.65 → 54/0.65 = 83.077mm
        assert self._balance(humedad=25.0, sistema_riego="gravedad")["lamina_bruta_mm"] == pytest.approx(83.08, abs=0.1)

    def test_volumen_m3_ha_gravedad(self):
        assert self._balance(humedad=25.0, sistema_riego="gravedad")["volumen_m3_ha"] == pytest.approx(830.8, abs=1.0)

    def test_lamina_bruta_goteo(self):
        # goteo: eficiencia=0.90 → 54/0.90 = 60.00mm
        assert self._balance(humedad=25.0, sistema_riego="goteo")["lamina_bruta_mm"] == pytest.approx(60.0, abs=0.01)

    def test_volumen_m3_ha_goteo(self):
        assert self._balance(humedad=25.0, sistema_riego="goteo")["volumen_m3_ha"] == pytest.approx(600.0, abs=0.1)

    def test_goteo_consume_menos_agua_que_gravedad(self):
        # El punto central del sistema: goteo siempre da menor volumen bruto
        vol_gravedad = self._balance(humedad=25.0, sistema_riego="gravedad")["volumen_m3_ha"]
        vol_goteo = self._balance(humedad=25.0, sistema_riego="goteo")["volumen_m3_ha"]
        assert vol_goteo < vol_gravedad

    def test_eficiencia_aplicada_en_respuesta(self):
        b_gravedad = self._balance(humedad=25.0, sistema_riego="gravedad")
        b_goteo = self._balance(humedad=25.0, sistema_riego="goteo")
        assert b_gravedad["eficiencia_aplicada"] == pytest.approx(0.65)
        assert b_goteo["eficiencia_aplicada"] == pytest.approx(0.90)

    def test_sistema_desconocido_usa_fallback(self):
        # Valor desconocido: debe usar fallback 0.75 sin lanzar excepción
        b = self._balance(humedad=25.0, sistema_riego="inundacion_ultrasonica")
        assert b["eficiencia_aplicada"] == pytest.approx(0.75)

    def test_deficit_positivo_cuando_requiere_riego(self):
        assert self._balance(humedad=20.0)["deficit_mm"] > 0.0

    def test_deficit_menor_con_precipitacion(self):
        sin_lluvia = self._balance(humedad=20.0, precip=0.0)
        con_lluvia = self._balance(humedad=20.0, precip=5.0)
        assert con_lluvia["deficit_mm"] < sin_lluvia["deficit_mm"]

    def test_humedad_resultante_no_supera_cc(self):
        b = self._balance(humedad=33.0, etc=0.0, precip=20.0)
        assert b["humedad_resultante_pct"] <= 34.0

    def test_humedad_resultante_no_baja_de_pmp(self):
        b = self._balance(humedad=18.5, etc=50.0, precip=0.0)
        assert b["humedad_resultante_pct"] >= 18.0

    def test_lamina_neta_es_no_negativa(self):
        assert self._balance(humedad=34.0, etc=0.0, precip=0.0)["lamina_neta_mm"] >= 0.0

    def test_claves_presentes_en_respuesta(self):
        b = self._balance(humedad=25.0)
        claves = {
            "lamina_neta_mm", "lamina_bruta_mm", "volumen_m3_ha",
            "requiere_riego", "deficit_mm", "humedad_resultante_pct",
            "eficiencia_aplicada",
        }
        assert claves.issubset(b.keys())


class TestCostoRiego:
    """
    Baseline DR-041: $1.68 MXN/m3 (CFE tarifa 9-CU, bombeo 80m, eficiencia 65%)

    E = (1m3 * 80m * 9810 N/m3) / (0.65 * 3600000 J/kWh) = 0.3354 kWh
    Costo = 0.3354 * $5.0/kWh = $1.677 MXN/m3 aprox $1.68
    """

    DEFAULT = dict(volumen_m3=1.0, profundidad_pozo_m=80.0, eficiencia_bomba=0.65, costo_kwh=5.0)

    def test_baseline_dr041_un_metro_cubico(self):
        r = calcular_costo_riego(**self.DEFAULT)
        assert r["costo_por_m3"] == pytest.approx(1.68, abs=0.05)

    def test_energia_kwh_es_positiva(self):
        assert calcular_costo_riego(**self.DEFAULT)["energia_kwh"] > 0.0

    def test_costo_escala_linealmente_con_volumen(self):
        r1 = calcular_costo_riego(volumen_m3=100.0)
        r2 = calcular_costo_riego(volumen_m3=200.0)
        assert r2["costo_pesos"] == pytest.approx(2 * r1["costo_pesos"], rel=1e-6)

    def test_mayor_profundidad_mayor_costo(self):
        r_poco = calcular_costo_riego(volumen_m3=1000.0, profundidad_pozo_m=40.0)
        r_prof = calcular_costo_riego(volumen_m3=1000.0, profundidad_pozo_m=80.0)
        assert r_prof["costo_pesos"] == pytest.approx(2 * r_poco["costo_pesos"], rel=1e-6)

    def test_mayor_eficiencia_menor_costo(self):
        r_baja = calcular_costo_riego(volumen_m3=1000.0, eficiencia_bomba=0.50)
        r_alta = calcular_costo_riego(volumen_m3=1000.0, eficiencia_bomba=0.80)
        assert r_alta["costo_pesos"] < r_baja["costo_pesos"]

    def test_claves_en_respuesta(self):
        r = calcular_costo_riego(**self.DEFAULT)
        assert {"energia_kwh", "costo_pesos", "costo_por_m3"}.issubset(r.keys())

    def test_volumen_cero_no_falla(self):
        r = calcular_costo_riego(volumen_m3=0.0)
        assert math.isfinite(r["costo_por_m3"])


# ---------------------------------------------------------------------------
# TestPropagar -- Balance hidrico acumulado desde el ultimo riego
# ---------------------------------------------------------------------------

class TestPropagar:
    """
    Tests unitarios para propagar_balance_hidrico().

    Suelo de referencia: CC=34%, PMP=18%, prof=0.60 m
    Maiz en etapa inicial (dias_siembra_ref=10, Kc=0.30)
    ETo fijo = 5 mm/dia -> ETc = 5 * 0.30 = 1.5 mm/dia
    Delta_humedad = -1.5 / (0.60*10) = -0.25 %/dia

    Capacidad util = (CC - PMP) * prof * 10 = (34-18)*0.60*10 = 96 mm
    """

    CC = 34.0
    PMP = 18.0
    PROF = 0.60
    CULTIVO = "maiz"
    DIAS_SIEMBRA = 10  # Kc = 0.30 (etapa inicial)
    ETO_FIJO = 5.0
    LLUVIA_CERO = 0.0

    def _make_clima(self, fecha_inicio, n_dias, et0=None, lluvia=0.0):
        """Genera lista de dicts con datos climaticos sintéticos."""
        from datetime import timedelta
        et0 = et0 if et0 is not None else self.ETO_FIJO
        return [
            {
                "fecha": fecha_inicio + timedelta(days=i),
                "et0": et0,
                "lluvia": lluvia,
            }
            for i in range(n_dias)
        ]

    def test_riego_hoy_devuelve_cc(self):
        """Si fecha_ultimo_riego == fecha_ref, suelo recien regado: humedad = CC."""
        from datetime import date
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 6, 15)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=hoy,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=[],
        )
        assert r["humedad_actual_pct"] == pytest.approx(self.CC, abs=1e-3)
        assert r["dias_propagados"] == 0
        assert r["metodo"] == "propagacion_balance"

    def test_riego_futuro_devuelve_cc(self):
        """Si el riego fue despues de fecha_ref (nunca deberia pasar), devuelve CC."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 6, 15)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=hoy + timedelta(days=2),
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=[],
        )
        assert r["humedad_actual_pct"] == pytest.approx(self.CC, abs=1e-3)
        assert r["dias_propagados"] == 0

    def test_fallback_sin_clima(self):
        """Sin registros de clima, devuelve punto medio CC+PMP y metodo fallback."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 6, 15)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=hoy - timedelta(days=5),
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=[],
        )
        midpoint = (self.CC + self.PMP) / 2.0
        assert r["humedad_actual_pct"] == pytest.approx(midpoint, abs=1e-3)
        assert r["metodo"] == "fallback_midpoint"
        assert len(r["advertencias"]) > 0

    def test_propagacion_1_dia_sin_lluvia(self):
        """1 dia sin lluvia: humedad baja en ETc/prof (mm a %)."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        # ETo=5, Kc_maiz_dia10=0.30 -> ETc=1.5 mm
        # delta_hum = -1.5 / (0.60*10) = -0.25 %
        hoy = date(2025, 6, 15)
        ayer = hoy - timedelta(days=1)
        clima = self._make_clima(hoy, 1)  # dia: hoy
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=ayer,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        esperado = self.CC - (self.ETO_FIJO * 0.30) / (self.PROF * 10.0)
        assert r["humedad_actual_pct"] == pytest.approx(esperado, abs=0.01)
        assert r["dias_propagados"] == 1
        assert r["metodo"] == "propagacion_balance"

    def test_propagacion_5_dias_sin_lluvia(self):
        """5 dias sin lluvia: humedad cae linealmente (Kc~constante en etapa inicial)."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        # delta_hum por dia = -1.5 / (0.60*10) = -0.25 %
        # despues de 5 dias: CC - 5*0.25 = 34 - 1.25 = 32.75 %
        hoy = date(2025, 6, 15)
        fecha_riego = hoy - timedelta(days=5)
        clima = self._make_clima(fecha_riego + timedelta(days=1), 5)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=fecha_riego,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        delta_dia = (self.ETO_FIJO * 0.30) / (self.PROF * 10.0)
        esperado = self.CC - 5 * delta_dia
        assert r["humedad_actual_pct"] == pytest.approx(esperado, abs=0.05)
        assert r["dias_propagados"] == 5
        assert r["etc_acumulada_mm"] == pytest.approx(5 * self.ETO_FIJO * 0.30, abs=0.1)

    def test_clamp_pmp_no_baja_de_pmp(self):
        """Con suficientes dias secos, la humedad debe quedar clampeada en PMP."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        # delta_dia = 0.25 %/dia -> para agotar (34-18)=16 % necesitamos 64 dias
        # Usar ETo muy alto para forzar clamp rapido
        hoy = date(2025, 7, 1)
        fecha_riego = hoy - timedelta(days=30)
        clima = self._make_clima(fecha_riego + timedelta(days=1), 30, et0=20.0)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=fecha_riego,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        assert r["humedad_actual_pct"] >= self.PMP - 1e-6

    def test_clamp_cc_lluvia_intensa(self):
        """Con lluvia muy intensa, la humedad no puede superar CC."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 7, 1)
        ayer = hoy - timedelta(days=1)
        # Lluvia enorme: 200 mm en un dia
        clima = [{"fecha": hoy, "et0": 3.0, "lluvia": 200.0}]
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=ayer,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        assert r["humedad_actual_pct"] <= self.CC + 1e-6

    def test_keys_presentes_en_respuesta(self):
        """Todas las claves esperadas deben estar en el resultado."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 6, 15)
        ayer = hoy - timedelta(days=1)
        clima = self._make_clima(hoy, 1)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=ayer,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        claves_requeridas = {
            "humedad_actual_pct",
            "dias_propagados",
            "etc_acumulada_mm",
            "lluvia_acumulada_mm",
            "deficit_acumulado_mm",
            "metodo",
            "advertencias",
        }
        assert claves_requeridas.issubset(r.keys())

    def test_humedad_post_riego_custom(self):
        """Si se pasa humedad_post_riego_pct, el punto de partida es ese valor, no CC."""
        from datetime import date, timedelta
        from core.balance_hidrico import propagar_balance_hidrico

        hoy = date(2025, 6, 15)
        ayer = hoy - timedelta(days=1)
        humedad_inicio = 28.0  # Riego parcial (< CC=34%)
        clima = self._make_clima(hoy, 1)
        r = propagar_balance_hidrico(
            fecha_ultimo_riego=ayer,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
            humedad_post_riego_pct=humedad_inicio,
        )
        # El resultado debe ser menor a la humedad_inicio (hay consumo)
        assert r["humedad_actual_pct"] < humedad_inicio
        # Y debe ser mayor que si hubieramos partido de CC (ya empieza mas bajo)
        r_cc = propagar_balance_hidrico(
            fecha_ultimo_riego=ayer,
            fecha_ref=hoy,
            cc_pct=self.CC,
            pmp_pct=self.PMP,
            prof_raiz_m=self.PROF,
            cultivo_nombre=self.CULTIVO,
            dias_siembra_ref=self.DIAS_SIEMBRA,
            clima_records=clima,
        )
        assert r["humedad_actual_pct"] < r_cc["humedad_actual_pct"]
