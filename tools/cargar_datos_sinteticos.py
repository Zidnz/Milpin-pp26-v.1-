"""
MILPÍN — Cargador de datos sintéticos a PostgreSQL
====================================================

Reemplaza los datos existentes con los CSVs generados por
generar_datos_sinteticos.py.

Uso desde la raíz del proyecto:
    python tools/cargar_datos_sinteticos.py
    python tools/cargar_datos_sinteticos.py --dry-run   # solo valida archivos
    python tools/cargar_datos_sinteticos.py --skip-truncate  # inserta sin borrar

IMPORTANTE: Los UUIDs de los CSVs son autogenerados — si tienes datos reales
(parcelas o riegos ingresados manualmente), usa --skip-truncate para no perderlos.
El script usa INSERT ON CONFLICT DO NOTHING en ese modo.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Configuración ────────────────────────────────────────────────────────────

# Ruta al .env del backend para leer DATABASE_URL
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE  = _REPO_ROOT / "backend" / ".env"
_DATA_DIR  = _REPO_ROOT / "data" / "synthetic"

def _leer_db_url() -> str:
    """Lee DATABASE_URL del .env del backend."""
    if not _ENV_FILE.exists():
        sys.exit(f"ERROR: No se encontró {_ENV_FILE}\n"
                 "Crea el archivo o define DATABASE_URL en el entorno.")
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
            # asyncpg → psycopg2 (quitar +asyncpg del driver)
            return url.replace("postgresql+asyncpg://", "postgresql://")
    sys.exit("ERROR: DATABASE_URL no encontrado en .env")


def _conectar(db_url: str):
    """Devuelve una conexión psycopg2 con autocommit=False."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    psycopg2.extras.register_uuid()
    return conn


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_uuid(val: str):
    return uuid.UUID(val) if val and val.strip() else None

def _parse_float(val: str):
    return float(val) if val and val.strip() else None

def _parse_int(val: str):
    return int(val) if val and val.strip() else None

def _parse_bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "t", "yes")

def _parse_date(val: str):
    return date.fromisoformat(val.strip()) if val and val.strip() else None

def _parse_ts(val: str):
    if not val or not val.strip():
        return None
    v = val.strip()
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None

def _leer_csv(nombre: str) -> list[dict]:
    path = _DATA_DIR / nombre
    if not path.exists():
        sys.exit(f"ERROR: No se encontró {path}\n"
                 "Ejecuta primero: python tools/generar_datos_sinteticos.py")
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Carga por tabla ───────────────────────────────────────────────────────────

