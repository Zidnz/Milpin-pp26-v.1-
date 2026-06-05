"""
test_riego_e2e.py — Tests de integración del loop FAO-56 → BD

Qué se prueba aquí:
    1. El endpoint GET /api/balance_hidrico produce HTTP 200 y el JSON esperado.
    2. La recomendación se persiste REALMENTE en la tabla `recomendaciones`
       (consulta independiente a la BD después del request).
    3. Los campos críticos del registro persistido son correctos.
    4. Casos de error: 404 sin clima_diario, 404 sin parcela, 400 sin cultivo.
    5. El endpoint legacy /api/balance_hidrico_manual funciona sin BD.
    6. El endpoint /api/kc/{cultivo} retorna la curva correcta.

Qué NO se prueba aquí:
    - La matemática FAO-56 en detalle (eso es test_fao56_unit.py).
    - El pipeline de voz (tiene su propia suite en run_tests.py).

Fixtures usadas (definidas en conftest.py):
    client      — httpx.AsyncClient apuntando a la app con BD SQLite
    seeded      — registros semilla: 1 usuario, 1 parcela (Maíz), 1 clima_diario
    db_session  — sesión directa para verificar estado post-request
    test_engine — motor SQLite aislado (base de las otras fixtures)
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import models


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _contar_recomendaciones(engine, id_parcela: uuid.UUID) -> int:
    """Abre una sesión nueva (independiente del request) y cuenta recomendaciones."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        res = await session.execute(
            select(models.Recomendacion).where(
                models.Recomendacion.id_parcela == id_parcela
            )
        )
        return len(res.scalars().all())


