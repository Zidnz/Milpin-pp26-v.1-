"""
actuador_control.py — Capa de decisión y control de actuadores de riego — MILPÍN AgTech v2.0

Orquesta FAO-56 + XGBoost para generar comandos de actuación (abrir/cerrar
válvulas, encender/apagar bombas) y persiste los eventos en historial_riego
con origen_decision='sistema'.

Contexto de simulación:
    Esta capa genera comandos reales y los persiste en BD, pero la ejecución
    física del actuador es SIMULADA. El campo `estado='simulado'` en
    ComandoActuador indica que no hay integración hardware aún.

    Para IoT real: reemplazar el bloque "# MQTT placeholder" en evaluar_y_comandar()
    por una llamada a un broker MQTT o un endpoint ModBus del PLC de campo.

Flujo:
    1. Carga parcela + clima más reciente desde BD
    2. FAO-56 → ETo, Kc, ETc, balance hídrico (deficit, lamina, requiere_riego)
    3. XGBoost → P(riego), lamina_ajustada_mm, riesgo_estres
    4. Calcula duración y volumen del actuador según sistema de riego
    5. Persiste en historial_riego con origen_decision='sistema'
    6. Actualiza estado en memoria (para GET /estado)
    7. Retorna ComandoActuador completo
"""

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ── Caudales típicos por sistema de riego (L/s por parcela) ──────────────────
# Fuente: valores de diseño hidráulico DR-041, Módulo 3, Sonora
CAUDAL_LS_POR_SISTEMA: Dict[str, float] = {
    "gravedad":       10.0,   # compuerta / surcos — caudal típico por unidad
    "aspersion":       4.0,   # aspersores de largo alcance
    "microaspersion":  1.5,   # microaspersores en frutales (uva, chile)
    "goteo":           0.5,   # goteo subsuperficial o superficial
}
CAUDAL_DEFAULT_LS = 10.0  # gravedad


# ── Estado en memoria (simulación de actuadores) ──────────────────────────────
# Estructura: { str(id_parcela): { "ultimo_comando": dict, "estado": str, "timestamp": str } }
# En producción IoT: reemplazar por lecturas al MQTT broker
_estado_actuadores: Dict[str, dict] = {}


# ── Dataclass de salida ───────────────────────────────────────────────────────

@dataclass
class ComandoActuador:
    """
    Comando completo generado para el actuador de una parcela.

    Campos de control:
        accion          : "abrir" (regar) | "standby" (no regar) | "cerrar" (detener)
        duracion_min    : minutos calculados para aplicar la lámina objetivo
        caudal_ls       : caudal del sistema de riego (L/s)
        estado          : "simulado" en el prototipo; "ejecutando" / "completado" en IoT

    Campos de trazabilidad:
        algoritmo       : "fao56+xgboost-v1" si XGBoost funcionó; "fao56-solo" si fallback
        id_historial_riego: UUID del registro creado en historial_riego (si se activó)
    """
    id_comando: str
    id_parcela: str
    accion: str                         # "abrir" | "standby" | "cerrar"
    duracion_min: float                  # minutos de riego
    volumen_objetivo_m3: float           # volumen total a aplicar
    lamina_objetivo_mm: float            # lámina neta objetivo
    caudal_ls: float                     # caudal del sistema (L/s)
    estado: str                          # "simulado" | "ejecutando" | "completado" | "cancelado"
    confianza_xgboost: float             # P(requiere_riego) — salida del clasificador
    riesgo_estres: float                 # score 0-1 de estrés hídrico
    nivel_urgencia: str                  # "critico" | "moderado" | "preventivo"
    algoritmo: str                       # pipeline usado
    eto_mm: float                        # ETo calculado por FAO-56
    kc: float                            # coeficiente de cultivo Kc
    etc_mm: float                        # evapotranspiración del cultivo ETc
    deficit_mm: float                    # déficit hídrico del suelo
    timestamp_generacion: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    id_historial_riego: Optional[str] = None
    observaciones: Optional[str] = None


# ── Funciones de utilidad ─────────────────────────────────────────────────────

