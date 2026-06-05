# MILPÍN — Guion de Storytelling (11 diapositivas)

**Agua Eficiente: Optimización del Riego en Zonas Áridas**
Equipo: Gutiérrez Escoto Omar · Rosas León Ximena · Anaya Lima Andrea Erika

> **Formato:** guion de presentación para jurado académico, mapeado 1:1 al deck de 11 slides.
> **Cada slide incluye:** *Lo que se dice* (narrativa hablada) · *Respaldo / datos* (lo que sostiene la afirmación) · *Si preguntan* (defensa ante el jurado) · *Tiempo* sugerido.
> **Duración total objetivo:** ~11–12 min de exposición + preguntas.
>
> **Nota de honestidad metodológica (léela antes de presentar):** el sistema está en fase **prototipo funcional / pre-MVP**. Los KPIs (25 %, $3,360, 700 kWh) son **metas calculadas con metodología FAO-56 + tarifa CFE**, no promedios medidos en campo. El modelo ML se entrena sobre **datos sintéticos**, así que la "precisión 85-90 %" es sobre validación sintética, no de campo. Decir esto con claridad **suma** credibilidad ante un jurado técnico; ocultarlo es el riesgo real.

---

## Arco narrativo (el pitch en 30 segundos)

> En el Valle del Yaqui se riega como siempre se ha regado: por calendario y por intuición. Eso cuesta agua, energía y dinero que ya no sobran. MILPÍN no le quita la decisión al agricultor —se la informa. Convierte datos dispersos (satélite, clima, suelo, FAO-56) en una sola respuesta clara por parcela: *cuánta agua, cuándo y dónde*. Y lo entrega por voz, en español, para que la barrera tecnológica deje de frenar la adopción. La meta no es vender software: es bajar el consumo de 8,000 a 6,000 m³/ha por ciclo sin sacrificar rendimiento.

**Estructura del relato:** Problema (slides 1–2) → Solución y valor (slide 3) → Producto en acción (slides 4–9) → Negocio (slide 10) → Cierre (slide 11).

---

## SLIDE 1 · Portada — "Agua eficiente: optimización del riego en zonas áridas"

**Lo que se dice (30–40 s):**
Buenas tardes. Somos MILPÍN AgTech, y nuestra propuesta cabe en una frase: *conectamos tecnología con el campo*. Vamos a hablar del recurso más crítico de la agricultura en zonas áridas —el agua— y de cómo se puede usar mejor sin pedirle al agricultor que cambie quién es. Tomamos cuatro fuentes de información —satélite, clima, suelo y cultivo— y las convertimos en decisiones de riego.

**Respaldo / datos:** los cuatro íconos de la portada (Satélite, Clima, Suelo, Cultivos) son literalmente las entradas del sistema; conviene nombrarlas aquí porque anticipan toda la arquitectura.

**Tiempo:** 0:40

---

## SLIDE 2 · El problema — "Enfoque: Valle del Yaqui, Cajeme"

**Lo que se dice (90 s):**
Empecemos por el problema, con números. La agricultura consume entre el **70 y el 80 % del agua dulce disponible a nivel mundial**; en México esa cifra no baja del **76 %**. El agua es, ante todo, un problema agrícola. Y el Valle del Yaqui —Distrito de Riego 041, uno de los más productivos del país, más de **223,000 hectáreas** bajo riego— consume en promedio **8,000 m³ por hectárea por ciclo**.

Lo importante es esto: ese 8,000 **no es una anomalía, es el estándar**. Y el estándar se sostiene porque la decisión de riego se toma por calendario fijo y experiencia, no por el estado real del cultivo. El problema ya no es que falte agronomía: es que ya no podemos darnos el lujo de seguir regando así. El agua se bombea desde ~80 metros, así que cada metro cúbico de más es también energía y dinero perdidos.

