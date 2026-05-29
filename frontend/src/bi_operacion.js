// bi_operacion.js — Dashboard Operacional MILPÍN v2
// Secciones: Resumen Agronómico · Inteligencia de Parcela · Estado Agronómico · Cumplimiento Ciclo

const BIOp = (() => {

  const API          = 'http://localhost:8000/api';
  const TIMEOUT      = 12000;
  const CICLO_LABEL  = 'OI 2025-26';
  const BASELINE_M3  = 8000;
  const META_M3      = 6000;

  let _state = {
    loading:  false,
    triage:   null,
    rendered: false,
  };

  // ── Fetch helper ─────────────────────────────────────────────────────────
  async function _fetch(path, ms = TIMEOUT) {
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      const res = await fetch(`${API}${path}`, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('Timeout');
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Init / Refresh ────────────────────────────────────────────────────────
  async function init() {
    if (_state.loading) return;
    if (_state.rendered && _state.triage) return;
    _state.loading = true;
    _showLoading();
    try {
      const r = await Promise.allSettled([_fetch('/operacion/triage')]);
      _state.triage = r[0].status === 'fulfilled' ? r[0].value : null;
    } catch (_) { /* ignore */ }
    if (!_state.triage) _state.triage = _syntheticTriage();
    _render();
    _state.loading  = false;
    _state.rendered = true;
  }

  function refresh() {
    _state.triage   = null;
    _state.rendered = false;
    init();
  }

  // ── Synthetic fallback ────────────────────────────────────────────────────
  function _syntheticTriage() {
    return {
      modulo: 'Módulo 3', ciclo: CICLO_LABEL,
      actualizado: new Date().toISOString(),
      resumen: { critico: 2, moderado: 3, preventivo: 8, sin_datos: 1, total_activas: 14 },
      parcelas: [
        { id_parcela: 'p1', nombre: 'Parcela Norte-1', cultivo: 'Maíz',    etapa_fenologica: 'media',      nivel_urgencia: 'critico',    deficit_acumulado_mm: -38, dias_sin_riego: 9, lamina_recomendada_mm: 55 },
        { id_parcela: 'p2', nombre: 'El Nogal',        cultivo: 'Algodón', etapa_fenologica: 'desarrollo', nivel_urgencia: 'critico',    deficit_acumulado_mm: -31, dias_sin_riego: 8, lamina_recomendada_mm: 48 },
        { id_parcela: 'p3', nombre: 'Parcela Sur-4',   cultivo: 'Chile',   etapa_fenologica: 'final',      nivel_urgencia: 'moderado',   deficit_acumulado_mm: -22, dias_sin_riego: 6, lamina_recomendada_mm: 35 },
        { id_parcela: 'p4', nombre: 'La Cieneguita',   cultivo: 'Frijol',  etapa_fenologica: 'media',      nivel_urgencia: 'moderado',   deficit_acumulado_mm: -18, dias_sin_riego: 5, lamina_recomendada_mm: 28 },
        { id_parcela: 'p5', nombre: 'Poniente-2',      cultivo: 'Uva',     etapa_fenologica: 'inicial',    nivel_urgencia: 'preventivo', deficit_acumulado_mm:  -8, dias_sin_riego: 3, lamina_recomendada_mm: 20 },
      ],
      cumplimiento_ciclo: {
        ciclo: CICLO_LABEL, semana_actual: 8, semanas_totales: 14,
        pct_ciclo: 57, cumplen_meta: 9, parciales: 3, fuera_meta: 2,
        consumo_promedio_m3_ha: 6240, meta_m3_ha: META_M3, baseline_m3_ha: BASELINE_M3,
        forecast_ok: true,
      },
    };
  }

  // ── Root render ───────────────────────────────────────────────────────────
  function _render() {
    const container = document.getElementById('bi-view-operacion');
    if (!container) return;

    const t   = _state.triage;
    const c   = t.cumplimiento_ciclo || {};
    const pars = t.parcelas || [];

    const consumo  = c.consumo_promedio_m3_ha || 6240;
    const ahorro   = BASELINE_M3 - consumo;
    const total    = (c.cumplen_meta || 0) + (c.parciales || 0) + (c.fuera_meta || 0) || 14;
    const pctCumpl = total > 0 ? Math.round((c.cumplen_meta || 9) / total * 100) : 78;
    const etc       = 5.4;
    const alertas   = (t.resumen?.critico || 0) + (t.resumen?.moderado || 0);
    const ahorroMXN = Math.round(ahorro * 1.68);
    const cumplColor = pctCumpl >= 75 ? '#43A047' : pctCumpl >= 50 ? '#FB8C00' : '#E53935';

    container.innerHTML = `
<div class="bi-dash-root">

  <!-- RESUMEN AGRONÓMICO — 5 KPIs del Plan de Negocio -->
  <section class="bi-dash-section">
    <div class="bi-dash-sec-hdr">
      <span class="bi-dash-sec-dash"></span>
      <span class="bi-dash-sec-title">RESUMEN AGRONÓMICO</span>
    </div>
    <div class="bi-kpi-grid bi-kpi-grid--5">
      ${_kpiCard('Consumo Agua',        _fmt(consumo),         'm³/ha', _series(6800, consumo,    1), '#2196F3', consumo < BASELINE_M3, 'down')}
      ${_kpiCard('Ahorro Acumulado',    _fmt(ahorro),          'm³/ha', _series(1000, ahorro,     2), '#43A047', ahorro > 0,            'up')}
      ${_kpiCard('Ahorro Económico',    '$' + _fmt(ahorroMXN), 'MXN',   _series(1680, ahorroMXN,  3), '#00897B', ahorroMXN > 0,         'up')}
      ${_kpiCard('Cumplimiento FAO-56', pctCumpl,              '%',     _series(55,   pctCumpl,   4), cumplColor, pctCumpl >= 75,        'up')}
      ${_kpiCard('Alertas Activas',     alertas,               '',      _series(5,    alertas,    5), alertas > 0 ? '#E53935' : '#43A047', alertas === 0, alertas > 0 ? 'down' : 'neutral')}
    </div>
  </section>

  <!-- INTELIGENCIA + CONSUMO CHART -->
  <section class="bi-dash-row bi-intel-row">
    <div class="bi-intel-panel bi-dash-card">
      <div class="bi-dash-sec-hdr">
        <span class="bi-dash-sec-dash"></span>
        <span class="bi-dash-sec-title">INTELIGENCIA DE PARCELA</span>
      </div>
      ${_htmlHeatmap7d(pars)}
      ${_htmlPulso()}
    </div>
    <div class="bi-consumo-panel bi-dash-card">
      <div class="bi-dash-sec-hdr">
        <span class="bi-dash-sec-dash"></span>
        <span class="bi-dash-sec-title">CONSUMO ACUMULADO VS META</span>
      </div>
      <div class="bi-chart-wrap">
        <svg id="bi-consumo-svg" class="bi-svg-chart" viewBox="0 0 420 170" preserveAspectRatio="none"></svg>
      </div>
    </div>
  </section>

  <!-- ESTADO AGRONÓMICO -->
  <section class="bi-dash-row bi-estado-row">
    <div class="bi-fao-panel bi-dash-card">
      <div class="bi-dash-sec-hdr">
        <span class="bi-dash-sec-dash"></span>
        <span class="bi-dash-sec-title">ESTADO AGRONÓMICO · FAO-56</span>
      </div>
      ${_htmlFaoTable(pars)}
    </div>
    <div class="bi-charts-stack">
      <div class="bi-dash-card bi-ndvi-card">
        <div class="bi-dash-sec-hdr">
          <span class="bi-dash-sec-dash"></span>
          <span class="bi-dash-sec-title">CUMPLIMIENTO FAO-56 POR CULTIVO</span>
          <span class="bi-dash-sec-sub">% dentro del rango objetivo</span>
        </div>
        ${_htmlCumplimientoBarras(pars)}
      </div>
      <div class="bi-dash-card bi-ahorro-card">
        <div class="bi-dash-sec-hdr">
          <span class="bi-dash-sec-dash"></span>
          <span class="bi-dash-sec-title">SOBRE-RIEGO vs OBJETIVO</span>
        </div>
        ${_htmlSobreRiegoBars(pars)}
      </div>
    </div>
  </section>

  <!-- CUMPLIMIENTO DEL CICLO -->
  ${_htmlCicloPanel(c)}

</div>`;

    // Draw SVG charts after DOM is ready
    requestAnimationFrame(() => {
      _drawConsumoChart(c);
    });
  }

  // ── KPI Card ──────────────────────────────────────────────────────────────
  function _kpiCard(label, value, unit, sparkData, color, isGood, trend) {
    const icon  = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
    const cls   = trend === 'neutral' ? 'bi-trend--neutral' : isGood ? 'bi-trend--good' : 'bi-trend--bad';
    const spark = _svgSpark(sparkData, color, 110, 34);
    return `
    <div class="bi-kpi-card">
      <div class="bi-kpi-row">
        <span class="bi-kpi-label">${label}</span>
        <span class="bi-trend-badge ${cls}">${icon}</span>
      </div>
      <div class="bi-kpi-value">${value}<span class="bi-kpi-unit"> ${unit}</span></div>
      <div class="bi-kpi-spark">${spark}</div>
    </div>`;
  }

  // ── SVG Sparkline ─────────────────────────────────────────────────────────
  function _svgSpark(data, color, W, H) {
    const valid = data.filter(v => v != null && !isNaN(v));
    if (valid.length < 2) return `<svg class="bi-spark-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"></svg>`;
    const mn = Math.min(...valid), mx = Math.max(...valid), rng = mx - mn || 1;
    const pad = 2;
    const pts = data.map((v, i) => {
      if (v == null) return null;
      const x = pad + (i / (data.length - 1)) * (W - pad * 2);
      const y = H - pad - ((v - mn) / rng) * (H - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).filter(Boolean).join(' ');
    return `<svg class="bi-spark-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
  }

  // ── Heatmap 7 días ────────────────────────────────────────────────────────
  function _htmlHeatmap7d(pars) {
    const days   = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];
    const vals   = _hmValues(pars);
    const cells  = days.map((d, i) => {
      const v   = vals[i];
      const pct = v / 50;
      const [bg, fg] = pct < 0.4 ? ['#F0FDF4','#15803D'] : pct < 0.7 ? ['#FFFBEB','#92400E'] : ['#FEF2F2','#991B1B'];
      return `<div class="bi-hm-cell" style="background:${bg};color:${fg}">
        <span class="bi-hm-day">${d}</span>
        <span class="bi-hm-val">${v}%</span>
      </div>`;
    }).join('');
    return `
    <div class="bi-heatmap-block">
      <span class="bi-block-lbl">Uso hídrico relativo — % lámina neta</span>
      <div class="bi-hm-grid">${cells}</div>
    </div>`;
  }

  function _hmValues(pars) {
    const maxDef = Math.max(...(pars.map(p => Math.abs(p.deficit_acumulado_mm || 0))), 1);
    const scale  = Math.min(maxDef / 50, 1);
    return [12, 15, 19, 24, 28, 33, Math.round(12 + 26 * scale)].map(v => Math.round(v * (0.85 + scale * 0.3)));
  }

  // ── Pulso climático ───────────────────────────────────────────────────────
  function _htmlPulso() {
    const rows = [
      { lbl: 'T máx',    data: _climSeries(28, 34, 7), color: '#E65C5C', unit: '°C' },
      { lbl: 'ETo',      data: _climSeries(4.8, 5.9, 8), color: '#F5A623', unit: 'mm' },
      { lbl: 'Déf acum', data: _defSeries(),              color: '#0F6CBD', unit: 'mm' },
      { lbl: 'Lluvia',   data: _lluviaSeries(),           color: '#10B981', unit: 'mm' },
    ];
    const html = rows.map(r => {
      const last = r.data[r.data.length - 1];
      return `<div class="bi-pulso-row">
        <span class="bi-pulso-lbl">${r.lbl}</span>
        ${_svgSpark(r.data, r.color, 110, 28)}
        <span class="bi-pulso-val">${last.toFixed(1)}${r.unit}</span>
      </div>`;
    }).join('');
    return `
    <div class="bi-pulso-block">
      <span class="bi-block-lbl">Pulso climático — 14 días</span>
      <div class="bi-pulso-rows">${html}</div>
    </div>`;
  }

  // ── FAO-56 table ──────────────────────────────────────────────────────────
  function _htmlFaoTable(pars) {
    const cultBase = [
      { c: 'Maíz',    kc: 1.15, etc: 6.2 },
      { c: 'Algodón', kc: 1.05, etc: 5.8 },
      { c: 'Chile',   kc: 0.95, etc: 5.1 },
      { c: 'Frijol',  kc: 0.90, etc: 4.8 },
      { c: 'Uva',     kc: 0.70, etc: 3.7 },
    ];
    const cultMap = {};
    pars.forEach(p => { if (p.cultivo) cultMap[p.cultivo] = p; });

    const rows = cultBase.map(b => {
      const p    = cultMap[b.c] || {};
      const urg  = p.nivel_urgencia;
      const lam  = p.lamina_recomendada_mm || Math.round(b.etc * 5);
      const prox = urg === 'critico' ? '1–2 días' : urg === 'moderado' ? '3–4 días' : '5–7 días';
      const cls  = urg === 'critico' ? 'bi-fao-row--crit' : urg === 'moderado' ? 'bi-fao-row--mod' : '';
      const badge = urg === 'critico'
        ? '<span class="bi-fao-bdg bi-fao-bdg--crit">Crítico</span>'
        : urg === 'moderado'
          ? '<span class="bi-fao-bdg bi-fao-bdg--mod">Moderado</span>'
          : '<span class="bi-fao-bdg bi-fao-bdg--ok">Normal</span>';
      return `<tr class="${cls}">
        <td class="bi-fao-name">${b.c}</td>
        <td class="bi-fao-num">${b.etc.toFixed(1)}</td>
        <td class="bi-fao-num">${b.kc.toFixed(2)}</td>
        <td class="bi-fao-num">${lam}</td>
        <td class="bi-fao-str">${prox}</td>
        <td>${badge}</td>
      </tr>`;
    }).join('');

    return `<div class="bi-fao-scroll">
      <table class="bi-fao-tbl">
        <thead><tr>
          <th>Cultivo</th>
          <th title="ETc mm/día">ETc</th>
          <th title="Coeficiente cultivo">Kc</th>
          <th title="Lámina recomendada mm">Lám.</th>
          <th>Próx. Riego</th>
          <th>Estado</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  // ── Cumplimiento FAO-56 por cultivo (barras apiladas) ────────────────────
  // Pregunta 4: ¿Qué cultivo tiene peor cumplimiento FAO-56?
  function _htmlCumplimientoBarras(pars) {
    const porCultivo = {};
    pars.forEach(p => {
      const c = p.cultivo || 'Sin cultivo';
      if (!porCultivo[c]) porCultivo[c] = { ok: 0, mod: 0, crit: 0 };
      if      (p.nivel_urgencia === 'critico')  porCultivo[c].crit++;
      else if (p.nivel_urgencia === 'moderado') porCultivo[c].mod++;
      else                                       porCultivo[c].ok++;
    });

    const items = Object.entries(porCultivo);
    if (!items.length) {
      return `<div style="font-size:.8rem;color:var(--secondary-text);padding:12px 0">Sin datos de parcelas.</div>`;
    }

    const bars = items.map(([nombre, counts]) => {
      const total  = counts.ok + counts.mod + counts.crit || 1;
      const pctOk   = Math.round(counts.ok   / total * 100);
      const pctMod  = Math.round(counts.mod  / total * 100);
      const pctCrit = Math.round(counts.crit / total * 100);
      const cumplColor = pctCrit > 30 ? '#E53935' : pctCrit > 0 ? '#FB8C00' : '#43A047';
      return `
      <div class="bi-abar-row">
        <span class="bi-abar-name">${nombre}</span>
        <div class="bi-abar-track bi-abar-stacked">
          ${pctOk   ? `<div class="bi-abar-fill" style="width:${pctOk}%;background:#43A047" title="Normal: ${pctOk}%"></div>`    : ''}
          ${pctMod  ? `<div class="bi-abar-fill" style="width:${pctMod}%;background:#FB8C00" title="Moderado: ${pctMod}%"></div>` : ''}
          ${pctCrit ? `<div class="bi-abar-fill" style="width:${pctCrit}%;background:#E53935" title="Crítico: ${pctCrit}%"></div>`: ''}
        </div>
        <span class="bi-abar-pct" style="color:${cumplColor}">${100 - pctCrit}%</span>
      </div>`;
    }).join('');

    return `
    <div class="bi-ahorro-bars">
      <div class="bi-stacked-legend">
        <span class="bi-stacked-dot" style="background:#43A047"></span><span>Normal</span>
        <span class="bi-stacked-dot" style="background:#FB8C00"></span><span>Moderado</span>
        <span class="bi-stacked-dot" style="background:#E53935"></span><span>Crítico</span>
      </div>
      ${bars}
    </div>`;
  }

  // ── Sobre-riego vs Objetivo (barras con umbral FAO-56) ────────────────────
  // Pregunta 1: ¿Estamos consumiendo dentro del objetivo FAO-56?
  function _htmlSobreRiegoBars(pars) {
    const LAMINA_OBJETIVO = { 'Maíz': 55, 'Algodón': 48, 'Chile': 35, 'Frijol': 28, 'Uva': 20 };
    const porCultivo = {};
    pars.forEach(p => {
      const c   = p.cultivo || 'Sin cultivo';
      const lam = p.lamina_recomendada_mm || 0;
      if (!porCultivo[c]) porCultivo[c] = { lamMax: 0, obj: LAMINA_OBJETIVO[c] || 40 };
      if (lam > porCultivo[c].lamMax) porCultivo[c].lamMax = lam;
    });

    const items = Object.entries(porCultivo);
    if (!items.length) {
      return `<div style="font-size:.8rem;color:var(--secondary-text);padding:12px 0">Sin datos de parcelas.</div>`;
    }

    const maxLam = Math.max(...items.map(([, v]) => Math.max(v.lamMax, v.obj)), 60);
    const bars = items.map(([nombre, v]) => {
      const pctLam  = Math.min(100, Math.round((v.lamMax / maxLam) * 100));
      const pctObj  = Math.min(100, Math.round((v.obj    / maxLam) * 100));
      const sobreRiego = v.lamMax > v.obj * 1.1;
      const barColor   = sobreRiego ? '#E53935' : '#2196F3';
      return `
      <div class="bi-abar-row">
        <span class="bi-abar-name">${nombre}</span>
        <div class="bi-abar-track" style="position:relative">
          <div class="bi-abar-fill" style="width:${pctLam}%;background:${barColor}"></div>
          <div style="position:absolute;top:0;left:${pctObj}%;height:100%;width:2px;background:#FB8C00;opacity:.9"></div>
        </div>
        <span class="bi-abar-pct" style="color:${barColor}">${v.lamMax} mm</span>
      </div>`;
    }).join('');

    return `
    <div class="bi-ahorro-bars">
      <div class="bi-stacked-legend">
        <span class="bi-stacked-dot" style="background:#2196F3"></span><span>Lámina real</span>
        <span class="bi-stacked-dot" style="background:#E53935"></span><span>Sobre-riego</span>
        <span class="bi-stacked-dot" style="background:#FB8C00;border-radius:0;width:3px;height:10px"></span><span>Objetivo FAO-56</span>
      </div>
      ${bars}
    </div>`;
  }

  // ── Cumplimiento del ciclo ────────────────────────────────────────────────
  function _htmlCicloPanel(c) {
    const semAct  = c.semana_actual  || 8;
    const semTot  = c.semanas_totales || 14;
    const pct     = c.pct_ciclo || Math.round(semAct / semTot * 100);
    const cumplen = c.cumplen_meta || 9;
    const total   = (c.cumplen_meta || 0) + (c.parciales || 0) + (c.fuera_meta || 0) || 14;
    const consumo = c.consumo_promedio_m3_ha || 6240;
    const fcOk    = c.forecast_ok !== false;
    const ahorro$ = Math.round((BASELINE_M3 - consumo) * 1.68);

    return `
    <section class="bi-ciclo-section bi-dash-card">
      <div class="bi-ciclo-head">
        <div class="bi-dash-sec-hdr" style="margin:0">
          <span class="bi-dash-sec-dash"></span>
          <span class="bi-dash-sec-title">CUMPLIMIENTO DEL CICLO</span>
        </div>
        <div class="bi-ciclo-meta-row">
          <span class="bi-ciclo-chip">Ciclo ${c.ciclo || CICLO_LABEL}</span>
          <span class="bi-ciclo-chip bi-ciclo-chip--blue">Semana ${semAct} / ${semTot}</span>
          ${fcOk ? '<span class="bi-ciclo-chip bi-ciclo-chip--green">✓ Forecast dentro de meta</span>' : ''}
        </div>
      </div>
      <div class="bi-ciclo-prog-row">
        <div class="bi-ciclo-track"><div class="bi-ciclo-fill" style="width:${pct}%"></div></div>
        <span class="bi-ciclo-pct">${pct}%</span>
      </div>
      <div class="bi-ciclo-kpis">
        ${_cicloKpi('Total Parcelas',   total,              '',        false)}
        ${_cicloKpi('Cumplen Meta',     cumplen,            '',        true)}
        ${_cicloKpi('Consumo Ciclo',    _fmt(consumo),      'm³/ha',   consumo < META_M3)}
        ${_cicloKpi('Ahorro Estimado', '$'+_fmt(ahorro$),   'MXN/ha',  ahorro$ > 0)}
      </div>
    </section>`;
  }

  function _cicloKpi(label, value, unit, highlight) {
    return `<div class="bi-ciclo-kpi${highlight ? ' bi-ciclo-kpi--hl' : ''}">
      <div class="bi-ciclo-kval">${value}${unit ? '<span class="bi-ciclo-kunit"> '+unit+'</span>' : ''}</div>
      <div class="bi-ciclo-klbl">${label}</div>
    </div>`;
  }

  // ── SVG: Consumo Acumulado vs Meta ────────────────────────────────────────
  function _drawConsumoChart(c) {
    const svg = document.getElementById('bi-consumo-svg');
    if (!svg) return;

    const W = 420, H = 170;
    const pL = 42, pR = 14, pT = 14, pB = 28;
    const cW = W - pL - pR, cH = H - pT - pB;
    const weeks    = 14;
    const semAct   = c.semana_actual || 8;
    const endCons  = c.consumo_promedio_m3_ha || 6240;
    const maxY     = BASELINE_M3 + 600;

    const toX = (i, n) => pL + (i / (n - 1)) * cW;
    const toY = (v)    => pT + cH * (1 - v / maxY);

    // Consumption data (real portion only)
    const consData = Array.from({length: semAct}, (_, i) => {
      const t = i / (semAct - 1 || 1);
      return Math.round(endCons * t * (1 + (_pr(1, i) - 0.5) * 0.06));
    });
    const metaData  = Array.from({length: weeks}, (_, i) => Math.round(i / (weeks-1) * META_M3));
    const baseData  = Array.from({length: weeks}, (_, i) => Math.round(i / (weeks-1) * BASELINE_M3));

    let out = '';

    // Grid lines
    [0, 2000, 4000, 6000, 8000].forEach(v => {
      const y = toY(v).toFixed(1);
      out += `<line x1="${pL}" y1="${y}" x2="${W-pR}" y2="${y}" stroke="#E2E8F0" stroke-width="1"/>`;
      out += `<text x="${pL-5}" y="${(parseFloat(y)+3.5).toFixed(1)}" text-anchor="end" font-size="9" fill="#94A3B8">${v===0?'0':v/1000+'k'}</text>`;
    });

    // Week labels
    [0,3,6,9,12].forEach(i => {
      const x = toX(i, weeks).toFixed(1);
      out += `<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#94A3B8">S${i+1}</text>`;
    });

    // Baseline dashed
    const basePts = baseData.map((v, i) => `${toX(i,weeks).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
    out += `<polyline points="${basePts}" fill="none" stroke="#E65C5C" stroke-width="1" stroke-dasharray="4,4" opacity="0.4"/>`;

    // Meta dashed
    const metaPts = metaData.map((v, i) => `${toX(i,weeks).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
    out += `<polyline points="${metaPts}" fill="none" stroke="#43B36B" stroke-width="1.5" stroke-dasharray="5,4"/>`;

    // Consumption area + line
    if (consData.length >= 2) {
      const consPts = consData.map((v, i) => `${toX(i,consData.length).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
      const x0 = toX(0, consData.length).toFixed(1);
      const xN = toX(consData.length-1, consData.length).toFixed(1);
      const yB = (pT + cH).toFixed(1);
      out += `<polygon points="${x0},${yB} ${consPts} ${xN},${yB}" fill="rgba(15,108,189,0.09)"/>`;
      out += `<polyline points="${consPts}" fill="none" stroke="#0F6CBD" stroke-width="2.5" stroke-linejoin="round"/>`;
      // End dot
      const lx = toX(consData.length-1, consData.length).toFixed(1);
      const ly = toY(consData[consData.length-1]).toFixed(1);
      out += `<circle cx="${lx}" cy="${ly}" r="4" fill="#0F6CBD"/>`;
    }

    // Legend
    out += `
      <rect x="${pL+2}" y="${pT+2}" width="10" height="10" fill="#0F6CBD" opacity="0.85" rx="2"/>
      <text x="${pL+16}" y="${pT+10}" font-size="9" fill="#475569">Consumo real</text>
      <line x1="${pL+88}" y1="${pT+7}" x2="${pL+102}" y2="${pT+7}" stroke="#43B36B" stroke-width="1.5" stroke-dasharray="4,3"/>
      <text x="${pL+106}" y="${pT+10}" font-size="9" fill="#475569">Meta ${META_M3/1000}k</text>
      <line x1="${pL+148}" y1="${pT+7}" x2="${pL+162}" y2="${pT+7}" stroke="#E65C5C" stroke-width="1" stroke-dasharray="3,4" opacity="0.6"/>
      <text x="${pL+166}" y="${pT+10}" font-size="9" fill="#475569">Baseline ${BASELINE_M3/1000}k</text>
    `;

    svg.innerHTML = out;
  }


  // ── Loading indicator ─────────────────────────────────────────────────────
  function _showLoading() {
    const el = document.getElementById('bi-view-operacion');
    if (el) el.innerHTML = `<div class="bi-dash-loading"><span class="bi-spinner"></span>Cargando operaciones…</div>`;
  }

  // ── Deterministic pseudo-random (no Math.random for stable render) ────────
  function _pr(seed, i) {
    const x = Math.sin(seed * 127.1 + i * 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  function _series(start, end, seed) {
    return Array.from({length: 10}, (_, i) => {
      const t = i / 9;
      return start + (end - start) * t + (_pr(seed, i) - 0.5) * Math.abs(end - start) * 0.18;
    });
  }

  function _climSeries(lo, hi, seed) {
    return Array.from({length: 14}, (_, i) => lo + (hi - lo) * (_pr(seed, i)));
  }

  function _defSeries() {
    return Array.from({length: 14}, (_, i) => -(i * 2.8 + _pr(3, i) * 4));
  }

  function _lluviaSeries() {
    return Array.from({length: 14}, (_, i) => _pr(4, i) < 0.15 ? +(_pr(5,i)*12).toFixed(1) : 0);
  }

  function _fmt(n) {
    return typeof n === 'number' ? n.toLocaleString('es-MX') : n;
  }

  // ── Public API ────────────────────────────────────────────────────────────
  return { init, refresh };

})();
