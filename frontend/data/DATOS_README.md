# Fuentes de Datos Geoespaciales — MILPÍN AgTech v2.0

Este directorio contiene los archivos GeoJSON que alimentan las capas del mapa.
El motor (`map_engine.js`) espera estos archivos exactos:

| Archivo | Capa | Fuente oficial | Estado |
|---------|------|----------------|--------|
| `cajeme_limits.geojson` | Polígono municipal de Cajeme | INEGI | Pendiente |
| `red_hidrografica.geojson` | Ríos y arroyos | CONAGUA / INEGI | Pendiente |
| `canales_riego.geojson` | Canales del Distrito de Riego 041 | CONAGUA | Pendiente |
| `pozos.geojson` | Pozos de extracción | CONAGUA REPDA | Pendiente |
| `lotes.geojson` | Parcelas agrícolas (prototipo) | Generado manualmente | ✅ Listo |

---

## 1. Límites de Cajeme (INEGI — Marco Geoestadístico)

**Portal:** https://www.inegi.org.mx/temas/mg/

- Ir a "Descarga" → Marco Geoestadístico, Diciembre 2024 (o la versión más reciente)
- Descargar: **Áreas geoestadísticas municipales** (nivel municipal)
- El archivo viene como Shapefile (.shp + .dbf + .shx + .prj)
- Filtrar por: `CVE_ENT = "26"` (Sonora), `CVE_MUN = "018"` (Cajeme)

**Conversión a GeoJSON:**

Opción A — Línea de comandos (requiere GDAL/ogr2ogr):
```bash
ogr2ogr -f GeoJSON cajeme_limits.geojson \
  conjunto_de_datos/00mun.shp \
  -where "CVEGEO='26018'" \
  -t_srs EPSG:4326 \
  -lco COORDINATE_PRECISION=6
```

Opción B — Web (sin instalar nada):
1. Ir a https://mapshaper.org
2. Drag & drop los 4 archivos del shapefile (.shp, .dbf, .shx, .prj)
3. Consola de mapshaper: `filter 'CVEGEO === "26018"'`
4. Export → GeoJSON
5. Renombrar como `cajeme_limits.geojson`

Opción C — Python (con geopandas):
```python
import geopandas as gpd
mun = gpd.read_file("00mun.shp")
cajeme = mun[mun["CVEGEO"] == "26018"]
cajeme.to_file("cajeme_limits.geojson", driver="GeoJSON")
```

---

## 2. Red Hidrográfica (INEGI — Red Hidrográfica 1:50,000)

**Portal:** https://www.inegi.org.mx/temas/hidrografia/

- Buscar: "Red hidrográfica escala 1:50 000 edición 2.0"
- Descargar la **Región Hidrológica RH09** (Sonora Sur) que cubre la cuenca del Río Yaqui
- El shapefile incluye: corrientes de agua (ríos, arroyos), cuerpos de agua (presas, lagunas)

**Conversión:**

```bash
# Extraer solo las corrientes de agua dentro del bbox de Cajeme
ogr2ogr -f GeoJSON red_hidrografica.geojson \
  red_hidrografica_rh09.shp \
  -spat -110.35 27.05 -109.70 27.70 \
  -t_srs EPSG:4326 \
  -lco COORDINATE_PRECISION=6
```

El flag `-spat` recorta por bounding box (Cajeme aprox: lon -110.35 a -109.70, lat 27.05 a 27.70).

**Propiedades esperadas por map_engine.js:**
- `NOMBRE` o `nombre`: Nombre del cuerpo de agua
- `TIPO` o `tipo`: "rio", "arroyo", "canal", "presa" (para asignar estilo)

---

## 3. Canales de Riego — Distrito de Riego 041 (CONAGUA)

**Fuente primaria:** Los canales del DR-041 Rio Yaqui no siempre están en portales de descarga directa.

**Alternativas reales:**

a) **CONAGUA SINA** (https://sina.conagua.gob.mx/sina/): Buscar infraestructura hidroagrícola.
   Puede requerir solicitud de información vía INAI/PNT (Plataforma Nacional de Transparencia).

b) **OpenStreetMap vía Overpass API** (gratuito, datos comunitarios):
   ```
   [out:json][timeout:60];
   (
     way["waterway"="canal"](27.05,-110.35,27.70,-109.70);
     way["waterway"="ditch"](27.05,-110.35,27.70,-109.70);
   );
   out geom;
   ```
   Ejecutar en: https://overpass-turbo.eu → Export → GeoJSON
   Renombrar como `canales_riego.geojson`

c) **IMTA** (Instituto Mexicano de Tecnología del Agua):
   https://www.gob.mx/imta — Tienen capas SIG de distritos de riego.

---

## 4. Pozos de Extracción (CONAGUA REPDA)

**Portal:** https://app.conagua.gob.mx/consultarepda.aspx

- REPDA = Registro Público de Derechos de Agua
- Buscar por: Estado = Sonora, Municipio = Cajeme, Uso = Agrícola
- El REPDA no siempre da coordenadas precisas. Alternativa:

**Alternativa OSM:**
```
[out:json][timeout:30];
node["man_made"="water_well"](27.05,-110.35,27.70,-109.70);
out;
```

**Esquema esperado por map_engine.js:**
```json
{
  "type": "Feature",
  "properties": {
    "nombre": "Pozo Bácum 1",
    "flujo": "40 L/s",
    "estado": "activo"
  },
  "geometry": { "type": "Point", "coordinates": [-109.920, 27.375] }
}
```

---

## Notas de rendimiento

- Simplificar geometrías complejas antes de servir al frontend.
  En mapshaper: `simplify dp 15%` reduce el peso ~80% sin pérdida visual a zoom 10-14.
- Target: cada GeoJSON < 500 KB para carga rápida en móvil.
- Los archivos se sirven desde `/data/` como recursos estáticos.
  En producción, considerar servir desde un CDN o comprimir con gzip.
