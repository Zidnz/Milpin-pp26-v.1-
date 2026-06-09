"""cultivos_catalogo_rendimiento

Añade columnas de rango de rendimiento a cultivos_catalogo:
    - rendimiento_min_ton: rendimiento mínimo esperado (ton/ha) en DR-041
    - rendimiento_max_ton: rendimiento máximo alcanzable con manejo tecnificado

Motivation: el prompt original solo tenía rendimiento_potencial_ton (techo
teórico FAO). Para predicción de yield y KPIs económicos se necesita un rango
realista: min = año malo sin estrés extremo, max = manejo tecnificado óptimo.

Fuentes:
    - Maíz/Frijol/Algodón: CIMMYT/INIFAP, datos DR-041 Valle del Yaqui
    - Uva/Chile: FAO, reporte Sonora 2022-2023

Esta migración es retrocompatible: las columnas son NULLABLE, los valores
existentes en cultivos_catalogo no se modifican (solo se añaden columnas).
El UPDATE de datos semilla se hace en init_db.py, no aquí.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cultivos_catalogo",
        sa.Column(
            "rendimiento_min_ton",
            sa.Numeric(8, 2),
            nullable=True,
            comment="Rendimiento mínimo esperado (ton/ha) en condiciones normales DR-041.",
        ),
    )
    op.add_column(
        "cultivos_catalogo",
        sa.Column(
            "rendimiento_max_ton",
            sa.Numeric(8, 2),
            nullable=True,
            comment="Rendimiento máximo alcanzable (ton/ha) con manejo tecnificado.",
        ),
    )

    # Poblar los valores semilla para los 5 cultivos existentes.
    # Se usa UPDATE por nombre_comun (estable) en vez de UUID (varía por instalación).
    # Los valores son consistentes con init_db.py::CULTIVOS_SEMILLA.
    op.execute("""
        UPDATE cultivos_catalogo SET rendimiento_min_ton = 5.0,  rendimiento_max_ton = 12.0 WHERE nombre_comun = 'Maíz';
        UPDATE cultivos_catalogo SET rendimiento_min_ton = 0.8,  rendimiento_max_ton =  2.5 WHERE nombre_comun = 'Frijol';
        UPDATE cultivos_catalogo SET rendimiento_min_ton = 1.5,  rendimiento_max_ton =  4.5 WHERE nombre_comun = 'Algodón';
        UPDATE cultivos_catalogo SET rendimiento_min_ton = 12.0, rendimiento_max_ton = 28.0 WHERE nombre_comun = 'Uva';
        UPDATE cultivos_catalogo SET rendimiento_min_ton = 15.0, rendimiento_max_ton = 40.0 WHERE nombre_comun = 'Chile';
    """)


def downgrade() -> None:
    op.drop_column("cultivos_catalogo", "rendimiento_max_ton")
    op.drop_column("cultivos_catalogo", "rendimiento_min_ton")
