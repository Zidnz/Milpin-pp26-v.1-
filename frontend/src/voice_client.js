// ==========================================
// voice_client.js: Cliente de Interfaz de Voz (Web Audio API)
// MILPÍN AgTech v2.0
// ==========================================

// API_BASE is declared in ui_tabs.js
let vozSeleccionada = null;

// ── ElevenLabs TTS — llamada directa desde el browser ────────────────────────
// Llamar a ElevenLabs directamente evita el salto por Railway (browser→Railway→EL→Railway→browser)
// y elimina la dependencia del backend para TTS. Trade-off: la key queda en el JS.
// Reemplaza YOUR_API_KEY con tu clave real de elevenlabs.io → Profile → API Keys.
const _EL_KEY      = '91370e4ba0f502023e38c98ec6534d668a34ccd167305c033dd3c60b45436608';
const _EL_VOICE_ID = 'pNInz6obpgDQGcFmaJgB'; // Adam — voz masculina gratuita por defecto
const _EL_URL      = `https://api.elevenlabs.io/v1/text-to-speech/${_EL_VOICE_ID}/stream`;

// ─────────────────────────────────────────────────────────────────────────────
// PIPELINE ANTIGUO — MediaRecorder + Whisper (servidor)
// ─────────────────────────────────────────────────────────────────────────────
// Flujo original: graba audio con MediaRecorder → envía blob al backend →
// Whisper transcribe en CPU → Ollama clasifica → respuesta.
// Latencia típica: 15-30s en hardware limitado.
// Conservado como referencia y fallback manual si Web Speech API no está disponible.
//
// let mediaRecorder;
// let audioChunks = [];
//
// navigator.mediaDevices.getUserMedia({ audio: true })
//     .then(stream => {
//         mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
//
//         mediaRecorder.ondataavailable = e => {
//             if (e.data.size > 0) audioChunks.push(e.data);
//         };
//
//         mediaRecorder.onstop = async () => {
//             statusText.innerText = "Procesando...";
//             btnMilpin.classList.remove('listening');
//             const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
//             audioChunks = [];
//             if (audioBlob.size < 1000) {
//                 statusText.innerText = "Audio muy corto. Intenta de nuevo.";
//                 return;
//             }
//             const formData = new FormData();
//             formData.append("audio_file", audioBlob, "command.webm");
//             const response = await fetch(`${API_BASE}/voice-command`, {
//                 method: "POST",
//                 body: formData
//             });
//             const data = await response.json();
//             procesarRespuestaIA(data);
//         };
//     });
//
// function alternarGrabacion() {
//     if (!mediaRecorder) return;
//     if (mediaRecorder.state === "inactive") {
//         _desbloquearAudio();
//         audioChunks = [];
//         mediaRecorder.start();
//         btnMilpin.classList.add('listening');
//         statusText.innerText = "MILPÍN TE ESCUCHA... (toca para enviar)";
//     } else if (mediaRecorder.state === "recording") {
//         mediaRecorder.stop();
//     }
// }
// ─────────────────────────────────────────────────────────────────────────────


// ─────────────────────────────────────────────────────────────────────────────
// PIPELINE NUEVO — Web Speech API (STT en browser) + Groq (LLM en nube)
// ─────────────────────────────────────────────────────────────────────────────
// Flujo: el browser transcribe el audio localmente con Web Speech API →
// envía TEXTO al backend → Groq/Ollama clasifica → respuesta.
// Elimina Whisper del camino crítico. Latencia típica: 1-3s.
// Limitación: requiere internet (Chrome manda audio a Google para STT).
// ─────────────────────────────────────────────────────────────────────────────

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let reconociendoVoz = false;
let _sttReintentos = 0;
const _STT_MAX_REINTENTOS = 2;
let _sttTimeout = null;
const _isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
const _STT_TIMEOUT_MS = _isMobile ? 7000 : 12000; // móvil más corto — UX y bug Chrome Android

