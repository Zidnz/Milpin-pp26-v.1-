#!/usr/bin/env python3
"""
grabar.py — Grabador de corpus de audio para MILPÍN AgTech v2.0
===============================================================
Muestra el texto de cada caso, espera ENTER para grabar, graba desde
el micrófono y guarda el WAV en tests/audio/ con el nombre correcto
para que run_tests.py --mode audio lo encuentre automáticamente.

INSTALACIÓN (una sola vez)
--------------------------
  pip install sounddevice soundfile numpy

USO
---
  # Grabar todos los casos que aún no tienen audio
  python tests/grabar.py

  # Grabar solo una categoría
  python tests/grabar.py --categoria prescripcion

  # Grabar casos específicos
  python tests/grabar.py --id TC-019 TC-027

  # Forzar re-grabación aunque el archivo ya exista
  python tests/grabar.py --force

  # Duración fija en lugar de detectar silencio
  python tests/grabar.py --segundos 4

AUDIOS DE WHATSAPP
------------------
  Los audios de WhatsApp son compatibles directamente con Whisper.

  Android:
    Busca en: WhatsApp/Media/WhatsApp Voice Notes/
    Formato: .opus  →  copia y renombra: TC-019.opus, TC-027.opus, etc.

  iPhone:
    Comparte el audio → "Guardar en Archivos" → copia a tests/audio/
    Formato: .m4a   →  renombra: TC-019.m4a, TC-027.m4a, etc.

  Whisper soporta: .wav .mp3 .m4a .opus .ogg .webm .mp4 .flac

  IMPORTANTE: el nombre del archivo debe ser exactamente el ID del
  caso, sin sufijo adicional (no "_tts"). Ejemplos válidos:
    TC-019.opus   TC-019.m4a   TC-019.wav

  Luego corre:
    python tests/run_tests.py --mode audio

NOTA SOBRE FINE-TUNING
-----------------------
  Los audios de WhatsApp NO reentrenan Whisper. Lo que hacen es
  darte una medición de accuracy más realista que los TTS sintéticos
  de gTTS, porque reflejan:
    - Tu acento regional (sonorense)
    - Ruido de campo (tractor, viento, pájaros)
    - Velocidad de habla real
    - Nombres técnicos ("CIMMYT", "DR-041", "fosfato diamónico")

  Esa diferencia de accuracy entre TTS y audio real ES la información
  valiosa para decidir si Whisper base es suficiente o si necesitas
  fine-tuning con openai/whisper o faster-whisper.
"""

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = Path(__file__).parent
TEST_CASES_PATH = SCRIPT_DIR / "test_cases.json"
AUDIO_DIR       = SCRIPT_DIR / "audio"

# ── ANSI ──────────────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()
GREEN  = "\033[92m" if _USE_COLOR else ""
RED    = "\033[91m" if _USE_COLOR else ""
YELLOW = "\033[93m" if _USE_COLOR else ""
CYAN   = "\033[96m" if _USE_COLOR else ""
BOLD   = "\033[1m"  if _USE_COLOR else ""
DIM    = "\033[2m"  if _USE_COLOR else ""
RESET  = "\033[0m"  if _USE_COLOR else ""

# ── Parámetros de audio ───────────────────────────────────────────────────────
SAMPLE_RATE   = 16_000  # Hz — Whisper opera a 16 kHz internamente
CHANNELS      = 1       # mono
DTYPE         = "int16"
SILENCIO_DB   = -40     # dBFS para detección de silencio (fin de grabación)
SILENCIO_SEG  = 1.5     # segundos de silencio para cortar automáticamente
MAX_SEGUNDOS  = 10      # límite máximo de grabación por caso


# ─────────────────────────────────────────────────────────────────────────────
# Verificación de dependencias
# ─────────────────────────────────────────────────────────────────────────────

