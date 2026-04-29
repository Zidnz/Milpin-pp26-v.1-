"""Script para agregar secciones 8-11 al notebook EDA MILPÍN."""
import json
import uuid
from pathlib import Path

NB_PATH = Path(__file__).parent.parent / "backend" / "eda_milpin.ipynb"


def new_md(src: str) -> dict:
    return {"cell_type": "markdown", "id": uuid.uuid4().hex[:8],
            "metadata": {}, "source": [src]}


def new_code(src: str) -> dict:
    return {"cell_type": "code", "id": uuid.uuid4().hex[:8],
            "execution_count": None, "metadata": {},
            "outputs": [], "source": [src]}


# ---------------------------------------------------------------------------
# Sección 8 — Histogramas
# ---------------------------------------------------------------------------
S8_MD = "---\n## 8 · Histogramas — Distribución de Variables Clave"

S8_CODE = """from scipy.stats import gaussian_kde

hist_groups = {
    'Parcelas': {
        'df': parcelas,
        'cols':   ['area_ha', 'conductividad_electrica',
                   'profundidad_raiz_cm', 'agua_disponible_mm'],
        'labels': ['Superficie (ha)', 'CE (dS/m)',
                   'Prof. raíz (cm)', 'Agua disponible (mm)'],
        'colors': [AZUL, ROJO, VERDE, NARANJA],
    },
    'Historial de riego': {
        'df': historial,
        'cols':   ['volumen_m3_ha', 'lamina_mm', 'costo_energia_mxn'],
        'labels': ['Volumen m³/ha (evento)', 'Lámina aplicada (mm)',
                   'Costo energía por evento (MXN)'],
        'colors': [AZUL, VERDE, NARANJA],
    },
    'Recomendaciones FAO-56': {
        'df': recomend,
        'cols':   ['lamina_recomendada_mm', 'eto_referencia',
                   'etc_calculada', 'deficit_acumulado_mm'],
        'labels': ['Lámina recomendada (mm)', 'ETo referencia',
                   'ETc calculada', 'Déficit acumulado (mm)'],
        'colors': [AZUL, VERDE, ROJO, NARANJA],
    },
}

for grupo, cfg in hist_groups.items():
    ncols = len(cfg['cols'])
    fig, axes = plt.subplots(1, ncols, figsize=(4.5 * ncols, 4.2))
    if ncols == 1:
        axes = [axes]
    fig.suptitle(f'Histogramas — {grupo}', fontsize=13, fontweight='bold')

    for ax, col, lbl, color in zip(axes, cfg['cols'], cfg['labels'], cfg['colors']):
        s = cfg['df'][col].dropna()
        ax.hist(s, bins=25, color=color, edgecolor='white', alpha=0.80)
        xs = np.linspace(s.min(), s.max(), 300)
        kde = gaussian_kde(s)
        ax_r = ax.twinx()
        ax_r.plot(xs, kde(xs), color='black', lw=1.8, alpha=0.65)
        ax_r.set_yticks([])
        ax.axvline(s.mean(),   color='white',  lw=1.8, linestyle='--',
                   label=f'Media: {s.mean():.2f}')
        ax.axvline(s.median(), color='yellow', lw=1.8, linestyle=':',
                   label=f'Mediana: {s.median():.2f}')
        ax.set_title(lbl, fontsize=10)
        ax.set_xlabel(lbl, fontsize=9)
        ax.set_ylabel('Frecuencia')
        ax.legend(fontsize=7)
        ax.text(0.98, 0.96, f'Asimetría: {s.skew():.2f}',
                transform=ax.transAxes, ha='right', va='top',
                fontsize=8, color='gray')

    plt.tight_layout()
    plt.show()
    print()
"""

# ---------------------------------------------------------------------------
# Sección 9 — Heatmaps
# ---------------------------------------------------------------------------
S9_MD = "---\n## 9 · Heatmaps — Correlaciones y Patrones Temporales"

