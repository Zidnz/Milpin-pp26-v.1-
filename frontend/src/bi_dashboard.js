// bi_dashboard.js — Dashboard BI de MILPÍN (vanilla JS, sin frameworks)
// Reemplaza el módulo BI falso de ui_tabs.js
// Conectado a: /api/parcelas, /api/parcelas/{id}/kpi,
//              /api/riego/parcela/{id}, /api/recomendaciones/parcela/{id}

const BI = (() => {

  // ── Constantes ─────────────────────────────────────────────────────────────
  const API      = 'http://localhost:8000/api';
  const BASELINE = 8000;   // m³/ha/ciclo — línea base DR-041
  const TARIFA   = 1.68;   // MXN/m³ — CFE 9-CU, bombeo 80 m

  const CROP_COLORS = {
    'maíz': '#E8C27D', 'maiz': '#E8C27D',
    'frijol': '#7BB395',
    'algodón': '#5DADE2', 'algodon': '#5DADE2',
    'uva': '#C09A6B',
    'chile': '#E63946',
  };

  const METHOD_COLORS = {
    'gravedad':        '#5DADE2',
    'goteo':           '#7BB395',
    'aspersión':       '#E8C27D', 'aspersion': '#E8C27D',
    'microaspersión':  '#8E7F71', 'microaspersion': '#8E7F71',
  };

  // ── Estado interno ─────────────────────────────────────────────────────────
  let _state = {
    initialized:     false,
    loading:         false,
    parcelas:        [],   // lista completa desde /api/parcelas
    cultivos:        [],   // lista completa desde /api/cultivos
    selectedParcela: 'all',
    selectedCultivo: 'all',
    rawData:         [],   // [{parcela, kpi, histRiego, recomendaciones}]
    computed: {
      kpis:      null,
      lineData:  [],
      barData:   [],
      donutData: [],
      tableRows: [],
    },
  };

  // ── Fetch helper con manejo de errores y timeout ──────────────────────────
  async function _fetch(path, timeoutMs = 10000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(`${API}${path}`, { signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status} — ${path}`);
      return res.json();
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error(`Timeout (${timeoutMs / 1000}s) — el backend no respondió en ${path}`);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Init: llamado cuando el tab BI se abre por primera vez ─────────────────
  async function init() {
    if (_state.initialized) return;
    _showSkeleton('Cargando parcelas y cultivos...');
    try {
      [_state.parcelas, _state.cultivos] = await Promise.all([
        _fetch('/parcelas'),
        _fetch('/cultivos'),
      ]);
      _state.initialized = true;   // solo se marca OK cuando los datos llegaron
      _populateFilters();
      await _fetchAndRender();
    } catch (err) {
      _showError(err);
      // _state.initialized queda en false → el usuario puede reintentar
    }
  }

  // ── Poblar los <select> de filtros con datos reales ────────────────────────
  function _populateFilters() {
    const selP = document.getElementById('bi-filter-parcela');
    const selC = document.getElementById('bi-filter-cultivo');
    if (!selP || !selC) return;

    selP.innerHTML = '<option value="all">Todas las parcelas</option>';
    _state.parcelas.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id_parcela;
      opt.textContent = p.nombre_parcela || p.id_parcela.slice(0, 8);
      selP.appendChild(opt);
    });

    selC.innerHTML = '<option value="all">Todos los cultivos</option>';
    _state.cultivos.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.nombre_comun.toLowerCase();
      opt.textContent = c.nombre_comun;
      selC.appendChild(opt);
    });
  }

  // ── Fetch datos para la selección activa y renderizar ─────────────────────
  async function _fetchAndRender() {
    _setLoading(true);
    try {
      const targets = _state.selectedParcela === 'all'
        ? _state.parcelas
        : _state.parcelas.filter(p => p.id_parcela === _state.selectedParcela);

      if (!targets.length) {
        _showError(new Error('No hay parcelas disponibles.'));
        return;
      }

      // Fetch paralelo para todas las parcelas objetivo
      _state.rawData = await Promise.all(targets.map(async p => {
        const [kpi, histRiego, recomendaciones] = await Promise.allSettled([
          _fetch(`/parcelas/${p.id_parcela}/kpi`),
          _fetch(`/riego/parcela/${p.id_parcela}?limite=50`),
          _fetch(`/recomendaciones/parcela/${p.id_parcela}`),
        ]);
        return {
          parcela:         p,
          kpi:             kpi.status === 'fulfilled'             ? kpi.value             : null,
          histRiego:       histRiego.status === 'fulfilled'       ? histRiego.value       : [],
          recomendaciones: recomendaciones.status === 'fulfilled' ? recomendaciones.value : { activa: null, historial: [] },
        };
      }));

      _compute();
      _render();
    } catch (err) {
      _showError(err);
    } finally {
      _setLoading(false);
    }
  }

  // ── Calcular valores agregados desde rawData ───────────────────────────────
  function _compute() {
    const data          = _state.rawData;
    const cultivoFilter = _state.selectedCultivo;

    // ── KPI Cards ──────────────────────────────────────────────────────────
    const kpisValidos = data.filter(d => d.kpi).map(d => d.kpi);
    const consumoTotal = kpisValidos.reduce((s, k) => s + (k.volumen_aplicado_m3_ha || 0), 0);
    const consumoAvg   = kpisValidos.length ? consumoTotal / kpisValidos.length : 0;
    const ahorroM3     = Math.max(0, BASELINE - consumoAvg);
    const ahorroPct    = BASELINE > 0 ? (ahorroM3 / BASELINE) * 100 : 0;
    const ahorroMXN    = ahorroM3 * TARIFA;

    // Adopción: sobre todas las recomendaciones disponibles
    const todasRecs = data.flatMap(d => [
      ...(d.recomendaciones.activa   ? [d.recomendaciones.activa]   : []),
      ...(d.recomendaciones.historial || []),
    ]);
    const recsCerradas  = todasRecs.filter(r => r.aceptada !== 'pendiente');
    const recsEjecutadas = todasRecs.filter(r => r.aceptada === 'aceptada' || r.aceptada === 'modificada');
    const tasaAdopcion  = recsCerradas.length > 0
      ? (recsEjecutadas.length / recsCerradas.length) * 100 : 0;

    _state.computed.kpis = {
      consumoAvg:   Math.round(consumoAvg),
      ahorroM3:     Math.round(ahorroM3),
      ahorroMXN:    Math.round(ahorroMXN),
      ahorroPct:    Math.round(ahorroPct),
      tasaAdopcion: Math.round(tasaAdopcion),
      totalRecs:    todasRecs.length,
    };

    // ── Serie semanal: agrupación client-side de historial_riego ──────────
    const todosRiegos = data.flatMap(d =>
      (d.histRiego || []).map(r => ({ ...r, _nombre: d.parcela.nombre_parcela }))
    );

    const porSemana = {};
    todosRiegos.forEach(r => {
      if (!r.volumen_m3_ha || !r.fecha_riego) return;
      const semKey = _isoWeekLabel(new Date(r.fecha_riego + 'T12:00:00'));
      if (!porSemana[semKey]) porSemana[semKey] = { vals: [], label: semKey };
      porSemana[semKey].vals.push(r.volumen_m3_ha);
    });
    _state.computed.lineData = Object.values(porSemana)
      .sort((a, b) => a.label.localeCompare(b.label))
      .map(s => ({ w: s.label, v: s.vals.reduce((a, b) => a + b, 0) / s.vals.length }));

    // ── ETc por cultivo: desde parametros_json de recomendaciones ─────────
    const etcPorCultivo = {};
    data.forEach(d => {
      const recs = [
        ...(d.recomendaciones.activa    ? [d.recomendaciones.activa]    : []),
        ...(d.recomendaciones.historial || []),
      ];
      recs.forEach(r => {
        const cultivo = (r.parametros_json?.cultivo || '').toLowerCase();
        if (!cultivo || !r.etc_calculada) return;
        if (cultivoFilter !== 'all' && cultivo !== cultivoFilter) return;
        if (!etcPorCultivo[cultivo]) etcPorCultivo[cultivo] = { vals: [], nombre: r.parametros_json.cultivo };
        etcPorCultivo[cultivo].vals.push(r.etc_calculada);
      });
    });
    _state.computed.barData = Object.entries(etcPorCultivo).map(([key, c]) => ({
      crop:  c.nombre,
      etc:   Math.round(c.vals.reduce((a, b) => a + b, 0) / c.vals.length),
      color: CROP_COLORS[key] || '#8E7F71',
    })).sort((a, b) => b.etc - a.etc);

    // ── Método de riego: distribución desde historial_riego ───────────────
    const porMetodo = {};
    todosRiegos.forEach(r => {
      const m = (r.metodo_riego || 'desconocido').toLowerCase();
      porMetodo[m] = (porMetodo[m] || 0) + 1;
    });
    const totalEventos = Object.values(porMetodo).reduce((a, b) => a + b, 0) || 1;
    _state.computed.donutData = Object.entries(porMetodo)
      .map(([m, cnt]) => ({
        name:  _capitalize(m),
        value: Math.round((cnt / totalEventos) * 100),
        color: METHOD_COLORS[m] || '#8E7F71',
      }))
      .sort((a, b) => b.value - a.value);

    // ── Tabla: eventos recientes enriquecidos ─────────────────────────────
    const recLookup = {};
    data.forEach(d => {
      const recs = [
        ...(d.recomendaciones.activa    ? [d.recomendaciones.activa]    : []),
        ...(d.recomendaciones.historial || []),
      ];
      recs.forEach(r => { if (r.id_recomendacion) recLookup[r.id_recomendacion] = r; });
    });

    _state.computed.tableRows = todosRiegos
      .filter(r => {
        if (cultivoFilter === 'all') return true;
        const rec = r.id_recomendacion ? recLookup[r.id_recomendacion] : null;
        return (rec?.parametros_json?.cultivo || '').toLowerCase() === cultivoFilter;
      })
      .sort((a, b) => new Date(b.fecha_riego) - new Date(a.fecha_riego))
      .slice(0, 25)
      .map(r => {
        const rec = r.id_recomendacion ? recLookup[r.id_recomendacion] : null;
        return {
          parcel: r._nombre || '—',
          crop:   rec?.parametros_json?.cultivo || '—',
          date:   r.fecha_riego || '—',
          applied: r.volumen_m3_ha,
          lamina:  r.lamina_mm,
          method:  r.metodo_riego || '—',
          origin:  r.origen_decision || '—',
          status:  rec?.aceptada || '—',
        };
      });
  }

  // ── Render completo del dashboard ──────────────────────────────────────────
  function _render() {
    const container = document.getElementById('bi-dashboard-content');
    if (!container) return;
    const c = _state.computed;
    const noData = !c.kpis || _state.rawData.every(d => !d.kpi);

    container.innerHTML = `
      ${_htmlKPIs(c.kpis, noData)}
      ${_htmlLineChart(c.lineData)}
      <div class="bi-row-2">
        ${_htmlBarChart(c.barData)}
        ${_htmlDonut(c.donutData)}
      </div>
      ${_htmlTable(c.tableRows)}
    `;
    container.style.opacity = '1';
  }

  // ── KPI Cards ──────────────────────────────────────────────────────────────
  function _htmlKPIs(k, noData) {
    if (noData || !k) {
      return `<div class="bi-empty-state">
        <span>📊</span>
        <p>Sin datos de riego registrados para esta selección.<br>
        Registra eventos de riego en el tab <strong>Riego</strong> para ver el dashboard.</p>
      </div>`;
    }

    const consumoColor = k.ahorroPct >= 25 ? 'var(--green-strong)'
                       : k.ahorroPct >  0  ? 'var(--amber-strong)'
                       : 'var(--red-strong)';
    const adopcionColor = k.tasaAdopcion >= 70 ? 'var(--green-strong)'
                        : k.tasaAdopcion >  0  ? 'var(--amber-strong)'
                        : 'var(--secondary-text)';
    const metaLabel = k.ahorroPct >= 25 ? `✓ ${k.ahorroPct}% logrado` : `${k.ahorroPct}% de meta 25%`;
    const metaColor = k.ahorroPct >= 25 ? 'var(--green-strong)' : 'var(--amber-dark)';

    const items = [
      { label: 'Consumo agua',    val: `${k.consumoAvg.toLocaleString('es-MX')} m³/ha`, color: consumoColor },
      { label: 'Ahorro estimado', val: `${k.ahorroM3.toLocaleString('es-MX')} m³/ha`,  color: 'var(--green-dark)' },
      { label: 'Ahorro en costo', val: `$${k.ahorroMXN.toLocaleString('es-MX')} MXN`,  color: 'var(--primary-text)' },
      { label: 'Adopción IA',     val: `${k.tasaAdopcion}%`,                            color: adopcionColor },
      { label: 'Recomendaciones', val: `${k.totalRecs}`,                                color: 'var(--primary-text)' },
      { label: 'Meta ciclo',      val: metaLabel,                                        color: metaColor },
    ];

    return `<div class="bi-kpi-grid">
      ${items.map(item => `
        <div class="bi-kpi-card">
          <div class="bi-kpi-label">${item.label}</div>
          <div class="bi-kpi-value" style="color:${item.color}">${item.val}</div>
        </div>`).join('')}
    </div>`;
  }

  // ── Line Chart SVG (consumo semanal) ───────────────────────────────────────
  function _htmlLineChart(data) {
    const titulo = `<div class="bi-card-title">Consumo de Agua vs. Línea Base DR-041</div>
      <div class="bi-card-sub">Promedio por semana · m³/ha</div>`;

    if (!data.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin registros de riego para graficar. Registra eventos en el tab Riego.</div>
      </div>`;
    }

    const W = 860, H = 240, PL = 52, PR = 20, PT = 14, PB = 34;
    const cW = W - PL - PR, cH = H - PT - PB;
    const minV = 5400, maxV = 8600;
    const clamp = v => Math.max(minV, Math.min(maxV, v));
    const toX   = i => PL + (i / Math.max(data.length - 1, 1)) * cW;
    const toY   = v => PT + cH - ((clamp(v) - minV) / (maxV - minV)) * cH;

    // Bezier suavizado
    const pts = data.map((d, i) => [toX(i), toY(d.v)]);
    let linePath = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const cx = (pts[i][0] + pts[i + 1][0]) / 2;
      linePath += ` C${cx.toFixed(1)},${pts[i][1].toFixed(1)} ${cx.toFixed(1)},${pts[i+1][1].toFixed(1)} ${pts[i+1][0].toFixed(1)},${pts[i+1][1].toFixed(1)}`;
    }
    const areaPath = `${linePath} L${toX(data.length-1)},${PT+cH} L${toX(0)},${PT+cH} Z`;

    const yBase   = toY(BASELINE);
    const yTarget = toY(6000);

    const gridYs = [5500, 6000, 6500, 7000, 7500, 8000, 8500].filter(v => v >= minV && v <= maxV);
    const gridLines = gridYs.map(v => {
      const y = toY(v), isKey = (v === 6000 || v === BASELINE);
      return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+cW}" y2="${y.toFixed(1)}"
        stroke="${isKey ? 'rgba(74,59,40,.12)' : 'rgba(74,59,40,.05)'}"
        stroke-width="${isKey ? 1 : 0.8}" stroke-dasharray="${isKey ? '' : '3 3'}"/>
        <text x="${PL-7}" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="10"
          fill="#8C7F6E" font-family="Segoe UI">${(v/1000).toFixed(1)}k</text>`;
    }).join('');

    const dots = pts.map(([x, y]) =>
      `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="#7BB395" stroke="#fff" stroke-width="2"/>`
    ).join('');

    const xLabels = data.map((d, i) => {
      const show = data.length <= 8 || i % Math.ceil(data.length / 8) === 0;
      return show ? `<text x="${toX(i).toFixed(1)}" y="${H-6}" text-anchor="middle"
        font-size="10" fill="#8C7F6E" font-family="Segoe UI">${d.w}</text>` : '';
    }).join('');

    const consumoMedio = data.reduce((s, d) => s + d.v, 0) / data.length;
    const ahorroActual = Math.max(0, BASELINE - consumoMedio);
    const ahorroPct    = Math.round((ahorroActual / BASELINE) * 100);

    return `
    <div class="bi-card bi-card--line">
      <div class="bi-card-header">
        <div>${titulo}</div>
        <div class="bi-legend">
          <span class="bi-legend-item">
            <span class="bi-legend-line" style="background:#7BB395"></span>Consumo real
          </span>
          <span class="bi-legend-item">
            <span class="bi-legend-line bi-legend-line--dash" style="background:#5DADE2"></span>Objetivo 6,000
          </span>
          <span class="bi-legend-item">
            <span class="bi-legend-line bi-legend-line--dash" style="background:rgba(74,59,40,.3)"></span>Línea base 8,000
          </span>
        </div>
      </div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block">
        <defs>
          <linearGradient id="biAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#7BB395" stop-opacity=".18"/>
            <stop offset="100%" stop-color="#7BB395" stop-opacity=".01"/>
          </linearGradient>
          <clipPath id="biChartClip">
            <rect x="${PL}" y="${PT}" width="${cW}" height="${cH}"/>
          </clipPath>
        </defs>
        ${gridLines}
        <rect x="${PL}" y="${yTarget.toFixed(1)}" width="${cW}"
          height="${(yBase-yTarget).toFixed(1)}" fill="rgba(123,179,149,.07)" clip-path="url(#biChartClip)"/>
        <line x1="${PL}" y1="${yBase.toFixed(1)}" x2="${PL+cW}" y2="${yBase.toFixed(1)}"
          stroke="rgba(74,59,40,.28)" stroke-width="1.5" stroke-dasharray="6 4"/>
        <line x1="${PL}" y1="${yTarget.toFixed(1)}" x2="${PL+cW}" y2="${yTarget.toFixed(1)}"
          stroke="#5DADE2" stroke-width="2" stroke-dasharray="5 3"/>
        <path d="${areaPath}" fill="url(#biAreaGrad)" clip-path="url(#biChartClip)"/>
        <path d="${linePath}" fill="none" stroke="#7BB395" stroke-width="2.8"
          stroke-linecap="round" stroke-linejoin="round" clip-path="url(#biChartClip)"/>
        ${dots}
        ${xLabels}
      </svg>
      <div class="bi-savings-note">
        <span class="bi-savings-dot"></span>
        Ahorro actual:
        <strong style="color:#3d8f60">
          −${ahorroActual.toLocaleString('es-MX',{maximumFractionDigits:0})} m³/ha/ciclo (−${ahorroPct}%)
        </strong>
        respecto a la línea base DR-041 (8,000 m³/ha/ciclo)
      </div>
    </div>`;
  }

  // ── Bar Chart SVG (ETc por cultivo) ────────────────────────────────────────
  function _htmlBarChart(data) {
    const titulo = `<div class="bi-card-title">Demanda Hídrica por Cultivo</div>
      <div class="bi-card-sub">ETc promedio (mm) · ciclo actual</div>`;

    if (!data.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin recomendaciones FAO-56 registradas aún.</div>
      </div>`;
    }

    const W = 400, H = 220, PL = 36, PR = 16, PT = 16, PB = 30;
    const cW = W - PL - PR, cH = H - PT - PB;
    const maxV = Math.max(...data.map(d => d.etc)) * 1.2 || 100;
    const gap  = cW / data.length;
    const bw   = gap * 0.55;

    const gridYs = [0, 200, 400, 600, 800].filter(v => v <= maxV);
    const gridLines = gridYs.map(v => {
      const y = PT + cH - (v / maxV) * cH;
      return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+cW}" y2="${y.toFixed(1)}"
        stroke="rgba(74,59,40,.055)" stroke-width=".8" stroke-dasharray="3 3"/>
        <text x="${PL-5}" y="${(y+4).toFixed(1)}" text-anchor="end"
          font-size="9" fill="#8C7F6E" font-family="Segoe UI">${v}</text>`;
    }).join('');

    const bars = data.map((d, i) => {
      const barH = (d.etc / maxV) * cH;
      const x    = PL + gap * i + (gap - bw) / 2;
      const y    = PT + cH - barH;
      return `
        <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${barH.toFixed(1)}"
          rx="5" fill="${d.color}" opacity=".85"/>
        <text x="${(x+bw/2).toFixed(1)}" y="${(y-5).toFixed(1)}" text-anchor="middle"
          font-size="9" fill="#4A3B28" font-family="Segoe UI" font-weight="600">${d.etc} mm</text>
        <text x="${(x+bw/2).toFixed(1)}" y="${H-6}" text-anchor="middle"
          font-size="11" fill="#8C7F6E" font-family="Segoe UI">${d.crop}</text>`;
    }).join('');

    return `
    <div class="bi-card">
      ${titulo}
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;margin-top:14px">
        ${gridLines}${bars}
      </svg>
    </div>`;
  }

  // ── Donut Chart SVG (método de riego) ──────────────────────────────────────
  function _htmlDonut(data) {
    const titulo = `<div class="bi-card-title">Distribución por Método de Riego</div>
      <div class="bi-card-sub">Eventos bajo cada sistema (%)</div>`;

    if (!data.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin eventos de riego registrados.</div>
      </div>`;
    }

    const CX = 80, CY = 80, R = 62, INNER = 38, SIZE = 160;
    const total = data.reduce((s, d) => s + d.value, 0) || 100;
    let angle = -90;

    const slices = data.map(d => {
      const slice = (d.value / total) * 360;
      const a1 = angle * Math.PI / 180;
      const a2 = (angle + slice - 0.5) * Math.PI / 180;
      const x1 = CX + R * Math.cos(a1),     y1 = CY + R * Math.sin(a1);
      const x2 = CX + R * Math.cos(a2),     y2 = CY + R * Math.sin(a2);
      const xi1 = CX + INNER * Math.cos(a1), yi1 = CY + INNER * Math.sin(a1);
      const xi2 = CX + INNER * Math.cos(a2), yi2 = CY + INNER * Math.sin(a2);
      const lg = slice > 180 ? 1 : 0;
      const path = `M${x1.toFixed(2)},${y1.toFixed(2)} A${R},${R} 0 ${lg},1 ${x2.toFixed(2)},${y2.toFixed(2)} L${xi2.toFixed(2)},${yi2.toFixed(2)} A${INNER},${INNER} 0 ${lg},0 ${xi1.toFixed(2)},${yi1.toFixed(2)} Z`;
      angle += slice;
      return `<path d="${path}" fill="${d.color}" fill-opacity=".88" stroke="#fff" stroke-width="2"/>`;
    }).join('');

    const legend = data.map(d =>
      `<div class="bi-donut-row">
        <span class="bi-donut-dot" style="background:${d.color}"></span>
        <span class="bi-donut-name">${d.name}</span>
        <span class="bi-donut-pct">${d.value}%</span>
      </div>`
    ).join('');

    return `
    <div class="bi-card">
      ${titulo}
      <div class="bi-donut-wrap">
        <svg width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}" style="flex-shrink:0">
          ${slices}
          <text x="${CX}" y="${CY+5}" text-anchor="middle"
            font-size="12" font-weight="700" fill="#4A3B28" font-family="Segoe UI">Total</text>
        </svg>
        <div class="bi-donut-legend">${legend}</div>
      </div>
    </div>`;
  }

  // ── Tabla de eventos recientes ─────────────────────────────────────────────
  function _htmlTable(rows) {
    const STATUS = {
      aceptada:  { bg:'rgba(123,179,149,.12)', color:'#3d8f60', dot:'#7BB395', label:'Aceptada'   },
      modificada:{ bg:'rgba(232,194,125,.16)', color:'#8a6010', dot:'#E8C27D', label:'Modificada' },
      ignorada:  { bg:'rgba(230,57,70,.09)',   color:'#c9303b', dot:'#E63946', label:'Ignorada'   },
      pendiente: { bg:'rgba(142,127,113,.10)', color:'#6b5f55', dot:'#8E7F71', label:'Pendiente'  },
    };
    const ORIGIN = {
      'sistema': { bg:'rgba(93,173,226,.10)',  color:'#2576a8', label:'Sistema' },
      'manual':  { bg:'rgba(142,127,113,.10)', color:'#6b5f55', label:'Manual'  },
      'voz':     { bg:'rgba(192,154,107,.12)', color:'#7a5a2a', label:'Voz IA'  },
    };

    const titulo = `<div class="bi-card-title">Eventos de Riego Recientes</div>
      <div class="bi-card-sub">${rows.length} registros · ordenados por fecha descendente</div>`;

    if (!rows.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline" style="padding:28px 0">
          Sin eventos de riego para esta selección.
        </div>
      </div>`;
    }

    const filas = rows.map(r => {
      const s = STATUS[r.status]  || STATUS['pendiente'];
      const o = ORIGIN[r.origin?.toLowerCase()] || { bg:'rgba(142,127,113,.10)', color:'#6b5f55', label: r.origin || '—' };
      const sobre = r.applied != null && r.applied > 6500;

      return `<tr class="bi-tr">
        <td class="bi-td bi-td--bold">${r.parcel}</td>
        <td class="bi-td"><span class="bi-crop-tag">🌱 ${r.crop}</span></td>
        <td class="bi-td bi-td--mono">${r.date}</td>
        <td class="bi-td bi-td--mono ${sobre ? 'bi-td--over' : r.applied != null ? 'bi-td--ok' : ''}">
          ${r.applied != null ? r.applied.toLocaleString('es-MX',{maximumFractionDigits:0}) + ' m³/ha' : '—'}
          ${sobre ? '<span class="bi-over-tag">↑ sobre meta</span>' : ''}
        </td>
        <td class="bi-td bi-td--mono">${r.lamina != null ? r.lamina : '—'}</td>
        <td class="bi-td">${r.method}</td>
        <td class="bi-td"><span class="bi-badge" style="background:${o.bg};color:${o.color}">${o.label}</span></td>
        <td class="bi-td">
          <span class="bi-badge bi-badge--dot" style="background:${s.bg};color:${s.color}">
            <span class="bi-badge-dot" style="background:${s.dot}"></span>${s.label}
          </span>
        </td>
      </tr>`;
    }).join('');

    return `
    <div class="bi-card bi-card--table">
      <div class="bi-card-header bi-card-header--table">
        <div>${titulo}</div>
      </div>
      <div class="bi-table-scroll">
        <table class="bi-table">
          <thead>
            <tr>
              <th class="bi-th">Parcela</th>
              <th class="bi-th">Cultivo</th>
              <th class="bi-th">Fecha</th>
              <th class="bi-th">Agua Aplicada</th>
              <th class="bi-th">Lámina mm</th>
              <th class="bi-th">Método</th>
              <th class="bi-th">Origen</th>
              <th class="bi-th">Estado</th>
            </tr>
          </thead>
          <tbody>${filas}</tbody>
        </table>
      </div>
    </div>`;
  }

  // ── Estados de carga / error ───────────────────────────────────────────────
  function _showSkeleton(msg) {
    const c = document.getElementById('bi-dashboard-content');
    if (c) c.innerHTML = `<div class="bi-loading"><span class="bi-spinner"></span>${msg}</div>`;
  }

  function _showError(err) {
    const c = document.getElementById('bi-dashboard-content');
    if (c) c.innerHTML = `<div class="bi-error">
      ⚠️ No se pudo conectar con el backend.<br>
      <small>${err.message}</small><br>
      <small style="color:var(--secondary-text)">Verifica que el servidor esté corriendo en localhost:8000.<br>
      Comando: <code>uvicorn backend.main:app --reload</code></small><br><br>
      <button onclick="BI.refresh()" style="
        padding:8px 18px;border:none;border-radius:8px;
        background:var(--primary-green);color:var(--white);
        font-size:0.85rem;font-weight:600;cursor:pointer;font-family:inherit
      ">↺ Reintentar</button>
    </div>`;
    console.error('[MILPÍN BI]', err);
  }

  function _setLoading(on) {
    _state.loading = on;
    const btn = document.getElementById('bi-btn-refresh');
    const cnt = document.getElementById('bi-dashboard-content');
    if (btn) btn.disabled = on;
    if (cnt) cnt.style.opacity = on ? '0.55' : '1';
    if (cnt) cnt.style.transition = 'opacity .2s';
  }

  // ── Utilidades ─────────────────────────────────────────────────────────────
  function _isoWeekLabel(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return `S${week}`;
  }

  function _capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
  }

  // ── API pública ────────────────────────────────────────────────────────────
  return {
    init,
    onFilterChange() {
      const p = document.getElementById('bi-filter-parcela');
      const c = document.getElementById('bi-filter-cultivo');
      _state.selectedParcela = p?.value || 'all';
      _state.selectedCultivo = c?.value || 'all';
      _fetchAndRender();
    },
    refresh() {
      if (!_state.initialized) {
        // Aún no hubo carga exitosa → reintentar init completo
        init();
        return;
      }
      // Carga base ya está OK → solo re-fetch de datos por parcela
      _state.rawData = [];
      _fetchAndRender();
    },
  };
})();