**Respaldo / datos:**
- 70–80 % global y 76 % México: cifras estándar FAO / CONAGUA sobre uso agrícola del agua.
- DR-041, >223,000 ha, 8,000 m³/ha/ciclo, bombeo ~80 m, tarifa $1.68/m³ (CFE 9-CU).
- Tres brechas que mantienen el problema: **información** (no hay respuesta cuantitativa al "¿cuánta agua hoy?"), **oportunidad** (cuando el dato existe, llega tarde o disperso) y **alfabetización tecnológica** (el productor no adopta dashboards).

**Si preguntan ("¿de dónde salen esas cifras?"):** las tres macro-cifras son de fuentes públicas (FAO/CONAGUA); el 8,000 m³/ha es el consumo de referencia del distrito. Tener la fuente citada al pie te blinda.

**Tiempo:** 1:30

---

## SLIDE 3 · La solución y la propuesta de valor — "Somos un DSS"

**Lo que se dice (90 s):**
Frente a eso, MILPÍN es un **sistema de apoyo a la decisión —un DSS— para riego agrícola**. Subrayo "de apoyo": no automatiza el campo, informa al que decide.

¿Qué nos diferencia? No es un algoritmo aislado, es la **integración de cuatro capas**: GIS para el análisis espacial por parcela, un motor agronómico FAO-56 para los cálculos, machine learning para predicciones más precisas, y una interfaz de voz para que la respuesta llegue en segundos. Tomamos datos dispersos y los convertimos en una recomendación accionable por parcela.

Eso se traduce en tres impactos medibles: **25 % menos agua** con riego de precisión sin afectar producción; **~$3,360 MXN/ha/ciclo** de ahorro —ahorrar 2,000 m³ a $1.68 es dinero directo en el bolsillo del productor—; y **~700 kWh/ha/ciclo** menos de energía de bombeo. Menos agua y menos energía van juntos.

**Respaldo / datos:** $3,360 = 2,000 m³ × $1.68. 700 kWh = energía de bombear esos 2,000 m³ desde 80 m.

**Si preguntan ("¿esos KPIs ya los midieron?"):** no. Son **potencial calculado**, aritméticamente defendible, pendiente de validación de campo a escala. Esa validación es nuestro siguiente paso. — *Di esto tal cual; es más fuerte que fingir resultados.*

**Tiempo:** 1:30

---

## SLIDE 4 · El producto — recorrido por la app (5 pestañas)

**Lo que se dice (60 s):**
Así se ve en manos del agrónomo: una plataforma con cinco pestañas, pero una sola pregunta de fondo —*¿cuánta agua, cuándo y dónde?*
- **Dashboard:** el estado del ciclo en tiempo real.
- **Mapa GIS:** el campo visto desde el satélite, parcela por parcela.
- **Riego:** el cálculo FAO-56 que dice cuánto regar.
- **Inteligencia ML:** la capa predictiva que anticipa el riesgo.
- **Anomalías:** la vigilancia que avisa antes de que algo se vuelva pérdida.
En las próximas slides entro a las cuatro que importan. Accesible desde web, iOS y Android.

**Respaldo / datos:** frontend vanilla JS + Leaflet; backend FastAPI; datos servidos desde PostgreSQL + PostGIS. *No es un mockup de Figma: hay backend real detrás.*

**Tiempo:** 1:00

---

## SLIDE 5 · Dashboard Operativo — "Riesgo Hídrico DR-041"

**Lo que se dice (75 s):**
El dashboard operativo responde, en **menos de un minuto**, las preguntas que un gestor del distrito se hace todos los días: ¿cómo va el consumo contra la meta?, ¿qué cultivos usan más o menos agua?, ¿estoy en riesgo hídrico?, ¿cuánto he ahorrado contra la línea base?

Aquí se ve el consumo promedio contra la meta de 6,000, el ahorro estimado contra el baseline de 8,000, el estado agronómico FAO-56 por cada uno de los cinco cultivos, y la distribución del riego por método —goteo, aspersión, gravedad, microaspersión—. Es la vista que convierte cinco mil parcelas en una decisión de gestión.