S9_CODE = """fig, axes = plt.subplots(1, 3, figsize=(20, 6))
fig.suptitle('Heatmaps — MILPÍN DR-041', fontsize=14, fontweight='bold')

# (a) Correlación variables edáficas de parcelas
ax1 = axes[0]
num_cols_parc = ['area_ha', 'conductividad_electrica',
                 'profundidad_raiz_cm', 'capacidad_campo',
                 'punto_marchitez', 'agua_disponible_mm']
corr_parc = parcelas[num_cols_parc].corr()
corr_labels_p = ['Sup.(ha)', 'CE(dS/m)', 'Prof.raíz',
                 'Cap.campo', 'Pto.march.', 'ADT(mm)']
sns.heatmap(corr_parc, ax=ax1, annot=True, fmt='.2f', cmap='RdBu_r',
            center=0, vmin=-1, vmax=1, linewidths=0.5,
            xticklabels=corr_labels_p, yticklabels=corr_labels_p,
            annot_kws={'size': 8}, square=True,
            cbar_kws={'shrink': 0.7})
ax1.set_title('Correlación — Variables edáficas\\n(parcelas)', fontsize=11)
ax1.tick_params(axis='x', rotation=40, labelsize=8)
ax1.tick_params(axis='y', rotation=0,  labelsize=8)

# (b) Volumen mensual por cultivo
ax2 = axes[1]
hist_m = historial.merge(parcelas[['id_parcela', 'cultivo']],
                         on='id_parcela', how='left')
hist_m['mes_str'] = hist_m['fecha_riego'].dt.strftime('%Y-%m')
pivot_vol = (hist_m.groupby(['mes_str', 'cultivo'])['volumen_m3_ha']
             .mean().unstack(fill_value=0))
if len(pivot_vol) > 12:
    pivot_vol = pivot_vol.tail(12)
sns.heatmap(pivot_vol, ax=ax2, cmap='YlOrRd', annot=True, fmt='.0f',
            linewidths=0.4, annot_kws={'size': 7},
            cbar_kws={'shrink': 0.7, 'label': 'm³/ha'})
ax2.set_title('Volumen medio m³/ha\\npor mes y cultivo', fontsize=11)
ax2.set_xlabel('Cultivo'); ax2.set_ylabel('Mes')
ax2.tick_params(axis='x', rotation=25, labelsize=9)
ax2.tick_params(axis='y', rotation=0,  labelsize=8)

# (c) Tasa de aceptación por cultivo × urgencia
ax3 = axes[2]
pivot_acept = (recomend.groupby(['cultivo', 'nivel_urgencia'])['aceptada']
               .apply(lambda x: round((x == 'aceptada').mean() * 100, 1))
               .unstack(fill_value=0))
urg_order = [c for c in ['crítico', 'moderado', 'preventivo']
             if c in pivot_acept.columns]
pivot_acept = pivot_acept[urg_order]
sns.heatmap(pivot_acept, ax=ax3, cmap='RdYlGn', annot=True, fmt='.1f',
            vmin=0, vmax=100, linewidths=0.5,
            annot_kws={'size': 10, 'weight': 'bold'},
            cbar_kws={'shrink': 0.7, 'label': '% aceptadas'})
ax3.set_title('Tasa de aceptación (%)\\npor cultivo × urgencia', fontsize=11)
ax3.set_xlabel('Urgencia'); ax3.set_ylabel('Cultivo')
ax3.tick_params(axis='x', rotation=15, labelsize=9)
ax3.tick_params(axis='y', rotation=0,  labelsize=9)

plt.tight_layout()
plt.show()
"""

# ---------------------------------------------------------------------------
# Sección 10 — Feature Engineering
# ---------------------------------------------------------------------------
S10_MD = (
    "---\n"
    "## 10 · Ingeniería de Características — Dataset para ML\n\n"
    "Se construye un DataFrame plano a nivel `id_parcela` con features agregadas\n"
    "de los cuatro datasets, listo para modelos supervisados.\n\n"
    "| Target | Tipo |\n"
    "|---|---|\n"
    "| `vol_m3_ha_total` | Regresión (consumo hídrico) |\n"
    "| `meta_alcanzada` | Clasificación binaria (≤ 6 000 m³/ha) |"
)