def verificar_dependencias() -> tuple:
    """Retorna (sounddevice, soundfile, numpy) o aborta con instrucciones."""
    try:
        import sounddevice as sd
        import soundfile as sf
        import numpy as np
        return sd, sf, np
    except ImportError as e:
        faltante = str(e).split("'")[1] if "'" in str(e) else str(e)
        print(f"\n{RED}✗ Falta: {faltante}{RESET}")
        print()
        print(f"{BOLD}Instala las dependencias de audio:{RESET}")
        print(f"  pip install sounddevice soundfile numpy")
        print()
        print(f"{DIM}Si sounddevice falla en tu SO:{RESET}")
        print(f"  Windows/Mac: la instalación con pip suele funcionar directo.")
        print(f"  Linux (Ubuntu): sudo apt install libportaudio2 && pip install sounddevice soundfile numpy")
        print()
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Carga de casos
# ─────────────────────────────────────────────────────────────────────────────

def cargar_casos(ids=None, categoria=None, solo_faltantes=True) -> list[dict]:
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    casos = data["casos"]

    if categoria:
        casos = [c for c in casos if c["categoria"] == categoria]
    if ids:
        casos = [c for c in casos if c["id"] in ids]
    if solo_faltantes:
        casos = [c for c in casos if not _tiene_audio(c["id"])]

    return casos


def _tiene_audio(caso_id: str) -> bool:
    """Verifica si ya existe un archivo de audio para el caso (cualquier extensión)."""
    for ext in [".wav", ".webm", ".mp3", ".m4a", ".opus", ".ogg", ".flac"]:
        if (AUDIO_DIR / f"{caso_id}{ext}").exists():
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Grabación
# ─────────────────────────────────────────────────────────────────────────────

def grabar_con_silencio(sd, np, max_seg: float = MAX_SEGUNDOS) -> "np.ndarray | None":
    """
    Graba hasta detectar silencio sostenido o alcanzar max_seg.

    Retorna el array de audio grabado, o None si no se capturó nada.
    """
    buffer = []
    frames_silencio = 0
    umbral_frames   = int(SILENCIO_SEG * SAMPLE_RATE / 1024)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, blocksize=1024) as stream:
        t_inicio = time.perf_counter()
        while True:
            chunk, _ = stream.read(1024)
            buffer.append(chunk.copy())

            # Nivel de audio en dBFS
            rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
            if rms > 0:
                db = 20 * np.log10(rms / 32768.0)
            else:
                db = -100.0

            if db < SILENCIO_DB:
                frames_silencio += 1
            else:
                frames_silencio = 0

            elapsed = time.perf_counter() - t_inicio

            # Indicador visual de nivel
            nivel_barras = max(0, int((db + 60) / 4))
            barra = "█" * nivel_barras + "░" * (15 - nivel_barras)
            print(
                f"\r  {CYAN}●{RESET} {barra} {DIM}{db:.0f} dBFS | {elapsed:.1f}s{RESET}",
                end="",
                flush=True,
            )

            if frames_silencio >= umbral_frames and elapsed > 0.5:
                break  # Silencio detectado
            if elapsed >= max_seg:
                break  # Límite de tiempo

    print()  # Nueva línea después del indicador
    if not buffer:
        return None
    return np.concatenate(buffer, axis=0)


