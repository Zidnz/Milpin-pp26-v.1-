"""
test_actuadores.py — Tests de integración para /api/actuadores/* — MILPÍN AgTech v2.0

Qué se prueba:
    1. POST /actuadores/{id}/activar          → 200, estructura ComandoOut completa
    2. POST /actuadores/{id}/activar forzar   → acción='abrir' siempre
    3. POST /actuadores/{id}/activar          → 404 con parcela inexistente
    4. GET  /actuadores/{id}/estado           → 'inactivo' antes de activar
    5. GET  /actuadores/{id}/estado           → estado real después de activar
    6. POST /actuadores/{id}/detener          → estado='cancelado'
    7. POST /actuadores/{id}/detener          → 'inactivo' si no había actuador
    8. GET  /actuadores/modelo/metricas       → 200, modelo XGBoost cargado
    9. POST /actuadores/modelo/reentrenar     → 200, listo=False con BD vacía

Nota sobre estado en memoria:
    Los endpoints GET /estado y POST /detener leen _estado_actuadores (dict global
    en actuador_control.py). Entre tests el dict persiste porque el módulo no se
    reimporta. Esto es intencional — refleja el comportamiento real de la sesión.
    Usamos parcelas con UUIDs únicos por test para evitar colisiones de estado.

Fixtures usadas (conftest.py):
    client      — httpx.AsyncClient con app + SQLite en memoria
    seeded      — parcela semilla con cultivo Maíz + clima_diario
"""

import uuid

import pytest

# ── Disponibilidad de XGBoost ─────────────────────────────────────────────────
# GET /actuadores/modelo/metricas llama a obtener_predictor() directamente.
# Si XGBoost no puede cargar su .so nativo (sandbox, CI sin OpenMP, disco lleno),
# esos endpoints retornan 500. Marcamos esos tests como skip condicional.

def _xgboost_disponible() -> bool:
    try:
        from ml.inference.xgboost_riego import obtener_predictor
        obtener_predictor()
        return True
    except Exception:
        return False

