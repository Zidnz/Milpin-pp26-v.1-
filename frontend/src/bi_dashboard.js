// bi_dashboard.js — Vista Análisis (Power BI-style, Chart.js 4.x)
// Conectado a: /api/parcelas, /api/parcelas/{id}/kpi,
//              /api/riego/parcela/{id}, /api/recomendaciones/parcela/{id}

const BI = (() => {
  'use strict';

  const API      = 'https://milpin-pp26-v-1.onrender.com/api';
  const BASELINE = 8000;
  const TARIFA   = 1.68;

  const METHOD_COLORS = {
    'gravedad':       '#5C6BC0',
    'goteo':          '#00897B',
    'aspersión':      '#FB8C00', 'aspersion':      '#FB8C00',
    'microaspersión': '#8D6E63', 'microaspersion': '#8D6E63',
  };
  const METHOD_EFF = {
    'gravedad': 60, 'goteo': 90,
    'aspersión': 75, 'aspersion': 75,
    'microaspersión': 80, 'microaspersion': 80,
  };

  const CICLOS_PRESET = {
    'PV-2026':    { desde: '2026-04-01', hasta: '2026-09-15', label: 'PV-2026 (abr–sep 2026)' },
    'OI-2026':    { desde: '2025-10-15', hasta: '2026-03-15', label: 'OI-2026 (oct 2025–mar 2026)' },
    'PV-2025':    { desde: '2025-04-01', hasta: '2025-09-15', label: 'PV-2025 (abr–sep 2025)' },
    'OI-2025':    { desde: '2024-10-15', hasta: '2025-03-15', label: 'OI-2025 (oct 2024–mar 2025)' },
    'anio-2025':  { desde: '2025-01-01', hasta: '2025-12-31', label: 'Año 2025' },
    'anio-2024':  { desde: '2024-01-01', hasta: '2024-12-31', label: 'Año 2024' },
    'ultimos-365':{ desde: null,         hasta: null,         label: 'Últimos 12 meses' },
  };

  // ── Estado ───────────────────────────────────────────────────────────────────
  let _state = {
    initialized:     false,
    loading:         false,
    parcelas:        [],
    cultivos:        [],
    selectedParcela: 'all',
    selectedCultivo: 'all',
    selectedPeriodo: 'PV-2026',
    selectedModulo:  'all',
    fechaDesde:      '2026-04-01',
    fechaHasta:      '2026-09-15',
    rawData:         [],
    computed: {
      kpis:       null,
      lineData:   { labels: [], real: [], objetivo: [] },
      barData:    [],
      donutData:  [],
      donutEff:   0,
      tableRows:  [],
      alertCount: 0,
    },
  };

  // ── Chart.js instances ───────────────────────────────────────────────────────
  let _charts = {};

  function _destroyCharts() {
    Object.values(_charts).forEach(c => { try { c?.destroy(); } catch (_e) {} });
    _charts = {};
  }

  // Tooltip singleton en body (evita clipping por overflow:hidden en cards)
  function _getTooltipEl() {
    let el = document.getElementById('bi2-float-tooltip');
    if (!el) {
      el = document.createElement('div');
      el.id = 'bi2-float-tooltip';
      el.className = 'bi2-float-tooltip';
      el.style.display = 'none';
      document.body.appendChild(el);
    }
    return el;
  }

  // ── Fetch ────────────────────────────────────────────────────────────────────
  async function _fetch(path, timeoutMs = 10000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API}${path}`, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status} — ${path}`);
      return res.json();
    } catch (err) {
      if (err.name === 'AbortError') throw new Error(`Timeout (${timeoutMs/1000}s) — ${path}`);
      throw err;
    } finally { clearTimeout(t); }
  }

  function _dateQuery() {
    const p = [];
    if (_state.fechaDesde) p.push(`fecha_desde=${_state.fechaDesde}`);
    if (_state.fechaHasta) p.push(`fecha_hasta=${_state.fechaHasta}`);
    return p.length ? '&' + p.join('&') : '';
  }

  function _parcelasPath() {
    const q = window.MILPIN_AUTH?.getParcelasQuery?.() || '';
    return `/parcelas${q}`;
  }

  function _periodoLabel() {
    return CICLOS_PRESET[_state.selectedPeriodo]?.label || _state.selectedPeriodo;
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  async function init() {
    if (!window.MILPIN_AUTH?.getUserId?.()) {
      _showSkeleton('Selecciona un usuario para cargar el dashboard.');
      return;
    }
    if (_state.initialized) return;
    _showSkeleton('Cargando datos del distrito…');
    try {
      [_state.parcelas, _state.cultivos] = await Promise.all([
        _fetch(_parcelasPath()),
        _fetch('/cultivos'),
      ]);
      _state.initialized = true;
      await _fetchAndRender();
    } catch (err) { _showError(err); }
  }

  async function _fetchAndRender() {
    _setLoading(true);
    try {
      const targets = _state.selectedParcela === 'all'
        ? _state.parcelas
        : _state.parcelas.filter(p => p.id_parcela === _state.selectedParcela);

      if (!targets.length) { _showError(new Error('No hay parcelas disponibles.')); return; }

      const dq = _dateQuery();
      _state.rawData = await Promise.all(targets.map(async p => {
        const [kpi, histRiego, recs] = await Promise.allSettled([
          _fetch(`/parcelas/${p.id_parcela}/kpi?${dq.slice(1)}`),
          _fetch(`/riego/parcela/${p.id_parcela}?limite=50${dq}`),
          _fetch(`/recomendaciones/parcela/${p.id_parcela}`),
        ]);
        return {
          parcela:         p,
          kpi:             kpi.status === 'fulfilled'   ? kpi.value   : null,
          histRiego:       histRiego.status === 'fulfilled' ? histRiego.value : [],
          recomendaciones: recs.status === 'fulfilled'  ? recs.value  : { activa: null, historial: [] },
        };
      }));
      _compute();
      _render();
    } catch (err) { _showError(err); }
    finally { _setLoading(false); }
  }

  // ── Compute ──────────────────────────────────────────────────────────────────
  function _compute() {
    const data  = _state.rawData;
    const culFil = _state.selectedCultivo;
    const modFil = _state.selectedModulo;

    const filtered = modFil === 'all'
      ? data
      : data.filter(d => (d.parcela.modulo || '').toLowerCase() === modFil.toLowerCase());

    // KPIs
    const kpisOk   = filtered.filter(d => d.kpi).map(d => d.kpi);
    const cAvg     = kpisOk.length ? kpisOk.reduce((s,k)=>s+(k.volumen_aplicado_m3_ha||0),0)/kpisOk.length : 0;
    const bAvg     = kpisOk.length ? kpisOk.reduce((s,k)=>s+(k.baseline_proporcional||BASELINE),0)/kpisOk.length : BASELINE;
    const ahorro   = Math.max(0, bAvg - cAvg);
    const cicloEnCurso = kpisOk.some(k=>k.ciclo_en_curso);
    const fracVals = kpisOk.map(k=>k.fraccion_ciclo).filter(v=>v!=null);
    const fraccion = fracVals.length ? fracVals.reduce((a,b)=>a+b)/fracVals.length : null;

    const todasRecs = filtered.flatMap(d=>[
      ...(d.recomendaciones.activa?[d.recomendaciones.activa]:[]),
      ...(d.recomendaciones.historial||[]),
    ]);
    const cerradas   = todasRecs.filter(r=>r.aceptada!=='pendiente');
    const ejecutadas = todasRecs.filter(r=>r.aceptada==='aceptada'||r.aceptada==='modificada');
    const adopcion   = cerradas.length ? Math.round(ejecutadas.length/cerradas.length*100) : 0;

    const alertasActivas = filtered.filter(d=> {
      const def = d.recomendaciones?.activa?.deficit_acumulado_mm||0;
      return def>25 || d.recomendaciones?.activa?.urgencia==='critico';
    }).length;

    _state.computed.kpis = {
      consumoAvg:    Math.round(cAvg),
      baselineAvg:   Math.round(bAvg),
      cicloEnCurso,
      fraccion,
      ahorroM3:      Math.round(ahorro),
      ahorroMXN:     Math.round(ahorro * TARIFA),
      ahorroPct:     bAvg>0 ? Math.round(ahorro/bAvg*100) : 0,
      tasaAdopcion:  adopcion,
      alertasActivas,
    };

    // Timeseries semanal
    const todosRiegos = filtered.flatMap(d=>(d.histRiego||[]).map(r=>({...r,_p:d.parcela.nombre_parcela})));
    const porSemana = {};
    todosRiegos.forEach(r=>{
      if (!r.volumen_m3_ha||!r.fecha_riego) return;
      const d = new Date(r.fecha_riego+'T12:00:00');
      const num = _weekNum(d);
      const lbl = _weekLabel(d);
      if (!porSemana[num]) porSemana[num]={vals:[],lbl,num};
      porSemana[num].vals.push(r.volumen_m3_ha);
    });
    const semanas = Object.values(porSemana).sort((a,b)=>a.num-b.num);
    const nSem = semanas.length||1;
    const weekObj = Math.round(6000/nSem);
    _state.computed.lineData = {
      labels:  semanas.map(s=>s.lbl),
      real:    semanas.map(s=>Math.round(s.vals.reduce((a,b)=>a+b,0)/(filtered.length||1))),
      objetivo:semanas.map(()=>weekObj),
    };

    // Compliance por cultivo
    const cropMap = {};
    filtered.forEach(d=>{
      const recIdx = {};
      [...(d.recomendaciones.activa?[d.recomendaciones.activa]:[]),
        ...(d.recomendaciones.historial||[])].forEach(r=>{if(r.id_recomendacion) recIdx[r.id_recomendacion]=r;});
      (d.histRiego||[]).forEach(r=>{
        const rec = r.id_recomendacion ? recIdx[r.id_recomendacion] : null;
        const cv  = (rec?.parametros_json?.cultivo||'').toLowerCase();
        if (!cv) return;
        if (culFil!=='all'&&cv!==culFil.toLowerCase()) return;
        if (!cropMap[cv]) cropMap[cv]={nombre:rec.parametros_json.cultivo,dentro:0,sobre:0};
        const lRec = rec?.lamina_recomendada||rec?.lamina_mm;
        if (lRec&&r.lamina_mm) {
          if (r.lamina_mm<=lRec*1.15) cropMap[cv].dentro++;
          else                         cropMap[cv].sobre++;
        } else { cropMap[cv].dentro++; }
      });
    });
    _state.computed.barData = Object.values(cropMap).map(v=>{
      const tot=v.dentro+v.sobre||1;
      return { crop:_cap(v.nombre), compliance:Math.round(v.dentro/tot*100), overIrrigation:Math.round(v.sobre/tot*100) };
    }).sort((a,b)=>a.compliance-b.compliance);

    if (!_state.computed.barData.length) {
      _state.computed.barData = ['Maíz','Frijol','Algodón','Uva','Chile'].map(c=>({crop:c,compliance:0,overIrrigation:0}));
    }

    // Donut
    const porMetodo = {};
    todosRiegos.forEach(r=>{ const m=(r.metodo_riego||'desconocido').toLowerCase(); porMetodo[m]=(porMetodo[m]||0)+1; });
    const totEv = Object.values(porMetodo).reduce((a,b)=>a+b,0)||1;
    _state.computed.donutData = Object.entries(porMetodo)
      .map(([m,cnt])=>({ name:_cap(m), value:Math.round(cnt/totEv*100), color:METHOD_COLORS[m]||'#9E9E9E' }))
      .sort((a,b)=>b.value-a.value);
    if (!_state.computed.donutData.length) _state.computed.donutData=[{name:'Sin datos',value:100,color:'#E0E0E0'}];

    const totPct = _state.computed.donutData.reduce((s,d)=>s+d.value,0)||100;
    _state.computed.donutEff = Math.round(
      _state.computed.donutData.reduce((s,d)=>s+(METHOD_EFF[d.name.toLowerCase()]||70)*(d.value/totPct),0)
    );

    // Tabla operacional
    _state.computed.tableRows = filtered.map(d=>{
      const activa = d.recomendaciones?.activa;
      const lastR  = (d.histRiego||[]).slice().sort((a,b)=>new Date(b.fecha_riego)-new Date(a.fecha_riego))[0];
      const deficit = activa?.deficit_acumulado_mm||0;
      const lRec    = activa?.lamina_recomendada||activa?.lamina_mm;
      const lApl    = lastR?.lamina_mm||0;
      const sobre   = lRec&&lApl>lRec ? Math.round((lApl-lRec)/lRec*100) : 0;
      const urg     = activa?.urgencia||'preventivo';
      let estado    = 'normal';
      if (deficit>30||urg==='critico')      estado='alerta';
      else if (activa?.aceptada==='pendiente') estado='pendiente';
      const cultivo = activa?.parametros_json?.cultivo||'—';
      if (culFil!=='all'&&cultivo.toLowerCase()!==culFil.toLowerCase()) return null;
      return {
        parcela:   d.parcela.nombre_parcela||'—',
        modulo:    d.parcela.modulo||'—',
        cultivo:   _cap(cultivo),
        etapa:     activa?.etapa_fenologica||'—',
        ultimoRiego: lastR?.fecha_riego||null,
        deficitMm: Math.round(deficit*10)/10,
        sobreRiegoPct: sobre,
        estado,
        urgNum: urg==='critico'?3:urg==='moderado'?2:urg==='preventivo'?1:0,
      };
    })
    .filter(Boolean)
    .sort((a,b)=>b.urgNum-a.urgNum||b.deficitMm-a.deficitMm)
    .slice(0,10);

    _state.computed.alertCount = _state.computed.tableRows.filter(r=>r.estado==='alerta').length;
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  function _render() {
    _destroyCharts();
    const container = document.getElementById('bi-dashboard-content');
    if (!container) return;
    const c   = _state.computed;
    const noD = !c.kpis;

    // Ocultar barra de filtros legacy
    document.querySelector('.bi-filters-bar')?.style.setProperty('display','none');

    const donutLegendHtml = c.donutData.map(d=>`
      <div class="bi2-dleg-item">
        <span class="bi2-dleg-dot" style="background:${d.color};"></span>
        <span class="bi2-dleg-name">${d.name}</span>
        <span class="bi2-dleg-pct">${d.value}%</span>
      </div>`).join('');

    container.innerHTML = `
      ${_htmlKPIs(c.kpis, noD)}

      <div class="bi2-mid-grid">
        <!-- Zona C: Gráfica Principal -->
        <div class="bi2-card bi2-main-chart-card">
          <div class="bi2-card-hdr">
            <div>
              <div class="bi2-card-title">Consumo Real vs Objetivo FAO-56</div>
              <div class="bi2-card-sub">m³/ha por semana · ${_periodoLabel()}</div>
            </div>
            <div class="bi2-legend">
              <span class="bi2-leg-item">
                <span class="bi2-leg-line" style="background:#2196F3;"></span>Consumo real
              </span>
              <span class="bi2-leg-item">
                <span class="bi2-leg-dashed" style="border-color:#FB8C00;"></span>Objetivo FAO-56
              </span>
              <span class="bi2-leg-item">
                <span class="bi2-leg-swatch"></span>Sobre-riego
              </span>
            </div>
          </div>
          <div class="bi2-chart-wrap bi2-chart-wrap--main">
            <canvas id="bi2-chart-main"></canvas>
          </div>
        </div>

        <!-- Sidebar: Filtros + D1 + D2 -->
        <aside class="bi2-sidebar">

          <!-- Zona B: Filtros -->
          <div class="bi2-card bi2-filter-card">
            <div class="bi2-card-title bi2-card-title--sm" style="padding:14px 16px 10px;">Filtros</div>

            <div class="bi2-fgrp">
              <label class="bi2-flabel" for="bi2-sel-ciclo">Ciclo agrícola</label>
              <select id="bi2-sel-ciclo" class="bi2-fsel">
                ${Object.entries(CICLOS_PRESET).map(([v,p])=>
                  `<option value="${v}"${_state.selectedPeriodo===v?' selected':''}>${v}</option>`
                ).join('')}
              </select>
            </div>

            <div class="bi2-fgrp">
              <label class="bi2-flabel">Cultivo</label>
              <div class="bi2-ms" id="bi2-ms-wrap">
                <button class="bi2-ms-trigger" id="bi2-ms-trigger" type="button">
                  <span id="bi2-ms-display">${_cultiDoc()}</span>
                  <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
                </button>
                <div class="bi2-ms-drop" id="bi2-ms-drop">
                  <label class="bi2-ms-opt">
                    <input type="checkbox" id="bi2-cul-all" value="all"${_state.selectedCultivo==='all'?' checked':''}> Todos
                  </label>
                  ${['Maíz','Frijol','Algodón','Uva','Chile'].map(c=>`
                  <label class="bi2-ms-opt">
                    <input type="checkbox" class="bi2-cul-cb" value="${c}"
                      ${_state.selectedCultivo!=='all'&&_state.selectedCultivo===c.toLowerCase()?' checked':''}> ${c}
                  </label>`).join('')}
                </div>
              </div>
            </div>

            <div class="bi2-fgrp">
              <label class="bi2-flabel" for="bi2-sel-mod">Módulo</label>
              <select id="bi2-sel-mod" class="bi2-fsel">
                <option value="all"${_state.selectedModulo==='all'?' selected':''}>Todos los módulos</option>
                ${['3A','3B','3C','3D'].map(m=>`<option value="${m}"${_state.selectedModulo===m?' selected':''}>${m}</option>`).join('')}
              </select>
            </div>

            <div class="bi2-badge-row">
              <span class="bi2-ms-badge${window.MILPIN_AUTH?.getUserId?.()?'':' bi2-ms-badge--off'}">
                <span class="bi2-ms-bdot"></span>
                ${window.MILPIN_AUTH?.getUserId?.() ? 'MILPIN ACTIVO' : 'SIN MILPIN'}
              </span>
            </div>
          </div>

          <!-- Zona D1: Cumplimiento FAO-56 por Cultivo -->
          <div class="bi2-card">
            <div class="bi2-card-hdr bi2-card-hdr--sm">
              <div class="bi2-card-title bi2-card-title--sm">Cumplimiento FAO-56 por Cultivo</div>
            </div>
            <div class="bi2-chart-wrap bi2-chart-wrap--bars">
              <canvas id="bi2-chart-bars"></canvas>
            </div>
          </div>

          <!-- Zona D2: Distribución Sistemas de Riego -->
          <div class="bi2-card">
            <div class="bi2-card-hdr bi2-card-hdr--sm">
              <div class="bi2-card-title bi2-card-title--sm">Distribución de Sistemas de Riego</div>
            </div>
            <div class="bi2-donut-wrap">
              <div class="bi2-donut-canvas">
                <canvas id="bi2-chart-donut"></canvas>
                <div class="bi2-donut-center">
                  <span class="bi2-donut-pct">${c.donutEff||'—'}%</span>
                  <span class="bi2-donut-lbl">Eficiencia</span>
                </div>
              </div>
              <div class="bi2-donut-legend">${donutLegendHtml}</div>
            </div>
          </div>

        </aside>
      </div>

      ${_htmlTable(c.tableRows, c.alertCount)}
      ${_htmlAnomaliasCardSkeleton()}
    `;

    container.style.opacity = '1';

    requestAnimationFrame(()=>{
      _initMainChart(c.lineData);
      _initBarsChart(c.barData);
      _initDonutChart(c.donutData);
      _bindFilters();
      _cargarAnomaliasML();
    });
  }

  // ── KPI Strip ────────────────────────────────────────────────────────────────
  function _htmlKPIs(k, noData) {
    if (noData||!k) return `<div class="bi-empty-state"><span>🌾</span>
      <p>Sin datos de riego registrados.<br>Registra eventos en el tab <strong>Riego</strong>.</p></div>`;

    const kpis = [
      {
        label:'Consumo Promedio', value:k.consumoAvg.toLocaleString('es-MX'), unit:'m³/ha',
        accent:'#2196F3',
        tClass: k.consumoAvg < BASELINE ? 'good':'bad',
        tIcon:  k.consumoAvg < BASELINE ? '↓':'↑',
        tText:  `vs ${k.baselineAvg.toLocaleString('es-MX')} m³/ha base`,
      },
      {
        label:'Ahorro Acumulado', value:k.ahorroM3.toLocaleString('es-MX'), unit:'m³/ha',
        accent:'#43A047',
        tClass: k.ahorroM3>0 ? 'good':'neutral',
        tIcon:  k.ahorroM3>0 ? '↑':'—',
        tText:  `${k.ahorroPct}% vs línea base DR-041`,
      },
      {
        label:'Ahorro Económico', value:`$${k.ahorroMXN.toLocaleString('es-MX')}`, unit:'MXN',
        accent:'#00897B',
        tClass: k.ahorroMXN>0 ? 'good':'neutral',
        tIcon:  k.ahorroMXN>0 ? '↑':'—',
        tText:  `CFE $${TARIFA}/m³`,
      },
      {
        label:'Cumplimiento FAO-56', value:k.tasaAdopcion, unit:'%',
        accent: k.tasaAdopcion>=70 ? '#43A047' : k.tasaAdopcion>=40 ? '#FB8C00' : '#E53935',
        tClass: k.tasaAdopcion>=70 ? 'good' : k.tasaAdopcion>=40 ? 'warn':'bad',
        tIcon:  k.tasaAdopcion>=70 ? '✓' : k.tasaAdopcion>=40 ? '△':'⚠',
        tText:  k.tasaAdopcion>=70 ? 'Meta superada' : k.tasaAdopcion>=40 ? 'En progreso':'Bajo la meta',
      },
      {
        label:'Alertas Activas', value:k.alertasActivas, unit:'parcelas',
        accent: k.alertasActivas===0 ? '#43A047':'#E53935',
        tClass: k.alertasActivas===0 ? 'good':'bad',
        tIcon:  k.alertasActivas===0 ? '✓':'⚠',
        tText:  k.alertasActivas===0 ? 'Sin alertas':'Requieren atención',
      },
    ];

    return `<div class="bi2-kpi-strip">
      ${kpis.map(kpi=>`
        <div class="bi2-kpi-card">
          <span class="bi2-kpi-accent" style="background:${kpi.accent};"></span>
          <div class="bi2-kpi-label">${kpi.label}</div>
          <div class="bi2-kpi-value">${kpi.value} <span class="bi2-kpi-unit">${kpi.unit}</span></div>
          <div class="bi2-kpi-trend bi2-kpi-trend--${kpi.tClass}">
            <span>${kpi.tIcon}</span><span>${kpi.tText}</span>
          </div>
        </div>`).join('')}
    </div>`;
  }

  // ── Chart.js: dual-line main ─────────────────────────────────────────────────
  function _initMainChart(ld) {
    const canvas = document.getElementById('bi2-chart-main');
    if (!canvas||typeof Chart==='undefined') return;
    const tip = _getTooltipEl();

    _charts.main = new Chart(canvas, {
      type:'line',
      data:{
        labels: ld.labels,
        datasets:[
          {
            label:'Consumo real',
            data: ld.real,
            borderColor:'#2196F3', borderWidth:2.5,
            pointRadius:4, pointBackgroundColor:'#2196F3',
            pointBorderColor:'#fff', pointBorderWidth:1.5,
            tension:0.35,
            fill:{ target:1, above:'rgba(229,57,53,0.13)', below:'rgba(33,150,243,0.06)' },
          },
          {
            label:'Objetivo FAO-56',
            data: ld.objetivo,
            borderColor:'#FB8C00', borderWidth:2,
            borderDash:[8,6], pointRadius:0,
            tension:0, fill:false,
          },
        ],
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ display:false },
          tooltip:{
            enabled:false,
            external:({chart,tooltip})=>{
              if (tooltip.opacity===0){ tip.style.display='none'; return; }
              const i   = tooltip.dataPoints[0].dataIndex;
              const real= ld.real[i];
              const obj = ld.objetivo[i];
              const lbl = ld.labels[i];
              const sobre= real>obj ? Math.round(((real/obj)-1)*100) : 0;
              tip.innerHTML=`
                <div class="bi2-tt-hd">Semana ${lbl}</div>
                <div class="bi2-tt-row">
                  <span class="bi2-tt-lbl">Consumo real</span>
                  <strong>${real.toLocaleString('es-MX')} m³/ha</strong>
                </div>
                <div class="bi2-tt-row">
                  <span class="bi2-tt-lbl">Objetivo FAO-56</span>
                  <strong>${obj.toLocaleString('es-MX')} m³/ha</strong>
                </div>
                ${sobre>0
                  ?`<div class="bi2-tt-alert">⚠ Sobre-riego: +${sobre}%</div>`
                  :`<div class="bi2-tt-ok">✓ Dentro del objetivo</div>`}
              `;
              const cr = chart.canvas.getBoundingClientRect();
              let lx = cr.left + tooltip.caretX + 14;
              let ty = cr.top  + tooltip.caretY - 70;
              if (lx+210 > window.innerWidth) lx = cr.left + tooltip.caretX - 220;
              if (ty < 8) ty = cr.top + tooltip.caretY + 14;
              tip.style.cssText=`display:block;left:${lx}px;top:${ty}px;`;
            },
          },
        },
        scales:{
          x:{ grid:{ color:'rgba(0,0,0,0.04)', drawTicks:false },
              ticks:{ font:{family:"'Inter','Segoe UI',sans-serif",size:10}, color:'#9EAAB8', maxRotation:0, autoSkip:true, maxTicksLimit:12 },
              border:{ display:false } },
          y:{ grid:{ color:'rgba(0,0,0,0.04)' }, beginAtZero:true,
              ticks:{ font:{family:"'Inter','Segoe UI',sans-serif",size:10}, color:'#9EAAB8',
                      callback: v=> v>=1000?`${(v/1000).toFixed(1)}k`:v },
              border:{ display:false } },
        },
      },
    });
  }

  // ── Chart.js: stacked bars ───────────────────────────────────────────────────
  function _initBarsChart(bd) {
    const canvas = document.getElementById('bi2-chart-bars');
    if (!canvas||typeof Chart==='undefined') return;
    const labels = bd.map(d=>d.crop);

    _charts.bars = new Chart(canvas,{
      type:'bar',
      data:{
        labels,
        datasets:[
          { label:'Cumplimiento FAO-56', data:bd.map(d=>d.compliance),
            backgroundColor:'rgba(67,160,71,0.82)',
            borderRadius:{topLeft:0,topRight:0,bottomLeft:3,bottomRight:3}, stack:'s' },
          { label:'Sobre-riego', data:bd.map(d=>d.overIrrigation),
            backgroundColor:'rgba(229,57,53,0.80)',
            borderRadius:{topLeft:3,topRight:3,bottomLeft:0,bottomRight:0}, stack:'s' },
          { type:'line', label:'Umbral 10%', data:Array(labels.length).fill(10),
            borderColor:'#FB8C00', borderWidth:1.5, borderDash:[4,3],
            pointRadius:0, fill:false, order:-1 },
        ],
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        onClick:(evt,els)=>{
          if (!els.length) return;
          const cv = labels[els[0].index].toLowerCase();
          _state.selectedCultivo = cv;
          document.getElementById('bi2-ms-display')?.textContent && (document.getElementById('bi2-ms-display').textContent = _cultiDoc());
          _compute(); _render();
        },
        plugins:{
          legend:{ display:false },
          tooltip:{ callbacks:{
            title: i=>i[0].label,
            label: i=> i.dataset.label==='Umbral 10%'?null:`${i.dataset.label}: ${i.raw}%`,
          }, backgroundColor:'rgba(22,34,48,0.90)',
            titleFont:{family:"'Inter','Segoe UI',sans-serif",size:11},
            bodyFont: {family:"'Inter','Segoe UI',sans-serif",size:11} },
        },
        scales:{
          x:{ stacked:true, grid:{display:false},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:9.5},color:'#9EAAB8',maxRotation:0},
              border:{display:false} },
          y:{ stacked:true, max:100, min:0,
              grid:{color:'rgba(0,0,0,0.04)'},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:9},color:'#9EAAB8',
                     callback:v=>`${v}%`,stepSize:25},
              border:{display:false} },
        },
      },
    });
  }

  // ── Chart.js: donut ──────────────────────────────────────────────────────────
  function _initDonutChart(dd) {
    const canvas = document.getElementById('bi2-chart-donut');
    if (!canvas||typeof Chart==='undefined') return;

    _charts.donut = new Chart(canvas,{
      type:'doughnut',
      data:{
        labels: dd.map(d=>d.name),
        datasets:[{
          data:            dd.map(d=>d.value),
          backgroundColor: dd.map(d=>d.color),
          borderWidth:2, borderColor:'#fff', hoverBorderColor:'#fff', hoverOffset:4,
        }],
      },
      options:{
        responsive:true, maintainAspectRatio:true, cutout:'65%',
        plugins:{
          legend:{ display:false },
          tooltip:{ callbacks:{ label: i=>`${i.label}: ${i.raw}%` },
            backgroundColor:'rgba(22,34,48,0.90)',
            titleFont:{family:"'Inter','Segoe UI',sans-serif",size:11},
            bodyFont: {family:"'Inter','Segoe UI',sans-serif",size:11} },
        },
      },
    });
  }

  // ── Tabla operacional ────────────────────────────────────────────────────────
  function _htmlTable(rows, alertCount) {
    const badge = alertCount===0
      ? `<span class="bi2-abadge bi2-abadge--zero">Sin alertas</span>`
      : `<span class="bi2-abadge">${alertCount} alerta${alertCount>1?'s':''}</span>`;

    const trs = rows.map(r=>{
      const rowCls = r.estado==='alerta' ? 'bi2-row--alert' : r.estado==='pendiente' ? 'bi2-row--pend' : '';
      const fecha  = r.ultimoRiego
        ? new Date(r.ultimoRiego+'T12:00:00').toLocaleDateString('es-MX',{day:'2-digit',month:'short'})
        : '—';
      const dCls = r.deficitMm>40?'bi2-n--d':r.deficitMm>20?'bi2-n--w':'bi2-n--m';
      const sCls = r.sobreRiegoPct>30?'bi2-n--d':r.sobreRiegoPct>10?'bi2-n--w':'bi2-n--ok';
      const eLbl = r.estado==='alerta'?'⚠ Alerta':r.estado==='pendiente'?'⏳ Pendiente':'✓ Normal';
      const eCls = r.estado==='alerta'?'bi2-est--a':r.estado==='pendiente'?'bi2-est--p':'bi2-est--ok';
      return `<tr class="${rowCls}">
        <td class="bi2-td bi2-td--bold">${r.parcela}</td>
        <td class="bi2-td bi2-td--muted">${r.modulo}</td>
        <td class="bi2-td"><span class="bi2-ctag">${r.cultivo}</span></td>
        <td class="bi2-td bi2-td--muted">${r.etapa}</td>
        <td class="bi2-td bi2-td--mono">${fecha}</td>
        <td class="bi2-td bi2-td--num ${dCls}">${r.deficitMm} mm</td>
        <td class="bi2-td bi2-td--num ${sCls}">${r.sobreRiegoPct>0?'+':''}${r.sobreRiegoPct}%</td>
        <td class="bi2-td"><span class="bi2-estat ${eCls}">${eLbl}</span></td>
      </tr>`;
    }).join('') || `<tr><td colspan="8" class="bi2-empty">Sin datos operacionales para esta selección.</td></tr>`;

    return `<div class="bi2-card bi2-table-card">
      <div class="bi2-card-hdr">
        <div>
          <div class="bi2-card-title">Tabla Operacional de Alertas</div>
          <div class="bi2-card-sub">Ordenado por urgencia y déficit · máx. 10 parcelas activas</div>
        </div>
        ${badge}
      </div>
      <div class="bi2-tscroll">
        <table class="bi2-table">
          <thead><tr>
            <th>Parcela</th><th>Módulo</th><th>Cultivo</th><th>Etapa</th>
            <th>Último Riego</th>
            <th class="bi2-th-num">Déficit mm</th>
            <th class="bi2-th-num">Sobre-riego %</th>
            <th>Estado Recomendación</th>
          </tr></thead>
          <tbody>${trs}</tbody>
        </table>
      </div>
    </div>`;
  }

  // ── Bind sidebar filters ─────────────────────────────────────────────────────
  function _bindFilters() {
    const selCiclo = document.getElementById('bi2-sel-ciclo');
    if (selCiclo) selCiclo.addEventListener('change', ()=>{
      const v = selCiclo.value;
      _state.selectedPeriodo = v;
      if (v==='ultimos-365') {
        const hoy=new Date(); _state.fechaHasta=hoy.toISOString().slice(0,10);
        const yr=new Date(hoy); yr.setFullYear(hoy.getFullYear()-1);
        _state.fechaDesde=yr.toISOString().slice(0,10);
      } else if (CICLOS_PRESET[v]) {
        _state.fechaDesde=CICLOS_PRESET[v].desde;
        _state.fechaHasta=CICLOS_PRESET[v].hasta;
      }
      // Sync legacy top filter
      const lp=document.getElementById('bi-filter-periodo'); if(lp) lp.value=v;
      _fetchAndRender();
    });

    const selMod = document.getElementById('bi2-sel-mod');
    if (selMod) selMod.addEventListener('change', ()=>{
      _state.selectedModulo = selMod.value;
      _compute(); _render();
    });

    const wrap    = document.getElementById('bi2-ms-wrap');
    const trigger = document.getElementById('bi2-ms-trigger');
    const drop    = document.getElementById('bi2-ms-drop');
    if (trigger&&drop&&wrap) {
      trigger.addEventListener('click', e=>{ e.stopPropagation(); wrap.classList.toggle('bi2-ms--open'); });

      function closeMs(e) {
        if (!wrap.contains(e.target)) { wrap.classList.remove('bi2-ms--open'); document.removeEventListener('click',closeMs); }
      }
      document.addEventListener('click', closeMs);

      const allCb = document.getElementById('bi2-cul-all');
      if (allCb) allCb.addEventListener('change', ()=>{
        if (allCb.checked) {
          document.querySelectorAll('.bi2-cul-cb').forEach(c=>c.checked=false);
          _state.selectedCultivo='all';
          _refreshAndFetch();
        }
      });
      document.querySelectorAll('.bi2-cul-cb').forEach(cb=>cb.addEventListener('change', ()=>{
        const checked=[...document.querySelectorAll('.bi2-cul-cb:checked')];
        const allBox=document.getElementById('bi2-cul-all');
        if (checked.length===0) { if(allBox) allBox.checked=true; _state.selectedCultivo='all'; }
        else { if(allBox) allBox.checked=false; _state.selectedCultivo=checked[0].value.toLowerCase(); }
        _refreshAndFetch();
      }));
    }
  }

  function _cultiDoc() {
    return _state.selectedCultivo==='all' ? 'Todos los cultivos' : _cap(_state.selectedCultivo);
  }

  function _refreshAndFetch() {
    const el=document.getElementById('bi-filter-cultivo'); if(el) el.value=_state.selectedCultivo;
    _fetchAndRender();
  }

  // ── Anomalías ML ─────────────────────────────────────────────────────────────
  const _svgRadar = `<svg viewBox="0 0 24 24" fill="none" width="16" height="16" style="flex-shrink:0">
    <circle cx="12" cy="12" r="2" fill="currentColor"/>
    <path d="M12 2a10 10 0 0 1 0 20A10 10 0 0 1 12 2" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="3 3"/>
    <path d="M12 6a6 6 0 0 1 0 12A6 6 0 0 1 12 6" stroke="currentColor" stroke-width="1.5" fill="none" stroke-dasharray="2 2"/>
    <path d="M20 12h-3M7 12H4M12 4v3M12 20v-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>`;

  function _anomSeverity(score) {
    if (score <= -0.35) return { cls: 'alta',  label: 'Alta',  color: '#e63946' };
    if (score <= -0.15) return { cls: 'media', label: 'Media', color: '#FB8C00' };
    return                     { cls: 'leve',  label: 'Leve',  color: '#d4b000' };
  }

  function _htmlAnomaliasCardSkeleton() {
    return `<div class="bi-anomalias-card" id="bi-anomalias-card" style="margin-top:14px;">
      <div class="bi-anomalias-header">
        <div class="bi-anomalias-header-left">
          <span class="bi-anomalias-icon">${_svgRadar}</span>
          <div>
            <div class="bi-anomalias-titulo">Detección de Anomalías</div>
            <div class="bi-anomalias-subtitulo">Isolation Forest · ciclos parcela × ciclo agrícola</div>
          </div>
        </div>
        <span class="bi-anomalias-badge" id="bi-anom-badge">
          <span class="bi-spinner bi-spinner--sm"></span>
        </span>
      </div>
      <div id="bi-anomalias-body">
        <div class="bi-anomalias-loading">
          <span class="bi-spinner"></span>
          <span>Analizando ciclos de riego…</span>
        </div>
      </div>
      <div class="bi-anomalias-disclaimer">
        <svg viewBox="0 0 24 24" fill="none" width="11" height="11" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/><path d="M12 8v4M12 16h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <span>Modelo entrenado con datos sintéticos · P=0.586 · R=0.466 · F1=0.519. No usar para decisiones operativas sin validación con datos reales del DR-041.</span>
      </div>
    </div>`;
  }

  async function _cargarAnomaliasML() {
    const body  = document.getElementById('bi-anomalias-body');
    const badge = document.getElementById('bi-anom-badge');
    if (!body) return;
    try {
      const res = await fetch(`${API}/ml/anomalias?solo_anomalias=true&limit=8`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const anoms = data.resultados || [];
      const tot   = data.total_anomalias || 0;
      const total = data.total_pares_analizados || 0;
      const pct   = data.pct_anomalias || 0;

      if (badge) {
        if (tot === 0) {
          badge.innerHTML = '✓ Sin anomalías';
          badge.className = 'bi-anomalias-badge bi-anomalias-badge--ok';
        } else {
          badge.innerHTML = `${tot}<span class="bi-anom-badge-sep">/</span>${total} <span class="bi-anom-badge-pct">${pct}%</span>`;
          badge.className = 'bi-anomalias-badge';
        }
      }

      if (!anoms.length) {
        body.innerHTML = `<div class="bi-anomalias-empty">
          <svg viewBox="0 0 24 24" fill="none" width="28" height="28"><path d="M9 12l2 2 4-4" stroke="var(--primary-green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="9" stroke="var(--primary-green)" stroke-width="1.5"/></svg>
          <span>Ningún ciclo presenta anomalías detectadas.</span>
        </div>`;
        return;
      }

      body.innerHTML = `<div class="bi-anomalias-lista">${anoms.map(a => {
        const sev   = _anomSeverity(a.anomaly_score);
        const score = a.anomaly_score.toFixed(3);
        const id    = a.id_parcela.slice(0, 8);
        const feat  = a.feature_principal;
        return `<div class="bi-anom-fila bi-anom-fila--${sev.cls}">
          <div class="bi-anom-accent"></div>
          <div class="bi-anom-content">
            <div class="bi-anom-top">
              <div class="bi-anom-info">
                <span class="bi-anom-id">${id}&hellip;</span>
                <span class="bi-anom-ciclo">${a.ciclo_agricola} &middot; ${a.n_eventos} riegos</span>
              </div>
              <span class="bi-anom-sev-badge bi-anom-sev--${sev.cls}">${sev.label}</span>
            </div>
            <div class="bi-anom-bottom">
              <span class="bi-anom-feature-tag">${feat}</span>
              <span class="bi-anom-score-pill" style="color:${sev.color}">IF ${score}</span>
            </div>
          </div>
        </div>`;
      }).join('')}</div>`;
    } catch (_e) {
      if (body) body.innerHTML = `<div class="bi-anomalias-loading bi-anomalias-loading--err">
        <svg viewBox="0 0 24 24" fill="none" width="18" height="18"><circle cx="12" cy="12" r="9" stroke="#e63946" stroke-width="1.5"/><path d="M12 8v4M12 16h.01" stroke="#e63946" stroke-width="2" stroke-linecap="round"/></svg>
        <span>Sin conexión con el endpoint ML.</span>
      </div>`;
      if (badge) { badge.innerHTML = 'Sin conexión'; badge.className = 'bi-anomalias-badge'; }
    }
  }

  // ── Utils ────────────────────────────────────────────────────────────────────
  function _showSkeleton(msg) {
    const el=document.getElementById('bi-dashboard-content');
    if (el) el.innerHTML=`<div class="bi-loading"><div class="bi-spinner"></div>${msg}</div>`;
  }
  function _showError(err) {
    const el=document.getElementById('bi-dashboard-content');
    if (el) el.innerHTML=`<div class="bi-error">⚠ ${err.message}<br><br>
      Verifica que el backend esté activo en localhost:8000.</div>`;
  }
  function _setLoading(on) { _state.loading=on; }

  function _weekNum(date) {
    const d=new Date(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate()));
    d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));
    const ys=new Date(Date.UTC(d.getUTCFullYear(),0,1));
    return d.getUTCFullYear()*100+Math.ceil(((d-ys)/86400000+1)/7);
  }
  function _weekLabel(date) {
    const d=new Date(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate()));
    d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));
    const ys=new Date(Date.UTC(d.getUTCFullYear(),0,1));
    return `S${Math.ceil(((d-ys)/86400000+1)/7)}`;
  }
  function _cap(s){ return s?s.charAt(0).toUpperCase()+s.slice(1):s; }

  // ── Vista Ejecutiva Comparativa 2025 vs 2026 (Página 2 / tab Análisis) ──────

  const CULTIVO_COLORS = {
    'Chile':'#EF5350','Frijol':'#66BB6A','Algodón':'#FFA726',
    'Maíz':'#4FC3F7','Uva':'#AB47BC',
  };

  let _compData = null;

  function _syntheticComp() {
    const bubbleDatasets = [
      { id:'PAR-001',c:'Chile',  ef:82,sr:18,ha:35.5},
      { id:'PAR-002',c:'Frijol', ef:82,sr:12,ha:26.6},
      { id:'PAR-003',c:'Frijol', ef:80,sr:25,ha:7.3 },
      { id:'PAR-004',c:'Frijol', ef:82,sr:22,ha:31.4},
      { id:'PAR-005',c:'Algodón',ef:65,sr:35,ha:21.0},
      { id:'PAR-006',c:'Chile',  ef:80,sr:20,ha:13.8},
      { id:'PAR-007',c:'Algodón',ef:82,sr:22,ha:31.8},
      { id:'PAR-008',c:'Frijol', ef:65,sr:30,ha:8.8 },
      { id:'PAR-009',c:'Maíz',   ef:65,sr:38,ha:21.1},
      { id:'PAR-010',c:'Uva',    ef:90,sr:8, ha:15.0},
      { id:'PAR-011',c:'Maíz',   ef:80,sr:28,ha:42.1},
      { id:'PAR-012',c:'Uva',    ef:90,sr:5, ha:15.6},
      { id:'PAR-013',c:'Algodón',ef:80,sr:26,ha:13.7},
      { id:'PAR-014',c:'Maíz',   ef:65,sr:42,ha:43.4},
      { id:'PAR-015',c:'Chile',  ef:65,sr:32,ha:28.8},
      { id:'PAR-016',c:'Frijol', ef:80,sr:15,ha:15.6},
      { id:'PAR-017',c:'Maíz',   ef:65,sr:36,ha:26.5},
      { id:'PAR-018',c:'Chile',  ef:80,sr:28,ha:44.4},
      { id:'PAR-019',c:'Maíz',   ef:90,sr:10,ha:40.6},
      { id:'PAR-020',c:'Chile',  ef:82,sr:22,ha:24.5},
    ];
    const grouped = {};
    bubbleDatasets.forEach(p=>{
      if (!grouped[p.c]) grouped[p.c]={ label:p.c, data:[], backgroundColor:CULTIVO_COLORS[p.c]+'BB' };
      grouped[p.c].data.push({ x:p.ef, y:p.sr, r:Math.max(4, Math.sqrt(p.ha)*1.9), _id:p.id });
    });
    return {
      kpis:{ ahorroM3:4253006, ahorroMXN:7145050, ahorroKwh:1312480, ahorroCO2:596, mejoraPct:24.9 },
      barData:[
        { cultivo:'Maíz',    c25:9000, c26:6500, obj:6500 },
        { cultivo:'Frijol',  c25:8750, c26:6700, obj:6700 },
        { cultivo:'Algodón', c25:8150, c26:6300, obj:6300 },
        { cultivo:'Uva',     c25:9500, c26:7150, obj:7150 },
        { cultivo:'Chile',   c25:8800, c26:6900, obj:7000 },
      ],
      bubbleDatasets: Object.values(grouped),
      moduleData:[
        { mod:'3A', consumo:6820, cumpl:74, alertas:2, acept:68, rechazo:14 },
        { mod:'3B', consumo:6950, cumpl:69, alertas:4, acept:62, rechazo:18 },
        { mod:'3C', consumo:6640, cumpl:78, alertas:1, acept:75, rechazo:10 },
        { mod:'3D', consumo:6730, cumpl:71, alertas:3, acept:66, rechazo:16 },
      ],
    };
  }

  async function _initComp() {
    const container = document.getElementById('bi-dashboard-content');
    if (container) container.innerHTML = `<div class="bi-loading"><span class="bi-spinner"></span>Cargando análisis comparativo 2025–2026…</div>`;

    // Intentar enriquecer scatter con datos reales de parcelas
    try {
      if (!_state.parcelas.length) {
        _state.parcelas = await _fetch(_parcelasPath()).catch(()=>[]);
      }
    } catch(_) {}

    _compData = _syntheticComp();

    // Si tenemos parcelas reales, reconstruir bubble con datos de eficiencia reales
    if (_state.parcelas.length) {
      const grouped = {};
      _state.parcelas.forEach(p=>{
        const c = _cap(p.cultivo_actual||'');
        if (!c) return;
        const ef  = Math.round((p.eficiencia_riego_2026||p.eficiencia_riego||0.75)*100);
        const sr  = Math.round(Math.max(0, (1 - (p.eficiencia_riego_2026||0.75))*60));
        const ha  = p.superficie_ha||10;
        if (!grouped[c]) grouped[c] = { label:c, data:[], backgroundColor:(CULTIVO_COLORS[c]||'#9E9E9E')+'BB' };
        grouped[c].data.push({ x:ef, y:sr, r:Math.max(4, Math.sqrt(ha)*1.9), _id:p.id_parcela });
      });
      if (Object.keys(grouped).length) {
        _compData.bubbleDatasets = Object.values(grouped);
      }
    }

    _renderAnalisis();
  }

  function _renderAnalisis() {
    _destroyCharts();
    const container = document.getElementById('bi-dashboard-content');
    if (!container) return;

    const d = _compData || _syntheticComp();
    const k = d.kpis;

    container.innerHTML = `
      <!-- Fila 1: 4 KPIs comparativos -->
      <div class="bi2-kpi-strip bi2-kpi-strip--comp">
        ${_htmlCompKPI('Ahorro vs 2025',    k.ahorroM3.toLocaleString('es-MX'),               'm³',  '#4FC3F7', `↓ ${k.mejoraPct}% en consumo total`)}
        ${_htmlCompKPI('Ahorro Económico',  `$${(k.ahorroMXN/1e6).toFixed(2)} M`,              'MXN', '#66BB6A', `@ $${TARIFA}/m³ (CFE 9-CU)`)}
        ${_htmlCompKPI('Ahorro Energético', (k.ahorroKwh/1e3).toFixed(0)+' k',                'kWh', '#FFA726', 'Bombeo 80 m · DR-041')}
        ${_htmlCompKPI('CO₂ Equivalente',   k.ahorroCO2.toLocaleString('es-MX'),               'ton', '#EF5350', '0.454 kg CO₂/kWh factor CFE')}
      </div>

      <!-- Fila 2: Barras agrupadas + Scatter/Bubble -->
      <div class="bi2-comp-row">

        <div class="bi2-card bi2-comp-main">
          <div class="bi2-card-hdr">
            <div>
              <div class="bi2-card-title">Consumo por Cultivo — PV-2025 vs PV-2026</div>
              <div class="bi2-card-sub">m³/ha · con línea objetivo FAO-56 por cultivo</div>
            </div>
            <div class="bi2-legend">
              <span class="bi2-leg-item"><span class="bi2-leg-line" style="background:#FFA726;"></span>2025</span>
              <span class="bi2-leg-item"><span class="bi2-leg-line" style="background:#4FC3F7;"></span>2026</span>
              <span class="bi2-leg-item"><span class="bi2-leg-dashed" style="border-color:#66BB6A;"></span>Objetivo</span>
            </div>
          </div>
          <div class="bi2-chart-wrap bi2-chart-wrap--comp">
            <canvas id="bi2-chart-grouped"></canvas>
          </div>
        </div>

        <div class="bi2-card bi2-comp-side">
          <div class="bi2-card-hdr bi2-card-hdr--sm">
            <div class="bi2-card-title bi2-card-title--sm">Eficiencia vs Sobre-riego por Parcela</div>
            <div class="bi2-card-sub">PV-2026 · tamaño = superficie ha · color = cultivo</div>
          </div>
          <div class="bi2-chart-wrap bi2-chart-wrap--bubble">
            <canvas id="bi2-chart-bubble"></canvas>
          </div>
        </div>

      </div>

      <!-- Fila 3: Tabla resumen por módulo -->
      ${_htmlModuleTable(d.moduleData)}
    `;

    requestAnimationFrame(()=>{
      _initGroupedChart(d.barData);
      _initBubbleChart(d.bubbleDatasets);
    });
  }

  function _htmlCompKPI(label, value, unit, color, sub) {
    return `<div class="bi2-kpi-card">
      <span class="bi2-kpi-accent" style="background:${color};"></span>
      <div class="bi2-kpi-label">${label}</div>
      <div class="bi2-kpi-value">${value} <span class="bi2-kpi-unit">${unit}</span></div>
      <div class="bi2-kpi-trend bi2-kpi-trend--good"><span>↑</span><span>${sub}</span></div>
    </div>`;
  }

  function _initGroupedChart(barData) {
    const canvas = document.getElementById('bi2-chart-grouped');
    if (!canvas||typeof Chart==='undefined') return;
    const labels = barData.map(d=>d.cultivo);
    _charts.grouped = new Chart(canvas,{
      type:'bar',
      data:{
        labels,
        datasets:[
          { label:'PV-2025', data:barData.map(d=>d.c25),
            backgroundColor:'rgba(255,167,38,0.82)',
            borderRadius:{topLeft:3,topRight:3,bottomLeft:0,bottomRight:0},
            barPercentage:0.72 },
          { label:'PV-2026', data:barData.map(d=>d.c26),
            backgroundColor:'rgba(79,195,247,0.82)',
            borderRadius:{topLeft:3,topRight:3,bottomLeft:0,bottomRight:0},
            barPercentage:0.72 },
          { type:'line', label:'Objetivo FAO-56', data:barData.map(d=>d.obj),
            borderColor:'#66BB6A', borderWidth:2, borderDash:[6,4],
            pointRadius:0, fill:false, order:-1 },
        ],
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{ display:false },
          tooltip:{
            callbacks:{
              label: i=>{
                if(i.dataset.label==='Objetivo FAO-56') return `Objetivo: ${i.raw.toLocaleString('es-MX')} m³/ha`;
                return `${i.dataset.label}: ${i.raw.toLocaleString('es-MX')} m³/ha`;
              },
            },
            backgroundColor:'rgba(22,34,48,0.90)',
            titleFont:{family:"'Inter','Segoe UI',sans-serif",size:11},
            bodyFont: {family:"'Inter','Segoe UI',sans-serif",size:11},
          },
        },
        scales:{
          x:{ grid:{display:false},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:11},color:'#9EAAB8'},
              border:{display:false} },
          y:{ beginAtZero:false, min:4500,
              grid:{color:'rgba(0,0,0,0.05)'},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:10},color:'#9EAAB8',
                     callback:v=>`${(v/1000).toFixed(0)}k`},
              border:{display:false} },
        },
      },
    });
  }

  function _initBubbleChart(datasets) {
    const canvas = document.getElementById('bi2-chart-bubble');
    if (!canvas||typeof Chart==='undefined') return;
    _charts.bubble = new Chart(canvas,{
      type:'bubble',
      data:{ datasets },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{
            display:true, position:'bottom',
            labels:{
              font:{family:"'Inter','Segoe UI',sans-serif",size:9},
              color:'#9EAAB8', boxWidth:10, boxHeight:10, padding:8,
            },
          },
          tooltip:{
            callbacks:{
              label: i=>{
                const d=i.raw;
                return [`${i.dataset.label}`, `Eficiencia: ${d.x}%`, `Sobre-riego: ${d.y}%`];
              },
            },
            backgroundColor:'rgba(22,34,48,0.90)',
            titleFont:{family:"'Inter','Segoe UI',sans-serif",size:11},
            bodyFont: {family:"'Inter','Segoe UI',sans-serif",size:11},
          },
        },
        scales:{
          x:{ title:{display:true,text:'Eficiencia de riego (%)',color:'#9EAAB8',font:{size:10}},
              min:55, max:100,
              grid:{color:'rgba(0,0,0,0.05)'},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:9},color:'#9EAAB8',
                     callback:v=>`${v}%`},
              border:{display:false} },
          y:{ title:{display:true,text:'Sobre-riego (%)',color:'#9EAAB8',font:{size:10}},
              min:0, max:55,
              grid:{color:'rgba(0,0,0,0.05)'},
              ticks:{font:{family:"'Inter','Segoe UI',sans-serif",size:9},color:'#9EAAB8',
                     callback:v=>`${v}%`},
              border:{display:false} },
        },
      },
    });
  }

  function _htmlModuleTable(rows) {
    const trs = rows.map(r=>{
      const cumplCls = r.cumpl>=75?'bi2-n--ok':r.cumpl>=60?'bi2-n--w':'bi2-n--d';
      const alerCls  = r.alertas===0?'bi2-n--ok':r.alertas<=2?'bi2-n--w':'bi2-n--d';
      const aceptCls = r.acept>=70?'bi2-n--ok':r.acept>=50?'bi2-n--w':'bi2-n--d';
      return `<tr>
        <td class="bi2-td bi2-td--bold">Módulo ${r.mod}</td>
        <td class="bi2-td bi2-td--num">${r.consumo.toLocaleString('es-MX')}</td>
        <td class="bi2-td bi2-td--num ${cumplCls}">${r.cumpl}%</td>
        <td class="bi2-td bi2-td--num ${alerCls}">${r.alertas}</td>
        <td class="bi2-td bi2-td--num ${aceptCls}">${r.acept}%</td>
        <td class="bi2-td bi2-td--num">${r.rechazo}%</td>
      </tr>`;
    }).join('');
    return `<div class="bi2-card bi2-table-card">
      <div class="bi2-card-hdr">
        <div>
          <div class="bi2-card-title">Resumen por Módulo DR-041 — PV-2026</div>
          <div class="bi2-card-sub">Comparativo de eficiencia, cumplimiento y adopción MILPÍN</div>
        </div>
      </div>
      <div class="bi2-tscroll">
        <table class="bi2-table">
          <thead><tr>
            <th>Módulo</th>
            <th class="bi2-th-num">Consumo m³/ha</th>
            <th class="bi2-th-num">Cumpl. FAO-56</th>
            <th class="bi2-th-num">Alertas</th>
            <th class="bi2-th-num">Rec. Aceptadas</th>
            <th class="bi2-th-num">Rec. Rechazadas</th>
          </tr></thead>
          <tbody>${trs}</tbody>
        </table>
      </div>
    </div>`;
  }

  // ── switchView ───────────────────────────────────────────────────────────────
  function switchView(view) {
    const op=document.getElementById('bi-view-operacion');
    const an=document.getElementById('bi-view-analisis');
    if (!op||!an) return;
    op.hidden=view!=='operacion'; an.hidden=view!=='analisis';
    document.querySelectorAll('.bi-subtab').forEach(b=>b.classList.toggle('bi-subtab--active',b.dataset.view===view));
    if (view==='operacion') { if(typeof BIOp!=='undefined') BIOp.init(); }
    else { if(!_compData) _initComp(); else _renderAnalisis(); }
  }

  // ── API pública ──────────────────────────────────────────────────────────────
  return {
    init() { switchView('operacion'); },
    switchView,
    onFilterChange() {
      const p=document.getElementById('bi-filter-parcela');
      const c=document.getElementById('bi-filter-cultivo');
      if(p) _state.selectedParcela=p.value;
      if(c) _state.selectedCultivo=c.value;
    },
    onPeriodoChange() {},
    refresh() {
      const av=document.querySelector('.bi-subtab--active')?.dataset.view||'operacion';
      if(av==='analisis'){ _compData=null; _initComp(); }
      else if(typeof BIOp!=='undefined') BIOp.refresh();
    },
  };
})();
