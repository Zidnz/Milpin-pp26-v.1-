// ==========================================
// map_engine.js: Motor Geoespacial Leaflet
// MILPÍN AgTech v2.1
//
// Arquitectura data-driven: todas las geometrías
// se cargan desde archivos GeoJSON en /data/.
// Cero coordenadas hardcodeadas.
// ==========================================

let map;
let mapaIniciado = false;

// ── Layer Groups ──────────────────────────────────────────────────────
let capaLotes    = null;   // Parcelas agrícolas (NDVI / rendimiento)
let capaRios     = null;   // Red hidrográfica
let capaCanales  = null;   // Canales DR-041
let capaPozos    = null;   // Pozos de extracción
let capaAnalisis = null;   // Resultados dinámicos (clustering, etc.)

// ── Centro por defecto (Cajeme, Valle del Yaqui) ─────────────────────
const DEFAULT_CENTER = [27.3670, -109.9310];
const DEFAULT_ZOOM   = 11;

// ── Paleta NDVI — valores normalizados 0.0 a 1.0 ─────────────────────
// Colores intencionalmente saturados para máximo contraste visual.
function obtenerColorNDVI(ndvi) {
    if (ndvi >= 0.80) return '#00a600';   // Excelente — verde intenso
    if (ndvi >= 0.60) return '#4cbb17';   // Saludable — verde
    if (ndvi >= 0.40) return '#d4c000';   // Moderado  — amarillo
    if (ndvi >= 0.25) return '#e07000';   // Alerta    — naranja
    return '#cc1800';                     // Crítico   — rojo
}

// Normalizar cualquier fuente de datos a NDVI 0–1
function getNDVI(p) {
    if (p.ndvi !== undefined && p.ndvi !== null) return parseFloat(p.ndvi);
    if (p.rendimiento !== undefined)              return p.rendimiento / 100;
    return 0.5;
}

// Clasificación textual del NDVI
function clasificarNDVI(ndvi) {
    if (ndvi >= 0.80) return { emoji: '🟢', texto: 'Excelente', clase: 'ndvi-excelente' };
    if (ndvi >= 0.60) return { emoji: '🟢', texto: 'Saludable', clase: 'ndvi-saludable' };
    if (ndvi >= 0.40) return { emoji: '🟡', texto: 'Moderado',  clase: 'ndvi-moderado'  };
    if (ndvi >= 0.25) return { emoji: '🟠', texto: 'Alerta',    clase: 'ndvi-alerta'    };
    return                     { emoji: '🔴', texto: 'Crítico',   clase: 'ndvi-critico'   };
}

// ── Estilos por tipo de capa ──────────────────────────────────────────
const ESTILOS = {
    limites: {
        color: '#00d4ff',
        fillColor: '#00d4ff',
        fillOpacity: 0.04,
        weight: 2.5,
        dashArray: '10, 6'
    },
    rio: {
        color: '#2980B9',
        weight: 5,
        opacity: 0.85,
        lineJoin: 'round'
    },
    arroyo: {
        color: '#5DADE2',
        weight: 2,
        opacity: 0.65,
        dashArray: '6, 4'
    },
    canal: {
        color: '#00E5FF',
        weight: 3,
        opacity: 0.8
    },
    pozo_activo: {
        radius: 6,
        fillColor: '#27AE60',
        color: '#1E8449',
        weight: 1.5,
        fillOpacity: 0.9
    },
    pozo_bajo: {
        radius: 6,
        fillColor: '#E67E22',
        color: '#D35400',
        weight: 1.5,
        fillOpacity: 0.9
    }
};