document.addEventListener('DOMContentLoaded', () => {
    const btnMilpin = document.getElementById('milpinBtn');
    const statusText = document.getElementById('statusLabel');

    // Inicializar Web Speech API para STT
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.lang          = 'es-MX';
        recognition.continuous    = false;  // Un comando por sesión
        recognition.interimResults = false; // Solo resultado final, no parciales

        recognition.onstart = () => {
            reconociendoVoz = true;
            if (btnMilpin) btnMilpin.classList.add('listening');
            if (statusText) statusText.innerText = _isMobile
                ? "Habla ahora... (toca para cancelar)"
                : "MILPÍN TE ESCUCHA...";
            console.log("[MILPÍN STT] Escuchando...");

            // Timeout de seguridad: Chrome Android a veces no dispara onend.
            _sttTimeout = setTimeout(() => {
                console.warn("[MILPÍN STT] Timeout — abortando.");
                // Forzar reset ANTES de abort para cubrir el caso donde onend no llega.
                _resetSTTUI(btnMilpin, statusText, "No se detectó voz. Intenta de nuevo.");
                try { recognition.abort(); } catch (_) {}
            }, _STT_TIMEOUT_MS);
        };

        recognition.onresult = async (event) => {
            clearTimeout(_sttTimeout);
            _sttReintentos = 0;
            const transcripcion = event.results[0][0].transcript.trim();
            const confianza     = (event.results[0][0].confidence * 100).toFixed(0);
            console.log(`[MILPÍN STT] Transcrito: "${transcripcion}" (confianza: ${confianza}%)`);
            if (statusText) statusText.innerText = "Procesando...";
            await _enviarTextoAlBackend(transcripcion);
        };

        recognition.onerror = (event) => {
            clearTimeout(_sttTimeout);
            console.error("[MILPÍN STT] Error:", event.error);

            if (event.error === 'network' && _sttReintentos < _STT_MAX_REINTENTOS) {
                _sttReintentos++;
                const delay = _sttReintentos * 1200;
                console.log(`[MILPÍN STT] Reintentando (${_sttReintentos}/${_STT_MAX_REINTENTOS}) en ${delay}ms...`);
                if (statusText) statusText.innerText = "Reintentando...";
                setTimeout(() => { try { recognition.start(); } catch (_) {} }, delay);
                return;
            }

            _sttReintentos = 0;
            const mensajes = {
                'no-speech'    : "No escuché nada. Intenta de nuevo.",
                'audio-capture': "No se detectó micrófono.",
                'not-allowed'  : "Permiso de micrófono denegado.",
                'network'      : "Sin conexión con el servicio de voz. Verifica internet.",
                'aborted'      : "MILPÍN listo",
            };
            const msg = mensajes[event.error] || `Error de reconocimiento: ${event.error}`;
            _resetSTTUI(btnMilpin, statusText, msg);
        };

        recognition.onend = () => {
            clearTimeout(_sttTimeout);
            // Solo resetear si aún está en modo escucha (evita sobreescribir mensaje de timeout).
            if (reconociendoVoz) _resetSTTUI(btnMilpin, statusText);
        };

        if (statusText) statusText.innerText = "MILPÍN listo";
        console.log("[MILPÍN] STT inicializado con Web Speech API.");
    } else {
        console.warn("[MILPÍN] Web Speech API no disponible en este navegador.");
        if (statusText) statusText.innerText = "Navegador no compatible con reconocimiento de voz";
    }

    // Botón micrófono
    // touchstart: desbloquea AudioContext dentro del gesto táctil (Chrome móvil lo exige).
    // click: inicia el reconocimiento (se dispara tras touchend si no se llamó preventDefault).
    if (btnMilpin) {
        // touchstart: previene el click sintético posterior (evita doble disparo).
        // NO llamar _desbloquearAudio() aquí — speechSynthesis activo bloquea STT en Android.
        btnMilpin.addEventListener('touchstart', (e) => {
            e.preventDefault();
            alternarGrabacion();
        }, { passive: false });
        // Fallback desktop
        btnMilpin.addEventListener('click', (e) => {
            if (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return;
            alternarGrabacion();
        });
    }

    // Cargar voces TTS del navegador y advertir si no hay español
    function _cargarYVerificarVoces() {
        poblarSelectorVoces();
        const voces = window.speechSynthesis.getVoices();
        const hayEspanol = voces.some(v => v.lang.startsWith('es'));
        if (!hayEspanol && voces.length > 0 && statusText) {
            // Sin voces en español → mostrar aviso con instrucción de instalación
            statusText.innerText = 'Sin voz española instalada. Ve a Ajustes → Síntesis de voz → Instalar español';
            setTimeout(() => { if (statusText) statusText.innerText = 'MILPÍN listo'; }, 6000);
            console.warn('[MILPÍN TTS] Sin voces en español. En Android: Configuración → Síntesis de voz → Google → Instalar datos de voz → Español.');
        }
    }
    if (window.speechSynthesis.getVoices().length > 0) {
        _cargarYVerificarVoces();
    } else {
        window.speechSynthesis.onvoiceschanged = _cargarYVerificarVoces;
    }

    // Dropdown de voces — inicializar
    _initVozDropdown();

    // Botón probar voz
    const btnProbarVoz = document.getElementById('btnProbarVoz');
    if (btnProbarVoz) {
        btnProbarVoz.addEventListener('click', () => {
            hablar('Hola, soy Milpín. Analizando el Valle del Yaqui.');
        });
    }

    // Persistencia de preferencias
    _cargarPreferencias();
    document.getElementById('toggleNotificaciones')
        ?.addEventListener('change', e => localStorage.setItem('milpin_notif', e.target.checked));
    document.getElementById('toggleBIAuto')
        ?.addEventListener('change', e => localStorage.setItem('milpin_bi_auto', e.target.checked));
});