def cargar_cultivos(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE cultivos_catalogo CASCADE")

    sql = """
    INSERT INTO cultivos_catalogo (
        id_cultivo, nombre_comun, nombre_cientifico,
        kc_inicial, kc_medio, kc_final, ky_total,
        dias_etapa_inicial, dias_etapa_desarrollo, dias_etapa_media, dias_etapa_final,
        rendimiento_potencial_ton
    ) VALUES (
        %(id_cultivo)s, %(nombre_comun)s, %(nombre_cientifico)s,
        %(kc_inicial)s, %(kc_medio)s, %(kc_final)s, %(ky_total)s,
        %(dias_etapa_inicial)s, %(dias_etapa_desarrollo)s,
        %(dias_etapa_media)s, %(dias_etapa_final)s,
        %(rendimiento_potencial_ton)s
    ) ON CONFLICT (id_cultivo) DO NOTHING
    """
    params = [{
        "id_cultivo":               _parse_uuid(r["id_cultivo"]),
        "nombre_comun":             r["nombre_comun"],
        "nombre_cientifico":        r["nombre_cientifico"],
        "kc_inicial":               _parse_float(r["kc_inicial"]),
        "kc_medio":                 _parse_float(r["kc_medio"]),
        "kc_final":                 _parse_float(r["kc_final"]),
        "ky_total":                 _parse_float(r["ky_total"]),
        "dias_etapa_inicial":       _parse_int(r["dias_etapa_inicial"]),
        "dias_etapa_desarrollo":    _parse_int(r["dias_etapa_desarrollo"]),
        "dias_etapa_media":         _parse_int(r["dias_etapa_media"]),
        "dias_etapa_final":         _parse_int(r["dias_etapa_final"]),
        "rendimiento_potencial_ton":_parse_float(r["rendimiento_potencial_ton"]),
    } for r in filas]
    psycopg2.extras.execute_batch(cur, sql, params, page_size=100)
    return len(params)


def cargar_usuarios(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE usuarios CASCADE")

    sql = """
    INSERT INTO usuarios (
        id_usuario, nombre_completo, email, telefono,
        modulo_dr041, activo, created_at
    ) VALUES (
        %(id_usuario)s, %(nombre_completo)s, %(email)s, %(telefono)s,
        %(modulo_dr041)s, %(activo)s, %(created_at)s
    ) ON CONFLICT (id_usuario) DO NOTHING
    """
    params = [{
        "id_usuario":      _parse_uuid(r["id_usuario"]),
        "nombre_completo": r["nombre_completo"],
        "email":           r["email"],
        "telefono":        r.get("telefono") or None,
        "modulo_dr041":    r.get("modulo_dr041") or None,
        "activo":          _parse_bool(r.get("activo", "true")),
        "created_at":      _parse_ts(r.get("created_at")),
    } for r in filas]
    psycopg2.extras.execute_batch(cur, sql, params, page_size=200)
    return len(params)


def cargar_parcelas(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE parcelas CASCADE")

    sql = """
    INSERT INTO parcelas (
        id_parcela, id_usuario, id_cultivo_actual, nombre_parcela,
        geom, area_ha, tipo_suelo, conductividad_electrica,
        profundidad_raiz_cm, capacidad_campo, punto_marchitez,
        sistema_riego, activo, created_at
    ) VALUES (
        %(id_parcela)s, %(id_usuario)s, %(id_cultivo_actual)s, %(nombre_parcela)s,
        ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326),
        %(area_ha)s, %(tipo_suelo)s, %(conductividad_electrica)s,
        %(profundidad_raiz_cm)s, %(capacidad_campo)s, %(punto_marchitez)s,
        %(sistema_riego)s, %(activo)s, %(created_at)s
    ) ON CONFLICT (id_parcela) DO NOTHING
    """
    params = [{
        "id_parcela":              _parse_uuid(r["id_parcela"]),
        "id_usuario":              _parse_uuid(r["id_usuario"]),
        "id_cultivo_actual":       _parse_uuid(r.get("id_cultivo_actual")),
        "nombre_parcela":          r.get("nombre_parcela") or None,
        "geom":                    r["geom"],           # GeoJSON string → PostGIS
        "area_ha":                 _parse_float(r.get("area_ha")),
        "tipo_suelo":              r.get("tipo_suelo") or None,
        "conductividad_electrica": _parse_float(r.get("conductividad_electrica")),
        "profundidad_raiz_cm":     _parse_int(r.get("profundidad_raiz_cm")),
        "capacidad_campo":         _parse_float(r.get("capacidad_campo")),
        "punto_marchitez":         _parse_float(r.get("punto_marchitez")),
        "sistema_riego":           r.get("sistema_riego") or None,
        "activo":                  _parse_bool(r.get("activo", "true")),
        "created_at":              _parse_ts(r.get("created_at")),
    } for r in filas]
    psycopg2.extras.execute_batch(cur, sql, params, page_size=100)
    return len(params)


def cargar_recomendaciones(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE recomendaciones CASCADE")

    sql = """
    INSERT INTO recomendaciones (
        id_recomendacion, id_parcela, id_cultivo,
        fecha_generacion, fecha_riego_sugerida,
        lamina_recomendada_mm, eto_referencia, etc_calculada,
        deficit_acumulado_mm, dias_sin_riego,
        nivel_urgencia, algoritmo_version, aceptada,
        lamina_ejecutada_mm, parametros_json
    ) VALUES (
        %(id_recomendacion)s, %(id_parcela)s, %(id_cultivo)s,
        %(fecha_generacion)s, %(fecha_riego_sugerida)s,
        %(lamina_recomendada_mm)s, %(eto_referencia)s, %(etc_calculada)s,
        %(deficit_acumulado_mm)s, %(dias_sin_riego)s,
        %(nivel_urgencia)s, %(algoritmo_version)s, %(aceptada)s,
        %(lamina_ejecutada_mm)s, %(parametros_json)s
    ) ON CONFLICT (id_recomendacion) DO NOTHING
    """
    params = []
    for r in filas:
        lam_ej = _parse_float(r.get("lamina_ejecutada_mm"))
        pj_raw = r.get("parametros_json") or ""
        try:
            pj = json.loads(pj_raw) if pj_raw.strip() else None
        except json.JSONDecodeError:
            pj = None
        params.append({
            "id_recomendacion":    _parse_uuid(r["id_recomendacion"]),
            "id_parcela":          _parse_uuid(r["id_parcela"]),
            "id_cultivo":          _parse_uuid(r.get("id_cultivo")),
            "fecha_generacion":    _parse_ts(r.get("fecha_generacion")),
            "fecha_riego_sugerida":_parse_date(r.get("fecha_riego_sugerida")),
            "lamina_recomendada_mm": _parse_float(r.get("lamina_recomendada_mm")),
            "eto_referencia":      _parse_float(r.get("eto_referencia")),
            "etc_calculada":       _parse_float(r.get("etc_calculada")),
            "deficit_acumulado_mm":_parse_float(r.get("deficit_acumulado_mm")),
            "dias_sin_riego":      _parse_int(r.get("dias_sin_riego")),
            "nivel_urgencia":      r.get("nivel_urgencia") or None,
            "algoritmo_version":   r.get("algoritmo_version") or "fao56-v0.2",
            "aceptada":            r.get("aceptada", "pendiente"),
            "lamina_ejecutada_mm": lam_ej,
            "parametros_json":     json.dumps(pj) if pj else None,
        })
    psycopg2.extras.execute_batch(cur, sql, params, page_size=500)
    return len(params)


def cargar_historial(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE historial_riego CASCADE")

    sql = """
    INSERT INTO historial_riego (
        id_riego, id_parcela, ciclo_agricola, id_recomendacion,
        fecha_riego, volumen_m3_ha, lamina_mm, duracion_horas,
        metodo_riego, origen_decision, costo_energia_mxn,
        observaciones, created_at
    ) VALUES (
        %(id_riego)s, %(id_parcela)s, %(ciclo_agricola)s, %(id_recomendacion)s,
        %(fecha_riego)s, %(volumen_m3_ha)s, %(lamina_mm)s, %(duracion_horas)s,
        %(metodo_riego)s, %(origen_decision)s, %(costo_energia_mxn)s,
        %(observaciones)s, %(created_at)s
    ) ON CONFLICT (id_riego) DO NOTHING
    """
    params = []
    for r in filas:
        rec_id = r.get("id_recomendacion", "").strip()
        params.append({
            "id_riego":          _parse_uuid(r["id_riego"]),
            "id_parcela":        _parse_uuid(r["id_parcela"]),
            "ciclo_agricola":    r.get("ciclo_agricola") or None,
            "id_recomendacion":  _parse_uuid(rec_id) if rec_id else None,
            "fecha_riego":       _parse_date(r["fecha_riego"]),
            "volumen_m3_ha":     _parse_float(r.get("volumen_m3_ha")),
            "lamina_mm":         _parse_float(r.get("lamina_mm")),
            "duracion_horas":    _parse_float(r.get("duracion_horas")),
            "metodo_riego":      r.get("metodo_riego") or None,
            "origen_decision":   r.get("origen_decision") or "manual",
            "costo_energia_mxn": _parse_float(r.get("costo_energia_mxn")),
            "observaciones":     r.get("observaciones") or None,
            "created_at":        _parse_ts(r.get("created_at")),
        })
    psycopg2.extras.execute_batch(cur, sql, params, page_size=500)
    return len(params)


def cargar_costos(cur, filas: list[dict], skip_truncate: bool) -> int:
    if not skip_truncate:
        cur.execute("TRUNCATE costos_ciclo CASCADE")

    sql = """
    INSERT INTO costos_ciclo (
        id_costo, id_parcela, ciclo_agricola, cultivo,
        volumen_agua_total_m3, costo_agua_mxn,
        costo_fertilizantes_mxn, costo_agroquimicos_mxn,
        costo_semilla_mxn, costo_maquinaria_mxn, costo_mano_obra_mxn,
        ingreso_estimado_mxn, margen_contribucion_mxn
    ) VALUES (
        %(id_costo)s, %(id_parcela)s, %(ciclo_agricola)s, %(cultivo)s,
        %(volumen_agua_total_m3)s, %(costo_agua_mxn)s,
        %(costo_fertilizantes_mxn)s, %(costo_agroquimicos_mxn)s,
        %(costo_semilla_mxn)s, %(costo_maquinaria_mxn)s, %(costo_mano_obra_mxn)s,
        %(ingreso_estimado_mxn)s, %(margen_contribucion_mxn)s
    ) ON CONFLICT (id_costo) DO NOTHING
    """
    params = [{
        "id_costo":                 _parse_uuid(r["id_costo"]),
        "id_parcela":               _parse_uuid(r["id_parcela"]),
        "ciclo_agricola":           r.get("ciclo_agricola"),
        "cultivo":                  r.get("cultivo"),
        "volumen_agua_total_m3":    _parse_float(r.get("volumen_agua_total_m3")),
        "costo_agua_mxn":           _parse_float(r.get("costo_agua_mxn")),
        "costo_fertilizantes_mxn":  _parse_float(r.get("costo_fertilizantes_mxn")),
        "costo_agroquimicos_mxn":   _parse_float(r.get("costo_agroquimicos_mxn")),
        "costo_semilla_mxn":        _parse_float(r.get("costo_semilla_mxn")),
        "costo_maquinaria_mxn":     _parse_float(r.get("costo_maquinaria_mxn")),
        "costo_mano_obra_mxn":      _parse_float(r.get("costo_mano_obra_mxn")),
        "ingreso_estimado_mxn":     _parse_float(r.get("ingreso_estimado_mxn")),
        "margen_contribucion_mxn":  _parse_float(r.get("margen_contribucion_mxn")),
    } for r in filas]
    psycopg2.extras.execute_batch(cur, sql, params, page_size=200)
    return len(params)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run",      action="store_true",
                    help="Solo valida que los archivos existan y muestran conteos.")
    ap.add_argument("--skip-truncate", action="store_true",
                    help="Inserta sin borrar datos existentes (ON CONFLICT DO NOTHING).")
    args = ap.parse_args()

    # Verificar archivos
    archivos = ["cultivos_catalogo.csv", "usuarios.csv", "parcelas.csv",
                "recomendaciones.csv", "historial_riego.csv", "costos_ciclo.csv"]
    print("\nMILPÍN — Cargador de datos sintéticos")
    print("=" * 45)
    print(f"Directorio: {_DATA_DIR}\n")

    for nombre in archivos:
        path = _DATA_DIR / nombre
        if not path.exists():
            sys.exit(f"ERROR: Falta {nombre}. Ejecuta primero generar_datos_sinteticos.py")
        filas = list(csv.DictReader(path.open(encoding="utf-8")))
        print(f"  ✓ {nombre:<35} {len(filas):>6} filas")

    if args.dry_run:
        print("\n[dry-run] Archivos OK. Nada fue cargado a la base de datos.")
        return

    # Conectar
    db_url = _leer_db_url()
    print(f"\nConectando a: {db_url.split('@')[-1]}")   # oculta credenciales
    try:
        conn = _conectar(db_url)
    except Exception as e:
        sys.exit(f"ERROR de conexión: {e}")
    print("Conexión exitosa.\n")

    modo = "REEMPLAZAR todo" if not args.skip_truncate else "INSERTAR sin borrar (ON CONFLICT DO NOTHING)"
    print(f"Modo: {modo}")

    if not args.skip_truncate:
        confirm = input("\n⚠  Esto borrará TODOS los datos existentes. ¿Continuar? (escribe SI): ")
        if confirm.strip().upper() != "SI":
            print("Cancelado.")
            conn.close()
            return

    try:
        cur = conn.cursor()

        print("\nCargando tablas...")
        n = cargar_cultivos(cur, _leer_csv("cultivos_catalogo.csv"), args.skip_truncate)
        print(f"  [1/6] cultivos_catalogo  → {n} filas")

        n = cargar_usuarios(cur, _leer_csv("usuarios.csv"), args.skip_truncate)
        print(f"  [2/6] usuarios           → {n} filas")

        n = cargar_parcelas(cur, _leer_csv("parcelas.csv"), args.skip_truncate)
        print(f"  [3/6] parcelas           → {n} filas")

        n = cargar_recomendaciones(cur, _leer_csv("recomendaciones.csv"), args.skip_truncate)
        print(f"  [4/6] recomendaciones    → {n} filas")

        n = cargar_historial(cur, _leer_csv("historial_riego.csv"), args.skip_truncate)
        print(f"  [5/6] historial_riego    → {n} filas")

        n = cargar_costos(cur, _leer_csv("costos_ciclo.csv"), args.skip_truncate)
        print(f"  [6/6] costos_ciclo       → {n} filas")

        conn.commit()
        print("\n✓ Commit exitoso. Base de datos actualizada.")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ ERROR: {e}")
        print("Rollback ejecutado — la base de datos no fue modificada.")
        raise
    finally:
        conn.close()

    print("\nReinicia el backend para que tome los nuevos datos:")
    print("  uvicorn backend.main:app --reload\n")


if __name__ == "__main__":
    main()
