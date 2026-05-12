# ==========================================
# llm_orchestrator.py: Motor de IA conversacional
# MILPÍN AgTech v2.0
# ==========================================

import json
import os
import requests
from collections import deque

# Cliente Groq (reemplaza Ollama para inferencia en la nube)
try:
    from groq import Groq
    _groq_api_key = os.getenv("GROQ_API_KEY")
    _groq_client = Groq(api_key=_groq_api_key) if _groq_api_key else None
    _USE_GROQ = bool(_groq_api_key)
except (ImportError, Exception):
    _groq_client = None
    _USE_GROQ = False

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

# ── Configuration ────────────────────────────────────────────────────────────
OLLAMA_URL   = os.getenv("MILPIN_OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("MILPIN_OLLAMA_MODEL", "llama3.2:latest")
HISTORY_TURNS = 3   # conversation turns kept in memory (user+assistant = 2 msgs each)

VALID_INTENTS = frozenset({
    "navegar", "ejecutar_analisis",
    "confirmar_riego", "ignorar_riego", "calcular_riego",
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
  ejecutar_analisis → el usuario pide correr el análisis de clustering en el mapa
  confirmar_riego   → el usuario confirma que regó hoy su parcela
  ignorar_riego     → el usuario indica que no regó o va a omitir el riego recomendado
  calcular_riego    → el usuario pide calcular una nueva recomendación FAO-56
  consultar         → el usuario hace una pregunta sobre datos de su parcela (lámina, déficit, ETo, días sin riego)
  saludo            → saludo o presentación
  desconocido       → no puedes clasificar el comando

CAMPO target — usa EXACTAMENTE uno de:
  tab-bi | tab-mapas | tab-costos | tab-ajustes | null

CAMPO message — respuesta hablada en español, máximo 35 palabras.

CAMPO parameters — SOLO para confirmar_riego, ignorar_riego y calcular_riego:

  confirmar_riego / ignorar_riego → {"nombre_parcela": "..."}
    nombre_parcela → nombre de la parcela mencionada por el usuario, o null si no dijo ninguna

  calcular_riego → {"dias_siembra": 0, "nombre_parcela": "..."}
    dias_siembra   → número entero de días desde la siembra (obligatorio)
    nombre_parcela → nombre de la parcela mencionada, o null si no la mencionó

Para cualquier otra intención, parameters SIEMPRE es null.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EJEMPLOS (uno por línea, copia el formato exacto):

Usuario: "Hola Milpín"
{"intent":"saludo","target":null,"message":"Hola agricultor. Soy MILPÍN. ¿Qué datos del Valle del Yaqui revisamos hoy?","parameters":null}

Usuario: "Muéstrame los mapas satelitales"
{"intent":"navegar","target":"tab-mapas","message":"Abriendo monitor satelital.","parameters":null}

Usuario: "Lleva a riego"
{"intent":"navegar","target":"tab-costos","message":"Abriendo módulo de riego FAO-56.","parameters":null}

Usuario: "Ve al dashboard de BI"
{"intent":"navegar","target":"tab-bi","message":"Abriendo el dashboard de análisis.","parameters":null}

Usuario: "Abre ajustes"
{"intent":"navegar","target":"tab-ajustes","message":"Abriendo configuración.","parameters":null}

Usuario: "Ejecuta el clustering logístico"
{"intent":"ejecutar_analisis","target":"tab-mapas","message":"Iniciando análisis de clustering en el mapa.","parameters":null}

Usuario: "Regué hoy"
{"intent":"confirmar_riego","target":"tab-costos","message":"Confirmado. Registrando el riego de hoy.","parameters":{"nombre_parcela":null}}

Usuario: "Regué hoy la Parcela Norte"
{"intent":"confirmar_riego","target":"tab-costos","message":"Confirmado. Registrando el riego de la Parcela Norte.","parameters":{"nombre_parcela":"Parcela Norte"}}

Usuario: "Ya apliqué el riego en la parcela 3"
{"intent":"confirmar_riego","target":"tab-costos","message":"Perfecto. Guardando el evento de riego en parcela 3.","parameters":{"nombre_parcela":"parcela 3"}}

Usuario: "No voy a regar"
{"intent":"ignorar_riego","target":"tab-costos","message":"Entendido. Registrando que no se aplicó riego hoy.","parameters":{"nombre_parcela":null}}

Usuario: "Voy a omitir el riego de la Parcela Sur"
{"intent":"ignorar_riego","target":"tab-costos","message":"Registrando que se omitió el riego en Parcela Sur.","parameters":{"nombre_parcela":"Parcela Sur"}}

Usuario: "Calcula la recomendación para 45 días desde siembra"
{"intent":"calcular_riego","target":"tab-costos","message":"Calculando recomendación FAO-56 para 45 días desde siembra.","parameters":{"dias_siembra":45,"nombre_parcela":null}}

Usuario: "Calcula el riego de la Parcela Este con 60 días de siembra"
{"intent":"calcular_riego","target":"tab-costos","message":"Calculando FAO-56 para Parcela Este, 60 días desde siembra.","parameters":{"dias_siembra":60,"nombre_parcela":"Parcela Este"}}

Usuario: "Tengo 30 días de siembra en la parcela chica, ¿cuánto riego?"
{"intent":"calcular_riego","target":"tab-costos","message":"Calculando balance hídrico para parcela chica, 30 días de cultivo.","parameters":{"dias_siembra":30,"nombre_parcela":"parcela chica"}}

Usuario: "¿Cuánta agua necesita mi parcela?"
{"intent":"consultar","target":null,"message":"Consultando datos de riego de tu parcela.","parameters":null}

Usuario: "¿Cuál es mi déficit hídrico?"
{"intent":"consultar","target":null,"message":"Revisando el balance hídrico de tu parcela.","parameters":null}

Usuario: "¿Cuántos días llevo sin regar?"
{"intent":"consultar","target":null,"message":"Revisando el historial de riego de tu parcela.","parameters":null}
"""

# ── STT: Whisper (lazy load) ──────────────────────────────────────────────────
# No se carga al importar el módulo. Se inicializa en el primer request de voz.
# Ahorra ~30-60s de startup y ~150MB de RAM si nadie usa el micrófono.
_whisper_model = None
_whisper_loaded = False


def _get_whisper():
    """Carga Whisper la primera vez que se necesita y reutiliza la instancia.

    El import de whisper (que arrastra torch y numpy) se hace aquí dentro,
    no al importar el módulo. Ahorra ~30-60 s de startup y ~150 MB de RAM
    cuando nadie usa el micrófono en la sesión.
    """
    global _whisper_model, _whisper_loaded
    if _whisper_loaded:
        return _whisper_model
    print("[MILPÍN] Cargando motor Whisper (primer uso)…")
    try:
        import whisper  # import diferido: torch se carga solo si se usa voz
        _whisper_model = whisper.load_model("base")
        print("[MILPÍN] Whisper listo.")
    except Exception as e:
        print(f"[MILPÍN] Whisper no disponible: {e}")
        _whisper_model = None
    _whisper_loaded = True
    return _whisper_model


# ── Session memory (ring buffer, single-user) ─────────────────────────────────
# Stores alternating {"role":"user"/"assistant", "content":"..."} dicts.
_history: deque = deque(maxlen=HISTORY_TURNS * 2)


# ── Private helpers ───────────────────────────────────────────────────────────

def _transcribir(audio_path: str) -> str | None:
    model = _get_whisper()
    if not model:
        return None
    try:
        result = model.transcribe(audio_path, language="es", fp16=False)
        return result["text"].strip()
    except Exception as e:
        print(f"[Whisper] Error: {e}")
        return None


def _llamar_llm(user_text: str) -> dict:
    """Llama al LLM disponible: Groq (nube, rápido) u Ollama (local, fallback)."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(list(_history))
    messages.append({"role": "user", "content": user_text})

    if _USE_GROQ and _groq_client:
        return _llamar_groq(messages)
    return _llamar_ollama(messages)


def _llamar_groq(messages: list) -> dict:
    """Inferencia en Groq Cloud — ~1s de latencia."""
    try:
        resp = _groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=200,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        print(f"[Groq] Respuesta raw: {raw[:100]}")
        return _parsear_y_validar(raw)
    except Exception as e:
        print(f"[Groq] Error: {e}. Cayendo a Ollama.")
        return _llamar_ollama(messages)


def _llamar_ollama(messages: list) -> dict:
    """Inferencia local con Ollama — fallback si Groq no está configurado."""
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
    if intent in ("confirmar_riego", "ignorar_riego"):
        raw_p = data.get("parameters") or {}
        parameters = {
            "nombre_parcela": _safe_str(raw_p.get("nombre_parcela")),
        }
    elif intent == "calcular_riego":
        raw_p = data.get("parameters") or {}
        parameters = {
            "dias_siembra":   _safe_int(raw_p.get("dias_siembra")),
            "nombre_parcela": _safe_str(raw_p.get("nombre_parcela")),
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

    resultado = _llamar_llm(transcripcion)

    # Persist this turn in session memory
    _history.append({"role": "user",      "content": transcripcion})
    _history.append({"role": "assistant", "content": json.dumps(resultado, ensure_ascii=False)})

    resultado["transcripcion"] = transcripcion
    return resultado


def interpretar_texto(texto: str) -> dict:
    """
    Clasifica la intención de un texto plano usando el LLM activo (sin STT).
    Útil para pruebas unitarias que no requieren audio.
    No actualiza _history para mantener aislamiento entre casos de prueba.
    """
    resultado = _llamar_llm(texto)
    resultado["transcripcion"] = texto
    return resultado


def limpiar_historial() -> None:
    """
    Vacía el buffer de historial de conversación.
    Llamar antes de cada suite de pruebas para garantizar aislamiento entre casos.
    """
