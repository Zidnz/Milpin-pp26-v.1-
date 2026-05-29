#!/usr/bin/env python3
"""
MILPÍN — Importador de CSVs sintéticos a PostgreSQL
====================================================

Trunca las tablas existentes e importa los CSVs de data/synthetic/ en el
orden correcto de claves foráneas.

Decisiones de diseño:
  - Usa psycopg2 (sync) en lugar de asyncpg para simplicidad de script.
  - TRUNCATE CASCADE antes de importar → estado limpio y reproducible.
  - parcelas.geom: el CSV trae GeoJSON string → ST_SetSRID(ST_GeomFromGeoJSON, 4326).
  - historial_riego: columnas 'ciclo_agricola' y 'ciclo_vol_target_m3_ha' del CSV
    no existen en el schema → se ignoran explícitamente.
  - id_recomendacion vacío en historial_riego → NULL.
  - clima_diario queda vacía después de la importación (no está en los CSVs).
    Rellenar con init_db.py o nasa_power_etl.py.

Uso (desde la raíz del proyecto, con el venv activo):
    cd backend
    python ../tools/importar_csv_postgres.py

Requisito adicional (si no está instalado):
    pip install psycopg2-binary
"""

import csv
import json
import os
import sys
from pathlib import Path

# ── Rutas ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # tools/
PROJECT_ROOT = SCRIPT_DIR.parent                      # raíz del proyecto
DATA_DIR     = PROJECT_ROOT / "data" / "synthetic"
BACKEND_DIR  = PROJECT_ROOT / "backend"

# ── Leer .env manualmente (evita dependencia de dotenv si no está instalado) ──
def _leer_env(path: Path) -> dict:
    env = {}
    if path.exists():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    return env

_env = _leer_env(BACKEND_DIR / ".env")
_raw_url = _env.get("DATABASE_URL") or os.getenv("DATABASE_URL", "")

# asyncpg URL → psycopg2 DSN
DSN = _raw_url.replace("postgresql+asyncpg://", "postgresql://")

if not DSN.startswith("postgresql://"):
    print("✗ DATABASE_URL no encontrado o no es PostgreSQL.")
    print("  Asegúrate de que backend/.env existe y tiene DATABASE_URL.")
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _none(v: str):
    """Convierte string vacío a None."""
    return None if (v is None or v == "") else v


def _bool(v: str) -> bool:
    return str(v).lower() in ("true", "1", "t", "yes")


def leer_csv(nombre: str) -> list[dict]:
    path = DATA_DIR / nombre
    if not path.exists():
        print(f"  ✗ Archivo no encontrado: {path}")
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Importadores por tabla ────────────────────────────────────────────────────

