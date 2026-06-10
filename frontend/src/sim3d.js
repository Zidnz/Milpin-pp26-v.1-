/* ════════════════════════════════════════════════════════════════════
   sim3d.js — Simulador 3D de parcela MILPÍN
   ────────────────────────────────────────────────────────────────────
   Simula un ciclo agrícola completo día a día sobre la geometría real
   de la parcela (PostGIS → GeoJSON) y compara dos estrategias de riego
   bajo el MISMO clima sintético determinista:

     · Tradicional — calendario fijo por gravedad (práctica actual DR-041)
     · MILPÍN      — riego por demanda FAO-56 (50% del agua disponible)

   Motor agronómico: espejo cliente de backend/core/balance_hidrico.py
     θ[t] = clamp(θ[t-1] + (lluvia + riego_neto − ETa)/(prof·10), PMP, CC)
     Ks   = FAO-56 Ec. 84 (lineal entre umbral y PMP)
     Ya   = Ymax·(1 − Ky·(1 − ΣETa/ΣETc))   ← FAO-33 (Doorenbos & Kassam)

   Render: Three.js r147 (UMD, unpkg — mismo patrón CDN que Leaflet).
   Se carga LAZY al abrir el simulador por primera vez, igual que
   Whisper en el backend: cero costo en el arranque de la app.

   API consumida:
     GET /api/parcelas/{id}  → geom_geojson, CC, PMP, prof_raíz, sistema
     GET /api/cultivos       → kc, etapas, ky_total, rendimiento_potencial
   ════════════════════════════════════════════════════════════════════ */
