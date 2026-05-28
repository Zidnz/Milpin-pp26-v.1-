"""usuarios_add_password

Añade la columna `hashed_password` a la tabla `usuarios`.

Los usuarios existentes quedan con NULL (sin contraseña).
Para establecer contraseña: POST /api/auth/register o actualizar
directamente en BD con el hash bcrypt generado por passlib.

Los usuarios semilla de desarrollo (rvalenzuela@dr041-dev.com,
admin@milpin-dr041.com) reciben contraseña vía init_db.py.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column(
            "hashed_password",
            sa.String(200),
            nullable=True,
            comment="bcrypt hash. NULL = usuario sin contraseña (debe usar /auth/register).",
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "hashed_password")
