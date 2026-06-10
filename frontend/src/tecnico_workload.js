// tecnico_workload.js — Vista de carga de trabajo para técnicos de riego
// Consume: GET /api/tecnico/carga-trabajo
// Fallback: DEMO_DATA cuando el backend no está disponible.

const WORKLOAD = (() => {
  const API = 'https://milpin-pp26-v1-production.up.railway.app/api';

  let _data          = null;
  let _filtroUrgencia = 'todos';
  let _modoDemo      = false;

  // ── Datos demo (Valle del Yaqui · DR-041 · Módulo 3) ─────────────────────
  const DEMO_DATA = {
    fecha_consulta: new Date().toISOString().slice(0, 10),
    resumen: { total: 5, critico: 2, moderado: 1, preventivo: 1, sin_recomendacion: 1 },
    parcelas: [
      {
        id_parcela:            'demo-001',
        nombre_parcela:        'La Paloma',
        propietario:           'Ramón Valenzuela Torres',
        cultivo:               'Maíz',
        area_ha:               8.5,
        sistema_riego:         'gravedad',
        nivel_urgencia:        'critico',
        dias_sin_riego:        14,
        deficit_acumulado_mm:  62.4,
        lamina_recomendada_mm: 78.0,
        fecha_riego_sugerida:  new Date().toISOString().slice(0, 10),
      },
      {
        id_parcela:            'demo-002',
        nombre_parcela:        'El Mezquital',
        propietario:           'Guadalupe Morales Soto',
        cultivo:               'Chile',
        area_ha:               4.2,
        sistema_riego:         'goteo',
        nivel_urgencia:        'critico',
        dias_sin_riego:        11,
        deficit_acumulado_mm:  48.7,
        lamina_recomendada_mm: 55.0,
        fecha_riego_sugerida:  new Date().toISOString().slice(0, 10),
      },
      {
        id_parcela:            'demo-003',
        nombre_parcela:        'Los Álamos',
        propietario:           'Carlos Félix Ríos',
        cultivo:               'Algodón',
        area_ha:               12.0,
        sistema_riego:         'aspersion',
        nivel_urgencia:        'moderado',
        dias_sin_riego:        7,
        deficit_acumulado_mm:  28.1,
        lamina_recomendada_mm: 34.0,
        fecha_riego_sugerida:  (() => { const d = new Date(); d.setDate(d.getDate() + 2); return d.toISOString().slice(0, 10); })(),
      },
      {
        id_parcela:            'demo-004',
        nombre_parcela:        'El Capomo',
        propietario:           'Ramón Valenzuela Torres',
        cultivo:               'Frijol',
        area_ha:               6.8,
        sistema_riego:         'gravedad',
        nivel_urgencia:        'preventivo',
        dias_sin_riego:        4,
        deficit_acumulado_mm:  12.3,
        lamina_recomendada_mm: 18.0,
        fecha_riego_sugerida:  (() => { const d = new Date(); d.setDate(d.getDate() + 4); return d.toISOString().slice(0, 10); })(),
      },
      {
        id_parcela:            'demo-005',
        nombre_parcela:        'Las Lomas',
        propietario:           'María Luisa Acedo',
        cultivo:               'Uva',
        area_ha:               3.5,
        sistema_riego:         'goteo',
        nivel_urgencia:        null,
        dias_sin_riego:        null,
        deficit_acumulado_mm:  null,
        lamina_recomendada_mm: null,
        fecha_riego_sugerida:  null,
      },
    ],
  };

  async function _get(path) {
    const res = await fetch(`${API}${path}`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  // ── Render resumen KPI ─────────────────────────────────────────────────────
  function _renderResumen(resumen) {
    const el = document.getElementById('wkload-resumen');
    if (!el) return;
    el.innerHTML = `
      <div class="wkload-kpi-card">
        <div class="wkload-kpi-val">${resumen.total}</div>
        <div class="wkload-kpi-lbl">Total</div>
      </div>
      <div class="wkload-kpi-card wkload-kpi-card--critico">
        <div class="wkload-kpi-val">${resumen.critico}</div>
        <div class="wkload-kpi-lbl">Críticas</div>
      </div>
      <div class="wkload-kpi-card wkload-kpi-card--moderado">
        <div class="wkload-kpi-val">${resumen.moderado}</div>
        <div class="wkload-kpi-lbl">Moderadas</div>
      </div>
      <div class="wkload-kpi-card wkload-kpi-card--preventivo">
        <div class="wkload-kpi-val">${resumen.preventivo}</div>
        <div class="wkload-kpi-lbl">Preventivas</div>
      </div>
      <div class="wkload-kpi-card wkload-kpi-card--sinrec">
        <div class="wkload-kpi-val">${resumen.sin_recomendacion}</div>
        <div class="wkload-kpi-lbl">Sin rec.</div>
      </div>
    `;
  }

  // ── Render lista de parcelas ───────────────────────────────────────────────
  function _renderLista(parcelas) {
    const el = document.getElementById('wkload-lista');
    if (!el) return;

    const filtradas = _filtroUrgencia === 'todos'
      ? parcelas
      : parcelas.filter(p =>
          _filtroUrgencia === 'sin_recomendacion'
            ? !p.nivel_urgencia
            : p.nivel_urgencia === _filtroUrgencia
        );

    if (!filtradas.length) {
      el.innerHTML = '<div class="wkload-empty">No hay parcelas en esta categoría.</div>';
      return;
    }

    const URGENCIA_LABEL = {
      critico:    'CRÍTICO',
      moderado:   'MODERADO',
      preventivo: 'PREVENTIVO',
    };

    el.innerHTML = filtradas.map(p => {
      const urgencia   = p.nivel_urgencia || 'sin_recomendacion';
      const badgeLabel = URGENCIA_LABEL[urgencia] || 'SIN REC.';
      const fechaFmt   = p.fecha_riego_sugerida
        ? new Date(p.fecha_riego_sugerida + 'T12:00:00').toLocaleDateString('es-MX', {
            day: 'numeric', month: 'short',
          })
        : '—';
      const dias    = p.dias_sin_riego != null ? `${p.dias_sin_riego}d sin riego` : '—';
      const deficit = p.deficit_acumulado_mm != null
        ? `${p.deficit_acumulado_mm.toFixed(1)} mm`
        : '—';
      const area  = p.area_ha != null ? ` · ${p.area_ha.toFixed(1)} ha` : '';
      const riego = p.sistema_riego
        ? ` · ${p.sistema_riego.charAt(0).toUpperCase() + p.sistema_riego.slice(1)}`
        : '';

      return `
        <div class="wkload-item wkload-item--${urgencia}"
             onclick="WORKLOAD.irAParcela('${p.id_parcela}')">
          <div class="wkload-band wkload-band--${urgencia}"></div>
          <div class="wkload-item-body">
            <div class="wkload-item-top">
              <span class="wkload-item-nombre">${p.nombre_parcela}</span>
              <span class="wkload-badge wkload-badge--${urgencia}">${badgeLabel}</span>
            </div>
            <div class="wkload-item-sub">${p.propietario} · ${p.cultivo || '—'}${area}${riego}</div>
            <div class="wkload-item-meta">
              <span class="wkload-chip wkload-chip--dias">${dias}</span>
              <span class="wkload-chip wkload-chip--deficit">💧 ${deficit} déficit</span>
              <span class="wkload-chip wkload-chip--fecha">📅 ${fechaFmt}</span>
              ${p.lamina_recomendada_mm != null
                ? `<span class="wkload-chip wkload-chip--lamina">${p.lamina_recomendada_mm.toFixed(0)} mm lámina</span>`
                : ''}
            </div>
          </div>
          <div class="wkload-chevron">›</div>
        </div>
      `;
    }).join('');
  }

  // ── Cargar datos desde la API (fallback a demo) ───────────────────────────
  async function cargar() {
    const loadingEl = document.getElementById('wkload-loading');
    const listaEl   = document.getElementById('wkload-lista');
    const statusEl  = document.getElementById('wkload-fecha-consulta');

    if (loadingEl) loadingEl.style.display = 'flex';
    if (listaEl)   listaEl.innerHTML = '';
    if (statusEl)  statusEl.textContent = '';

    try {
      const query = window.MILPIN_AUTH?.getParcelasQuery?.() || '';
      _data     = await _get(`/tecnico/carga-trabajo${query}`);
      _modoDemo = false;
    } catch {
      _data     = DEMO_DATA;
      _modoDemo = true;
    }

    if (loadingEl) loadingEl.style.display = 'none';
    _renderResumen(_data.resumen);
    _renderLista(_data.parcelas);
    _sincronizarFiltros();

    if (statusEl) {
      const d = new Date(_data.fecha_consulta + 'T12:00:00');
      const fechaStr = d.toLocaleDateString('es-MX', {
        day: 'numeric', month: 'long', year: 'numeric',
      });
      statusEl.textContent = _modoDemo
        ? `Modo demo · ${fechaStr}`
        : `Actualizado: ${fechaStr}`;
    }
  }

  // ── Filtro por urgencia ────────────────────────────────────────────────────
  function setFiltro(urgencia) {
    _filtroUrgencia = urgencia;
    _sincronizarFiltros();
    if (_data) _renderLista(_data.parcelas);
  }

  function _sincronizarFiltros() {
    document.querySelectorAll('.wkload-filtro-chip').forEach(el => {
      el.classList.toggle('wkload-filtro-chip--active', el.dataset.urgencia === _filtroUrgencia);
    });
  }

  // ── Navegar a tab Riego con la parcela seleccionada ───────────────────────
  function irAParcela(idParcela) {
    if (_modoDemo) return;
    cambiarPestana(null, 'tab-costos');
    setTimeout(() => {
      const sel = document.getElementById('select-parcela-riego');
      if (sel) {
        sel.value = idParcela;
        if (typeof cargarRecomendacion === 'function') {
          cargarRecomendacion(idParcela);
        }
      }
    }, 50);
  }

  return { cargar, setFiltro, irAParcela };
})();

window.WORKLOAD = WORKLOAD;