(function () {
    "use strict";

    const API = (typeof API_BASE !== "undefined")
        ? API_BASE
        : "https://milpin-pp26-v1-production.up.railway.app/api";

    const THREE_CDN = "https://unpkg.com/three@0.147.0/build/three.min.js";
    const ORBIT_CDN = "https://unpkg.com/three@0.147.0/examples/js/controls/OrbitControls.js";

    // ── Constantes de negocio (mismas fuentes que el backend) ──────────
    const TARIFA_M3_MXN = 1.68;   // CFE 9-CU, bombeo 80 m — baseline CLAUDE.md
    const EFICIENCIA_RIEGO = {    // backend/core/balance_hidrico.py
        gravedad: 0.65, aspersion: 0.80, microaspersion: 0.82, goteo: 0.90,
    };

    // Práctica tradicional DR-041: riegos de auxilio por calendario, gravedad.
    // 100 mm brutos cada 14 días ≈ 8,000–9,000 m³/ha/ciclo (baseline del KPI).
    const TRAD_INTERVALO_DIAS = 14;
    const TRAD_LAMINA_BRUTA_MM = 100;
    const TRAD_PRIMER_RIEGO_DIA = 7;
    const TRAD_ULTIMO_RIEGO_MARGEN = 14; // no se riega en los últimos N días

    // ── Catálogo fallback si /api/cultivos no responde ─────────────────
    // Kc y etapas: espejo de KC_TABLE (FAO-56 Tabla 12).
    // Ky: FAO-33 Tabla 24. Rendimiento potencial y precio: estimaciones
    // DR-041 — solo para ilustrar el impacto económico, no son dato duro.
    const CATALOGO_FALLBACK = {
        maiz:    { kc: [0.30, 1.20, 0.60], etapas: [25, 40, 45, 30], ky: 1.25, rend: 12.0 },
        frijol:  { kc: [0.40, 1.15, 0.35], etapas: [20, 30, 40, 20], ky: 1.15, rend: 2.6 },
        algodon: { kc: [0.35, 1.20, 0.70], etapas: [30, 50, 55, 45], ky: 0.85, rend: 5.0 },
        uva:     { kc: [0.30, 0.85, 0.45], etapas: [30, 60, 75, 50], ky: 0.85, rend: 20.0 },
        chile:   { kc: [0.60, 1.05, 0.90], etapas: [30, 35, 40, 20], ky: 1.10, rend: 28.0 },
    };
    const PRECIO_TON_MXN = { maiz: 5800, frijol: 24000, algodon: 11500, uva: 26000, chile: 9500 };
    const NOMBRE_CULTIVO = { maiz: "Maíz", frijol: "Frijol", algodon: "Algodón", uva: "Uva", chile: "Chile" };

    // Apariencia 3D por cultivo: altura máx (m), forma y colores de planta
    const VISUAL_CULTIVO = {
        maiz:    { hMax: 2.3, forma: "cono",   verde: 0x2f8f46, fruto: null },
        frijol:  { hMax: 0.55, forma: "esfera", verde: 0x3ba55d, fruto: null },
        algodon: { hMax: 1.25, forma: "esfera", verde: 0x4f9e5f, fruto: 0xf4f2ec },
        uva:     { hMax: 1.8, forma: "esfera", verde: 0x3e7d3a, fruto: 0x5b2d7e },
        chile:   { hMax: 0.85, forma: "esfera", verde: 0x2e8b57, fruto: 0xd63a2f },
    };

    // ── Estado del módulo ───────────────────────────────────────────────
    let _threeListo = false;
    let _catalogoAPI = null;          // cache de /api/cultivos
    let _overlay = null;              // raíz DOM
    let _scene, _camera, _renderer, _controls, _rafId = null;
    let _campo = null;                // { sueloMesh, aguaMesh, plantas, frutos, ... }
    let _sim = null;                  // { clima, tradicional, milpin, cfg }
    let _escenario = "milpin";        // escenario que se ve en 3D
    let _diaActual = 0;
    let _reproduciendo = false;
    let _velocidad = 3;               // días por segundo
    let _acumulador = 0;
    let _relojPrev = null;
    let _aguaOpacidad = 0;
    let _ultimoG = -1;                // growth aplicado a las matrices

    // ════════════════════════════════════════════════════════════════
    //  UTILIDADES
    // ════════════════════════════════════════════════════════════════

    function _normalizar(nombre) {
        return (nombre || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
    }

    // PRNG determinista (mulberry32): mismo clima para ambos escenarios
    // y reproducible entre sesiones → la comparación es justa.
    function _mulberry32(semilla) {
        let a = semilla >>> 0;
        return function () {
            a |= 0; a = (a + 0x6D2B79F5) | 0;
            let t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function _hashStr(s) {
        let h = 2166136261;
        for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
        return h >>> 0;
    }

    function _cargarScript(src) {
        return new Promise((ok, err) => {
            const tag = document.createElement("script");
            tag.src = src;
            tag.onload = ok;
            tag.onerror = () => err(new Error("No se pudo cargar " + src));
            document.head.appendChild(tag);
        });
    }

    async function _asegurarThree() {
        if (_threeListo) return;
        if (typeof THREE === "undefined") await _cargarScript(THREE_CDN);
        if (typeof THREE.OrbitControls === "undefined") await _cargarScript(ORBIT_CDN);
        _threeListo = true;
    }

    // ════════════════════════════════════════════════════════════════
    //  DATOS — parcela y catálogo de cultivos
    // ════════════════════════════════════════════════════════════════

    async function _obtenerParcela(idParcela) {
        if (!idParcela) return null;
        try {
            const res = await fetch(`${API}/parcelas/${idParcela}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (e) {
            console.warn("[SIM3D] No se pudo cargar la parcela:", e.message);
            return null;
        }
    }

    async function _obtenerCatalogo() {
        if (_catalogoAPI) return _catalogoAPI;
        try {
            const res = await fetch(`${API}/cultivos`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const lista = await res.json();
            const mapa = {};
            lista.forEach(c => {
                mapa[_normalizar(c.nombre_comun)] = {
                    kc: [Number(c.kc_inicial), Number(c.kc_medio), Number(c.kc_final)],
                    etapas: [c.dias_etapa_inicial, c.dias_etapa_desarrollo,
                             c.dias_etapa_media, c.dias_etapa_final],
                    ky: Number(c.ky_total),
                    rend: c.rendimiento_potencial_ton != null
                        ? Number(c.rendimiento_potencial_ton)
                        : (CATALOGO_FALLBACK[_normalizar(c.nombre_comun)]?.rend ?? 10),
                };
            });
            if (Object.keys(mapa).length) { _catalogoAPI = mapa; return mapa; }
        } catch (e) {
            console.warn("[SIM3D] /api/cultivos no disponible, uso catálogo local:", e.message);
        }
        return CATALOGO_FALLBACK;
    }

    // ════════════════════════════════════════════════════════════════
    //  MOTOR AGRONÓMICO (espejo de balance_hidrico.py)
    // ════════════════════════════════════════════════════════════════

    // Kc por interpolación lineal en 4 etapas — idéntico a obtener_kc()
    function _kcDia(cat, d) {
        const [kIni, kMed, kFin] = cat.kc;
        const [dIni, dDes, dMed, dFin] = cat.etapas;
        const finIni = dIni, finDes = finIni + dDes, finMed = finDes + dMed, finFin = finMed + dFin;
        if (d <= finIni) return kIni;
        if (d <= finDes) return kIni + (kMed - kIni) * ((d - finIni) / dDes);
        if (d <= finMed) return kMed;
        if (d <= finFin) return kMed + (kFin - kMed) * ((d - finMed) / dFin);
        return kFin;
    }

    function _etapaDia(cat, d) {
        const [dIni, dDes, dMed] = cat.etapas;
        if (d <= dIni) return "Inicial";
        if (d <= dIni + dDes) return "Desarrollo";
        if (d <= dIni + dDes + dMed) return "Mediados";
        return "Final · maduración";
    }

    // Clima sintético del Valle del Yaqui: ETo estacional senoidal
    // (~2.4 mm/d invierno, ~7.4 mm/d junio) + lluvia tipo monzón jul–sep.
    // Sustituible por clima_diario real cuando exista endpoint de serie.
    function _generarClima(fechaSiembra, dias, semilla) {
        const rnd = _mulberry32(semilla);
        const clima = [];
        const inicio = new Date(fechaSiembra.getTime());
        for (let i = 0; i < dias; i++) {
            const f = new Date(inicio.getTime() + i * 86400000);
            const doy = Math.floor((f - new Date(f.getFullYear(), 0, 0)) / 86400000);
            let eto = 4.9 + 2.5 * Math.sin(2 * Math.PI * (doy - 81) / 365) + (rnd() - 0.5);
            eto = Math.max(1.2, eto);
            const monzon = doy >= 185 && doy <= 260;
            const pLluvia = monzon ? 0.20 : 0.03;
            let lluvia = 0;
            if (rnd() < pLluvia) {
                lluvia = Math.min(45, -(monzon ? 8 : 4) * Math.log(Math.max(1e-6, rnd())));
            }
            clima.push({ fecha: f, eto: +eto.toFixed(2), lluvia: +lluvia.toFixed(1) });
        }
        return clima;
    }

    /**
     * Simula un ciclo completo con una estrategia de riego.
     * estrategia(dia, thetaPct, ctx) → lámina BRUTA mm a aplicar hoy (0 = no riega).
     * El agua útil es bruta·eficiencia; lo que excede CC se pierde
     * (escurrimiento/percolación) pero SÍ se contabiliza como aplicada —
     * ahí vive el desperdicio del riego por calendario.
     */
    function _simularEstrategia(cat, clima, suelo, eficiencia, estrategia) {
        const { ccPct, pmpPct, profM } = suelo;
        const umbral = pmpPct + 0.5 * (ccPct - pmpPct);   // 50% ADT (FAO-56)
        const dias = [];
        let theta = ccPct;            // siembra con suelo a capacidad de campo
        let etaSum = 0, etcSum = 0, aguaBruta = 0, nRiegos = 0, diasEstres = 0;

        for (let i = 0; i < clima.length; i++) {
            const d = i + 1;
            const kc = _kcDia(cat, d);
            const etc = clima[i].eto * kc;

            // 1) Decisión de riego en la mañana, con la humedad de ayer
            const bruta = estrategia(d, theta, { umbral, ccPct, pmpPct, profM, clima });
            let netaUtil = 0;
            if (bruta > 0) {
                const netaDisponible = bruta * eficiencia;
                const capacidadMm = (ccPct - theta) * profM * 10;
                netaUtil = Math.min(netaDisponible, Math.max(0, capacidadMm));
                aguaBruta += bruta;
                nRiegos += 1;
            }
            theta = Math.min(ccPct, theta + netaUtil / (profM * 10));

            // 2) Consumo del día: Ks lineal FAO-56 Ec. 84 (p = 0.5)
            const ks = theta >= umbral ? 1 : Math.max(0, (theta - pmpPct) / (umbral - pmpPct));
            const eta = etc * ks;
            if (ks < 0.95) diasEstres += 1;

            // 3) Balance: lluvia entra, ETa sale, clamp [PMP, CC]
            theta += (clima[i].lluvia - eta) / (profM * 10);
            theta = Math.max(pmpPct, Math.min(ccPct, theta));

            etaSum += eta; etcSum += etc;
            dias.push({
                dia: d, fecha: clima[i].fecha, kc: +kc.toFixed(2),
                eto: clima[i].eto, etc: +etc.toFixed(2), lluvia: clima[i].lluvia,
                riegoBruto: bruta, ks: +ks.toFixed(3), theta: +theta.toFixed(3),
                etapa: _etapaDia(cat, d),
            });
        }

        // FAO-33: Ya/Ymax = 1 − Ky·(1 − ETa/ETc)
        const relEt = etcSum > 0 ? etaSum / etcSum : 1;
        const fraccionRend = Math.max(0, 1 - cat.ky * (1 - relEt));
        const volumenM3Ha = aguaBruta * 10;              // 1 mm = 10 m³/ha

        return {
            dias,
            totales: {
                aguaBrutaMm: +aguaBruta.toFixed(0),
                volumenM3Ha: +volumenM3Ha.toFixed(0),
                nRiegos,
                diasEstres,
                relEt: +relEt.toFixed(3),
                fraccionRend: +fraccionRend.toFixed(3),
                rendTonHa: +(cat.rend * fraccionRend).toFixed(2),
                costoAguaMxnHa: +(volumenM3Ha * TARIFA_M3_MXN).toFixed(0),
            },
        };
    }

    function _correrComparativa(cfg) {
        const cat = cfg.cat;
        const ciclo = cat.etapas.reduce((a, b) => a + b, 0);
        const semilla = _hashStr((cfg.idParcela || "demo") + cfg.fechaSiembra.toISOString().slice(0, 10));
        const clima = _generarClima(cfg.fechaSiembra, ciclo, semilla);
        const suelo = { ccPct: cfg.ccPct, pmpPct: cfg.pmpPct, profM: cfg.profM };

        // Tradicional: calendario fijo, siempre gravedad (práctica actual)
        const tradicional = _simularEstrategia(cat, clima, suelo, EFICIENCIA_RIEGO.gravedad,
            (d) => {
                const ultimo = ciclo - TRAD_ULTIMO_RIEGO_MARGEN;
                if (d >= TRAD_PRIMER_RIEGO_DIA && d <= ultimo &&
                    (d - TRAD_PRIMER_RIEGO_DIA) % TRAD_INTERVALO_DIAS === 0) {
                    return TRAD_LAMINA_BRUTA_MM;
                }
                return 0;
            });

        // MILPÍN: riega solo al cruzar el umbral, la lámina justa hasta CC
        const efMilpin = EFICIENCIA_RIEGO[cfg.sistema] ?? 0.75;
        const milpin = _simularEstrategia(cat, clima, suelo, efMilpin,
            (d, theta, ctx) => {
                if (theta > ctx.umbral) return 0;
                const netaMm = (ctx.ccPct - theta) * ctx.profM * 10;
                return netaMm / efMilpin;
            });

        return { clima, tradicional, milpin, ciclo, cfg };
    }

    // ════════════════════════════════════════════════════════════════
    //  GEOMETRÍA — GeoJSON (lon/lat) → metros locales
    // ════════════════════════════════════════════════════════════════

    function _anilloAMetros(anillo) {
        // Proyección equirectangular local: suficiente para lotes < 2 km
        let lon0 = 0, lat0 = 0;
        anillo.forEach(c => { lon0 += c[0]; lat0 += c[1]; });
        lon0 /= anillo.length; lat0 /= anillo.length;
        const kx = 111320 * Math.cos(lat0 * Math.PI / 180);
        const kz = 110540;
        return anillo.map(c => [(c[0] - lon0) * kx, -(c[1] - lat0) * kz]); // -z = norte arriba
    }

    function _poligonoDeParcela(parcela) {
        const g = parcela?.geom_geojson;
        let anillo = null;
        if (g?.type === "Polygon") anillo = g.coordinates?.[0];
        else if (g?.type === "MultiPolygon") anillo = g.coordinates?.[0]?.[0];
        if (anillo && anillo.length >= 4) return _anilloAMetros(anillo);

        // Fallback: rectángulo con el área real de la parcela (o 10 ha demo)
        const areaHa = Number(parcela?.area_ha) || 10;
        const lado = Math.sqrt(areaHa * 10000);
        const w = lado * 1.4, h = (areaHa * 10000) / w;
        return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2], [-w / 2, -h / 2]];
    }

    function _puntoEnPoligono(x, z, pts) {
        let dentro = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const xi = pts[i][0], zi = pts[i][1], xj = pts[j][0], zj = pts[j][1];
            if (((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi) + xi)) {
                dentro = !dentro;
            }
        }
        return dentro;
    }

    // ════════════════════════════════════════════════════════════════
    //  ESCENA THREE.JS
    // ════════════════════════════════════════════════════════════════

    const ALTURA_SUELO = 1.4;

    function _crearEscena(canvasWrap, poligono, cultivoKey) {
        // Limpieza de escena previa (reabrir / reiniciar)
        _destruirEscena();

        const ancho = canvasWrap.clientWidth, alto = canvasWrap.clientHeight;
        _renderer = new THREE.WebGLRenderer({ antialias: true });
        _renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        _renderer.setSize(ancho, alto);
        _renderer.shadowMap.enabled = true;
        _renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        canvasWrap.appendChild(_renderer.domElement);

        _scene = new THREE.Scene();
        _scene.background = new THREE.Color(0xbfdcf0);

        // Bounding box del polígono → encuadre de cámara y luces
        let minX = 1e9, maxX = -1e9, minZ = 1e9, maxZ = -1e9;
        poligono.forEach(p => {
            minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]);
            minZ = Math.min(minZ, p[1]); maxZ = Math.max(maxZ, p[1]);
        });
        const tam = Math.max(maxX - minX, maxZ - minZ, 60);
        const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
        _scene.fog = new THREE.Fog(0xbfdcf0, tam * 3, tam * 9);

        _camera = new THREE.PerspectiveCamera(55, ancho / alto, 0.5, tam * 20);
        _camera.position.set(cx + tam * 0.85, tam * 0.65, cz + tam * 0.85);

        _controls = new THREE.OrbitControls(_camera, _renderer.domElement);
        _controls.target.set(cx, ALTURA_SUELO, cz);
        _controls.maxPolarAngle = 1.45;
        _controls.minDistance = tam * 0.15;
        _controls.maxDistance = tam * 4;
        _controls.enableDamping = true;
        _controls.dampingFactor = 0.08;

        // Luces: hemisferio (cielo/desierto) + sol direccional con sombras
        _scene.add(new THREE.HemisphereLight(0xcfe8ff, 0xb59a6a, 0.85));
        const sol = new THREE.DirectionalLight(0xfff4d6, 1.15);
        sol.position.set(cx - tam, tam * 1.6, cz - tam * 0.4);
        sol.castShadow = true;
        sol.shadow.mapSize.set(1024, 1024);
        const s = tam * 1.2;
        sol.shadow.camera.left = -s; sol.shadow.camera.right = s;
        sol.shadow.camera.top = s; sol.shadow.camera.bottom = -s;
        sol.shadow.camera.far = tam * 6;
        sol.target.position.set(cx, 0, cz);
        _scene.add(sol, sol.target);

        // Terreno circundante (desierto sonorense)
        const piso = new THREE.Mesh(
            new THREE.CircleGeometry(tam * 8, 48),
            new THREE.MeshLambertMaterial({ color: 0xc9b287 })
        );
        piso.rotation.x = -Math.PI / 2;
        piso.receiveShadow = true;
        _scene.add(piso);

        // Bloque de suelo de la parcela: extrusión del polígono real
        const forma = new THREE.Shape(poligono.map(p => new THREE.Vector2(p[0], p[1])));
        const geoSuelo = new THREE.ExtrudeGeometry(forma, { depth: ALTURA_SUELO, bevelEnabled: false });
        const matSuelo = new THREE.MeshLambertMaterial({ color: 0x4a3a2a });
        const suelo = new THREE.Mesh(geoSuelo, matSuelo);
        suelo.rotation.x = -Math.PI / 2;   // shape XY → plano XZ, extrusión hacia +Y
        suelo.receiveShadow = true;
        _scene.add(suelo);

        // Lámina de agua (animación de riego): misma silueta, casi a ras
        const aguaMesh = new THREE.Mesh(
            new THREE.ShapeGeometry(forma),
            new THREE.MeshBasicMaterial({ color: 0x2f8fd8, transparent: true, opacity: 0, depthWrite: false })
        );
        aguaMesh.rotation.x = -Math.PI / 2;
        aguaMesh.position.y = ALTURA_SUELO + 0.08;
        _scene.add(aguaMesh);

        // ── Plantas en surcos (InstancedMesh: 3 draw calls totales) ────
        const vis = VISUAL_CULTIVO[cultivoKey] || VISUAL_CULTIVO.maiz;
        const areaM2 = (maxX - minX) * (maxZ - minZ);
        const MAX_PLANTAS = 1800;
        const paso = Math.max(2.5, Math.sqrt(areaM2 / MAX_PLANTAS));
        const posiciones = [];
        const rndPlanta = _mulberry32(1234);
        for (let x = minX + paso / 2; x < maxX; x += paso) {
            for (let z = minZ + paso / 2; z < maxZ; z += paso) {
                if (_puntoEnPoligono(x, z, poligono)) {
                    posiciones.push({
                        x: x + (rndPlanta() - 0.5) * paso * 0.25,
                        z,                                    // surcos rectos en z
                        esc: 0.8 + rndPlanta() * 0.45,        // variación natural
                        rot: rndPlanta() * Math.PI * 2,
                    });
                }
            }
        }
        const n = posiciones.length;
        // Cada instancia representa varias plantas reales: el ancho de copa
        // se escala al espaciamiento (las copas casi se tocan con g=1) para
        // que el campo se lea lleno; la altura crece menos para no deformar.
        const diamCopaM = paso * 0.85;
        const escAltura = Math.min(3.0, Math.max(1, paso / 2.5));

        const matTallo = new THREE.MeshLambertMaterial({ color: 0x6d8f3a });
        const matCopa = new THREE.MeshLambertMaterial({ color: vis.verde });
        const tallos = new THREE.InstancedMesh(
            new THREE.CylinderGeometry(0.05, 0.09, 1, 5), matTallo, n);
        const geoCopa = vis.forma === "cono"
            ? new THREE.ConeGeometry(0.45, 1.2, 7)
            : new THREE.SphereGeometry(0.5, 8, 6);
        const copas = new THREE.InstancedMesh(geoCopa, matCopa, n);
        copas.castShadow = true;

        let frutos = null, matFruto = null;
        if (vis.fruto != null) {
            matFruto = new THREE.MeshLambertMaterial({ color: vis.fruto });
            frutos = new THREE.InstancedMesh(new THREE.SphereGeometry(0.11, 6, 5), matFruto, n);
        }
        _scene.add(tallos, copas);
        if (frutos) _scene.add(frutos);

        _campo = {
            suelo, matSuelo, aguaMesh, tallos, copas, frutos, matCopa, matFruto,
            posiciones, vis, tam, cx, cz, diamCopaM, escAltura,
        };
        _ultimoG = -1;

        // Resize handler
        _campo.onResize = () => {
            const w = canvasWrap.clientWidth, h = canvasWrap.clientHeight;
            if (!w || !h) return;
            _camera.aspect = w / h;
            _camera.updateProjectionMatrix();
            _renderer.setSize(w, h);
        };
        window.addEventListener("resize", _campo.onResize);
    }

    function _destruirEscena() {
        if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
        if (_campo?.onResize) window.removeEventListener("resize", _campo.onResize);
        if (_renderer) {
            _renderer.dispose();
            _renderer.domElement?.remove();
        }
        if (_scene) {
            _scene.traverse(o => {
                if (o.geometry) o.geometry.dispose();
                if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose());
            });
        }
        _scene = _camera = _renderer = _controls = _campo = null;
    }

    // Reconstruye las matrices de instancias para una fracción de
    // crecimiento g (0–1). Solo se llama cuando g cambió lo suficiente.
    function _aplicarCrecimiento(g) {
        const { tallos, copas, frutos, posiciones, vis, diamCopaM, escAltura } = _campo;
        const m = new THREE.Matrix4();
        const q = new THREE.Quaternion();
        const ejeY = new THREE.Vector3(0, 1, 0);
        const gn = Math.max(0.06, g);
        const hTotal = vis.hMax * gn * escAltura;
        const hTallo = hTotal * 0.45;
        const hCopa = hTotal * 0.8;
        // Diámetro de la geometría base: cono r=0.45 → 0.9 m; esfera r=0.5 → 1 m
        const diamGeo = vis.forma === "cono" ? 0.9 : 1.0;
        const sXZ = (diamCopaM * gn) / diamGeo;
        const yEscCopa = hCopa / (vis.forma === "cono" ? 1.2 : 1.0);
        const base = ALTURA_SUELO;

        for (let i = 0; i < posiciones.length; i++) {
            const p = posiciones[i];
            q.setFromAxisAngle(ejeY, p.rot);

            m.compose(
                new THREE.Vector3(p.x, base + (hTallo * p.esc) / 2, p.z),
                q, new THREE.Vector3(sXZ * 0.22 * p.esc, hTallo * p.esc, sXZ * 0.22 * p.esc));
            tallos.setMatrixAt(i, m);

            const yCopa = vis.forma === "cono"
                ? base + hTallo * p.esc + (hCopa * p.esc) / 2
                : base + hTallo * p.esc + (hCopa * p.esc) * 0.35;
            m.compose(
                new THREE.Vector3(p.x, yCopa, p.z),
                q, new THREE.Vector3(sXZ * p.esc, yEscCopa * p.esc, sXZ * p.esc));
            copas.setMatrixAt(i, m);

            if (frutos) {
                const escF = _campo.frutoVisible ? p.esc * sXZ * 0.32 : 0.0001;
                m.compose(
                    new THREE.Vector3(p.x + sXZ * 0.3 * p.esc, yCopa - hCopa * 0.15, p.z + sXZ * 0.25),
                    q, new THREE.Vector3(escF, escF, escF));
                frutos.setMatrixAt(i, m);
            }
        }
        tallos.instanceMatrix.needsUpdate = true;
        copas.instanceMatrix.needsUpdate = true;
        if (frutos) frutos.instanceMatrix.needsUpdate = true;
    }

    // ════════════════════════════════════════════════════════════════
    //  ACTUALIZACIÓN VISUAL POR DÍA
    // ════════════════════════════════════════════════════════════════

    function _aplicarDia(idx, esSalto) {
        if (!_sim || !_campo) return;
        const datos = _sim[_escenario].dias;
        idx = Math.max(0, Math.min(idx, datos.length - 1));
        _diaActual = idx;
        const dia = datos[idx];
        const cat = _sim.cfg.cat;
        const { ccPct, pmpPct } = _sim.cfg;

        // 1) Crecimiento: fracción de desarrollo de copa desde la curva Kc
        const [kIni, kMed] = [cat.kc[0], cat.kc[1]];
        const g = Math.max(0, Math.min(1, (dia.kc - kIni) / Math.max(0.01, kMed - kIni)));
        const visible = _campo.frutoVisible;
        const [dIni, dDes] = cat.etapas;
        _campo.frutoVisible = dia.dia > dIni + dDes;      // frutos desde mediados
        if (Math.abs(g - _ultimoG) > 0.02 || visible !== _campo.frutoVisible) {
            _aplicarCrecimiento(g);
            _ultimoG = g;
        }

        // 2) Color de copa: estrés seca, senescencia dora
        const verde = new THREE.Color(_campo.vis.verde);
        const seco = new THREE.Color(0x9a7b34);
        const dorado = new THREE.Color(0xc8a14b);
        const estres = 1 - dia.ks;                         // 0 sano → 1 marchito
        const finMed = cat.etapas[0] + cat.etapas[1] + cat.etapas[2];
        const sen = dia.dia > finMed
            ? Math.min(1, (dia.dia - finMed) / cat.etapas[3]) : 0;
        const col = verde.clone().lerp(seco, Math.min(1, estres * 1.3)).lerp(dorado, sen * 0.85);
        _campo.matCopa.color.copy(col);

        // 3) Suelo: húmedo oscuro ↔ seco claro según θ relativo
        const fHum = Math.max(0, Math.min(1, (dia.theta - pmpPct) / (ccPct - pmpPct)));
        _campo.matSuelo.color.copy(new THREE.Color(0xa3814f).lerp(new THREE.Color(0x3a2c1e), fHum));

        // 4) Animación de riego (solo en reproducción, no al arrastrar slider)
        if (dia.riegoBruto > 0 && !esSalto) _aguaOpacidad = 0.55;

        _actualizarHUD(dia, idx, datos.length);
    }

    // ════════════════════════════════════════════════════════════════
    //  LOOP DE ANIMACIÓN
    // ════════════════════════════════════════════════════════════════

    function _animar(t) {
        _rafId = requestAnimationFrame(_animar);
        if (!_renderer || !_scene) return;
        const dt = _relojPrev == null ? 0 : (t - _relojPrev) / 1000;
        _relojPrev = t;

        if (_reproduciendo && _sim) {
            _acumulador += dt * _velocidad;
            while (_acumulador >= 1) {
                _acumulador -= 1;
                if (_diaActual < _sim.ciclo - 1) {
                    _aplicarDia(_diaActual + 1, false);
                } else {
                    _setReproduciendo(false);
                    _mostrarResultados();
                    break;
                }
            }
        }

        // Decaimiento de la lámina de agua tras un riego
        if (_aguaOpacidad > 0.005) {
            _aguaOpacidad *= Math.pow(0.35, dt);
            _campo.aguaMesh.material.opacity = _aguaOpacidad;
        } else if (_campo?.aguaMesh.material.opacity !== 0) {
            _campo.aguaMesh.material.opacity = 0;
        }

        _controls.update();
        _renderer.render(_scene, _camera);
    }

    // ════════════════════════════════════════════════════════════════
    //  UI — overlay, HUD, controles, resultados
    // ════════════════════════════════════════════════════════════════

    function _fmt(n, dec = 0) {
        return Number(n).toLocaleString("es-MX", { maximumFractionDigits: dec, minimumFractionDigits: dec });
    }

    function _construirOverlay() {
        if (_overlay) return;
        _overlay = document.createElement("div");
        _overlay.id = "sim3d-overlay";
        _overlay.innerHTML = `
        <div id="sim3d-canvas-wrap"></div>

        <div class="sim3d-topbar">
            <button class="sim3d-btn-volver" onclick="SIM3D.cerrar()" aria-label="Cerrar simulador">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                    <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
                </svg>
            </button>
            <div class="sim3d-topbar-tit">
                <span id="sim3d-titulo">Simulador 3D</span>
                <span id="sim3d-subtitulo" class="sim3d-topbar-sub">—</span>
            </div>
            <div class="sim3d-esc-toggle">
                <button id="sim3d-esc-trad" onclick="SIM3D._setEscenario('tradicional')">Tradicional</button>
                <button id="sim3d-esc-milpin" class="activo" onclick="SIM3D._setEscenario('milpin')">MILPÍN</button>
            </div>
        </div>

        <div class="sim3d-hud">
            <div class="sim3d-hud-fila">
                <span id="sim3d-hud-dia" class="sim3d-chip sim3d-chip--dia">Día 1</span>
                <span id="sim3d-hud-etapa" class="sim3d-chip">Inicial</span>
                <span id="sim3d-hud-clima" class="sim3d-chip" style="display:none;">🌧</span>
                <span id="sim3d-hud-riego" class="sim3d-chip sim3d-chip--riego" style="display:none;">💧 Riego</span>
            </div>
            <div class="sim3d-hud-humedad">
                <div class="sim3d-hud-hum-lbl">
                    <span>Humedad del suelo</span><span id="sim3d-hud-hum-pct">—</span>
                </div>
                <div class="sim3d-hud-hum-track">
                    <div id="sim3d-hud-hum-fill"></div>
                    <div id="sim3d-hud-hum-umbral" title="Umbral de riego (50% ADT)"></div>
                </div>
            </div>
            <div id="sim3d-hud-detalle" class="sim3d-hud-detalle"></div>
        </div>

        <div class="sim3d-kpis" id="sim3d-kpis"></div>

        <div class="sim3d-controles">
            <button id="sim3d-btn-play" class="sim3d-btn-play" onclick="SIM3D._togglePlay()">▶</button>
            <input id="sim3d-slider" type="range" min="0" max="100" value="0"
                   oninput="SIM3D._irADia(parseInt(this.value))">
            <button id="sim3d-btn-vel" class="sim3d-btn-vel" onclick="SIM3D._cicloVelocidad()">3×</button>
            <button class="sim3d-btn-vel" onclick="SIM3D._toggleConfig()" aria-label="Configurar simulación">⚙</button>
        </div>

        <div id="sim3d-config" class="sim3d-config" style="display:none;">
            <div class="sim3d-config-tit">Parámetros de simulación</div>
            <label class="sim3d-config-lbl">Cultivo</label>
            <select id="sim3d-sel-cultivo" class="sim3d-config-input"></select>
            <label class="sim3d-config-lbl">Sistema de riego (escenario MILPÍN)</label>
            <select id="sim3d-sel-sistema" class="sim3d-config-input">
                <option value="gravedad">Gravedad (ef. 65%)</option>
                <option value="aspersion">Aspersión (ef. 80%)</option>
                <option value="microaspersion">Microaspersión (ef. 82%)</option>
                <option value="goteo">Goteo (ef. 90%)</option>
            </select>
            <label class="sim3d-config-lbl">Fecha de siembra</label>
            <input id="sim3d-fecha-siembra" type="date" class="sim3d-config-input">
            <button class="sim3d-btn-reiniciar" onclick="SIM3D._reiniciar()">Aplicar y reiniciar ciclo</button>
            <p class="sim3d-config-nota">
                El escenario Tradicional siempre simula la práctica actual DR-041:
                gravedad por calendario (${TRAD_LAMINA_BRUTA_MM} mm cada ${TRAD_INTERVALO_DIAS} días).
            </p>
        </div>

        <div id="sim3d-resultados" class="sim3d-resultados" style="display:none;"></div>

        <div id="sim3d-cargando" class="sim3d-cargando">
            <span class="bi-spinner"></span> Preparando parcela 3D…
        </div>`;
        document.body.appendChild(_overlay);
    }

    function _actualizarHUD(dia, idx, total) {
        const $ = id => document.getElementById(id);
        const fecha = dia.fecha.toLocaleDateString("es-MX", { day: "numeric", month: "short" });
        $("sim3d-hud-dia").textContent = `Día ${dia.dia}/${total} · ${fecha}`;
        $("sim3d-hud-etapa").textContent = `${dia.etapa} · Kc ${dia.kc.toFixed(2)}`;
        $("sim3d-hud-clima").style.display = dia.lluvia > 0.5 ? "" : "none";
        $("sim3d-hud-clima").textContent = `🌧 ${dia.lluvia.toFixed(0)} mm`;
        $("sim3d-hud-riego").style.display = dia.riegoBruto > 0 ? "" : "none";
        $("sim3d-hud-riego").textContent = `💧 Riego ${dia.riegoBruto.toFixed(0)} mm`;

        const { ccPct, pmpPct } = _sim.cfg;
        const f = Math.max(0, Math.min(1, (dia.theta - pmpPct) / (ccPct - pmpPct)));
        const fill = $("sim3d-hud-hum-fill");
        fill.style.width = `${(f * 100).toFixed(0)}%`;
        fill.style.background = f > 0.5 ? "var(--primary-blue)" : f > 0.25 ? "var(--amber-strong)" : "var(--red-strong)";
        $("sim3d-hud-hum-pct").textContent = `θ ${dia.theta.toFixed(1)}%`;
        $("sim3d-hud-hum-umbral").style.left = "50%";

        $("sim3d-hud-detalle").innerHTML =
            `ETc <b>${dia.etc.toFixed(1)}</b> mm · ETo ${dia.eto.toFixed(1)} mm` +
            (dia.ks < 1 ? ` · <span class="sim3d-estres">estrés Ks ${dia.ks.toFixed(2)}</span>` : "");

        const slider = $("sim3d-slider");
        if (slider && Number(slider.value) !== idx) slider.value = idx;
    }

    function _renderKPIs() {
        const el = document.getElementById("sim3d-kpis");
        if (!el || !_sim) return;
        const t = _sim.tradicional.totales, m = _sim.milpin.totales;
        const dAgua = t.volumenM3Ha > 0 ? (1 - m.volumenM3Ha / t.volumenM3Ha) * 100 : 0;
        const dRend = m.rendTonHa - t.rendTonHa;
        el.innerHTML = `
            <div class="sim3d-kpi-card">
                <span class="sim3d-kpi-lbl">Agua · m³/ha</span>
                <span class="sim3d-kpi-comp">
                    <s>${_fmt(t.volumenM3Ha)}</s> → <b>${_fmt(m.volumenM3Ha)}</b>
                </span>
                <span class="sim3d-kpi-delta ${dAgua >= 0 ? "ok" : "mal"}">
                    ${dAgua >= 0 ? "−" : "+"}${_fmt(Math.abs(dAgua), 0)}% agua</span>
            </div>
            <div class="sim3d-kpi-card">
                <span class="sim3d-kpi-lbl">Rendimiento · ton/ha</span>
                <span class="sim3d-kpi-comp">
                    <s>${_fmt(t.rendTonHa, 1)}</s> → <b>${_fmt(m.rendTonHa, 1)}</b>
                </span>
                <span class="sim3d-kpi-delta ${dRend >= 0 ? "ok" : "mal"}">
                    ${dRend >= 0 ? "+" : "−"}${_fmt(Math.abs(dRend), 1)} ton/ha</span>
            </div>`;
    }

    function _mostrarResultados() {
        const el = document.getElementById("sim3d-resultados");
        if (!el || !_sim) return;
        const t = _sim.tradicional.totales, m = _sim.milpin.totales;
        const cfg = _sim.cfg;
        const area = cfg.areaHa || 1;
        const precio = PRECIO_TON_MXN[cfg.cultivoKey] || 6000;

        const ahorroAguaM3 = (t.volumenM3Ha - m.volumenM3Ha) * area;
        const ahorroCostoMxn = (t.costoAguaMxnHa - m.costoAguaMxnHa) * area;
        const ingresoExtraMxn = (m.rendTonHa - t.rendTonHa) * precio * area;
        const beneficio = ahorroCostoMxn + ingresoExtraMxn;
        const pctAgua = t.volumenM3Ha > 0 ? ((1 - m.volumenM3Ha / t.volumenM3Ha) * 100) : 0;

        const fila = (lbl, vt, vm, unidad = "") => `
            <div class="sim3d-res-fila">
                <span class="sim3d-res-lbl">${lbl}</span>
                <span class="sim3d-res-trad">${vt}${unidad}</span>
                <span class="sim3d-res-milpin">${vm}${unidad}</span>
            </div>`;

        el.innerHTML = `
            <button class="sim3d-res-cerrar" onclick="document.getElementById('sim3d-resultados').style.display='none'">✕</button>
            <div class="sim3d-res-tit">Resultados del ciclo · ${NOMBRE_CULTIVO[cfg.cultivoKey] || cfg.cultivoKey}</div>
            <div class="sim3d-res-headline">
                MILPÍN vs práctica tradicional:
                <b>${pctAgua >= 0 ? "−" : "+"}${_fmt(Math.abs(pctAgua), 0)}% agua</b> y
                <b>${m.rendTonHa >= t.rendTonHa ? "+" : "−"}${_fmt(Math.abs(m.rendTonHa - t.rendTonHa), 1)} ton/ha</b>
            </div>
            <div class="sim3d-res-cab">
                <span></span><span>Tradicional</span><span>MILPÍN</span>
            </div>
            ${fila("Agua aplicada", _fmt(t.volumenM3Ha), _fmt(m.volumenM3Ha), " m³/ha")}
            ${fila("Eventos de riego", t.nRiegos, m.nRiegos)}
            ${fila("Días con estrés hídrico", t.diasEstres, m.diasEstres)}
            ${fila("ETa/ETc (satisfacción hídrica)", _fmt(t.relEt * 100, 0) + "%", _fmt(m.relEt * 100, 0) + "%")}
            ${fila("Rendimiento estimado", _fmt(t.rendTonHa, 1), _fmt(m.rendTonHa, 1), " ton/ha")}
            ${fila("Costo de agua (${TARIFA} MXN/m³)".replace("${TARIFA}", TARIFA_M3_MXN),
                   "$" + _fmt(t.costoAguaMxnHa), "$" + _fmt(m.costoAguaMxnHa), "/ha")}
            <div class="sim3d-res-beneficio">
                Beneficio del ciclo en <b>${_fmt(area, 1)} ha</b>:
                ahorro de <b>${_fmt(Math.max(0, ahorroAguaM3))} m³</b> de agua
                ≈ <b>$${_fmt(Math.max(0, beneficio))} MXN</b>
                <span class="sim3d-res-desglose">
                    ($${_fmt(Math.max(0, ahorroCostoMxn))} en agua + $${_fmt(Math.max(0, ingresoExtraMxn))} por rendimiento,
                    precio est. $${_fmt(precio)}/ton)
                </span>
            </div>
            <p class="sim3d-res-nota">
                Simulación FAO-56 / FAO-33 con clima sintético del Valle del Yaqui
                (determinista: ambos escenarios reciben el mismo clima). Herramienta
                de apoyo a decisiones — no sustituye el juicio agronómico.
            </p>`;
        el.style.display = "block";
    }

    // ════════════════════════════════════════════════════════════════
    //  CONTROL DE REPRODUCCIÓN / CONFIG
    // ════════════════════════════════════════════════════════════════

    function _setReproduciendo(estado) {
        _reproduciendo = estado;
        const btn = document.getElementById("sim3d-btn-play");
        if (btn) btn.textContent = estado ? "❚❚" : "▶";
    }

    function _setEscenario(esc) {
        _escenario = esc;
        document.getElementById("sim3d-esc-trad")?.classList.toggle("activo", esc === "tradicional");
        document.getElementById("sim3d-esc-milpin")?.classList.toggle("activo", esc === "milpin");
        _ultimoG = -1;                       // fuerza rebuild de matrices
        _aplicarDia(_diaActual, true);
    }

    async function _reiniciar() {
        if (!_sim) return;
        const cfg = _sim.cfg;
        const selC = document.getElementById("sim3d-sel-cultivo");
        const selS = document.getElementById("sim3d-sel-sistema");
        const inF = document.getElementById("sim3d-fecha-siembra");
        if (selC?.value) cfg.cultivoKey = selC.value;
        if (selS?.value) cfg.sistema = selS.value;
        if (inF?.value) cfg.fechaSiembra = new Date(inF.value + "T12:00:00");

        const catalogo = await _obtenerCatalogo();
        cfg.cat = catalogo[cfg.cultivoKey] || CATALOGO_FALLBACK[cfg.cultivoKey] || CATALOGO_FALLBACK.maiz;

        _sim = _correrComparativa(cfg);
        document.getElementById("sim3d-slider").max = _sim.ciclo - 1;
        document.getElementById("sim3d-resultados").style.display = "none";
        document.getElementById("sim3d-config").style.display = "none";
        document.getElementById("sim3d-subtitulo").textContent =
            `${NOMBRE_CULTIVO[cfg.cultivoKey]} · ${_fmt(cfg.areaHa, 1)} ha · ${cfg.sistema}`;

        // El cambio de cultivo cambia la forma de las plantas → reconstruir
        _crearEscena(document.getElementById("sim3d-canvas-wrap"), cfg.poligono, cfg.cultivoKey);
        _renderKPIs();
        _aplicarDia(0, true);
        _setReproduciendo(true);
        if (!_rafId) { _relojPrev = null; _rafId = requestAnimationFrame(_animar); }
    }

    // ════════════════════════════════════════════════════════════════
    //  API PÚBLICA
    // ════════════════════════════════════════════════════════════════

    async function abrir(idParcela, propsMapa) {
        _construirOverlay();
        _overlay.style.display = "block";
        document.getElementById("sim3d-cargando").style.display = "flex";
        document.getElementById("sim3d-resultados").style.display = "none";

        try {
            const [parcela, catalogo] = await Promise.all([
                _obtenerParcela(idParcela),
                _obtenerCatalogo(),
                _asegurarThree(),
            ]);

            const nombreCultivo = parcela?.cultivo_nombre || propsMapa?.cultivo || "Maíz";
            let cultivoKey = _normalizar(nombreCultivo);
            if (!CATALOGO_FALLBACK[cultivoKey] && !catalogo[cultivoKey]) cultivoKey = "maiz";

            const cfg = {
                idParcela: idParcela || "demo",
                nombreParcela: parcela?.nombre_parcela || propsMapa?.nombre || "Parcela demo",
                areaHa: Number(parcela?.area_ha || propsMapa?.area_ha) || 10,
                // CC/PMP en BD son fracción m³/m³ → balance trabaja en %
                ccPct: (Number(parcela?.capacidad_campo) || 0.34) * 100,
                pmpPct: (Number(parcela?.punto_marchitez) || 0.18) * 100,
                profM: (Number(parcela?.profundidad_raiz_cm) || 60) / 100,
                sistema: _normalizar(parcela?.sistema_riego || propsMapa?.sistema_riego) || "gravedad",
                cultivoKey,
                cat: catalogo[cultivoKey] || CATALOGO_FALLBACK[cultivoKey],
                // Default: ciclo OI (oct–abr), la temporada de riego del Yaqui
                // donde vive el KPI 8,000→6,000 m³/ha. En PV (verano) la demanda
                // ETc es tan alta que el calendario tradicional sub-riega: ahí
                // MILPÍN gana por rendimiento, no por agua.
                fechaSiembra: new Date("2026-11-15T12:00:00"),
                poligono: _poligonoDeParcela(parcela),
            };
            if (!EFICIENCIA_RIEGO[cfg.sistema]) cfg.sistema = "gravedad";

            // Poblar selectores de configuración
            const selC = document.getElementById("sim3d-sel-cultivo");
            selC.innerHTML = Object.keys(CATALOGO_FALLBACK)
                .map(k => `<option value="${k}" ${k === cultivoKey ? "selected" : ""}>${NOMBRE_CULTIVO[k]}</option>`)
                .join("");
            document.getElementById("sim3d-sel-sistema").value = cfg.sistema;
            document.getElementById("sim3d-fecha-siembra").value = "2026-11-15";

            document.getElementById("sim3d-titulo").textContent = cfg.nombreParcela;
            document.getElementById("sim3d-subtitulo").textContent =
                `${NOMBRE_CULTIVO[cultivoKey]} · ${_fmt(cfg.areaHa, 1)} ha · ${cfg.sistema}`;

            _sim = _correrComparativa(cfg);
            document.getElementById("sim3d-slider").max = _sim.ciclo - 1;

            _crearEscena(document.getElementById("sim3d-canvas-wrap"), cfg.poligono, cultivoKey);
            _escenario = "milpin";
            _setEscenario("milpin");
            _renderKPIs();
            _aplicarDia(0, true);
            _setReproduciendo(true);
            _relojPrev = null;
            _rafId = requestAnimationFrame(_animar);
        } catch (e) {
            console.error("[SIM3D] Error al abrir el simulador:", e);
            alert("No se pudo iniciar el simulador 3D: " + e.message);
            cerrar();
            return;
        } finally {
            const carga = document.getElementById("sim3d-cargando");
            if (carga) carga.style.display = "none";
        }
    }

    function cerrar() {
        _setReproduciendo(false);
        _destruirEscena();
        if (_overlay) _overlay.style.display = "none";
    }

    window.SIM3D = {
        abrir,
        cerrar,
        _togglePlay: () => _setReproduciendo(!_reproduciendo),
        _irADia: (d) => { _setReproduciendo(false); _aplicarDia(d, true); },
        _setEscenario,
        _reiniciar,
        _toggleConfig: () => {
            const c = document.getElementById("sim3d-config");
            if (c) c.style.display = c.style.display === "none" ? "block" : "none";
        },
        _cicloVelocidad: () => {
            _velocidad = _velocidad === 1 ? 3 : _velocidad === 3 ? 7 : 1;
            const btn = document.getElementById("sim3d-btn-vel");
            if (btn) btn.textContent = `${_velocidad}×`;
        },
        _mostrarResultados,
    };
})();