S10_CODE = """# ── Bloque 1: base de parcelas ───────────────────────────────────────────────
feat = parcelas[[
    'id_parcela', 'cultivo', 'area_ha', 'tipo_suelo', 'sistema_riego',
    'conductividad_electrica', 'profundidad_raiz_cm',
    'capacidad_campo', 'punto_marchitez', 'agua_disponible_mm'
]].copy()

feat['stress_salino']  = (feat['conductividad_electrica'] > 4).astype(int)
feat['stress_hidrico'] = (
    feat['agua_disponible_mm'] < feat['agua_disponible_mm'].quantile(0.25)
).astype(int)
feat['stress_doble'] = (feat['stress_salino'] & feat['stress_hidrico']).astype(int)

feat['cap_almacen_relativa'] = (
    (feat['capacidad_campo'] - feat['punto_marchitez']) / feat['capacidad_campo']
).round(4)

eff_map = {'goteo': 0.90, 'aspersión': 0.75, 'microaspersión': 0.80, 'gravedad': 0.55}
feat['eficiencia_riego'] = feat['sistema_riego'].map(eff_map).fillna(0.65)

# ── Bloque 2: historial de riego ─────────────────────────────────────────────
h_feats = (
    historial.groupby('id_parcela').agg(
        n_eventos_riego     = ('id_riego',         'count'),
        vol_m3_ha_total     = ('volumen_m3_ha',    'sum'),
        vol_m3_ha_media     = ('volumen_m3_ha',    'mean'),
        vol_m3_ha_std       = ('volumen_m3_ha',    'std'),
        lamina_media_mm     = ('lamina_mm',        'mean'),
        lamina_cv           = ('lamina_mm',
                               lambda x: x.std() / x.mean() if x.mean() > 0 else 0),
        costo_energia_total = ('costo_energia_mxn','sum'),
        costo_energia_media = ('costo_energia_mxn','mean'),
    ).reset_index()
)
h_feats['vol_m3_ha_std'] = h_feats['vol_m3_ha_std'].fillna(0)
feat = feat.merge(h_feats, on='id_parcela', how='left')

# ── Bloque 3: recomendaciones ─────────────────────────────────────────────────
r_feats = (
    recomend.groupby('id_parcela').agg(
        n_recomendaciones   = ('id_recomendacion',    'count'),
        tasa_aceptacion     = ('aceptada',
                               lambda x: (x == 'aceptada').mean()),
        tasa_ignorada       = ('aceptada',
                               lambda x: (x == 'ignorada').mean()),
        eto_media           = ('eto_referencia',      'mean'),
        etc_media           = ('etc_calculada',       'mean'),
        deficit_acum_medio  = ('deficit_acumulado_mm','mean'),
        lamina_rec_media_mm = ('lamina_recomendada_mm','mean'),
        pct_critico         = ('nivel_urgencia',
                               lambda x: (x == 'crítico').mean()),
        pct_moderado        = ('nivel_urgencia',
                               lambda x: (x == 'moderado').mean()),
    ).reset_index()
)
r_feats['ratio_eta_eto'] = (
    r_feats['etc_media'] / r_feats['eto_media'].replace(0, np.nan)
).round(4)
feat = feat.merge(r_feats, on='id_parcela', how='left')

# ── Bloque 4: costos económicos ───────────────────────────────────────────────
c_feats = (
    costos.groupby('id_parcela').agg(
        roi_medio            = ('roi_pct',                'mean'),
        margen_medio_mxn     = ('margen_contribucion_mxn','mean'),
        ingreso_medio_mxn    = ('ingreso_estimado_mxn',   'mean'),
        ingreso_por_m3_medio = ('ingreso_por_m3',         'mean'),
        vol_agua_ciclo       = ('volumen_agua_total_m3',  'mean'),
    ).reset_index()
)
feat = feat.merge(c_feats, on='id_parcela', how='left')

# ── Bloque 5: parámetros FAO-56 del catálogo ─────────────────────────────────
cult_join = cult[['nombre_comun', 'kc_ponderado', 'ky_total',
                  'ciclo_total_dias']].rename(columns={'nombre_comun': 'cultivo'})
feat = feat.merge(cult_join, on='cultivo', how='left')

# ── Bloque 6: variables objetivo ─────────────────────────────────────────────
feat['meta_alcanzada']       = (feat['vol_m3_ha_total'] <= 6000).astype(int)
feat['ahorro_potencial_m3']  = (8000 - feat['vol_m3_ha_total']).clip(lower=0)
feat['ahorro_potencial_mxn'] = feat['ahorro_potencial_m3'] * 1.68

# ── Bloque 7: encoding de categóricas ────────────────────────────────────────
feat_encoded = pd.get_dummies(
    feat, columns=['cultivo', 'tipo_suelo', 'sistema_riego'],
    prefix=['cult', 'suelo', 'riego'], drop_first=False, dtype=int
)

print(f'✓ Dataset ML base:    {feat.shape[0]} filas × {feat.shape[1]} columnas')
print(f'✓ Dataset codificado: {feat_encoded.shape[0]} filas × {feat_encoded.shape[1]} columnas')
print()
print('▶ Balance target (meta_alcanzada):')
print(feat['meta_alcanzada']
      .value_counts(normalize=True)
      .rename({0: 'No alcanzada (0)', 1: 'Alcanzada (1)'})
      .map('{:.1%}'.format))
print()
nulls = feat.isnull().sum()
nulls_pos = nulls[nulls > 0]
if len(nulls_pos):
    print('▶ Nulos en dataset ML:')
    print(nulls_pos.to_string())
else:
    print('▶ Nulos en dataset ML: ninguno')
"""

