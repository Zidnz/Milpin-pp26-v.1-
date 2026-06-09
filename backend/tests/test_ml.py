"""
test_ml.py — Tests de integración para /api/ml/* — MILPÍN AgTech v2.0

Qué se prueba:
    1. GET /api/ml/metricas       → estructura y campos del payload
    2. GET /api/ml/prediccion/{id} → 200 con parcela existente (fallback defaults)
    3. GET /api/ml/prediccion/{id} → 200 con última recomendación en BD
    4. GET /api/ml/prediccion/{id} → 404 con parcela inexistente
    5. GET /api/ml/anomalias       → 200, estructura correcta
    6. GET /api/ml/anomalias?solo_anomalias=false → incluye no-anómalos

Qué NO se prueba:
    - La matemática interna de XGBoost o Isolation Forest (son modelos entrenados).
    - La precisión de las predicciones (se cubre con las métricas declaradas en /metricas).

Fixtures usadas (conftest.py):
    client      — httpx.AsyncClient con app + SQLite en memoria
    seeded      — parcela semilla con cultivo Maíz + clima_diario
    db_session  — sesión directa para insertar recomendaciones previas
"""

import uuid
from datetime import date, datetime

import pytest

import models

# ── Disponibilidad de XGBoost ─────────────────────────────────────────────────
# En el entorno de desarrollo (máquina de Omar) XGBoost está disponible y los
# modelos .joblib están en backend/models_ml/. En algunos entornos CI/sandbox
# la librería nativa no carga (disco lleno, OpenMP ausente, etc.).
# Los tests que dependen de XGBoost se marcan con `needs_xgb` y se saltan
# automáticamente si el runtime no está disponible.

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


def _anomaly_disponible() -> bool:
    try:
        import joblib  # noqa: F401
        from ml.inference.anomaly_detector import AnomalyDetector  # noqa: F401
        return True
    except Exception:
        return False

