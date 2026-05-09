import asyncio
import os
import sys
from pathlib import Path

# Cambiar al directorio backend para que database.py encuentre el .env
backend_dir = Path(__file__).parent / "backend"
os.chdir(backend_dir)
sys.path.insert(0, str(backend_dir))

from database import AsyncSessionLocal
from sqlalchemy import text


async def main():
    print("Conectando a la base de datos...")
    try:
        async with AsyncSessionLocal() as db:
            r = await db.execute(text("SELECT COUNT(*) FROM clima_diario"))
            total = r.scalar()

            r2 = await db.execute(text("SELECT MIN(fecha), MAX(fecha) FROM clima_diario"))
            row = r2.fetchone()

            r3 = await db.execute(text("SELECT COUNT(DISTINCT id_parcela) FROM clima_diario"))
            parcelas = r3.scalar()

            print(f"  Filas en clima_diario : {total:,}")
            print(f"  Parcelas con datos    : {parcelas}")
            print(f"  Fecha mas antigua     : {row[0]}")
            print(f"  Fecha mas reciente    : {row[1]}")

            if total == 0:
                print("\n  PROBLEMA: tabla vacia. El ETL no escribio en BD.")
            else:
                print("\n  OK: datos en base de datos.")

    except Exception as e:
        print(f"\n  ERROR: {e}")


asyncio.run(main())