def importar_cultivos(cur, filas: list[dict]) -> int:
    sql = """
        INSERT INTO cultivos_catalogo (
            id_cultivo, nombre_comun, nombre_cientifico,
            kc_inicial, kc_medio, kc_final, ky_total,
            dias_etapa_inicial, dias_etapa_desarrollo,
            dias_etapa_media, dias_etapa_final,
            rendimiento_potencial_ton
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    for r in filas:
        cur.execute(sql, (
            r["id_cultivo"],
            r["nombre_comun"],
            _none(r.get("nombre_cientifico", "")),
            r["kc_inicial"], r["kc_medio"], r["kc_final"], r["ky_total"],
            r["dias_etapa_inicial"], r["dias_etapa_desarrollo"],
            r["dias_etapa_media"], r["dias_etapa_final"],
            _none(r.get("rendimiento_potencial_ton", "")),
        ))
    return len(filas)


def importar_usuarios(cur, filas: list[dict]) -> int:
    sql = """
        INSERT INTO usuarios (
            id_usuario, nombre_completo, email,
            telefono, modulo_dr041, activo, created_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (email) DO NOTHING
    """
    for r in filas:
        cur.execute(sql, (
            r["id_usuario"],
            r["nombre_completo"],
            r["email"],
            _none(r.get("telefono", "")),
            _none(r.get("modulo_dr041", "")),
            _bool(r.get("activo", "True")),
            _none(r.get("created_at", "")),
        ))
    return len(filas)


def importar_parcelas(cur, filas: list[dict]) -> int:
    # parcelas.geom llega como GeoJSON string → ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
    sql = """
        INSERT INTO parcelas (
            id_parcela, id_usuario, id_cultivo_actual, nombre_parcela,
            geom, area_ha, tipo_suelo, conductividad_electrica,
            profundidad_raiz_cm, capacidad_campo, punto_marchitez,
            sistema_riego, activo, created_at
        ) VALUES (
            %s, %s, %s, %s,
            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT DO NOTHING
    """
    errores = 0
    for r in filas:
        geom_raw = r.get("geom", "")
        # csv.DictReader ya desescapa las comillas dobles → debería ser JSON válido
        try:
            json.loads(geom_raw)  # validación rápida
        except json.JSONDecodeError:
            print(f"  ⚠ geom inválido en parcela {r.get('id_parcela', '?')}, saltando")
            errores += 1
            continue

        cur.execute(sql, (
            r["id_parcela"],
            r["id_usuario"],
            _none(r.get("id_cultivo_actual", "")),
            _none(r.get("nombre_parcela", "")),
            geom_raw,
            _none(r.get("area_ha", "")),
            _none(r.get("tipo_suelo", "")),
            _none(r.get("conductividad_electrica", "")),
            _none(r.get("profundidad_raiz_cm", "")),
            _none(r.get("capacidad_campo", "")),
            _none(r.get("punto_marchitez", "")),
            _none(r.get("sistema_riego", "")),
            _bool(r.get("activo", "True")),
            _none(r.get("created_at", "")),
        ))
    if errores:
        print(f"  ⚠ {errores} parcelas con geom inválido fueron omitidas")
    return len(filas) - errores


def importar_recomendaciones(cur, filas: list[dict]) -> int:
    import psycopg2.extras as _extras
    sql = """
        INSERT INTO recomendaciones (
            id_recomendacion, id_parcela, id_cultivo,
            fecha_generacion, fecha_riego_sugerida,
            lamina_recomendada_mm, eto_referencia, etc_calculada,
            deficit_acumulado_mm, dias_sin_riego,
            nivel_urgencia, algoritmo_version,
            aceptada, lamina_ejecutada_mm, parametros_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    for r in filas:
        raw_json = r.get("parametros_json", "")
        params = _extras.Json(json.loads(raw_json)) if raw_json else None

        cur.execute(sql, (
            r["id_recomendacion"],
            r["id_parcela"],
            _none(r.get("id_cultivo", "")),
            _none(r.get("fecha_generacion", "")),
            _none(r.get("fecha_riego_sugerida", "")),
            _none(r.get("lamina_recomendada_mm", "")),
            _none(r.get("eto_referencia", "")),
            _none(r.get("etc_calculada", "")),
            _none(r.get("deficit_acumulado_mm", "")),
            _none(r.get("dias_sin_riego", "")),
            _none(r.get("nivel_urgencia", "")),
            _none(r.get("algoritmo_version", "")),
            r.get("aceptada", "pendiente"),
            _none(r.get("lamina_ejecutada_mm", "")),
            params,
        ))
    return len(filas)


def importar_historial_riego(cur, filas: list[dict]) -> int:
    # ciclo_agricola y ciclo_vol_target_m3_ha ahora forman parte del schema
    # (migración 0004). Se importan directamente desde el CSV sintético.
    sql = """
        INSERT INTO historial_riego (
            id_riego, id_parcela, id_recomendacion,
            fecha_riego, ciclo_agricola, ciclo_vol_target_m3_ha,
            volumen_m3_ha, lamina_mm, duracion_horas,
            metodo_riego, origen_decision, costo_energia_mxn,
            observaciones, created_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    for r in filas:
        cur.execute(sql, (
            r["id_riego"],
            r["id_parcela"],
            _none(r.get("id_recomendacion", "")),   # vacío → NULL (riego manual)
            r["fecha_riego"],
            _none(r.get("ciclo_agricola", "")),
            _none(r.get("ciclo_vol_target_m3_ha", "")),
            _none(r.get("volumen_m3_ha", "")),
            _none(r.get("lamina_mm", "")),
            _none(r.get("duracion_horas", "")),
            _none(r.get("metodo_riego", "")),
            _none(r.get("origen_decision", "")),
            _none(r.get("costo_energia_mxn", "")),
            _none(r.get("observaciones", "")),
            _none(r.get("created_at", "")),
        ))
    return len(filas)


def importar_costos_ciclo(cur, filas: list[dict]) -> int:
    sql = """
        INSERT INTO costos_ciclo (
            id_costo, id_parcela, ciclo_agricola, cultivo,
            volumen_agua_total_m3, costo_agua_mxn,
            costo_fertilizantes_mxn, costo_agroquimicos_mxn,
            costo_semilla_mxn, costo_maquinaria_mxn, costo_mano_obra_mxn,
            ingreso_estimado_mxn, margen_contribucion_mxn
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """
    for r in filas:
        cur.execute(sql, (
            r["id_costo"], r["id_parcela"],
            r["ciclo_agricola"],
            _none(r.get("cultivo", "")),
            _none(r.get("volumen_agua_total_m3", "")),
            _none(r.get("costo_agua_mxn", "")),
            _none(r.get("costo_fertilizantes_mxn", "")),
            _none(r.get("costo_agroquimicos_mxn", "")),
            _none(r.get("costo_semilla_mxn", "")),
            _none(r.get("costo_maquinaria_mxn", "")),
            _none(r.get("costo_mano_obra_mxn", "")),
            _none(r.get("ingreso_estimado_mxn", "")),
            _none(r.get("margen_contribucion_mxn", "")),
        ))
    return len(filas)


# ── Verificación final ────────────────────────────────────────────────────────

def verificar_conteos(cur):
    tablas = [
        "usuarios", "cultivos_catalogo", "parcelas",
        "recomendaciones", "historial_riego", "costos_ciclo", "clima_diario",
    ]
    print("\n=== Conteo final en PostgreSQL ===")
    for t in tablas:
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        n = cur.fetchone()[0]
        print(f"  {t:<35} {n:>8} filas")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("✗ psycopg2 no está instalado.")
        print("  Ejecuta:  pip install psycopg2-binary")
        sys.exit(1)

    print("=" * 55)
    print("  MILPÍN — Importador CSV → PostgreSQL")
    print("=" * 55)
    print(f"\n  Origen : {DATA_DIR}")
    host_db = DSN.split("@")[-1] if "@" in DSN else DSN
    print(f"  Destino: {host_db}")
    print("\n  ⚠  Esta operación TRUNCARÁ todas las tablas.")
    print("     Se perderán: seeder demo, clima_diario y cualquier dato existente.")
    resp = input("\n  ¿Confirmar? (escribe SI): ").strip()
    if resp.upper() != "SI":
        print("  Cancelado.")
        sys.exit(0)

    # Conectar
    try:
        conn = psycopg2.connect(DSN)
        conn.autocommit = False
        print(f"\n✓ Conectado a: {host_db}")
    except Exception as e:
        print(f"✗ Error de conexión: {e}")
        sys.exit(1)

    cur = conn.cursor()

    try:
        # 1. Truncar en orden inverso a FKs
        print("\n[1/8] Truncando tablas...")
        for t in ["costos_ciclo", "historial_riego", "recomendaciones",
                  "clima_diario", "parcelas", "cultivos_catalogo", "usuarios"]:
            cur.execute(f"TRUNCATE TABLE {t} CASCADE;")
            print(f"  ✓ {t}")
        conn.commit()

        pasos = [
            ("[2/8] cultivos_catalogo", "cultivos_catalogo.csv", importar_cultivos),
            ("[3/8] usuarios",          "usuarios.csv",          importar_usuarios),
            ("[4/8] parcelas",          "parcelas.csv",          importar_parcelas),
            ("[5/8] recomendaciones",   "recomendaciones.csv",   importar_recomendaciones),
            ("[6/8] historial_riego",   "historial_riego.csv",   importar_historial_riego),
            ("[7/8] costos_ciclo",      "costos_ciclo.csv",      importar_costos_ciclo),
        ]

        for label, archivo, fn in pasos:
            print(f"\n{label}: {archivo}")
            filas = leer_csv(archivo)
            if not filas:
                print("  ⚠ Sin filas, saltando.")
                continue
            n = fn(cur, filas)
            conn.commit()
            print(f"  ✓ {n} filas insertadas")

        # 8. Conteo final
        print("\n[8/8] Verificando conteos...")
        verificar_conteos(cur)

        print("\n" + "=" * 55)
        print("  ✓ Importación completada.")
        print()
        print("  NOTA: clima_diario quedó vacía.")
        print("  Para regenerarla para la parcela demo, ejecuta:")
        print("    cd backend && python init_db.py")
        print("  (solo insertará clima_diario; el resto ya existe y")
        print("   tiene ON CONFLICT DO NOTHING)")
        print("=" * 55)

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error durante la importación: {e}")
        import traceback
        traceback.print_exc()
        print("\n  Se hizo rollback. La BD no fue modificada en este paso.")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
