// ==========================================
// ui_tabs.js: Controladores de Interfaz y Recomendaciones
// ==========================================

const API_BASE = "http://localhost:8000/api";

// ID de la parcela activa en el tab de Riego (necesario para feedback)
let _parcelaRiegoActual = null;
// ID de la recomendación pendiente actual (para el PATCH de feedback)
let _recActualId = null;

// ── Navegación de pestañas ────────────────────────────────────────────────────

function cambiarPestana(event, tabId) {
    if (event) event.preventDefault();
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));

    const targetTab = document.getElementById(tabId);
    if (targetTab) {
        targetTab.style.display = "block";
        if (tabId === 'tab-mapas') {
            setTimeout(async () => {
                await inicializarMapa();
                if (map) map.invalidateSize();
            }, 300);
        }
        if (tabId === 'tab-costos') {
            _cargarParcelasEnSelect('select-parcela-riego');
        }
    }

    document.querySelectorAll(".nav-item").forEach(i => {
        if (i.getAttribute('onclick') && i.getAttribute('onclick').includes(tabId)) {
            i.classList.add("active");
        }
    });
}

// ── Utilidad compartida: poblar un <select> con parcelas ─────────────────────

async function _cargarParcelasEnSelect(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel || sel.options.length > 1) return;
    try {
        const res = await fetch(`${API_BASE}/parcelas`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const parcelas = await res.json();
        parcelas.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id_parcela;
            opt.textContent = p.nombre_parcela || `Parcela ${p.id_parcela.slice(0, 8)}`;
            sel.appendChild(opt);
        });
    } catch (err) {
        console.error('[MILPÍN] Error cargando parcelas:', err);
    }
}

// ── Módulo Mi Riego (FAO-56 + Feedback) ──────────────────────────────────────

