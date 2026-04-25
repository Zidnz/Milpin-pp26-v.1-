"""
main.py — Punto de entrada de la API MILPÍN AgTech v2.0

Microservicios registrados:
    /api/balance_hidrico  → Motor FAO-56 (cálculo en memoria, sin persistencia)
    /api/kc/{cultivo}     → Curvas Kc por cultivo
    /api/logistica        → Clustering logístico (K-Means)
    /api/voz              → Pipeline STT + Ollama
    /api/usuarios         → CRUD usuarios (BD)
    /api/cultivos         → Catálogo FAO-56 (BD)
    /api/parcelas         → CRUD parcelas (BD)
    /api/riego            → Historial de riego (BD)
    /api/recomendaciones  → Recomendaciones persistentes (BD)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from API.analytics_api import router as analytics_router
from API.db_api import router as db_router
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

# CORS: necesario para que el frontend (Leaflet en VS Code Live Server) pueda llamar al backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Registro de routers ───────────────────────────────────────────────────────

# Motor agronómico (en memoria, sin BD)
app.include_router(analytics_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(riego_router, prefix="/api")

# Capa de persistencia (PostgreSQL) — MVP 5 tablas
app.include_router(db_router, prefix="/api")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Sistema"])
async def health():
    return {"status": "ok", "sistema": "MILPÍN AgTech v2.0", "version": "mvp"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