// Envía el texto transcrito por Web Speech API al backend.
// Incluye parcela_id si hay una parcela activa en el módulo de riego,
// para que el backend pueda enriquecer respuestas de consulta con datos reales.
async function _enviarTextoAlBackend(texto) {
    const statusText = document.getElementById('statusLabel');
    try {
        const response = await fetch(`${API_BASE}/text-command`, {
            method : "POST",
            headers: { "Content-Type": "application/json" },
            body   : JSON.stringify({
                texto,
                parcela_id: typeof _parcelaRiegoActual !== 'undefined' ? _parcelaRiegoActual : null,
            }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        console.log("[MILPÍN] Respuesta:", data);
        procesarRespuestaIA(data);
    } catch (error) {
        console.error("[MILPÍN] Error de conexión:", error);
        if (statusText) statusText.innerText = "Error de conexión con el servidor";
        hablar("No puedo conectar con el servidor. Verifica que el backend esté corriendo.");
    }
}

// Desbloquea el contexto de audio de Chrome en el momento del clic del usuario.
// Chrome bloquea speechSynthesis si no hay un gesto activo reciente.
// La solución es reproducir un sonido silencioso en el instante del clic,
// lo que establece el contexto de audio y mantiene el permiso activo.
function _desbloquearAudio() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const buf = ctx.createBuffer(1, 1, 22050);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        src.start(0);
        ctx.close();
    } catch (_) {}

    // También hacer un speak vacío inmediato para "activar" speechSynthesis
    const silencio = new SpeechSynthesisUtterance(' ');
    silencio.volume = 0;
    window.speechSynthesis.speak(silencio);
}

function _resetSTTUI(btn, st, msg) {
    reconociendoVoz = false;
    const b = btn || document.getElementById('milpinBtn');
    const s = st  || document.getElementById('statusLabel');
    if (b) b.classList.remove('listening');
    if (s) s.innerText = msg !== undefined ? msg : 'MILPÍN listo';
}

// ─── Pipeline móvil: MediaRecorder → Groq Whisper API ────────────────────────
// Web Speech API en Android no transcribe de forma confiable (depende de Google
// STT y a menudo no devuelve resultado). MediaRecorder graba localmente y envía
// el audio a /api/voz/voice-command donde Groq Whisper transcribe en la nube.
let _mediaRecorder  = null;
let _audioChunks    = [];
let _grabandoMobile = false;
// Elemento Audio pre-desbloqueado en el gesto táctil (iOS/Android policy).
// Se crea UNA vez y se reutiliza para todas las respuestas TTS.
let _ttsAudio = new Audio();

async function _iniciarMobile() {
    const btnMilpin  = document.getElementById('milpinBtn');
    const statusText = document.getElementById('statusLabel');

    // Segunda pulsación: detener y enviar
    if (_grabandoMobile) {
        // Activar speechSynthesis en el contexto del gesto táctil.
        // Chrome Android bloquea speechSynthesis.speak() desde contextos async (la respuesta
        // del backend llega varios segundos después del gesto). Llamarlo aquí — con el gesto
        // activo — inicializa el motor TTS; la activación persiste incluso después del
        // cancel() que hablar() ejecuta internamente antes de encolar la respuesta real.
        try {
            const s = new SpeechSynthesisUtterance(' ');
            s.volume = 0;
            window.speechSynthesis.speak(s);
        } catch (_) {}

        if (_mediaRecorder && _mediaRecorder.state === 'recording') {
            _mediaRecorder.stop();
        } else {
            // _mediaRecorder no está grabando pero _grabandoMobile quedó true (edge case).
            _grabandoMobile = false;
            if (btnMilpin) btnMilpin.classList.remove('listening');
            if (statusText) statusText.innerText = 'MILPÍN listo';
        }
        return;
    }

    // Chrome Android requiere HTTPS (o localhost) para getUserMedia.
    // En acceso por IP local (http://192.168.x.x) el micrófono falla silenciosamente.
    const _isSecure = location.protocol === 'https:'
        || location.hostname === 'localhost'
        || location.hostname === '127.0.0.1';
    if (!_isSecure) {
        if (statusText) statusText.innerText = 'El micrófono requiere HTTPS. Abre la app desde la URL segura.';
        console.warn('[MILPÍN Mobile] getUserMedia bloqueado: no es HTTPS ni localhost.');
        return;
    }

    // Desbloquear audio DURANTE el gesto táctil — los browsers móviles bloquean
    // Audio.play() si no se llama en el contexto directo de un user gesture.
    // 1) AudioContext: desbloquea Web Audio API.
    // 2) _ttsAudio.play(): desbloquea el elemento HTML Audio que se reutilizará
    //    asincrónicamente para ElevenLabs (iOS exige play() en el mismo gesto).
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const buf = ctx.createBuffer(1, 1, 22050);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        src.start(0);
        await ctx.resume();
    } catch (_) {}

    // Pre-desbloquear _ttsAudio con un MP3 silencioso mínimo (44 bytes).
    // Después de este play(), iOS permitirá que el mismo elemento reproduzca
    // audio generado asincrónicamente (fetch → blob → src → play).
    try {
        _ttsAudio.muted = true;
        // 1 frame de silencio en base64 (MP3 válido, 44 bytes)
        _ttsAudio.src = 'data:audio/mpeg;base64,//uQxAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//sQxAADgnABGiAAQBCqgCRMAAgEAH///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////';
        await _ttsAudio.play();
        _ttsAudio.muted = false;
    } catch (_) {}

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm')
            ? 'audio/webm'
            : 'audio/mp4';

        _audioChunks  = [];
        _mediaRecorder = new MediaRecorder(stream, { mimeType });

        _mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) _audioChunks.push(e.data);
        };

        _mediaRecorder.onstop = async () => {
            stream.getTracks().forEach(t => t.stop()); // liberar micrófono
            _grabandoMobile = false;
            if (btnMilpin) btnMilpin.classList.remove('listening');
            if (statusText) statusText.innerText = 'Procesando...';

            const blob = new Blob(_audioChunks, { type: mimeType });
            _audioChunks = [];

            if (blob.size < 1000) {
                if (statusText) statusText.innerText = 'Audio muy corto. Intenta de nuevo.';
                return;
            }
            await _enviarAudioAlBackend(blob, mimeType, statusText);
        };

        _mediaRecorder.start();
        _grabandoMobile = true;
        if (btnMilpin) btnMilpin.classList.add('listening');
        if (statusText) statusText.innerText = 'Habla ahora... (toca para enviar)';

        // Watchdog: Chrome Android a veces no dispara onstop.
        // Si después de 60s el estado sigue grabando, forzar detención.
        setTimeout(() => {
            if (_grabandoMobile) {
                console.warn('[MILPÍN Mobile] Watchdog: forzando stop tras 60s.');
                try { _mediaRecorder.stop(); } catch (_) {}
                _grabandoMobile = false;
                if (btnMilpin) btnMilpin.classList.remove('listening');
                if (statusText) statusText.innerText = 'Grabación demasiado larga. Intenta de nuevo.';
            }
        }, 60000);

    } catch (err) {
        console.error('[MILPÍN Mobile] Error micrófono:', err);
        if (statusText) statusText.innerText =
            err.name === 'NotAllowedError'
                ? 'Permiso de micrófono denegado.'
                : 'Error al acceder al micrófono.';
    }
}

