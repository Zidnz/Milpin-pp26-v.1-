// ==========================================
// ui_tabs.js: Controladores de Interfaz y Recomendaciones
// ==========================================

const API_BASE = "http://localhost:8000/api";

// Mapa cultivo → imagen servida por el backend en /static/imagenes/
// El backend (FastAPI en localhost:8000) monta la carpeta imagenes/ como static.
const _IMG_BASE = "http://localhost:8000/static/imagenes";
const CULTIVO_IMG = {
    "maiz":     `${_IMG_BASE}/maiz.jpeg`,
    "maíz":     `${_IMG_BASE}/maiz.jpeg`,
    "frijol":   `${_IMG_BASE}/frijoles.jpeg`,
    "frijoles": `${_IMG_BASE}/frijoles.jpeg`,
    "algodon":  `${_IMG_BASE}/algodon.jpeg`,
    "algodón":  `${_IMG_BASE}/algodon.jpeg`,
    "uva":      `${_IMG_BASE}/uvas.jpeg`,
    "uvas":     `${_IMG_BASE}/uvas.jpeg`,
    "chile":    `${_IMG_BASE}/chile.jpeg`,
    "chiles":   `${_IMG_BASE}/chile.jpeg`,
};

// ID de la parcela activa en el tab de Riego (necesario para feedback)
let _parcelaRiegoActual = null;
// ID de la recomendacion pendiente actual (para el PATCH de feedback)
let _recActualId = null;
// Lámina recomendada activa (para pre-llenar el panel de detalle)
let _laminaRecomendada = null;
// Decisión pendiente mientras el panel de detalle está abierto
let _decisionPendiente = null;

function _queryParcelasUsuario() {
    return window.MILPIN_AUTH?.getParcelasQuery?.() || "";
}

// Navegacion de pestanas
function cambiarPestana(event, tabId) {
    if (event) event.preventDefault();
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));

    const targetTab = document.getElementById(tabId);
    if (targetTab) {
        targetTab.style.display = "block";
        if (tabId === "tab-mapas") {
            setTimeout(async () => {
                await inicializarMapa();
                if (map) map.invalidateSize();
            }, 300);
        }
        if (tabId === "tab-costos") {
            _cargarParcelasEnSelect("select-parcela-riego");
        }
        if (tabId === "tab-bi") {
            BI.init();
        }
    }

    document.querySelectorAll(".nav-item").forEach(i => {
        const onclick = i.getAttribute("onclick");
        if (onclick && onclick.includes(tabId)) {
            i.classList.add("active");
        }
    });
}

// Abre el panel admin desde Config — mantiene Config como nav-item activo
function abrirPanelAdmin() {
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    const adminTab = document.getElementById("tab-admin");
    if (adminTab) adminTab.style.display = "block";
    // Mantener Config resaltado en el nav (admin es sub-vista de Config)
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(i => {
        const onclick = i.getAttribute("onclick") || "";
        if (onclick.includes("tab-ajustes")) i.classList.add("active");
    });
    if (window.ADMIN?.cargar) window.ADMIN.cargar();
}

document.addEventListener("DOMContentLoaded", () => {
    if (window.MILPIN_AUTH?.init) {
        window.MILPIN_AUTH.init();
    }
    if (window.ADMIN?.init) {
        window.ADMIN.init();
    }
    cambiarPestana(null, "tab-bi");
});