// ── HTML del popup enriquecido ────────────────────────────────────────
function crearHTMLPopup(p, esDesdeAPI) {
    const ndvi      = getNDVI(p);
    const ndviPct   = Math.round(ndvi * 100);
    const color     = obtenerColorNDVI(ndvi);
    const clasif    = clasificarNDVI(ndvi);
    const esCritico = ndvi < 0.25;
    const colorDias = (p.dias_sin_riego && p.dias_sin_riego > 14) ? '#cc1800' : '#555';

    // Barra NDVI visual
    const barraHTML = `
        <div style="margin:10px 0 12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <span style="font-size:0.72em;color:#777;font-weight:600;letter-spacing:.3px;">NDVI</span>
                <span style="font-weight:800;color:${color};font-size:1em;">${ndviPct}%&nbsp;${clasif.emoji}&nbsp;${clasif.texto}</span>
            </div>
            <div style="height:10px;background:#e8e8e8;border-radius:5px;overflow:hidden;">
                <div style="width:${ndviPct}%;height:100%;background:linear-gradient(90deg,${esCritico ? '#ff4500' : color},${color});border-radius:5px;transition:width .4s;"></div>
            </div>
            ${esCritico ? '<div style="font-size:0.7em;color:#cc1800;margin-top:4px;font-weight:600;">⚠ Zona en estrés hídrico severo</div>' : ''}
        </div>`;

    // Tabla de propiedades agronómicas
    const filas = [
        ['Cultivo',    p.cultivo        || '—'],
        ['Superficie', p.area_ha        ? p.area_ha + ' ha'  : '—'],
        ['Módulo',     p.modulo         || (p.id_parcela ? 'DR-041' : '—')],
        ['Suelo',      p.tipo_suelo     || '—'],
        ['Riego',      p.sistema_riego  || '—'],
        ['Sin riego',  p.dias_sin_riego != null ? `<span style="color:${colorDias};font-weight:700;">${p.dias_sin_riego} días</span>` : '—'],
        ['Déficit',    p.deficit_hidrico != null ? p.deficit_hidrico + ' mm' : '—'],
        ['Consumo',    p.consumo_ciclo_m3ha ? (p.consumo_ciclo_m3ha.toLocaleString('es-MX') + ' m³/ha') : '—'],
    ].map(([k, v]) => `
        <tr>
            <td style="color:#888;padding:3px 0;font-size:0.76em;">${k}</td>
            <td style="font-weight:600;text-align:right;font-size:0.76em;padding:3px 0 3px 12px;">${v}</td>
        </tr>`).join('');

    return `
    <div style="min-width:240px;max-width:280px;font-family:'Segoe UI',sans-serif;line-height:1.4;">
        <div style="font-weight:800;font-size:1em;color:#1a2e1f;padding-bottom:6px;border-bottom:2px solid ${color};margin-bottom:4px;">
            ${p.nombre || (p.id_parcela ? 'Parcela ' + p.id_parcela : 'Parcela')}
        </div>
        <div style="font-size:0.72em;color:#888;margin-bottom:2px;">${
            p.estado ||
            (p.nivel_urgencia ? ({ critico:'⚠ Urgencia Crítica', moderado:'Urgencia Moderada', preventivo:'Preventivo' }[p.nivel_urgencia] || p.nivel_urgencia) : 'PostGIS')
        }</div>
        ${barraHTML}
        <table style="width:100%;border-collapse:collapse;">${filas}</table>
        ${p.id_parcela ? `
        <button onclick="window._irRiego && window._irRiego('${p.id_parcela}')"
            style="margin-top:12px;width:100%;padding:8px;background:#2d8254;color:#fff;border:none;
                   border-radius:8px;font-weight:700;cursor:pointer;font-size:0.82em;">
            Ver recomendación de riego →
        </button>` : ''}
    </div>`;
}