async function _enviarAudioAlBackend(blob, mimeType, statusText) {
    try {
        const ext      = mimeType.includes('mp4') ? 'mp4' : 'webm';
        const formData = new FormData();
        formData.append('audio_file', blob, `comando.${ext}`);

        const response = await fetch(`${API_BASE}/voice-command`, {
            method: 'POST',
            body  : formData,
            signal: AbortSignal.timeout(35000), // 35s — Whisper CPU en Railway puede tardar en cold start
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        console.log('[MILPÍN Mobile] Transcripción:', data.transcripcion);

        if (statusText) {
            statusText.innerText = data.transcripcion
                ? `"${data.transcripcion}"`
                : 'MILPÍN listo';
            if (data.transcripcion) {
                setTimeout(() => { if (statusText) statusText.innerText = 'MILPÍN listo'; }, 3000);
            }
        }
        procesarRespuestaIA(data);
    } catch (err) {
        console.error('[MILPÍN Mobile] Error de envío:', err);
        const msg = (err.name === 'TimeoutError' || err.name === 'AbortError')
            ? 'El servidor tardó demasiado. Intenta de nuevo en unos segundos.'
            : 'Error de conexión con el servidor.';
        if (statusText) statusText.innerText = msg;
    }
}
// ─────────────────────────────────────────────────────────────────────────────

function alternarGrabacion() {
    // Móvil: usar MediaRecorder → Groq Whisper (más confiable que Web Speech API en Android)
    if (_isMobile) {
        _iniciarMobile();
        return;
    }
    // Desktop: Web Speech API
    if (!recognition) {
        console.error("[MILPÍN] Web Speech API no disponible.");
        return;
    }
    if (!reconociendoVoz) {
        _sttReintentos = 0;
        try { recognition.start(); } catch (e) {
            console.error("[MILPÍN STT] Error al iniciar:", e);
        }
    } else {
        // Resetear UI de inmediato — no esperar onend (puede no llegar en Android).
        clearTimeout(_sttTimeout);
        _resetSTTUI(null, null, 'MILPÍN listo');
        try { recognition.abort(); } catch (_) {}
    }
}

// ── Selector y configuración de voces TTS ───────────────────────────

// ── Dropdown de selección de voz ────────────────────────────────────
// La lista se mueve a <body> con position:fixed para evitar clipping
// por cualquier contenedor padre con overflow:hidden/auto.

function _initVozDropdown() {
    const trigger = document.getElementById('vozDropdownTrigger');
    const lista   = document.getElementById('vozDropdownList');
    if (!trigger || !lista) return;

    // Reubicar la lista como hijo directo de <body>
    document.body.appendChild(lista);

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = lista.classList.contains('open');
        if (isOpen) {
            _cerrarVozDropdown();
        } else {
            _abrirVozDropdown();
        }
    });

    // Cerrar al hacer click fuera
    document.addEventListener('click', (e) => {
        if (!trigger.contains(e.target) && !lista.contains(e.target)) {
            _cerrarVozDropdown();
        }
    });

    // Cerrar al hacer scroll (reposicionar sería complejo, mejor cerrar)
    window.addEventListener('scroll', _cerrarVozDropdown, true);
}