// Utilidad compartida: poblar un <select> con parcelas
async function _cargarParcelasEnSelect(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = '<option value="">— Selecciona una parcela —</option>';
    try {
        const res = await fetch(`${API_BASE}/parcelas${_queryParcelasUsuario()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const parcelas = await res.json();
        parcelas.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id_parcela;
            opt.textContent = p.nombre_parcela || `Parcela ${p.id_parcela.slice(0, 8)}`;
            sel.appendChild(opt);
        });
    } catch (err) {
        console.error("[MILPIN] Error cargando parcelas:", err);
    }
}

async function cargarParcelasAjustes() {
    const select = document.getElementById("ajustes-parcela-select");
    if (!select) return;
    select.innerHTML = '<option value="all">Todas las parcelas</option>';
    try {
        const res = await fetch(`${API_BASE}/parcelas${_queryParcelasUsuario()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const parcelas = await res.json();
        parcelas.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id_parcela;
            opt.textContent = p.nombre_parcela || `Parcela ${p.id_parcela.slice(0, 8)}`;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error("[MILPIN] Error cargando parcelas en ajustes:", err);
    }
}

// Modulo Mi Riego (FAO-56 + Feedback)
async function cargarRecomendacion(idParcela) {
    _parcelaRiegoActual = idParcela || null;
    _recActualId = null;

    if (!idParcela) {
        _riegoEstado("Selecciona una parcela para ver la recomendacion activa.");
        _riegoOcultarPaneles();
        return;
    }

    _riegoEstado("Consultando recomendacion...");
    _riegoOcultarPaneles();

    try {
        const res = await fetch(`${API_BASE}/recomendaciones/parcela/${idParcela}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        document.getElementById("riego-estado").style.display = "none";

        if (data.activa) {
            _renderizarCardActiva(data.activa);
        } else {
            document.getElementById("riego-sin-activa").style.display = "block";
        }

        if (data.historial && data.historial.length > 0) {
            _renderizarHistorial(data.historial);
        }

        // Mostrar siempre el botón de riego manual cuando hay parcela seleccionada
        const manualWrap = document.getElementById("riego-manual-wrap");
        if (manualWrap) manualWrap.style.display = "block";

    } catch (err) {
        console.error("[MILPIN] Error cargando recomendacion:", err);
        _riegoEstado("No se pudo conectar con el backend. Verifica localhost:8000.");
    }
}

// Consejos agronómicos por nivel de urgencia
const CONSEJOS_RIEGO = {
    critico:    "Riego urgente. El cultivo presenta estrés hídrico severo. Riega lo antes posible para evitar pérdida de rendimiento.",
    moderado:   "Riego en horas de la mañana para mayor eficiencia y menor evaporación.",
    preventivo: "El cultivo está bien hidratado. Monitorea las condiciones climáticas los próximos días antes de regar.",
};

function _renderizarCardActiva(rec) {
    _recActualId        = rec.id_recomendacion;
    _laminaRecomendada  = rec.lamina_recomendada_mm ?? null;
    _decisionPendiente  = null;

    // ── 1. Badge de urgencia ──────────────────────────────────────────────────
    const urgenciaLabel = { critico: "CRÍTICO", moderado: "MODERADO", preventivo: "PREVENTIVO" };
    const urgencia = rec.nivel_urgencia || "preventivo";

    const badgeEl = document.getElementById("riego-badge-urgencia");
    if (badgeEl) {
        badgeEl.textContent = urgenciaLabel[urgencia] || urgencia;
        badgeEl.className = "riego-badge riego-badge-" + urgencia;
    }

    // Propagar color de urgencia al bloque FAO-56 y al consejo agronómico
    const recBoxEl = document.querySelector(".rcard-rec");
    if (recBoxEl) recBoxEl.className = "rcard-rec rcard-rec--" + urgencia;

    const consejoEl = document.querySelector(".rcard-consejo");
    if (consejoEl) consejoEl.className = "rcard-consejo rcard-consejo--" + urgencia;

    // ── 2. Cabecera: nombre parcela + cultivo + fecha ─────────────────────────
    const parcelaNombre = rec.parcela_nombre
        || _getNombreParcelaDelSelect()
        || "Parcela";
    const parcelaCultivo = rec.cultivo || "—";
    const elNombre = document.getElementById("rcard-parcela-cultivo");
    if (elNombre) elNombre.textContent = `${parcelaNombre} · Cultivo: ${parcelaCultivo}`;

    const elFechaGen = document.getElementById("rcard-fecha-gen");
    if (elFechaGen && rec.fecha_generacion) {
        const dGen = new Date(rec.fecha_generacion);
        elFechaGen.textContent = "Fecha: " + dGen.toLocaleDateString("es-MX", {
            day: "numeric", month: "short", year: "numeric",
        });
    }

    // ── 3. Imágenes del cultivo (thumbnail cabecera + círculo suelo) ──────────
    const cultivoKey = (rec.cultivo || "").toLowerCase().trim();
    const imgSrc = CULTIVO_IMG[cultivoKey] || null;

    const thumbEl = document.getElementById("riego-cultivo-img");
    if (thumbEl) {
        thumbEl.src = imgSrc || "";
        thumbEl.alt = rec.cultivo || "";
        thumbEl.style.opacity = imgSrc ? "1" : "0";
    }

    const sueloImgEl = document.getElementById("rcard-suelo-img");
    if (sueloImgEl) {
        sueloImgEl.src = imgSrc || "";
        sueloImgEl.alt = rec.cultivo || "";
        const sueloThumb = sueloImgEl.parentElement;
        if (sueloThumb) sueloThumb.style.display = imgSrc ? "block" : "none";
    }

    // ── 4. Bloque principal: lámina + fecha sugerida ──────────────────────────
    const elLamina = document.getElementById("riego-lamina");
    if (elLamina) {
        elLamina.textContent = rec.lamina_recomendada_mm != null
            ? rec.lamina_recomendada_mm.toFixed(1) : "—";
    }

    const elFechaSug = document.getElementById("riego-fecha-sugerida");
    if (elFechaSug) {
        if (rec.fecha_riego_sugerida) {
            const d = new Date(rec.fecha_riego_sugerida + "T12:00:00");
            elFechaSug.textContent = d.toLocaleDateString("es-MX", {
                day: "numeric", month: "short", year: "numeric",
            });
        } else {
            elFechaSug.textContent = "—";
        }
    }

    // ── 5. Detalles del cálculo ───────────────────────────────────────────────
    const elEtc = document.getElementById("riego-etc");
    if (elEtc) elEtc.textContent = rec.etc_calculada != null
        ? rec.etc_calculada.toFixed(1) : "—";

    const elKc = document.getElementById("riego-kc");
    if (elKc) elKc.textContent = rec.kc != null
        ? Number(rec.kc).toFixed(2) : "—";

    const elEto = document.getElementById("riego-eto");
    if (elEto) elEto.textContent = rec.eto_referencia != null
        ? rec.eto_referencia.toFixed(1) : "—";

    const elPrecip = document.getElementById("riego-precip");
    if (elPrecip) elPrecip.textContent = rec.precipitacion_mm != null
        ? Number(rec.precipitacion_mm).toFixed(1) : "0.0";

    const elDeficit = document.getElementById("riego-deficit");
    if (elDeficit) elDeficit.textContent = rec.deficit_acumulado_mm != null
        ? rec.deficit_acumulado_mm.toFixed(1) : "—";

    // ── 6. Condiciones del suelo (barras de progreso) ─────────────────────────
    const humPct  = rec.humedad_actual_pct ?? null;
    const ccPct   = rec.cc_pct ?? null;

    // Calcular humedad como % de la capacidad de campo (0–100)
    let humRelPct = 0;
    if (humPct != null && ccPct != null && ccPct > 0) {
        humRelPct = Math.min(100, Math.round((humPct / ccPct) * 100));
    }

    const barHumEl  = document.getElementById("rcard-bar-humedad");
    const pctHumEl  = document.getElementById("rcard-pct-humedad");
    if (barHumEl)  barHumEl.style.width  = humRelPct + "%";
    if (pctHumEl)  pctHumEl.textContent  = humPct != null ? humRelPct + "%" : "—%";

    const barCcEl = document.getElementById("rcard-bar-cc");
    const pctCcEl = document.getElementById("rcard-pct-cc");
    if (barCcEl) barCcEl.style.width = "100%";
    if (pctCcEl) pctCcEl.textContent = "100%";

    // ── 7. Consejo agronómico ─────────────────────────────────────────────────
    const elConsejo = document.getElementById("rcard-consejo-texto");
    if (elConsejo) {
        elConsejo.textContent = CONSEJOS_RIEGO[rec.nivel_urgencia]
            || "Monitorea el estado hídrico del cultivo antes del próximo riego.";
    }

    // ── 8. Mostrar card + forecast ────────────────────────────────────────────
    document.getElementById("riego-card-activa").style.display = "block";

    const diasSiembra = rec.dias_siembra ?? rec.parametros_json?.dias_siembra;
    if (_parcelaRiegoActual && diasSiembra) {
        cargarForecast(_parcelaRiegoActual, diasSiembra);
    }
}

// Obtiene el nombre de la parcela seleccionada en el select (fallback si la API no lo retorna)
function _getNombreParcelaDelSelect() {
    const sel = document.getElementById("select-parcela-riego");
    if (!sel || !sel.value) return null;
    const opt = sel.options[sel.selectedIndex];
    return opt ? opt.textContent : null;
}

function _renderizarHistorial(historial) {
    const ESTADO = { aceptada: "Rego", modificada: "Modifico", ignorada: "No rego" };
    const CLASE = { aceptada: "riego-hist-ok", modificada: "riego-hist-mod", ignorada: "riego-hist-no" };

    document.getElementById("riego-historial-lista").innerHTML = historial.map(r => {
        const fecha = new Date(r.fecha_generacion).toLocaleDateString("es-MX", {
            day: "numeric",
            month: "short",
            year: "numeric",
        });
        const lamina = r.lamina_recomendada_mm != null ? r.lamina_recomendada_mm.toFixed(1) + " mm" : "—";
        const estado = ESTADO[r.aceptada] || r.aceptada;
        const claseEstado = CLASE[r.aceptada] || "";
        return `
        <div class="riego-hist-item">
            <div class="riego-hist-info">
                <span class="riego-hist-fecha">${fecha}</span>
                <span class="riego-hist-cultivo">${r.cultivo || "—"} · ${r.nivel_urgencia || "—"}</span>
            </div>
            <div class="riego-hist-derecha">
                <span class="riego-hist-lamina">${lamina}</span>
                <span class="riego-hist-estado ${claseEstado}">${estado}</span>
            </div>
        </div>`;
    }).join("");

    document.getElementById("riego-historial-wrap").style.display = "block";
}

function confirmarRiego(decision) {
    if (!_recActualId) return;

    _decisionPendiente = decision;

    const detail   = document.getElementById("riego-feedback-detail");
    const laminaRow = document.getElementById("rfb-lamina-row");
    const laminaEl  = document.getElementById("rfb-lamina");
    const notasEl   = document.getElementById("rfb-notas");
    const btnSi     = document.getElementById("btn-riego-si");
    const btnNo     = document.getElementById("btn-riego-no");

    // Limpiar estado previo
    if (notasEl) notasEl.value = "";

    if (decision === "aceptada") {
        // Mostrar campo de lámina pre-llenado con el valor recomendado
        if (laminaRow) laminaRow.style.display = "flex";
        if (laminaEl) laminaEl.value = _laminaRecomendada != null ? _laminaRecomendada : "";
        btnSi.style.opacity = "0.5";
        btnNo.style.opacity = "1";
    } else {
        // "ignorada": no tiene sentido pedir lámina
        if (laminaRow) laminaRow.style.display = "none";
        if (laminaEl)  laminaEl.value = "";
        btnNo.style.opacity = "0.5";
        btnSi.style.opacity = "1";
    }

    if (detail) detail.style.display = "flex";
}

async function _submitFeedback() {
    if (!_recActualId || !_decisionPendiente) return;

    const laminaEl  = document.getElementById("rfb-lamina");
    const notasEl   = document.getElementById("rfb-notas");
    const confirmBtn = document.getElementById("rfb-btn-confirmar");

    const notas = notasEl?.value?.trim() || null;

    // Determinar aceptada/modificada según si la lámina cambió
    let decision = _decisionPendiente;
    let lamina_ejecutada_mm = null;

    if (decision === "aceptada" && laminaEl?.value) {
        const laminaIngresada = parseFloat(laminaEl.value);
        if (!isNaN(laminaIngresada) && laminaIngresada > 0) {
            lamina_ejecutada_mm = laminaIngresada;
            if (_laminaRecomendada != null &&
                Math.abs(laminaIngresada - _laminaRecomendada) > 2.0) {
                decision = "modificada";
            }
        }
    }

    confirmBtn.disabled = true;
    confirmBtn.textContent = "Guardando...";

    const payload = { aceptada: decision };
    if (lamina_ejecutada_mm !== null) payload.lamina_ejecutada_mm = lamina_ejecutada_mm;
    if (notas)                         payload.notas = notas;

    try {
        const res = await fetch(`${API_BASE}/recomendaciones/${_recActualId}/feedback`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        _decisionPendiente = null;
        await cargarRecomendacion(_parcelaRiegoActual);

    } catch (err) {
        console.error("[MILPIN] Error enviando feedback:", err);
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Confirmar";
        alert("Error al guardar. Revisa la conexión con el backend.");
    }
}

function _cancelarFeedback() {
    _decisionPendiente = null;
    const detail = document.getElementById("riego-feedback-detail");
    if (detail) detail.style.display = "none";
    const btnSi = document.getElementById("btn-riego-si");
    const btnNo = document.getElementById("btn-riego-no");
    if (btnSi) btnSi.style.opacity = "1";
    if (btnNo) btnNo.style.opacity = "1";
}

async function calcularNuevaRecomendacion() {
    if (!_parcelaRiegoActual) return;
    const dias = parseInt(document.getElementById("input-dias-siembra").value, 10);
    if (!dias || dias < 1 || dias > 365) {
        alert("Ingresa un valor valido para dias desde siembra (1-365).");
        return;
    }

    const btn = document.querySelector(".riego-btn-calcular");
    btn.disabled = true;
    btn.textContent = "Calculando...";

    try {
        const url = `${API_BASE}/balance_hidrico?parcela_id=${_parcelaRiegoActual}&dias_siembra=${dias}`;
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        await cargarRecomendacion(_parcelaRiegoActual);
    } catch (err) {
        console.error("[MILPIN] Error calculando FAO-56:", err);
        alert(`Error al calcular: ${err.message}`);
        btn.disabled = false;
        btn.textContent = "Calcular recomendacion FAO-56";
    }
}

function _riegoEstado(msg) {
    const el = document.getElementById("riego-estado");
    el.querySelector("p").textContent = msg;
    el.style.display = "flex";
}

function _riegoOcultarPaneles() {
    ["riego-card-activa", "riego-sin-activa", "riego-historial-wrap", "riego-forecast-wrap"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
    });
    // Ocultar y resetear el form manual al cambiar de parcela
    const manualWrap = document.getElementById("riego-manual-wrap");
    if (manualWrap) manualWrap.style.display = "none";
    const manualForm   = document.getElementById("riego-manual-form");
    const manualToggle = document.getElementById("riego-manual-toggle");
    if (manualForm)   manualForm.style.display = "none";
    if (manualToggle) manualToggle.classList.remove("is-open");
}
function formatMXN(val) {
    return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(val);
}

function formatNum(val) {
    return new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 }).format(val);
}

// ── Módulo BI: reemplazado por bi_dashboard.js (vanilla JS + SVG + API real) ──
// Las funciones actualizarAnalisisBI, cosineSimilarity y las matrices
// hardcoded fueron eliminadas. El tab BI ahora usa BI.init() al abrirse.

// ── Módulo Forecast: Proyección FAO-56 a 7 días con Ridge Regression ─────────

async function cargarForecast(idParcela, diasSiembra) {
    const wrap      = document.getElementById('riego-forecast-wrap');
    const timeline  = document.getElementById('riego-forecast-timeline');
    const alertaEl  = document.getElementById('riego-forecast-alerta');
    const advertEl  = document.getElementById('riego-forecast-advertencia');
    const badgeEl   = document.getElementById('riego-forecast-metodo');

    if (!idParcela || !diasSiembra) {
        if (wrap) wrap.style.display = 'none';
        return;
    }

    if (wrap) wrap.style.display = 'block';
    if (timeline) timeline.innerHTML = '<div class="riego-forecast-loading">⏳ Calculando proyección Ridge…</div>';
    if (alertaEl) alertaEl.style.display = 'none';
    if (advertEl) advertEl.style.display = 'none';

    try {
        const url = `${API_BASE}/parcelas/${idParcela}/forecast?dias_siembra=${diasSiembra}&horizon=7`;
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        _renderForecast(data, timeline, alertaEl, advertEl, badgeEl);
    } catch (err) {
        console.error('[MILPÍN Forecast]', err);
        if (timeline) {
            timeline.innerHTML = `<div class="riego-forecast-error">
                ⚠️ No se pudo cargar la proyección.<br>
                <small>${err.message}</small>
            </div>`;
        }
    }
}

function _renderForecast(data, timeline, alertaEl, advertEl, badgeEl) {
    const dias          = data.dias_proyectados || [];
    const diaRiego      = data.dia_riego_estimado;
    const fechaRiego    = data.fecha_riego_estimada;
    const incertidumbre = data.incertidumbre_dias ?? 1;
    const metodo        = data.metodo_eto || 'ridge_regression';

    // Badge del método
    if (badgeEl) {
        const esML = metodo === 'ridge_regression';
        badgeEl.textContent  = esML ? '🤖 Ridge ML' : '📊 Media 14d';
        badgeEl.className    = 'riego-forecast-badge ' +
            (esML ? 'riego-forecast-badge--ml' : 'riego-forecast-badge--fallback');
    }

    // Alerta de riego estimado
    if (alertaEl) {
        if (diaRiego !== null && diaRiego !== undefined) {
            const fechaFmt = fechaRiego
                ? new Date(fechaRiego + 'T12:00:00').toLocaleDateString(
                    'es-MX', { weekday: 'long', day: 'numeric', month: 'long' })
                : `en ${diaRiego} días`;
            alertaEl.innerHTML =
                `💧 <strong>Próximo riego estimado: ${fechaFmt}</strong>` +
                `<span class="riego-forecast-incert">&nbsp;±${incertidumbre} días</span>`;
            alertaEl.style.display = 'block';
            alertaEl.className = 'riego-forecast-alerta riego-forecast-alerta--activa';
        } else {
            alertaEl.innerHTML = '✓ Sin déficit crítico proyectado en los próximos 7 días.';
            alertaEl.style.display = 'block';
            alertaEl.className = 'riego-forecast-alerta riego-forecast-alerta--ok';
        }
    }

    // Timeline día a día
    if (timeline && dias.length) {
        const DIAS_ES = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
        timeline.innerHTML = dias.map(d => {
            const fecha      = new Date(d.fecha + 'T12:00:00');
            const diaSemana  = DIAS_ES[fecha.getDay()];
            const diaNum     = fecha.getDate();
            const esRiego    = diaRiego !== null && d.dia === diaRiego;
            // Normalizar barra: 25 mm déficit = barra llena
            const deficitPct = Math.min(100, (d.deficit_mm / 25) * 100);
            const barColor   = d.deficit_mm > 20 ? '#E63946'
                             : d.deficit_mm > 10 ? '#E8C27D'
                             : '#7BB395';

            return `<div class="riego-fc-dia${esRiego ? ' riego-fc-dia--riego' : ''}">
                <div class="riego-fc-fecha">
                    <span class="riego-fc-ds">${diaSemana}</span>
                    <span class="riego-fc-dn">${diaNum}</span>
                </div>
                <div class="riego-fc-barra-wrap" title="Déficit: ${d.deficit_mm} mm">
                    <div class="riego-fc-barra"
                         style="height:${deficitPct}%;background:${barColor}"></div>
                </div>
                <div class="riego-fc-vals">
                    <span class="riego-fc-etc" title="ETc estimada">~${d.etc_mm} mm</span>
                    <span class="riego-fc-deficit" style="color:${barColor}">${d.deficit_mm} mm</span>
                </div>
                ${esRiego ? '<div class="riego-fc-pin">💧 riego</div>' : ''}
            </div>`;
        }).join('');
    }

    // Advertencia de fallback o datos insuficientes
    if (advertEl && data.advertencia) {
        advertEl.textContent  = `ℹ️ ${data.advertencia}`;
        advertEl.style.display = 'block';
    }
}

function _iconSi() { return '✓'; }
function _iconNo() { return '✗'; }

// ── Riego manual ──────────────────────────────────────────────────────────────

function toggleRiegoManual() {
    const form     = document.getElementById("riego-manual-form");
    const toggle   = document.getElementById("riego-manual-toggle");
    const feedback = document.getElementById("riego-manual-feedback");
    if (!form || !toggle) return;

    const abriendo = form.style.display === "none";

    if (abriendo) {
        form.style.display = "block";
        toggle.classList.add("is-open");
        const fechaInput = document.getElementById("manual-fecha");
        if (fechaInput && !fechaInput.value) {
            fechaInput.value = new Date().toISOString().split("T")[0];
        }
    } else {
        form.style.display = "none";
        toggle.classList.remove("is-open");
        if (feedback) { feedback.style.display = "none"; feedback.textContent = ""; }
    }
}

async function registrarRiegoManual() {
    if (!_parcelaRiegoActual) {
        alert("Selecciona una parcela primero.");
        return;
    }

    const fechaEl    = document.getElementById("manual-fecha");
    const laminaEl   = document.getElementById("manual-lamina");
    const metodoEl   = document.getElementById("manual-metodo");
    const notasEl    = document.getElementById("manual-notas");
    const submitBtn  = document.getElementById("btn-manual-submit");

    if (!fechaEl?.value) {
        _mostrarFeedbackManual("Indica la fecha del riego.", "err");
        return;
    }
    const lamina = parseFloat(laminaEl?.value);
    if (!lamina || lamina <= 0 || lamina > 300) {
        _mostrarFeedbackManual("Ingresa una lámina válida entre 1 y 300 mm.", "err");
        return;
    }
    if (!metodoEl?.value) {
        _mostrarFeedbackManual("Selecciona el método de riego.", "err");
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Guardando...";

    // lamina (mm) × 10 = m³/ha  (conversión estándar FAO)
    const volumen_m3_ha = Math.round(lamina * 10 * 100) / 100;

    const payload = {
        id_parcela:      _parcelaRiegoActual,
        fecha_riego:     fechaEl.value,
        lamina_mm:       lamina,
        volumen_m3_ha:   volumen_m3_ha,
        metodo_riego:    metodoEl.value,
        origen_decision: "manual",
        observaciones:   notasEl?.value?.trim() || null,
    };

    try {
        const res = await fetch(`${API_BASE}/riego`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const costoMXN = (volumen_m3_ha * 1.68)
            .toLocaleString("es-MX", { maximumFractionDigits: 0 });
        _mostrarFeedbackManual(
            `✓ Riego guardado · ${lamina} mm · ` +
            `${volumen_m3_ha.toLocaleString("es-MX")} m³/ha · ` +
            `costo estimado $${costoMXN} MXN`,
            "ok"
        );

        laminaEl.value = "";
        metodoEl.value = "";
        if (notasEl) notasEl.value = "";

        // Recargar historial — el nuevo riego actualiza propagar_balance_hidrico
        await cargarRecomendacion(_parcelaRiegoActual);

    } catch (err) {
        console.error("[MILPÍN] Error registrando riego manual:", err);
        _mostrarFeedbackManual(`Error al guardar: ${err.message}`, "err");
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Guardar riego";
    }
}

function _mostrarFeedbackManual(msg, tipo) {
    const el = document.getElementById("riego-manual-feedback");
    if (!el) return;
    el.textContent   = msg;
    el.className     = `riego-manual-feedback ${tipo}`;
    el.style.display = "block";
}
