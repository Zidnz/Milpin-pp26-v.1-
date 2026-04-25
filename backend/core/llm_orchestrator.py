# ==========================================
# llm_orchestrator.py: Motor de IA conversacional
# MILPÍN AgTech v2.0
# ==========================================

import json
import os
import requests
from collections import deque

# imageio_ffmpeg trae su propio binario pero con nombre largo (ej. ffmpeg-win64-v6.exe).
# Whisper lo llama por nombre exacto "ffmpeg", así que copiamos el binario
# a un directorio temporal con el nombre correcto y lo añadimos al PATH.
import shutil, tempfile, atexit

try:
    import imageio_ffmpeg
    _src_exe = imageio_ffmpeg.get_ffmpeg_exe()
    _tmp_dir = tempfile.mkdtemp(prefix="milpin_ffmpeg_")
    _dst_exe = os.path.join(_tmp_dir, "ffmpeg.exe")
    shutil.copy2(_src_exe, _dst_exe)
    os.environ["PATH"] = _tmp_dir + os.pathsep + os.environ.get("PATH", "")
    atexit.register(shutil.rmtree, _tmp_dir, ignore_errors=True)
    print(f"[MILPÍN] ffmpeg listo en: {_tmp_dir}")
except ImportError:
    print("[MILPÍN] imageio-ffmpeg no instalado. Whisper buscará ffmpeg en el PATH del sistema.")

import whisper