**Respaldo / datos:** se alimenta de dos vistas KPI definidas en la base (`schema.sql`). Cultivos oficiales: Maíz, Frijol, Algodón, Uva, Chile.

**Si preguntan ("¿los números del tablero son reales?"):** son **datos sembrados de demostración** del DR-041 Módulo 3 para mostrar la funcionalidad. La lógica de cálculo es real; los valores son de prueba.

**Tiempo:** 1:15

---

## SLIDE 6 · Módulo Mapa GIS

**Lo que se dice (60 s):**
El Mapa GIS integra imagen satelital, índices de vegetación y datos de campo, parcela por parcela. La capa **NDVI** clasifica cada lote de Crítico a Excelente, así que el agrónomo ve de un vistazo dónde hay estrés o bajo desarrollo. Sobre el mapa también consulta humedad del suelo, evapotranspiración, rendimiento y los límites de cada parcela. De un punto en el mapa se salta directo a la recomendación de riego.

**Respaldo / datos:** Leaflet 1.9.4 con capas Esri World Imagery + OpenTopoMap. Las parcelas se sirven como **GeoJSON desde PostgreSQL 15 + PostGIS 3.6** (`parcelas.geom` = `GEOMETRY(Polygon, 4326)`, índice GIST). Pipeline geoespacial con geopandas + shapely. **Esta base ya está implementada —no es promesa.**

**Si preguntan ("¿el NDVI lo procesan ustedes?"):** la visualización y las capas están integradas; la ingesta satelital a escala es parte de la consolidación.

**Tiempo:** 1:00

---

## SLIDE 7 · El asistente de voz — "Tu campo, ahora te escucha"

> *Momento emocional del pitch. Bájale el ritmo y sube la mirada al jurado.*

**Lo que se dice (90 s):**
Toda esta potencia —GIS, FAO-56, machine learning— no sirve de nada si el agricultor no puede usarla. Y la realidad del campo es que **buena parte de los productores no tiene alta alfabetización tecnológica**: no se sienten cómodos con menús, formularios ni dashboards. Históricamente, **por ahí fracasan las soluciones digitales agrícolas** —no por mala tecnología, sino por mala adopción.

Por eso apostamos por la voz. El productor pregunta en español natural —*"¿Cómo está la humedad del suelo hoy?"*— y el sistema responde, recomienda y ejecuta. El ciclo es Habla → Escucha → Responde → Ejecuta → Mejora. Sin escribir, sin manos ocupadas, en pleno campo.

El argumento de fondo: la voz no es un adorno, es **el mecanismo que cierra la brecha de adopción**. Es lo que convierte un modelo agronómico sofisticado en algo que un productor de 60 años usa de verdad.

**Respaldo / datos:** pipeline **Whisper** (STT) → **Ollama `llama3.2`** (interpreta la intención y devuelve una acción en JSON) → **Web Speech API** (TTS). En español desde el diseño.

**Tiempo:** 1:30

---

## SLIDE 8 · Módulo Riego — el corazón agronómico (FAO-56)

**Lo que se dice (90 s):**
Esta es la pestaña que justifica todo el proyecto. Pone la metodología **FAO-56 Penman-Monteith** en la palma de la mano. Calcula, por parcela y etapa fenológica, cuánta lámina aplicar y cuándo, y entrega una recomendación concreta —por ejemplo, "104.6 mm, próximo riego el 11 de diciembre"— con todo el detalle del cálculo: ETc, Kc, ETo, precipitación efectiva, déficit de humedad, humedad del suelo contra capacidad de campo. Y guarda el historial: lámina, volumen, método y **costo estimado de cada riego**, para que el productor vea en pesos el efecto de cada decisión.

**Respaldo / datos:** FAO-56 **implementado a mano** en `core/balance_hidrico.py` (fiel a Allen et al., 1998), con **Hargreaves como fallback** cuando faltan variables climáticas. El balance hídrico se **propaga día a día desde el último riego real** —no se inventa la humedad inicial—. *Este es tu punto más fuerte de rigor: el motor agronómico no es una caja negra, es un modelo reconocido implementado y verificado con pruebas.*

