# MILPÍN — Guion de Storytelling (13 diapositivas · versión 10 min)

**Agua Eficiente: Optimización del Riego en Zonas Áridas**
Equipo: Gutiérrez Escoto Omar · Rosas León Ximena · Anaya Lima Andrea Erika

> **Formato:** guion de presentación para jurado académico, mapeado 1:1 al deck de 13 slides.
> **Cada slide incluye:** *Lo que se dice* (narrativa hablada) · *Respaldo / datos* · *Si preguntan* · *Tiempo* sugerido.
> **Duración total objetivo:** ~10 min de exposición + preguntas.
>
> **Nota de honestidad metodológica (léela antes de presentar):** el sistema está en fase **prototipo funcional / pre-MVP**. Los KPIs (25 %, $3,360, 700 kWh) son **metas calculadas con metodología FAO-56 + tarifa CFE**, no promedios medidos en campo. El modelo ML se entrena sobre **datos sintéticos**, así que la "precisión 85-90 %" es sobre validación sintética, no de campo. Decir esto con claridad **suma** credibilidad ante un jurado técnico; ocultarlo es el riesgo real.

---

## Arco narrativo (el pitch en 30 segundos)

> En el Valle del Yaqui se riega como siempre se ha regado: por calendario y por intuición. Eso cuesta agua, energía y dinero que ya no sobran. MILPÍN no le quita la decisión al agricultor —se la informa. Convierte datos dispersos (satélite, clima, suelo, FAO-56) en una sola respuesta clara por parcela: *cuánta agua, cuándo y dónde*. Y lo entrega por voz, en español, para que la barrera tecnológica deje de frenar la adopción.

**Estructura del relato:** Problema (slides 1–2) → Solución + Impactos (slides 3–4) → Producto (slides 5–10) → Negocio (slides 11–12) → Cierre (slide 13).

---

## SLIDE 1 · Portada

**Lo que se dice (30 s):**
Buenas tardes. Somos MILPÍN AgTech. Nuestra propuesta cabe en una frase: *conectamos tecnología con el campo*. Tomamos cuatro fuentes — satélite, clima, suelo y cultivo — y las convertimos en decisiones de riego. Eso es lo que van a ver hoy.

**Tiempo:** 0:30

---

## SLIDE 2 · El problema — "Enfoque: Valle del Yaqui, Cajeme"

**Lo que se dice (75 s):**
El problema, con números. La agricultura consume entre **70 y 80 % del agua dulce a nivel mundial**; en México no baja del **76 %**. El Valle del Yaqui — DR-041, más de **223,000 hectáreas** — consume **8,000 m³ por hectárea por ciclo**. Y ese 8,000 no es una anomalía: es el estándar.

El estándar se mantiene porque la decisión de riego se toma por calendario, no por el estado real del cultivo. Cada metro cúbico de más se bombea desde ~80 metros, así que es también energía y dinero perdidos. Hay tres brechas: información, oportunidad y alfabetización tecnológica. MILPÍN ataca las tres.

**Respaldo / datos:** 70–80 % global / 76 % México: FAO/CONAGUA. DR-041, >223,000 ha, 8,000 m³/ha/ciclo, bombeo ~80 m, tarifa $1.68/m³ (CFE 9-CU).

**Si preguntan ("¿de dónde salen esas cifras?"):** FAO/CONAGUA para las macro-cifras; 8,000 m³/ha es el consumo de referencia del distrito.

**Tiempo:** 1:15

---

## SLIDE 3 · La solución — "Somos un DSS"

**Lo que se dice (45 s):**
Frente a eso, MILPÍN es un **DSS — sistema de apoyo a la decisión para riego agrícola**. No automatiza el campo, informa al que decide. La diferencia con otras apps es la integración: GIS + motor FAO-56 + machine learning + interfaz de voz, conectados en un solo flujo que termina en una recomendación accionable por parcela.

**Respaldo / datos:** flujo explícito en la slide: Datos dispersos → MILPÍN AgTech → Decisión por parcela → Recomendación accionable.

**Tiempo:** 0:45

---

## SLIDE 4 · Los tres impactos

> *Dilo despacio — estos son los números que el jurado va a recordar.*

**Lo que se dice (45 s):**
Tres impactos calculables. **25 % menos agua** — de 8,000 a 6,000 m³/ha/ciclo con riego guiado por FAO-56. **$3,360 MXN por hectárea por ciclo** de ahorro directo — 2,000 m³ menos a $1.68 el m³. Y **700 kWh menos** de energía de bombeo. Agua y energía van de la mano.

**Respaldo / datos:** $3,360 = 2,000 m³ × $1.68. 700 kWh = bombeo de esos 2,000 m³ desde 80 m.

**Si preguntan ("¿ya los midieron?"):** son potencial calculado, aritméticamente defendible, pendiente de validación de campo. Di esto tal cual.

