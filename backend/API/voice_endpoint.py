from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
import shutil
import os
from core.llm_orchestrator import interpretar_comando_voz, interpretar_texto

router = APIRouter()


# ── Endpoint original: audio → Whisper STT → LLM ─────────────────────────────
# Sigue activo como fallback para navegadores sin Web Speech API support.
@router.post("/voice-command")
async def receive_voice(audio_file: UploadFile = File(...)):
    temp_path = f"temp_{audio_file.filename}"

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)

    resultado = interpretar_comando_voz(temp_path)

    if os.path.exists(temp_path):
        os.remove(temp_path)

    return resultado


# ── Endpoint nuevo: texto → LLM (Web Speech API ya transcribió en el browser) ─
# El browser hace STT localmente vía Web Speech API y manda el texto aquí.
# Elimina el round-trip de audio + carga de Whisper → latencia ~0.5-1s con Groq.
class TextCommand(BaseModel):
    texto: str

@router.post("/text-command")
async def receive_text(body: TextCommand):
    return interpretar_texto(body.texto)