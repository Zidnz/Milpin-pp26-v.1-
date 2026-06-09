"""
security.py — Utilidades JWT y criptografía para MILPÍN AgTech v2.0

Flujo de autenticación:
    1. POST /api/auth/login      → email + contraseña → access_token (JWT Bearer)
    2. POST /api/auth/register   → email + contraseña + nombre → crea usuario + token
    3. Endpoints protegidos      → Authorization: Bearer <token>
    4. get_current_user()        → valida token → retorna ORM Usuario
    5. get_current_admin()       → igual, pero exige rol="admin"
    6. get_optional_user()       → valida si hay token, None si no hay (GET endpoints)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Usuario
from settings import auth_settings

# ── Crypto ────────────────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=True)
_optional_bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Token schema ──────────────────────────────────────────────────────────────
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    id_usuario: uuid.UUID
    nombre_completo: str
    email: str
    rol: str


# ── JWT creation / validation ─────────────────────────────────────────────────
def create_access_token(id_usuario: uuid.UUID, rol: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.jwt_expire_minutes)
    payload = {"sub": str(id_usuario), "rol": rol, "exp": exp}
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=auth_settings.jwt_algorithm)


def _decode_token(token: str) -> Optional[str]:
    """Decodifica el JWT y retorna el UUID del usuario (sub) o None si inválido."""
    try:
        payload = jwt.decode(
            token,
            auth_settings.jwt_secret_key,
            algorithms=[auth_settings.jwt_algorithm],
        )
        return payload.get("sub")
    except JWTError:
        return None


# ── FastAPI dependencies ──────────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Extrae y valida el JWT del header Authorization. Lanza 401 si inválido."""
    uid = _decode_token(credentials.credentials)
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    res = await db.execute(select(Usuario).where(Usuario.id_usuario == uuid.UUID(uid)))
    usuario = res.scalar_one_or_none()
    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


async def get_current_admin(
    current_user: Usuario = Depends(get_current_user),
) -> Usuario:
    """Como get_current_user pero exige rol='admin'. Lanza 403 si no es admin."""
    if current_user.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol administrador.",
        )
    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[Usuario]:
    """Como get_current_user pero no lanza error si no hay token (para GET endpoints)."""
    if credentials is None:
        return None
    uid = _decode_token(credentials.credentials)
    if uid is None:
        return None
    try:
        res = await db.execute(select(Usuario).where(Usuario.id_usuario == uuid.UUID(uid)))
        usuario = res.scalar_one_or_none()
        return usuario if (usuario and usuario.activo) else None
    except (ValueError, Exception):
        return None
