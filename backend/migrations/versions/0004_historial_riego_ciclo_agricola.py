"""historial_riego_ciclo_agricola

Añade dos columnas a historial_riego para conectar cada evento de riego
con su ciclo agrícola y el volumen objetivo del proyecto:

    - ciclo_agricola        VARCHAR(20)  — etiqueta del ciclo (ej. "OI-2024", "PV-2025")
    - ciclo_vol_target_m3_ha NUMERIC(10,2) — volumen objetivo MILPÍN: 6,000 m³/ha/ciclo

Motivación:
    El CSV sintético (data/synthetic/historial_riego.csv) ya tenía estas columnas
    usadas por los notebooks de ML y Power BI, pero el schema de producción las
    omitía. Al agregarlas al schema real se cierra la brecha entre datos sintéticos
    y producción, y se habilita la vista v_kpi_consumo para comparar por ciclo.

    ciclo_vol_target_m3_ha = 6,000 m³/ha/ciclo es el KPI objetivo de MILPÍN
    (reducir desde el baseline DR-041 de 8,000 m³/ha/ciclo, ahorro ~25%).
    El backend lo autocalcula al insertar; no requiere que el usuario lo envíe.

Convención de ciclos Valle del Yaqui (DR-041):
    OI (Otoño-Invierno): oct–mar  → etiqueta = año de cierre (ej. OI-2024)
    PV (Primavera-Verano): abr–sep → etiqueta = año del período  (ej. PV-2024)

Retrocompatibilidad: usa IF NOT EXISTS via inspección antes de add_column.
Si las columnas ya existen en la BD (creadas manualmente), la migración las
omite y solo corre el backfill y el índice.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columnas_existentes() -> set[str]:
    """Devuelve el conjunto de columnas actuales de historial_riego."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col["name"] for col in inspector.get_columns("historial_riego")}


def upgrade() -> None:
    existentes = _columnas_existentes()

    if "ciclo_agricola" not in existentes:
        op.add_column(
            "historial_riego",
            sa.Column(
                "ciclo_agricola",
                sa.String(20),
                nullable=True,
                comment=(
                    "Ciclo agrícola DR-041. Formato: OI-YYYY (oct-mar) o PV-YYYY (abr-sep). "
                    "Autocalculado por el backend desde fecha_riego si no se envía."
                ),
            ),
        )

    if "ciclo_vol_target_m3_ha" not in existentes:
        op.add_column(
            "historial_riego",
            sa.Column(
                "ciclo_vol_target_m3_ha",
                sa.Numeric(10, 2),
                nullable=True,
                comment=(
                    "Volumen objetivo MILPÍN para el ciclo: 6,000 m³/ha "
                    "(KPI: reducir 25% vs. baseline DR-041 de 8,000 m³/ha/ciclo)."
                ),
            ),
        )

    # Backfill: poblar registros existentes con NULL en esas columnas.
    # La lógica de ciclo replica _ciclo_agricola() de db_api.py en SQL puro.
    op.execute(text("""
        UPDATE historial_riego
        SET
            ciclo_agricola = CASE
                WHEN EXTRACT(MONTH FROM fecha_riego) >= 10
                    THEN 'OI-' || (EXTRACT(YEAR FROM fecha_riego)::int + 1)::text
                WHEN EXTRACT(MONTH FROM fecha_riego) <= 3
                    THEN 'OI-' || EXTRACT(YEAR FROM fecha_riego)::int::text
                ELSE
                    'PV-' || EXTRACT(YEAR FROM fecha_riego)::int::text
            END,
            ciclo_vol_target_m3_ha = 6000.00
        WHERE ciclo_agricola IS NULL
           OR ciclo_vol_target_m3_ha IS NULL;
    """))

    # Crear índice solo si no existe
    bind = op.get_bind()
    inspector = inspect(bind)
    indices = {idx["name"] for idx in inspector.get_indexes("historial_riego")}
    if "idx_riego_ciclo_parcela" not in indices:
        op.create_index(
            "idx_riego_ciclo_parcela",
            "historial_riego",
            ["id_parcela", "ciclo_agricola"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    indices = {idx["name"] for idx in inspector.get_indexes("historial_riego")}
    if "idx_riego_ciclo_parcela" in indices:
        op.drop_index("idx_riego_ciclo_parcela", table_name="historial_riego")

    existentes = {col["name"] for col in inspector.get_columns("historial_riego")}
    if "ciclo_vol_target_m3_ha" in existentes:
        op.drop_column("historial_riego", "ciclo_vol_target_m3_ha")
    if "ciclo_agricola" in existentes:
        op.drop_column("historial_riego", "ciclo_agricola")