**Si preguntan ("¿por qué FAO-56 y no un modelo propio?"):** porque es el estándar internacional de referencia para evapotranspiración; usarlo nos hace **auditables y comparables**, no dependientes de una caja negra.

**Tiempo:** 1:30

---

## SLIDE 9 · Módulo Machine Learning — "No reemplaza al agricultor, lo potencia"

> *Slide de credibilidad técnica Y de posicionamiento ético. La frase clave está impresa: úsala.*

**Lo que se dice (90 s):**
Sobre el modelo agronómico montamos una capa de machine learning. Predice el riesgo hídrico de cada parcela, estima si requiere riego con un nivel de confianza, sugiere lámina y detecta anomalías. Pero hay dos cosas que la hacen seria:

Primero, **transparencia**: el modelo no solo dice "riega ya", **explica por qué** —déficit acumulado, ETo, Kc de la etapa, días sin riego, humedad del suelo—. Es IA explicable, no un oráculo.

Y segundo, y lo dice la slide con todas sus letras: **la decisión final siempre pertenece al agricultor**. El modelo recomienda con base en datos y patrones, pero la experiencia y las condiciones del campo pueden requerir otra decisión. La IA lo **potencia**, no lo reemplaza.

**Respaldo / datos:** XGBoost para riego, Isolation Forest para anomalías, K-Means para segmentar parcelas, Ridge para pronóstico de ETo a 7 días (scikit-learn). Precisión estimada 85-90 % con margen de error; modelo reentrenable con datos nuevos.

**Si preguntan ("¿1 millón de registros reales? ¿85-90 % medido dónde?"):** *responde con la verdad* — el entrenamiento usa **datos sintéticos** (`milpin_ciclos_ml.csv`); el 85-90 % es sobre **validación sintética (holdout), no de campo**. Es prueba de concepto del pipeline, no desempeño productivo certificado. El paso pendiente es entrenar con datos reales del distrito. **Esta honestidad es la que distingue tu proyecto del que infla cifras.**

**Tiempo:** 1:30

---

## SLIDE 10 · Modelo de negocio — "Nuestros planes"

**Lo que se dice (75 s):**
¿Cómo se sostiene esto? El modelo de ingresos se ancla en el ahorro que generamos: **cobramos una fracción del valor que el productor deja de gastar.** Si ahorramos ~$3,360/ha/ciclo, capturar una parte de eso es una venta fácil de justificar —se paga con dinero que igual se iba en agua y luz. Tres planes:

1. **Suscripción SaaS por hectárea/ciclo** —el modelo principal—: tarifa por ciclo, escalable con la superficie. Ingreso recurrente y predecible.
2. **Licenciamiento institucional:** asociaciones de usuarios del DR-041 y dependencias compran la vista agregada del dashboard para gestionar agua a nivel módulo o distrito.
3. **Servicios de datos / integración:** conexión con sensores y estaciones, reportes de cumplimiento hídrico y energético.

La economía unitaria funciona porque el costo de servir una parcela más es casi cero, mientras el ahorro por hectárea es tangible y se repite cada ciclo.

**Si preguntan ("¿ya tienen clientes pagando?"):** todavía no. Es una **hipótesis de negocio con economía unitaria clara (ahorro > precio)**, pendiente de pilotos que confirmen la disposición a pagar. No es proyección validada.

**Tiempo:** 1:15

---

## SLIDE 11 · Cierre — "No vendemos sensores, vendemos mejores decisiones"

**Lo que se dice (60 s):**
Y por eso cerramos con lo que de verdad somos: **no vendemos sensores, no vendemos dashboards —vendemos mejores decisiones de riego.** Porque cada metro cúbico ahorrado es agua que permanece en el acuífero, energía que no se consume y rentabilidad que se conserva.

