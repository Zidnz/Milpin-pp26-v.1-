#!/usr/bin/env python3
"""
run_tests.py — Suite de evaluación del pipeline de voz MILPÍN AgTech v2.0
==========================================================================
Mide la precisión del pipeline Whisper STT → Ollama LLM → JSON validado.

KPI objetivo fase 1 : 85 % de intents correctos (50 audios con ruido).
KPI objetivo producción: 95 %.

MODOS
-----
  texto  — Envía el campo `texto` de cada caso directamente a Ollama.
           Útil para aislar la calidad del LLM sin depender de Whisper.
           Ollama debe estar corriendo: ollama serve

  tts    — Genera audio MP3 desde `texto` con gTTS (Google TTS),
           luego corre el pipeline completo Whisper → Ollama.
           Requiere: pip install gtts  +  Ollama corriendo.
           Los audios se cachean en tests/audio/ para reutilización.

  audio  — Pipeline completo con archivos pre-grabados (WAV / WebM / MP3).
           Los archivos deben estar en tests/audio/ con nombre = TC-XXX.*

USO
---
  # Modo texto (solo LLM) — más rápido
  python run_tests.py

  # Pipeline completo con TTS sintético
  python run_tests.py --mode tts

  # Solo casos de prescripción en modo texto
  python run_tests.py --categoria prescripcion

  # Casos específicos
  python run_tests.py --id TC-019 TC-027 TC-030

  # Guardar reporte JSON para CI
  python run_tests.py --output resultados_$(date +%Y%m%d).json

  # Detalle completo de cada caso (útil para debugging)
  python run_tests.py --verbose

  # Regenerar caché de TTS aunque ya existan los archivos
  python run_tests.py --mode tts --force-tts
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

# ── Path setup ────────────────────────────────────────────────────────────────
# Agrega el directorio raíz del backend al path para importar core/
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# ── ANSI colors (desactivar si no hay terminal TTY) ───────────────────────────
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

# ── Rutas ─────────────────────────────────────────────────────────────────────
TEST_CASES_PATH = os.path.join(os.path.dirname(__file__), "test_cases.json")
AUDIO_DIR       = os.path.join(os.path.dirname(__file__), "audio")


# ─────────────────────────────────────────────────────────────────────────────
# Carga de casos
# ─────────────────────────────────────────────────────────────────────────────

def cargar_casos(
    ids: Optional[list[str]] = None,
    categoria: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Retorna (lista_de_casos, kpi_objetivo)."""
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    casos = data["casos"]
    kpi   = data.get("baseline_kpi", 85)

    if categoria:
        casos = [c for c in casos if c["categoria"] == categoria]
    if ids:
        casos = [c for c in casos if c["id"] in ids]

    return casos, kpi


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def score_intent(resultado: dict, expected: dict) -> bool:
    return resultado.get("intent") == expected.get("intent")


def score_target(resultado: dict, expected: dict) -> tuple[bool, str]:
    """Retorna (correcto, nota_legible)."""
    exp_t = expected.get("target")
    res_t = resultado.get("target")
    if exp_t is None and res_t is None:
        return True, "target=null ✓"
    if exp_t is None:
        return False, f"esperado null, obtenido '{res_t}'"
    if exp_t == res_t:
        return True, f"'{exp_t}' ✓"
    return False, f"esperado '{exp_t}', obtenido '{res_t or 'null'}'"


