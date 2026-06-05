// ==========================================
// ui_tabs.js: Controladores de Interfaz y Recomendaciones
// ==========================================

const API_BASE = "https://milpin-pp26-v1-production.up.railway.app/api";

// Mapa cultivo → imagen local en frontend/imagenes/
const _IMG_BASE = "imagenes";
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
    _cerrarAlertasPanel();
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
        if (tabId === "tab-ml") {
            _cargarParcelasEnSelect("select-parcela-ml");
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
async function _fetchWithRetry(url, intentos = 3, delayMs = 800) {
    for (let i = 0; i < intentos; i++) {
        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res;
        } catch (err) {
            const esRed = err instanceof TypeError || (err.message || "").includes("ERR_NETWORK");
            if (esRed && i < intentos - 1) {
                await new Promise(r => setTimeout(r, delayMs * (i + 1)));
                continue;
            }
            throw err;
        }
    }
}

async function _cargarParcelasEnSelect(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = '<option value="">Cargando parcelas…</option>';
    sel.disabled = true;
    try {
        const res = await _fetchWithRetry(`${API_BASE}/parcelas${_queryParcelasUsuario()}`);
        const parcelas = await res.json();
        sel.innerHTML = '<option value="">— Selecciona una parcela —</option>';
        parcelas.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id_parcela;
            opt.textContent = p.nombre_parcela || `Parcela ${p.id_parcela.slice(0, 8)}`;
            sel.appendChild(opt);
        });
    } catch (err) {
        console.error("[MILPIN] Error cargando parcelas:", err);
        sel.innerHTML = '<option value="">⚠ Sin conexión — reintenta</option>';
    } finally {
        sel.disabled = false;
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
        _mostrarSubtabNav(false);
        return;
    }
    _mostrarSubtabNav(true);

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
    const humPct      = rec.humedad_actual_pct ?? null;
    const ccPct       = rec.cc_pct ?? null;
    const humEstimada = !!rec.humedad_estimada;

    // Calcular humedad como % de la capacidad de campo (0–100)
    let humRelPct = 0;
    if (humPct != null && ccPct != null && ccPct > 0) {
        humRelPct = Math.min(100, Math.round((humPct / ccPct) * 100));
    }

    const barHumEl  = document.getElementById("rcard-bar-humedad");
    const pctHumEl  = document.getElementById("rcard-pct-humedad");
    if (barHumEl) barHumEl.style.width = humRelPct + "%";
    if (pctHumEl) {
        // humedad_estimada = true → rec antigua sin balance acumulado propagado;
        // se muestra el punto medio CC+PMP como aproximación con prefijo "~".
        pctHumEl.textContent = humPct != null
            ? (humEstimada ? `~${humRelPct}%` : `${humRelPct}%`)
            : "—%";
        pctHumEl.title = humEstimada
            ? "Valor estimado (punto medio CC+PMP). Recalcula para obtener la humedad real."
            : "";
    }

    const barCcEl = document.getElementById("rcard-bar-cc");
    const pctCcEl = document.getElementById("rcard-pct-cc");
    // La barra de CC siempre ocupa el 100% del ancho (es el techo de referencia).
    // El texto muestra el valor real de capacidad de campo en % vol/vol
    // leído desde la BD, no un hardcode.
    if (barCcEl) barCcEl.style.width = "100%";
    if (pctCcEl) pctCcEl.textContent = ccPct != null ? `${ccPct.toFixed(1)}%` : "—%";

    // ── 7. Consejo agronómico ─────────────────────────────────────────────────
    const elConsejo = document.getElementById("rcard-consejo-texto");
    if (elConsejo) {
        elConsejo.textContent = CONSEJOS_RIEGO[rec.nivel_urgencia]
            || "Monitorea el estado hídrico del cultivo antes del próximo riego.";
    }

    // ── 7b. Banner de incertidumbre (Fase 3) ──────────────────────────────────
    _renderizarIncertidumbre(rec);

    // ── 8. Mostrar card + forecast ────────────────────────────────────────────
    // XGBoost se muestra en el tab ML (módulo propio), no aquí.
    document.getElementById("riego-card-activa").style.display = "block";

    const diasSiembra = rec.dias_siembra ?? rec.parametros_json?.dias_siembra;
    if (_parcelaRiegoActual && diasSiembra) {
        cargarForecast(_parcelaRiegoActual, diasSiembra);
    }
}

/**
 * Renderiza (o actualiza) el banner de incertidumbre debajo de la card de riego.
 *
 * Tres niveles visuales:
 *   alta  → fondo naranja/rojo, requiere validación humana
 *   media → fondo amarillo, revisar si el contexto cambia
 *   baja  → fondo verde suave, confianza razonable (puede ocultarse)
 *
 * El banner se crea dinámicamente si no existe; se elimina si la
 * recomendación no trae datos de incertidumbre (compatibilidad con
 * respuestas antiguas del backend).
 *
 * (OECD 2019; UNESCO 2021: comunicar límites sin generar rechazo ni garantía.)
 */
