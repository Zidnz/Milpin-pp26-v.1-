"""
init_db.py — Inicialización de la base de datos MILPÍN AgTech v2.0 MVP

Uso:
    python init_db.py                  # Crea tablas y carga datos semilla
    python init_db.py --reset          # DROP + CREATE + seed (¡DESTRUCTIVO!)
    python init_db.py --check          # Solo verifica la conexión

Requiere que PostgreSQL esté corriendo y que DATABASE_URL esté configurado.
Ver README_DB.md para instrucciones de instalación.
"""

import asyncio
import math
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from security import hash_password
from database import AsyncSessionLocal, create_all_tables, drop_all_tables, engine
from models import ClimaDiario, CultivoCatalogo, HistorialRiego, Parcela, Recomendacion, Usuario


def _suelo_franco_arcilloso() -> tuple[float, float]:
    """Genera CC y PMP con variación realista para suelo franco-arcilloso
    del Valle del Yaqui, Sonora.

    Rangos basados en FAO-56 Annex 5 y Hillel (1998) para Loam / Clay-Loam:
        CC:  0.27 – 0.42 m³/m³  (µ = 0.34, σ = 0.025)
        PMP: CC - diferencia     (diferencia µ = 0.16, σ = 0.015)
    Restricción dura: CC − PMP ≥ 0.08 (agua disponible mínima viable).

    Returns: (capacidad_campo, punto_marchitez) en m³/m³, 4 decimales.
    """
    cc = random.gauss(0.34, 0.025)
    cc = round(max(0.27, min(0.42, cc)), 4)

    diff = random.gauss(0.16, 0.015)
    diff = max(0.08, min(0.22, diff))

    pmp = round(max(0.10, cc - diff), 4)
    return cc, pmp


# ── Datos semilla: catálogo definitivo MILPÍN (FAO-56 Tabla 12, FAO-33 Tabla 25)
CULTIVOS_SEMILLA = [
    {
        "nombre_comun": "Maíz",
        "nombre_cientifico": "Zea mays",
        "kc_inicial": 0.30,
        "kc_medio": 1.20,
        "kc_final": 0.60,
        "ky_total": 1.25,
        "dias_etapa_inicial": 25,
        "dias_etapa_desarrollo": 40,
        "dias_etapa_media": 45,
        "dias_etapa_final": 30,
        "rendimiento_potencial_ton": 10.0,
        "rendimiento_min_ton": 5.0,   # CIMMYT/INIFAP DR-041, ciclo PV sin estrés hídrico
        "rendimiento_max_ton": 12.0,  # techo tecnificado con riego deficitario controlado
    },
    {
        "nombre_comun": "Frijol",
        "nombre_cientifico": "Phaseolus vulgaris",
        "kc_inicial": 0.40,
        "kc_medio": 1.15,
        "kc_final": 0.35,
        "ky_total": 1.15,
        "dias_etapa_inicial": 20,
        "dias_etapa_desarrollo": 30,
        "dias_etapa_media": 40,
        "dias_etapa_final": 20,
        "rendimiento_potencial_ton": 2.0,
        "rendimiento_min_ton": 0.8,
        "rendimiento_max_ton": 2.5,
    },
    {
        "nombre_comun": "Algodón",
        "nombre_cientifico": "Gossypium hirsutum",
        "kc_inicial": 0.35,
        "kc_medio": 1.20,
        "kc_final": 0.70,
        "ky_total": 0.85,
        "dias_etapa_inicial": 30,
        "dias_etapa_desarrollo": 50,
        "dias_etapa_media": 55,
        "dias_etapa_final": 45,
        "rendimiento_potencial_ton": 3.5,
        "rendimiento_min_ton": 1.5,   # fibra limpia ton/ha
        "rendimiento_max_ton": 4.5,
    },
    {
        "nombre_comun": "Uva",
        "nombre_cientifico": "Vitis vinifera",
        "kc_inicial": 0.30,
        "kc_medio": 0.85,
        "kc_final": 0.45,
        "ky_total": 0.85,
        "dias_etapa_inicial": 30,
        "dias_etapa_desarrollo": 60,
        "dias_etapa_media": 75,
        "dias_etapa_final": 50,
        "rendimiento_potencial_ton": 22.5,
        "rendimiento_min_ton": 12.0,
        "rendimiento_max_ton": 28.0,
    },
    {
        "nombre_comun": "Chile",
        "nombre_cientifico": "Capsicum annuum",
        "kc_inicial": 0.60,
        "kc_medio": 1.05,
        "kc_final": 0.90,
        "ky_total": 1.10,
        "dias_etapa_inicial": 30,
        "dias_etapa_desarrollo": 35,
        "dias_etapa_media": 40,
        "dias_etapa_final": 20,
        "rendimiento_potencial_ton": 30.0,
        "rendimiento_min_ton": 15.0,
        "rendimiento_max_ton": 40.0,
    },
]