def score_parameters(resultado: dict, expected: dict) -> dict:
    """
    Puntaje 0.0–1.0 sobre los parámetros de llenar_prescripcion.

    Solo evalúa los campos que el caso esperaba (campos None en expected
    se ignoran). La tasa tiene tolerancia ±5 kg/ha.
    """
    exp_p = expected.get("parameters")
    res_p = resultado.get("parameters")

    if exp_p is None and res_p is None:
        return {"score": 1.0, "campos": {}, "nota": "params=null ✓"}
    if exp_p is None:
        return {"score": 0.5, "campos": {}, "nota": f"params: esperado null, obtenido {res_p}"}
    if res_p is None:
        return {"score": 0.0, "campos": {}, "nota": "params esperado pero LLM devolvió null"}

    campos   = {}
    total    = 0
    correctos = 0

    for campo in ["cultivo", "variedad", "insumo", "zona"]:
        exp_val = exp_p.get(campo)
        if exp_val is not None:
            total += 1
            res_val = res_p.get(campo)
            ok = (res_val == exp_val)
            campos[campo] = {"esperado": exp_val, "obtenido": res_val, "ok": ok}
            if ok:
                correctos += 1

    # tasa: tolerancia ±5 kg/ha
    exp_tasa = exp_p.get("tasa")
    if exp_tasa is not None:
        total += 1
        res_tasa = res_p.get("tasa")
        if res_tasa is not None:
            ok = abs(int(res_tasa) - int(exp_tasa)) <= 5
        else:
            ok = False
        campos["tasa"] = {"esperado": exp_tasa, "obtenido": res_tasa, "ok": ok}
        if ok:
            correctos += 1

    score = correctos / total if total > 0 else 1.0
    nota  = f"{correctos}/{total} campos correctos"
    return {"score": score, "campos": campos, "nota": nota}