# ---------------------------------------------------------------------------
# Sección 11 — DataFrame ML: Vista
# ---------------------------------------------------------------------------
S11_MD = "---\n## 11 · DataFrame ML — Vista del Dataset Construido"

S11_CODE = """# ── (a) Muestra estilizada ──────────────────────────────────────────────────
cols_show = [
    'id_parcela', 'cultivo', 'area_ha', 'conductividad_electrica',
    'agua_disponible_mm', 'stress_salino', 'stress_doble',
    'eficiencia_riego', 'n_eventos_riego', 'vol_m3_ha_total',
    'tasa_aceptacion', 'pct_critico', 'roi_medio',
    'kc_ponderado', 'ky_total',
    'meta_alcanzada', 'ahorro_potencial_mxn'
]
col_alias = [
    'ID Parcela', 'Cultivo', 'Área (ha)', 'CE (dS/m)',
    'ADT (mm)', 'Estrés salino', 'Estrés doble',
    'Efic. riego', 'N° eventos', 'Vol m³/ha total',
    'Tasa aceptac.', '% Crítico', 'ROI (%)',
    'Kc pond.', 'Ky total',
    'Meta alcanzada', 'Ahorro pot. (MXN)'
]

muestra = feat[cols_show].head(15).copy().reset_index(drop=True)
muestra.columns = col_alias

def _hl_target(v):
    if v == 1:
        return 'background-color:#D5F5E3;color:#1E8449;font-weight:bold'
    return 'background-color:#FADBD8;color:#C0392B;font-weight:bold'

def _hl_stress(v):
    return 'background-color:#FADBD8;font-weight:bold' if v == 1 else ''

display(
    muestra.style
    .set_caption('🤖 Dataset ML — Primeras 15 filas (features + targets)')
    .applymap(_hl_target, subset=['Meta alcanzada'])
    .applymap(_hl_stress, subset=['Estrés salino', 'Estrés doble'])
    .background_gradient(subset=['Vol m³/ha total'], cmap='RdYlGn_r')
    .background_gradient(subset=['Ahorro pot. (MXN)'], cmap='Greens')
    .background_gradient(subset=['ROI (%)'], cmap='RdYlGn')
    .format({
        'Área (ha)':       '{:.1f}',
        'CE (dS/m)':       '{:.2f}',
        'ADT (mm)':        '{:.1f}',
        'Efic. riego':     '{:.2f}',
        'Vol m³/ha total': '{:,.0f}',
        'Tasa aceptac.':   '{:.0%}',
        '% Crítico':       '{:.0%}',
        'ROI (%)':         '{:.1f}%',
        'Kc pond.':        '{:.3f}',
        'Ky total':        '{:.2f}',
        'Ahorro pot. (MXN)': '${:,.0f}',
    })
    .set_properties(**{'text-align': 'center', 'font-size': '10px'})
    .set_table_styles([{'selector': 'caption',
                        'props': [('font-size', '14px'), ('font-weight', 'bold')]}])
    .hide(axis='index')
)

# ── (b) Estadísticas descriptivas ───────────────────────────────────────────
desc_ml = feat[cols_show[2:]].describe().T
desc_ml.index = col_alias[2:]

display(
    desc_ml.style
    .set_caption('📊 Estadísticas descriptivas — Dataset ML')
    .background_gradient(subset=['mean'], cmap='Blues')
    .background_gradient(subset=['std'],  cmap='Oranges')
    .format('{:.3f}')
    .format('{:.0f}', subset=['count'])
    .set_table_styles([{'selector': 'caption',
                        'props': [('font-size', '14px'), ('font-weight', 'bold')]}])
)

# ── (c) Heatmap de correlación entre features ML y el target ────────────────
num_feats_ml = [
    'area_ha', 'conductividad_electrica', 'agua_disponible_mm',
    'eficiencia_riego', 'cap_almacen_relativa',
    'n_eventos_riego', 'lamina_media_mm', 'lamina_cv',
    'tasa_aceptacion', 'deficit_acum_medio', 'pct_critico',
    'roi_medio', 'kc_ponderado', 'ky_total',
    'stress_salino', 'stress_doble',
    'vol_m3_ha_total'
]
num_feats_ml = [c for c in num_feats_ml if c in feat.columns]
corr_ml = feat[num_feats_ml].corr()

fig, ax = plt.subplots(figsize=(14, 11))
sns.heatmap(
    corr_ml, ax=ax, annot=True, fmt='.2f', cmap='RdBu_r',
    center=0, vmin=-1, vmax=1, linewidths=0.3,
    annot_kws={'size': 7},
    xticklabels=[c.replace('_', '\\n') for c in corr_ml.columns],
    yticklabels=[c.replace('_', ' ') for c in corr_ml.index],
    square=True, cbar_kws={'shrink': 0.6}
)
ax.set_title(
    'Matriz de correlación — Features ML\\n'
    '(última fila/columna = vol_m3_ha_total)',
    fontsize=12, fontweight='bold'
)
ax.tick_params(axis='x', rotation=45, labelsize=8)
ax.tick_params(axis='y', rotation=0,  labelsize=8)
plt.tight_layout()
plt.show()

# ── (d) Ranking de correlación con el target ─────────────────────────────────
target_corr = (
    corr_ml['vol_m3_ha_total']
    .drop('vol_m3_ha_total')
    .rename('corr')
    .reset_index()
    .rename(columns={'index': 'Feature'})
)
target_corr['|corr|'] = target_corr['corr'].abs()
target_corr['Dir.']   = target_corr['corr'].apply(lambda v: '+ (directa)' if v >= 0 else '− (inversa)')
target_corr = target_corr.sort_values('|corr|', ascending=False).reset_index(drop=True)
target_corr.columns = ['Feature', 'Correlación', '|Correlación|', 'Dirección']

display(
    target_corr.style
    .set_caption('🎯 Features por correlación absoluta con vol_m3_ha_total')
    .background_gradient(subset=['|Correlación|'], cmap='Blues')
    .bar(subset=['Correlación'], color=[VERDE, ROJO], align='zero', vmin=-1, vmax=1)
    .format({'Correlación': '{:+.3f}', '|Correlación|': '{:.3f}'})
    .set_properties(**{'text-align': 'center'})
    .set_table_styles([{'selector': 'caption',
                        'props': [('font-size', '13px'), ('font-weight', 'bold')]}])
    .hide(axis='index')
)
"""

# ---------------------------------------------------------------------------
# Escribir en el notebook
# ---------------------------------------------------------------------------
with open(NB_PATH, "r", encoding="utf-8") as f:
    nb = json.load(f)

new_cells = [
    new_md(S8_MD), new_code(S8_CODE),
    new_md(S9_MD), new_code(S9_CODE),
    new_md(S10_MD), new_code(S10_CODE),
    new_md(S11_MD), new_code(S11_CODE),
]
nb["cells"].extend(new_cells)

with open(NB_PATH, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print(f"Notebook actualizado: {len(nb['cells'])} celdas totales (+{len(new_cells)} nuevas)")
