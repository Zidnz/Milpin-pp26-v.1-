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
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, create_all_tables, drop_all_tables, engine
from models import CultivoCatalogo, Usuario


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
        from sqlalchemy import select
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
    from sqlalchemy import select
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

    print("\n" + "=" * 60)
    print("  ✓ Base de datos inicializada correctamente.")
    print("  Inicia el backend con: uvicorn main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    check_only = "--check" in sys.argv
    asyncio.run(main(reset=reset, check_only=check_only))