**Tiempo:** 0:45

---

## SLIDE 5 · El producto — 5 módulos

> *Transición rápida — no te detengas aquí.*

**Lo que se dice (15 s):**
Así se ve en manos del agrónomo. Cinco módulos: Dashboard, Mapa GIS, Riego, Machine Learning y Anomalías. Disponible en web, iOS y Android. Vamos directo a los que importan.

**Tiempo:** 0:15

---

## SLIDE 6 · Dashboard Operativo — "Riesgo Hídrico DR-041"

**Lo que se dice (45 s):**
El dashboard responde en menos de un minuto lo que el gestor necesita saber cada día: ¿cómo va el consumo contra la meta de 6,000?, ¿qué cultivos consumen más?, ¿cuánto he ahorrado? Se alimenta de vistas KPI calculadas en base de datos — no es una pantalla estática.

**Si preguntan ("¿los números son reales?"):** datos de demostración sembrados en el DR-041 Módulo 3. Lógica de cálculo real, valores de prueba.

**Tiempo:** 0:45

---

## SLIDE 7 · Módulo Mapa GIS

**Lo que se dice (30 s):**
El mapa integra imagen satelital, NDVI, humedad, evapotranspiración y límites de parcela en tiempo real. Desde un lote en el mapa se salta directo a la recomendación de riego. Ya está corriendo sobre **PostgreSQL 15 + PostGIS 3.6** — no es promesa.

**Tiempo:** 0:30

---

## SLIDE 8 · El asistente de voz

> *Baja el ritmo aquí. Este es el momento emocional.*

**Lo que se dice (1:00):**
Todo esto no sirve si el agricultor no puede usarlo. La realidad del campo es que buena parte de los productores no se siente cómoda con menús y dashboards. Por eso fracasan las soluciones digitales agrícolas — no por mala tecnología, sino por mala adopción.

La voz cierra esa brecha. El productor pregunta en español natural y el sistema responde, recomienda y ejecuta. Sin escribir, sin manos ocupadas, en pleno campo. La voz no es un adorno — es el mecanismo que hace que la tecnología se use de verdad.

**Respaldo / datos:** Whisper (STT) → Ollama llama3.2 (NLU, devuelve JSON) → Web Speech API (TTS). En español desde el diseño. Demo en el cierre: *"¿cuándo debo regar?"* → *"en 2 días, 28 mm."*

**Tiempo:** 1:00

---

## SLIDE 9 · Módulo Riego — FAO-56

**Lo que se dice (1:00):**
Este módulo es el corazón del proyecto. FAO-56 Penman-Monteith en la palma de la mano: calcula por parcela y etapa fenológica cuánta lámina aplicar y cuándo, con detalle completo — ETc, Kc, ETo, déficit, historial y costo por riego. El balance hídrico se propaga día a día desde el último riego real — **no inventamos la humedad inicial**.

**Respaldo / datos:** implementado en `core/balance_hidrico.py`, fiel a Allen et al. 1998. Hargreaves como fallback. Verificado con pruebas unitarias.

**Si preguntan ("¿por qué FAO-56?"):** es el estándar internacional — nos hace auditables y comparables, no dependientes de una caja negra.

**Tiempo:** 1:00

---

## SLIDE 10 · Machine Learning

**Lo que se dice (1:00):**
Sobre FAO-56 montamos ML. Predice riesgo hídrico, estima si requiere riego con nivel de confianza, y detecta anomalías. Pero lo que la hace seria es la **transparencia**: explica por qué recomienda — déficit, ETo, Kc, días sin riego. No es un oráculo. Y la slide lo dice con todas sus letras: **la decisión final siempre pertenece al agricultor**. Lo potencia, no lo reemplaza.

**Respaldo / datos:** XGBoost, Isolation Forest, K-Means, Ridge (scikit-learn). Precisión 85-90 % sobre holdout **sintético**, no de campo. Entrenado con `milpin_ciclos_ml.csv`.

**Si preguntan ("¿85-90 % medido dónde?"):** validación sintética. El paso pendiente es entrenar con datos reales del distrito. Esa honestidad distingue el proyecto.

**Tiempo:** 1:00

---

## SLIDE 11 · Nuestros Planes

**Lo que se dice (45 s):**
Tres planes. **SaaS a $120 MXN/ha/ciclo** — escalable, ingreso recurrente por productor individual. **Licenciamiento Institucional a $35,000/módulo/año** — para asociaciones del DR-041. **Servicios de integración a $8,000/estación/año** — sensores y reportes de cumplimiento. La economía unitaria funciona porque el ahorro por hectárea ($3,360/ciclo) supera el precio de suscripción desde el primer ciclo.

**Si preguntan ("¿ya tienen clientes?"):** no. Hipótesis con economía unitaria clara, pendiente de pilotos.

**Tiempo:** 0:45

