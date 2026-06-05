"""
main.py — Punto de entrada de la API MILPÍN AgTech v2.0

Microservicios registrados:
    /api/balance_hidrico          → Motor FAO-56 (cálculo en memoria, sin persistencia)
    /api/kc/{cultivo}             → Curvas Kc por cultivo
    /api/voz                      → Pipeline STT + Ollama
    /api/usuarios                 → CRUD usuarios (BD)
    /api/cultivos                 → Catálogo FAO-56 (BD)
    /api/parcelas                 → CRUD parcelas (BD)
    /api/riego                    → Historial de riego (BD)
    /api/recomendaciones          → Recomendaciones persistentes (BD)
    /api/actuadores/{id}/activar  → Control automático FAO-56 + XGBoost
    /api/actuadores/modelo/*      → Métricas y diagnóstico del modelo XGBoost
    /api/ml/prediccion/{id}       → XGBoost: requiere_riego, lamina_ajustada, riesgo_estres
    /api/ml/anomalias             → Isolation Forest: detección de ciclos anómalos
    /api/ml/metricas              → Métricas de ambos modelos ML
"""

from contextlib import asynccontextmanager

import os
import sys
from pathlib import Path

# Agrega la raíz del repo a sys.path para que `ml.inference` sea importable
# desde el backend (que corre en backend/ como cwd).
_REPO_ROOT = str(Path(__file__).parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Alias de paquete para case-sensitivity Linux/macOS.
# En Windows ML/ == ml/ (case-insensitive). En Linux hay que registrar
# todos los submódulos explícitamente para que el import system no se confunda.
try:
    import ML as _ml_pkg
    import ML.inference as _ml_inf
    import ML.inference.xgboost_riego as _ml_xgb
    import ML.inference.anomaly_detector as _ml_ad
    for _name, _mod in [
        ("ml",                            _ml_pkg),
        ("ml.inference",                  _ml_inf),
        ("ml.inference.xgboost_riego",    _ml_xgb),
        ("ml.inference.anomaly_detector", _ml_ad),
    ]:
        sys.modules.setdefault(_name, _mod)
except ImportError:
    pass  # En Windows los nombres ml/ == ML/ resuelven solos

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from API.actuadores_api import router as actuadores_router
from API.db_api import router as db_router
from API.ml_api import router as ml_router
from API.operacion_api import router as operacion_router
from API.riego_api import router as riego_router
from API.voice_endpoint import router as voice_router
from database import create_all_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación FastAPI.
    Al arrancar: crea las tablas de la BD si no existen (no destructivo).
    """
    print("MILPÍN AgTech v2.0 — Iniciando...")
    try:
        await create_all_tables()
        print("✓ Base de datos: tablas verificadas/creadas.")
    except Exception as e:
        print(f"⚠  Base de datos no disponible: {e}")
        print("   El backend inicia igualmente. Los endpoints de BD retornarán 503.")
        print("   Para configurar PostgreSQL: consulta README_DB.md")

    yield  # ← La app corre aquí

    print("MILPÍN AgTech v2.0 — Cerrando...")


app = FastAPI(
    title="MILPÍN AgTech v2.0 API",
    description=(
        "Sistema inteligente de optimización agrícola — Valle del Yaqui, DR-041.\n"
        "KPI objetivo: reducir consumo hídrico de 8,000 a 6,000 m³/ha/ciclo (−25%)."
    ),
    version="2.0.0-mvp",
    lifespan=lifespan,
)

# CORS: orígenes explícitos (no wildcard) para compatibilidad futura con auth/cookies.
# Agregar aquí cualquier origen adicional de desarrollo o producción.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",   # VS Code Live Server (puerto por defecto)
    "http://127.0.0.1:5500",
    "http://localhost:5501",   # VS Code Live Server (si 5500 está ocupado)
    "http://127.0.0.1:5501",
    "http://localhost:8080",   # Python http.server / otros servidores locales
    "http://127.0.0.1:8080",
    "null",                    # file:// abierto directo en navegador
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
    allow_credentials=False,
)


# ── Handler global de errores no capturados ───────────────────────────────────
# Starlette no propaga Access-Control-Allow-Origin en respuestas de error
# generadas por excepciones no capturadas (bypass del CORSMiddleware).
# Este handler asegura que los headers CORS lleguen incluso en 500.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    origin = request.headers.get("origin", "")
    cors_header = origin if origin in ALLOWED_ORIGINS else ""

    # Imprimir traceback completo en la terminal del servidor para debug
    print(f"\n[ERROR 500] {request.method} {request.url}")
    traceback.print_exc()

    headers = {}
    if cors_header:
        headers["Access-Control-Allow-Origin"] = cors_header

    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno del servidor: {type(exc).__name__}: {exc}"},
        headers=headers,
    )

# ── Registro de routers ───────────────────────────────────────────────────────

# Motor agronómico (en memoria, sin BD)
app.include_router(voice_router, prefix="/api")
app.include_router(riego_router, prefix="/api")

# Capa de persistencia (PostgreSQL) — MVP 5 tablas
app.include_router(db_router, prefix="/api")

# Control automático de actuadores (FAO-56 + XGBoost)
app.include_router(actuadores_router, prefix="/api")

# Machine Learning: XGBoost predicción + Isolation Forest anomalías
app.include_router(ml_router, prefix="/api")

# Vista operacional: triage + pulso climático
app.include_router(operacion_router, prefix="/api")

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Sistema"])
async def health():
    """Verificación rápida de que el backend está en línea."""
    return {"status": "ok", "sistema": "MILPÍN AgTech v2.0", "version": "mvp"}


# ── Archivos estáticos: imágenes de cultivos ──────────────────────────────────
# Sirve la carpeta /imagenes/ del proyecto en /static/imagenes/
# URL de acceso: http://localhost:8000/static/imagenes/<archivo>
_imagenes_dir = os.path.join(os.path.dirname(__file__), "..", "imagenes")
if os.path.isdir(_imagenes_dir):
    app.mount(
        "/static/imagenes",
        StaticFiles(directory=_imagenes_dir),
        name="imagenes",
    )