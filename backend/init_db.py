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
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, create_all_tables, drop_all_tables, engine
from models import ClimaDiario, CultivoCatalogo, Parcela, Usuario


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
    },
]

# Usuario de prueba para desarrollo
USUARIO_PRUEBA = {
    "nombre_completo": "Ramón Valenzuela Torres",
    "email": "rvalenzuela@dr041-dev.com",
    "telefono": "+52 644 100 0001",
    "modulo_dr041": "Módulo 3",
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
    """Inserta un usuario de prueba para desarrollo."""
    resultado = await db.execute(
        select(Usuario).where(Usuario.email == USUARIO_PRUEBA["email"])
    )
    if resultado.scalar_one_or_none() is None:
        usuario = Usuario(id_usuario=uuid.uuid4(), **USUARIO_PRUEBA)
        db.add(usuario)
        await db.commit()
        print(f"  + Usuario de prueba insertado: {USUARIO_PRUEBA['email']}")
        return True
    else:
        print(f"  ○ Usuario de prueba ya existe: {USUARIO_PRUEBA['email']}")
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

    parcela = Parcela(
        id_parcela=uuid.uuid4(),
        id_usuario=usuario.id_usuario,
        id_cultivo_actual=cultivo.id_cultivo if cultivo else None,
        nombre_parcela="Lote Demo A-3",
        geom={
            "type": "Polygon",
            "coordinates": [[
                [-109.935, 27.365], [-109.930, 27.365],
                [-109.930, 27.370], [-109.935, 27.370],
                [-109.935, 27.365],
            ]],
        },
        area_ha=25.0,
        tipo_suelo="franco-arcilloso",
        conductividad_electrica=1.8,
        profundidad_raiz_cm=60,
        capacidad_campo=0.34,
        punto_marchitez=0.18,
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

    # 5. Parcela demo con datos edáficos
    print("\nCreando parcela de prueba...")
    async with AsyncSessionLocal() as db:
        id_parcela = await seed_parcela_prueba(db)

    # 6. Serie climática sintética (365 días)
    if id_parcela:
        print("\nGenerando serie climática sintética (Valle del Yaqui 2024)...")
        async with AsyncSessionLocal() as db:
            await seed_clima_diario(db, id_parcela)

    print("\n" + "=" * 60)
    print("  ✓ Base de datos inicializada correctamente.")
    print("  Inicia el backend con: uvicorn main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    check_only = "--check" in sys.argv
    asyncio.run(main(reset=reset, check_only=check_only))