---

## SLIDE 12 · Inversión y Operación

> *Mención rápida — no entres en desglose.*

**Lo que se dice (20 s):**
En números concretos: **CAPEX de $450,000 MXN** para arrancar y **OPEX de $850,000 MXN al año**. Inversión moderada para un modelo SaaS escalable con potencial de expansión a otros distritos de riego.

**Tiempo:** 0:20

---

## SLIDE 13 · Cierre

**Lo que se dice (45 s):**
Lo que somos: **no vendemos sensores, no vendemos dashboards — vendemos mejores decisiones de riego.** Cada metro cúbico ahorrado es agua en el acuífero, energía no consumida y rentabilidad conservada. La meta: de 8,000 a 6,000 m³/ha/ciclo. Hoy tenemos el núcleo construido. Lo que sigue es validarlo en campo.

**Frase de cierre:**
> *"No le quitamos la decisión al agricultor: le damos los datos para tomarla mejor — y se los damos hablando. Menos agua, más rentabilidad, más futuro."*

**Tiempo:** 0:45

---

## Resumen de tiempos

| Slide | Tema | Tiempo |
|---|---|---|
| 1 | Portada | 0:30 |
| 2 | El problema (Valle del Yaqui) | 1:15 |
| 3 | Propuesta de valor (DSS) | 0:45 |
| 4 | Los tres impactos | 0:45 |
| 5 | La app — transición rápida | 0:15 |
| 6 | Dashboard operativo | 0:45 |
| 7 | Mapa GIS | 0:30 |
| 8 | Asistente de voz | 1:00 |
| 9 | Módulo Riego (FAO-56) | 1:00 |
| 10 | Machine Learning | 1:00 |
| 11 | Nuestros Planes | 0:45 |
| 12 | Inversión y Operación — mención | 0:20 |
| 13 | Cierre | 0:45 |
| | **Total** | **~9:55** |

---

## Anexo · Defensa ante preguntas del jurado

| Tema | Dato | Estado / cómo defenderlo |
|---|---|---|
| Meta hídrica | 8,000 → 6,000 m³/ha/ciclo (−25 %) | Objetivo del proyecto |
| Ahorro económico | ~$3,360 MXN/ha/ciclo | 2,000 m³ × $1.68/m³ (CFE 9-CU). Aritmética, no medición |
| Ahorro energético | ~700 kWh/ha/ciclo | Energía de bombeo a ~80 m |
| Superficie DR-041 | >223,000 ha | Cifra del distrito — cita la fuente al pie |
| Uso agrícola del agua | 70–80 % global / 76 % México | FAO / CONAGUA — cita la fuente |
| Modelo agronómico | FAO-56 Penman-Monteith + Hargreaves | Implementado y con pruebas (`balance_hidrico.py`) |
| Geoespacial | PostgreSQL 15 + PostGIS 3.6, Leaflet 1.9.4 | Implementado |
| ML | XGBoost, Isolation Forest, K-Means, Ridge | Pipeline funcional; entrenado con datos sintéticos |
| Precisión ML | 85–90 % | Sobre holdout sintético, no validación de campo |
| 1M+ modelos evaluados | Búsqueda de hiperparámetros | Combinaciones evaluadas, no modelos distintos |
| Voz | Whisper → Ollama llama3.2 → Web Speech API | Pipeline funcional, español |
| Ejemplo voz | "¿cuándo debo regar?" → "en 2 días, 28 mm" | Demo funcional en prototipo |
| Cultivos | Maíz, Frijol, Algodón, Uva, Chile | Catálogo oficial del DR-041 |
| Precios | $120/ha/ciclo · $35,000/módulo/año · $8,000/estación/año | Hipótesis; sin clientes pagantes aún |
| CAPEX | $450,000 MXN | Estimación estructurada por componente |
| OPEX | $850,000 MXN/año | Estimación; mayor componente: equipo técnico |
| Fase del proyecto | Prototipo funcional (pre-MVP) | Estado real |
| Naturaleza | DSS — apoyo a la decisión, no sustituye al agricultor | Posicionamiento central |

### Las 4 preguntas que te van a hacer
1. **"¿Esos datos y esa precisión son reales?"** → No: datos sintéticos, validación sintética. Pipeline probado, validación de campo pendiente.
2. **"¿Cómo sabes que ahorrarás 25 %?"** → Es la brecha entre consumo estándar (8,000) y requerimiento FAO-56 (~6,000). Techo teórico; el real se mide en piloto.
3. **"¿Quién es responsable si la recomendación falla?"** → El agricultor decide; somos DSS, no automatización.
4. **"¿Las cifras de CAPEX/OPEX están auditadas?"** → Estimaciones de arranque estructuradas, no auditadas. El modelo es coherente: OPEX cubierto con penetración pequeña del DR-041 a $120/ha/ciclo.
