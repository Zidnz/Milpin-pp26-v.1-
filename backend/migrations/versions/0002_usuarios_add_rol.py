"""usuarios_add_rol

Añade la columna `rol` a la tabla `usuarios`.

Valores posibles:
    - 'agricultor'  → solo ve sus propias parcelas (comportamiento anterior)
    - 'admin'       → ve todas las parcelas del sistema

El valor por defecto es 'agricultor', por lo que todos los usuarios
existentes quedan sin cambios de comportamiento.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-07
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column(
            "rol",
            sa.String(20),
            nullable=False,
            server_default="agricultor",
            comment="Rol del usuario: 'agricultor' (solo sus parcelas) o 'admin' (todas)",
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "rol")
