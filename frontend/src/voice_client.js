// ==========================================
// voice_client.js: Cliente de Interfaz de Voz (Web Audio API)
// MILPÍN AgTech v2.0
// ==========================================

// API_BASE is declared in ui_tabs.js
let vozSeleccionada = null;

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
            if (statusText) statusText.innerText = "MILPÍN TE ESCUCHA...";
            console.log("[MILPÍN STT] Escuchando...");
        };

        recognition.onresult = async (event) => {
            const transcripcion = event.results[0][0].transcript.trim();
            const confianza     = (event.results[0][0].confidence * 100).toFixed(0);
            console.log(`[MILPÍN STT] Transcrito: "${transcripcion}" (confianza: ${confianza}%)`);
            if (statusText) statusText.innerText = "Procesando...";
            await _enviarTextoAlBackend(transcripcion);
        };

        recognition.onerror = (event) => {
            reconociendoVoz = false;
            if (btnMilpin) btnMilpin.classList.remove('listening');
            console.error("[MILPÍN STT] Error:", event.error);
            const mensajes = {
                'no-speech'      : "No escuché nada. Intenta de nuevo.",
                'audio-capture'  : "No se detectó micrófono.",
                'not-allowed'    : "Permiso de micrófono denegado.",
                'network'        : "Sin conexión. Web Speech API requiere internet.",
            };
            const msg = mensajes[event.error] || `Error de reconocimiento: ${event.error}`;
            if (statusText) statusText.innerText = msg;
        };

        recognition.onend = () => {
            reconociendoVoz = false;
            if (btnMilpin) btnMilpin.classList.remove('listening');
        };

        if (statusText) statusText.innerText = "MILPÍN listo";
        console.log("[MILPÍN] STT inicializado con Web Speech API.");
    } else {
        console.warn("[MILPÍN] Web Speech API no disponible en este navegador.");
        if (statusText) statusText.innerText = "Navegador no compatible con reconocimiento de voz";
    }

    // Botón micrófono
    if (btnMilpin) {
        btnMilpin.addEventListener('click', alternarGrabacion);
        btnMilpin.addEventListener('touchstart', (e) => { e.preventDefault(); alternarGrabacion(); });
    }

    // Cargar voces TTS del navegador
    if (window.speechSynthesis.getVoices().length > 0) {
        poblarSelectorVoces();
    } else {
        window.speechSynthesis.onvoiceschanged = poblarSelectorVoces;
    }

    // Dropdown custom de voces — toggle
    const dropdownTrigger = document.getElementById('vozDropdownTrigger');
    const dropdownList    = document.getElementById('vozDropdownList');
    if (dropdownTrigger && dropdownList) {
        dropdownTrigger.addEventListener('click', () => {
            const open = dropdownList.classList.toggle('open');
            dropdownTrigger.classList.toggle('open', open);
        });
        document.addEventListener('click', (e) => {
            if (!document.getElementById('vozDropdown')?.contains(e.target)) {
                dropdownList.classList.remove('open');
                dropdownTrigger.classList.remove('open');
            }
        });
    }

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

function alternarGrabacion() {
    if (!recognition) {
        console.error("[MILPÍN] Web Speech API no disponible.");
        return;
    }
    // Desbloquear audio en el momento del clic para que el TTS funcione
    // cuando llegue la respuesta (Chrome requiere gesto de usuario activo)
    _desbloquearAudio();

    if (!reconociendoVoz) {
        recognition.start();
    } else {
        // Segundo clic: detener antes de que el silencio lo haga automáticamente
        recognition.stop();
    }
}

// ── Selector y configuración de voces TTS ───────────────────────────