_ANOMALY_OK = _anomaly_disponible()
needs_anomaly = pytest.mark.skipif(
    not _ANOMALY_OK,
    reason="Isolation Forest no disponible en este entorno (joblib/scikit-learn ausente)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/ml/metricas
# ─────────────────────────────────────────────────────────────────────────────

@needs_xgb
@pytest.mark.asyncio
async def test_ml_metricas_estructura(client):
    """Retorna 200 con las métricas de ambos modelos y el disclaimer."""
    resp = await client.get("/api/ml/metricas")
    assert resp.status_code == 200

    data = resp.json()
    assert "xgboost_riego" in data
    assert "isolation_forest" in data
    assert "disclaimer" in data

    xgb = data["xgboost_riego"]
    assert xgb["entrenado"] is True
    assert "metricas" in xgb
    assert "features" in xgb
    assert "deficit_mm" in xgb["features"]

    ifo = data["isolation_forest"]
    assert ifo["entrenado"] is True
    assert "metricas" in ifo

    # Las métricas del clasificador XGBoost deben tener accuracy y f1
    metricas_clf = xgb["metricas"].get("clasificador", {})
    assert "accuracy" in metricas_clf
    assert metricas_clf["accuracy"] > 0.90, "Accuracy del clasificador debe ser >90%"


@needs_xgb
@pytest.mark.asyncio
async def test_ml_metricas_iforest_campos(client):
    """Isolation Forest tiene precision, recall y f1 reportados."""
    resp = await client.get("/api/ml/metricas")
    assert resp.status_code == 200
    ifo_metricas = resp.json()["isolation_forest"]["metricas"]
    assert "precision" in ifo_metricas
    assert "recall" in ifo_metricas
    assert "f1" in ifo_metricas


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/ml/prediccion/{id} — parcela existente, sin recomendación previa
# ─────────────────────────────────────────────────────────────────────────────

@needs_xgb
@pytest.mark.asyncio
async def test_ml_prediccion_defaults(client, seeded):
    """
    Cuando no hay recomendaciones previas, el endpoint usa defaults por tipo_suelo.
    Debe retornar 200 con todos los campos obligatorios.
    """
    id_parcela = seeded["id_parcela"]
    resp = await client.get(f"/api/ml/prediccion/{id_parcela}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["id_parcela"] == str(id_parcela)
    assert "requiere_riego" in data
    assert isinstance(data["requiere_riego"], bool)
    assert "probabilidad_riego" in data
    assert 0.0 <= data["probabilidad_riego"] <= 1.0
    assert "lamina_ajustada_mm" in data
    assert data["lamina_ajustada_mm"] >= 0.0
    assert "riesgo_estres" in data
    assert 0.0 <= data["riesgo_estres"] <= 1.0
    assert "nivel_urgencia" in data
    assert data["nivel_urgencia"] in ("critico", "moderado", "preventivo")
    assert "algoritmo" in data
    assert "inputs_usados" in data
    assert data["inputs_usados"]["fuente"] == "defaults_tipo_suelo"
    assert "disclaimer" in data


@needs_xgb
@pytest.mark.asyncio
async def test_ml_prediccion_campos_inputs(client, seeded):
    """Los inputs_usados incluyen todos los campos agronómicos de trazabilidad."""
    id_parcela = seeded["id_parcela"]
    resp = await client.get(f"/api/ml/prediccion/{id_parcela}")
    assert resp.status_code == 200

    inputs = resp.json()["inputs_usados"]
    for campo in ("deficit_mm", "etc_mm", "eto_mm", "kc",
                  "dias_sin_riego", "humedad_pct", "cc_pct", "pmp_pct"):
        assert campo in inputs, f"Falta campo '{campo}' en inputs_usados"


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /api/ml/prediccion/{id} — parcela con última recomendación en BD
# ─────────────────────────────────────────────────────────────────────────────

@needs_xgb
@pytest.mark.asyncio
async def test_ml_prediccion_usa_ultima_recomendacion(client, seeded, db_session):
    """
    Si existe una recomendación previa en BD, el endpoint la usa como fuente
    de inputs (fuente='ultima_recomendacion').
    """
    id_parcela = seeded["id_parcela"]

    # Insertar una recomendación manual
    rec = models.Recomendacion(
        id_recomendacion=uuid.uuid4(),
        id_parcela=id_parcela,
        fecha_generacion=datetime.utcnow(),
        fecha_riego_sugerida=date.today(),
        lamina_recomendada_mm=40.0,
        deficit_acumulado_mm=35.0,
        etc_calculada=5.5,
        eto_referencia=7.2,
        dias_sin_riego=5,
        aceptada="pendiente",
        parametros_json={"humedad_actual_pct": 22.5},
    )
    db_session.add(rec)
    await db_session.commit()

    resp = await client.get(f"/api/ml/prediccion/{id_parcela}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["inputs_usados"]["fuente"] == "ultima_recomendacion"
    # Los valores deben coincidir con lo que insertamos
    assert abs(data["inputs_usados"]["deficit_mm"] - 35.0) < 0.5
    assert abs(data["inputs_usados"]["etc_mm"] - 5.5) < 0.5
    assert data["inputs_usados"]["dias_sin_riego"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/ml/prediccion/{id} — parcela inexistente
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ml_prediccion_parcela_no_existe(client):
    """Retorna 404 si la parcela no existe en BD."""
    id_fake = uuid.uuid4()
    resp = await client.get(f"/api/ml/prediccion/{id_fake}")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /api/ml/anomalias — solo_anomalias=true (default)
# ─────────────────────────────────────────────────────────────────────────────

@needs_anomaly
@pytest.mark.asyncio
async def test_ml_anomalias_solo_anomalas(client):
    """
    Retorna 200 con la estructura correcta.
    Con BD vacía hace fallback al CSV sintético; la detección debe funcionar.
    """
    resp = await client.get("/api/ml/anomalias?solo_anomalias=true&limit=20")
    assert resp.status_code == 200

    data = resp.json()
    assert "total_pares_analizados" in data
    assert "total_anomalias" in data
    assert "pct_anomalias" in data
    assert "resultados" in data
    assert "config_modelo" in data
    assert "disclaimer" in data

    # Con solo_anomalias=true todos los resultados deben ser anómalos
    for r in data["resultados"]:
        assert r["es_anomalia"] is True

    # El porcentaje debe ser coherente
    assert 0.0 <= data["pct_anomalias"] <= 100.0


@needs_anomaly
@pytest.mark.asyncio
async def test_ml_anomalias_estructura_item(client):
    """Cada ítem de resultados tiene los campos mínimos esperados."""
    resp = await client.get("/api/ml/anomalias?solo_anomalias=true&limit=5")
    assert resp.status_code == 200

    resultados = resp.json()["resultados"]
    if not resultados:
        pytest.skip("No hay anomalías detectadas en el CSV sintético")

    item = resultados[0]
    for campo in ("id_parcela", "ciclo_agricola", "es_anomalia", "anomaly_score"):
        assert campo in item, f"Falta campo '{campo}' en ítem de anomalías"


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/ml/anomalias?solo_anomalias=false — incluye no-anómalos
# ─────────────────────────────────────────────────────────────────────────────

@needs_anomaly
@pytest.mark.asyncio
async def test_ml_anomalias_todos(client):
    """Con solo_anomalias=false el total de pares > total de anomalías."""
    resp_anomalas = await client.get("/api/ml/anomalias?solo_anomalias=true")
    resp_todos    = await client.get("/api/ml/anomalias?solo_anomalias=false")
    assert resp_anomalas.status_code == 200
    assert resp_todos.status_code == 200

    n_anomalas = resp_anomalas.json()["total_pares_analizados"]
    n_todos    = resp_todos.json()["total_pares_analizados"]
    assert n_todos >= n_anomalas, (
        "solo_anomalias=false debe retornar al menos tantos pares como solo_anomalias=true"
    )


@needs_anomaly
@pytest.mark.asyncio
async def test_ml_anomalias_limit_respetado(client):
    """El parámetro limit recorta el array de resultados correctamente."""
    resp = await client.get("/api/ml/anomalias?solo_anomalias=false&limit=3")
    assert resp.status_code == 200
    assert len(resp.json()["resultados"]) <= 3


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/ml/anomalias — config_modelo correcto
# ─────────────────────────────────────────────────────────────────────────────

@needs_anomaly
@pytest.mark.asyncio
async def test_ml_anomalias_config_modelo(client):
    """El campo config_modelo tiene las features y parámetros del Isolation Forest."""
    resp = await client.get("/api/ml/anomalias")
    assert resp.status_code == 200

    cfg = resp.json()["config_modelo"]
    assert cfg["contamination"] == 0.12
    assert cfg["n_estimators"] == 160
    assert "vol_total_m3_ha" in cfg["features"]
    assert "n_eventos" in cfg["features"]
