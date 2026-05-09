"""
tools/geo_pipeline.py
=====================
Pipeline GIS para MILPÍN AgTech v2.0
Convierte Shapefiles nacionales de INEGI/CONAGUA en GeoJSON ligeros
recortados al municipio de Cajeme, Sonora.

Dependencias:
    pip install geopandas shapely pyproj

Uso:
    python tools/geo_pipeline.py \
        --municipios  ruta/a/26mun.shp \
        --rios        ruta/a/red_hidrografica.shp \
        --canales     ruta/a/canales_DR041.shp \
        --pozos       ruta/a/acuifero_2626_pozos.shp \
        --out         frontend/data

Si una capa no está disponible, omite el argumento y se saltará.
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely.validation import make_valid


# ── Constantes ──────────────────────────────────────────────────────────────

# Cajeme en el Marco Geoestadístico de INEGI:
#   CVE_ENT = '26'  → Sonora
#   CVE_MUN = '018' → Cajeme
# Usar ambos evita falsos positivos si existiera otro "Cajeme" en otro estado.
CAJEME_ENT = "26"
CAJEME_MUN = "018"

# EPSG:4326 = WGS84 geográfico (latitud/longitud en grados decimales).
# Leaflet y la especificación GeoJSON RFC 7946 exigen este CRS.
CRS_WEB = "EPSG:4326"

# Tolerancia de simplificación en grados decimales (unidades de EPSG:4326).
# Referencia de escala:
#   0.00001° ≈  1.1 m   → detalle catastral
#   0.0001°  ≈ 11   m   → parcelas agrícolas
#   0.0005°  ≈ 55   m   → red hidrográfica a zoom 12-14
#   0.001°   ≈ 111  m   → límites municipales a zoom 10-12
#   0.005°   ≈ 555  m   → contornos regionales
#
# Para el polígono municipal (se ve completo desde zoom 9-11) usamos 0.001°.
# Para ríos/canales (zoom 11-14) usamos 0.0005° para mantener meandros legibles.
# Los pozos son puntos → no se simplifican.
TOL_MUNICIPIO = 0.001   # ° → ~111 m de error máximo admisible en el borde
TOL_LINEAS    = 0.0005  # ° → ~55  m para trazados hidrográficos

# Número máximo de decimales en las coordenadas GeoJSON exportadas.
# RFC 7946 recomienda ≤6 decimales (≈ 11 cm de precisión), que es
# más que suficiente para visualización en Leaflet.
PRECISION_COORDS = 6


# ── Utilidades ───────────────────────────────────────────────────────────────

def cargar_shp(ruta: str, nombre: str) -> gpd.GeoDataFrame | None:
    """Carga un Shapefile con manejo de errores descriptivo."""
    path = Path(ruta)
    if not path.exists():
        print(f"[WARN] {nombre}: archivo no encontrado → {ruta}")
        return None
    print(f"[INFO] Cargando {nombre}...")
    gdf = gpd.read_file(path)
    print(f"       {len(gdf):,} features | CRS: {gdf.crs}")
    return gdf


def asegurar_4326(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Reproyecta a EPSG:4326 si el GeoDataFrame está en otro CRS.

    INEGI entrega sus archivos en ITRF2008 / México (equivalente a
    EPSG:4326 pero a veces declarado como EPSG:6365 o sin CRS explícito).
    Si el CRS no está definido asumimos que las coordenadas ya son
    geográficas (grados) y solo declaramos el CRS; NO transformamos.
    """
    if gdf.crs is None:
        print("       [WARN] CRS no declarado. Se asume EPSG:4326.")
        gdf = gdf.set_crs(CRS_WEB)
    elif gdf.crs.to_epsg() != 4326:
        print(f"       Reproyectando {gdf.crs.to_epsg()} → 4326...")
        gdf = gdf.to_crs(CRS_WEB)
    return gdf