_XGB_OK = _xgboost_disponible()
needs_xgb = pytest.mark.skipif(
    not _XGB_OK,
    reason="XGBoost no disponible en este entorno (libxgboost.so no cargó)"
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_ACTIVAR_PAYLOAD_BASE = {
    "dias_siembra": 60,
    "dias_sin_riego": 5,
    "humedad_suelo_pct": None,
    "precipitacion_mm": 0.0,
    "forzar": False,
}

_CAMPOS_COMANDO = [
    "id_comando", "id_parcela", "accion", "duracion_min",
    "volumen_objetivo_m3", "lamina_objetivo_mm", "caudal_ls", "estado",
    "confianza_xgboost", "riesgo_estres", "nivel_urgencia", "algoritmo",
    "eto_mm", "kc", "etc_mm", "deficit_mm", "timestamp_generacion",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. POST /actuadores/{id}/activar — caso nominal
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activar_estructura_respuesta(client, seeded):
    """El pipeline FAO-56 + XGBoost retorna todos los campos de ComandoOut."""
    id_parcela = seeded["id_parcela"]
    resp = await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json=_ACTIVAR_PAYLOAD_BASE,
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()
    for campo in _CAMPOS_COMANDO:
        assert campo in data, f"Falta campo '{campo}' en respuesta"

    assert data["id_parcela"] == str(id_parcela)
    assert data["accion"] in ("abrir", "standby")
    assert data["estado"] in ("simulado", "inactivo", "standby")
    assert data["algoritmo"] in ("fao56+xgboost-v1", "fao56-solo")
    assert 0.0 <= data["confianza_xgboost"] <= 1.0
    assert 0.0 <= data["riesgo_estres"] <= 1.0
    assert data["nivel_urgencia"] in ("critico", "moderado", "preventivo")
    assert data["eto_mm"] > 0.0, "ETo debe ser positivo"
    assert data["kc"] > 0.0, "Kc debe ser positivo"


@pytest.mark.asyncio
async def test_activar_duracion_coherente(client, seeded):
    """Si se decide regar (accion='abrir'), la duración debe ser > 0."""
    id_parcela = seeded["id_parcela"]
    # Forzar riego para garantizar duración > 0
    resp = await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json={**_ACTIVAR_PAYLOAD_BASE, "forzar": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    if data["accion"] == "abrir":
        assert data["duracion_min"] > 0.0
        assert data["volumen_objetivo_m3"] > 0.0
        assert data["lamina_objetivo_mm"] > 0.0


@pytest.mark.asyncio
async def test_activar_campos_fao56_presentes(client, seeded):
    """ETo, Kc y ETc son campos numéricos positivos en cualquier respuesta."""
    id_parcela = seeded["id_parcela"]
    resp = await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json=_ACTIVAR_PAYLOAD_BASE,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["eto_mm"], float)
    assert isinstance(data["kc"], float)
    assert isinstance(data["etc_mm"], float)
    assert data["eto_mm"] > 0.0
    assert data["kc"] > 0.0
    assert data["etc_mm"] > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. POST /actuadores/{id}/activar con forzar=True
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activar_forzar_genera_comando_abrir(client, seeded):
    """Con forzar=True la acción siempre debe ser 'abrir'."""
    id_parcela = seeded["id_parcela"]
    resp = await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json={**_ACTIVAR_PAYLOAD_BASE, "forzar": True},
    )
    assert resp.status_code == 200
    assert resp.json()["accion"] == "abrir"


# ─────────────────────────────────────────────────────────────────────────────
# 3. POST /actuadores/{id}/activar — parcela inexistente
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activar_parcela_no_existe(client):
    """Retorna 404 si la parcela no existe o está inactiva."""
    resp = await client.post(
        f"/api/actuadores/{uuid.uuid4()}/activar",
        json=_ACTIVAR_PAYLOAD_BASE,
    )
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /actuadores/{id}/estado — antes de activar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_estado_inactivo_antes_de_activar(client):
    """Una parcela sin activaciones previas en la sesión retorna estado='inactivo'."""
    id_parcela = uuid.uuid4()  # ID que nunca se activó
    resp = await client.get(f"/api/actuadores/{id_parcela}/estado")
    assert resp.status_code == 200
    assert resp.json()["estado"] == "inactivo"


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /actuadores/{id}/estado — después de activar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_estado_despues_de_activar(client, seeded):
    """Después de activar, GET /estado retorna el último comando con acción real."""
    id_parcela = seeded["id_parcela"]

    # Activar primero
    resp_act = await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json={**_ACTIVAR_PAYLOAD_BASE, "forzar": True},
    )
    assert resp_act.status_code == 200

    # Consultar estado
    resp_estado = await client.get(f"/api/actuadores/{id_parcela}/estado")
    assert resp_estado.status_code == 200

    data = resp_estado.json()
    assert data["id_parcela"] == str(id_parcela)
    # El estado debe ser 'simulado' (asignado por actuador_control al crear comando)
    assert data["estado"] not in ("inactivo",), (
        "Después de activar, el estado no debe ser 'inactivo'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. POST /actuadores/{id}/detener — después de activar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detener_cambia_estado_a_cancelado(client, seeded):
    """Detener un actuador activo retorna estado='cancelado'."""
    id_parcela = seeded["id_parcela"]

    # Activar primero
    await client.post(
        f"/api/actuadores/{id_parcela}/activar",
        json={**_ACTIVAR_PAYLOAD_BASE, "forzar": True},
    )

    # Detener
    resp = await client.post(f"/api/actuadores/{id_parcela}/detener")
    assert resp.status_code == 200
    assert resp.json()["estado"] == "cancelado"

    # Confirmar que GET /estado refleja el cancelado
    resp_estado = await client.get(f"/api/actuadores/{id_parcela}/estado")
    assert resp_estado.json()["estado"] == "cancelado"


# ─────────────────────────────────────────────────────────────────────────────
# 7. POST /actuadores/{id}/detener — sin actuador activo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detener_sin_actuador_activo(client):
    """Detener una parcela que nunca fue activada retorna estado='inactivo'."""
    id_parcela = uuid.uuid4()
    resp = await client.post(f"/api/actuadores/{id_parcela}/detener")
    assert resp.status_code == 200
    assert resp.json()["estado"] == "inactivo"


# ─────────────────────────────────────────────────────────────────────────────
# 8. GET /actuadores/modelo/metricas
# ─────────────────────────────────────────────────────────────────────────────

@needs_xgb
@pytest.mark.asyncio
async def test_metricas_modelo_estructura(client):
    """Retorna 200 con el estado del modelo XGBoost y sus métricas."""
    resp = await client.get("/api/actuadores/modelo/metricas")
    assert resp.status_code == 200

    data = resp.json()
    assert data["estado"] == "ok"
    assert "modelos" in data
    assert "clasificador_requiere_riego" in data["modelos"]
    assert "regresor_lamina_mm" in data["modelos"]
    assert "regresor_riesgo_estres" in data["modelos"]
    assert "features" in data
    assert "deficit_mm" in data["features"]


@needs_xgb
@pytest.mark.asyncio
async def test_metricas_modelo_tipo_datos(client):
    """El tipo de datos del modelo es 'sintetico-fao56' (no reales aún)."""
    resp = await client.get("/api/actuadores/modelo/metricas")
    assert resp.status_code == 200
    assert resp.json()["tipo_datos"] == "sintetico-fao56"


@needs_xgb
@pytest.mark.asyncio
async def test_metricas_modelo_n_muestras(client):
    """El modelo fue entrenado con al menos 1,000 muestras."""
    resp = await client.get("/api/actuadores/modelo/metricas")
    assert resp.status_code == 200
    n = resp.json()["n_muestras_entrenamiento"]
    assert n >= 1000, f"Se esperaban ≥1000 muestras, got {n}"


# ─────────────────────────────────────────────────────────────────────────────
# 9. POST /actuadores/modelo/reentrenar — diagnóstico con BD vacía
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reentrenar_bd_vacia(client):
    """Con BD vacía, listo_para_reentrenamiento debe ser False."""
    resp = await client.post("/api/actuadores/modelo/reentrenar")
    assert resp.status_code == 200

    data = resp.json()
    assert "listo_para_reentrenamiento" in data
    assert data["listo_para_reentrenamiento"] is False

    datos = data["datos_disponibles"]
    assert datos["recomendaciones_con_feedback"] == 0
    assert datos["faltante"] > 0
    assert "proximos_pasos" in data


@pytest.mark.asyncio
async def test_reentrenar_n_minimo_custom(client):
    """El parámetro n_minimo se respeta en el diagnóstico."""
    resp = await client.post(
        "/api/actuadores/modelo/reentrenar?n_minimo=100"
    )
    assert resp.status_code == 200
    assert resp.json()["datos_disponibles"]["minimo_requerido"] == 100