async def _get_recomendacion(engine, id_parcela: uuid.UUID) -> models.Recomendacion | None:
    """Recupera la primera recomendación de la parcela (sesión independiente)."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        res = await session.execute(
            select(models.Recomendacion)
            .where(models.Recomendacion.id_parcela == id_parcela)
            .limit(1)
        )
        return res.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Clase principal: loop completo
# ─────────────────────────────────────────────────────────────────────────────

class TestLoopFao56BD:

    async def test_endpoint_retorna_200(self, client: AsyncClient, seeded: dict, test_engine):
        """El endpoint responde 200 con datos semilla válidos."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        assert r.status_code == 200, f"Esperaba 200, recibí {r.status_code}: {r.text}"

    async def test_respuesta_contiene_claves_obligatorias(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """El JSON de respuesta incluye todos los campos esperados del contrato API."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        body = r.json()
        claves_obligatorias = {
            "id_recomendacion",
            "parcela_id",
            "cultivo",
            "fecha_calculo",
            "metodo_eto",
            "eto_mm",
            "kc",
            "etc_mm",
            "balance",
            "costo",
            "nivel_urgencia",
            "persistido",
        }
        faltantes = claves_obligatorias - body.keys()
        assert not faltantes, f"Claves faltantes en respuesta: {faltantes}"

    async def test_persistido_true_en_respuesta(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """El campo 'persistido' debe ser True — confirma que el endpoint intentó escribir en BD."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        assert r.json()["persistido"] is True

    async def test_recomendacion_existe_en_bd(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """
        Test central: después del request, la tabla `recomendaciones`
        contiene exactamente 1 fila para la parcela.
        Esto verifica que el commit de la sesión ocurrió correctamente.
        """
        await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        count = await _contar_recomendaciones(test_engine, seeded["id_parcela"])
        assert count == 1, f"Esperaba 1 recomendación en BD, encontré {count}"

    async def test_dos_requests_generan_dos_recomendaciones(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """Cada llamada al endpoint genera y persiste una recomendación nueva."""
        params = {
            "parcela_id": str(seeded["id_parcela"]),
            "dias_siembra": 30,
            "fecha": seeded["fecha"].isoformat(),
        }
        await client.get("/api/balance_hidrico", params=params)
        await client.get("/api/balance_hidrico", params=params)

        count = await _contar_recomendaciones(test_engine, seeded["id_parcela"])
        assert count == 2, f"Esperaba 2 recomendaciones, encontré {count}"

    async def test_campos_recomendacion_persistida(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """
        Verifica que los campos críticos del registro persistido son coherentes
        con la parcela semilla y el cultivo.
        """
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        body = r.json()
        rec = await _get_recomendacion(test_engine, seeded["id_parcela"])

        assert rec is not None, "No se encontró la recomendación en BD"

        # El id en la respuesta debe coincidir con el de BD
        assert str(rec.id_recomendacion) == body["id_recomendacion"]

        # ETo almacenada debe ser positiva
        assert float(rec.eto_referencia) > 0.0

        # ETc debe ser positiva y coherente con etc_mm del response
        assert float(rec.etc_calculada) > 0.0
        assert float(rec.etc_calculada) == pytest.approx(body["etc_mm"], rel=0.01)

        # Urgencia válida según el CHECK de la tabla
        assert rec.nivel_urgencia in ("critico", "moderado", "preventivo")

        # Estado inicial del feedback
        assert rec.aceptada == "pendiente"

        # algoritmo_version trazable
        assert rec.algoritmo_version == "fao56-mvp-v1.0"

        # Snapshot de parámetros presente
        assert rec.parametros_json is not None
        assert "cultivo" in rec.parametros_json
        assert "fecha" in rec.parametros_json

    async def test_metodo_eto_penman_con_datos_completos(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """Con los 5 campos climáticos completos, el método usado debe ser Penman-Monteith."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        assert r.json()["metodo_eto"] == "penman_monteith"

    async def test_eto_en_rango_fisico_verano_sonora(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """
        Con tmax=38, tmin=22, hr=35, viento=2.5, Rg=22 (semilla),
        ETo Penman-Monteith debe estar entre 6 y 12 mm/día.
        La función recibe Rg (solar bruta), no Rn (neta), por eso el valor
        resultante es ~7-8 mm/día, no 9-13 como estimaría sin conversión.
        """
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        eto = r.json()["eto_mm"]
        assert 6.0 <= eto <= 12.0, f"ETo={eto} fuera del rango esperado para verano Sonora"

    async def test_costo_riego_presente_y_positivo(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """El bloque 'costo' en la respuesta tiene los tres campos y son positivos."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        costo = r.json()["costo"]
        assert costo["energia_kwh"] > 0
        assert costo["costo_pesos"] > 0
        assert costo["costo_por_m3"] > 0


    async def test_usa_et0_precalculado_cuando_disponible(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """Si clima_diario.et0 esta precalculado, el endpoint lo usa y reporta
        metodo_eto='et0_precalculado' en lugar de recalcular con Penman-Monteith."""
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import update
        import models
        # Escribir et0 via la misma factory que usa el client (mismo engine, misma conexion)
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                update(models.ClimaDiario)
                .where(
                    models.ClimaDiario.id_parcela == seeded["id_parcela"],
                    models.ClimaDiario.fecha == seeded["fecha"],
                )
                .values(et0=7.5)
            )
            await session.commit()

        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["metodo_eto"] == "et0_precalculado"
        assert body["eto_mm"] == pytest.approx(7.5, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Casos de error
# ─────────────────────────────────────────────────────────────────────────────

class TestCasosError:

    async def test_parcela_inexistente_retorna_404(
        self, client: AsyncClient, test_engine
    ):
        """UUID que no existe en BD → 404."""
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(uuid.uuid4()),
                "dias_siembra": 30,
            },
        )
        assert r.status_code == 404

    async def test_sin_clima_diario_retorna_404(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """
        La parcela existe pero no hay registro de clima para la fecha pedida.
        El endpoint debe retornar 404 (no 500).
        """
        fecha_sin_datos = date(2020, 1, 1)  # fecha sin datos en la semilla
        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(seeded["id_parcela"]),
                "dias_siembra": 30,
                "fecha": fecha_sin_datos.isoformat(),
            },
        )
        assert r.status_code == 404

    async def test_parcela_sin_cultivo_retorna_400(
        self, client: AsyncClient, seeded: dict, db_session: AsyncSession, test_engine
    ):
        """
        Parcela en barbecho (id_cultivo_actual=NULL) → el endpoint retorna 400
        con mensaje explicativo, no 500.
        """
        # Crear parcela sin cultivo asignado
        id_usuario = seeded["id_usuario"]
        id_parcela_barb = uuid.uuid4()
        parcela_barb = models.Parcela(
            id_parcela=id_parcela_barb,
            id_usuario=id_usuario,
            id_cultivo_actual=None,   # barbecho
            nombre_parcela="Barbecho Sur",
            geom=None,
            area_ha=3.0,
            capacidad_campo=0.30,
            punto_marchitez=0.15,
            profundidad_raiz_cm=50,
            sistema_riego="gravedad",
        )
        db_session.add(parcela_barb)
        await db_session.commit()

        r = await client.get(
            "/api/balance_hidrico",
            params={
                "parcela_id": str(id_parcela_barb),
                "dias_siembra": 30,
                "fecha": seeded["fecha"].isoformat(),
            },
        )
        assert r.status_code == 400
        assert "cultivo" in r.json()["detail"].lower()

    async def test_sin_parcela_id_retorna_422(self, client: AsyncClient, test_engine):
        """Request sin parcela_id → FastAPI retorna 422 (validación Pydantic)."""
        r = await client.get("/api/balance_hidrico", params={"dias_siembra": 30})
        assert r.status_code == 422

    async def test_sin_dias_siembra_retorna_422(
        self, client: AsyncClient, seeded: dict, test_engine
    ):
        """Request sin dias_siembra → FastAPI retorna 422."""
        r = await client.get(
            "/api/balance_hidrico",
            params={"parcela_id": str(seeded["id_parcela"])},
        )
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint legacy (balance_hidrico_manual) — sin BD
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyManual:
    """
    El endpoint legacy /api/balance_hidrico_manual no lee ni escribe en BD.
    Sirve para verificar el motor sin dependencia de datos semilla.
    """

    BASE_PARAMS = dict(
        parcela_id="test-123",
        cultivo="maiz",
        dias_siembra=30,
        tmax=38.0,
        tmin=22.0,
        humedad_rel=35.0,
        viento=2.5,
        radiacion=22.0,
        precipitacion=0.0,
    )

    async def test_retorna_200(self, client: AsyncClient, test_engine):
        r = await client.get("/api/balance_hidrico_manual", params=self.BASE_PARAMS)
        assert r.status_code == 200

    async def test_no_persiste(self, client: AsyncClient, test_engine):
        """El campo 'persistido' debe ser False en el endpoint manual."""
        r = await client.get("/api/balance_hidrico_manual", params=self.BASE_PARAMS)
        assert r.json()["persistido"] is False

    async def test_usa_penman_con_datos_completos(self, client: AsyncClient, test_engine):
        r = await client.get("/api/balance_hidrico_manual", params=self.BASE_PARAMS)
        assert r.json()["metodo_eto"] == "penman_monteith"

    async def test_fallback_hargreaves_sin_hr(self, client: AsyncClient, test_engine):
        """Sin HR/viento/radiación, debe caer a Hargreaves."""
        params = dict(parcela_id="x", cultivo="maiz", dias_siembra=30,
                      tmax=38.0, tmin=22.0)
        r = await client.get("/api/balance_hidrico_manual", params=params)
        assert r.status_code == 200
        assert r.json()["metodo_eto"] == "hargreaves"

    async def test_cultivo_invalido_retorna_400(self, client: AsyncClient, test_engine):
        """Cultivo fuera del catálogo → 400."""
        params = {**self.BASE_PARAMS, "cultivo": "trigo"}
        r = await client.get("/api/balance_hidrico_manual", params=params)
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint /api/kc/{cultivo}
# ─────────────────────────────────────────────────────────────────────────────

class TestCurvaKc:

    async def test_maiz_retorna_200(self, client: AsyncClient, test_engine):
        r = await client.get("/api/kc/maiz")
        assert r.status_code == 200

    async def test_ciclo_total_maiz(self, client: AsyncClient, test_engine):
        """Ciclo total Maíz = 25+40+45+30 = 140 días."""
        r = await client.get("/api/kc/maiz")
        assert r.json()["ciclo_total_dias"] == 140

    async def test_cuatro_etapas(self, client: AsyncClient, test_engine):
        r = await client.get("/api/kc/maiz")
        assert len(r.json()["etapas"]) == 4

    async def test_cultivo_invalido_retorna_400(self, client: AsyncClient, test_engine):
        r = await client.get("/api/kc/cebada")
        assert r.status_code == 400

    @pytest.mark.parametrize("cultivo", ["maiz", "frijol", "algodon", "uva", "chile"])
    async def test_todos_cultivos_validos(
        self, client: AsyncClient, cultivo: str, test_engine
    ):
        """Los 5 cultivos del catalogo oficial retornan 200."""
        r = await client.get(f"/api/kc/{cultivo}")
        assert r.status_code == 200, f"Fallo para cultivo: {cultivo}"


# =============================================================================
# TestFeedbackLoop — PATCH /recomendaciones/{id}/feedback
# Verifica que aceptar/modificar una recomendacion auto-inserta historial_riego
# (el dato que alimenta v_kpi_consumo y el KPI 8000->6000 m3/ha/ciclo).
# =============================================================================

class TestFeedbackLoop:
    """
    Flujo completo: FAO56 genera recomendacion -> agricultor acepta ->
    historial_riego se escribe automaticamente.
    """

    async def _generar_recomendacion(self, client, seeded) -> dict:
        """Helper: llama al endpoint FAO-56 y retorna el body de la recomendacion."""
        r = await client.get("/api/balance_hidrico", params={
            "parcela_id": str(seeded["id_parcela"]),
            "dias_siembra": 45,
            "fecha": str(seeded["fecha"]),
        })
        assert r.status_code == 200
        body = r.json()
        assert body["persistido"] is True
        return body

    async def _id_recomendacion(self, client, seeded) -> str:
        """Helper: genera recomendacion y devuelve su UUID."""
        body = await self._generar_recomendacion(client, seeded)
        # El endpoint retorna id_recomendacion en el body
        assert "id_recomendacion" in body, f"Claves: {list(body.keys())}"
        return body["id_recomendacion"]

    async def _contar_historial(self, engine, id_parcela) -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import select
        import models
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            res = await session.execute(
                select(models.HistorialRiego).where(
                    models.HistorialRiego.id_parcela == id_parcela
                )
            )
            return len(res.scalars().all())

    async def test_aceptada_inserta_historial(self, auth_client, seeded, test_engine):
        id_rec = await self._id_recomendacion(auth_client, seeded)
        antes = await self._contar_historial(test_engine, seeded["id_parcela"])

        r = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )
        assert r.status_code == 200

        despues = await self._contar_historial(test_engine, seeded["id_parcela"])
        assert despues == antes + 1, "Debe insertar exactamente 1 fila en historial_riego"

    async def test_modificada_inserta_historial_con_lamina_ejecutada(
        self, auth_client, seeded, test_engine
    ):
        id_rec = await self._id_recomendacion(auth_client, seeded)

        r = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "modificada", "lamina_ejecutada_mm": 40.0},
        )
        assert r.status_code == 200

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import select
        import models, uuid
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            res = await session.execute(
                select(models.HistorialRiego).where(
                    models.HistorialRiego.id_parcela == seeded["id_parcela"]
                )
            )
            rows = res.scalars().all()
        assert len(rows) == 1
        riego = rows[0]
        assert float(riego.lamina_mm) == pytest.approx(40.0, abs=0.01)
        assert float(riego.volumen_m3_ha) == pytest.approx(400.0, abs=0.1)

    async def test_ignorada_inserta_historial_con_volumen_cero(self, auth_client, seeded, test_engine):
        """
        'ignorada' debe escribir un registro en historial_riego con volumen = 0.
        Esto permite calcular tasa de adopcion real en el dashboard BI.
        El registro NO debe afectar propagar_balance_hidrico porque
        _estimar_humedad_actual filtra por volumen_m3_ha > 0.
        """
        id_rec = await self._id_recomendacion(auth_client, seeded)

        r = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "ignorada"},
        )
        assert r.status_code == 200

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import select
        import models
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            res = await session.execute(
                select(models.HistorialRiego).where(
                    models.HistorialRiego.id_parcela == seeded["id_parcela"]
                )
            )
            rows = res.scalars().all()

        assert len(rows) == 1, "ignorada debe insertar exactamente 1 fila en historial_riego"
        riego = rows[0]
        assert float(riego.volumen_m3_ha) == pytest.approx(0.0), "volumen debe ser 0 para no-riego"
        assert float(riego.lamina_mm) == pytest.approx(0.0), "lamina debe ser 0 para no-riego"
        assert riego.origen_decision == "sistema"

    async def test_feedback_doble_retorna_409(self, auth_client, seeded):
        id_rec = await self._id_recomendacion(auth_client, seeded)

        r1 = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )
        assert r1.status_code == 200

        r2 = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )
        assert r2.status_code == 409

    async def test_recomendacion_queda_marcada_aceptada(self, auth_client, seeded):
        id_rec = await self._id_recomendacion(auth_client, seeded)

        await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )

        r = await auth_client.get(f"/api/recomendaciones/{id_rec}")
        assert r.status_code == 200
        assert r.json()["aceptada"] == "aceptada"

    async def test_origen_decision_es_sistema(self, auth_client, seeded, test_engine):
        id_rec = await self._id_recomendacion(auth_client, seeded)
        await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import select
        import models
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            res = await session.execute(
                select(models.HistorialRiego).where(
                    models.HistorialRiego.id_parcela == seeded["id_parcela"]
                )
            )
            riego = res.scalars().first()
        assert riego.origen_decision == "sistema"

    async def test_volumen_coherente_con_lamina(self, auth_client, seeded, test_engine):
        """volumen_m3_ha debe ser lamina_mm * 10 (conversion FAO estandar)."""
        id_rec = await self._id_recomendacion(auth_client, seeded)

        r = await auth_client.patch(
            f"/api/recomendaciones/{id_rec}/feedback",
            json={"aceptada": "aceptada"},
        )
        assert r.status_code == 200

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy import select
        import models
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            res = await session.execute(
                select(models.HistorialRiego).where(
                    models.HistorialRiego.id_parcela == seeded["id_parcela"]
                )
            )
            riego = res.scalars().first()

        assert riego is not None
        assert riego.volumen_m3_ha is not None
        assert riego.lamina_mm is not None
        assert float(riego.volumen_m3_ha) == pytest.approx(float(riego.lamina_mm) * 10.0, rel=0.01), (
            f"volumen_m3_ha ({riego.volumen_m3_ha}) debe ser lamina_mm ({riego.lamina_mm}) * 10"
        )

