"""postgis_geom_jsonb_to_geometry

Migra parcelas.geom de JSONB (GeoJSON almacenado como texto) a
GEOMETRY(Polygon, 4326) nativo de PostGIS.

Estrategia de conversión de datos:
    ST_GeomFromGeoJSON(geom::text) convierte el GeoJSON que había en el
    campo JSONB a geometría PostGIS con SRID 4326. Filas con geom NULL
    quedan NULL (sin cambio). Si el GeoJSON no es un Polygon válido,
    ST_MakeValid() lo repara antes de insertar.

Downgrade:
    Devuelve la columna a JSONB convirtiendo con ST_AsGeoJSON().
    No hay pérdida de datos si la geometría original era un Polygon.

Revision ID: 0001
Revises: (ninguna — primera migración)
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Asegurarse de que la extensión PostGIS esté activa
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology;")

    # 2. Añadir columna temporal con el tipo PostGIS correcto
    op.add_column(
        "parcelas",
        sa.Column(
            "geom_new",
            Geometry(geometry_type="POLYGON", srid=4326, nullable=True),
        ),
    )

    # 3. Convertir los datos existentes de JSONB → GEOMETRY
    #    ST_MakeValid repara polígonos con auto-intersecciones (output de
    #    Douglas-Peucker u otros simplificadores GIS puede generar esto).
    op.execute(
        """
        UPDATE parcelas
        SET geom_new = ST_MakeValid(
            ST_GeomFromGeoJSON(geom::text)
        )
        WHERE geom IS NOT NULL
          AND geom != 'null'::jsonb;
        """
    )

    # 4. Eliminar la columna vieja
    op.drop_column("parcelas", "geom")

    # 5. Renombrar la nueva columna al nombre canónico
    op.alter_column("parcelas", "geom_new", new_column_name="geom")

    # 6. Crear índice espacial GIST (esencial para queries de intersección)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_parcelas_geom "
        "ON parcelas USING GIST (geom);"
    )

    # 7. Recalcular area_ha desde la geometría real
    #    ST_Area sobre geography (::geography) devuelve m², dividimos por 10000.
    #    Solo actualiza filas donde geom quedó poblado.
    op.execute(
        """
        UPDATE parcelas
        SET area_ha = ROUND(
            (ST_Area(geom::geography) / 10000.0)::numeric,
            4
        )
        WHERE geom IS NOT NULL;
        """
    )

    # 8. Actualizar comentario de la columna
    op.execute(
        "COMMENT ON COLUMN parcelas.geom IS "
        "'Geometría PostGIS POLYGON SRID 4326. "
        "Migrada desde JSONB en 0001_postgis_geom_jsonb_to_geometry.';"
    )


def downgrade() -> None:
    # Revertir: geometry → JSONB usando ST_AsGeoJSON
    op.execute("DROP INDEX IF EXISTS idx_parcelas_geom;")

    op.add_column(
        "parcelas",
        sa.Column("geom_jsonb", JSONB, nullable=True),
    )

    op.execute(
        """
        UPDATE parcelas
        SET geom_jsonb = ST_AsGeoJSON(geom)::jsonb
        WHERE geom IS NOT NULL;
        """
    )

    op.drop_column("parcelas", "geom")
    op.alter_column("parcelas", "geom_jsonb", new_column_name="geom")

    op.execute(
        "COMMENT ON COLUMN parcelas.geom IS "
        "'GeoJSON Polygon. Revertido desde GEOMETRY en downgrade 0001.';"
    )