def grabar_duracion_fija(sd, np, segundos: float) -> "np.ndarray":
    """Graba exactamente N segundos sin detección de silencio."""
    print(f"  {CYAN}●{RESET} Grabando {segundos}s", end="", flush=True)
    audio = sd.rec(
        int(segundos * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    for _ in range(int(segundos)):
        time.sleep(1)
        print(".", end="", flush=True)
    sd.wait()
    print()
    return audio


def guardar_wav(audio, np, output_path: Path) -> int:
    """Guarda el array de audio como WAV. Retorna duración en ms."""
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    duracion_ms = int(len(audio) / SAMPLE_RATE * 1000)
    return duracion_ms


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Grabador de corpus de audio para MILPÍN AgTech v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--categoria", "-c", help="Filtrar por categoría")
    parser.add_argument("--id", "-i", nargs="+", metavar="ID", help="IDs específicos")
    parser.add_argument("--force", "-f", action="store_true", help="Re-grabar aunque ya exista el audio")
    parser.add_argument("--segundos", "-s", type=float, default=None,
                        help="Duración fija en segundos (default: detectar silencio)")
    args = parser.parse_args()

    sd, sf, np = verificar_dependencias()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    casos = cargar_casos(
        ids=args.id,
        categoria=args.categoria,
        solo_faltantes=not args.force,
    )

    if not casos:
        print(f"\n{GREEN}✓ Todos los casos ya tienen audio grabado.{RESET}")
        print(f"  Usa --force para re-grabar, o corre:")
        print(f"  python tests/run_tests.py --mode audio\n")
        sys.exit(0)

    print(f"\n{BOLD}MILPÍN — Grabación de Corpus de Audio{RESET}")
    print(f"  Casos pendientes : {len(casos)}")
    print(f"  Directorio salida: {AUDIO_DIR}/")
    if args.segundos:
        print(f"  Modo              : duración fija {args.segundos}s")
    else:
        print(f"  Modo              : detección de silencio ({SILENCIO_SEG}s de pausa = fin)")
    print()
    print(f"  {BOLD}Controles:{RESET}")
    print(f"    ENTER → iniciar grabación del caso")
    print(f"    S + ENTER → saltar este caso")
    print(f"    Q + ENTER → salir y guardar progreso")
    print()

    grabados = 0
    saltados = 0

    for i, caso in enumerate(casos, 1):
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"  [{i}/{len(casos)}]  {CYAN}{caso['id']}{RESET}  ({caso['categoria']})")
        print()
        print(f"  {BOLD}Di exactamente:{RESET}")
        print(f"  {YELLOW}❝ {caso['texto']} ❞{RESET}")
        print()

        # Esperar input del usuario
        try:
            accion = input("  ENTER para grabar  /  S=saltar  /  Q=salir → ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {DIM}Grabación interrumpida.{RESET}")
            break

        if accion == "q":
            print(f"\n  {DIM}Saliendo. Progreso guardado.{RESET}")
            break
        if accion == "s":
            print(f"  {DIM}Saltado.{RESET}\n")
            saltados += 1
            continue

        output_path = AUDIO_DIR / f"{caso['id']}.wav"

        print(f"\n  {GREEN}Habla cuando aparezca el indicador...{RESET}")
        time.sleep(0.3)

        try:
            if args.segundos:
                audio = grabar_duracion_fija(sd, np, args.segundos)
            else:
                audio = grabar_con_silencio(sd, np)

            if audio is None or len(audio) == 0:
                print(f"  {RED}✗ No se capturó audio. Intenta de nuevo.{RESET}\n")
                continue

            duracion_ms = guardar_wav(audio, np, output_path)
            size_kb     = output_path.stat().st_size / 1024

            print(f"  {GREEN}✓{RESET} Guardado: {DIM}{output_path.name}{RESET}  "
                  f"{DIM}({duracion_ms}ms, {size_kb:.1f} KB){RESET}")
            grabados += 1

        except Exception as exc:
            print(f"  {RED}✗ Error al grabar: {exc}{RESET}")
        print()

    # ── Resumen ───────────────────────────────────────────────────────────────
    print(f"{BOLD}{'─'*60}{RESET}")
    print(f"  {GREEN}Grabados: {grabados}{RESET}   {DIM}Saltados: {saltados}{RESET}")
    print()

    # Cuántos casos tienen audio ahora
    con_audio = sum(1 for c in casos if _tiene_audio(c["id"]) or (AUDIO_DIR / f"{c['id']}.wav").exists())
    total_casos = len(json.load(open(TEST_CASES_PATH))["casos"])
    total_con_audio = sum(1 for c in json.load(open(TEST_CASES_PATH))["casos"] if _tiene_audio(c["id"]))

    print(f"  Corpus audio real: {total_con_audio}/{total_casos} casos")
    print()

    if grabados > 0:
        print(f"  {BOLD}Siguiente paso:{RESET}")
        print(f"  python tests/run_tests.py --mode audio --verbose")
        print()


if __name__ == "__main__":
    main()