def reparar_geometrias(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Corrige geometrías inválidas (auto-intersecciones, anillos abiertos, etc.)
    usando make_valid() de Shapely antes de cualquier operación de clip o
    simplificación, ya que estas fallan con geometrías rotas.
    """
    invalidas = (~gdf.is_valid).sum()
    if invalidas > 0:
        print(f"       Reparando {invalidas} geometría(s) inválida(s)...")
        gdf = gdf.copy()
        gdf["geometry"] = gdf["geometry"].apply(make_valid)
    return gdf


def simplificar(gdf: gpd.GeoDataFrame, tolerancia: float) -> gpd.GeoDataFrame:
    """
    Aplica simplificación de Douglas-Peucker con preserve_topology=True.

    preserve_topology=True garantiza que el polígono no se auto-interseque
    ni pierda huecos interiores durante la simplificación.  Es más lento
    que preserve_topology=False pero evita artefactos visuales.
    """
    antes = gdf.memory_usage(deep=True).sum() // 1024
    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].simplify(tolerancia, preserve_topology=True)
    despues = gdf.memory_usage(deep=True).sum() // 1024
    print(f"       Simplificado (tol={tolerancia}°): {antes} KB → {despues} KB")
    return gdf


def exportar_geojson(gdf: gpd.GeoDataFrame, ruta_salida: Path, nombre: str) -> None:
    """
    Exporta a GeoJSON con precisión de coordenadas controlada.

    geopandas delega en Fiona/pyogrio la escritura.  El parámetro
    COORDINATE_PRECISION reduce el número de decimales y es la palanca
    principal para reducir el tamaño final del archivo.
    """
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(
        ruta_salida,
        driver="GeoJSON",
        # COORDINATE_PRECISION se pasa como kwarg al driver de Fiona
        COORDINATE_PRECISION=PRECISION_COORDS,
    )
    kb = ruta_salida.stat().st_size // 1024
    print(f"[OK]   {nombre} → {ruta_salida} ({kb} KB, {len(gdf)} features)")


# ── Etapas del pipeline ───────────────────────────────────────────────────────

def procesar_municipio(ruta_shp: str, dir_salida: Path) -> gpd.GeoDataFrame | None:
    """
    Etapa 1: Extrae el polígono oficial de Cajeme desde el MGN de INEGI.

    Columnas clave del Marco Geoestadístico Nacional:
        CVE_ENT  → clave de entidad federativa (string con ceros iniciales)
        CVE_MUN  → clave de municipio          (string con ceros iniciales)
        NOMGEO   → nombre geográfico oficial
    """
    gdf = cargar_shp(ruta_shp, "Municipios INEGI")
    if gdf is None:
        return None

    gdf = asegurar_4326(gdf)
    gdf = reparar_geometrias(gdf)

    # Normalizar claves a string con ceros iniciales (a veces vienen como int)
    gdf["CVE_ENT"] = gdf["CVE_ENT"].astype(str).str.zfill(2)
    gdf["CVE_MUN"] = gdf["CVE_MUN"].astype(str).str.zfill(3)

    cajeme = gdf[(gdf["CVE_ENT"] == CAJEME_ENT) & (gdf["CVE_MUN"] == CAJEME_MUN)].copy()

    if cajeme.empty:
        # Fallback: búsqueda por nombre (menos seguro, puede traer homónimos)
        print("[WARN] No se encontró Cajeme por clave. Buscando por nombre...")
        cajeme = gdf[gdf["NOMGEO"].str.upper().str.contains("CAJEME", na=False)].copy()

    if cajeme.empty:
        print("[ERROR] No se encontró el municipio de Cajeme en el Shapefile.")
        return None

    print(f"       Polígono de Cajeme encontrado: {cajeme.iloc[0].get('NOMGEO', 'N/D')}")

    cajeme = simplificar(cajeme, TOL_MUNICIPIO)
    exportar_geojson(cajeme, dir_salida / "cajeme_limite.geojson", "Límite Cajeme")
    return cajeme


def procesar_rios_canales(
    ruta_rios: str,
    ruta_canales: str,
    cajeme_gdf: gpd.GeoDataFrame,
    dir_salida: Path,
) -> None:
    """
    Etapa 2: Recorta la red hidrográfica al polígono de Cajeme.

    gpd.clip() implementa el algoritmo de intersección de Shapely.
    Es preferible a sjoin() porque conserva geometrías parciales
    (trozos de río que entran y salen del municipio), mientras que
    sjoin solo conservaría líneas cuyo centroide cae dentro.

    Si ambas capas (ríos SINA + canales DR-041) están disponibles,
    las une en un solo GeoDataFrame para minimizar peticiones HTTP en el frontend.
    """
    capas = []

    if ruta_rios:
        gdf_rios = cargar_shp(ruta_rios, "Red Hidrográfica SINA")
        if gdf_rios is not None:
            gdf_rios = asegurar_4326(gdf_rios)
            gdf_rios = reparar_geometrias(gdf_rios)
            # Etiquetar para distinguir en el frontend
            if "TIPO" not in gdf_rios.columns:
                gdf_rios["TIPO"] = "rio"
            capas.append(gdf_rios)

    if ruta_canales:
        gdf_can = cargar_shp(ruta_canales, "Canales DR-041")
        if gdf_can is not None:
            gdf_can = asegurar_4326(gdf_can)
            gdf_can = reparar_geometrias(gdf_can)
            if "TIPO" not in gdf_can.columns:
                gdf_can["TIPO"] = "canal"
            capas.append(gdf_can)

    if not capas:
        print("[SKIP] Sin datos de ríos/canales disponibles.")
        return

    # Unir capas y recortar al municipio en un solo paso
    red = gpd.GeoDataFrame(
        gpd.pd.concat(capas, ignore_index=True),
        crs=CRS_WEB,
    )

    print(f"       Recortando {len(red):,} tramos al polígono de Cajeme...")
    # gpd.clip requiere que ambos GDFs estén en el mismo CRS (ya garantizado)
    red_cajeme = gpd.clip(red, cajeme_gdf)
    print(f"       Tramos dentro de Cajeme: {len(red_cajeme):,}")

    # Conservar solo columnas útiles para el frontend
    cols_keep = [c for c in ["NOMBRE", "TIPO", "ORDEN_RED", "geometry"] if c in red_cajeme.columns]
    red_cajeme = red_cajeme[cols_keep]

    red_cajeme = simplificar(red_cajeme, TOL_LINEAS)
    exportar_geojson(red_cajeme, dir_salida / "cajeme_rios_canales.geojson", "Ríos + Canales")


def procesar_pozos(
    ruta_pozos: str,
    cajeme_gdf: gpd.GeoDataFrame,
    dir_salida: Path,
) -> None:
    """
    Etapa 3: Filtra pozos dentro del municipio de Cajeme.

    Los pozos son features de tipo Point.  No se pueden simplificar
    (son ya la geometría más simple posible), por lo que solo se
    aplica filtrado espacial con sjoin (más eficiente para puntos).

    sjoin con predicate='within' conserva únicamente los pozos cuyo
    punto cae estrictamente dentro del polígono municipal.
    """
    gdf = cargar_shp(ruta_pozos, "Pozos Acuífero 2626")
    if gdf is None:
        return

    gdf = asegurar_4326(gdf)
    gdf = reparar_geometrias(gdf)

    print(f"       Filtrando {len(gdf):,} pozos dentro de Cajeme...")
    pozos_cajeme = gpd.sjoin(gdf, cajeme_gdf[["geometry"]], how="inner", predicate="within")

    # Limpiar columnas residuales del join
    pozos_cajeme = pozos_cajeme.drop(columns=["index_right"], errors="ignore")

    # Conservar solo columnas útiles; normalizar nombres para el frontend
    rename_map = {
        "CLAVE":     "id",
        "NOMBRE":    "nombre",
        "CAUDAL":    "flujo",
        "ESTADO":    "estado",
        "CONDICION": "estado",
        "ACUIFERO":  "acuifero",
    }
    pozos_cajeme = pozos_cajeme.rename(columns={k: v for k, v in rename_map.items() if k in pozos_cajeme.columns})
    cols_keep = [c for c in ["id", "nombre", "flujo", "estado", "acuifero", "geometry"] if c in pozos_cajeme.columns]
    pozos_cajeme = pozos_cajeme[cols_keep]

    print(f"       Pozos encontrados: {len(pozos_cajeme):,}")
    exportar_geojson(pozos_cajeme, dir_salida / "cajeme_pozos.geojson", "Pozos")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline GIS: Shapefiles INEGI/CONAGUA → GeoJSON Cajeme"
    )
    parser.add_argument("--municipios", required=True,  help="Ruta al .shp de municipios INEGI (ej. 26mun.shp)")
    parser.add_argument("--rios",       default=None,   help="Ruta al .shp de red hidrográfica SINA")
    parser.add_argument("--canales",    default=None,   help="Ruta al .shp de canales DR-041")
    parser.add_argument("--pozos",      default=None,   help="Ruta al .shp de pozos acuífero 2626")
    parser.add_argument("--out",        default="frontend/data",
                        help="Directorio de salida para los GeoJSON (default: frontend/data)")
    args = parser.parse_args()

    dir_salida = Path(args.out)
    print(f"\n{'='*55}")
    print(f"  MILPÍN GIS Pipeline — Cajeme, Sonora")
    print(f"  Salida: {dir_salida.resolve()}")
    print(f"{'='*55}\n")

    # Etapa 1: municipio (obligatorio — es el polígono de recorte)
    cajeme = procesar_municipio(args.municipios, dir_salida)
    if cajeme is None:
        print("\n[FATAL] Sin polígono de Cajeme no se puede continuar.")
        sys.exit(1)

    # Etapa 2: red hidrográfica (opcional)
    if args.rios or args.canales:
        procesar_rios_canales(args.rios, args.canales, cajeme, dir_salida)
    else:
        print("[SKIP] --rios y --canales no especificados.")

    # Etapa 3: pozos (opcional)
    if args.pozos:
        procesar_pozos(args.pozos, cajeme, dir_salida)
    else:
        print("[SKIP] --pozos no especificado.")

    print(f"\n[DONE] Archivos GeoJSON listos en: {dir_salida.resolve()}\n")


if __name__ == "__main__":
    main()
