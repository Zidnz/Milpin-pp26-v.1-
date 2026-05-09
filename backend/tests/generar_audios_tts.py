#!/usr/bin/env python3
"""
generar_audios_tts.py — Generador de corpus de audio para MILPÍN AgTech v2.0
=============================================================================
Pre-genera los 50 archivos MP3 del corpus de evaluación usando gTTS
(Google Text-to-Speech). Los archivos se guardan en tests/audio/ con el
nombre {ID}_tts.mp3.

Al tener los archivos en caché puedes correr `run_tests.py --mode tts`
sin necesidad de conexión a internet durante los tests.

REQUISITOS
----------
  pip install gtts

USO
---
  # Generar todos los audios
  python generar_audios_tts.py

  # Regenerar forzando sobreescritura
  python generar_audios_tts.py --force

  # Solo una categoría
  python generar_audios_tts.py --categoria prescripcion

  # Casos específicos
  python generar_audios_tts.py --id TC-019 TC-027

  # Velocidad lenta (mejor para Whisper con ruido real)
  python generar_audios_tts.py --slow

VARIANTES DE ACENTO
-------------------
  El parámetro tld controla el acento de Google TTS:
    com.mx → español México  (default — más cercano al español sonorense)
    es     → español España
    com.ar → español Argentina
  Para generar variantes y probar robustez de acento:
    python generar_audios_tts.py --tld es --sufijo _es

INTEGRACIÓN CON run_tests.py
----------------------------
  Después de generar, corre el pipeline completo:
    python run_tests.py --mode tts
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ── Rutas ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = Path(__file__).parent
TEST_CASES_PATH = SCRIPT_DIR / "test_cases.json"
AUDIO_DIR       = SCRIPT_DIR / "audio"

# ── ANSI colors ───────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()
GREEN  = "\033[92m" if _USE_COLOR else ""
RED    = "\033[91m" if _USE_COLOR else ""
YELLOW = "\033[93m" if _USE_COLOR else ""
CYAN   = "\033[96m" if _USE_COLOR else ""
BOLD   = "\033[1m"  if _USE_COLOR else ""
DIM    = "\033[2m"  if _USE_COLOR else ""
RESET  = "\033[0m"  if _USE_COLOR else ""

PASS_MARK = f"{GREEN}✓{RESET}"
FAIL_MARK = f"{RED}✗{RESET}"
WARN_MARK = f"{YELLOW}⚠{RESET}"


def cargar_casos(ids: list[str] = None, categoria: str = None) -> list[dict]:
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    casos = data["casos"]
    if categoria:
        casos = [c for c in casos if c["categoria"] == categoria]
    if ids:
        casos = [c for c in casos if c["id"] in ids]
    return casos


def generar_audio(
    caso: dict,
    audio_dir: Path,
    lang: str = "es",
    tld: str = "com.mx",
    slow: bool = False,
    sufijo: str = "_tts",
    force: bool = False,
) -> tuple[bool, str]:
    """
    Genera un archivo MP3 para el caso dado.

    Retorna (éxito: bool, ruta_archivo: str).
    """
    try:
        from gtts import gTTS
    except ImportError:
        print(f"\n{FAIL_MARK} gTTS no instalado. Instala con: pip install gtts")
        sys.exit(1)

    filename   = f"{caso['id']}{sufijo}.mp3"
    audio_path = audio_dir / filename

    if audio_path.exists() and not force:
        return True, str(audio_path)  # Usando caché

    try:
        tts = gTTS(text=caso["texto"], lang=lang, tld=tld, slow=slow)
        tts.save(str(audio_path))
        return True, str(audio_path)
    except Exception as exc:
        return False, str(exc)


def main():
    parser = argparse.ArgumentParser(
        description="Generador de corpus de audio TTS para MILPÍN AgTech v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Regenerar archivos aunque ya existan en caché",
    )
    parser.add_argument(
        "--categoria", "-c",
        choices=["navegacion", "ejecutar_analisis", "prescripcion", "consultar", "saludo", "desconocido"],
        help="Filtrar por categoría",
    )
    parser.add_argument(
        "--id", "-i",
        nargs="+",
        metavar="ID",
        help="IDs específicos (ej. TC-019 TC-027)",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Generar TTS a velocidad lenta (puede ayudar con Whisper en condiciones de ruido)",
    )
    parser.add_argument(
        "--tld",
        default="com.mx",
        choices=["com.mx", "es", "com.ar", "com"],
        help="Variante de acento Google TTS (default: com.mx → español México)",
    )
    parser.add_argument(
        "--sufijo",
        default="_tts",
        help="Sufijo del nombre de archivo (default: _tts → TC-001_tts.mp3)",
    )
    args = parser.parse_args()

    # ── Validar gTTS ──────────────────────────────────────────────────────────
    try:
        import gtts  # noqa: F401
    except ImportError:
        print(f"{FAIL_MARK} gTTS no instalado. Ejecuta:\n   pip install gtts")
        sys.exit(1)

    # ── Preparar directorio de salida ─────────────────────────────────────────
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # ── Cargar casos ──────────────────────────────────────────────────────────
    casos = cargar_casos(ids=args.id, categoria=args.categoria)
    if not casos:
        print(f"{WARN_MARK} Sin casos con los filtros especificados.")
        sys.exit(1)

    print(f"\n{BOLD}MILPÍN — Generación de Corpus de Audio TTS{RESET}")
    print(f"  Casos : {len(casos)}  │  Acento : {CYAN}{args.tld}{RESET}  │  Salida : {AUDIO_DIR}/")
    print(f"  Velocidad lenta: {'sí' if args.slow else 'no'}  │  Forzar: {'sí' if args.force else 'no (usando caché)'}")
    print()

    exitosos = 0
    fallidos  = 0
    cacheados = 0
    t_inicio  = time.perf_counter()

    for i, caso in enumerate(casos, 1):
        audio_path = AUDIO_DIR / f"{caso['id']}{args.sufijo}.mp3"
        ya_existe  = audio_path.exists()

        print(f"  [{i:02d}/{len(casos):02d}] {caso['id']:8}  {DIM}{caso['texto'][:55]}{RESET}", end="", flush=True)

        if ya_existe and not args.force:
            print(f"  {DIM}(caché){RESET}")
            cacheados += 1
            exitosos  += 1
            continue

        ok, result = generar_audio(
            caso,
            audio_dir=AUDIO_DIR,
            tld=args.tld,
            slow=args.slow,
            sufijo=args.sufijo,
            force=args.force,
        )

        if ok:
            size_kb = Path(result).stat().st_size / 1024
            print(f"  {PASS_MARK}  {DIM}{size_kb:.1f} KB{RESET}")
            exitosos += 1
        else:
            print(f"  {FAIL_MARK}  {RED}{result}{RESET}")
            fallidos += 1

        # Pausa breve para no saturar la API de Google
        time.sleep(0.3)

    elapsed = time.perf_counter() - t_inicio

    print()
    print(f"  {'─'*50}")
    print(f"  {GREEN}Generados :{RESET} {exitosos - cacheados}")
    print(f"  {DIM}Cacheados : {cacheados}{RESET}")
    if fallidos:
        print(f"  {RED}Fallidos  : {fallidos}{RESET}")
    print(f"  Tiempo    : {elapsed:.1f} s")
    print()
    print(f"  {BOLD}Siguiente paso:{RESET}")
    print(f"  python run_tests.py --mode tts --verbose")
    print()

    sys.exit(0 if fallidos == 0 else 1)


if __name__ == "__main__":
    main()