function _abrirVozDropdown() {
    const trigger = document.getElementById('vozDropdownTrigger');
    const lista   = document.getElementById('vozDropdownList');
    if (!trigger || !lista) return;

    const rect  = trigger.getBoundingClientRect();
    const gap   = 6;
    const alturaLista = Math.min(280, lista.scrollHeight || 280);

    // Abrir arriba si no cabe abajo, abrir abajo si cabe
    const cabeAbajo = rect.bottom + gap + alturaLista < window.innerHeight;

    lista.style.position = 'fixed';
    lista.style.width    = rect.width + 'px';
    lista.style.left     = rect.left  + 'px';

    if (cabeAbajo) {
        lista.style.top    = (rect.bottom + gap) + 'px';
        lista.style.bottom = 'auto';
    } else {
        lista.style.bottom = (window.innerHeight - rect.top + gap) + 'px';
        lista.style.top    = 'auto';
    }

    lista.classList.add('open');
    trigger.classList.add('open');
}

function _cerrarVozDropdown() {
    const trigger = document.getElementById('vozDropdownTrigger');
    const lista   = document.getElementById('vozDropdownList');
    lista?.classList.remove('open');
    trigger?.classList.remove('open');
}

// Voces neurales (Online) primero — más naturales. Locales como fallback.
const PRIORIDAD_VOCES = [
    'Microsoft Sofia Online (Natural)',
    'Microsoft Sofia',
    'Microsoft Sabina Online (Natural)',
    'Microsoft Renata Online (Natural)',
    'Microsoft Elvira Online (Natural)',
    'Google español de México',
    'Google español',
    'Microsoft Sabina',
    'Microsoft Helena',
];

function _esNeural(voz) {
    return voz.name.includes('Natural') || voz.name.includes('Online');
}

function _metaVoz(voz) {
    const tipo = _esNeural(voz) ? 'Neural' : 'Estándar';
    return `${voz.lang} · ${tipo}`;
}