def calcular_duracion_min(
    lamina_mm: float,
    area_ha: float,
    caudal_ls: float,
) -> float:
    """
    Calcula la duración de riego en minutos para aplicar una lámina dada.

    Fórmula:
        Volumen (m³) = lamina_mm × area_ha × 10
        Duración (h) = Volumen (m³) / (caudal_ls × 3.6)
        Duración (min) = Duración (h) × 60

    Ejemplo:
        lamina=40mm, area=5ha, caudal=10 L/s
        → V = 40 × 5 × 10 = 2000 m³
        → Duración = 2000 / (10 × 3.6) = 55.6h = 3333 min
        → Ajustar caudal_ls al sistema real del módulo de riego.
    """
    if caudal_ls <= 0.0 or lamina_mm <= 0.0 or area_ha <= 0.0:
        return 0.0
    volumen_m3 = lamina_mm * area_ha * 10.0
    duracion_h = volumen_m3 / (caudal_ls * 3.6)
    return round(duracion_h * 60.0, 1)


def obtener_estado_parcela(id_parcela: str) -> Optional[dict]:
    """Retorna el estado actual del actuador de una parcela desde memoria."""
    return _estado_actuadores.get(str(id_parcela))


def detener_actuador(id_parcela: str) -> dict:
    """
    Detiene el actuador de una parcela (simula cierre de válvula/bomba).
    Actualiza el estado en memoria a 'cancelado'.
    """
    estado_actual = _estado_actuadores.get(str(id_parcela))
    ts = datetime.utcnow().isoformat()

    if not estado_actual:
        return {
            "estado": "inactivo",
            "mensaje": "No hay actuador activo para esta parcela en esta sesión.",
            "timestamp": ts,
        }

    _estado_actuadores[str(id_parcela)]["estado"] = "cancelado"
    _estado_actuadores[str(id_parcela)]["timestamp_detenido"] = ts
    logger.info("Actuador detenido manualmente — parcela=%s", id_parcela)

    return {
        "estado": "cancelado",
        "mensaje": f"Actuador de parcela {id_parcela} detenido.",
        "timestamp": ts,
    }


# ── Función principal ─────────────────────────────────────────────────────────

