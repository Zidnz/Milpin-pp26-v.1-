import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm_orchestrator import interpretar_comando_voz, interpretar_texto
from database import get_db
from models import Recomendacion, CultivoCatalogo

router = APIRouter()

# ── Seguridad: validación de uploads de audio ─────────────────────────────────

# Content-types aceptados. "application/octet-stream" lo mandan algunos
# navegadores móviles para blobs de audio grabados con MediaRecorder.
_AUDIO_CONTENT_TYPES: set[str] = {
    "audio/wav", "audio/wave", "audio/x-wav",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/webm",
    "audio/mp4", "audio/x-m4a", "audio/m4a",
    "audio/flac", "audio/opus",
    "application/octet-stream",
}

# Extensiones válidas para el archivo temporal (Whisper las usa para decodificar).
_AUDIO_EXTENSIONS: set[str] = {
    ".wav", ".mp3", ".ogg", ".webm", ".m4a", ".flac", ".opus",
}

# 25 MB — suficiente para ~15 min en MP3 128 kbps, razonable para un comando de voz.
_MAX_AUDIO_BYTES: int = 25 * 1024 * 1024


# ── Endpoint original: audio → Whisper STT → LLM ─────────────────────────────
# Sigue activo como fallback para navegadores sin Web Speech API support.
@router.post("/voice-command")
async def receive_voice(audio_file: UploadFile = File(...)):
    # 1. Validar content-type
    ct = (audio_file.content_type or "").lower().split(";")[0].strip()
    if ct not in _AUDIO_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Tipo de archivo no soportado: '{ct}'. "
                "Solo se aceptan archivos de audio (wav, mp3, ogg, webm, m4a, flac)."
            ),
        )

    # 2. Extraer extensión del nombre original y validarla contra el allowlist.
    #    El nombre original se usa SOLO para obtener la extensión — nunca para
    #    construir rutas de sistema de archivos (previene path traversal).
    original_name = audio_file.filename or ""
    ext = Path(original_name).suffix.lower()
    if ext not in _AUDIO_EXTENSIONS:
        ext = ".wav"  # fallback seguro; Whisper lo maneja bien

    # 3. Ruta temporal completamente controlada: directorio del SO + UUID.
    #    El nombre del archivo del cliente no toca el filesystem en ningún momento.
    temp_path = os.path.join(
        tempfile.gettempdir(),
        f"milpin_audio_{uuid.uuid4().hex}{ext}",
    )

    try:
        # 4. Leer con límite de tamaño (previene agotamiento de disco)
        contenido = await audio_file.read(_MAX_AUDIO_BYTES + 1)
        if len(contenido) > _MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Archivo demasiado grande. "
                    f"Máximo permitido: {_MAX_AUDIO_BYTES // (1024 * 1024)} MB."
                ),
            )

        with open(temp_path, "wb") as f:
            f.write(contenido)

        resultado = interpretar_comando_voz(temp_path)

    finally:
        # 5. Limpiar siempre, incluso si Whisper lanza una excepción
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return resultado


# ── Endpoint nuevo: texto → LLM (Web Speech API ya transcribió en el browser) ─
# El browser hace STT localmente vía Web Speech API y manda el texto aquí.
# Elimina el round-trip de audio + carga de Whisper → latencia ~0.5-1s con Groq.
# Si viene parcela_id y el intent es "consultar", el backend enriquece la respuesta
# con datos reales de la tabla recomendaciones en lugar de devolver un mensaje genérico.
class TextCommand(BaseModel):
    texto: str
    parcela_id: Optional[str] = None  # UUID string de la parcela activa en el frontend


@router.post("/text-command")
async def receive_text(body: TextCommand, db: AsyncSession = Depends(get_db)):
    resultado = interpretar_texto(body.texto)

    # Enriquecer respuesta de consulta con datos reales de BD
    if resultado.get("intent") == "consultar" and body.parcela_id:
        try:
            parsed_id = uuid.UUID(body.parcela_id)
            mensaje_real = await _consultar_datos_reales(db, parsed_id)
            resultado["message"] = mensaje_real
        except (ValueError, AttributeError):
            # parcela_id malformado — dejar el mensaje genérico del LLM
            pass
        except Exception as e:
            print(f"[MILPÍN consultar] Error BD: {e}")
            # No romper el endpoint: el LLM ya generó un mensaje de fallback

    return resultado


async def _consultar_datos_reales(db: AsyncSession, parcela_id: uuid.UUID) -> str:
    """
    Busca la recomendación más reciente de la parcela y formatea una respuesta
    hablada con los datos reales: lámina, déficit, ETo, ETc y días sin riego.
    """
    stmt = (
        select(Recomendacion, CultivoCatalogo.nombre_comun)
        .join(
            CultivoCatalogo,
            Recomendacion.id_cultivo == CultivoCatalogo.id_cultivo,
            isouter=True,
        )
        .where(Recomendacion.id_parcela == parcela_id)
        .order_by(desc(Recomendacion.fecha_generacion))
        .limit(1)
    )
    row = (await db.execute(stmt)).first()

    if not row:
        return (
            "No encontré recomendaciones para esta parcela. "
            "Calcula una nueva ingresando los días desde la siembra."
        )

    rec, cultivo_nombre = row
    return _formatear_consulta_hablada(rec, cultivo_nombre)


def _formatear_consulta_hablada(rec: Recomendacion, cultivo_nombre: Optional[str]) -> str:
    """
    Convierte los campos de una Recomendacion en una oración hablada en español.
    Máximo ~40 palabras para que el TTS no suene demasiado largo.
    """
    partes: list[str] = []

    if cultivo_nombre:
        partes.append(f"Para tu {cultivo_nombre}")

    if rec.lamina_recomendada_mm is not None:
        partes.append(f"la lámina recomendada es {rec.lamina_recomendada_mm:.0f} milímetros")

    if rec.deficit_acumulado_mm is not None:
        partes.append(f"déficit acumulado de {rec.deficit_acumulado_mm:.0f} milímetros")

    if rec.dias_sin_riego is not None:
        if rec.dias_sin_riego == 999:
            partes.append("sin registros de riego previos")
        else:
            partes.append(f"{rec.dias_sin_riego} días sin regar")

    if rec.nivel_urgencia:
        nivel_label = {"critico": "urgente", "moderado": "moderado", "preventivo": "preventivo"}
        partes.append(f"nivel {nivel_label.get(rec.nivel_urgencia, rec.nivel_urgencia)}")

    if not partes:
        return "No hay datos suficientes en la recomendación activa para responder esa consulta."

    # Unir con coma y punto final
    return ", ".join(partes) + "."