function poblarSelectorVoces() {
    const lista  = document.getElementById('vozDropdownList');
    const label  = document.getElementById('vozDropdownLabel');
    if (!lista) return;

    const todas  = window.speechSynthesis.getVoices();
    if (todas.length === 0) return;

    const esES = v => v.lang.startsWith('es');

    // Solo voces en español — neurales/online primero, luego estándar
    const ordenadas = [
        ...todas.filter(v => esES(v) && _esNeural(v)),
        ...todas.filter(v => esES(v) && !_esNeural(v)),
    ];

    if (ordenadas.length === 0) return;

    // Determinar voz activa: 1) guardada en localStorage, 2) vozSeleccionada actual,
    // 3) lista de prioridad, 4) primera disponible.
    const vozGuardada = localStorage.getItem('milpin_voz');
    let porDefecto = vozGuardada
        ? ordenadas.find(v => v.name === vozGuardada) ?? null
        : null;

    if (!porDefecto && vozSeleccionada) {
        porDefecto = ordenadas.find(v => v.name === vozSeleccionada.name) ?? null;
    }

    if (!porDefecto) {
        for (const nombre of PRIORIDAD_VOCES) {
            porDefecto = ordenadas.find(v => v.name.toLowerCase().includes(nombre.toLowerCase()));
            if (porDefecto) break;
        }
    }
    if (!porDefecto) porDefecto = ordenadas[0] ?? null;

    lista.innerHTML = '';

    // Encabezado único — solo español
    const sep = document.createElement('li');
    sep.className = 'voz-dropdown-sep';
    sep.textContent = 'Voces en español';
    lista.appendChild(sep);

    ordenadas.forEach(voz => {
        const neural  = _esNeural(voz);
        const prefijo = neural ? '★ ' : '';
        const meta    = neural ? `Neural · ${voz.lang}` : `Estándar · ${voz.lang}`;

        const li = document.createElement('li');
        li.className = 'voz-dropdown-item' + (voz === porDefecto ? ' selected' : '');
        li.setAttribute('role', 'option');
        li.innerHTML = `<span class="voz-item-nombre">${prefijo}${voz.name}</span>
                        <span class="voz-item-meta">${meta}</span>`;

        li.addEventListener('click', () => {
            vozSeleccionada = voz;
            localStorage.setItem('milpin_voz', voz.name);
            if (label) label.textContent = prefijo + voz.name;
            lista.querySelectorAll('.voz-dropdown-item').forEach(i => i.classList.remove('selected'));
            li.classList.add('selected');
            _cerrarVozDropdown();
            console.log(`[MILPÍN TTS] Voz cambiada a: ${voz.name}`);
        });
        lista.appendChild(li);
    });

    // Pie de nota si no hay voces neurales de español
    const hayNeuralES = ordenadas.some(_esNeural);
    if (!hayNeuralES) {
        const nota = document.createElement('li');
        nota.className = 'voz-dropdown-nota';
        nota.textContent = 'Para voces neurales abre en Microsoft Edge';
        lista.appendChild(nota);
    }

    if (porDefecto) {
        vozSeleccionada = porDefecto;
        const prefijoDef = _esNeural(porDefecto) ? '★ ' : '';
        if (label) label.textContent = prefijoDef + porDefecto.name;
        console.log(`[MILPÍN TTS] Voz activa: ${porDefecto.name}${vozGuardada ? ' (restaurada)' : ' (por defecto)'}`);
    }
}

// ── Persistencia de preferencias ────────────────────────────────────
function _cargarPreferencias() {
    const notif  = document.getElementById('toggleNotificaciones');
    const biAuto = document.getElementById('toggleBIAuto');
    if (notif)  notif.checked  = localStorage.getItem('milpin_notif')    !== 'false';
    if (biAuto) biAuto.checked = localStorage.getItem('milpin_bi_auto')  === 'true';
}

// ── Sintetizador de voz (TTS nativo del navegador) ──────────────────

// Workaround bug Chrome: speechSynthesis se pausa silenciosamente.
// Este intervalo fuerza un resume() si detecta estado paused.
setInterval(() => {
    if (window.speechSynthesis && window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
    }
}, 5000);

// Audio activo de ElevenLabs (para poder cancelarlo si llega otro mensaje)
let _elevenlabsAudio = null;

