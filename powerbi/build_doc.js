// MILPIN Dashboard Proposal — Word Document Generator
"use strict";
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  ExternalHyperlink,
} = require("docx");
const fs = require("fs");

// ── palette ──────────────────────────────────────────────────────────────────
const BLUE   = "1A56A0";
const LBLUE  = "D6E4F7";
const TEAL   = "0D7377";
const LTEAL  = "D0EEEE";
const GRAY   = "F5F6FA";
const DGRAY  = "4A4A4A";
const GREEN  = "1A7A4A";
const LGREEN = "D6F0E0";
const RED    = "B71C1C";
const LRED   = "FDECEA";
const ORANGE = "E65100";
const WHITE  = "FFFFFF";
const BLACK  = "111111";
const BORDER_COLOR = "BBCFE8";

// ── sizes (DXA) ──────────────────────────────────────────────────────────────
const PW = 11906; // A4 width
const PH = 16838; // A4 height
const ML = 1134;  // margin left  (~2 cm)
const MR = 1134;
const MT = 1134;
const MB = 1134;
const CW = PW - ML - MR; // content width = 9638

// ── helpers ──────────────────────────────────────────────────────────────────
function sp(n) { return { size: n }; }
function clr(hex) { return { color: hex }; }

function cell(children, { w, bg, bold, color, align, vAlign, colspan, borders, padding } = {}) {
  const brd = borders || {
    top:    { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR },
    bottom: { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR },
    left:   { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR },
    right:  { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR },
  };
  return new TableCell({
    width: w ? { size: w, type: WidthType.DXA } : undefined,
    columnSpan: colspan,
    verticalAlign: vAlign || VerticalAlign.CENTER,
    shading: bg ? { fill: bg, type: ShadingType.CLEAR } : undefined,
    margins: padding || { top: 80, bottom: 80, left: 120, right: 120 },
    borders: brd,
    children: Array.isArray(children) ? children : [
      new Paragraph({
        alignment: align || AlignmentType.LEFT,
        children: [new TextRun({
          text: children,
          bold: bold || false,
          color: color || BLACK,
          size: 20,
          font: "Arial",
        })],
      }),
    ],
  });
}

function hcell(text, w) {
  return cell(text, { w, bg: BLUE, bold: true, color: WHITE, align: AlignmentType.CENTER });
}

function row(...cells) { return new TableRow({ children: cells }); }

function para(text, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.before ?? 80, after: opts.after ?? 80 },
    indent: opts.indent ? { left: opts.indent } : undefined,
    numbering: opts.numbering,
    children: [new TextRun({
      text,
      bold:      opts.bold   || false,
      italics:   opts.italic || false,
      color:     opts.color  || BLACK,
      size:      opts.size   || 20,
      font:      "Arial",
      highlight: opts.highlight || undefined,
    })],
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 320, after: 160 },
    children: [new TextRun({ text, bold: true, size: 36, font: "Arial", color: BLUE })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: BLUE, space: 4 } },
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text, bold: true, size: 28, font: "Arial", color: TEAL })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 80 },
    children: [new TextRun({ text, bold: true, size: 24, font: "Arial", color: DGRAY })],
  });
}

function note(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    indent: { left: 360 },
    border: { left: { style: BorderStyle.THICK, size: 12, color: TEAL, space: 8 } },
    children: [new TextRun({ text, size: 18, italic: true, color: DGRAY, font: "Arial" })],
  });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, size: 20, font: "Arial", color: BLACK })],
  });
}

function numbered(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "steps", level },
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, size: 20, font: "Arial", color: BLACK })],
  });
}

function subStep(text) {
  return new Paragraph({
    numbering: { reference: "substeps", level: 0 },
    spacing: { before: 40, after: 40 },
    indent: { left: 720 },
    children: [new TextRun({ text, size: 19, font: "Arial", color: DGRAY })],
  });
}

function divider() {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 1 } },
    children: [new TextRun("")],
  });
}

function pb() { return new Paragraph({ children: [new PageBreak()] }); }

// ── COVER PAGE ────────────────────────────────────────────────────────────────
function coverPage() {
  return [
    new Paragraph({ spacing: { before: 1800, after: 0 }, children: [] }),

    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
      children: [new TextRun({ text: "MILPIN", bold: true, size: 96, font: "Arial", color: BLUE })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 200 },
      children: [new TextRun({ text: "Monitor de Optimizacion Hidrica — DR-041 Modulo 3", size: 32, font: "Arial", color: TEAL })],
    }),

    // Accent line
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 60, after: 400 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 1 } },
      children: [new TextRun("")],
    }),

    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 120 },
      children: [new TextRun({ text: "Propuesta de Dashboard Power BI", bold: true, size: 40, font: "Arial", color: BLACK })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
      children: [new TextRun({ text: "Diseno, arquitectura y paso a paso de implementacion", size: 26, font: "Arial", color: DGRAY })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 600 },
      children: [new TextRun({ text: "Valle del Yaqui, Sonora | Ciclo PV-2025 — PV-2026", size: 22, font: "Arial", color: DGRAY })],
    }),

    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 40 },
      children: [new TextRun({ text: "Version 1.0   |   2026", size: 20, font: "Arial", color: DGRAY })],
    }),

    pb(),
  ];
}

