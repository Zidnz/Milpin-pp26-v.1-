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

  // ── Ciclos agrícolas predefinidos ─────────────────────────────────────────
  const CICLOS_PRESET = {
    'PV-2026':      { desde: '2026-04-01', hasta: '2026-09-15', label: 'PV-2026 (abr–sep 2026)' },
    'OI-2026':      { desde: '2025-10-15', hasta: '2026-03-15', label: 'OI-2026 (oct 2025–mar 2026)' },
    'PV-2025':      { desde: '2025-04-01', hasta: '2025-09-15', label: 'PV-2025 (abr–sep 2025)' },
    'OI-2025':      { desde: '2024-10-15', hasta: '2025-03-15', label: 'OI-2025 (oct 2024–mar 2025)' },
    'anio-2025':    { desde: '2025-01-01', hasta: '2025-12-31', label: 'Año 2025' },
    'anio-2024':    { desde: '2024-01-01', hasta: '2024-12-31', label: 'Año 2024' },
    'ultimos-365':  { desde: null,         hasta: null,         label: 'Últimos 12 meses' },
  };

  // ── Estado interno ─────────────────────────────────────────────────────────
  let _state = {
    initialized:     false,
    loading:         false,
    parcelas:        [],
    cultivos:        [],
    selectedParcela: 'all',
    selectedCultivo: 'all',
    selectedPeriodo: 'PV-2026',
    fechaDesde:      '2026-04-01',
    fechaHasta:      '2026-09-15',
    rawData:         [],
    computed: {
      kpis:      null,
      lineData:  [],
      barData:   [],
      donutData: [],
      costData:  null,
      faoData:   [],
      tableRows: [],
    },
  };

  function _dateQuery() {
    if (!_state.fechaDesde && !_state.fechaHasta) return '';
    const parts = [];
    if (_state.fechaDesde) parts.push(`fecha_desde=${_state.fechaDesde}`);
    if (_state.fechaHasta) parts.push(`fecha_hasta=${_state.fechaHasta}`);
    return '&' + parts.join('&');
  }

  function _parcelasPath() {
    const query = window.MILPIN_AUTH?.getParcelasQuery?.() || '';
    return `/parcelas${query}`;
  }

  // ── Fetch helper ──────────────────────────────────────────────────────────
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

  // ── Init ──────────────────────────────────────────────────────────────────
  async function init() {
    if (!window.MILPIN_AUTH?.getUserId?.()) {
      _showSkeleton('Selecciona un usuario para cargar el dashboard.');
      return;
    }
    if (_state.initialized) return;
    _showSkeleton('Cargando parcelas y cultivos...');
    try {
      [_state.parcelas, _state.cultivos] = await Promise.all([
        _fetch(_parcelasPath()),
        _fetch('/cultivos'),
      ]);
      _state.initialized = true;
      _populateFilters();
      await _fetchAndRender();
    } catch (err) {
      _showError(err);
    }
  }

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

      const dq = _dateQuery();
      _state.rawData = await Promise.all(targets.map(async p => {
        const [kpi, histRiego, recomendaciones] = await Promise.allSettled([
          _fetch(`/parcelas/${p.id_parcela}/kpi?${dq.slice(1)}`),
          _fetch(`/riego/parcela/${p.id_parcela}?limite=50${dq}`),
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

  // ── Cómputo ───────────────────────────────────────────────────────────────
  function _compute() {
    const data          = _state.rawData;
    const cultivoFilter = _state.selectedCultivo;

    const kpisValidos   = data.filter(d => d.kpi).map(d => d.kpi);
    const consumoTotal  = kpisValidos.reduce((s, k) => s + (k.volumen_aplicado_m3_ha || 0), 0);
    const consumoAvg    = kpisValidos.length ? consumoTotal / kpisValidos.length : 0;
    const baselineTotal = kpisValidos.reduce((s, k) => s + (k.baseline_proporcional || BASELINE), 0);
    const baselineAvg   = kpisValidos.length ? baselineTotal / kpisValidos.length : BASELINE;
    const cicloEnCurso  = kpisValidos.some(k => k.ciclo_en_curso === true);
    const fraccionVals  = kpisValidos.map(k => k.fraccion_ciclo).filter(v => v != null);
    const fraccionCiclo = fraccionVals.length
      ? fraccionVals.reduce((a, b) => a + b, 0) / fraccionVals.length
      : null;
    const ahorroM3  = Math.max(0, baselineAvg - consumoAvg);
    const ahorroPct = baselineAvg > 0 ? (ahorroM3 / baselineAvg) * 100 : 0;
    const ahorroMXN = ahorroM3 * TARIFA;

    const todasRecs     = data.flatMap(d => [
      ...(d.recomendaciones.activa   ? [d.recomendaciones.activa]   : []),
      ...(d.recomendaciones.historial || []),
    ]);
    const recsCerradas   = todasRecs.filter(r => r.aceptada !== 'pendiente');
    const recsEjecutadas = todasRecs.filter(r => r.aceptada === 'aceptada' || r.aceptada === 'modificada');
    const tasaAdopcion   = recsCerradas.length > 0
      ? (recsEjecutadas.length / recsCerradas.length) * 100 : 0;

    _state.computed.kpis = {
      consumoAvg:    Math.round(consumoAvg),
      baselineAvg:   Math.round(baselineAvg),
      cicloEnCurso,
      fraccionCiclo,
      ahorroM3:      Math.round(ahorroM3),
      ahorroMXN:     Math.round(ahorroMXN),
      ahorroPct:     Math.round(ahorroPct),
      tasaAdopcion:  Math.round(tasaAdopcion),
      totalRecs:     todasRecs.length,
    };

    const todosRiegos = data.flatMap(d =>
      (d.histRiego || []).map(r => ({ ...r, _nombre: d.parcela.nombre_parcela }))
    );

    const porSemana = {};
    todosRiegos.forEach(r => {
      if (!r.volumen_m3_ha || !r.fecha_riego) return;
      const d = new Date(r.fecha_riego + 'T12:00:00');
      const semNum   = _isoWeekNum(d);
      const semLabel = _isoWeekLabel(d);
      if (!porSemana[semNum]) porSemana[semNum] = { vals: [], label: semLabel, num: semNum };
      porSemana[semNum].vals.push(r.volumen_m3_ha);
    });

    const semanasOrdenadas = Object.values(porSemana).sort((a, b) => a.num - b.num);
    let acumulado = 0;
    _state.computed.lineData = semanasOrdenadas.map(s => {
      const nParcelas  = _state.rawData.length || 1;
      const sumaEventos = s.vals.reduce((a, b) => a + b, 0);
      const volSemana  = sumaEventos / nParcelas;
      acumulado += volSemana;
      return { w: s.label, v: Math.round(acumulado) };
    });

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

    const costAguaBase   = Math.round(baselineAvg * TARIFA);
    const costAguaActual = Math.round(consumoAvg  * TARIFA);
    const costAhorroAgua = Math.max(0, costAguaBase - costAguaActual);
    const costoEnergiaTotal = todosRiegos.reduce((s, r) => s + (r.costo_energia_mxn || 0), 0);
    const nP = _state.rawData.length || 1;
    _state.computed.costData = {
      costAguaBase,
      costAguaActual,
      costAhorroAgua,
      costoEnergiaAvg: Math.round(costoEnergiaTotal / nP),
      ahorroPct: costAguaBase > 0 ? Math.round(costAhorroAgua / costAguaBase * 100) : 0,
    };

    const latestRecs = {};
    data.forEach(d => {
      const recs = [
        ...(d.recomendaciones.activa   ? [d.recomendaciones.activa]   : []),
        ...(d.recomendaciones.historial || []),
      ];
      recs.forEach(r => {
        const key = (r.cultivo || r.parametros_json?.cultivo || '').toLowerCase();
        if (!key) return;
        if (cultivoFilter !== 'all' && key !== cultivoFilter) return;
        if (!latestRecs[key] || r.fecha_generacion > latestRecs[key].fecha_generacion) {
          latestRecs[key] = r;
        }
      });
    });
    _state.computed.faoData = Object.values(latestRecs);

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
          parcel:  r._nombre || '—',
          crop:    rec?.parametros_json?.cultivo || '—',
          date:    r.fecha_riego || '—',
          applied: r.volumen_m3_ha,
          lamina:  r.lamina_mm,
          method:  r.metodo_riego || '—',
          origin:  r.origen_decision || '—',
          status:  rec?.aceptada || '—',
        };
      });
  }

  // ── Render ────────────────────────────────────────────────────────────────
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
      <div class="bi-row-2">
        ${_htmlCostSavings(c.costData, c.kpis)}
        ${_htmlFAO56Status(c.faoData)}
      </div>
      ${_htmlTable(c.tableRows)}
    `;
    container.style.opacity = '1';
  }

  // ── KPI Cards ─────────────────────────────────────────────────────────────
  function _htmlKPIs(k, noData) {
    if (noData || !k) {
      return `<div class="bi-empty-state">
        <span>🌾</span>
        <p>Sin datos de riego registrados para esta selección.<br>
        Registra eventos de riego en el tab <strong>Riego</strong> para ver el dashboard.</p>
      </div>`;
    }

    const consumoColor  = k.ahorroPct >= 25 ? 'var(--green-strong)'
                        : k.ahorroPct >  0  ? 'var(--amber-strong)'
                        : 'var(--red-strong)';
    const adopcionColor = k.tasaAdopcion >= 70 ? 'var(--green-strong)'
                        : k.tasaAdopcion >  0  ? 'var(--amber-strong)'
                        : 'var(--secondary-text)';
    const metaLabel = k.ahorroPct >= 25
      ? `✓ ${k.ahorroPct}% logrado`
      : `${k.ahorroPct}% de meta 25%`;
    const metaColor = k.ahorroPct >= 25 ? 'var(--green-strong)' : 'var(--amber-dark)';

    let baselineLabel;
    if (k.cicloEnCurso) {
      const pct = k.fraccionCiclo != null ? Math.round(k.fraccionCiclo * 100) : '?';
      baselineLabel = `vs ${k.baselineAvg.toLocaleString('es-MX')} m³/ha (${pct}% del ciclo)`;
    } else {
      baselineLabel = 'vs 8,000 m³/ha (ciclo completo)';
    }

    const items = [
      { label: 'Consumo agua',    val: `${k.consumoAvg.toLocaleString('es-MX')} m³/ha`, color: consumoColor,               sub: baselineLabel },
      { label: 'Ahorro estimado', val: `${k.ahorroM3.toLocaleString('es-MX')} m³/ha`,   color: 'var(--green-dark)' },
      { label: 'Ahorro en costo', val: `$${k.ahorroMXN.toLocaleString('es-MX')} MXN`,   color: 'var(--primary-text)' },
      { label: 'Adopción IA',     val: `${k.tasaAdopcion}%`,                             color: adopcionColor },
      { label: 'Recomendaciones', val: `${k.totalRecs}`,                                 color: 'var(--primary-text)' },
      { label: 'Meta ciclo',      val: metaLabel,                                         color: metaColor },
    ];

    const normNote = k.cicloEnCurso
      ? `<div class="bi-norm-note">⏳ Ciclo en curso · datos hasta hoy · baseline prorrateado por días transcurridos</div>`
      : '';

    return `<div class="bi-kpi-grid">
      ${items.map(item => `
        <div class="bi-kpi-card">
          <div class="bi-kpi-label">${item.label}</div>
          <div class="bi-kpi-value" style="color:${item.color}">${item.val}</div>
          ${item.sub ? `<div class="bi-kpi-sub">${item.sub}</div>` : ''}
        </div>`).join('')}
    </div>
    ${normNote}`;
  }

  // ── Line Chart SVG ────────────────────────────────────────────────────────
  function _htmlLineChart(data) {
    const periodoLabel = document.getElementById('bi-filter-periodo')?.selectedOptions[0]?.text || '';
    const titulo = `<div class="bi-card-title">Consumo Acumulado vs. Línea Base DR-041</div>
      <div class="bi-card-sub">m³/ha acumulado por semana · ${periodoLabel}</div>`;

    if (!data.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin registros de riego para graficar.</div>
      </div>`;
    }

    const W = 860, H = 220, PL = 56, PR = 20, PT = 14, PB = 34;
    const cW = W - PL - PR, cH = H - PT - PB;

    const maxConsumo = data[data.length - 1]?.v || BASELINE;
    const maxV = Math.ceil(Math.max(maxConsumo, BASELINE) * 1.08 / 500) * 500;
    const minV = 0;

    const toX = i => PL + (i / Math.max(data.length - 1, 1)) * cW;
    const toY = v => PT + cH - ((Math.min(v, maxV) - minV) / (maxV - minV)) * cH;

    const nSem = data.length;
    const baselineAcum = (i) => BASELINE * ((i + 1) / nSem);
    const targetAcum   = (i) => 6000    * ((i + 1) / nSem);

    const pts = data.map((d, i) => [toX(i), toY(d.v)]);
    let linePath = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const cx = (pts[i][0] + pts[i + 1][0]) / 2;
      linePath += ` C${cx.toFixed(1)},${pts[i][1].toFixed(1)} ${cx.toFixed(1)},${pts[i+1][1].toFixed(1)} ${pts[i+1][0].toFixed(1)},${pts[i+1][1].toFixed(1)}`;
    }
    const areaPath     = `${linePath} L${toX(nSem-1)},${PT+cH} L${toX(0)},${PT+cH} Z`;
    const baselinePath = data.map((_, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(baselineAcum(i)).toFixed(1)}`).join(' ');
    const targetPath   = data.map((_, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(targetAcum(i)).toFixed(1)}`).join(' ');

    const gridYs = Array.from({length: 6}, (_, i) =>
      Math.round((maxV / 5) * i / 500) * 500
    ).filter(v => v <= maxV);
    const gridLines = gridYs.map(v => {
      const y = toY(v);
      return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+cW}" y2="${y.toFixed(1)}"
        stroke="rgba(74,59,40,.05)" stroke-width="0.8" stroke-dasharray="3 3"/>
        <text x="${PL-7}" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="10"
          fill="#8C7F6E" font-family="Segoe UI">${(v/1000).toFixed(1)}k</text>`;
    }).join('');

    const dots = pts.map(([x, y]) =>
      `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="#7BB395" stroke="#fff" stroke-width="1.5"/>`
    ).join('');

    const xLabels = data.map((d, i) => {
      const show = data.length <= 10 || i % Math.ceil(data.length / 10) === 0 || i === data.length - 1;
      return show ? `<text x="${toX(i).toFixed(1)}" y="${H-6}" text-anchor="middle"
        font-size="10" fill="#8C7F6E" font-family="Segoe UI">${d.w}</text>` : '';
    }).join('');

    const consumoFinal  = data[data.length - 1]?.v || 0;
    const ahorroFinal   = Math.max(0, BASELINE - consumoFinal);
    const ahorroPct     = Math.round((ahorroFinal / BASELINE) * 100);
    const sobreBaseline = consumoFinal > BASELINE;

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
            <span class="bi-legend-line bi-legend-line--dash" style="background:rgba(74,59,40,.3)"></span>Base 8,000
          </span>
        </div>
      </div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
        <defs>
          <linearGradient id="biAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#7BB395" stop-opacity=".15"/>
            <stop offset="100%" stop-color="#7BB395" stop-opacity=".01"/>
          </linearGradient>
          <clipPath id="biChartClip">
            <rect x="${PL}" y="${PT}" width="${cW}" height="${cH}"/>
          </clipPath>
        </defs>
        ${gridLines}
        <path d="${targetPath}" fill="none" stroke="#5DADE2" stroke-width="1.8"
          stroke-dasharray="5 3" clip-path="url(#biChartClip)"/>
        <path d="${baselinePath}" fill="none" stroke="rgba(74,59,40,.25)" stroke-width="1.5"
          stroke-dasharray="6 4" clip-path="url(#biChartClip)"/>
        <path d="${areaPath}" fill="url(#biAreaGrad)" clip-path="url(#biChartClip)"/>
        <path d="${linePath}" fill="none" stroke="#7BB395" stroke-width="2.8"
          stroke-linecap="round" stroke-linejoin="round" clip-path="url(#biChartClip)"/>
        ${dots}
        ${xLabels}
      </svg>
      <div class="bi-savings-note">
        <span class="bi-savings-dot" style="background:${sobreBaseline ? '#E63946' : '#7BB395'}"></span>
        Consumo final del período:
        <strong style="color:${sobreBaseline ? '#c9303b' : '#3d8f60'}">
          ${consumoFinal.toLocaleString('es-MX')} m³/ha
          ${sobreBaseline
            ? `(+${(consumoFinal - BASELINE).toLocaleString('es-MX')} sobre base 8,000)`
            : `· ahorro ${ahorroFinal.toLocaleString('es-MX')} m³/ha (${ahorroPct}% vs base)`}
        </strong>
      </div>
    </div>`;
  }

  // ── Bar Chart SVG (ETc por cultivo) ───────────────────────────────────────
  function _htmlBarChart(data) {
    const titulo = `<div class="bi-card-title">Demanda Hídrica por Cultivo</div>
      <div class="bi-card-sub">ETc promedio (mm/día) · recomendaciones FAO-56</div>`;

    if (!data.length) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin recomendaciones FAO-56 registradas aún.</div>
      </div>`;
    }

    const W = 400, H = 220, PL = 36, PR = 16, PT = 16, PB = 30;
    const cW = W - PL - PR, cH = H - PT - PB;
    const maxV = Math.max(...data.map(d => d.etc)) * 1.2 || 10;
    const gap  = cW / data.length;
    const bw   = gap * 0.55;

    const gridYs = [0, 2, 4, 6, 8, 10].filter(v => v <= maxV);
    const gridLines = gridYs.map(v => {
      const y = PT + cH - (v / maxV) * cH;
      return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${PL+cW}" y2="${y.toFixed(1)}"
        stroke="rgba(74,59,40,.055)" stroke-width=".8" stroke-dasharray="3 3"/>
        <text x="${PL-5}" y="${(y+4).toFixed(1)}" text-anchor="end"
          font-size="9" fill="#8C7F6E" font-family="Segoe UI">${v}</text>`;
    }).join('');

    const bars = data.map((d, i) => {
      const barH = Math.max(0, (d.etc / maxV) * cH);
      const x    = PL + gap * i + (gap - bw) / 2;
      const y    = PT + cH - barH;
      return `
        <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${barH.toFixed(1)}"
          rx="5" fill="${d.color}" opacity=".85"/>
        <text x="${(x+bw/2).toFixed(1)}" y="${(y-5).toFixed(1)}" text-anchor="middle"
          font-size="9" fill="#4A3B28" font-family="Segoe UI" font-weight="600">${d.etc} mm/d</text>
        <text x="${(x+bw/2).toFixed(1)}" y="${H-6}" text-anchor="middle"
          font-size="11" fill="#8C7F6E" font-family="Segoe UI">${d.crop}</text>`;
    }).join('');

    return `
    <div class="bi-card">
      ${titulo}
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;margin-top:14px">
        ${gridLines}${bars}
      </svg>
    </div>`;
  }

  // ── Donut Chart (método de riego) ─────────────────────────────────────────
  // FIX RESPONSIVO: bi-donut-wrap usa flex-wrap para apilar en pantallas angostas.
  // El SVG NO lleva width/height fijos — el CSS controla el tamaño máximo.
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
      const x1  = CX + R     * Math.cos(a1), y1  = CY + R     * Math.sin(a1);
      const x2  = CX + R     * Math.cos(a2), y2  = CY + R     * Math.sin(a2);
      const xi1 = CX + INNER * Math.cos(a1), yi1 = CY + INNER * Math.sin(a1);
      const xi2 = CX + INNER * Math.cos(a2), yi2 = CY + INNER * Math.sin(a2);
      const lg  = slice > 180 ? 1 : 0;
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
        <svg viewBox="0 0 ${SIZE} ${SIZE}" class="bi-donut-svg">
          ${slices}
          <text x="${CX}" y="${CY+5}" text-anchor="middle"
            font-size="12" font-weight="700" fill="#4A3B28" font-family="Segoe UI">Total</text>
        </svg>
        <div class="bi-donut-legend">${legend}</div>
      </div>
    </div>`;
  }

  // ── Cost Savings: barras horizontales responsivas ──────────────────────────
  // FIX RESPONSIVO: viewBox + width="100%" — el SVG escala a cualquier ancho.
  function _htmlCostSavings(cost, kpis) {
    const titulo = `<div class="bi-card-title">Ahorro en Costo de Agua</div>
      <div class="bi-card-sub">MXN/ha · tarifa CFE 9-CU $1.68/m³</div>`;

    if (!cost || !kpis) {
      return `<div class="bi-card">${titulo}
        <div class="bi-empty-inline">Sin datos de consumo registrados.</div>
      </div>`;
    }

    // Coordenadas internas del SVG — el viewBox hace que escalen solos en el DOM
    const PL = 88, barW = 220, rowH = 32, gap = 10, PT = 12, labelW = 110;
    const totalW = PL + barW + labelW;
    const maxVal = Math.max(cost.costAguaBase, 1);

    const rows = [
      { label: 'Base DR-041', val: cost.costAguaBase,   color: 'rgba(74,59,40,.2)', mxn: cost.costAguaBase   },
      { label: 'Actual',      val: cost.costAguaActual,  color: '#5DADE2',           mxn: cost.costAguaActual  },
      { label: 'Ahorro',      val: cost.costAhorroAgua,  color: '#7BB395',           mxn: cost.costAhorroAgua  },
    ];

    const svgH = PT + rows.length * (rowH + gap) + gap;

    const barsSvg = rows.map((r, i) => {
      const bw     = Math.max(4, (r.val / maxVal) * barW);
      const y      = PT + i * (rowH + gap);
      const valStr = `$${r.mxn.toLocaleString('es-MX')}`;
      return `
        <text x="${PL - 8}" y="${y + rowH / 2 + 4}" text-anchor="end"
          font-size="11" fill="#8C7F6E" font-family="Segoe UI">${r.label}</text>
        <rect x="${PL}" y="${y}" width="${bw.toFixed(1)}" height="${rowH}"
          rx="6" fill="${r.color}"/>
        <text x="${PL + bw + 8}" y="${y + rowH / 2 + 4}" text-anchor="start"
          font-size="11" fill="#4A3B28" font-family="Segoe UI" font-weight="600">${valStr}</text>`;
    }).join('');

    const metaColor = kpis.ahorroPct >= 25 ? 'var(--green-dark)' : 'var(--amber-dark)';

    return `
    <div class="bi-card">
      ${titulo}
      <svg viewBox="0 0 ${totalW} ${svgH}" width="100%" style="display:block;margin-top:10px;overflow:visible">
        ${barsSvg}
      </svg>
      <div class="bi-meta-note" style="color:${metaColor}">
        — ${kpis.ahorroPct}% de ahorro · meta del ciclo: 25%
      </div>
    </div>`;
  }

  // ── FAO-56 Status table ───────────────────────────────────────────────────
  function _htmlFAO56Status(data) {
    const titulo = `<div class="bi-card-title">Estado Motor FAO-56</div>
      <div class="bi-card-sub">Última recomendación por cultivo · Penman-Monteith</div>`;

    if (!data.length) {
      return `<div class="bi-card bi-card--table">
        <div class="bi-card-header bi-card-header--table">${titulo}</div>
        <div class="bi-empty-inline">Sin recomendaciones FAO-56 activas.</div>
      </div>`;
    }

    const CROP_EMOJI = {
      maíz: '🌽', maiz: '🌽',
      frijol: '🫘',
      algodón: '🌿', algodon: '🌿',
      uva: '🍇',
      chile: '🌶️',
    };

    const maxDef = Math.max(...data.map(d => d.deficit_acumulado_mm || 0), 1);

    const rows = data.map(r => {
      const key    = (r.cultivo || r.parametros_json?.cultivo || '').toLowerCase();
      const emoji  = CROP_EMOJI[key] || '🌾';
      const nombre = r.cultivo || r.parametros_json?.cultivo || key;
      const eto    = r.eto_referencia    != null ? r.eto_referencia.toFixed(1)    : '—';
      const etc    = r.etc_calculada     != null ? r.etc_calculada.toFixed(1)     : '—';
      const kc     = r.kc               != null ? Number(r.kc).toFixed(2)        : '—';
      const def    = r.deficit_acumulado_mm != null ? r.deficit_acumulado_mm.toFixed(0) : '—';
      const defPct = r.deficit_acumulado_mm != null
        ? Math.min(100, (r.deficit_acumulado_mm / maxDef) * 100) : 0;

      return `<tr class="bi-fao-tr">
        <td class="bi-fao-td"><span style="margin-right:5px">${emoji}</span>${_capitalize(nombre)}</td>
        <td class="bi-fao-td bi-fao-mono">${eto} mm/d</td>
        <td class="bi-fao-td bi-fao-mono">${etc} mm/d</td>
        <td class="bi-fao-td bi-fao-mono">${kc}</td>
        <td class="bi-fao-td">
          <div class="bi-def-wrap"><div class="bi-def-bar" style="width:${defPct.toFixed(0)}%"></div></div>
          <span class="bi-fao-mono" style="font-size:0.72rem">${def} mm</span>
        </td>
      </tr>`;
    }).join('');

    return `
    <div class="bi-card bi-card--table">
      <div class="bi-card-header bi-card-header--table">${titulo}</div>
      <div class="bi-table-scroll">
        <table class="bi-fao-table" style="width:100%;border-collapse:collapse">
          <thead>
            <tr>
              <th class="bi-th">CULTIVO</th>
              <th class="bi-th">ETO</th>
              <th class="bi-th">ETC</th>
              <th class="bi-th">KC</th>
              <th class="bi-th">DÉFICIT</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="bi-fao-footnote" style="padding:8px 18px">
        ETc = ETo × Kc (Allen et al. 1998) · Déficit = lámina que se debe reponer
      </div>
    </div>`;
  }

  // ── Tabla de eventos recientes ────────────────────────────────────────────
  function _htmlTable(rows) {
    if (!rows.length) return '';

    const STATUS_MAP = {
      aceptada:  { label: 'Regó',      color: 'var(--green-dark)',      bg: 'rgba(123,179,149,.15)' },
      modificada: { label: 'Modificó', color: 'var(--amber-dark)',      bg: 'rgba(245,166,35,.12)' },
      ignorada:  { label: 'No regó',   color: 'var(--red-dark)',        bg: 'var(--red-bg-badge)' },
      pendiente: { label: 'Pendiente', color: 'var(--secondary-text)',  bg: 'var(--accent-bg)' },
    };

    const trs = rows.map(r => {
      const st    = STATUS_MAP[r.status] || STATUS_MAP.pendiente;
      const vol   = r.applied != null ? `${r.applied.toLocaleString('es-MX')} m³/ha` : '—';
      const lam   = r.lamina  != null ? `${Number(r.lamina).toFixed(1)} mm` : '—';
      const fecha = r.date !== '—'
        ? new Date(r.date + 'T12:00:00').toLocaleDateString('es-MX', { day: 'numeric', month: 'short', year: '2-digit' })
        : '—';
      const isOver = r.applied != null && r.lamina != null && r.applied > r.lamina * 10 * 1.15;

      return `<tr class="bi-tr">
        <td class="bi-td bi-td--bold">${r.parcel}</td>
        <td class="bi-td"><span class="bi-crop-tag">${r.crop}</span></td>
        <td class="bi-td bi-td--mono">${fecha}</td>
        <td class="bi-td bi-td--mono ${isOver ? 'bi-td--over' : 'bi-td--ok'}">${vol}${isOver ? '<span class="bi-over-tag">↑</span>' : ''}</td>
        <td class="bi-td bi-td--mono">${lam}</td>
        <td class="bi-td">${r.method}</td>
        <td class="bi-td">
          <span class="bi-badge" style="background:${st.bg};color:${st.color}">
            <span class="bi-badge-dot" style="background:${st.color}"></span>${st.label}
          </span>
        </td>
      </tr>`;
    }).join('');

    return `
    <div class="bi-card bi-card--table" style="margin-top:16px">
      <div class="bi-card-header bi-card-header--table">
        <div class="bi-card-title">Historial de Eventos de Riego</div>
        <div class="bi-card-sub">Últimos 25 registros · por fecha descendente</div>
      </div>
      <div class="bi-table-scroll bi-table-scroll--capped">
        <table class="bi-table">
          <thead>
            <tr>
              <th class="bi-th bi-th--sticky">PARCELA</th>
              <th class="bi-th bi-th--sticky">CULTIVO</th>
              <th class="bi-th bi-th--sticky">FECHA</th>
              <th class="bi-th bi-th--sticky">VOLUMEN</th>
              <th class="bi-th bi-th--sticky">LÁMINA</th>
              <th class="bi-th bi-th--sticky">MÉTODO</th>
              <th class="bi-th bi-th--sticky">DECISIÓN</th>
            </tr>
          </thead>
          <tbody>${trs}</tbody>
        </table>
      </div>
    </div>`;
  }

  // ── Helpers de UI ─────────────────────────────────────────────────────────
  function _showSkeleton(msg) {
    const el = document.getElementById('bi-dashboard-content');
    if (el) el.innerHTML = `<div class="bi-loading"><div class="bi-spinner"></div>${msg}</div>`;
  }

  function _showError(err) {
    const el = document.getElementById('bi-dashboard-content');
    if (el) el.innerHTML = `<div class="bi-error">⚠ Error al cargar el dashboard:<br>
      <strong>${err.message}</strong><br><br>
      Verifica que el backend esté activo en localhost:8000.</div>`;
  }

  function _setLoading(on) {
    _state.loading = on;
    const btn = document.getElementById('bi-refresh-btn');
    if (btn) btn.disabled = on;
  }

  function _isoWeekNum(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
    return d.getUTCFullYear() * 100 + week;
  }

  function _isoWeekLabel(date) {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
    return `S${week}`;
  }

  function _capitalize(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : str;
  }

  // ── API pública ───────────────────────────────────────────────────────────
  return {
    init,
    onFilterChange() {
      const selP = document.getElementById('bi-filter-parcela');
      const selC = document.getElementById('bi-filter-cultivo');
      if (selP) _state.selectedParcela = selP.value;
      if (selC) _state.selectedCultivo = selC.value;
      _fetchAndRender();
    },
    onPeriodoChange() {
      const selPer = document.getElementById('bi-filter-periodo');
      if (!selPer) return;
      const val = selPer.value;
      _state.selectedPeriodo = val;

      const customRow = document.getElementById('bi-custom-dates');
      if (val === 'personalizado') {
        if (customRow) customRow.style.display = 'flex';
        return;
      }
      if (customRow) customRow.style.display = 'none';

      if (CICLOS_PRESET[val]) {
        const preset = CICLOS_PRESET[val];
        if (val === 'ultimos-365') {
          const hoy = new Date();
          _state.fechaHasta = hoy.toISOString().slice(0, 10);
          const hace1year = new Date(hoy);
          hace1year.setFullYear(hoy.getFullYear() - 1);
          _state.fechaDesde = hace1year.toISOString().slice(0, 10);
        } else {
          _state.fechaDesde = preset.desde;
          _state.fechaHasta = preset.hasta;
        }
      }
      _fetchAndRender();
    },
    onCustomDateChange() {
      const desde = document.getElementById('bi-filter-desde')?.value;
      const hasta  = document.getElementById('bi-filter-hasta')?.value;
      if (desde) _state.fechaDesde = desde;
      if (hasta)  _state.fechaHasta = hasta;
      _fetchAndRender();
    },
    refresh() {
      _state.initialized = false;
      _state.rawData     = [];
      init();
    },
  };

})();