async function hablar(texto) {
    if (!texto) return;

    // Cancelar audio previo
    if (_elevenlabsAudio) {
        _elevenlabsAudio.pause();
        _elevenlabsAudio = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();

    // Intentar ElevenLabs directo desde el browser (sin pasar por Railway)
    if (_EL_KEY && _EL_KEY !== 'YOUR_API_KEY') {
        try {
            const resp = await fetch(_EL_URL, {
                method : 'POST',
                headers: {
                    'xi-api-key'  : _EL_KEY,
                    'Content-Type': 'application/json',
                    'Accept'      : 'audio/mpeg',
                },
                body  : JSON.stringify({
                    text          : texto,
                    model_id      : 'eleven_turbo_v2_5',
                    voice_settings: { stability: 0.45, similarity_boost: 0.80, style: 0.20 },
                }),
                signal: AbortSignal.timeout(18000),
            });

            if (!resp.ok) throw new Error(`ElevenLabs ${resp.status}`);

            const blob = await resp.blob();
            const url  = URL.createObjectURL(blob);

            // Reutilizar _ttsAudio (pre-desbloqueado en el gesto táctil).
            _elevenlabsAudio = _ttsAudio;
            _elevenlabsAudio.onended = () => {
                URL.revokeObjectURL(url);
                _elevenlabsAudio = null;
                console.log('[MILPÍN TTS] ElevenLabs — reproducción completa.');
            };
            _elevenlabsAudio.onerror = (e) => {
                console.warn('[MILPÍN TTS] Error audio element:', e);
                URL.revokeObjectURL(url);
                _elevenlabsAudio = null;
            };
            _elevenlabsAudio.src = url;
            _elevenlabsAudio.load();
            _elevenlabsAudio.muted = false;
            console.log(`[MILPÍN TTS] ElevenLabs → "${texto.substring(0, 40)}..."`);
            try {
                await _elevenlabsAudio.play();
            } catch (playErr) {
                console.warn('[MILPÍN TTS] play() bloqueado, usando Web Speech API:', playErr);
                URL.revokeObjectURL(url);
                _elevenlabsAudio = null;
                throw playErr;
            }
            return;

        } catch (err) {
            console.warn(`[MILPÍN TTS] ElevenLabs directo falló (${err.message}). Fallback a Web Speech API.`);
        }
    }

    // Fallback: Web Speech API
    if (!window.speechSynthesis) return;
    _desbloquearAudio();
    setTimeout(() => {
        const utterance = new SpeechSynthesisUtterance(texto);
        utterance.lang  = 'es-MX';
        utterance.rate  = 1.05;
        utterance.voice = vozSeleccionada || null;
        utterance.onstart = () => console.log(`[MILPÍN TTS] Web Speech → "${texto.substring(0, 40)}..."`);
        utterance.onerror = (e) => {
            if (e.error === 'interrupted') return;
            const vocesLocales = window.speechSynthesis.getVoices()
                .filter(v => v.lang.startsWith('es') && !v.name.includes('Online'));
            const fb = new SpeechSynthesisUtterance(texto);
            fb.voice = vocesLocales[0] || null;
            fb.lang  = 'es';
            window.speechSynthesis.speak(fb);
        };
        window.speechSynthesis.speak(utterance);
    }, 50);
}

// ── Selección de parcela por nombre (para intents de riego con nombre) ──────
// Busca en #select-parcela-riego una opción cuyo texto contenga `nombre`
// (match parcial, case-insensitive). Si el select está vacío, espera a que
// _cargarParcelasEnSelect lo pueble desde la API antes de buscar.
async function _seleccionarParcelaPorNombre(nombre) {
    const sel = document.getElementById('select-parcela-riego');
    if (!sel) return null;

    if (sel.options.length <= 1 && typeof _cargarParcelasEnSelect === 'function') {
        await _cargarParcelasEnSelect('select-parcela-riego');
    }

    const nombreLower = nombre.toLowerCase().trim();
    for (const opt of sel.options) {
        if (opt.value && opt.textContent.toLowerCase().includes(nombreLower)) {
            sel.value = opt.value;
            console.log(`[MILPÍN] Parcela seleccionada por voz: "${opt.textContent}" → ${opt.value}`);
            return opt.value;
        }
    }

    console.warn(`[MILPÍN] No se encontró parcela con nombre: "${nombre}"`);
    return null;
}

// Resuelve la parcela a usar para cualquier intent que la necesite.
// Prioridad:
//   1. Nombre mencionado por el usuario (match parcial en el select).
//   2. Parcela activa en el módulo de riego (_parcelaRiegoActual).
//   3. "Lote Alg-024" como parcela por defecto de demo.
// Siempre actualiza el select de riego. Devuelve el UUID o null si no hay ninguna.
async function _resolverParcela(nombreSugerido) {
    const sel = document.getElementById('select-parcela-riego');
    if (sel && sel.options.length <= 1 && typeof _cargarParcelasEnSelect === 'function') {
        await _cargarParcelasEnSelect('select-parcela-riego');
    }

    if (nombreSugerido) {
        const id = await _seleccionarParcelaPorNombre(nombreSugerido);
        if (id) return id;
        console.warn(`[MILPÍN] Nombre "${nombreSugerido}" no encontrado en BD, usando Lote Alg-024.`);
    }

    if (_parcelaRiegoActual) return _parcelaRiegoActual;

    // Fallback fijo: Lote Alg-024
    const id = await _seleccionarParcelaPorNombre('Alg-024');
    if (id) {
        console.log('[MILPÍN] Parcela por defecto: Lote Alg-024');
        return id;
    }

    return null;
}

// ── Orquestador de respuestas del ERP ───────────────────────────────
function procesarRespuestaIA(data) {
    const statusText = document.getElementById('statusLabel');

    // Mostrar transcripción si viene (debug)
    if (data.transcripcion) {
        console.log(`[MILPÍN] Transcrito: "${data.transcripcion}"`);
    }

    // Reproducir respuesta con voz
    if (data.message) {
        hablar(data.message);
    }

    // Actualizar status
    if (statusText) {
        statusText.innerText = data.message || "MILPÍN listo";
        // Restaurar después de 4 segundos
        setTimeout(() => { statusText.innerText = "MILPÍN listo"; }, 4000);
    }

    // Ejecutar acciones según la intención
    switch (data.intent) {
        case "navegar":
            if (data.target && typeof cambiarPestana === 'function') {
                cambiarPestana(null, data.target);
            }
            break;

        case "registrar_riego_manual": {
            const p = data.parameters || {};
            if (typeof cambiarPestana === 'function') cambiarPestana(null, 'tab-costos');
            setTimeout(async () => {
                const parcelaId = await _resolverParcela(p.nombre_parcela ?? null);
                if (!parcelaId) {
                    hablar('No encontré la parcela. Selecciónala manualmente en el módulo de riego.');
                    return;
                }
                if (typeof cargarRecomendacion === 'function') {
                    await cargarRecomendacion(parcelaId);
                }
                // Asegurarse de estar en la sub-tab de recomendaciones
                if (typeof switchRiegoTab === 'function') switchRiegoTab('recomendaciones');
                // Abrir el formulario si está cerrado
                const form = document.getElementById('riego-manual-form');
                if (form && form.style.display === 'none' && typeof toggleRiegoManual === 'function') {
                    toggleRiegoManual();
                }
                // Pre-llenar los campos conocidos
                if (p.fecha) {
                    const fechaEl = document.getElementById('manual-fecha');
                    if (fechaEl) fechaEl.value = p.fecha;
                }
                if (p.lamina_mm) {
                    const laminaEl = document.getElementById('manual-lamina');
                    if (laminaEl) laminaEl.value = p.lamina_mm;
                }
                if (p.metodo) {
                    const metodoEl = document.getElementById('manual-metodo');
                    if (metodoEl) metodoEl.value = p.metodo;
                }
                // Si llegaron todos los datos requeridos, guardar automáticamente
                if (p.lamina_mm && p.metodo && typeof registrarRiegoManual === 'function') {
                    await registrarRiegoManual();
                }
            }, 600);
            break;
        }

        case "abrir_alertas":
            if (typeof toggleAlertasPanel === 'function') {
                toggleAlertasPanel();
            }
            break;

        case "confirmar_riego":
        case "ignorar_riego": {
            const decision = data.intent === "confirmar_riego" ? 'aceptada' : 'ignorada';
            if (typeof cambiarPestana === 'function') cambiarPestana(null, 'tab-costos');
            setTimeout(async () => {
                const parcelaId = await _resolverParcela(data.parameters?.nombre_parcela ?? null);
                if (!parcelaId) {
                    hablar('No encontré la parcela. Selecciónala manualmente en el módulo de riego.');
                    return;
                }
                if (typeof cargarRecomendacion === 'function') {
                    await cargarRecomendacion(parcelaId);
                }
                if (!_recActualId) {
                    hablar('No hay recomendación activa para esta parcela. Calcula una nueva primero.');
                    return;
                }
                if (typeof confirmarRiego === 'function') confirmarRiego(decision);
            }, 600);
            break;
        }

        case "calcular_riego": {
            if (typeof cambiarPestana === 'function') cambiarPestana(null, 'tab-costos');
            setTimeout(async () => {
                const parcelaId = await _resolverParcela(data.parameters?.nombre_parcela ?? null);
                if (!parcelaId) {
                    hablar('No encontré la parcela. Selecciónala manualmente en el módulo de riego.');
                    return;
                }
                if (typeof cargarRecomendacion === 'function') {
                    await cargarRecomendacion(parcelaId);
                }
                const dias = data.parameters?.dias_siembra;
                if (dias) {
                    const inputDias = document.getElementById('input-dias-siembra');
                    if (inputDias) inputDias.value = dias;
                }
                if (typeof calcularNuevaRecomendacion === 'function') {
                    calcularNuevaRecomendacion();
                }
            }, 600);
            break;
        }

        case "consultar":
            // El mensaje ya viene enriquecido con datos reales desde el backend.
            // No se necesita acción adicional en el frontend: la respuesta
            // hablada (data.message) se reproduce arriba via hablar().
            break;

        case "error":
            console.error("[MILPÍN] Error del backend:", data.message);
            if (statusText) {
                statusText.innerText = data.message || "Error al procesar el audio.";
                statusText.style.color = "#c0392b";
                setTimeout(() => {
                    statusText.innerText = "MILPÍN listo";
                    statusText.style.color = "";
                }, 5000);
            }
            break;

        case "saludo":
        case "desconocido":
        default:
            // Solo reproduce el mensaje de voz (ya manejado arriba)
            break;
    }
}