def evaluar_caso(caso: dict, resultado: dict) -> dict:
    """Consolida todas las métricas de un caso en un dict estandarizado."""
    expected   = caso["expected"]
    intent_ok  = score_intent(resultado, expected)
    target_ok, target_nota = score_target(resultado, expected)
    params     = score_parameters(resultado, expected)

    # Caso completo: intent correcto + target correcto + params ≥ 0.9
    caso_correcto = intent_ok and target_ok and params["score"] >= 0.9

    return {
        "id":            caso["id"],
        "categoria":     caso["categoria"],
        "texto":         caso["texto"],
        "expected":      expected,
        "resultado":     resultado,
        "intent_ok":     intent_ok,
        "target_ok":     target_ok,
        "target_nota":   target_nota,
        "params":        params,
        "caso_correcto": caso_correcto,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runners
# ─────────────────────────────────────────────────────────────────────────────

def run_texto(caso: dict, **_) -> tuple[dict, float]:
    """Envía texto directo a Ollama. Omite Whisper por completo."""
    from core.llm_orchestrator import interpretar_texto
    t0 = time.perf_counter()
    resultado = interpretar_texto(caso["texto"])
    return resultado, time.perf_counter() - t0


def run_audio(caso: dict, **_) -> tuple[dict, float]:
    """Pipeline completo con archivo de audio pre-grabado."""
    from core.llm_orchestrator import interpretar_comando_voz

    # Busca el archivo con cualquier extensión soportada
    audio_base = os.path.join(AUDIO_DIR, caso["id"])
    audio_path = None
    for ext in [".wav", ".webm", ".mp3", ".m4a", ".ogg"]:
        candidate = audio_base + ext
        if os.path.exists(candidate):
            audio_path = candidate
            break

    # También acepta el campo audio_file del caso
    if audio_path is None and caso.get("audio_file"):
        candidate = os.path.join(AUDIO_DIR, caso["audio_file"])
        if os.path.exists(candidate):
            audio_path = candidate

    if audio_path is None:
        return {
            "intent": "error",
            "target": None,
            "message": f"Archivo no encontrado para {caso['id']} en {AUDIO_DIR}/",
            "parameters": None,
            "transcripcion": "",
        }, 0.0

    t0 = time.perf_counter()
    resultado = interpretar_comando_voz(audio_path)
    return resultado, time.perf_counter() - t0


def run_tts(caso: dict, force: bool = False, **_) -> tuple[dict, float]:
    """
    Genera audio MP3 desde el texto con gTTS (Google TTS) y corre el pipeline completo.
    Los archivos se cachean en tests/audio/ para no hacer llamadas repetidas a la API.
    """
    try:
        from gtts import gTTS
    except ImportError:
        print(f"\n{WARN_MARK} gTTS no instalado. Ejecuta: pip install gtts")
        sys.exit(1)

    from core.llm_orchestrator import interpretar_comando_voz

    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio_path = os.path.join(AUDIO_DIR, f"{caso['id']}_tts.mp3")

    if not os.path.exists(audio_path) or force:
        try:
            tts = gTTS(text=caso["texto"], lang="es", tld="com.mx", slow=False)
            tts.save(audio_path)
        except Exception as exc:
            return {
                "intent": "error",
                "target": None,
                "message": f"Error gTTS: {exc}",
                "parameters": None,
                "transcripcion": "",
            }, 0.0

    t0 = time.perf_counter()
    resultado = interpretar_comando_voz(audio_path)
    return resultado, time.perf_counter() - t0


RUNNERS = {"texto": run_texto, "audio": run_audio, "tts": run_tts}


# ─────────────────────────────────────────────────────────────────────────────
# Impresión de resultados
# ─────────────────────────────────────────────────────────────────────────────

def print_caso(ev: dict, elapsed: float, verbose: bool):
    """Imprime el resultado de un caso individual."""
    mark = PASS_MARK if ev["caso_correcto"] else FAIL_MARK
    res  = ev["resultado"]
    exp  = ev["expected"]

    if not verbose and ev["caso_correcto"]:
        return  # En modo normal solo muestra fallos (la barra de progreso ya imprimió el ✓)

    print()
    print(f"  {mark} {BOLD}[{ev['id']}]{RESET} {DIM}{ev['texto'][:65]}{RESET}")

    # Transcripción STT (solo en modo audio/tts y si difiere del texto original)
    transcripcion = res.get("transcripcion", "")
    if transcripcion and transcripcion != ev["texto"]:
        print(f"      {DIM}STT → \"{transcripcion[:70]}\"{RESET}")

    # Intent
    ic = GREEN if ev["intent_ok"] else RED
    print(f"      intent : {ic}{res.get('intent')}{RESET}  (esperado: {exp.get('intent')})")

    # Target (solo si alguno no es null)
    if exp.get("target") is not None or res.get("target") is not None:
        tc = GREEN if ev["target_ok"] else RED
        print(f"      target : {tc}{ev['target_nota']}{RESET}")

    # Parámetros
    if ev["params"]["campos"]:
        pc = GREEN if ev["params"]["score"] >= 0.9 else RED
        print(f"      params : {pc}{ev['params']['nota']}{RESET}")
        if not ev["caso_correcto"]:
            for campo, info in ev["params"]["campos"].items():
                pm = PASS_MARK if info["ok"] else FAIL_MARK
                print(f"               {pm} {campo}: esperado='{info['esperado']}' obtenido='{info['obtenido']}'")

    print(f"      {DIM}latencia: {elapsed*1000:.0f} ms{RESET}")


def print_reporte(evaluaciones: list[dict], latencias: list[float], modo: str, kpi: int):
    """Imprime el reporte final con métricas agregadas."""
    total  = len(evaluaciones)
    if total == 0:
        print(f"\n{WARN_MARK} Sin evaluaciones que reportar.")
        return

    casos_ok   = sum(1 for e in evaluaciones if e["caso_correcto"])
    intents_ok = sum(1 for e in evaluaciones if e["intent_ok"])

    pct_casos   = casos_ok   / total * 100
    pct_intents = intents_ok / total * 100

    lat_sorted = sorted(latencias)
    lat_media  = sum(latencias) / len(latencias)
    lat_p95    = lat_sorted[min(int(len(lat_sorted) * 0.95), len(lat_sorted) - 1)]

    kpi_ok    = pct_intents >= kpi
    kpi_color = GREEN if kpi_ok else RED
    kpi_label = f"{GREEN}✓ KPI FASE 1 CUMPLIDO{RESET}" if kpi_ok else f"{RED}✗ KPI no alcanzado (meta: {kpi}%){RESET}"

    print()
    print(f"{BOLD}{'═'*62}{RESET}")
    print(f"{BOLD}  MILPÍN — Reporte Evaluación Pipeline de Voz{RESET}")
    print(f"  Modo: {CYAN}{modo}{RESET}  │  Casos: {total}  │  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*62}")
    print()

    print(f"  {BOLD}Intent accuracy  :{RESET}  {kpi_color}{intents_ok}/{total}  ({pct_intents:.1f}%){RESET}  {kpi_label}")
    print(f"  {BOLD}Casos completos  :{RESET}  {casos_ok}/{total}  ({pct_casos:.1f}%)")
    print(f"  {BOLD}Latencia media   :{RESET}  {lat_media*1000:.0f} ms   P95: {lat_p95*1000:.0f} ms")
    print()

    # ── Por categoría ─────────────────────────────────────────────────────────
    categorias: dict[str, dict] = {}
    for ev in evaluaciones:
        cat = ev["categoria"]
        if cat not in categorias:
            categorias[cat] = {"total": 0, "intent_ok": 0, "params_scores": []}
        categorias[cat]["total"] += 1
        if ev["intent_ok"]:
            categorias[cat]["intent_ok"] += 1
        if ev["params"]["campos"]:
            categorias[cat]["params_scores"].append(ev["params"]["score"])

    print(f"  {BOLD}Por categoría:{RESET}")
    col_w = max(len(c) for c in categorias) + 2
    for cat, stats in sorted(categorias.items()):
        pct   = stats["intent_ok"] / stats["total"] * 100
        llen  = int(pct / 10)
        bar   = "█" * llen + "░" * (10 - llen)
        color = GREEN if pct >= kpi else (YELLOW if pct >= 70 else RED)
        line  = f"    {cat:<{col_w}} {color}{bar}{RESET} {stats['intent_ok']}/{stats['total']} ({pct:.0f}%)"
        if stats["params_scores"]:
            avg_p = sum(stats["params_scores"]) / len(stats["params_scores"])
            line += f"  {DIM}params avg: {avg_p:.0%}{RESET}"
        print(line)

    # ── Fallos ────────────────────────────────────────────────────────────────
    fallos = [e for e in evaluaciones if not e["caso_correcto"]]
    if fallos:
        print()
        print(f"  {BOLD}{RED}Casos fallidos ({len(fallos)}):{RESET}")
        for e in fallos:
            res_intent  = e["resultado"].get("intent", "?")
            exp_intent  = e["expected"].get("intent", "?")
            transcripcion = e["resultado"].get("transcripcion", "")
            print(f"    {FAIL_MARK} [{e['id']}]  {DIM}\"{e['texto'][:55]}\"{RESET}")
            if res_intent != exp_intent:
                print(f"         intent:  {RED}{res_intent}{RESET}  (esperado: {exp_intent})")
            if transcripcion and transcripcion != e["texto"]:
                print(f"         STT:     \"{transcripcion[:60]}\"")
            if e["params"]["campos"] and e["params"]["score"] < 0.9:
                print(f"         params:  {e['params']['nota']}")
    else:
        print()
        print(f"  {GREEN}Sin fallos. ¡Pipeline limpio!{RESET}")

    print()
    print(f"{'═'*62}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Suite de tests del pipeline de voz MILPÍN AgTech v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["texto", "audio", "tts"],
        default="texto",
        help="Modo de ejecución (default: texto)",
    )
    parser.add_argument(
        "--categoria", "-c",
        choices=["navegacion", "ejecutar_analisis", "prescripcion", "consultar", "saludo", "desconocido"],
        help="Filtrar por categoría de casos",
    )
    parser.add_argument(
        "--id", "-i",
        nargs="+",
        metavar="ID",
        help="IDs específicos a correr (ej. TC-001 TC-019)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Guardar resultados detallados en JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar detalle de todos los casos (no solo fallos)",
    )
    parser.add_argument(
        "--force-tts",
        action="store_true",
        help="Regenerar archivos TTS aunque ya existan en caché",
    )
    args = parser.parse_args()

    # ── Cargar casos ──────────────────────────────────────────────────────────
    casos, kpi = cargar_casos(ids=args.id, categoria=args.categoria)
    if not casos:
        print(f"{WARN_MARK} Sin casos con los filtros especificados.")
        sys.exit(1)

    runner = RUNNERS[args.mode]

    print(f"\n{BOLD}MILPÍN — Suite de Evaluación de Voz{RESET}")
    print(f"Modo: {CYAN}{args.mode}{RESET}  │  Casos: {len(casos)}  │  KPI objetivo: {kpi}%")

    if args.mode == "texto":
        print(f"{DIM}(Cargando Whisper igualmente; su inferencia no se usará en este modo){RESET}")
    else:
        print(f"{DIM}Cargando Whisper... puede tardar hasta 60 s la primera vez.{RESET}")
    print()

    evaluaciones : list[dict] = []
    latencias    : list[float] = []

    # Limpiar historial antes de la suite para aislar cada caso
    try:
        from core.llm_orchestrator import limpiar_historial
        limpiar_historial()
    except Exception:
        pass  # No es crítico si falla

    for i, caso in enumerate(casos, 1):
        prefix = f"  [{i:02d}/{len(casos):02d}] {DIM}{caso['id']}{RESET}"
        print(f"{prefix}  {DIM}{caso['texto'][:55]}...{RESET}", end="", flush=True)

        try:
            resultado, elapsed = runner(caso, force=args.force_tts)
        except Exception as exc:
            print(f"\r  {FAIL_MARK} [{i:02d}/{len(casos):02d}] {RED}ERROR: {exc}{RESET}")
            # Registrar como caso fallido
            evaluaciones.append(evaluar_caso(caso, {
                "intent": "error", "target": None,
                "message": str(exc), "parameters": None, "transcripcion": "",
            }))
            latencias.append(0.0)
            continue

        ev = evaluar_caso(caso, resultado)
        evaluaciones.append(ev)
        latencias.append(elapsed)

        mark = PASS_MARK if ev["caso_correcto"] else FAIL_MARK
        print(f"\r  {mark} [{caso['id']}]  {DIM}{caso['texto'][:55]}{RESET}  {DIM}{elapsed*1000:.0f}ms{RESET}")

        # Detalle del caso (solo fallos en modo normal, todos en verbose)
        if args.verbose or not ev["caso_correcto"]:
            print_caso(ev, elapsed, args.verbose)

    # ── Reporte final ─────────────────────────────────────────────────────────
    print_reporte(evaluaciones, latencias, args.mode, kpi)

    # ── Guardar JSON ──────────────────────────────────────────────────────────
    if args.output and evaluaciones:
        total      = len(evaluaciones)
        intents_ok = sum(1 for e in evaluaciones if e["intent_ok"])
        output_data = {
            "fecha":             datetime.now().isoformat(),
            "modo":              args.mode,
            "total_casos":       total,
            "intent_accuracy":   round(intents_ok / total, 4),
            "kpi_objetivo":      kpi,
            "kpi_cumplido":      (intents_ok / total * 100) >= kpi,
            "casos":             evaluaciones,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  {PASS_MARK} Resultados guardados en: {args.output}\n")

    # ── Exit code para CI (0 = KPI cumplido, 1 = KPI no alcanzado) ───────────
    pct_intents = sum(1 for e in evaluaciones if e["intent_ok"]) / len(evaluaciones) * 100
    sys.exit(0 if pct_intents >= kpi else 1)


if __name__ == "__main__":
    main()