async def evaluar_y_comandar(
    id_parcela: uuid.UUID,
    db,
    dias_siembra: int,
    dias_sin_riego: int = 0,
    humedad_suelo_pct: Optional[float] = None,
    precipitacion_mm: float = 0.0,
    forzar: bool = False,
) -> ComandoActuador:
    """
    Punto de entrada principal del sistema de control de actuadores.

    Pasos:
        1. Carga parcela + último registro climático desde BD
        2. FAO-56: calcula ETo (Penman-Monteith o Hargreaves fallback), Kc, ETc, balance
        3. XGBoost: predice P(riego), lamina_ajustada, riesgo_estres
        4. Decide acción: "abrir" si pred.requiere_riego o forzar=True
        5. Calcula duración y volumen del actuador
        6. Persiste en historial_riego con origen_decision='sistema'
        7. Actualiza estado en memoria y retorna ComandoActuador

    Parámetros:
        id_parcela       : UUID de la parcela a evaluar
        db               : AsyncSession de SQLAlchemy
        dias_siembra     : días desde la siembra (para Kc FAO-56)
        dias_sin_riego   : días desde el último riego registrado
        humedad_suelo_pct: humedad actual del suelo (%). None = promedio CC/PMP
        precipitacion_mm : precipitación del día actual
        forzar           : si True, genera el comando aunque XGBoost diga que no requiere

    Retorna:
        ComandoActuador con estado='simulado'

    Raises:
        ValueError: si la parcela no existe en BD
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from core.balance_hidrico import (
        calcular_balance_hidrico,
        calcular_costo_riego,
        calcular_eto_hargreaves,
        calcular_eto_penman_monteith,
        obtener_kc,
    )
    from ml.inference.xgboost_riego import XGBoostRiego, obtener_predictor
    from models import ClimaDiario, HistorialRiego, Parcela

    # ── 1. Cargar parcela con cultivo_actual (selectinload para evitar lazy noload) ──
    res = await db.execute(
        select(Parcela)
        .options(selectinload(Parcela.cultivo_actual))
        .where(Parcela.id_parcela == id_parcela, Parcela.activo == True)
    )
    parcela = res.scalar_one_or_none()
    if not parcela:
        raise ValueError(f"Parcela {id_parcela} no encontrada o inactiva.")

    # Parámetros edáficos con defaults razonables para Valle del Yaqui
    cc_pct      = float(parcela.capacidad_campo   or 0.34) * 100.0
    pmp_pct     = float(parcela.punto_marchitez   or 0.16) * 100.0
    prof_raiz_m = (parcela.profundidad_raiz_cm    or 60)   / 100.0
    area_ha     = float(parcela.area_ha           or 5.0)
    tipo_suelo  = parcela.tipo_suelo              or "franco"
    sistema     = (parcela.sistema_riego          or "gravedad").lower()

    humedad_actual = humedad_suelo_pct if humedad_suelo_pct is not None else (
        (cc_pct + pmp_pct) / 2.0
    )

    # ── 2. Clima más reciente ──────────────────────────────────────────────
    clima_res = await db.execute(
        select(ClimaDiario)
        .where(ClimaDiario.id_parcela == id_parcela)
        .order_by(ClimaDiario.fecha.desc())
        .limit(1)
    )
    clima = clima_res.scalar_one_or_none()
    dia_del_ano = date.today().timetuple().tm_yday

    # ETo: Penman-Monteith si hay datos completos, Hargreaves como fallback
    campos_clima = (
        clima and
        all(
            getattr(clima, c) is not None
            for c in ["t_max", "t_min", "humedad_rel", "viento", "radiacion"]
        )
    )
    if campos_clima:
        eto = calcular_eto_penman_monteith(
            tmax=float(clima.t_max),
            tmin=float(clima.t_min),
            humedad_rel=float(clima.humedad_rel),
            viento_ms=float(clima.viento),
            radiacion_solar_mj=float(clima.radiacion),
            dia_del_ano=dia_del_ano,
        )
        metodo_eto = "penman_monteith"
    else:
        # Valores medios estacionales Valle del Yaqui si no hay datos de BD
        t_max_ref = float(clima.t_max) if clima and clima.t_max else 35.0
        t_min_ref = float(clima.t_min) if clima and clima.t_min else 20.0
        eto = calcular_eto_hargreaves(
            tmax=t_max_ref, tmin=t_min_ref, dia_del_ano=dia_del_ano
        )
        metodo_eto = "hargreaves_fallback"

    # ── 3. FAO-56: Kc y balance hídrico ───────────────────────────────────
    cultivo_nombre = "maiz"  # default — maíz dominante en DR-041
    if parcela.cultivo_actual:
        cultivo_nombre = parcela.cultivo_actual.nombre_comun.lower().strip()

    try:
        kc = obtener_kc(cultivo_nombre, dias_siembra)
    except ValueError:
        logger.warning(
            "Cultivo '%s' no en KC_TABLE — usando Kc=0.80 genérico", cultivo_nombre
        )
        kc = 0.80

    etc = eto * kc

    balance = calcular_balance_hidrico(
        etc_mm=etc,
        precipitacion_mm=precipitacion_mm,
        humedad_actual_pct=humedad_actual,
        capacidad_campo_pct=cc_pct,
        punto_marchitez_pct=pmp_pct,
        profundidad_raiz_m=prof_raiz_m,
        sistema_riego=sistema,
    )

    # ── 4. XGBoost: predicción ─────────────────────────────────────────────
    try:
        predictor = obtener_predictor()
        pred = predictor.predecir(
            deficit_mm=balance["deficit_mm"],
            etc_mm=etc,
            eto_mm=eto,
            kc=kc,
            dias_sin_riego=dias_sin_riego,
            humedad_suelo_pct=humedad_actual,
            capacidad_campo_pct=cc_pct,
            punto_marchitez_pct=pmp_pct,
            profundidad_raiz_m=prof_raiz_m,
            area_ha=area_ha,
            tipo_suelo=tipo_suelo,
        )
    except Exception as exc:
        logger.warning("XGBoost falló (%s) — usando fallback FAO-56 puro", exc)
        pred = XGBoostRiego._fallback_fao56(
            deficit_mm=balance["deficit_mm"],
            etc_mm=etc,
            humedad_suelo_pct=humedad_actual,
            capacidad_campo_pct=cc_pct,
            punto_marchitez_pct=pmp_pct,
            profundidad_raiz_m=prof_raiz_m,
        )

    # ── 5. Decisión y cálculo del actuador ────────────────────────────────
    activar = pred.requiere_riego or forzar
    accion  = "abrir" if activar else "standby"
    lamina_final = pred.lamina_ajustada_mm if activar else 0.0

    caudal_ls = CAUDAL_LS_POR_SISTEMA.get(sistema, CAUDAL_DEFAULT_LS)
    duracion_min = (
        calcular_duracion_min(lamina_final, area_ha, caudal_ls) if activar else 0.0
    )
    volumen_m3 = lamina_final * area_ha * 10.0
    costo = calcular_costo_riego(volumen_m3=volumen_m3)

    # ── 6. Persistir en historial_riego ────────────────────────────────────
    id_historial = None
    if activar:
        evento = HistorialRiego(
            id_riego=uuid.uuid4(),
            id_parcela=id_parcela,
            id_recomendacion=None,
            fecha_riego=date.today(),
            volumen_m3_ha=round(lamina_final * 10.0, 2),   # 1 mm = 10 m³/ha
            lamina_mm=round(lamina_final, 2),
            duracion_horas=round(duracion_min / 60.0, 3),
            metodo_riego=sistema,
            origen_decision="sistema",
            costo_energia_mxn=round(costo["costo_pesos"], 2),
            observaciones=(
                f"Auto: {pred.algoritmo} | "
                f"P(riego)={pred.probabilidad_riego:.2%} | "
                f"Estrés={pred.riesgo_estres:.2%} | "
                f"Urgencia={pred.nivel_urgencia} | "
                f"ETo={eto:.2f}mm ({metodo_eto}) | "
                f"Kc={kc:.2f} | ETc={etc:.2f}mm | "
                f"Déficit={balance['deficit_mm']:.1f}mm"
            ),
        )
        db.add(evento)
        await db.flush()
        id_historial = str(evento.id_riego)
        logger.info(
            "Riego persistido — parcela=%s lamina=%.1fmm vol=%.0fm³ "
            "dur=%.0fmin costo=$%.2fMXN",
            id_parcela, lamina_final, volumen_m3, duracion_min, costo["costo_pesos"],
        )

    # ── MQTT placeholder (IoT futuro) ─────────────────────────────────────
    # if activar and MQTT_ENABLED:
    #     await mqtt_client.publish(
    #         topic=f"milpin/actuadores/{id_parcela}/cmd",
    #         payload=json.dumps({
    #             "accion": accion,
    #             "duracion_min": duracion_min,
    #             "caudal_ls": caudal_ls,
    #         }),
    #     )

    # ── 7. Construir comando y actualizar estado en memoria ────────────────
    id_cmd = str(uuid.uuid4())
    comando = ComandoActuador(
        id_comando=id_cmd,
        id_parcela=str(id_parcela),
        accion=accion,
        duracion_min=round(duracion_min, 1),
        volumen_objetivo_m3=round(volumen_m3, 2),
        lamina_objetivo_mm=round(lamina_final, 2),
        caudal_ls=caudal_ls,
        estado="simulado",
        confianza_xgboost=pred.probabilidad_riego,
        riesgo_estres=pred.riesgo_estres,
        nivel_urgencia=pred.nivel_urgencia,
        algoritmo=pred.algoritmo,
        eto_mm=round(eto, 3),
        kc=round(kc, 3),
        etc_mm=round(etc, 3),
        deficit_mm=round(balance["deficit_mm"], 2),
        id_historial_riego=id_historial,
        observaciones=(
            f"Parcela: {parcela.nombre_parcela or id_parcela} | "
            f"Sistema: {sistema} | Cultivo: {cultivo_nombre}"
        ),
    )

    _estado_actuadores[str(id_parcela)] = {
        "ultimo_comando": asdict(comando),
        "estado": comando.estado,
        "timestamp": comando.timestamp_generacion,
    }

    logger.info(
        "ComandoActuador → parcela=%s accion=%s lamina=%.1fmm "
        "dur=%.0fmin P(riego)=%.2f urgencia=%s algoritmo=%s",
        id_parcela, accion, lamina_final, duracion_min,
        pred.probabilidad_riego, pred.nivel_urgencia, pred.algoritmo,
    )

    return comando