const PRIORIDAD_VOCES = [
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

    const vocesES = window.speechSynthesis.getVoices().filter(v => v.lang.startsWith('es'));
    if (vocesES.length === 0) return;

    const ordenadas = [
        ...vocesES.filter(_esNeural),
        ...vocesES.filter(v => !_esNeural(v)),
    ];

    let porDefecto = null;
    for (const nombre of PRIORIDAD_VOCES) {
        porDefecto = ordenadas.find(v => v.name.toLowerCase().includes(nombre.toLowerCase()));
        if (porDefecto) break;
    }
    if (!porDefecto) porDefecto = ordenadas[0] || null;

    lista.innerHTML = '';
    ordenadas.forEach(voz => {
        const li = document.createElement('li');
        li.className = 'voz-dropdown-item' + (voz === porDefecto ? ' selected' : '');
        li.textContent = (_esNeural(voz) ? '★ ' : '') + voz.name + ' · ' + voz.lang;
        li.addEventListener('click', () => {
            vozSeleccionada = voz;
            if (label) label.textContent = li.textContent;
            lista.querySelectorAll('.voz-dropdown-item').forEach(i => i.classList.remove('selected'));
            li.classList.add('selected');
            lista.classList.remove('open');
            document.getElementById('vozDropdownTrigger')?.classList.remove('open');
            console.log(`[MILPÍN TTS] Voz cambiada a: ${voz.name}`);
        });
        lista.appendChild(li);
    });

    if (porDefecto) {
        vozSeleccionada = porDefecto;
        if (label) label.textContent = (_esNeural(porDefecto) ? '★ ' : '') + porDefecto.name + ' · ' + porDefecto.lang;
        console.log(`[MILPÍN TTS] Voz por defecto: ${porDefecto.name}`);
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

function hablar(texto) {
    if (!texto || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    // Delay tras cancel() — Chrome necesita un tick para liberar el sintetizador
    setTimeout(() => {
        const utterance = new SpeechSynthesisUtterance(texto);
        utterance.lang  = vozSeleccionada?.lang || 'es-MX';
        utterance.rate  = 1.05;

        // Las voces "Online" requieren red y pueden fallar silenciosamente.
        // Si la voz seleccionada es Online, intentamos primero con ella;
        // si falla, el onerror cae a cualquier voz local española disponible.
        utterance.voice = vozSeleccionada || null;

        utterance.onstart = () => console.log(`[MILPÍN TTS] Reproduciendo: "${texto.substring(0, 40)}..."`);
        utterance.onend   = () => console.log('[MILPÍN TTS] Reproducción completa.');

        utterance.onerror = (e) => {
            console.warn(`[MILPÍN TTS] Fallo con voz "${vozSeleccionada?.name}": ${e.error}. Usando voz local.`);
            const fallback = new SpeechSynthesisUtterance(texto);
            // Buscar primera voz local española (sin "Online" en el nombre)
            const vocesLocales = window.speechSynthesis.getVoices()
                .filter(v => v.lang.startsWith('es') && !v.name.includes('Online'));
            fallback.voice = vocesLocales[0] || null;
            fallback.lang  = 'es';
            fallback.rate  = 1.0;
            window.speechSynthesis.speak(fallback);
        };

        window.speechSynthesis.speak(utterance);
    }, 50);
}

// ── Selección de parcela por nombre (para intents de riego con nombre) ──────
/**
 * Busca en #select-parcela-riego una opción cuyo texto contenga `nombre`
 * (match parcial, case-insensitive). Si el select está vacío, espera a que
 * _cargarParcelasEnSelect lo pueble desde la API antes de buscar.
 *
 * @param {string} nombre - Nombre o fragmento del nombre dicho por el usuario.
 * @returns {Promise<string|null>} id_parcela (UUID) si hay match, null si no.
 */
async function _seleccionarParcelaPorNombre(nombre) {
    const sel = document.getElementById('select-parcela-riego');
    if (!sel) return null;

    // Asegurar que las opciones estén cargadas antes de buscar
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

        case "ejecutar_analisis":
            if (typeof cambiarPestana === 'function') {
                cambiarPestana(null, data.target || 'tab-mapas');
            }
            // Dar tiempo al DOM para renderizar el mapa antes de ejecutar
            setTimeout(() => {
                if (data.analisis === "logistica" && typeof ejecutarAnalisisSIG === 'function') {
                    ejecutarAnalisisSIG();
                }
            }, 600);
            break;

        case "confirmar_riego":
        case "ignorar_riego": {
            const decision = data.intent === "confirmar_riego" ? 'aceptada' : 'ignorada';
            const nombreParcelaConf = data.parameters?.nombre_parcela ?? null;
            if (typeof cambiarPestana === 'function') cambiarPestana(null, 'tab-costos');
            // IIFE async: necesitamos await para la selección de parcela y carga de rec.
            setTimeout(async () => {
                if (nombreParcelaConf) {
                    const parcelaId = await _seleccionarParcelaPorNombre(nombreParcelaConf);
                    if (!parcelaId) {
                        hablar(`No encontré una parcela con ese nombre. Selecciónala manualmente en el módulo de riego.`);
                        return;
                    }
                    // Esperar a que la recomendación cargue (popula _recActualId)
                    if (typeof cargarRecomendacion === 'function') {
                        await cargarRecomendacion(parcelaId);
                    }
                }
                if (!_recActualId) {
                    hablar("No hay recomendación activa para esta parcela. Calcula una nueva primero.");
                    return;
                }
                if (typeof confirmarRiego === 'function') confirmarRiego(decision);
            }, 600);
            break;
        }

        case "calcular_riego": {
            const nombreParcelaCalc = data.parameters?.nombre_parcela ?? null;
            if (typeof cambiarPestana === 'function') cambiarPestana(null, 'tab-costos');
            setTimeout(async () => {
                if (nombreParcelaCalc) {
                    const parcelaId = await _seleccionarParcelaPorNombre(nombreParcelaCalc);
                    if (!parcelaId) {
                        hablar(`No encontré una parcela con ese nombre. Selecciónala manualmente.`);
                        return;
                    }
                    // Cargar estado de la parcela antes de calcular
                    if (typeof cargarRecomendacion === 'function') {
                        await cargarRecomendacion(parcelaId);
                    }
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