La meta es concreta y medible: **de 8,000 a 6,000 m³/ha por ciclo.** 25 % menos agua, ~$3,360 más en el bolsillo del productor, ~700 kWh menos de bombeo —sin sacrificar rendimiento—. Hoy tenemos un prototipo funcional con el núcleo ya construido: base PostGIS, motor FAO-56, capa de ML e interfaz de voz en español. Lo que sigue es validarlo en campo y convertir el potencial calculado en ahorro medido.

**Frase de cierre (memorízala):**
> *"No le quitamos la decisión al agricultor: le damos los datos para tomarla mejor —y se los damos hablando. Esa es la diferencia entre tecnología que se compra y tecnología que se usa. Menos agua, más rentabilidad, más futuro."*

**Tiempo:** 1:00

---

## Resumen de tiempos

| Slide | Tema | Tiempo |
|---|---|---|
| 1 | Portada / quiénes somos | 0:40 |
| 2 | El problema (Valle del Yaqui) | 1:30 |
| 3 | Propuesta de valor (DSS + 3 impactos) | 1:30 |
| 4 | La app (5 pestañas) | 1:00 |
| 5 | Dashboard operativo | 1:15 |
| 6 | Mapa GIS | 1:00 |
| 7 | Asistente de voz | 1:30 |
| 8 | Módulo Riego (FAO-56) | 1:30 |
| 9 | Machine Learning | 1:30 |
| 10 | Modelo de negocio | 1:15 |
| 11 | Cierre | 1:00 |
| | **Total** | **~13:10** |

> Si el límite es 10 min, recorta slides 4 (40 s) y 6 (40 s) y abrevia el respaldo técnico hablado; deja intactas 2, 7, 9 y 11.

---

## Anexo · Defensa ante preguntas del jurado

| Tema | Dato | Estado / cómo defenderlo |
|---|---|---|
| Meta hídrica | 8,000 → 6,000 m³/ha/ciclo (−25 %) | Objetivo del proyecto |
| Ahorro económico | ~$3,360 MXN/ha/ciclo | 2,000 m³ × $1.68/m³ (CFE 9-CU). Aritmética, no medición |
| Ahorro energético | ~700 kWh/ha/ciclo | Energía de bombeo a ~80 m |
| Superficie DR-041 | >223,000 ha | Cifra del distrito — **cita la fuente al pie** |
| Uso agrícola del agua | 70–80 % global / 76 % México | FAO / CONAGUA — **cita la fuente** |
| Modelo agronómico | FAO-56 Penman-Monteith + Hargreaves | Implementado y con pruebas (`balance_hidrico.py`) |
| Geoespacial | PostgreSQL 15 + PostGIS 3.6, Leaflet 1.9.4 | Implementado |
| ML | XGBoost, Isolation Forest, K-Means, Ridge | Pipeline funcional; **entrenado con datos sintéticos** |
| Precisión ML | 85–90 % | Sobre **holdout sintético**, no validación de campo |
| Voz | Whisper → Ollama llama3.2 → Web Speech API | Pipeline funcional, español |
| Cultivos | Maíz, Frijol, Algodón, Uva, Chile | Catálogo oficial |
| Negocio | SaaS / licenciamiento / servicios de datos | Hipótesis con economía unitaria; sin clientes pagantes aún |
| Fase del proyecto | Prototipo funcional (pre-MVP) | Estado real |
| Naturaleza | DSS — apoyo a la decisión, no sustituye al agricultor | Posicionamiento central |

### Las 3 preguntas que te van a hacer (prepáralas)
1. **"¿Esos datos y esa precisión son reales?"** → No: datos sintéticos, validación sintética. Pipeline probado, validación de campo pendiente.
2. **"¿Cómo sabes que ahorrarás 25 %?"** → Es la brecha entre consumo estándar (8,000) y requerimiento FAO-56 (~6,000). Es el techo teórico; el real se mide en piloto.
3. **"¿Quién es responsable si la recomendación falla?"** → El agricultor decide y es responsable; somos apoyo a la decisión (DSS), no automatización. Diseñado así a propósito.