async function cargarRecomendacion(idParcela) {
    _parcelaRiegoActual = idParcela || null;
    _recActualId = null;

    if (!idParcela) {
        _riegoEstado('💧 Selecciona una parcela para ver la recomendación activa.');
        _riegoOcultarPaneles();
        return;
    }

    _riegoEstado('⏳ Consultando recomendación...');
    _riegoOcultarPaneles();

    try {
        const res = await fetch(`${API_BASE}/recomendaciones/parcela/${idParcela}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        document.getElementById('riego-estado').style.display = 'none';

        if (data.activa) {
            _renderizarCardActiva(data.activa);
        } else {
            document.getElementById('riego-sin-activa').style.display = 'block';
        }

        if (data.historial && data.historial.length > 0) {
            _renderizarHistorial(data.historial);
        }

    } catch (err) {
        console.error('[MILPÍN] Error cargando recomendación:', err);
        _riegoEstado('⚠️ No se pudo conectar con el backend. ¿Está corriendo el servidor?');
    }
}

function _renderizarCardActiva(rec) {
    _recActualId = rec.id_recomendacion;

    // Badge de urgencia
    const badgeEl = document.getElementById('riego-badge-urgencia');
    const urgenciaLabel = { critico: '🔴 CRÍTICO', moderado: '🟡 MODERADO', preventivo: '🟢 PREVENTIVO' };
    badgeEl.textContent = urgenciaLabel[rec.nivel_urgencia] || rec.nivel_urgencia || '—';
    badgeEl.className = 'riego-badge riego-badge-' + (rec.nivel_urgencia || 'preventivo');

    document.getElementById('riego-badge-cultivo').textContent = rec.cultivo || '—';

    // Métricas
    document.getElementById('riego-lamina').textContent =
        rec.lamina_recomendada_mm != null ? rec.lamina_recomendada_mm.toFixed(1) : '—';
    document.getElementById('riego-eto').textContent =
        rec.eto_referencia != null ? rec.eto_referencia.toFixed(2) + ' mm' : '—';
    document.getElementById('riego-etc').textContent =
        rec.etc_calculada != null ? rec.etc_calculada.toFixed(2) + ' mm' : '—';
    document.getElementById('riego-deficit').textContent =
        rec.deficit_acumulado_mm != null ? rec.deficit_acumulado_mm.toFixed(1) + ' mm' : '—';
    document.getElementById('riego-dias').textContent =
        rec.dias_sin_riego != null
            ? (rec.dias_sin_riego === 999 ? 'Sin registros' : rec.dias_sin_riego + ' días')
            : '—';

    // Fecha sugerida
    if (rec.fecha_riego_sugerida) {
        const d = new Date(rec.fecha_riego_sugerida + 'T12:00:00');
        document.getElementById('riego-fecha-sugerida').textContent =
            'Fecha sugerida: ' + d.toLocaleDateString('es-MX', { weekday: 'long', day: 'numeric', month: 'long' });
    }

    document.getElementById('riego-card-activa').style.display = 'block';
}

function _renderizarHistorial(historial) {
    const ESTADO = { aceptada: '✓ Regó', modificada: '~ Modificó', ignorada: '✗ No regó' };
    const CLASE  = { aceptada: 'riego-hist-ok', modificada: 'riego-hist-mod', ignorada: 'riego-hist-no' };

    document.getElementById('riego-historial-lista').innerHTML = historial.map(r => {
        const fecha = new Date(r.fecha_generacion).toLocaleDateString('es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
        const lamina = r.lamina_recomendada_mm != null ? r.lamina_recomendada_mm.toFixed(1) + ' mm' : '—';
        const estado = ESTADO[r.aceptada] || r.aceptada;
        const claseEstado = CLASE[r.aceptada] || '';
        return `
        <div class="riego-hist-item">
            <div class="riego-hist-info">
                <span class="riego-hist-fecha">${fecha}</span>
                <span class="riego-hist-cultivo">${r.cultivo || '—'} · ${r.nivel_urgencia || '—'}</span>
            </div>
            <div class="riego-hist-derecha">
                <span class="riego-hist-lamina">${lamina}</span>
                <span class="riego-hist-estado ${claseEstado}">${estado}</span>
            </div>
        </div>`;
    }).join('');

    document.getElementById('riego-historial-wrap').style.display = 'block';
}

async function confirmarRiego(decision) {
    if (!_recActualId) return;

    const btnSi = document.getElementById('btn-riego-si');
    const btnNo = document.getElementById('btn-riego-no');
    btnSi.disabled = btnNo.disabled = true;

    // Marcar visualmente qué botón se presionó
    if (decision === 'aceptada') {
        btnSi.innerHTML = '<span class="riego-spinner"></span> Guardando...';
        btnNo.innerHTML = _iconNo() + ' No regué';
    } else {
        btnNo.innerHTML = '<span class="riego-spinner"></span> Guardando...';
        btnSi.innerHTML = _iconSi() + ' Regué hoy';
    }

    try {
        const res = await fetch(`${API_BASE}/recomendaciones/${_recActualId}/feedback`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ aceptada: decision }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        await cargarRecomendacion(_parcelaRiegoActual);

    } catch (err) {
        console.error('[MILPÍN] Error enviando feedback:', err);
        btnSi.disabled = btnNo.disabled = false;
        btnSi.innerHTML = _iconSi() + ' Regué hoy';
        btnNo.innerHTML = _iconNo() + ' No regué';
        alert('Error al guardar. Revisa la conexión con el backend.');
    }
}

async function calcularNuevaRecomendacion() {
    if (!_parcelaRiegoActual) return;
    const dias = parseInt(document.getElementById('input-dias-siembra').value);
    if (!dias || dias < 1 || dias > 365) {
        alert('Ingresa un valor válido para días desde siembra (1-365).');
        return;
    }

    const btn = document.querySelector('.riego-btn-calcular');
    btn.disabled = true;
    btn.textContent = '⏳ Calculando...';

    try {
        const url = `${API_BASE}/balance_hidrico?parcela_id=${_parcelaRiegoActual}&dias_siembra=${dias}`;
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        // Recargar el tab: el endpoint ya persistió la recomendación en BD
        await cargarRecomendacion(_parcelaRiegoActual);
    } catch (err) {
        console.error('[MILPÍN] Error calculando FAO-56:', err);
        alert(`Error al calcular: ${err.message}`);
        btn.disabled = false;
        btn.textContent = 'Calcular recomendación FAO-56';
    }
}

// ── Helpers estado Riego ──────────────────────────────────────────────────────

function _riegoEstado(msg) {
    const el = document.getElementById('riego-estado');
    el.querySelector('p').textContent = msg;
    el.style.display = 'flex';
}

function _riegoOcultarPaneles() {
    ['riego-card-activa', 'riego-sin-activa', 'riego-historial-wrap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}

// ── Helpers de formato ────────────────────────────────────────────────────────

function formatMXN(val) {
    return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 }).format(val);
}

function formatNum(val) {
    return new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 }).format(val);
}

// ── Módulo BI (demo — mantener hasta reemplazar con lógica real) ───────────────

const productos = ["Uva", "Maíz", "Frijol"];
const historial = [
    [[200, 230, 260], [0, 0, 0], [0, 0, 0]],
    [[210, 230, 250], [100, 120, 140], [200, 220, 240]],
    [[0, 0, 0], [90, 110, 130], [180, 200, 220]],
    [[190, 220, 250], [80, 90, 100], [160, 180, 200]]
];

function cosineSimilarity(vecA, vecB) {
    let dotProduct = 0; let normA = 0; let normB = 0;
    for (let i = 0; i < vecA.length; i++) {
        dotProduct += vecA[i] * vecB[i];
        normA += vecA[i] * vecA[i];
        normB += vecB[i] * vecB[i];
    }
    return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}

function actualizarAnalisisBI() {
    const element = document.getElementById('select-cliente-bi');
    if(!element) return;
    const idx = parseInt(element.value);

    const promedios = historial.map(c => c.map(p => p.reduce((a,b) => a+b)/3));
    const promedioActual = promedios[idx];

    let maxSim = -1; let similarIdx = -1;
    promedios.forEach((p, i) => {
        if (i !== idx) {
            let sim = cosineSimilarity(promedioActual, p);
            if (sim > maxSim) { maxSim = sim; similarIdx = i; }
        }
    });

    let htmlRecs = "<h4>Producción Recomendada:</h4><ul>";
    promedioActual.forEach((p, i) => {
        let cantidad = p > 0 ? p : promedios[similarIdx][i];
        let esNuevo = p === 0 && promedios[similarIdx][i] > 0;

        htmlRecs += `<li>
            <b>${productos[i]}:</b> ${Math.round(cantidad)} kg
            ${esNuevo ? '<span style="color: #7BB395;">(✨ Sugerencia IA)</span>' : ''}
        </li>`;
    });
    htmlRecs += "</ul>";

    document.getElementById('resultados-bi').innerHTML = `
        <p><b>Cliente más similar:</b> Perfil ${similarIdx + 1}</p>
        ${htmlRecs}
    `;
}