// ── Cargador genérico de GeoJSON ──────────────────────────────────────
async function cargarGeoJSON(ruta) {
    try {
        const response = await fetch(ruta);
        if (!response.ok) {
            console.warn(`[GIS] ${ruta} no disponible (HTTP ${response.status}). Capa omitida.`);
            return null;
        }
        const data = await response.json();
        if (!data.type || !data.features) {
            console.warn(`[GIS] ${ruta} no es un FeatureCollection válido.`);
            return null;
        }
        console.log(`[GIS] ✓ ${ruta} cargado — ${data.features.length} features`);
        return data;
    } catch (err) {
        console.warn(`[GIS] Error cargando ${ruta}:`, err.message);
        return null;
    }
}

/**
 * Carga parcelas desde la API de MILPÍN (/api/parcelas/geojson).
 * Fuente primaria: PostGIS real.
 * Fallback: archivo estático data/lotes.geojson (datos demo).
 */
async function cargarParcelasAPI() {
    const API_URL = 'http://127.0.0.1:8000/api/parcelas/geojson';
    try {
        const res = await fetch(API_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const fc = await res.json();
        const conGeom = (fc.features || []).filter(f => f.geometry != null);
        if (conGeom.length > 0) {
            console.log(`[GIS] ✓ API: ${conGeom.length} parcela(s) con geometría PostGIS`);
            return { ...fc, features: conGeom };
        }
        console.warn('[GIS] API sin geometría — usando lotes.geojson de demo');
    } catch (err) {
        console.warn('[GIS] API no disponible, usando lotes.geojson:', err.message);
    }
    return cargarGeoJSON('data/lotes.geojson');
}

// ── Leyenda NDVI como control Leaflet ─────────────────────────────────
function crearLeyendaNDVI(parcelas) {
    const LeyendaControl = L.Control.extend({
        options: { position: 'bottomright' },
        onAdd: function() {
            const div = L.DomUtil.create('div', 'control-leyenda-ndvi');

            // Calcular conteo por categoría si hay datos
            const conteos = { excelente: 0, saludable: 0, moderado: 0, alerta: 0, critico: 0 };
            if (parcelas) {
                parcelas.features.forEach(f => {
                    const ndvi = getNDVI(f.properties);
                    if      (ndvi >= 0.80) conteos.excelente++;
                    else if (ndvi >= 0.60) conteos.saludable++;
                    else if (ndvi >= 0.40) conteos.moderado++;
                    else if (ndvi >= 0.25) conteos.alerta++;
                    else                   conteos.critico++;
                });
            }

            const total = parcelas ? parcelas.features.length : 0;

            const niveles = [
                { color: '#00a600', label: '≥ 80%',    nombre: 'Excelente', n: conteos.excelente },
                { color: '#4cbb17', label: '60–79%',   nombre: 'Saludable', n: conteos.saludable },
                { color: '#d4c000', label: '40–59%',   nombre: 'Moderado',  n: conteos.moderado  },
                { color: '#e07000', label: '25–39%',   nombre: 'Alerta',    n: conteos.alerta    },
                { color: '#cc1800', label: '< 25%',    nombre: 'Crítico',   n: conteos.critico   },
            ];

            div.innerHTML = `
            <div style="background:rgba(255,255,255,0.95);padding:10px 14px;border-radius:10px;
                        font-family:'Segoe UI',sans-serif;font-size:0.76em;
                        box-shadow:0 2px 12px rgba(0,0,0,0.18);min-width:155px;">
                <div style="font-weight:800;margin-bottom:7px;color:#1a2e1f;letter-spacing:.3px;">
                    NDVI · Valle del Yaqui
                </div>
                <div style="height:8px;border-radius:4px;margin-bottom:8px;
                            background:linear-gradient(90deg,#cc1800,#e07000,#d4c000,#4cbb17,#00a600);"></div>
                ${niveles.map(e => `
                <div style="display:flex;align-items:center;gap:7px;margin-bottom:4px;">
                    <span style="width:12px;height:12px;border-radius:3px;background:${e.color};
                                 flex-shrink:0;display:inline-block;"></span>
                    <span style="color:#555;flex:1;">${e.nombre}</span>
                    <span style="color:#888;font-size:.9em;">${e.label}</span>
                    ${total > 0 ? `<span style="color:${e.color};font-weight:700;min-width:16px;text-align:right;">${e.n}</span>` : ''}
                </div>`).join('')}
                ${total > 0 ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #eee;
                                           color:#777;font-size:.88em;">Total: ${total} parcelas</div>` : ''}
            </div>`;
            return div;
        }
    });
    return new LeyendaControl();
}

// ── Badge resumen NDVI en esquina superior derecha ────────────────────
function crearBadgeResumen(parcelas) {
    if (!parcelas || !parcelas.features.length) return;

    const features  = parcelas.features;
    const total     = features.length;
    const ndviMedia = features.reduce((s, f) => s + getNDVI(f.properties), 0) / total;
    const criticas  = features.filter(f => getNDVI(f.properties) < 0.25).length;
    const color     = obtenerColorNDVI(ndviMedia);

    const BadgeControl = L.Control.extend({
        options: { position: 'topright' },
        onAdd: function() {
            const div = L.DomUtil.create('div', 'control-badge-resumen');
            div.innerHTML = `
            <div style="background:rgba(26,46,31,0.9);padding:8px 12px;border-radius:10px;
                        font-family:'Segoe UI',sans-serif;font-size:0.76em;color:#fff;
                        box-shadow:0 2px 12px rgba(0,0,0,0.25);min-width:170px;">
                <div style="font-weight:700;margin-bottom:5px;opacity:.7;letter-spacing:.4px;font-size:.9em;">
                    Resumen DR-041
                </div>
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>
                    <span style="opacity:.85;">NDVI promedio</span>
                    <span style="font-weight:800;margin-left:auto;color:${color};">${Math.round(ndviMedia*100)}%</span>
                </div>
                ${criticas > 0 ? `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:#cc1800;flex-shrink:0;"></span>
                    <span style="opacity:.85;">En estrés crítico</span>
                    <span style="font-weight:800;margin-left:auto;color:#ff6b6b;">${criticas} lotes</span>
                </div>` : ''}
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:#aaa;flex-shrink:0;"></span>
                    <span style="opacity:.85;">Total parcelas</span>
                    <span style="font-weight:800;margin-left:auto;">${total}</span>
                </div>
            </div>`;
            return div;
        }
    });
    return new BadgeControl();
}

// ── Inicialización del mapa ───────────────────────────────────────────
async function inicializarMapa() {
    if (mapaIniciado) return;
    mapaIniciado = true;

    map = L.map('map', {
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        zoomControl: true
    });

    // Bases cartográficas
    const baseSatelite = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Tiles &copy; Esri — USDA, GeoEye, GIS Community', maxZoom: 18 }
    );
    const baseTopo = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Tiles &copy; Esri — Esri, DeLorme, NAVTEQ', maxZoom: 18 }
    );

    baseSatelite.addTo(map);

    // Capa para resultados dinámicos
    capaAnalisis = L.layerGroup().addTo(map);

    // ── Carga paralela ──────────────────────────────────────────────
    // cajeme_limits.geojson existe en /data/ pero no se renderiza en el mapa.
    const [datosLotes, datosRios, datosCanales, datosPozos] = await Promise.all([
        cargarParcelasAPI(),
        cargarGeoJSON('data/red_hidrografica.geojson'),
        cargarGeoJSON('data/canales_riego.geojson'),
        cargarGeoJSON('data/pozos.geojson')
    ]);

    // 1. ── Parcelas agrícolas ────────────────────────────────────────
    if (datosLotes) {
        // Detectar fuente: API PostGIS (tiene id_parcela) vs fallback estático
        const esDesdeAPI = datosLotes.features.length > 0 &&
                           datosLotes.features[0].properties?.id_parcela != null;

        capaLotes = L.geoJSON(datosLotes, {
            style: (feature) => {
                const p    = feature.properties;
                const ndvi = getNDVI(p);
                const esCritico = ndvi < 0.25;
                return {
                    fillColor:   obtenerColorNDVI(ndvi),
                    fillOpacity: 0.82,
                    weight:      esCritico ? 2.5 : 1.5,
                    color:       esCritico ? '#ff4400' : 'rgba(255,255,255,0.7)',
                    dashArray:   esCritico ? '5,3' : null,
                    className:   esCritico ? 'parcela-critica' : ''
                };
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties;
                const popup = L.popup({ maxWidth: 300, className: 'popup-milpin' })
                               .setContent(crearHTMLPopup(p, esDesdeAPI));

                layer.bindPopup(popup);

                layer.on('mouseover', function () {
                    this.setStyle({ fillOpacity: 1, weight: 3 });
                    this.bringToFront();
                });
                layer.on('mouseout', function () {
                    capaLotes.resetStyle(this);
                });
                layer.on('click', function () {
                    actualizarPanelDetalle(p, esDesdeAPI);
                });
            }
        }).addTo(map);

        map.fitBounds(capaLotes.getBounds(), { padding: [30, 30] });

        // Leyenda NDVI en el mapa
        crearLeyendaNDVI(datosLotes).addTo(map);

        // Badge resumen en esquina superior derecha
        const badge = crearBadgeResumen(datosLotes);
        if (badge) badge.addTo(map);
    }

    // 3. ── Red hidrográfica ─────────────────────────────────────────
    if (datosRios) {
        capaRios = L.geoJSON(datosRios, {
            style: (feature) => {
                const tipo = (feature.properties.TIPO || feature.properties.tipo || '').toLowerCase();
                return tipo.includes('rio') || tipo.includes('río') ? ESTILOS.rio : ESTILOS.arroyo;
            },
            onEachFeature: (feature, layer) => {
                const nombre = feature.properties.NOMBRE || feature.properties.nombre || 'Sin nombre';
                const tipo   = feature.properties.TIPO   || feature.properties.tipo   || '';
                layer.bindPopup(`<b>${nombre}</b><br>Tipo: ${tipo}`);
            },
            filter: (feature) => feature.geometry && feature.geometry.coordinates
        }).addTo(map);
    }

    // 4. ── Canales de riego ─────────────────────────────────────────
    if (datosCanales) {
        capaCanales = L.geoJSON(datosCanales, {
            style: () => ESTILOS.canal,
            onEachFeature: (feature, layer) => {
                const nombre = feature.properties.NOMBRE || feature.properties.name
                             || feature.properties.nombre || 'Canal';
                layer.bindPopup(`<b>${nombre}</b><br>Infraestructura DR-041`);
            }
        }).addTo(map);
    }

    // 5. ── Pozos de extracción ──────────────────────────────────────
    if (datosPozos) {
        capaPozos = L.geoJSON(datosPozos, {
            pointToLayer: (feature, latlng) => {
                const flujo  = feature.properties.flujo || '';
                const esBajo = flujo.toLowerCase().includes('bajo') ||
                               (parseInt(flujo) > 0 && parseInt(flujo) < 20);
                return L.circleMarker(latlng, esBajo ? ESTILOS.pozo_bajo : ESTILOS.pozo_activo);
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties;
                layer.bindPopup(
                    `<b>${p.nombre || 'Pozo'}</b><br>` +
                    `Flujo: ${p.flujo || 'N/D'}<br>` +
                    `Estado: ${p.estado || 'N/D'}`
                );
            }
        }).addTo(map);
    }

    // ── Control de capas ──────────────────────────────────────────────
    const baseMaps = {
        "Satélite (Esri)": baseSatelite,
        "Topográfico":     baseTopo
    };
    const overlays = {};
    if (capaLotes)   overlays["Parcelas (NDVI)"]         = capaLotes;
    if (capaRios)    overlays["Red Hidrográfica"]        = capaRios;
    if (capaCanales) overlays["Canales DR-041"]          = capaCanales;
    if (capaPozos)   overlays["Pozos de Extracción"]     = capaPozos;
    overlays["Análisis (K-Means)"] = capaAnalisis;

    L.control.layers(baseMaps, overlays, { collapsed: true }).addTo(map);

    // ── Escala métrica ────────────────────────────────────────────────
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

    // ── Bridge: botón "Ver recomendación" dentro del popup ────────────
    window._irRiego = function(idParcela) {
        if (typeof cambiarPestana === 'function') {
            cambiarPestana(null, 'tab-costos');
            setTimeout(() => {
                const sel = document.getElementById('select-parcela-riego');
                if (sel) { sel.value = idParcela; sel.dispatchEvent(new Event('change')); }
            }, 200);
        }
    };

    console.log("[GIS] Mapa v2.1 inicializado — NDVI mejorado, Cajeme delimitado.");
}

// ── Panel de detalle de parcela (bajo el mapa) ────────────────────────
function actualizarPanelDetalle(p, esDesdeAPI) {
    const panel = document.getElementById('parcela-detalle-card');
    if (!panel) return;

    const ndvi    = getNDVI(p);
    const ndviPct = Math.round(ndvi * 100);
    const color   = obtenerColorNDVI(ndvi);
    const clasif  = clasificarNDVI(ndvi);

    // Indicador consumo vs objetivo
    const consumo  = p.consumo_ciclo_m3ha;
    const objetivo = 6000;
    const linea_base = 8000;
    let consumoHTML = '';
    if (consumo) {
        const exceso  = consumo - objetivo;
        const ahorro  = linea_base - consumo;
        const colorConsumopct = consumo <= objetivo ? '#00a600'
                               : consumo <= 7000    ? '#d4c000'
                               : '#cc1800';
        consumoHTML = `
        <div style="margin-top:14px;padding-top:12px;border-top:1px solid #eee;">
            <div style="font-size:.78em;font-weight:700;color:#555;margin-bottom:8px;text-transform:uppercase;letter-spacing:.4px;">
                Consumo hídrico del ciclo
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-size:.76em;color:#777;width:80px;">Esta parcela</span>
                <div style="flex:1;height:8px;background:#eee;border-radius:4px;overflow:hidden;">
                    <div style="width:${Math.min(100, (consumo/linea_base)*100)}%;height:100%;background:${colorConsumopct};border-radius:4px;"></div>
                </div>
                <span style="font-size:.8em;font-weight:700;color:${colorConsumopct};">${consumo.toLocaleString('es-MX')} m³/ha</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-size:.76em;color:#777;width:80px;">Objetivo MILPÍN</span>
                <div style="flex:1;height:8px;background:#eee;border-radius:4px;overflow:hidden;">
                    <div style="width:${(objetivo/linea_base)*100}%;height:100%;background:#00a600;border-radius:4px;"></div>
                </div>
                <span style="font-size:.8em;font-weight:700;color:#00a600;">${objetivo.toLocaleString('es-MX')} m³/ha</span>
            </div>
            <div style="font-size:.75em;margin-top:4px;${ahorro > 0 ? 'color:#00a600;' : 'color:#cc1800;'}font-weight:600;">
                ${ahorro > 0
                    ? `✓ Ahorro vs baseline: ${ahorro.toLocaleString('es-MX')} m³/ha`
                    : `⚠ Exceso vs objetivo: ${Math.abs(exceso).toLocaleString('es-MX')} m³/ha`}
            </div>
        </div>`;
    }

    panel.innerHTML = `
    <div style="font-family:'Segoe UI',sans-serif;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
            <div>
                <span style="font-weight:800;font-size:1.05em;color:#1a2e1f;">${p.nombre || 'Parcela'}</span>
                &nbsp;
                <span style="font-size:.78em;color:#888;">${p.modulo || ''}</span>
            </div>
            <span style="font-size:1.3em;">${clasif.emoji}</span>
        </div>

        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
            <div style="flex:1;height:12px;background:#e8e8e8;border-radius:6px;overflow:hidden;">
                <div style="width:${ndviPct}%;height:100%;background:linear-gradient(90deg,${ndvi<.25?'#ff4500':color},${color});border-radius:6px;"></div>
            </div>
            <span style="font-weight:800;color:${color};font-size:1em;min-width:42px;text-align:right;">NDVI ${ndviPct}%</span>
        </div>

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:6px;">
            ${[
                { label: 'Cultivo',    val: p.cultivo       || '—' },
                { label: 'Superficie', val: p.area_ha ? p.area_ha + ' ha' : '—' },
                { label: 'Riego',      val: p.sistema_riego || '—' },
                { label: 'Suelo',      val: p.tipo_suelo    || '—' },
                { label: 'Sin riego',  val: p.dias_sin_riego != null ? p.dias_sin_riego + ' días' : '—',
                  color: p.dias_sin_riego > 14 ? '#cc1800' : '#1a2e1f' },
                { label: 'Déficit',    val: p.deficit_hidrico != null ? p.deficit_hidrico + ' mm' : '—',
                  color: p.deficit_hidrico > 60 ? '#cc1800' : '#1a2e1f' },
            ].map(item => `
            <div style="background:#f8f5f0;border-radius:8px;padding:8px;">
                <div style="font-size:.68em;color:#999;margin-bottom:2px;">${item.label}</div>
                <div style="font-weight:700;font-size:.85em;color:${item.color || '#1a2e1f'};">${item.val}</div>
            </div>`).join('')}
        </div>
        ${consumoHTML}
    </div>`;

    panel.style.display = 'block';
}

// ── Análisis: Clustering logístico K-Means ────────────────────────────
async function ejecutarAnalisisSIG() {
    console.log("[GIS] Conectando con el motor de clustering Python...");
    if (capaAnalisis) capaAnalisis.clearLayers();

    try {
        const response = await fetch('http://127.0.0.1:8000/api/logistica_inteligente');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        if (data.status !== "success") {
            console.error("[GIS] Respuesta inesperada del backend:", data);
            return;
        }

        const warehouseIcon = L.icon({
            iconUrl:    'https://cdn-icons-png.flaticon.com/512/2311/2311110.png',
            iconSize:   [40, 40],
            iconAnchor: [20, 40],
            popupAnchor:[0, -35]
        });

        data.puntos_demanda.forEach(p => {
            L.circleMarker([p[0], p[1]], {
                radius: 5, color: '#E67E22', fillOpacity: 0.8, weight: 1
            }).addTo(capaAnalisis);
        });

        data.almacenes_sugeridos.forEach((centro, i) => {
            L.marker([centro[0], centro[1]], { icon: warehouseIcon })
                .addTo(capaAnalisis)
                .bindPopup(
                    `<b>Almacén Sugerido ${i + 1}</b><br>` +
                    `Lat: ${centro[0].toFixed(4)}, Lng: ${centro[1].toFixed(4)}<br>` +
                    `Optimizado por K-Means (n=3)`
                );
            L.circle([centro[0], centro[1]], {
                color: '#27AE60', fillColor: '#2ECC71',
                fillOpacity: 0.15, radius: 800, weight: 1.5
            }).addTo(capaAnalisis);
        });

        const bounds = capaAnalisis.getLayers().length > 0
            ? L.featureGroup(capaAnalisis.getLayers()).getBounds()
            : null;
        if (bounds && bounds.isValid()) {
            map.flyToBounds(bounds, { padding: [40, 40], duration: 1.2 });
        }

        console.log(`[GIS] Clustering: ${data.almacenes_sugeridos.length} almacenes sugeridos.`);

    } catch (error) {
        console.error("[GIS] Error en la API de analítica espacial:", error);
    }
}