// ── SECTION 1: INTRODUCCION ────────────────────────────────────────────────────
function secIntro() {
  return [
    h1("1. Introduccion y Contexto"),

    para("MILPIN es un sistema de apoyo a decisiones (DSS) para optimizacion de riego en el Distrito de Riego DR-041, enfocado en el Modulo 3 del Valle del Yaqui, Sonora. Este documento define la arquitectura de un dashboard operacional en Power BI que permite a jefes de modulo y tecnicos agronomos monitorear el consumo hidrico, detectar parcelas en sobre-riego, evaluar el cumplimiento FAO-56 y dar seguimiento a las recomendaciones del algoritmo MILPIN."),

    para(""),
    h3("KPI central del proyecto"),
    note("Reducir consumo de riego de 8,000 m3/ha/ciclo en 2025 a 6,000 m3/ha/ciclo en 2026 (ahorro objetivo: 25%). Tarifa base: $1.68 MXN/m3 (CFE 9-CU, bombeo 80 m)."),

    para(""),
    h3("Audiencia del dashboard"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [2400, 3000, 4238],
      rows: [
        row(hcell("Perfil", 2400), hcell("Frecuencia de uso", 3000), hcell("Necesidad principal", 4238)),
        row(
          cell("Jefe de modulo", { w: 2400 }),
          cell("Diaria", { w: 3000 }),
          cell("Ver alertas activas y recomendaciones pendientes", { w: 4238 }),
        ),
        row(
          cell("Tecnico agronomo", { w: 2400, bg: GRAY }),
          cell("Diaria / semanal", { w: 3000, bg: GRAY }),
          cell("Verificar cumplimiento FAO-56 por cultivo y etapa", { w: 4238, bg: GRAY }),
        ),
        row(
          cell("Director de distrito", { w: 2400 }),
          cell("Semanal", { w: 3000 }),
          cell("KPIs de ahorro hidrico y economico vs. 2025", { w: 4238 }),
        ),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 2: TIPO DE DASHBOARD ─────────────────────────────────────────────
function secTipo() {
  return [
    h1("2. Tipo de Dashboard"),

    para("El dashboard propuesto es un hibrido operacional-ejecutivo. No es solo un cuadro de mando para directivos ni solo un monitor de campo para operadores: sirve a ambos en una sola pagina principal mas una pagina secundaria de analisis comparativo."),

    para(""),
    h3("Caracteristicas del tipo operacional"),
    bullet("Responde preguntas del momento: que esta pasando ahora, que parcela tiene problema, que accion debo tomar hoy."),
    bullet("Datos actualizados frecuentemente (diario o semanal)."),
    bullet("Prioriza alertas y estados anomalos sobre promedios generales."),
    bullet("La tabla de accion al final del layout dirige al operador al siguiente paso concreto."),

    para(""),
    h3("Capa ejecutiva incluida"),
    bullet("KPIs de ahorro (m3, MXN, kWh) visibles al primer golpe de vista."),
    bullet("Segunda pagina dedicada a comparativo 2025 vs. 2026 para reportes de direccion."),
    bullet("Todos los valores estan contextualizados contra el objetivo FAO-56, no solo presentados como numeros absolutos."),

    para(""),
    divider(),
  ];
}

// ── SECTION 3: PREGUNTAS QUE RESPONDE ────────────────────────────────────────
function secPreguntas() {
  return [
    h1("3. Las 6 Preguntas que Debe Responder"),

    note("Regla de diseno: cada visual incluido debe responder al menos una de estas preguntas. Si no responde ninguna, no entra al dashboard."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [640, 4800, 2400, 1798],
      rows: [
        row(hcell("#", 640), hcell("Pregunta", 4800), hcell("Frecuencia", 2400), hcell("Prioridad", 1798)),
        row(cell("1", { w: 640 }), cell("¿Estamos consumiendo dentro del objetivo FAO-56?", { w: 4800 }), cell("Diaria", { w: 2400 }), cell("CRITICA", { w: 1798, color: RED, bold: true })),
        row(cell("2", { w: 640, bg: GRAY }), cell("¿Que parcelas estan en sobre-riego o con alerta activa?", { w: 4800, bg: GRAY }), cell("Diaria", { w: 2400, bg: GRAY }), cell("CRITICA", { w: 1798, bg: GRAY, color: RED, bold: true })),
        row(cell("3", { w: 640 }), cell("¿Cuanto agua y dinero hemos ahorrado vs. 2025?", { w: 4800 }), cell("Semanal", { w: 2400 }), cell("ALTA", { w: 1798, color: ORANGE, bold: true })),
        row(cell("4", { w: 640, bg: GRAY }), cell("¿Que cultivo tiene peor cumplimiento FAO-56?", { w: 4800, bg: GRAY }), cell("Semanal", { w: 2400, bg: GRAY }), cell("ALTA", { w: 1798, bg: GRAY, color: ORANGE, bold: true })),
        row(cell("5", { w: 640 }), cell("¿Como avanza la migracion de sistemas de riego?", { w: 4800 }), cell("Mensual", { w: 2400 }), cell("MEDIA", { w: 1798, color: TEAL, bold: true })),
        row(cell("6", { w: 640, bg: GRAY }), cell("¿Que recomendaciones de MILPIN no se han atendido?", { w: 4800, bg: GRAY }), cell("Diaria", { w: 2400, bg: GRAY }), cell("CRITICA", { w: 1798, bg: GRAY, color: RED, bold: true })),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 4: FORMATO Z ──────────────────────────────────────────────────────
function secFormato() {
  return [
    h1("4. Formato Z — Por que y Como"),

    h3("Por que patron Z y no F"),
    para("El patron F es adecuado para interfaces con texto denso y listas largas (reportes, feeds). El patron Z es para dashboards de decision donde hay pocos elementos clave y el usuario llega con una pregunta urgente. En un contexto operacional agricola, el jefe de modulo revisa el dashboard en 2 minutos antes de dar la orden de riego: el patron Z replica exactamente ese recorrido mental."),

    para(""),
    h3("El recorrido visual en Z"),

    // ASCII diagram as table
    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [CW],
      rows: [
        new TableRow({ children: [
          new TableCell({
            width: { size: CW, type: WidthType.DXA },
            shading: { fill: "1A1D27", type: ShadingType.CLEAR },
            borders: { top: { style: BorderStyle.SINGLE, size: 4, color: BLUE },
                       bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE },
                       left: { style: BorderStyle.SINGLE, size: 4, color: BLUE },
                       right: { style: BorderStyle.SINGLE, size: 4, color: BLUE } },
            margins: { top: 160, bottom: 160, left: 240, right: 240 },
            children: [
              new Paragraph({ children: [new TextRun({ text: "[A] KPIs Criticos ──────────────────────────────────── [B] Filtros", font: "Courier New", size: 18, color: "4FC3F7" })] }),
              new Paragraph({ children: [new TextRun({ text: "      ↘  diagonal de atencion", font: "Courier New", size: 18, color: "9E9E9E" })] }),
              new Paragraph({ children: [new TextRun({ text: "[C] Grafica Principal (grande)  ──────  [D] Visuals de soporte", font: "Courier New", size: 18, color: "66BB6A" })] }),
              new Paragraph({ children: [new TextRun({ text: "─────────────────────────────────────────────────────────────", font: "Courier New", size: 18, color: "555555" })] }),
              new Paragraph({ children: [new TextRun({ text: "[E] Tabla Operacional / Accion pendiente (ancho completo)", font: "Courier New", size: 18, color: "FFA726" })] }),
            ],
          }),
        ]}),
      ],
    }),

    para(""),
    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [640, 2000, 6998],
      rows: [
        row(hcell("Zona", 640), hcell("Nombre", 2000), hcell("Que contiene y por que ahi", 6998)),
        row(cell("A", { w: 640 }), cell("KPI Strip", { w: 2000, bold: true }), cell("5 tarjetas horizontales. Primera fijacion visual. Responde preguntas 1 y 3 en < 3 segundos.", { w: 6998 })),
        row(cell("B", { w: 640, bg: GRAY }), cell("Filtros", { w: 2000, bg: GRAY, bold: true }), cell("Segmentadores de ciclo, cultivo y modulo. Controlan todos los visuals de la pagina.", { w: 6998, bg: GRAY })),
        row(cell("C", { w: 640 }), cell("Visual principal", { w: 2000, bold: true }), cell("Linea dual con area sombreada: consumo real vs. objetivo FAO-56. ~40% del ancho total.", { w: 6998 })),
        row(cell("D", { w: 640, bg: GRAY }), cell("Visuals soporte", { w: 2000, bg: GRAY, bold: true }), cell("D1: Barras de sobre-riego por cultivo. D2: Donut de sistemas de riego.", { w: 6998, bg: GRAY })),
        row(cell("E", { w: 640 }), cell("Tabla operacional", { w: 2000, bold: true }), cell("Parcelas con alerta o recomendacion pendiente. Zona de accion: el operador sabe que hacer al llegar aqui.", { w: 6998 })),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 5: KPI STRIP ─────────────────────────────────────────────────────
function secKpis() {
  return [
    h1("5. Zona A — KPI Strip (Fila Superior)"),

    para("Cinco tarjetas horizontales en la parte superior del canvas. Son el primer punto de contacto visual. Cada tarjeta tiene: numero grande (metrica principal), delta vs. objetivo o vs. ano anterior, y color de semaforo."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [640, 3200, 2000, 2000, 1798],
      rows: [
        row(hcell("#", 640), hcell("Metrica", 3200), hcell("Comparador", 2000), hcell("Color alerta", 2000), hcell("Columna CSV", 1798)),
        row(
          cell("1", { w: 640 }),
          cell("Consumo promedio m3/ha/ciclo actual", { w: 3200 }),
          cell("vs. objetivo FAO-56", { w: 2000 }),
          cell("Rojo si > objetivo", { w: 2000, color: RED }),
          cell("volumen_m3ha", { w: 1798 }),
        ),
        row(
          cell("2", { w: 640, bg: GRAY }),
          cell("Ahorro acumulado m3 (PV-2026 vs PV-2025)", { w: 3200, bg: GRAY }),
          cell("Delta %", { w: 2000, bg: GRAY }),
          cell("Verde siempre", { w: 2000, bg: GRAY, color: GREEN }),
          cell("ahorro_total_m3", { w: 1798, bg: GRAY }),
        ),
        row(
          cell("3", { w: 640 }),
          cell("Ahorro economico MXN ($1.68/m3)", { w: 3200 }),
          cell("Absoluto MXN", { w: 2000 }),
          cell("Verde siempre", { w: 2000, color: GREEN }),
          cell("ahorro_economico_mxn", { w: 1798 }),
        ),
        row(
          cell("4", { w: 640, bg: GRAY }),
          cell("Cumplimiento FAO-56 %", { w: 3200, bg: GRAY }),
          cell("Gauge o numero grande", { w: 2000, bg: GRAY }),
          cell("Rojo <50%, Amarillo 50-74%, Verde >=75%", { w: 2000, bg: GRAY }),
          cell("cumplimiento_fao56_pct", { w: 1798, bg: GRAY }),
        ),
        row(
          cell("5", { w: 640 }),
          cell("Alertas activas en parcelas", { w: 3200 }),
          cell("Numero con icono", { w: 2000 }),
          cell("Rojo si > 0, Verde si = 0", { w: 2000, color: RED }),
          cell("alertas_criticas", { w: 1798 }),
        ),
      ],
    }),

    para(""),
    note("Regla de diseno: fondo oscuro neutro (#1A1D27), numero grande en blanco, subtitulo gris, indicador delta en color (verde = mejor, rojo = peor). Sin bordes decorativos ni sombras excesivas. Maximo 5 tarjetas."),
    para(""),
    divider(),
  ];
}

// ── SECTION 6: VISUALS ───────────────────────────────────────────────────────
function secVisuals() {
  return [
    h1("6. Visuals del Dashboard"),

    h2("Zona C — Visual Principal: Linea Dual FAO-56"),

    para("La grafica mas importante del dashboard. Responde preguntas 1 y 4 simultaneamente."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [2400, 7238],
      rows: [
        row(hcell("Elemento", 2400), hcell("Configuracion", 7238)),
        row(cell("Tipo", { w: 2400 }), cell("Grafico de lineas con area sombreada (Line Chart)", { w: 7238 })),
        row(cell("Eje X", { w: 2400, bg: GRAY }), cell("fecha_riego — formato MM/AAAA o semana agricola", { w: 7238, bg: GRAY })),
        row(cell("Linea 1 (azul)", { w: 2400 }), cell("volumen_m3ha real aplicado — datos de historial_riego.csv", { w: 7238 })),
        row(cell("Linea 2 (naranja punteada)", { w: 2400, bg: GRAY }), cell("Objetivo FAO-56 calculado: ETc x intervalo x 10 / eficiencia — columna etc_mm", { w: 7238, bg: GRAY })),
        row(cell("Area sombreada", { w: 2400 }), cell("Zona entre ambas lineas cuando volumen_real > objetivo (sobre-riego en rojo transparente)", { w: 7238 })),
        row(cell("Tooltip", { w: 2400, bg: GRAY }), cell("Parcela, cultivo, etapa_fenologica, kc, eto_mm, sobre_riego_pct, alerta", { w: 7238, bg: GRAY })),
        row(cell("Tamano", { w: 2400 }), cell("40% del ancho del canvas, 45% de la altura total", { w: 7238 })),
        row(cell("Filtros aplicados", { w: 2400, bg: GRAY }), cell("Responde a todos los segmentadores de Zona B (ciclo, cultivo, modulo)", { w: 7238, bg: GRAY })),
      ],
    }),

    para(""),
    h2("Zona D1 — Barras: Sobre-riego por Cultivo"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [2400, 7238],
      rows: [
        row(hcell("Elemento", 2400), hcell("Configuracion", 7238)),
        row(cell("Tipo", { w: 2400 }), cell("Grafico de barras apiladas (Stacked Bar Chart)", { w: 7238 })),
        row(cell("Eje X", { w: 2400, bg: GRAY }), cell("Cultivo: Maiz, Frijol, Algodon, Uva, Chile", { w: 7238, bg: GRAY })),
        row(cell("Segmento verde", { w: 2400 }), cell("% de eventos dentro del rango FAO-56 (cumplimiento_fao56 = TRUE)", { w: 7238 })),
        row(cell("Segmento rojo", { w: 2400, bg: GRAY }), cell("% de eventos con sobre-riego > umbral (sobre_riego_pct > 10%)", { w: 7238, bg: GRAY })),
        row(cell("Linea referencia", { w: 2400 }), cell("Linea horizontal en 10% — umbral aceptable MILPIN", { w: 7238 })),
        row(cell("Pregunta que responde", { w: 2400, bg: GRAY }), cell("Pregunta 4: ¿Que cultivo tiene peor cumplimiento FAO-56?", { w: 7238, bg: GRAY })),
      ],
    }),

    para(""),
    h2("Zona D2 — Donut: Distribucion de Sistemas de Riego"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [2400, 7238],
      rows: [
        row(hcell("Elemento", 2400), hcell("Configuracion", 7238)),
        row(cell("Tipo", { w: 2400 }), cell("Grafico de dona (Donut Chart)", { w: 7238 })),
        row(cell("Segmentos", { w: 2400, bg: GRAY }), cell("Gravedad / Aspersion / Microaspersion / Goteo — columna metodo_riego", { w: 7238, bg: GRAY })),
        row(cell("Centro", { w: 2400 }), cell("Eficiencia promedio ponderada % — columna eficiencia_riego", { w: 7238 })),
        row(cell("Interaccion", { w: 2400, bg: GRAY }), cell("Al cambiar ciclo en Zona B, la dona muestra la migracion de sistemas automaticamente", { w: 7238, bg: GRAY })),
        row(cell("Pregunta que responde", { w: 2400 }), cell("Pregunta 5: ¿Como avanza la migracion de sistemas de riego?", { w: 7238 })),
      ],
    }),

    para(""),
    h2("Zona B — Panel de Filtros (esquina superior derecha)"),
    bullet("Segmentador de ciclo: PV-2025 / OI-2025 / PV-2026 — columna id_ciclo"),
    bullet("Segmentador de cultivo: multiselect — columna cultivo"),
    bullet("Segmentador de modulo DR-041: Modulo 3A / 3B / 3C / 3D — columna modulo_dr041"),
    bullet("Badge estado MILPIN: activo/inactivo segun ciclo seleccionado — columna milpin_activo"),
    para(""),

    h2("Zona E — Tabla Operacional (fila inferior, ancho completo)"),

    para("Esta es la zona de accion. El operador llego aqui para saber que hacer hoy. Filtra solo parcelas con alerta o recomendacion pendiente sin atender."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [1200, 1400, 1000, 1200, 1100, 1200, 1100, 1438],
      rows: [
        row(
          hcell("Parcela", 1200), hcell("Modulo", 1400), hcell("Cultivo", 1000),
          hcell("Etapa fenol.", 1200), hcell("Ultimo riego", 1100),
          hcell("Deficit mm", 1200), hcell("Sobre-riego %", 1100), hcell("Estado rec.", 1438),
        ),
        row(
          cell("historial_riego: id_parcela", { w: 1200 }),
          cell("parcelas: modulo_dr041", { w: 1400 }),
          cell("historial_riego: cultivo", { w: 1000 }),
          cell("historial_riego: etapa_fenologica", { w: 1200 }),
          cell("MAX(fecha_riego)", { w: 1100 }),
          cell("SUM(deficit_hidrico_mm)", { w: 1200 }),
          cell("AVG(sobre_riego_pct)", { w: 1100 }),
          cell("recomendaciones: aceptada", { w: 1438 }),
        ),
      ],
    }),

    para(""),
    note("Formato de filas: alerta activa = fondo rojo suave. Recomendacion sin atender (sin_respuesta) = fondo amarillo. Sin fondo = operacion normal. Ordenado por nivel_urgencia descendente, luego deficit acumulado. Maximo 10 filas visibles, scroll interno."),
    para(""),
    divider(),
  ];
}

// ── SECTION 7: PALETA ────────────────────────────────────────────────────────
function secPaleta() {
  return [
    h1("7. Paleta de Colores y Tema"),

    para("Tema oscuro. Los operadores de campo revisan este dashboard en tablets con brillo variable o en oficinas de modulo con luz directa. El fondo oscuro reduce la fatiga visual en sesiones largas."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [1800, 1600, 2000, 4238],
      rows: [
        row(hcell("Uso", 1800), hcell("Hex", 1600), hcell("Nombre", 2000), hcell("Justificacion", 4238)),
        row(cell("Fondo principal", { w: 1800 }), cell("#1A1D27", { w: 1600, bg: "1A1D27", color: WHITE }), cell("Azul noche", { w: 2000 }), cell("Bajo en fatiga visual para sesiones largas", { w: 4238 })),
        row(cell("Fondo tarjeta", { w: 1800, bg: GRAY }), cell("#242736", { w: 1600, bg: "242736", color: WHITE }), cell("Gris oscuro", { w: 2000, bg: GRAY }), cell("Separacion sutil sin bordes agresivos", { w: 4238, bg: GRAY })),
        row(cell("Acento primario", { w: 1800 }), cell("#4FC3F7", { w: 1600, bg: "4FC3F7" }), cell("Azul agua", { w: 2000 }), cell("Agua, coherencia tematica agricola", { w: 4238 })),
        row(cell("Sobre-riego / alerta", { w: 1800, bg: GRAY }), cell("#EF5350", { w: 1600, bg: "EF5350", color: WHITE }), cell("Rojo alerta", { w: 2000, bg: GRAY }), cell("Universal para problema critico", { w: 4238, bg: GRAY })),
        row(cell("Dentro de objetivo", { w: 1800 }), cell("#66BB6A", { w: 1600, bg: "66BB6A" }), cell("Verde exito", { w: 2000 }), cell("Universal para resultado positivo", { w: 4238 })),
        row(cell("Objetivo FAO-56", { w: 1800, bg: GRAY }), cell("#FFA726", { w: 1600, bg: "FFA726" }), cell("Naranja referencia", { w: 2000, bg: GRAY }), cell("Distinguible del azul y del verde en daltonismo", { w: 4238, bg: GRAY })),
        row(cell("Texto principal", { w: 1800 }), cell("#FFFFFF", { w: 1600, bg: "1A1D27", color: WHITE }), cell("Blanco", { w: 2000 }), cell("Maximo contraste sobre fondo oscuro", { w: 4238 })),
        row(cell("Texto secundario", { w: 1800, bg: GRAY }), cell("#9E9E9E", { w: 1600, bg: "9E9E9E" }), cell("Gris medio", { w: 2000, bg: GRAY }), cell("Metadatos, subtitulos, etiquetas de eje", { w: 4238, bg: GRAY })),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 8: SEGUNDA PAGINA ─────────────────────────────────────────────────
function secPag2() {
  return [
    h1("8. Segunda Pagina — Vista Comparativa Ejecutiva"),

    para("Formato F. Esta pagina es para analisis, no para operacion. El directivo la revisa en reuniones semanales. El patron F es correcto aqui porque el contenido es mas denso y comparativo."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [1400, 8238],
      rows: [
        row(hcell("Fila / Zona", 1400), hcell("Contenido", 8238)),
        row(cell("Fila 1 (completa)", { w: 1400 }), cell("KPI bar de ahorro anual: m3 ahorrados, MXN ahorrados, kWh reducidos, CO2 equivalente evitado (usando 0.454 kg CO2/kWh de la red electrica mexicana).", { w: 8238 })),
        row(cell("Fila 2 izquierda", { w: 1400, bg: GRAY }), cell("Barras agrupadas: consumo promedio m3/ha por cultivo — PV-2025 vs PV-2026. Fuente: historial_riego agrupado por cultivo y ciclo.", { w: 8238, bg: GRAY })),
        row(cell("Fila 2 derecha", { w: 1400 }), cell("Scatter plot: eficiencia_riego (eje X) vs. sobre_riego_pct (eje Y) por parcela. Detecta outliers: parcelas con alta eficiencia pero sobre-riego persistente.", { w: 8238 })),
        row(cell("Fila 3 (completa)", { w: 1400, bg: GRAY }), cell("Tabla resumen por modulo: consumo promedio m3/ha, cumplimiento FAO-56 %, alertas totales, numero de parcelas con recomendacion aceptada vs. rechazada.", { w: 8238, bg: GRAY })),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 9: LO QUE NO DEBE TENER ──────────────────────────────────────────
function secNegativo() {
  return [
    h1("9. Lo que NO Debe Tener el Dashboard"),

    note("Cada elemento que se elimina reduce la carga cognitiva y hace mas efectivo lo que queda."),
    para(""),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [3200, 6438],
      rows: [
        row(hcell("Elemento a evitar", 3200), hcell("Por que", 6438)),
        row(cell("Mapa geografico en pagina principal", { w: 3200 }), cell("Consume espacio y atencion. No responde ninguna de las 6 preguntas operacionales en < 5 segundos. Puede ir en una pagina 3 de analisis espacial.", { w: 6438 })),
        row(cell("Mas de 5 KPI cards en la fila superior", { w: 3200, bg: GRAY }), cell("Todo lo que supera 5 pierde la atencion. Si algo no cabe en 5 cards, va en la tabla o en la pagina 2.", { w: 6438, bg: GRAY })),
        row(cell("Tablas con mas de 8 columnas visibles", { w: 3200 }), cell("La tabla de Zona E tiene 8 columnas: ese es el limite absoluto para lectura sin scroll horizontal.", { w: 6438 })),
        row(cell("Graficas de torta (pie charts)", { w: 3200, bg: GRAY }), cell("El ojo humano no compara angulos con precision. El donut en D2 es la unica excepcion justificada porque muestra proporciones de un todo.", { w: 6438, bg: GRAY })),
        row(cell("Titulos de visual con nombres de columnas", { w: 3200 }), cell("Los titulos deben ser preguntas o respuestas: 'Consumo real vs. objetivo FAO-56', no 'volumen_m3ha'.", { w: 6438 })),
        row(cell("Colores decorativos sin significado", { w: 3200, bg: GRAY }), cell("Cada color debe tener un significado consistente en todo el dashboard. Ver tabla de paleta en seccion 7.", { w: 6438, bg: GRAY })),
      ],
    }),

    para(""),
    divider(),
  ];
}

// ── SECTION 10: PASO A PASO POWER BI ─────────────────────────────────────────
function secPasoAPaso() {
  const STEP_W = [720, 2800, 6118];
  function srow(n, titulo, desc, bg) {
    return row(
      cell(n, { w: STEP_W[0], bg: bg || BLUE, bold: true, color: WHITE, align: AlignmentType.CENTER }),
      cell(titulo, { w: STEP_W[1], bold: true, bg: bg ? GRAY : undefined }),
      cell(desc, { w: STEP_W[2], bg: bg ? GRAY : undefined }),
    );
  }

  return [
    h1("10. Paso a Paso — Construccion en Power BI Desktop"),

    note("Version recomendada: Power BI Desktop (septiembre 2025 o posterior). Todos los pasos estan probados con los archivos CSV generados en powerbi/DB/"),

    para(""),
    h2("FASE 1 — Preparacion del entorno"),

    numbered("Descargar e instalar Power BI Desktop"),
    subStep("Ir a powerbi.microsoft.com -> Descargas -> Power BI Desktop"),
    subStep("Instalar con opciones por defecto. No se requiere cuenta Power BI Pro para desarrollo local."),

    para(""),
    numbered("Crear un nuevo archivo .pbix"),
    subStep("Abrir Power BI Desktop -> Archivo -> Nuevo"),
    subStep("Guardar inmediatamente: Archivo -> Guardar como -> MILPIN_Dashboard.pbix en la carpeta powerbi/"),

    para(""),
    h2("FASE 2 — Importar los 6 archivos CSV"),

    numbered("Conectar fuente de datos"),
    subStep("Clic en 'Obtener datos' (barra superior) -> Texto/CSV"),
    subStep("Navegar a powerbi/DB/ y seleccionar parcelas.csv -> Cargar"),
    subStep("Repetir para: cultivos_catalogo.csv, ciclos_agricolas.csv, historial_riego.csv, recomendaciones.csv, kpis_dashboard.csv"),
    subStep("Verificar que Power BI detecte correctamente los tipos de dato de cada columna en la vista previa antes de cargar."),

    para(""),
    numbered("Verificar tipos de dato en Power Query"),
    subStep("Clic en 'Transformar datos' (barra superior) para abrir Power Query Editor"),
    subStep("En historial_riego: fecha_riego -> tipo Fecha. volumen_m3ha, sobre_riego_pct, eficiencia_riego -> tipo Numero decimal. cumplimiento_fao56 -> tipo Verdadero/Falso"),
    subStep("En parcelas: superficie_ha, latitud, longitud, eficiencia_riego_2025, eficiencia_riego_2026 -> tipo Numero decimal"),
    subStep("En recomendaciones: fecha_generacion, fecha_riego_sugerida -> tipo Fecha. score_optimizacion, confianza_modelo -> tipo Numero decimal"),
    subStep("En kpis_dashboard: valor_2025, valor_2026, mejora_pct -> tipo Numero decimal"),
    subStep("Clic 'Cerrar y aplicar' cuando todos los tipos esten correctos"),

    para(""),
    h2("FASE 3 — Modelo de datos y relaciones"),

    numbered("Ir a la vista Modelo (icono de diagrama en el panel izquierdo)"),

    para(""),
    numbered("Crear las siguientes relaciones (arrastrar campo origen al campo destino)"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [3200, 3200, 1619, 1619],
      rows: [
        row(hcell("Tabla origen (campo)", 3200), hcell("Tabla destino (campo)", 3200), hcell("Cardinalidad", 1619), hcell("Filtro cruzado", 1619)),
        row(cell("historial_riego (id_parcela)", { w: 3200 }), cell("parcelas (id_parcela)", { w: 3200 }), cell("Muchos a uno", { w: 1619 }), cell("Ambas", { w: 1619 })),
        row(cell("historial_riego (id_ciclo)", { w: 3200, bg: GRAY }), cell("ciclos_agricolas (id_ciclo)", { w: 3200, bg: GRAY }), cell("Muchos a uno", { w: 1619, bg: GRAY }), cell("Ambas", { w: 1619, bg: GRAY })),
        row(cell("recomendaciones (id_parcela)", { w: 3200 }), cell("parcelas (id_parcela)", { w: 3200 }), cell("Muchos a uno", { w: 1619 }), cell("Ambas", { w: 1619 })),
        row(cell("recomendaciones (id_ciclo)", { w: 3200, bg: GRAY }), cell("ciclos_agricolas (id_ciclo)", { w: 3200, bg: GRAY }), cell("Muchos a uno", { w: 1619, bg: GRAY }), cell("Ambas", { w: 1619, bg: GRAY })),
      ],
    }),

    para(""),
    note("Si Power BI detecta relaciones automaticamente, verificar que coincidan con la tabla anterior. Eliminar cualquier relacion automatica incorrecta antes de continuar."),

    para(""),
    numbered("Verificar el modelo: cada tabla debe tener exactamente las relaciones de la tabla anterior. Ninguna tabla debe quedar aislada."),

    para(""),
    h2("FASE 4 — Medidas DAX"),

    note("Todas las medidas se crean en la tabla historial_riego. Clic derecho sobre la tabla en el panel Campos -> Nueva medida."),
    para(""),

    numbered("Medida: Consumo Promedio m3/ha"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Consumo Promedio m3ha = AVERAGEX(SUMMARIZE(historial_riego, historial_riego[id_parcela], historial_riego[id_ciclo], \"TotalVol\", SUM(historial_riego[volumen_total_m3]), \"Sup\", RELATED(parcelas[superficie_ha])), [TotalVol] / [Sup])",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Ahorro Total m3 (PV-2025 vs PV-2026)"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Ahorro m3 = VAR vol25 = CALCULATE(SUM(historial_riego[volumen_total_m3]), ciclos_agricolas[ciclo] = \"PV-2025\") VAR vol26 = CALCULATE(SUM(historial_riego[volumen_total_m3]), ciclos_agricolas[ciclo] = \"PV-2026\") RETURN vol25 - vol26",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Ahorro Economico MXN"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Ahorro MXN = [Ahorro m3] * 1.68",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Cumplimiento FAO-56 %"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Cumplimiento FAO56 % = DIVIDE(COUNTROWS(FILTER(historial_riego, historial_riego[cumplimiento_fao56] = TRUE())), COUNTROWS(historial_riego)) * 100",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Alertas Activas"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Alertas Activas = COUNTROWS(FILTER(historial_riego, historial_riego[alerta] <> \"\"))",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Sobre-riego Promedio %"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Sobre Riego Avg % = AVERAGE(historial_riego[sobre_riego_pct])",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    numbered("Medida: Objetivo FAO-56 (linea de referencia)"),
    new Paragraph({
      spacing: { before: 60, after: 60 },
      indent: { left: 720 },
      children: [new TextRun({
        text: "Objetivo FAO56 m3ha = AVERAGEX(RELATEDTABLE(parcelas), RELATED(cultivos_catalogo[consumo_objetivo_m3ha]))",
        font: "Courier New", size: 18, color: TEAL,
      })],
    }),

    para(""),
    pb(),
    h2("FASE 5 — Configurar el tema oscuro"),

    numbered("Aplicar tema base oscuro"),
    subStep("Cinta superior -> Ver -> Temas -> Temas integrados -> Explorador nocturno (Night Navigator) — es el mas cercano al esquema de color propuesto"),
    subStep("Si no existe ese tema: Ver -> Temas -> Personalizar tema actual"),

    para(""),
    numbered("Personalizar colores (Ver -> Temas -> Personalizar tema actual)"),
    subStep("Color 1 (principal): #4FC3F7"),
    subStep("Color 2: #66BB6A"),
    subStep("Color 3: #EF5350"),
    subStep("Color 4: #FFA726"),
    subStep("Fondo de pagina: #1A1D27 (aplicar en Formato -> Fondo de pagina)"),
    subStep("Exportar el tema como JSON con 'Guardar tema actual' para reutilizarlo en otros informes MILPIN"),

    para(""),
    h2("FASE 6 — Construir Zona A (KPI Strip)"),

    numbered("Insertar primera tarjeta KPI: Consumo vs Objetivo"),
    subStep("Insertar -> Objeto visual -> Tarjeta (Card)"),
    subStep("Campo: arrastrar medida [Consumo Promedio m3ha] al campo Valor"),
    subStep("Formato -> Etiqueta de datos -> Unidades: Ninguno, Decimales: 0"),
    subStep("Formato -> Titulo: 'Consumo m3/ha actual'"),
    subStep("Formato -> Fondo: #242736"),
    subStep("Agregar un KPI visual secundario: Insertar -> Objeto visual -> KPI"),
    subStep("Valor: [Consumo Promedio m3ha], Objetivo: [Objetivo FAO56 m3ha]"),

    para(""),
    numbered("Insertar tarjeta: Ahorro m3"),
    subStep("Repetir proceso con medida [Ahorro m3]"),
    subStep("Formato -> Color de datos: condicional. Si valor > 0 -> #66BB6A (verde), si < 0 -> #EF5350 (rojo)"),

    para(""),
    numbered("Insertar tarjeta: Ahorro MXN"),
    subStep("Campo: medida [Ahorro MXN]"),
    subStep("Formato -> Unidades de visualizacion: Millones si el valor supera 1,000,000"),

    para(""),
    numbered("Insertar tarjeta: Cumplimiento FAO-56 %"),
    subStep("Usar objeto visual Medidor (Gauge): Valor = [Cumplimiento FAO56 %], Min = 0, Max = 100, Objetivo = 75"),
    subStep("O tarjeta simple con formato condicional: <50 rojo, 50-74 amarillo, >=75 verde"),

    para(""),
    numbered("Insertar tarjeta: Alertas Activas"),
    subStep("Campo: medida [Alertas Activas]"),
    subStep("Formato condicional de color de fuente: si valor > 0 -> #EF5350, si = 0 -> #66BB6A"),
    subStep("Agregar icono de advertencia en el titulo si el valor es > 0 (usando campo de imagen condicional)"),

    para(""),
    numbered("Alinear las 5 tarjetas"),
    subStep("Seleccionar las 5 tarjetas con Ctrl+Clic -> Formato -> Alinear -> Distribuir horizontalmente"),
    subStep("Altura uniforme: 120 px cada una. Ancho: 20% del canvas cada una"),
    subStep("Posicion: parte superior del canvas, fila unica"),

    para(""),
    h2("FASE 7 — Construir Zona B (Filtros)"),

    numbered("Insertar segmentador de ciclo"),
    subStep("Insertar -> Objeto visual -> Segmentador de datos (Slicer)"),
    subStep("Campo: ciclos_agricolas[ciclo]"),
    subStep("Formato -> Estilo del segmentador: Lista"),
    subStep("Formato -> Encabezado: 'Ciclo Agricola'"),
    subStep("Posicion: esquina superior derecha"),

    para(""),
    numbered("Insertar segmentador de cultivo"),
    subStep("Campo: historial_riego[cultivo]"),
    subStep("Formato -> Seleccion multiple: activado"),
    subStep("Formato -> Encabezado: 'Cultivo'"),

    para(""),
    numbered("Insertar segmentador de modulo DR-041"),
    subStep("Campo: parcelas[modulo_dr041]"),
    subStep("Formato -> Encabezado: 'Modulo DR-041'"),

    para(""),
    numbered("Insertar badge MILPIN activo"),
    subStep("Insertar -> Objeto visual -> Tarjeta"),
    subStep("Campo: ciclos_agricolas[milpin_activo]"),
    subStep("Formato condicional: True = texto 'MILPIN ACTIVO' en verde, False = 'SIN MILPIN' en gris"),

    para(""),
    pb(),
    h2("FASE 8 — Construir Zona C (Grafica Principal)"),

    numbered("Insertar grafico de lineas"),
    subStep("Insertar -> Objeto visual -> Grafico de lineas"),
    subStep("Eje X: historial_riego[fecha_riego] — formato Mes/Ano"),
    subStep("Valores (Linea 1): medida [Consumo Promedio m3ha] — color #4FC3F7 (azul agua)"),
    subStep("Valores (Linea 2): medida [Objetivo FAO56 m3ha] — color #FFA726 (naranja punteado)"),
    subStep("Formato -> Linea 2 -> Estilo de linea: Punteado"),

    para(""),
    numbered("Agregar area sombreada de sobre-riego"),
    subStep("Formato -> Lineas -> Sombra de area: activado para Linea 1"),
    subStep("Color de sombra: #EF5350 con transparencia 70%"),

    para(""),
    numbered("Configurar tooltip personalizado"),
    subStep("Agregar al campo Informacion sobre herramientas: cultivo, etapa_fenologica, kc, eto_mm, sobre_riego_pct, alerta"),
    subStep("Formato -> Informacion sobre herramientas -> Activar modo detallado"),

    para(""),
    numbered("Ajustar tamano y posicion"),
    subStep("Posicion: centro-izquierda del canvas. Ancho: 40% del canvas. Alto: 45% de la altura util"),
    subStep("Formato -> Fondo: #242736"),

    para(""),
    h2("FASE 9 — Construir Zona D (Visuals de soporte)"),

    numbered("Insertar grafico de barras apiladas — Sobre-riego por cultivo (D1)"),
    subStep("Insertar -> Objeto visual -> Grafico de barras apiladas"),
    subStep("Eje: historial_riego[cultivo]"),
    subStep("Valores: Crear medida 'Pct Cumplimiento' = [Cumplimiento FAO56 %] y medida 'Pct Sobre Riego' = 100 - [Cumplimiento FAO56 %]"),
    subStep("Color 'Pct Cumplimiento': #66BB6A. Color 'Pct Sobre Riego': #EF5350"),
    subStep("Agregar linea de referencia constante en Y=10: Formato -> Lineas de referencia -> Agregar -> Valor: 10, Color: blanco punteado"),
    subStep("Titulo: 'Cumplimiento FAO-56 vs Sobre-riego por Cultivo'"),

    para(""),
    numbered("Insertar grafico de dona — Sistemas de riego (D2)"),
    subStep("Insertar -> Objeto visual -> Grafico de anillos (Donut Chart)"),
    subStep("Leyenda: historial_riego[metodo_riego]"),
    subStep("Valores: COUNTROWS(historial_riego) — esto da la distribucion por numero de eventos"),
    subStep("Formato -> Radio interior: 55% para que se vea el centro"),
    subStep("Agregar etiqueta central: crear medida 'Eff Prom' = AVERAGE(historial_riego[eficiencia_riego]) * 100, colocarla como tarjeta pequena encima de la dona"),
    subStep("Titulo: 'Distribucion Sistemas de Riego'"),

    para(""),
    h2("FASE 10 — Construir Zona E (Tabla Operacional)"),

    numbered("Insertar objeto visual de tabla"),
    subStep("Insertar -> Objeto visual -> Tabla"),
    subStep("Agregar columnas: id_parcela, modulo_dr041, cultivo, etapa_fenologica, MAX(fecha_riego), SUM(deficit_hidrico_mm), AVG(sobre_riego_pct), nivel_urgencia (de recomendaciones), aceptada (de recomendaciones)"),
    subStep("Ordenar por nivel_urgencia descendente"),

    para(""),
    numbered("Agregar formato condicional de fondo por filas"),
    subStep("Seleccionar columna 'alerta' -> Formato -> Fondo de celda -> Formato condicional"),
    subStep("Regla 1: si alerta contiene 'Sobre-riego' -> fondo #FDECEA (rojo muy suave)"),
    subStep("Regla 2: si aceptada = 'sin_respuesta' -> fondo #FFF8E1 (amarillo suave)"),

    para(""),
    numbered("Filtrar la tabla para mostrar solo filas con problema"),
    subStep("Agregar filtro de nivel de visual: alerta <> '' O nivel_urgencia = 'Alta'"),
    subStep("Formato -> Alto de fila: 36 px. Filas visibles sin scroll: 10"),
    subStep("Activar scroll vertical interno"),
    subStep("Titulo: 'Parcelas con Alerta o Recomendacion Pendiente'"),

    para(""),
    numbered("Alinear tabla al ancho completo del canvas"),
    subStep("Posicion: fila inferior. Ancho: 100% del canvas. Alto: ~30% de la altura util"),

    para(""),
    h2("FASE 11 — Interactividad y filtros cruzados"),

    numbered("Verificar que todos los visuals responden a los segmentadores de Zona B"),
    subStep("Clic en segmentador 'PV-2026' y confirmar que: KPI cards cambian, grafica de lineas cambia, barras de cultivo cambian, dona cambia, tabla se filtra"),

    para(""),
    numbered("Configurar interaccion entre visuals"),
    subStep("Seleccionar el grafico de lineas -> Formato -> Editar interacciones"),
    subStep("Marcar que la dona y las barras de cultivo filtren al hacer clic en un punto de la linea"),
    subStep("La tabla operacional debe filtrar siempre con todos los segmentadores activos"),

    para(""),
    numbered("Agregar drill-through a pagina de detalle de parcela"),
    subStep("En pagina 2: agregar campo id_parcela como campo de obtener detalles (Drill through)"),
    subStep("En la tabla de Zona E: clic derecho sobre una fila -> Obtener detalles -> Pagina 2 llevara el filtro de esa parcela especifica"),

    para(""),
    h2("FASE 12 — Crear la pagina 2 (Vista Ejecutiva)"),

    numbered("Agregar nueva pagina"),
    subStep("Clic en el boton '+' en la barra de paginas inferior -> Renombrar como 'Analisis Comparativo 2025-2026'"),

    para(""),
    numbered("Insertar KPI bar de ahorro (Fila 1 completa)"),
    subStep("4 tarjetas en fila: Ahorro m3, Ahorro MXN, Ahorro kWh, CO2 equivalente"),
    subStep("CO2 = crear medida: Ahorro CO2 kg = CALCULATE(SUM(historial_riego[energia_kwh]), ciclos_agricolas[ciclo]=\"PV-2025\") - CALCULATE(SUM(historial_riego[energia_kwh]), ciclos_agricolas[ciclo]=\"PV-2026\") * 0.454"),

    para(""),
    numbered("Insertar barras agrupadas — consumo por cultivo 2025 vs 2026 (Fila 2 izquierda)"),
    subStep("Grafico de barras agrupadas (Clustered Bar Chart)"),
    subStep("Eje Y: historial_riego[cultivo]"),
    subStep("Valores: medida con CALCULATE filtrando por ciclo 'PV-2025' (barra naranja) y medida con 'PV-2026' (barra azul)"),
    subStep("Agregar linea de referencia en objetivo FAO-56 por cultivo"),

    para(""),
    numbered("Insertar scatter plot — eficiencia vs sobre-riego (Fila 2 derecha)"),
    subStep("Grafico de dispersion (Scatter Chart)"),
    subStep("Eje X: AVG(eficiencia_riego) por parcela"),
    subStep("Eje Y: AVG(sobre_riego_pct) por parcela"),
    subStep("Tamano de punto: superficie_ha"),
    subStep("Color: por cultivo"),
    subStep("Detalles: id_parcela (para identificar outliers)"),

    para(""),
    numbered("Insertar tabla resumen por modulo (Fila 3 completa)"),
    subStep("Tabla con: modulo_dr041, consumo promedio m3/ha, cumplimiento_fao56 %, alertas totales, recomendaciones aceptadas %, recomendaciones rechazadas %"),

    para(""),
    h2("FASE 13 — Publicacion y configuracion final"),

    numbered("Revisar checklist antes de publicar"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [640, 8998],
      rows: [
        row(hcell("", 640), hcell("Verificacion", 8998)),
        row(cell("[ ]", { w: 640 }), cell("Todos los segmentadores de Zona B afectan todos los visuals simultaneamente", { w: 8998 })),
        row(cell("[ ]", { w: 640, bg: GRAY }), cell("La tabla Zona E filtra solo parcelas del ciclo seleccionado", { w: 8998, bg: GRAY })),
        row(cell("[ ]", { w: 640 }), cell("Las tarjetas KPI muestran N/A limpio cuando no hay datos en el filtro (verificar con ISINSCOPE en DAX)", { w: 8998 })),
        row(cell("[ ]", { w: 640, bg: GRAY }), cell("El visual C muestra la linea FAO-56 teorica aunque no haya datos reales en ese filtro", { w: 8998, bg: GRAY })),
        row(cell("[ ]", { w: 640 }), cell("El donut D2 se actualiza al cambiar ciclo y muestra la migracion de sistemas visible", { w: 8998 })),
        row(cell("[ ]", { w: 640, bg: GRAY }), cell("Colores de semaforo son consistentes en todos los visuals (rojo=problema, verde=bien, naranja=objetivo)", { w: 8998, bg: GRAY })),
        row(cell("[ ]", { w: 640 }), cell("Todos los tooltips tienen unidades explicitas: m3/ha, MXN, mm, %, kWh", { w: 8998 })),
        row(cell("[ ]", { w: 640, bg: GRAY }), cell("La pagina 2 tiene drill-through funcional desde la tabla de la pagina 1", { w: 8998, bg: GRAY })),
        row(cell("[ ]", { w: 640 }), cell("El archivo .pbix esta guardado y el tema oscuro exportado como JSON", { w: 8998 })),
      ],
    }),

    para(""),
    numbered("Publicar en Power BI Service (opcional)"),
    subStep("Archivo -> Publicar -> Seleccionar area de trabajo MILPIN"),
    subStep("En Power BI Service: configurar actualizacion de datos programada si los CSV se actualizan periodicamente"),
    subStep("Configurar alertas de datos: si 'Alertas Activas' > 0, enviar notificacion por email al jefe de modulo"),

    para(""),
    divider(),
  ];
}

// ── SECTION 11: ARCHIVOS CSV ──────────────────────────────────────────────────
function secArchivos() {
  return [
    h1("11. Referencia de Archivos CSV"),

    new Table({
      width: { size: CW, type: WidthType.DXA },
      columnWidths: [2800, 1400, 5438],
      rows: [
        row(hcell("Archivo", 2800), hcell("Registros", 1400), hcell("Uso principal en el dashboard", 5438)),
        row(cell("parcelas.csv", { w: 2800 }), cell("80", { w: 1400, align: AlignmentType.CENTER }), cell("Informacion de cada parcela: modulo, cultivo, sistema de riego, superficie. Base para filtros y tabla Zona E.", { w: 5438 })),
        row(cell("cultivos_catalogo.csv", { w: 2800, bg: GRAY }), cell("5", { w: 1400, bg: GRAY, align: AlignmentType.CENTER }), cell("Parametros FAO-56 por cultivo: Kc inicial/medio/final, duracion, consumo objetivo. Base para lineas de referencia.", { w: 5438, bg: GRAY })),
        row(cell("ciclos_agricolas.csv", { w: 2800 }), cell("3", { w: 1400, align: AlignmentType.CENTER }), cell("PV-2025, OI-2025, PV-2026. Controla el segmentador de ciclo y el badge MILPIN activo.", { w: 5438 })),
        row(cell("historial_riego.csv", { w: 2800, bg: GRAY }), cell("2,745", { w: 1400, bg: GRAY, align: AlignmentType.CENTER }), cell("Tabla principal. Contiene todos los eventos de riego con fechas, volumenes, eficiencias, alertas y cumplimiento FAO-56. Base para todas las graficas y medidas DAX.", { w: 5438, bg: GRAY })),
        row(cell("recomendaciones.csv", { w: 2800 }), cell("1,310", { w: 1400, align: AlignmentType.CENTER }), cell("Recomendaciones generadas por el algoritmo MILPIN. Columna 'aceptada' para semaforo de tabla Zona E. Columna 'nivel_urgencia' para ordenamiento.", { w: 5438 })),
        row(cell("kpis_dashboard.csv", { w: 2800, bg: GRAY }), cell("10", { w: 1400, bg: GRAY, align: AlignmentType.CENTER }), cell("Resumen ejecutivo precalculado con mejora_pct lista para tarjetas y comparativos directos. Alternativa a calcular todo en DAX.", { w: 5438, bg: GRAY })),
      ],
    }),

    para(""),
    note("Ruta de archivos: powerbi/DB/ relativa a la raiz del repositorio MILPIN. Todos en UTF-8, separador coma, encabezado en primera fila. Compatibles con Power BI, pandas, Tableau y PostgreSQL COPY."),
    para(""),
    divider(),
  ];
}

// ── DOCUMENT ASSEMBLY ─────────────────────────────────────────────────────────
const allChildren = [
  ...coverPage(),
  ...secIntro(),
  ...secTipo(),
  ...secPreguntas(),
  pb(),
  ...secFormato(),
  ...secKpis(),
  pb(),
  ...secVisuals(),
  pb(),
  ...secPaleta(),
  ...secPag2(),
  ...secNegativo(),
  pb(),
  ...secPasoAPaso(),
  pb(),
  ...secArchivos(),
];

const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
      {
        reference: "steps",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 }, spacing: { before: 100, after: 60 } } },
        }],
      },
      {
        reference: "substeps",
        levels: [{
          level: 0, format: LevelFormat.LOWER_LETTER, text: "%1)",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } },
        }],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Arial", size: 20, color: BLACK } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: TEAL },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: DGRAY },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 },
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PW, height: PH },
        margin: { top: MT, right: MR, bottom: MB, left: ML },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          spacing: { before: 0, after: 0 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
          children: [
            new TextRun({ text: "MILPIN  |  Monitor de Optimizacion Hidrica DR-041", size: 16, font: "Arial", color: DGRAY }),
          ],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: BORDER_COLOR, space: 4 } },
          children: [
            new TextRun({ text: "Pagina ", size: 16, font: "Arial", color: DGRAY }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, font: "Arial", color: DGRAY }),
            new TextRun({ text: "  |  Confidencial — uso interno DR-041 Modulo 3  |  v1.0  2026", size: 16, font: "Arial", color: DGRAY }),
          ],
        })],
      }),
    },
    children: allChildren,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  const out = "C:\\Users\\madri\\Downloads\\pp26(Omar)\\powerbi\\MILPIN_Dashboard_Propuesta.docx";
  fs.writeFileSync(out, buffer);
  const kb = Math.round(buffer.length / 1024);
  console.log(`Saved: ${out} (${kb} KB)`);
});