function _renderizarIncertidumbre(rec) {
    const CONTENEDOR_ID = "rcard-incertidumbre";
    const card = document.getElementById("riego-card-activa");
    if (!card) return;

    // Eliminar banner previo si existe
    const previo = document.getElementById(CONTENEDOR_ID);
    if (previo) previo.remove();

    // Si el backend no envía datos de incertidumbre (respuesta antigua), no mostrar nada
    const nivel   = rec.nivel_incertidumbre;
    const mensaje = rec.mensaje_incertidumbre;
    if (!nivel || !mensaje) return;

    // No mostrar el banner de nivel "baja" — es la situación normal y añadir
    // texto extra podría interpretarse como garantía implícita.
    if (nivel === "baja") return;

    const ESTILOS = {
        alta: {
            bg:     "#fff3cd",
            borde:  "#e6a817",
            icono:  "⚠️",
            etiq:   "Validación recomendada",
            color:  "#7a4f00",
        },
        media: {
            bg:     "#e8f4fd",
            borde:  "#5b9bd5",
            icono:  "ℹ️",
            etiq:   "Dato orientativo",
            color:  "#1a4971",
        },
    };

    const s = ESTILOS[nivel] || ESTILOS["media"];

    const banner = document.createElement("div");
    banner.id = CONTENEDOR_ID;
    banner.style.cssText = [
        `background:${s.bg}`,
        `border-left:4px solid ${s.borde}`,
        `color:${s.color}`,
        "border-radius:6px",
        "padding:10px 14px",
        "margin:10px 0 4px 0",
        "font-size:0.88rem",
        "line-height:1.5",
    ].join(";");

    // Cabecera: icono + etiqueta de nivel
    const cab = document.createElement("div");
    cab.style.cssText = "font-weight:600;margin-bottom:4px;";
    cab.textContent = `${s.icono} ${s.etiq}`;
    banner.appendChild(cab);

    // Mensaje en lenguaje natural
    const txt = document.createElement("div");
    txt.textContent = mensaje;
    banner.appendChild(txt);

    // Indicador adicional: "requiere validación humana"
    if (rec.requiere_validacion_humana) {
        const nota = document.createElement("div");
        nota.style.cssText = "margin-top:6px;font-style:italic;font-size:0.83rem;";
        nota.textContent = "Esta recomendación requiere revisión de un técnico antes de ejecutarse.";
        banner.appendChild(nota);
    }

    // Insertar justo después del bloque de consejo agronómico, antes del botón de feedback
    const consejoEl = document.querySelector(".rcard-consejo");
    if (consejoEl && consejoEl.parentNode) {
        consejoEl.parentNode.insertBefore(banner, consejoEl.nextSibling);
    } else {
        // Fallback: al final de la card
        card.appendChild(banner);
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
            headers: { "Content-Type": "application/json", ...MILPIN_AUTH.getAuthHeader() },
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
    if (timeline) timeline.innerHTML = '<div class="riego-forecast-loading"><span class="bi-spinner"></span> Calculando proyección…</div>';
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
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                No se pudo cargar la proyección.<br>
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

    // SVG icons reutilizables
    const _svgDrop  = `<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>`;
    const _svgCheck = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="15" height="15"><polyline points="20 6 9 17 4 12"/></svg>`;
    const _svgInfo  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

    // Badge del método
    if (badgeEl) {
        const esML = metodo === 'ridge_regression';
        badgeEl.innerHTML = esML
            ? `${_svgDrop} Ridge ML`
            : `${_svgInfo} Media 14d`;
        badgeEl.className = 'riego-forecast-badge ' +
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
                `<span class="riego-fc-alerta-icon">${_svgDrop}</span>` +
                `<span><strong>Próximo riego estimado: ${fechaFmt}</strong>` +
                `<span class="riego-forecast-incert">&nbsp;±${incertidumbre} días</span></span>`;
            alertaEl.style.display = 'flex';
            alertaEl.className = 'riego-forecast-alerta riego-forecast-alerta--activa';
        } else {
            alertaEl.innerHTML =
                `<span class="riego-fc-alerta-icon riego-fc-alerta-icon--ok">${_svgCheck}</span>` +
                `<span>Sin déficit crítico proyectado en los próximos 7 días.</span>`;
            alertaEl.style.display = 'flex';
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
            const deficitPct = Math.min(100, (d.deficit_mm / 25) * 100);
            const barColor   = d.deficit_mm > 20 ? '#E63946'
                             : d.deficit_mm > 10 ? '#E8A23A'
                             : '#2E9E5B';
            const barGradient = d.deficit_mm > 20
                ? 'linear-gradient(to top, #E63946, #ff6b6b)'
                : d.deficit_mm > 10
                ? 'linear-gradient(to top, #E8A23A, #f5c87a)'
                : 'linear-gradient(to top, #2E9E5B, #7BB395)';

            return `<div class="riego-fc-dia${esRiego ? ' riego-fc-dia--riego' : ''}">
                <div class="riego-fc-fecha">
                    <span class="riego-fc-ds">${diaSemana}</span>
                    <span class="riego-fc-dn">${diaNum}</span>
                </div>
                <div class="riego-fc-barra-wrap" title="Déficit acumulado: ${d.deficit_mm} mm">
                    <div class="riego-fc-barra"
                         style="height:${deficitPct}%;background:${barGradient}"></div>
                </div>
                <div class="riego-fc-vals">
                    <span class="riego-fc-etc">−${d.etc_mm} mm</span>
                    <span class="riego-fc-deficit" style="color:${barColor}">${d.deficit_mm} mm</span>
                </div>
                ${esRiego ? `<div class="riego-fc-pin">${_svgDrop} Riego</div>` : ''}
            </div>`;
        }).join('');
    }

    // Advertencia de fallback o datos insuficientes
    if (advertEl && data.advertencia) {
        advertEl.innerHTML = `${_svgInfo} ${data.advertencia}`;
        advertEl.style.display = 'block';
    }
}

function _iconSi() { return '✓'; }
function _iconNo() { return '✗'; }

// ── Resumen multi-parcela (panel de entrada del tab Riego) ────────────────
// Muestra el estado hídrico de TODAS las parcelas de un vistazo antes de
// que el usuario seleccione una específica. Semáforo rojo/ámbar/verde,
// ordenado por urgencia. Click en una fila → carga la recomendación.

const _RRESUMEN_CFG = {
    critico:    { color: '#E65C5C', bg: 'rgba(230,89,89,.07)',   dot: '#E65C5C', label: '🔴 Urgente'   },
    moderado:   { color: '#F5A623', bg: 'rgba(245,166,35,.07)',  dot: '#F5A623', label: '🟡 Pronto'    },
    preventivo: { color: '#2E9E5B', bg: 'rgba(46,158,91,.06)',   dot: '#2E9E5B', label: '🟢 OK'        },
};
const _RRESUMEN_ORDER = { critico: 0, moderado: 1, preventivo: 2 };

async function cargarResumenParcelas() {
    const wrap = document.getElementById('riego-resumen-wrap');
    if (!wrap) return;

    wrap.innerHTML = '<div class="rresumen-loading">Cargando estado de parcelas…</div>';

    try {
        const res = await fetch(`${API_BASE}/parcelas${_queryParcelasUsuario()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const parcelas = await res.json();

        if (!parcelas.length) {
            wrap.innerHTML = '';
            return;
        }

        // Fetch rec activa de cada parcela en paralelo
        const items = await Promise.all(parcelas.map(async p => {
            try {
                const r = await fetch(`${API_BASE}/recomendaciones/parcela/${p.id_parcela}`);
                if (!r.ok) return { parcela: p, activa: null };
                const d = await r.json();
                return { parcela: p, activa: d.activa || null };
            } catch (_) {
                return { parcela: p, activa: null };
            }
        }));

        _renderResumenParcelas(items, wrap);
    } catch (err) {
        console.error('[MILPÍN] Error cargando resumen parcelas:', err);
        wrap.innerHTML = `<div class="rresumen-error">No se pudo cargar el resumen: ${err.message}</div>`;
    }
}

function _renderResumenParcelas(items, wrap) {
    // Ordenar por urgencia; sin rec activa va al final
    const sorted = [...items].sort((a, b) =>
        (_RRESUMEN_ORDER[a.activa?.nivel_urgencia] ?? 3) -
        (_RRESUMEN_ORDER[b.activa?.nivel_urgencia] ?? 3)
    );

    // ── Conteo KPIs ────────────────────────────────────────────────────────────
    const nCritico    = items.filter(i => i.activa?.nivel_urgencia === 'critico').length;
    const nModerado   = items.filter(i => i.activa?.nivel_urgencia === 'moderado').length;
    const nPreventivo = items.filter(i => i.activa?.nivel_urgencia === 'preventivo').length;

    // Actualizar badge de la campana (urgencias + moderadas = requieren atención)
    _actualizarBadgeAlertas(nCritico, nModerado);

    const kpisHtml = `
    <div class="rresumen-kpis">
        <div class="rresumen-kpi-card rresumen-kpi-card--critico">
            <span class="rresumen-kpi-num">${nCritico}</span>
            <span class="rresumen-kpi-label">Crítico</span>
        </div>
        <div class="rresumen-kpi-card rresumen-kpi-card--moderado">
            <span class="rresumen-kpi-num">${nModerado}</span>
            <span class="rresumen-kpi-label">Moderado</span>
        </div>
        <div class="rresumen-kpi-card rresumen-kpi-card--preventivo">
            <span class="rresumen-kpi-num">${nPreventivo}</span>
            <span class="rresumen-kpi-label">Preventivo</span>
        </div>
    </div>`;

    // ── Filas de parcelas ──────────────────────────────────────────────────────
    const filas = sorted.map(({ parcela, activa }) => {
        const urgencia = activa?.nivel_urgencia || null;
        const cfg      = _RRESUMEN_CFG[urgencia];
        const cultivo  = activa?.cultivo || activa?.parametros_json?.cultivo || '';
        const deficit  = activa?.deficit_acumulado_mm != null
            ? `${Math.round(activa.deficit_acumulado_mm)} mm` : '—';
        const nombre   = parcela.nombre_parcela || `Parcela ${parcela.id_parcela.slice(0, 8)}`;

        let fechaLabel = '—';
        if (activa?.fecha_riego_sugerida) {
            const d   = new Date(activa.fecha_riego_sugerida + 'T12:00:00');
            const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
            const diff = Math.round((d - hoy) / 86400000);
            if      (diff <= 0)  fechaLabel = 'HOY';
            else if (diff === 1) fechaLabel = 'MAÑANA';
            else                 fechaLabel = d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
        }

        // Sin rec activa — fila neutra, no interactiva
        if (!cfg) {
            return `
            <div class="rresumen-fila rresumen-fila--vacia">
                <div class="rresumen-dot" style="background:#C7BFAF"></div>
                <div class="rresumen-info">
                    <span class="rresumen-nombre">${nombre}</span>
                    <span class="rresumen-cultivo"> · sin recomendación</span>
                </div>
                <div class="rresumen-met"><span class="rresumen-met-label">Déficit</span><strong>—</strong></div>
                <div class="rresumen-met"><span class="rresumen-met-label">Próximo riego</span><strong>—</strong></div>
            </div>`;
        }

        return `
        <div class="rresumen-fila"
             style="border-left:4px solid ${cfg.color};background:${cfg.bg}"
             onclick="seleccionarParcelaResumen('${parcela.id_parcela}')"
             title="Ver recomendación de ${nombre}">
            <div class="rresumen-dot" style="background:${cfg.dot}"></div>
            <div class="rresumen-info">
                <span class="rresumen-nombre">${nombre}</span>
                ${cultivo ? `<span class="rresumen-cultivo"> · ${cultivo}</span>` : ''}
            </div>
            <div class="rresumen-badge" style="color:${cfg.color}">${cfg.label}</div>
            <div class="rresumen-met">
                <span class="rresumen-met-label">Déficit</span>
                <strong style="color:${cfg.color}">${deficit}</strong>
            </div>
            <div class="rresumen-met">
                <span class="rresumen-met-label">Próximo riego</span>
                <strong>${fechaLabel}</strong>
            </div>
            <span class="rresumen-arrow">›</span>
        </div>`;
    }).join('');

    wrap.innerHTML = `
    <div class="rresumen-card">
        ${kpisHtml}
        <div class="rresumen-lista">${filas}</div>
    </div>`;
}

function seleccionarParcelaResumen(idParcela) {
    // Cerrar el drawer antes de navegar a la parcela
    _cerrarAlertasPanel();
    const sel = document.getElementById('select-parcela-riego');
    if (sel) sel.value = idParcela;
    cargarRecomendacion(idParcela);
    // Scroll suave al detalle de la recomendación
    setTimeout(() => {
        const estado = document.getElementById('riego-estado');
        if (estado) estado.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
}

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
            headers: { "Content-Type": "application/json", ...MILPIN_AUTH.getAuthHeader() },
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

        // Recargar historial y actualizar resumen tras registrar riego
        await cargarRecomendacion(_parcelaRiegoActual);
        cargarResumenParcelas();
        // Si el tab de historial está activo, refrescarlo también
        if (_riegoTabActivo === 'historial') cargarHistorialRiego(_parcelaRiegoActual);

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

// ── ML · Helpers de visualización ────────────────────────────────────────────

/**
 * Devuelve el SVG del ícono según el nivel de urgencia.
 *   critico    → triángulo de alerta rojo
 *   moderado   → reloj ámbar
 *   preventivo → escudo verde con check
 */
function _xgbUrgenciaIcon(nivel) {
    const n = (nivel || "").toLowerCase();
    if (n === "critico") {
        return `<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M24 6L44 40H4L24 6Z" fill="rgba(230,57,70,0.15)"
                  stroke="#e63946" stroke-width="2.5" stroke-linejoin="round"/>
            <rect x="22.5" y="18" width="3" height="12" rx="1.5" fill="#e63946"/>
            <circle cx="24" cy="34" r="2" fill="#e63946"/>
        </svg>`;
    }
    if (n === "moderado") {
        return `<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="24" cy="24" r="18" fill="rgba(255,185,50,0.13)"
                    stroke="#d4820a" stroke-width="2.5"/>
            <path d="M24 14v10l6 4" stroke="#d4820a" stroke-width="2.8"
                  stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
    }
    // preventivo (default)
    return `<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M24 4L8 11v13c0 9.5 6.8 18.4 16 21 9.2-2.6 16-11.5 16-21V11L24 4Z"
              fill="rgba(82,183,136,0.13)" stroke="#52b788" stroke-width="2.5"
              stroke-linejoin="round"/>
        <path d="M16 24l6 6 10-10" stroke="#52b788" stroke-width="2.8"
              stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
}

/**
 * Genera el SVG del gauge semicircular para el riesgo de estrés.
 * riesgo: 0.0 – 1.0
 * Arco de r=72, longitud total ≈ 226.2 px.
 */
function _xgbGaugeSVG(riesgo) {
    const R   = 72;
    const CX  = 95, CY = 97;
    const ARC = Math.PI * R;
    const v   = Math.min(Math.max(riesgo ?? 0, 0), 1);
    const pct = Math.round(v * 100);
    const fill = v * ARC;

    const color = v < 0.40 ? "#52b788"
                : v < 0.70 ? "#d4820a"
                :             "#e63946";

    return `<svg class="xgb-gauge-svg" viewBox="0 0 190 112"
                 aria-label="Riesgo de estrés ${pct}%">
        <!-- Pista de fondo -->
        <path d="M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}"
              class="xgb-gauge-track"/>
        <!-- Relleno coloreado -->
        <path d="M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}"
              class="xgb-gauge-fill"
              stroke="${color}"
              stroke-dasharray="${fill.toFixed(1)} ${ARC.toFixed(1)}"/>
        <!-- Porcentaje -->
        <text x="${CX}" y="${CY - 14}" text-anchor="middle"
              class="xgb-gauge-pct" fill="${color}">${pct}%</text>
        <text x="${CX}" y="${CY + 5}" text-anchor="middle"
              class="xgb-gauge-sub" fill="var(--secondary-text)">riesgo de estrés</text>
        <!-- Marcas de escala -->
        <text x="${CX - R - 6}" y="${CY + 15}" text-anchor="middle"
              class="xgb-gauge-mark">0</text>
        <text x="${CX}" y="${CY - R - 8}" text-anchor="middle"
              class="xgb-gauge-mark">50%</text>
        <text x="${CX + R + 6}" y="${CY + 15}" text-anchor="middle"
              class="xgb-gauge-mark">100</text>
    </svg>`;
}

/** Textos descriptivos por nivel de urgencia. */
const _URGENCIA_DESC = {
    critico:    "Riego urgente — déficit hídrico crítico detectado.",
    moderado:   "Monitorear — déficit moderado, riego próximo recomendado.",
    preventivo: "Sin urgencia — humedad dentro del rango óptimo.",
};


/**
 * SVG gauge circular para "Confianza del modelo".
 * prob: 0.0 – 1.0
 */
function _mlConfidenceGaugeSVG(prob) {
    const r = 36, cx = 50, cy = 50;
    const circumference = 2 * Math.PI * r;
    const v   = Math.min(Math.max(prob ?? 0, 0), 1);
    const pct = Math.round(v * 100);
    const offset = circumference * (1 - v);
    const color = v >= 0.75 ? '#52b788' : v >= 0.50 ? '#d4820a' : '#e63946';
    return `<svg class="ml-conf-svg" viewBox="0 0 100 100" aria-label="Confianza ${pct}%">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
                stroke="var(--border-card,#e5e9f0)" stroke-width="11"/>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
                stroke="${color}" stroke-width="11"
                stroke-dasharray="${circumference.toFixed(2)}"
                stroke-dashoffset="${offset.toFixed(2)}"
                stroke-linecap="round"
                transform="rotate(-90 ${cx} ${cy})"
                style="transition:stroke-dashoffset 0.45s ease"/>
        <text x="${cx}" y="${cy + 6}" text-anchor="middle"
              font-size="18" font-weight="800" font-family="Poppins,sans-serif"
              fill="${color}">${pct}%</text>
    </svg>`;
}

/**
 * SVG donut completo para "Riesgo de estrés hídrico".
 * riesgo: 0.0 – 1.0
 */
function _mlDonutSVG(riesgo) {
    const r = 54, cx = 80, cy = 80;
    const circumference = 2 * Math.PI * r;
    const v   = Math.min(Math.max(riesgo ?? 0, 0), 1);
    const pct = Math.round(v * 100);
    const offset = circumference * (1 - v);
    const color = v >= 0.75 ? '#e63946' : v >= 0.30 ? '#d4820a' : '#52b788';
    const label = v >= 0.75 ? 'Riesgo alto' : v >= 0.30 ? 'Riesgo medio' : 'Riesgo bajo';
    return `<svg class="ml-donut-svg" viewBox="0 0 160 160" aria-label="${label} ${pct}%">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
                stroke="var(--border-card,#e5e9f0)" stroke-width="17"/>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
                stroke="${color}" stroke-width="17"
                stroke-dasharray="${circumference.toFixed(2)}"
                stroke-dashoffset="${offset.toFixed(2)}"
                stroke-linecap="round"
                transform="rotate(-90 ${cx} ${cy})"
                style="transition:stroke-dashoffset 0.45s ease"/>
        <text x="${cx}" y="${cy - 4}" text-anchor="middle"
              font-size="30" font-weight="800" font-family="Poppins,sans-serif"
              fill="${color}">${pct}%</text>
        <text x="${cx}" y="${cy + 18}" text-anchor="middle"
              font-size="11" font-family="Poppins,sans-serif"
              fill="var(--secondary-text,#6b7a8d)">${label}</text>
    </svg>`;
}

// ── ML · Predicción XGBoost ───────────────────────────────────────────────────
/**
 * Carga la predicción XGBoost para la parcela activa y renderiza el panel.
 * Llamada automáticamente junto con cargarForecast() al mostrar una recomendación.
 */
async function cargarPrediccionXGB(idParcela) {
    const wrap = document.getElementById("riego-xgb-wrap");
    if (!wrap) return;

    wrap.style.display = "block";

    const reqEl     = document.getElementById("xgb-requiere");
    const probEl    = document.getElementById("xgb-prob");
    const laminaEl  = document.getElementById("xgb-lamina");   // fix: faltaba declaración
    const badgeEl   = document.getElementById("xgb-algoritmo-badge");
    const urgCard   = document.getElementById("xgb-urgencia-card");
    const urgIcon   = document.getElementById("xgb-urgencia-icon");
    const urgNivel  = document.getElementById("xgb-urgencia-nivel");
    const urgDesc   = document.getElementById("xgb-urgencia-desc");
    const gaugeWrap = document.getElementById("xgb-gauge-wrap");

    // Estado de carga inicial
    if (reqEl)     { reqEl.textContent = "…"; reqEl.className = "riego-xgb-badge riego-xgb-badge--loading"; }
    if (probEl)    probEl.textContent  = "…";
    if (laminaEl)  laminaEl.textContent = "…";
    if (gaugeWrap) gaugeWrap.innerHTML = _xgbGaugeSVG(0);
    if (urgNivel)  urgNivel.textContent = "Calculando…";
    if (urgDesc)   urgDesc.textContent  = "";

    try {
        const res  = await fetch(`${API_BASE}/ml/prediccion/${idParcela}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const nivel = (data.nivel_urgencia || "preventivo").toLowerCase();

        // ── Badge de algoritmo ─────────────────────────────────────────────
        if (badgeEl) {
            const esXGB = data.algoritmo === "fao56+xgboost-v1";
            badgeEl.textContent = esXGB ? "XGBoost v1" : "FAO-56 fallback";
            badgeEl.className   = "riego-forecast-badge " +
                (esXGB ? "riego-forecast-badge--ml" : "riego-forecast-badge--fallback");
        }

        // ── Tarjeta de urgencia con ícono SVG ─────────────────────────────
        if (urgCard)  urgCard.className = `xgb-urgencia-card xgb-urgencia-card--${nivel}`;
        if (urgIcon)  urgIcon.innerHTML = _xgbUrgenciaIcon(nivel);
        if (urgNivel) {
            urgNivel.textContent = nivel.charAt(0).toUpperCase() + nivel.slice(1);
            urgNivel.className   = `xgb-urgencia-nivel xgb-urgencia-nivel--${nivel}`;
        }
        if (urgDesc) urgDesc.textContent = _URGENCIA_DESC[nivel] || "";

        // ── ¿Requiere riego? ───────────────────────────────────────────────
        if (reqEl) {
            reqEl.textContent = data.requiere_riego ? "Sí — regar" : "No — esperar";
            reqEl.className   = "riego-xgb-badge " +
                (data.requiere_riego ? "riego-xgb-badge--si" : "riego-xgb-badge--no");
        }

        // ── Confianza del modelo ───────────────────────────────────────────
        if (probEl) probEl.textContent = `${Math.round(data.probabilidad_riego * 100)}%`;

        // ── Lámina ajustada por ML ─────────────────────────────────────────
        if (laminaEl) laminaEl.textContent = `${(data.lamina_ajustada_mm ?? 0).toFixed(1)} mm`;

        // ── Gauge semicircular de estrés ───────────────────────────────────
        if (gaugeWrap) gaugeWrap.innerHTML = _xgbGaugeSVG(data.riesgo_estres);

    } catch (err) {
        console.warn("cargarPrediccionXGB:", err);
        wrap.style.display = "none";
    }
}

// ── Panel de Alertas (drawer desde topbar) ───────────────────────────────────
// La campana abre el drawer con anomalías de Isolation Forest.

let _alertasPanelAbierto = false;

async function _cargarDrawerAnomalias() {
    const bodyEl = document.getElementById('riego-resumen-wrap');
    if (!bodyEl) return;

    bodyEl.innerHTML = '<div class="ml-loading" style="padding:18px 0"><span class="bi-spinner"></span> Consultando Isolation Forest…</div>';

    try {
        const res = await fetch(`${API_BASE}/ml/anomalias?solo_anomalias=false&limit=20`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Reutilizar el renderer del tab ML
        _renderMLAnomalias(data, bodyEl);

        // Badge: mostrar número de anomalías
        const nAnom = data.total_anomalias || 0;
        _actualizarBadgeAlertas(nAnom, 0);
    } catch (err) {
        console.warn('[MILPÍN Drawer Anomalias]', err);
        bodyEl.innerHTML = `<div class="ml-anomaly-error" style="padding:16px">
            No se pudo cargar el análisis de anomalías.<br>
            <small>${err.message}</small>
        </div>`;
    }
}

function toggleAlertasPanel() {
    const drawer  = document.getElementById('alertas-drawer');
    const overlay = document.getElementById('alertas-overlay');
    if (!drawer) return;

    _alertasPanelAbierto = !_alertasPanelAbierto;

    if (_alertasPanelAbierto) {
        drawer.classList.add('is-open');
        drawer.setAttribute('aria-hidden', 'false');
        if (overlay) overlay.classList.add('is-visible');
        _cargarDrawerAnomalias();
    } else {
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
        if (overlay) overlay.classList.remove('is-visible');
    }
}

function _cerrarAlertasPanel() {
    if (!_alertasPanelAbierto) return;
    _alertasPanelAbierto = false;
    const drawer  = document.getElementById('alertas-drawer');
    const overlay = document.getElementById('alertas-overlay');
    if (drawer)  { drawer.classList.remove('is-open'); drawer.setAttribute('aria-hidden', 'true'); }
    if (overlay) overlay.classList.remove('is-visible');
}

function _actualizarBadgeAlertas(nCritico, nModerado) {
    // Sincroniza el badge en los 4 headers simultáneamente
    const badges = document.querySelectorAll('.alertas-badge');
    const total = nCritico + nModerado;
    badges.forEach(badge => {
        if (total > 0) {
            badge.textContent = total > 99 ? '99+' : String(total);
            badge.style.display = 'flex';
        } else {
            badge.style.display = 'none';
        }
    });
}

// ── Sub-tab switcher del módulo de riego ─────────────────────────────────────
// Alterna entre "Recomendaciones" (panel existente) y "Historial Riego" (nuevo).
// El nav se muestra sólo cuando hay parcela activa (_parcelaRiegoActual != null).

let _riegoTabActivo = 'recomendaciones';

function switchRiegoTab(tabName) {
    _riegoTabActivo = tabName;

    const panelRec  = document.getElementById('riego-panel-rec');
    const panelHist = document.getElementById('riego-panel-hist');
    const btnRec    = document.getElementById('rtab-btn-rec');
    const btnHist   = document.getElementById('rtab-btn-hist');

    if (tabName === 'recomendaciones') {
        if (panelRec)  panelRec.style.display  = 'block';
        if (panelHist) panelHist.style.display = 'none';
        btnRec?.classList.add('active');
        btnHist?.classList.remove('active');
    } else {
        if (panelRec)  panelRec.style.display  = 'none';
        if (panelHist) panelHist.style.display = 'block';
        btnRec?.classList.remove('active');
        btnHist?.classList.add('active');
        // Cargar historial cuando se abre el tab (siempre fresco)
        if (_parcelaRiegoActual) cargarHistorialRiego(_parcelaRiegoActual);
    }
}

function _mostrarSubtabNav(visible) {
    const nav = document.getElementById('riego-subtab-nav');
    if (nav) nav.style.display = 'flex'; // siempre visible
    // Al ocultar (sin parcela), resetear al tab de recomendaciones
    if (!visible) {
        _riegoTabActivo = 'recomendaciones';
        const panelRec  = document.getElementById('riego-panel-rec');
        const panelHist = document.getElementById('riego-panel-hist');
        if (panelRec)  panelRec.style.display  = 'block';
        if (panelHist) panelHist.style.display = 'none';
        document.getElementById('rtab-btn-rec')?.classList.add('active');
        document.getElementById('rtab-btn-hist')?.classList.remove('active');
    }
}

// ── Historial de riego real ───────────────────────────────────────────────────
// Carga GET /api/riego/parcela/{id} y renderiza KPIs + lista scrollable.

const _METODO_LABEL = {
    gravedad:        'Gravedad',
    goteo:           'Goteo',
    aspersion:       'Aspersión',
    microaspersion:  'Microaspersión',
};

async function cargarHistorialRiego(idParcela) {
    const listaEl  = document.getElementById('rhist-lista');
    const kpisEl   = document.getElementById('rhist-kpis');
    const estadoEl = document.getElementById('rhist-estado');
    const msgEl    = document.getElementById('rhist-estado-msg');

    if (!listaEl || !kpisEl) return;

    // Estado de carga
    kpisEl.innerHTML = '<div class="rhist-loading">Cargando historial…</div>';
    listaEl.innerHTML = '';
    if (estadoEl) estadoEl.style.display = 'none';

    try {
        const res = await fetch(`${API_BASE}/riego/parcela/${idParcela}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const eventos = await res.json();  // list[RiegoOut]

        _renderHistorialRiegoKPIs(eventos, kpisEl);
        _renderHistorialRiegoLista(eventos, listaEl, estadoEl, msgEl);

    } catch (err) {
        console.error('[MILPÍN] Error historial riego:', err);
        kpisEl.innerHTML = '';
        listaEl.innerHTML = '';
        if (estadoEl) estadoEl.style.display = 'block';
        if (msgEl)    msgEl.textContent = `No se pudo cargar: ${err.message}`;
    }
}

function _renderHistorialRiegoKPIs(eventos, kpisEl) {
    const n         = eventos.length;
    const laminaTotal = eventos.reduce((s, e) => s + (e.lamina_mm || 0), 0);
    const volTotal    = eventos.reduce((s, e) => s + (e.volumen_m3_ha || 0), 0);
    const promLamina  = n > 0 ? laminaTotal / n : 0;

    // Costo acumulado estimado (tarifa FAO 1.68 MXN/m³)
    const costoTotal = volTotal * 1.68;

    // Último riego
    let ultimoLabel = '—';
    if (n > 0 && eventos[0].fecha_riego) {
        const d = new Date(eventos[0].fecha_riego + 'T12:00:00');
        ultimoLabel = d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
    }

    kpisEl.innerHTML = `
    <div class="rhist-kpis-grid">
        <div class="rhist-kpi">
            <span class="rhist-kpi-val">${n}</span>
            <span class="rhist-kpi-lbl">Riegos</span>
        </div>
        <div class="rhist-kpi">
            <span class="rhist-kpi-val">${laminaTotal.toFixed(0)}<span class="rhist-kpi-unit"> mm</span></span>
            <span class="rhist-kpi-lbl">Lámina total</span>
        </div>
        <div class="rhist-kpi">
            <span class="rhist-kpi-val">${(volTotal/1000).toFixed(1)}<span class="rhist-kpi-unit"> k m³/ha</span></span>
            <span class="rhist-kpi-lbl">Volumen total</span>
        </div>
        <div class="rhist-kpi">
            <span class="rhist-kpi-val">${promLamina.toFixed(1)}<span class="rhist-kpi-unit"> mm</span></span>
            <span class="rhist-kpi-lbl">Promedio/riego</span>
        </div>
        <div class="rhist-kpi rhist-kpi--wide">
            <span class="rhist-kpi-val">$${costoTotal.toLocaleString('es-MX', { maximumFractionDigits: 0 })}<span class="rhist-kpi-unit"> MXN</span></span>
            <span class="rhist-kpi-lbl">Costo estimado · $1.68/m³</span>
        </div>
        <div class="rhist-kpi rhist-kpi--wide">
            <span class="rhist-kpi-val rhist-kpi-val--fecha">${ultimoLabel}</span>
            <span class="rhist-kpi-lbl">Último riego</span>
        </div>
    </div>`;
}

function _renderHistorialRiegoLista(eventos, listaEl, estadoEl, msgEl) {
    if (!eventos.length) {
        listaEl.innerHTML = '';
        if (estadoEl) estadoEl.style.display = 'block';
        if (msgEl)    msgEl.textContent = 'No hay riegos registrados para esta parcela.';
        return;
    }

    if (estadoEl) estadoEl.style.display = 'none';

    listaEl.innerHTML = eventos.map(e => {
        const fecha = e.fecha_riego
            ? new Date(e.fecha_riego + 'T12:00:00').toLocaleDateString('es-MX', {
                weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
            : '—';

        const lamina  = e.lamina_mm     != null ? `${Number(e.lamina_mm).toFixed(1)} mm`   : '—';
        const volumen = e.volumen_m3_ha != null ? `${Number(e.volumen_m3_ha).toFixed(0)} m³/ha` : '—';
        const metodo  = _METODO_LABEL[e.metodo_riego] || e.metodo_riego || '—';
        const costo   = e.volumen_m3_ha != null
            ? `$${(e.volumen_m3_ha * 1.68).toLocaleString('es-MX', { maximumFractionDigits: 0 })} MXN`
            : '—';

        // Origen: manual vs recomendado
        const origenTag = e.origen_decision === 'manual'
            ? '<span class="rhist-evento-tag rhist-evento-tag--manual">Manual</span>'
            : '<span class="rhist-evento-tag rhist-evento-tag--rec">Recomendado</span>';

        const notas = e.observaciones
            ? `<div class="rhist-evento-notas">${e.observaciones}</div>`
            : '';

        return `
        <div class="rhist-evento">
            <div class="rhist-evento-header">
                <span class="rhist-evento-fecha">${fecha}</span>
                ${origenTag}
            </div>
            <div class="rhist-evento-metricas">
                <div class="rhist-evento-met">
                    <span class="rhist-evento-met-lbl">Lámina</span>
                    <strong>${lamina}</strong>
                </div>
                <div class="rhist-evento-met">
                    <span class="rhist-evento-met-lbl">Volumen</span>
                    <strong>${volumen}</strong>
                </div>
                <div class="rhist-evento-met">
                    <span class="rhist-evento-met-lbl">Método</span>
                    <strong>${metodo}</strong>
                </div>
                <div class="rhist-evento-met">
                    <span class="rhist-evento-met-lbl">Costo est.</span>
                    <strong>${costo}</strong>
                </div>
            </div>
            ${notas}
        </div>`;
    }).join('');
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB ML — Inteligencia ML · XGBoost
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Carga la predicción XGBoost para la parcela seleccionada en el tab ML
 * y renderiza todos los elementos visuales del módulo (risk card, gauge, etc.)
 */
async function cargarMLTab(idParcela) {
    const panel   = document.getElementById('ml-panel');
    const estado  = document.getElementById('ml-estado');

    if (!idParcela) {
        if (panel)  panel.style.display  = 'none';
        if (estado) estado.style.display = 'flex';
        return;
    }

    if (estado) estado.style.display = 'none';
    if (panel)  panel.style.display  = 'block';

    const riskCard    = document.getElementById('ml-risk-card');
    const riskIcon    = document.getElementById('ml-risk-icon');
    const riskNivel   = document.getElementById('ml-risk-nivel');
    const riskDesc    = document.getElementById('ml-risk-desc');
    const algoBadge   = document.getElementById('ml-algoritmo-badge');
    const requiereEl  = document.getElementById('ml-requiere');
    const requiereSubEl = document.getElementById('ml-requiere-sub');
    const confianzaWrap = document.getElementById('ml-confianza-wrap');
    const laminaEl    = document.getElementById('ml-lamina');
    const gaugeWrap   = document.getElementById('ml-gauge-wrap');

    if (riskNivel)     { riskNivel.textContent = 'Calculando…'; riskNivel.className = 'ml-risk-nivel'; }
    if (riskDesc)      riskDesc.textContent    = '';
    if (algoBadge)     algoBadge.textContent   = '…';
    if (requiereEl)    { requiereEl.textContent = '…'; requiereEl.className = 'ml-requiere-val'; }
    if (requiereSubEl) requiereSubEl.textContent = '';
    if (confianzaWrap) confianzaWrap.innerHTML  = _mlConfidenceGaugeSVG(0);
    if (laminaEl)      laminaEl.textContent     = '…';
    if (gaugeWrap)     gaugeWrap.innerHTML      = _mlDonutSVG(0);

    try {
        const res = await fetch(`${API_BASE}/ml/prediccion/${idParcela}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const nivel = (data.nivel_urgencia || 'preventivo').toLowerCase();

        if (riskCard) riskCard.className = `ml-risk-card ml-risk-card--${nivel}`;
        if (riskIcon) riskIcon.innerHTML = _xgbUrgenciaIcon(nivel);
        if (riskNivel) {
            const labels = { critico: 'Riesgo crítico', moderado: 'Riesgo moderado', preventivo: 'Sin riesgo' };
            riskNivel.textContent = labels[nivel] || nivel;
            riskNivel.className   = `ml-risk-nivel ml-risk-nivel--${nivel}`;
        }
        if (riskDesc) riskDesc.textContent = _URGENCIA_DESC[nivel] || '';

        if (algoBadge) {
            const esXGB = data.algoritmo === 'fao56+xgboost-v1';
            algoBadge.textContent = esXGB ? 'XGBoost v1' : 'FAO-56 fallback';
        }

        if (requiereEl) {
            const si = !!data.requiere_riego;
            requiereEl.textContent = si ? 'Sí' : 'No';
            requiereEl.className   = 'ml-requiere-val ' +
                (si ? 'ml-requiere-val--si' : 'ml-requiere-val--no');
            if (requiereSubEl) requiereSubEl.textContent = si ? 'Regar' : 'Esperar';
        }

        if (confianzaWrap) confianzaWrap.innerHTML = _mlConfidenceGaugeSVG(data.probabilidad_riego);
        if (laminaEl)      laminaEl.textContent    = `${(data.lamina_ajustada_mm ?? 0).toFixed(1)}`;
        if (gaugeWrap)     gaugeWrap.innerHTML     = _mlDonutSVG(data.riesgo_estres);

        _renderMLFeatureBreakdown(data);

    } catch (err) {
        console.warn('[MILPÍN ML]', err);
        if (riskNivel) riskNivel.textContent = 'Sin datos';
        if (riskDesc)  riskDesc.textContent  = `No se pudo conectar con el backend. (${err.message})`;
    }
}

// ── ML · Explicabilidad: Feature Breakdown + Radar ────────────────────────────

function _renderMLFeatureBreakdown(data) {
    const bodyEl    = document.getElementById('ml-features-body');
    const sourceEl  = document.getElementById('ml-features-source');
    const radarWrap = document.getElementById('ml-radar-wrap');
    if (!bodyEl) return;

    const inp = data.inputs_usados || {};
    const cc  = inp.cc_pct || 29.5;

    const features = [
        {
            label: 'Déficit acumulado',
            val: inp.deficit_mm,
            max: 80,
            unit: 'mm',
            desc: 'Agua faltante en el perfil de suelo',
            riskDir: 'high',
        },
        {
            label: 'ETc diaria',
            val: inp.etc_mm,
            max: 12,
            unit: 'mm/día',
            desc: 'Evapotranspiración del cultivo (ETo × Kc)',
            riskDir: 'high',
        },
        {
            label: 'Kc (etapa fenológica)',
            val: inp.kc,
            max: 1.5,
            unit: '',
            desc: 'Coeficiente de cultivo en la etapa actual',
            riskDir: 'neutral',
        },
        {
            label: 'Días sin riego',
            val: inp.dias_sin_riego,
            max: 21,
            unit: 'días',
            desc: 'Tiempo transcurrido desde el último riego registrado',
            riskDir: 'high',
        },
        {
            label: 'Humedad del suelo',
            val: inp.humedad_pct,
            max: cc,
            unit: '%',
            desc: 'Humedad volumétrica actual vs capacidad de campo',
            riskDir: 'low',
        },
    ];

    bodyEl.innerHTML = features.map(f => {
        const v   = f.val ?? 0;
        const pct = Math.min(100, Math.max(0, (v / f.max) * 100));
        let barColor;
        if (f.riskDir === 'neutral') {
            barColor = '#7B2FBE';
        } else if (f.riskDir === 'high') {
            barColor = pct > 72 ? '#e63946' : pct > 42 ? '#d4820a' : '#52b788';
        } else {
            barColor = pct < 30 ? '#e63946' : pct < 55 ? '#d4820a' : '#52b788';
        }

        const numFmt = (n) => {
            if (n == null) return '—';
            if (f.unit === '' && n < 2) return n.toFixed(2);
            if (n >= 10) return Math.round(n).toString();
            return n.toFixed(1);
        };
        const valDisplay = v != null
            ? `${numFmt(v)}${f.unit ? ' ' + f.unit : ''}`
            : '—';

        return `<div class="ml-feature-row">
            <div class="ml-feature-meta">
                <span class="ml-feature-label">${f.label}</span>
                <span class="ml-feature-val" style="color:${barColor}">${valDisplay}</span>
            </div>
            <div class="ml-feature-bar-track">
                <div class="ml-feature-bar" style="width:${pct.toFixed(1)}%;background:${barColor}"></div>
            </div>
            <div class="ml-feature-desc">${f.desc}</div>
        </div>`;
    }).join('');

    if (sourceEl) {
        const fuente = inp.fuente === 'ultima_recomendacion'
            ? '✓ Datos de la última recomendación FAO-56'
            : '⚠ Usando valores por defecto — sin recomendación activa';
        sourceEl.textContent = fuente;
        sourceEl.className   = 'ml-features-source '
            + (inp.fuente === 'ultima_recomendacion'
                ? 'ml-features-source--ok'
                : 'ml-features-source--warn');
    }

    if (radarWrap) radarWrap.innerHTML = _mlRadarSVG(inp);
}

/**
 * Genera SVG de radar (pentágono) con 5 ejes de riesgo.
 * Área mayor = mayor riesgo hídrico multidimensional.
 * Cada eje normalizado 0–1: 1 = máximo riesgo en esa dimensión.
 */
function _mlRadarSVG(inp) {
    const cx = 100, cy = 105, maxR = 72;
    const n   = 5;
    const cc  = inp.cc_pct || 29.5;

    const axes = [
        { label: 'Déficit',    val: Math.min(1, (inp.deficit_mm    || 0) / 80) },
        { label: 'ETc',        val: Math.min(1, (inp.etc_mm        || 0) / 12) },
        { label: 'Kc',         val: Math.min(1, (inp.kc            || 0) / 1.5) },
        { label: 'Sin riego', val: Math.min(1, (inp.dias_sin_riego || 0) / 21) },
        { label: 'Sequía',     val: Math.min(1, 1 - Math.min(1, (inp.humedad_pct || cc) / cc)) },
    ];

    const avgRisk  = axes.reduce((s, a) => s + a.val, 0) / n;
    const riskColor = avgRisk > 0.60 ? '#e63946'
                    : avgRisk > 0.30 ? '#d4820a'
                    : '#52b788';

    function pt(i, r) {
        const angle = (2 * Math.PI * i / n) - Math.PI / 2;
        return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
    }

    // Anillos de referencia
    const ringsSVG = [0.25, 0.5, 0.75, 1.0].map(scale => {
        const d = Array.from({ length: n }, (_, i) => {
            const p = pt(i, maxR * scale);
            return `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        }).join(' ') + ' Z';
        return `<path d="${d}" fill="none" stroke="rgba(123,47,190,0.10)" stroke-width="1"/>`;
    }).join('');

    // Líneas de eje
    const axisLinesSVG = Array.from({ length: n }, (_, i) => {
        const end = pt(i, maxR);
        return `<line x1="${cx}" y1="${cy}" x2="${end.x.toFixed(1)}" y2="${end.y.toFixed(1)}"
                      stroke="rgba(123,47,190,0.15)" stroke-width="1"/>`;
    }).join('');

    // Polígono de datos
    const dataPts = axes.map((a, i) => {
        const p = pt(i, maxR * Math.max(0.04, a.val));
        return `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(' ') + ' Z';

    // Etiquetas en cada vértice
    const labelsSVG = axes.map((a, i) => {
        const p  = pt(i, maxR + 16);
        const ha = p.x < cx - 5 ? 'end' : p.x > cx + 5 ? 'start' : 'middle';
        return `<text x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}"
                      text-anchor="${ha}" dominant-baseline="middle"
                      font-size="9" font-family="Poppins,sans-serif"
                      fill="var(--secondary-text)">${a.label}</text>`;
    }).join('');

    return `<svg class="ml-radar-svg" viewBox="0 0 200 210"
                 aria-label="Perfil de riesgo hídrico multidimensional">
        ${ringsSVG}
        ${axisLinesSVG}
        <path d="${dataPts}" fill="${riskColor}" fill-opacity="0.18"
              stroke="${riskColor}" stroke-width="2" stroke-linejoin="round"/>
        ${labelsSVG}
        <circle cx="${cx}" cy="${cy}" r="3" fill="${riskColor}" opacity="0.55"/>
    </svg>`;
}

// ── ML · Detección de Anomalías · Isolation Forest ────────────────────────────

async function cargarMLAnomalias() {
    const bodyEl = document.getElementById('ml-anomaly-body');
    if (!bodyEl) return;

    bodyEl.innerHTML = '<div class="ml-loading"><span class="bi-spinner"></span> Consultando Isolation Forest…</div>';

    try {
        const res = await fetch(`${API_BASE}/ml/anomalias?solo_anomalias=false&limit=20`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _renderMLAnomalias(data, bodyEl);
    } catch (err) {
        console.warn('[MILPÍN ML Anomalias]', err);
        bodyEl.innerHTML = `<div class="ml-anomaly-error">
            No se pudo conectar con el modelo de anomalías.<br>
            <small>${err.message}</small>
        </div>`;
    }
}

function _renderMLAnomalias(data, bodyEl) {
    const total   = data.total_pares_analizados || 0;
    const nAnom   = data.total_anomalias        || 0;
    const pct     = data.pct_anomalias          || 0;
    const results = (data.resultados || []).filter(r => r.es_anomalia).slice(0, 8);

    const summaryHtml = `
    <div class="ml-anomaly-summary">
        <div class="ml-anomaly-kpi${nAnom > 0 ? ' ml-anomaly-kpi--warn' : ''}">
            <span class="ml-anomaly-kpi-num">${nAnom}</span>
            <span class="ml-anomaly-kpi-lbl">Anomalías</span>
        </div>
        <div class="ml-anomaly-kpi">
            <span class="ml-anomaly-kpi-num">${total}</span>
            <span class="ml-anomaly-kpi-lbl">Ciclos analizados</span>
        </div>
        <div class="ml-anomaly-kpi">
            <span class="ml-anomaly-kpi-num">${pct.toFixed(1)}%</span>
            <span class="ml-anomaly-kpi-lbl">Tasa anomalía</span>
        </div>
    </div>`;

    if (!results.length) {
        bodyEl.innerHTML = summaryHtml
            + '<div class="ml-anomaly-empty">Sin ciclos de riego anómalos detectados. El historial está dentro del patrón esperado.</div>';
        return;
    }

    const FEAT_LABEL = {
        vol_total_m3_ha: 'Volumen total atípico',
        n_eventos:       'Frecuencia inusual',
        vol_media_evento:'Dosis por evento atípica',
        vol_cv:          'Irregularidad de volumen',
        max_gap_dias:    'Brecha prolongada entre riegos',
        costo_total_mxn: 'Costo fuera de rango',
    };

    const itemsHtml = results.map(r => {
        // score_samples: más negativo = más anómalo; rango típico [-0.5, 0]
        const score = r.anomaly_score || 0;
        const level = Math.min(1, Math.max(0, -score * 3.5));
        const barColor = level > 0.65 ? '#e63946' : level > 0.35 ? '#d4820a' : '#52b788';
        const barPct   = (level * 100).toFixed(0);

        const parcela = (r.id_parcela || '').length > 20
            ? r.id_parcela.slice(0, 8) + '…'
            : (r.id_parcela || 'Parcela');

        const motivo = FEAT_LABEL[r.feature_principal] || r.feature_principal || '';

        return `<div class="ml-anomaly-item">
            <div class="ml-anomaly-item-header">
                <span class="ml-anomaly-parcela" title="${r.id_parcela || ''}">${parcela}</span>
                <span class="ml-anomaly-ciclo">${r.ciclo_agricola || '—'}</span>
                <span class="ml-anomaly-score-chip" style="background:${barColor}18;color:${barColor}">
                    ${score.toFixed(3)}
                </span>
            </div>
            <div class="ml-anomaly-score-bar-track" title="Nivel de anomalía: ${barPct}%">
                <div class="ml-anomaly-score-bar" style="width:${barPct}%;background:${barColor}"></div>
            </div>
            <div class="ml-anomaly-metrics">
                ${r.vol_total_m3_ha != null ? `<span>Vol: ${Math.round(r.vol_total_m3_ha).toLocaleString('es-MX')} m³/ha</span>` : ''}
                ${r.n_eventos       != null ? `<span>${r.n_eventos} evento${r.n_eventos !== 1 ? 's' : ''}</span>` : ''}
                ${r.vol_cv          != null ? `<span>CV: ${r.vol_cv.toFixed(2)}</span>` : ''}
                ${r.max_gap_dias    != null && r.max_gap_dias > 0 ? `<span>Gap: ${r.max_gap_dias} días</span>` : ''}
                ${motivo ? `<span class="ml-anomaly-motivo">${motivo}</span>` : ''}
            </div>
        </div>`;
    }).join('');

    bodyEl.innerHTML = summaryHtml + `<div class="ml-anomaly-list">${itemsHtml}</div>`;

    if (data.disclaimer) {
        bodyEl.innerHTML += `<p class="ml-anomaly-disclaimer">${data.disclaimer}</p>`;
    }
}

// ── ML · Métricas del modelo (colapsable) ─────────────────────────────────────

function _toggleMLMetricas() {
    const body = document.getElementById('ml-metricas-body');
    const icon = document.getElementById('ml-metricas-icon');
    if (!body) return;
    const open = body.style.display === 'none';
    body.style.display = open ? 'block' : 'none';
    if (icon) icon.textContent = open ? '▴' : '▾';
    if (open && !body.hasAttribute('data-loaded')) {
        body.setAttribute('data-loaded', '1');
        cargarMLMetricas();
    }
}

async function cargarMLMetricas() {
    const bodyEl = document.getElementById('ml-metricas-body');
    if (!bodyEl) return;

    bodyEl.innerHTML = '<div class="ml-loading"><span class="bi-spinner"></span> Cargando métricas…</div>';

    try {
        const res = await fetch(`${API_BASE}/ml/metricas`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _renderMLMetricas(data, bodyEl);
    } catch (err) {
        console.warn('[MILPÍN ML Metricas]', err);
        bodyEl.innerHTML = `<div class="ml-anomaly-error">No se pudo cargar métricas: ${err.message}</div>`;
    }
}

function _renderMLMetricas(data, bodyEl) {
    const xgb = data.xgboost_riego    || {};
    const iso = data.isolation_forest || {};
    const xm  = xgb.metricas || {};
    const im  = iso.metricas || {};

    function chip(label, val) {
        if (val == null) return '';
        const n = typeof val === 'number'
            ? (val <= 1 ? (val * 100).toFixed(1) + '%' : val.toFixed(1))
            : val;
        return `<div class="ml-met-chip">
            <span class="ml-met-chip-lbl">${label}</span>
            <span class="ml-met-chip-val">${n}</span>
        </div>`;
    }

    const xgbChips = [
        chip('Accuracy',    xm.clasificador?.accuracy),
        chip('F1',          xm.clasificador?.f1),
        chip('AUC-ROC',     xm.clasificador?.roc_auc),
        chip('R² lámina',   xm.regresor_lamina?.r2),
        chip('R² estrés',   xm.regresor_estres?.r2),
    ].filter(Boolean).join('');

    const isoChips = [
        chip('Precision', im.precision),
        chip('Recall',    im.recall),
        chip('F1',        im.f1),
    ].filter(Boolean).join('');

    bodyEl.innerHTML = `
    <div class="ml-metricas-grid">
        <div class="ml-met-section">
            <div class="ml-met-header">
                <span class="ml-met-dot ${xgb.entrenado ? 'ml-met-dot--ok' : 'ml-met-dot--err'}"></span>
                <span class="ml-met-title">XGBoost Riego</span>
            </div>
            <div class="ml-met-desc">${xgb.descripcion || ''}</div>
            <div class="ml-met-chips">${xgbChips || '<span style="font-size:.7rem;color:var(--secondary-text)">Sin métricas disponibles</span>'}</div>
        </div>
        <div class="ml-met-section">
            <div class="ml-met-header">
                <span class="ml-met-dot ${iso.entrenado ? 'ml-met-dot--ok' : 'ml-met-dot--err'}"></span>
                <span class="ml-met-title">Isolation Forest</span>
            </div>
            <div class="ml-met-desc">${iso.descripcion || ''}</div>
            <div class="ml-met-chips">${isoChips || '<span style="font-size:.7rem;color:var(--secondary-text)">Sin métricas disponibles</span>'}</div>
        </div>
    </div>
    <p class="ml-metricas-disclaimer">${data.disclaimer || ''}</p>`;
}

// ── ML · Drift Monitoring ────────────────────────────────────────────────────

function _toggleMLDrift() {
    const body = document.getElementById('ml-drift-body');
    const icon = document.getElementById('ml-drift-icon');
    if (!body) return;
    const open = body.style.display === 'none';
    body.style.display = open ? 'block' : 'none';
    if (icon) icon.textContent = open ? '▴' : '▾';
    if (open && !body.hasAttribute('data-loaded')) {
        body.setAttribute('data-loaded', '1');
        cargarMLDrift();
    }
}

async function cargarMLDrift() {
    const bodyEl = document.getElementById('ml-drift-body');
    if (!bodyEl) return;

    bodyEl.innerHTML = '<div class="ml-loading"><span class="bi-spinner"></span> Calculando drift…</div>';

    try {
        const res = await fetch(`${API_BASE}/ml/drift`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        _renderMLDrift(data, bodyEl);
    } catch (err) {
        console.warn('[MILPIN ML Drift]', err);
        bodyEl.innerHTML = `<div class="ml-anomaly-error">
            ${err.message}<br>
            <small style="opacity:.7">Ejecutar primero: python ML/pipelines/train_eval_promote.py</small>
        </div>`;
    }
}

function _renderMLDrift(data, bodyEl) {
    const STATUS_COLOR = { OK: '#52b788', MONITOREAR: '#d4820a', CRITICO: '#e63946' };
    const STATUS_BG    = { OK: 'rgba(82,183,136,.12)', MONITOREAR: 'rgba(212,130,10,.12)', CRITICO: 'rgba(230,57,70,.12)' };

    const globalColor = STATUS_COLOR[data.estado_global] || '#8C7F6E';
    const globalBg    = STATUS_BG[data.estado_global]    || 'transparent';

    const summaryHtml = `
    <div class="ml-anomaly-summary">
        <div class="ml-anomaly-kpi${data.n_critico > 0 ? ' ml-anomaly-kpi--warn' : ''}">
            <span class="ml-anomaly-kpi-num">${data.n_critico}</span>
            <span class="ml-anomaly-kpi-lbl">Critico</span>
        </div>
        <div class="ml-anomaly-kpi">
            <span class="ml-anomaly-kpi-num">${data.n_monitorear}</span>
            <span class="ml-anomaly-kpi-lbl">Monitorear</span>
        </div>
        <div class="ml-anomaly-kpi">
            <span class="ml-anomaly-kpi-num">${data.n_ok}</span>
            <span class="ml-anomaly-kpi-lbl">OK</span>
        </div>
        <div class="ml-anomaly-kpi" style="min-width:90px">
            <span class="ml-anomaly-kpi-num" style="color:${globalColor}">${data.estado_global}</span>
            <span class="ml-anomaly-kpi-lbl">Estado global</span>
        </div>
    </div>`;

    const rowsHtml = (data.features || []).map(f => {
        const color = STATUS_COLOR[f.status] || '#8C7F6E';
        const bg    = STATUS_BG[f.status]    || 'transparent';
        const psi   = f.psi.toFixed(4);
        const psiPct = Math.min(100, (f.psi / 0.3) * 100).toFixed(0);
        const driftFlag = f.drift_ks ? 'SI' : 'no';

        return `<div class="ml-anomaly-item" style="background:${bg};border-left:3px solid ${color}">
            <div class="ml-anomaly-item-header">
                <span class="ml-anomaly-parcela">${f.feature}</span>
                <span class="ml-anomaly-score-chip" style="background:${color}18;color:${color}">${f.status}</span>
                <span style="font-size:.72rem;color:var(--secondary-text)">N=${f.prod_n}</span>
            </div>
            <div class="ml-anomaly-score-bar-track" title="PSI ${psi}">
                <div class="ml-anomaly-score-bar" style="width:${psiPct}%;background:${color}"></div>
            </div>
            <div class="ml-anomaly-metrics">
                <span>PSI: <strong style="color:${color}">${psi}</strong></span>
                <span>KS: ${f.ks_stat.toFixed(3)}</span>
                <span>p: ${f.ks_p.toFixed(3)}</span>
                <span>Drift KS: <strong>${driftFlag}</strong></span>
            </div>
        </div>`;
    }).join('');

    const legendHtml = `<div style="font-size:.7rem;color:var(--secondary-text);padding:10px 0 4px">
        PSI &lt; 0.10 = OK &nbsp;·&nbsp; 0.10–0.20 = Monitorear &nbsp;·&nbsp; &gt; 0.20 = Critico (reentrenar)
    </div>`;

    bodyEl.innerHTML = summaryHtml
        + '<div class="ml-anomaly-list">' + rowsHtml + '</div>'
        + legendHtml;
}

// ── Configuración global (accesible desde engranaje de cualquier módulo) ─────
let _tabAnteriorConfig = 'tab-bi';

function abrirConfiguracion() {
    // Guardar el tab activo actual para poder volver
    const tabActivo = document.querySelector('.tab-content[style*="block"]');
    if (tabActivo && tabActivo.id !== 'tab-ajustes') _tabAnteriorConfig = tabActivo.id;
    // Cierra el drawer de alertas si estuviera abierto
    if (_alertasPanelAbierto) _cerrarAlertasPanel();
    // Navega a Configuración sin marcar ningún nav-item como activo
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    const tab = document.getElementById('tab-ajustes');
    if (tab) tab.style.display = 'block';
    cargarParcelasAjustes();
}

function cerrarConfiguracion() {
    cambiarPestana(null, _tabAnteriorConfig);
}

// ── Exports globales explícitos ──────────────────────────────────────────────
window.cambiarPestana             = cambiarPestana;
window.abrirPanelAdmin            = abrirPanelAdmin;
window.cargarParcelasAjustes      = cargarParcelasAjustes;
window.confirmarRiego             = confirmarRiego;
window.calcularNuevaRecomendacion = calcularNuevaRecomendacion;
window.toggleRiegoManual          = toggleRiegoManual;
window.registrarRiegoManual       = registrarRiegoManual;
window.seleccionarParcelaResumen  = seleccionarParcelaResumen;
window.switchRiegoTab             = switchRiegoTab;
window.toggleAlertasPanel         = toggleAlertasPanel;
window.cargarMLTab                = cargarMLTab;
window._toggleMLMetricas          = _toggleMLMetricas;
window._toggleMLDrift             = _toggleMLDrift;
window.cargarMLDrift              = cargarMLDrift;
window.abrirConfiguracion         = abrirConfiguracion;
window.cerrarConfiguracion        = cerrarConfiguracion;
