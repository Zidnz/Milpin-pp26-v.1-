#!/usr/bin/env python3
"""
MILPÍN — Recuperación de caché NASA POWER tras cambio de UUIDs
===============================================================

Problema: los JSONs cacheados en data/raw/nasa_power/ tienen nombres
  clima_{uuid_viejo}.json
pero las parcelas actuales tienen UUIDs distintos. El ETL busca por
  clima_{id_parcela}.json
y al no encontrarlos re-descarga todo desde la API.

Solución: emparejar cada parcela nueva (CSV) con el JSON viejo más cercano
por distancia de centroide, y copiar el archivo con el nuevo nombre.

Justificación agronómica: NASA POWER tiene resolución de ~0.5°×0.5° (~55 km).
Todos los emparejamientos están dentro del Valle del Yaqui (<15 km entre sí),
lo que garantiza que pertenecen a la misma celda o celdas adyacentes del grid.
La diferencia climática entre 1-3 km es despreciable a nivel diario.

Uso:
    cd "C:\\Users\\madri\\Downloads\\pp26(Omar)"
    python tools/recuperar_cache_nasa.py          # dry-run (solo muestra plan)
    python tools/recuperar_cache_nasa.py --apply  # ejecuta el renombramiento
"""

import csv
import json
import math
import shutil
import argparse
from pathlib import Path

# ── Rutas ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent
JSON_DIR  = ROOT / "data" / "raw" / "nasa_power"
CSV_PATH  = ROOT / "data" / "synthetic" / "parcelas.csv"


def dist_km(a: tuple, b: tuple) -> float:
    """Distancia en km entre dos puntos (lat, lon)."""
    dlat = (b[0] - a[0]) * 111.0
    dlon = (b[1] - a[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.sqrt(dlat**2 + dlon**2)


def centroide_ring(ring: list) -> tuple:
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def cargar_coords_json() -> dict:
    """Extrae (lat, lon) consultada a NASA de cada archivo JSON cacheado."""
    coords = {}
    for f in JSON_DIR.glob("clima_*.json"):
        uuid_old = f.stem.replace("clima_", "")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            c = d["geometry"]["coordinates"]  # [lon, lat, alt]
            coords[uuid_old] = (c[1], c[0])   # (lat, lon)
        except Exception as e:
            print(f"  ⚠ No se pudo leer {f.name}: {e}")
    return coords


def cargar_coords_csv() -> dict:
    """Calcula centroide de cada parcela del CSV."""
    coords = {}
    with CSV_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            geom = json.loads(row["geom"])
            ring = geom["coordinates"][0]
            coords[row["id_parcela"]] = centroide_ring(ring)
    return coords


def emparejar(json_coords: dict, csv_coords: dict) -> list[dict]:
    """
    Para cada UUID nuevo (CSV), encuentra el JSON viejo más cercano.
    Retorna lista de dicts con el plan de copia.
    """
    plan = []
    usados = set()  # evitar que dos parcelas apunten al mismo JSON

    for new_uuid, new_coord in csv_coords.items():
        # ¿Ya existe el archivo con el nuevo nombre? → no hace falta copiar
        target = JSON_DIR / f"clima_{new_uuid}.json"
        if target.exists():
            plan.append({
                "new_uuid": new_uuid,
                "old_uuid": new_uuid,
                "dist_km": 0.0,
                "action": "ya_existe",
                "src": target,
                "dst": target,
            })
            usados.add(new_uuid)
            continue

        # Buscar el JSON más cercano que no haya sido asignado ya
        candidatos = [
            (uuid_old, dist_km(new_coord, old_coord))
            for uuid_old, old_coord in json_coords.items()
            if uuid_old not in usados
        ]
        if not candidatos:
            plan.append({
                "new_uuid": new_uuid,
                "old_uuid": None,
                "dist_km": None,
                "action": "sin_candidato",
                "src": None,
                "dst": target,
            })
            continue

        candidatos.sort(key=lambda x: x[1])
        best_uuid, best_dist = candidatos[0]

        plan.append({
            "new_uuid": new_uuid,
            "old_uuid": best_uuid,
            "dist_km": round(best_dist, 3),
            "action": "copiar",
            "src": JSON_DIR / f"clima_{best_uuid}.json",
            "dst": target,
        })
        usados.add(best_uuid)

    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Ejecuta la copia. Sin este flag solo muestra el plan.")
    args = ap.parse_args()

    print("=" * 60)
    print("  MILPÍN — Recuperación de caché NASA POWER")
    print("=" * 60)

    print("\nLeyendo coordenadas de JSONs cacheados...")
    json_coords = cargar_coords_json()
    print(f"  {len(json_coords)} JSONs encontrados")

    print("Leyendo centroides de parcelas.csv...")
    csv_coords = cargar_coords_csv()
    print(f"  {len(csv_coords)} parcelas en CSV")

    print("\nCalculando emparejamiento...")
    plan = emparejar(json_coords, csv_coords)

    # ── Resumen del plan ──────────────────────────────────────────────────────
    ya_existe   = [p for p in plan if p["action"] == "ya_existe"]
    a_copiar    = [p for p in plan if p["action"] == "copiar"]
    sin_cand    = [p for p in plan if p["action"] == "sin_candidato"]

    print(f"\n  Ya existen con UUID correcto : {len(ya_existe)}")
    print(f"  A copiar (UUID viejo → nuevo): {len(a_copiar)}")
    print(f"  Sin candidato (necesita API) : {len(sin_cand)}")

    if a_copiar:
        dists = [p["dist_km"] for p in a_copiar]
        print(f"\n  Distancias de emparejamiento:")
        print(f"    min={min(dists):.2f} km  "
              f"media={sum(dists)/len(dists):.2f} km  "
              f"max={max(dists):.2f} km")
        print(f"\n  {'UUID nuevo (CSV)':<38} {'UUID viejo (JSON)':<38} {'dist km':>8}")
        print("  " + "-" * 88)
        for p in sorted(a_copiar, key=lambda x: x["dist_km"]):
            print(f"  {p['new_uuid']:<38} {p['old_uuid']:<38} {p['dist_km']:>8.3f}")

    if sin_cand:
        print(f"\n  Parcelas SIN JSON disponible (se descargarán de NASA POWER):")
        for p in sin_cand:
            print(f"    {p['new_uuid']}")

    if not args.apply:
        print("\n" + "=" * 60)
        print("  Modo DRY-RUN. Para ejecutar agrega --apply")
        print("=" * 60)
        return

    # ── Ejecutar copia ────────────────────────────────────────────────────────
    print(f"\nCopiando {len(a_copiar)} archivos...")
    copiados = 0
    errores = 0
    for p in a_copiar:
        try:
            shutil.copy2(p["src"], p["dst"])
            copiados += 1
        except Exception as e:
            print(f"  ✗ Error copiando {p['old_uuid']} → {p['new_uuid']}: {e}")
            errores += 1

    print(f"\n  ✓ {copiados} archivos copiados")
    if errores:
        print(f"  ✗ {errores} errores")

    total_ok = len(ya_existe) + copiados
    print(f"\n  Total parcelas con caché listo: {total_ok}/{len(csv_coords)}")
    if sin_cand:
        print(f"  {len(sin_cand)} parcelas se descargarán de NASA POWER al correr el ETL.")

    print("\n" + "=" * 60)
    print("  Siguiente paso:")
    print("    cd backend")
    print("    python -m tools.nasa_power_etl")
    print("  (usará caché para las que ya tienen JSON, descargará las demás)")
    print("=" * 60)


if __name__ == "__main__":
    main()