# Usuario de prueba para desarrollo
# Contraseña dev: milpin2024
USUARIO_PRUEBA = {
    "nombre_completo": "Ramón Valenzuela Torres",
    "email": "rvalenzuela@dr041-dev.com",
    "telefono": "+52 644 100 0001",
    "modulo_dr041": "Módulo 3",
    "rol": "agricultor",
    "password_dev": "milpin2024",
}

# Usuario administrador (acceso a todas las parcelas)
# Contraseña dev: admin2024
USUARIO_ADMIN = {
    "nombre_completo": "Administrador MILPÍN",
    "email": "admin@milpin-dr041.com",
    "telefono": "+52 644 000 0000",
    "modulo_dr041": "DR-041 Completo",
    "rol": "admin",
    "password_dev": "admin2024",
}


async def verificar_conexion() -> bool:
    """Verifica que la base de datos es accesible."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("✓ Conexión a base de datos: OK")
        return True
    except Exception as e:
        print(f"✗ Error de conexión: {e}")
        print("\nVerifica que PostgreSQL está corriendo y que DATABASE_URL es correcto.")
        print("Consulta README_DB.md para instrucciones de instalación.")
        return False


async def seed_cultivos(db: AsyncSession) -> int:
    """Inserta los cultivos semilla si no existen ya."""
    insertados = 0
    for cultivo_data in CULTIVOS_SEMILLA:
        # Verificar si ya existe
        resultado = await db.execute(
            select(CultivoCatalogo).where(
                CultivoCatalogo.nombre_comun == cultivo_data["nombre_comun"]
            )
        )
        existente = resultado.scalar_one_or_none()
        if existente is None:
            cultivo = CultivoCatalogo(
                id_cultivo=uuid.uuid4(),
                **cultivo_data
            )
            db.add(cultivo)
            insertados += 1
            print(f"  + Cultivo insertado: {cultivo_data['nombre_comun']}")
        else:
            print(f"  ○ Cultivo ya existe: {cultivo_data['nombre_comun']}")
    await db.commit()
    return insertados


async def seed_usuario_prueba(db: AsyncSession) -> bool:
    """Inserta un usuario de prueba para desarrollo. Contraseña: milpin2024"""
    resultado = await db.execute(
        select(Usuario).where(Usuario.email == USUARIO_PRUEBA["email"])
    )
    existente = resultado.scalar_one_or_none()
    if existente is None:
        data = {k: v for k, v in USUARIO_PRUEBA.items() if k != "password_dev"}
        usuario = Usuario(
            id_usuario=uuid.uuid4(),
            hashed_password=hash_password(USUARIO_PRUEBA["password_dev"]),
            **data,
        )
        db.add(usuario)
        await db.commit()
        print(f"  + Usuario de prueba insertado: {USUARIO_PRUEBA['email']} (pwd: milpin2024)")
        return True
    else:
        # Actualizar contraseña si aún es NULL (migración desde dataset sin auth)
        if existente.hashed_password is None:
            existente.hashed_password = hash_password(USUARIO_PRUEBA["password_dev"])
            await db.commit()
            print(f"  ↑ Contraseña actualizada para: {USUARIO_PRUEBA['email']} (pwd: milpin2024)")
        else:
            print(f"  ○ Usuario de prueba ya existe: {USUARIO_PRUEBA['email']}")
        return False


async def seed_usuario_admin(db: AsyncSession) -> bool:
    """Inserta el usuario administrador si no existe. Contraseña: admin2024"""
    resultado = await db.execute(
        select(Usuario).where(Usuario.email == USUARIO_ADMIN["email"])
    )
    existente = resultado.scalar_one_or_none()
    if existente is None:
        data = {k: v for k, v in USUARIO_ADMIN.items() if k != "password_dev"}
        admin = Usuario(
            id_usuario=uuid.uuid4(),
            hashed_password=hash_password(USUARIO_ADMIN["password_dev"]),
            **data,
        )
        db.add(admin)
        await db.commit()
        print(f"  + Admin insertado: {USUARIO_ADMIN['email']} (pwd: admin2024)")
        return True
    else:
        if existente.hashed_password is None:
            existente.hashed_password = hash_password(USUARIO_ADMIN["password_dev"])
            await db.commit()
            print(f"  ↑ Contraseña actualizada para: {USUARIO_ADMIN['email']} (pwd: admin2024)")
        else:
            print(f"  ○ Admin ya existe: {USUARIO_ADMIN['email']}")
        return False


async def seed_parcela_prueba(db: AsyncSession) -> uuid.UUID | None:
    """Crea una parcela de prueba vinculada al usuario y cultivo semilla.

    Retorna el id_parcela para poder generar clima_diario después.
    Si ya existe, retorna su id sin crear duplicado.
    """
    # Buscar usuario de prueba
    res_u = await db.execute(
        select(Usuario).where(Usuario.email == USUARIO_PRUEBA["email"])
    )
    usuario = res_u.scalar_one_or_none()
    if usuario is None:
        print("  ⚠ No se encontró usuario de prueba, no se puede crear parcela.")
        return None

    # Buscar cultivo Maíz
    res_c = await db.execute(
        select(CultivoCatalogo).where(CultivoCatalogo.nombre_comun == "Maíz")
    )
    cultivo = res_c.scalar_one_or_none()

    # ¿Ya existe la parcela?
    res_p = await db.execute(
        select(Parcela).where(
            Parcela.id_usuario == usuario.id_usuario,
            Parcela.nombre_parcela == "Lote Demo A-3",
        )
    )
    existente = res_p.scalar_one_or_none()
    if existente is not None:
        print(f"  ○ Parcela demo ya existe: {existente.id_parcela}")
        return existente.id_parcela

    # Convertir GeoJSON dict → WKBElement para GeoAlchemy2 (PostGIS)
    from geoalchemy2.shape import from_shape as _from_shape
    from shapely.geometry import shape as _shape
    _geom_dict = {
        "type": "Polygon",
        "coordinates": [[
            [-109.935, 27.365], [-109.930, 27.365],
            [-109.930, 27.370], [-109.935, 27.370],
            [-109.935, 27.365],
        ]],
    }
    _geom_wkb = _from_shape(_shape(_geom_dict), srid=4326)

    # Generar CC y PMP realistas para el lote demo (variación por corrida)
    _cc_demo, _pmp_demo = _suelo_franco_arcilloso()

    parcela = Parcela(
        id_parcela=uuid.uuid4(),
        id_usuario=usuario.id_usuario,
        id_cultivo_actual=cultivo.id_cultivo if cultivo else None,
        nombre_parcela="Lote Demo A-3",
        geom=_geom_wkb,
        area_ha=25.0,
        tipo_suelo="franco-arcilloso",
        conductividad_electrica=1.8,
        profundidad_raiz_cm=60,
        capacidad_campo=_cc_demo,
        punto_marchitez=_pmp_demo,
        sistema_riego="gravedad",
    )
    db.add(parcela)
    await db.commit()
    print(f"  + Parcela demo insertada: {parcela.nombre_parcela} ({parcela.id_parcela})")
    return parcela.id_parcela


async def seed_clima_diario(db: AsyncSession, id_parcela: uuid.UUID) -> int:
    """Genera 365 días de datos climáticos sintéticos para la parcela demo.

    Rangos calibrados para Valle del Yaqui, Sonora (lat 27.37°N, alt 40 m):
    ┌─────────────┬──────────┬──────────┬─────────────────────────────────────┐
    │ Variable    │ Mín      │ Máx      │ Fuente / justificación              │
    ├─────────────┼──────────┼──────────┼─────────────────────────────────────┤
    │ T max (°C)  │ 18–25    │ 38–45    │ NASA POWER T2M_MAX, zona semiárida  │
    │ T min (°C)  │  3–8     │ 22–28    │ NASA POWER T2M_MIN                  │
    │ HR (%)      │ 25–40    │ 55–80    │ NASA POWER RH2M, clima seco         │
    │ Viento (m/s)│ 0.5      │ 4.0      │ NASA POWER WS2M                     │
    │ Rad (MJ/m²) │ 10–15    │ 22–30    │ NASA POWER ALLSKY_SFC_SW_DWN        │
    │ Lluvia (mm) │ 0        │ 0–40     │ PRECTOTCORR, monzón jul-sep         │
    └─────────────┴──────────┴──────────┴─────────────────────────────────────┘
    El ciclo estacional se modela con sinusoidales + ruido gaussiano.
    ET0 se calcula con el mismo motor FAO-56 de balance_hidrico.py.
    """
    from core.balance_hidrico import calcular_eto_penman_monteith

    # Verificar si ya hay datos
    res = await db.execute(
        select(ClimaDiario).where(ClimaDiario.id_parcela == id_parcela).limit(1)
    )
    if res.scalar_one_or_none() is not None:
        print("  ○ clima_diario ya tiene datos para esta parcela.")
        return 0

    rng = np.random.default_rng(seed=42)
    fecha_inicio = date(2024, 1, 1)
    dias = 365
    insertados = 0

    for d in range(dias):
        fecha = fecha_inicio + timedelta(days=d)
        doy = fecha.timetuple().tm_yday

        # Fase estacional: 0 = invierno, 1 = verano (pico ~julio)
        fase = 0.5 * (1.0 + math.sin(2.0 * math.pi * (doy - 80) / 365.0))

        # Temperaturas con ciclo estacional + ruido
        t_max = 22.0 + 18.0 * fase + rng.normal(0, 1.5)
        t_min = 5.0 + 18.0 * fase + rng.normal(0, 1.2)
        # Restricción física: t_min < t_max con margen mínimo 3°C
        if t_min >= t_max - 3.0:
            t_min = t_max - 3.0 - abs(rng.normal(0, 0.5))

        # Humedad relativa: más alta en monzón (jul-sep), más baja en invierno
        hr_base = 35.0 + 25.0 * fase
        hr = hr_base + rng.normal(0, 5.0)
        hr = float(np.clip(hr, 20.0, 90.0))

        # Viento
        viento = 1.5 + rng.exponential(0.8)
        viento = float(np.clip(viento, 0.3, 6.0))

        # Radiación solar: más alta en verano
        rad = 14.0 + 12.0 * fase + rng.normal(0, 1.5)
        rad = float(np.clip(rad, 6.0, 32.0))

        # Lluvia: concentrada en monzón (jul-sep, doy 182-273)
        if 182 <= doy <= 273:
            # Temporada de monzón: ~30% de días con lluvia
            if rng.random() < 0.30:
                lluvia = float(rng.exponential(8.0))
                lluvia = min(lluvia, 45.0)
            else:
                lluvia = 0.0
        else:
            # Resto del año: ~5% de días con lluvia ligera
            if rng.random() < 0.05:
                lluvia = float(rng.exponential(3.0))
                lluvia = min(lluvia, 15.0)
            else:
                lluvia = 0.0

        # Calcular ET0 con el motor FAO-56 real
        et0 = calcular_eto_penman_monteith(
            tmax=t_max,
            tmin=t_min,
            humedad_rel=hr,
            viento_ms=viento,
            radiacion_solar_mj=rad,
            dia_del_ano=doy,
        )

        registro = ClimaDiario(
            id_parcela=id_parcela,
            fecha=fecha,
            t_max=round(t_max, 2),
            t_min=round(t_min, 2),
            humedad_rel=round(hr, 2),
            viento=round(viento, 2),
            radiacion=round(rad, 3),
            lluvia=round(lluvia, 2),
            et0=round(et0, 2),
        )
        db.add(registro)
        insertados += 1

    await db.commit()
    print(f"  + clima_diario: {insertados} registros insertados (2024-01-01 a 2024-12-31)")
    return insertados


async def seed_historial_riego(db: AsyncSession, id_parcela: uuid.UUID) -> int:
    """Genera historial de riego sintético para el ciclo PV-2024 (Maíz).

    Simula el balance hídrico FAO-56 día a día usando los datos de clima_diario
    ya cargados en BD. Dispara riego cuando el déficit acumulado supera el RAW
    (Readily Available Water, p=0.55 para maíz — FAO-56 Tabla 22).

    Por cada evento de riego genera un par vinculado:
        Recomendacion (aceptada="aceptada") + HistorialRiego (origen="sistema")

    Esto permite que la vista v_kpi_consumo, el feedback loop y el forecast
    tengan datos reales desde el primer `python init_db.py`.

    Parámetros del ciclo PV-2024 (Primavera-Verano):
        Siembra: 2024-04-15 (práctica habitual maíz DR-041, ciclo primaveral)
        Duración: 140 días (25+40+45+30 según FAO-56 Tabla 11 para maíz)

    Tarifa energética: $1.68 MXN/m³ (CFE 9-CU, bombeo 80 m — baseline DR-041)
    Caudal gravedad: 40 m³/h (referencia para calcular duración del riego)
    """
    from sqlalchemy import select as _sel

    # Verificar si ya hay datos (idempotente)
    res = await db.execute(
        _sel(HistorialRiego).where(HistorialRiego.id_parcela == id_parcela).limit(1)
    )
    if res.scalar_one_or_none() is not None:
        print("  ○ historial_riego ya tiene datos para esta parcela.")
        return 0

    # Cargar parcela y cultivo Maíz
    res_p = await db.execute(_sel(Parcela).where(Parcela.id_parcela == id_parcela))
    parcela = res_p.scalar_one_or_none()
    if not parcela:
        print("  ⚠ Parcela no encontrada, no se genera historial.")
        return 0

    res_c = await db.execute(
        _sel(CultivoCatalogo).where(CultivoCatalogo.nombre_comun == "Maíz")
    )
    cultivo = res_c.scalar_one_or_none()
    if not cultivo:
        print("  ⚠ Cultivo Maíz no encontrado en catálogo.")
        return 0

    # ── Parámetros edáficos de la parcela ─────────────────────────────────────
    CC      = float(parcela.capacidad_campo)      # 0.34 m³/m³
    PMP     = float(parcela.punto_marchitez)      # 0.18 m³/m³
    Zr      = float(parcela.profundidad_raiz_cm)  # 60 cm
    area_ha = float(parcela.area_ha)              # 25 ha
    TAW     = (CC - PMP) * Zr * 10               # Agua disponible total (mm) ~96
    p       = 0.55                                # Fracción de agotamiento maíz
    RAW     = p * TAW                             # Agua fácilmente disponible ~52.8 mm
    TARIFA  = 1.68                                # MXN/m³ (CFE 9-CU)
    CAUDAL  = 40.0                                # m³/h — gravedad, referencia DR-041

    # ── Ciclo Primavera-Verano 2024 ───────────────────────────────────────────
    fecha_siembra = date(2024, 4, 15)
    dias_ciclo = (
        cultivo.dias_etapa_inicial
        + cultivo.dias_etapa_desarrollo
        + cultivo.dias_etapa_media
        + cultivo.dias_etapa_final
    )
    fecha_fin_ciclo = fecha_siembra + timedelta(days=dias_ciclo - 1)

    # Cargar datos climáticos del periodo
    res_clima = await db.execute(
        _sel(ClimaDiario)
        .where(
            ClimaDiario.id_parcela == id_parcela,
            ClimaDiario.fecha >= fecha_siembra,
            ClimaDiario.fecha <= fecha_fin_ciclo,
        )
        .order_by(ClimaDiario.fecha)
    )
    clima_rows = res_clima.scalars().all()

    if not clima_rows:
        print("  ⚠ Sin datos climáticos para el periodo del ciclo (2024-04-15 a 2024-09-01).")
        print("    Ejecuta primero seed_clima_diario.")
        return 0

    # ── Kc lineal por etapa (FAO-56 Figura 25) ────────────────────────────────
    ini = cultivo.dias_etapa_inicial
    dev = cultivo.dias_etapa_desarrollo
    mid = cultivo.dias_etapa_media
    fin = cultivo.dias_etapa_final
    Kc_ini = float(cultivo.kc_inicial)
    Kc_mid = float(cultivo.kc_medio)
    Kc_fin = float(cultivo.kc_final)

    def kc_dia(ddc: int) -> float:
        """Kc según día del ciclo (ddc 1-based). Interpolación lineal entre etapas."""
        if ddc <= ini:
            return Kc_ini
        elif ddc <= ini + dev:
            t = (ddc - ini) / dev
            return Kc_ini + t * (Kc_mid - Kc_ini)
        elif ddc <= ini + dev + mid:
            return Kc_mid
        else:
            t = (ddc - ini - dev - mid) / fin
            return Kc_mid + t * (Kc_fin - Kc_mid)

    # ── Simulación del balance hídrico FAO-56 ─────────────────────────────────
    # Dr = déficit de humedad del suelo (mm). Dr=0 → suelo a CC.
    # Balance diario: Dr(t) = Dr(t-1) + ETc - lluvia
    # Cuando Dr ≥ RAW → riego para reponer CC (lamina = Dr actual).
    Dr = 0.0  # suelo a capacidad de campo tras siembra
    insertados = 0

    for idx, clima in enumerate(clima_rows):
        ddc = idx + 1
        Kc  = kc_dia(ddc)
        ET0 = float(clima.et0) if clima.et0 else 4.0   # fallback conservador
        ETc = Kc * ET0
        lluvia = float(clima.lluvia) if clima.lluvia else 0.0

        # Actualizar déficit
        Dr = Dr + ETc - lluvia
        Dr = max(0.0, min(Dr, TAW))  # acotado [0, TAW]

        if Dr < RAW:
            continue  # no se necesita riego este día

        # ── Evento de riego ───────────────────────────────────────────────────
        lamina    = round(Dr, 2)                        # mm a reponer
        volumen   = round(lamina * 10, 2)               # m³/ha (1 mm = 10 m³/ha)
        duracion  = round((volumen * area_ha) / CAUDAL, 2)  # horas
        costo     = round(volumen * area_ha * TARIFA, 2)    # MXN

        # Urgencia: basada en qué tan cerca está del límite crítico
        if Dr >= 0.85 * TAW:
            urgencia = "critico"
        elif Dr >= 0.65 * TAW:
            urgencia = "moderado"
        else:
            urgencia = "preventivo"

        # Recomendación (ya aceptada en el pasado)
        fecha_dt = datetime(
            clima.fecha.year, clima.fecha.month, clima.fecha.day,
            7, 0, 0, tzinfo=timezone.utc
        )
        reco = Recomendacion(
            id_recomendacion=uuid.uuid4(),
            id_parcela=id_parcela,
            id_cultivo=cultivo.id_cultivo,
            fecha_generacion=fecha_dt,
            fecha_riego_sugerida=clima.fecha,
            lamina_recomendada_mm=lamina,
            eto_referencia=round(ET0, 3),
            etc_calculada=round(ETc, 3),
            deficit_acumulado_mm=lamina,
            dias_sin_riego=ddc,
            nivel_urgencia=urgencia,
            algoritmo_version="fao56-seed-v1.0",
            aceptada="aceptada",
            lamina_ejecutada_mm=lamina,
            parametros_json={
                "fuente": "seeder_sintetico_pv2024",
                "ddc": ddc,
                "kc": round(Kc, 3),
                "et0": round(ET0, 2),
                "etc": round(ETc, 2),
                "lluvia": round(lluvia, 2),
                "taw_mm": round(TAW, 2),
                "raw_mm": round(RAW, 2),
                "p_factor": p,
            },
        )
        db.add(reco)
        await db.flush()  # necesario para obtener id_recomendacion antes del commit

        # Historial de riego vinculado a la recomendación
        riego = HistorialRiego(
            id_riego=uuid.uuid4(),
            id_parcela=id_parcela,
            id_recomendacion=reco.id_recomendacion,
            fecha_riego=clima.fecha,
            volumen_m3_ha=volumen,
            lamina_mm=lamina,
            duracion_horas=duracion,
            metodo_riego="gravedad",
            origen_decision="sistema",
            costo_energia_mxn=costo,
            observaciones=(
                f"Riego sintético PV-2024 — día {ddc} del ciclo. "
                f"Kc={Kc:.2f}, ETc={ETc:.2f} mm/d, déficit={lamina} mm."
            ),
        )
        db.add(riego)
        insertados += 1
        Dr = 0.0  # reponer el suelo a CC tras el riego

    await db.commit()
    print(
        f"  + historial_riego: {insertados} eventos de riego insertados "
        f"(PV-2024, Maíz, parcela {id_parcela})"
    )
    return insertados


async def main(reset: bool = False, check_only: bool = False) -> None:
    """Punto de entrada principal de la inicialización."""
    print("=" * 60)
    print("  MILPÍN AgTech v2.0 — Inicialización de Base de Datos")
    print("=" * 60)

    # 1. Verificar conexión
    ok = await verificar_conexion()
    if not ok:
        sys.exit(1)

    if check_only:
        print("\nVerificación completada. Usa --reset para (re)inicializar.")
        return

    # 2. Opcional: borrar todo
    if reset:
        print("\n⚠  MODO RESET: Se eliminarán TODAS las tablas y datos.")
        confirmacion = input("   ¿Confirmar? (escribe 'SI' para continuar): ")
        if confirmacion.strip().upper() != "SI":
            print("   Cancelado.")
            return
        await drop_all_tables()
        print("  ✓ Tablas eliminadas.")

    # 3. Crear tablas
    print("\nCreando tablas...")
    await create_all_tables()
    print("  ✓ Tablas creadas (o ya existían).")

    # 4. Cargar datos semilla
    print("\nCargando cultivos del catálogo FAO-56...")
    async with AsyncSessionLocal() as db:
        n = await seed_cultivos(db)
        print(f"  ✓ {n} cultivos nuevos insertados.")

    print("\nCreando usuario de prueba (solo desarrollo)...")
    async with AsyncSessionLocal() as db:
        await seed_usuario_prueba(db)

    print("\nCreando usuario administrador...")
    async with AsyncSessionLocal() as db:
        await seed_usuario_admin(db)

    # 5. Parcela demo con datos edáficos
    print("\nCreando parcela de prueba...")
    async with AsyncSessionLocal() as db:
        id_parcela = await seed_parcela_prueba(db)

    # 6. Serie climática sintética (365 días)
    if id_parcela:
        print("\nGenerando serie climática sintética (Valle del Yaqui 2024)...")
        async with AsyncSessionLocal() as db:
            await seed_clima_diario(db, id_parcela)

    # 7. Historial de riego sintético (ciclo PV-2024, Maíz)
    if id_parcela:
        print("\nGenerando historial de riego sintético (ciclo PV-2024, Maíz)...")
        async with AsyncSessionLocal() as db:
            n = await seed_historial_riego(db, id_parcela)
            print(f"  ✓ {n} eventos de riego con recomendaciones vinculadas.")

    print("\n" + "=" * 60)
    print("  ✓ Base de datos inicializada correctamente.")
    print("  Inicia el backend con: uvicorn main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    check_only = "--check" in sys.argv
    asyncio.run(main(reset=reset, check_only=check_only))