# ── Configuration ────────────────────────────────────────────────────────────
OLLAMA_URL   = os.getenv("MILPIN_OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("MILPIN_OLLAMA_MODEL", "llama3.2:latest")
HISTORY_TURNS = 3   # conversation turns kept in memory (user+assistant = 2 msgs each)

VALID_INTENTS = frozenset({
    "navegar", "ejecutar_analisis", "llenar_prescripcion",
    "consultar", "saludo", "desconocido", "error",
})
VALID_TARGETS  = frozenset({"tab-bi", "tab-mapas", "tab-costos", "tab-ajustes"})
VALID_CULTIVOS = frozenset({"uva", "maiz", "algodon", "frijol", "chile"})

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """Eres MILPÍN, asistente de IA del ERP agrícola del Valle del Yaqui (Sonora, México).

REGLA ABSOLUTA: Tu ÚNICA salida permitida es un objeto JSON válido en UNA sola línea.
Sin markdown, sin texto adicional, sin bloques de código. Solo JSON plano.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ESQUEMA BASE (siempre presente):
{"intent":"...","target":"...","message":"...","parameters":null}

CAMPO intent — elige UNO de estos valores exactos:
  navegar           → el usuario quiere ir a una sección de la app
  ejecutar_analisis → el usuario pide correr un análisis o clustering
  llenar_prescripcion → el usuario dicta datos para el formulario de fertilización
  consultar         → el usuario hace una pregunta sobre datos o estadísticas
  saludo            → saludo o presentación
  desconocido       → no puedes clasificar el comando

CAMPO target — usa EXACTAMENTE uno de:
  tab-bi | tab-mapas | tab-costos | tab-ajustes | null

CAMPO message — respuesta hablada en español, máximo 35 palabras.

CAMPO parameters — SOLO para llenar_prescripcion, usar este sub-objeto:
{"cultivo":"...","variedad":"...","insumo":"...","tasa":0,"zona":0}

  cultivo  → uno de: uva | maiz | algodon | frijol | chile | null
  variedad → string o null
  insumo   → string o null
  tasa     → número entero (kg/ha) o null
  zona     → número entero o null

Para cualquier otra intención, parameters SIEMPRE es null.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAPEO DE CULTIVOS (normaliza siempre al valor del enum):
  uva / vid / uva de mesa            → "uva"
  maíz / maiz / elote / corn         → "maiz"
  algodón / algodon / cotton         → "algodon"
  frijol / frijoles / beans          → "frijol"
  chile / chili / pimiento / pepper  → "chile"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EJEMPLOS (uno por línea, copia el formato exacto):

Usuario: "Hola Milpín"
{"intent":"saludo","target":null,"message":"Hola agricultor. Soy MILPÍN. ¿Qué datos del Valle del Yaqui revisaremos hoy?","parameters":null}

Usuario: "Muéstrame los mapas satelitales"
{"intent":"navegar","target":"tab-mapas","message":"Abriendo monitor satelital NDVI.","parameters":null}

Usuario: "Lleva a costos"
{"intent":"navegar","target":"tab-costos","message":"Abriendo módulo de prescripción de fertilización.","parameters":null}

Usuario: "Ejecuta el clustering logístico"
{"intent":"ejecutar_analisis","target":"tab-mapas","message":"Iniciando análisis de clustering. Calculando ubicaciones óptimas para logística.","parameters":null}

Usuario: "Llena la prescripción para algodón con 300 kilos de urea en la zona 5"
{"intent":"llenar_prescripcion","target":"tab-costos","message":"Prescripción lista: algodón, urea a 300 kg por hectárea, zona 5.","parameters":{"cultivo":"algodon","variedad":null,"insumo":"urea","tasa":300,"zona":5}}

Usuario: "Pon maíz variedad Pioneer H-514 con sulfato de amonio a 180 kilos zona 3"
{"intent":"llenar_prescripcion","target":"tab-costos","message":"Llenando formulario: maíz Pioneer H-514, sulfato de amonio, 180 kilogramos, zona 3.","parameters":{"cultivo":"maiz","variedad":"Pioneer H-514","insumo":"sulfato de amonio","tasa":180,"zona":3}}

Usuario: "Prescripción de uva para la variedad Flame sin Nitrogen, zona 7, doscientos kilos"
{"intent":"llenar_prescripcion","target":"tab-costos","message":"Formulario actualizado: uva Flame, Nitrogen, 200 kilogramos por hectárea, zona 7.","parameters":{"cultivo":"uva","variedad":"Flame","insumo":"Nitrogen","tasa":200,"zona":7}}
"""

# ── STT: Whisper ──────────────────────────────────────────────────────────────
print("[MILPÍN] Cargando motor Whisper…")
try:
    _whisper_model = whisper.load_model("base")
    print("[MILPÍN] Whisper listo.")
except Exception as _e:
    print(f"[MILPÍN] Whisper no disponible: {_e}")
    _whisper_model = None

# ── Session memory (ring buffer, single-user) ─────────────────────────────────
# Stores alternating {"role":"user"/"assistant", "content":"..."} dicts.
_history: deque = deque(maxlen=HISTORY_TURNS * 2)


# ── Private helpers ───────────────────────────────────────────────────────────

def _transcribir(audio_path: str) -> str | None:
    if not _whisper_model:
        return None
    try:
        result = _whisper_model.transcribe(audio_path, language="es", fp16=False)
        return result["text"].strip()
    except Exception as e:
        print(f"[Whisper] Error: {e}")
        return None


def _llamar_ollama(user_text: str) -> dict:
    """Build the full message list (system + history + current) and call Ollama."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(list(_history))
    messages.append({"role": "user", "content": user_text})

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False, "options": {"num_ctx": 1024}}

        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        return _parsear_y_validar(raw)

    except requests.exceptions.ConnectionError:
        return _error("Ollama no está disponible. Inicia el servidor con 'ollama serve'.")
    except requests.exceptions.Timeout:
        return _error("El modelo tardó demasiado. Intenta de nuevo.")
    except Exception as e:
        print(f"[Ollama] Error inesperado: {e}")
        return _error("Error interno del motor de IA.")


def _parsear_y_validar(raw: str) -> dict:
    """Strip any accidental markdown fences, parse JSON, then validate schema."""
    # Some models wrap output in ```json ... ```
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) >= 2 else raw

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[Parser] JSON inválido recibido:\n{raw[:300]}")
        return _error("El modelo devolvió una respuesta no válida.")

    return _validar_esquema(data)


def _validar_esquema(data: dict) -> dict:
    """Enforce strict types and whitelist values — no LLM hallucination gets through."""
    intent = data.get("intent", "desconocido")
    if intent not in VALID_INTENTS:
        intent = "desconocido"

    target = data.get("target")
    if target not in VALID_TARGETS:
        target = None

    message = str(data.get("message") or "")[:200]

    parameters = None
    if intent == "llenar_prescripcion":
        raw_p = data.get("parameters") or {}
        cultivo = raw_p.get("cultivo")
        parameters = {
            "cultivo":  cultivo if cultivo in VALID_CULTIVOS else None,
            "variedad": _safe_str(raw_p.get("variedad")),
            "insumo":   _safe_str(raw_p.get("insumo")),
            "tasa":     _safe_int(raw_p.get("tasa")),
            "zona":     _safe_int(raw_p.get("zona")),
        }

    return {"intent": intent, "target": target, "message": message, "parameters": parameters}


def _safe_str(val) -> str | None:
    s = str(val).strip() if val is not None else ""
    return s if s else None

def _safe_int(val) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _error(msg: str) -> dict:
    return {"intent": "error", "target": None, "message": msg, "parameters": None}


# ── Public API ────────────────────────────────────────────────────────────────

def interpretar_comando_voz(audio_path: str) -> dict:
    """
    Main pipeline: WAV/WebM → Whisper STT → Ollama LLM → validated JSON dict.
    Injects the last HISTORY_TURNS exchanges as conversational context.
    """
    transcripcion = _transcribir(audio_path)
    if not transcripcion:
        resultado = _error("No pude transcribir el audio. Habla más claro cerca del micrófono.")
        resultado["transcripcion"] = ""
        return resultado

    print(f"[Whisper] '{transcripcion}'")

    resultado = _llamar_ollama(transcripcion)

    # Persist this turn in session memory
    _history.append({"role": "user",      "content": transcripcion})
    _history.append({"role": "assistant", "content": json.dumps(resultado, ensure_ascii=False)})

    resultado["transcripcion"] = transcripcion
    return resultado


def interpretar_texto(texto: str) -> dict:
    """
    Clasifica la intención de un texto plano usando Ollama (sin STT).
    Útil para pruebas unitarias del LLM que no requieren audio.

    A diferencia de interpretar_comando_voz, NO actualiza _history para
    mantener los casos de prueba completamente aislados entre sí.

    Retorna el mismo esquema JSON que interpretar_comando_voz, con
    'transcripcion' igual al texto de entrada.
    """
    resultado = _llamar_ollama(texto)
    resultado["transcripcion"] = texto
    return resultado


def limpiar_historial() -> None:
    """
    Vacía el buffer de historial de conversación.
    Llamar antes de cada suite de pruebas para garantizar aislamiento entre casos.
    """
    _history.clear()
