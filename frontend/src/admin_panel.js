// admin_panel.js — Panel de administración MILPÍN
// Visible solo para usuarios con rol="admin".
// Consume: GET /api/parcelas (sin filtro → todas), GET /api/usuarios

const ADMIN = (() => {
  const API = 'http://localhost:8000/api';

  // ── Estado ──────────────────────────────────────────────────────────────────
  let _parcelas  = [];
  let _usuarios  = [];
  let _loading   = false;
  let _filterUsr = 'todos';
  let _filterSis = 'todos';
  let _sortCol   = 'nombre_parcela';
  let _sortDir   = 'asc';

  // ── Fetch helpers ────────────────────────────────────────────────────────────
  async function _get(path) {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) throw new Error(`HTTP ${res.status} en ${path}`);
    return res.json();
  }

  // ── Mapa id_usuario → nombre ─────────────────────────────────────────────
  function _mapaUsuarios() {
    const m = {};
    _usuarios.forEach(u => { m[u.id_usuario] = u; });
    return m;
  }

  // ── KPIs del panel ───────────────────────────────────────────────────────────
  function _calcKpis() {
    const totalHa = _parcelas.reduce((s, p) => s + (p.area_ha || 0), 0);
    const totalMods = new Set(_usuarios.map(u => u.modulo_dr041).filter(Boolean)).size;
    return {
      parcelas:  _parcelas.length,
      usuarios:  _usuarios.filter(u => u.activo).length,
      hectareas: totalHa.toFixed(1),
      modulos:   totalMods,
    };
  }

  // ── Filtrado + ordenamiento ───────────────────────────────────────────────
  function _filteredParcelas() {
    let list = [..._parcelas];

    if (_filterUsr !== 'todos') {
      list = list.filter(p => p.id_usuario === _filterUsr);
    }
    if (_filterSis !== 'todos') {
      list = list.filter(p => (p.sistema_riego || '').toLowerCase() === _filterSis);
    }

    list.sort((a, b) => {
      let va = a[_sortCol] ?? '';
      let vb = b[_sortCol] ?? '';
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      if (va < vb) return _sortDir === 'asc' ? -1 : 1;
      if (va > vb) return _sortDir === 'asc' ? 1 : -1;
      return 0;
    });

    return list;
  }

  // ── Render KPI cards ─────────────────────────────────────────────────────
  function _renderKpis(kpis) {
    const el = document.getElementById('admin-kpis');
    if (!el) return;
    el.innerHTML = `
      <div class="admin-kpi-card">
        <div class="admin-kpi-value">${kpis.parcelas}</div>
        <div class="admin-kpi-label">Parcelas activas</div>
      </div>
      <div class="admin-kpi-card">
        <div class="admin-kpi-value">${kpis.usuarios}</div>
        <div class="admin-kpi-label">Usuarios activos</div>
      </div>
      <div class="admin-kpi-card">
        <div class="admin-kpi-value">${kpis.hectareas}</div>
        <div class="admin-kpi-label">Hectáreas totales</div>
      </div>
      <div class="admin-kpi-card">
        <div class="admin-kpi-value">${kpis.modulos}</div>
        <div class="admin-kpi-label">Módulos DR-041</div>
      </div>
    `;
  }

  // ── Render filtros ───────────────────────────────────────────────────────
  function _renderFiltros() {
    const selUsr = document.getElementById('admin-filter-usuario');
    const selSis = document.getElementById('admin-filter-sistema');
    if (!selUsr || !selSis) return;

    // Usuarios
    const usrActual = selUsr.value;
    selUsr.innerHTML = '<option value="todos">Todos los usuarios</option>';
    _usuarios.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.id_usuario;
      opt.textContent = `${u.nombre_completo} · ${u.modulo_dr041 || 'DR-041'}`;
      selUsr.appendChild(opt);
    });
    if (usrActual) selUsr.value = usrActual;

    // Sistemas de riego únicos
    const sistemas = [...new Set(
      _parcelas.map(p => (p.sistema_riego || '').toLowerCase()).filter(Boolean)
    )].sort();
    const sisActual = selSis.value;
    selSis.innerHTML = '<option value="todos">Todos los sistemas</option>';
    sistemas.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s.charAt(0).toUpperCase() + s.slice(1);
      selSis.appendChild(opt);
    });
    if (sisActual) selSis.value = sisActual;
  }

  // ── Render tabla ─────────────────────────────────────────────────────────
  function _renderTabla() {
    const container = document.getElementById('admin-tabla-container');
    if (!container) return;

    const list   = _filteredParcelas();
    const usrMap = _mapaUsuarios();

    if (list.length === 0) {
      container.innerHTML = `
        <div class="admin-empty">
          <svg viewBox="0 0 24 24" width="36" height="36" fill="var(--secondary-text)">
            <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-7 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm0 10c-2.67 0-8 1.34-8 4v1h16v-1c0-2.66-5.33-4-8-4z"/>
          </svg>
          <p>No hay parcelas con los filtros actuales.</p>
        </div>`;
      return;
    }

    // Indicador de columna ordenada
    const arrow = (col) => {
      if (_sortCol !== col) return '<span class="admin-sort-arrow admin-sort-arrow--inactive">↕</span>';
      return `<span class="admin-sort-arrow">${_sortDir === 'asc' ? '↑' : '↓'}</span>`;
    };

    const sortable = (col, label) =>
      `<span class="admin-th-sort" data-col="${col}">${label}${arrow(col)}</span>`;

    const rows = list.map(p => {
      const usr = usrMap[p.id_usuario];
      const nombre = p.nombre_parcela || '—';
      const usrNombre = usr ? usr.nombre_completo : p.id_usuario?.slice(0, 8) + '…';
      const modulo = usr?.modulo_dr041 || '—';
      const area = p.area_ha != null ? `${p.area_ha.toFixed(1)} ha` : '—';
      const suelo = p.tipo_suelo || '—';
      const sistema = p.sistema_riego
        ? `<span class="bi-crop-tag">${p.sistema_riego}</span>`
        : '<span style="color:var(--secondary-text)">—</span>';
      const aguaDisp = p.agua_disponible_mm != null
        ? `${p.agua_disponible_mm.toFixed(0)} mm`
        : '—';
      const ce = p.conductividad_electrica != null
        ? `${p.conductividad_electrica.toFixed(1)} dS/m`
        : '—';

      return `
        <tr class="bi-tr">
          <td class="bi-td bi-td--bold">${nombre}</td>
          <td class="bi-td">${usrNombre}</td>
          <td class="bi-td admin-td--mod">${modulo}</td>
          <td class="bi-td bi-td--mono">${area}</td>
          <td class="bi-td">${suelo}</td>
          <td class="bi-td">${sistema}</td>
          <td class="bi-td bi-td--mono">${aguaDisp}</td>
          <td class="bi-td bi-td--mono">${ce}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="bi-table-scroll">
        <table class="bi-table">
          <thead>
            <tr>
              <th class="bi-th">${sortable('nombre_parcela', 'Parcela')}</th>
              <th class="bi-th">${sortable('id_usuario', 'Usuario')}</th>
              <th class="bi-th">Módulo</th>
              <th class="bi-th">${sortable('area_ha', 'Área')}</th>
              <th class="bi-th">Suelo</th>
              <th class="bi-th">Sistema riego</th>
              <th class="bi-th">${sortable('agua_disponible_mm', 'Agua disp.')}</th>
              <th class="bi-th">CE (dS/m)</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="admin-tabla-footer">
        Mostrando <b>${list.length}</b> de <b>${_parcelas.length}</b> parcelas
      </div>`;

    // Vincular sort clicks
    container.querySelectorAll('.admin-th-sort').forEach(el => {
      el.style.cursor = 'pointer';
      el.addEventListener('click', () => {
        const col = el.dataset.col;
        if (_sortCol === col) {
          _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          _sortCol = col;
          _sortDir = 'asc';
        }
        _renderTabla();
      });
    });
  }

  // ── Estado de carga / error ───────────────────────────────────────────────
  function _setStatus(msg, isError = false) {
    const el = document.getElementById('admin-load-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = isError ? 'var(--red-listening)' : 'var(--secondary-text)';
    el.style.display = msg ? 'block' : 'none';
  }

  // ── Carga de datos ───────────────────────────────────────────────────────
  async function _loadData(forceReload = false) {
    if (_loading) return;
    if (!forceReload && _parcelas.length > 0) {
      _renderFiltros();
      _renderKpis(_calcKpis());
      _renderTabla();
      return;
    }

    _loading = true;
    _setStatus('Cargando datos del sistema…');

    const container = document.getElementById('admin-tabla-container');
    if (container) container.innerHTML = '<div class="admin-loading-spinner"></div>';

    try {
      [_parcelas, _usuarios] = await Promise.all([
        _get('/parcelas'),
        _get('/usuarios'),
      ]);

      _setStatus('');
      _renderKpis(_calcKpis());
      _renderFiltros();
      _renderTabla();
    } catch (err) {
      _setStatus(`Error al cargar datos: ${err.message}`, true);
      if (container) container.innerHTML = '';
    } finally {
      _loading = false;
    }
  }

  // ── Inicialización ───────────────────────────────────────────────────────
  function init() {
    // Sólo montar si el usuario es admin
    if (!window.MILPIN_AUTH?.isAdmin?.()) return;

    // Mostrar nav item admin
    const navAdmin = document.getElementById('nav-item-admin');
    if (navAdmin) navAdmin.style.display = 'flex';

    // Filtro usuario
    const selUsr = document.getElementById('admin-filter-usuario');
    if (selUsr) {
      selUsr.addEventListener('change', () => {
        _filterUsr = selUsr.value;
        _renderTabla();
      });
    }

    // Filtro sistema
    const selSis = document.getElementById('admin-filter-sistema');
    if (selSis) {
      selSis.addEventListener('change', () => {
        _filterSis = selSis.value;
        _renderTabla();
      });
    }

    // Botón recargar
    const btnReload = document.getElementById('admin-btn-reload');
    if (btnReload) {
      btnReload.addEventListener('click', () => _loadData(true));
    }
  }

  // ── API pública ──────────────────────────────────────────────────────────
  return {
    init,
    cargar: () => _loadData(false),
    recargar: () => _loadData(true),
  };
})();

window.ADMIN = ADMIN;
