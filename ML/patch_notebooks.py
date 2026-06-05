"""
patch_notebooks.py
------------------
Agrega una celda de setup a todos los notebooks de ML/experiments/ para que,
al ejecutarse, guarden automáticamente en ML/images/:

  - Figuras matplotlib  → PNG (auto-save en plt.show() + redirigir plt.savefig)
  - Figuras Plotly       → HTML + PNG (via write_html / write_image)
  - DataFrames pandas    → CSV + HTML (hook en _repr_html_)
  - Prints / stdout      → output_log.txt (tee global)

Uso:
    python ML/patch_notebooks.py
"""

import json
import re
import uuid
from pathlib import Path

EXPERIMENTS = Path(__file__).parent / "experiments"
IMAGES_DIR_REL = "../images"   # relativo desde experiments/

# ─── Celda de setup que se inyecta en cada notebook ──────────────────────────
SETUP_CELL_SOURCE = """\
# ═══════════════════════════════════════════════════════════════════
# MILPÍN — Auto-guardado en ML/images/
# Generado por ML/patch_notebooks.py — NO editar manualmente.
# ═══════════════════════════════════════════════════════════════════
from pathlib import Path
import sys as _sys
import re  as _re
import atexit as _atexit

# ── Directorio de salida ─────────────────────────────────────────────────────
_here = Path().resolve()
IMAGES_DIR = (
    _here.parent / "images"
    if _here.name == "experiments"
    else _here / "ML" / "images"
)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ── Parche matplotlib: auto-save en plt.show() + redirigir plt.savefig ───────
import matplotlib.pyplot   as _plt
import matplotlib.figure   as _mpl_fig

_saved_fig_ids  = set()
_auto_fig_count = [0]
_orig_plt_show    = _plt.show
_orig_plt_savefig = _plt.savefig
_orig_fig_savefig = _mpl_fig.Figure.savefig

def _auto_fname(fig, n):
    title = (fig._suptitle.get_text() if fig._suptitle else "") or next(
        (ax.get_title() for ax in fig.get_axes() if ax.get_title()), "")
    stem = _re.sub(r"[^\\w\\-]", "_", title)[:50].strip("_").lower() if title else f"figura_{n:03d}"
    return f"{stem}.png"

def _patched_plt_savefig(fname, *a, **kw):
    dest = IMAGES_DIR / Path(str(fname)).name
    fig  = _plt.gcf()
    _orig_fig_savefig(fig, dest, *a, **kw)  # llama directo para evitar doble-parche
    _saved_fig_ids.add(id(fig))
    print(f"  ✓ [imagen] {dest.name}")

def _patched_fig_savefig(self, fname, *a, **kw):
    dest = IMAGES_DIR / Path(str(fname)).name
    _orig_fig_savefig(self, dest, *a, **kw)
    _saved_fig_ids.add(id(self))
    print(f"  ✓ [imagen] {dest.name}")

def _patched_plt_show(*a, **kw):
    fig = _plt.gcf()
    if fig.get_axes() and id(fig) not in _saved_fig_ids:
        _auto_fig_count[0] += 1
        fname = _auto_fname(fig, _auto_fig_count[0])
        _orig_fig_savefig(fig, IMAGES_DIR / fname, dpi=150, bbox_inches="tight")
        print(f"  ✓ [auto-imagen] {fname}")
    _saved_fig_ids.discard(id(fig))
    _orig_plt_show(*a, **kw)

_plt.show               = _patched_plt_show
_plt.savefig            = _patched_plt_savefig
_mpl_fig.Figure.savefig = _patched_fig_savefig

# ── Parche pandas: auto-save DataFrames al mostrarse en Jupyter ─────────────
_df_count = [0]
try:
    import pandas as _pd
    _orig_df_repr_html = _pd.DataFrame._repr_html_

    def _patched_df_repr_html(self):
        _df_count[0] += 1
        stem = f"tabla_{_df_count[0]:03d}"
        self.to_csv(IMAGES_DIR / f"{stem}.csv", index=True, encoding="utf-8-sig")
        self.to_html(IMAGES_DIR / f"{stem}.html")
        print(f"  ✓ [tabla] {stem}.csv  ({len(self)} filas × {len(self.columns)} cols)")
        return _orig_df_repr_html(self)

    _pd.DataFrame._repr_html_ = _patched_df_repr_html
except Exception as _pd_err:
    print(f"  ! pandas hook: {_pd_err}")

# ── Capturar stdout → IMAGES_DIR/output_log.txt ──────────────────────────────
_log_path = IMAGES_DIR / "output_log.txt"
_log_file = open(_log_path, "w", encoding="utf-8")

class _Tee:
    def __init__(self, real, log):
        self._real = real
        self._log  = log
    def write(self, s):
        self._real.write(s)
        self._log.write(s)
    def flush(self):
        self._real.flush()
        self._log.flush()
    def __getattr__(self, attr):
        return getattr(self._real, attr)

_sys.stdout = _Tee(_sys.__stdout__, _log_file)
_atexit.register(lambda: (_log_file.flush(), _log_file.close()))

print(f"✓ IMAGES_DIR  → {IMAGES_DIR}")
print(f"✓ matplotlib  → auto-save en show() + redirigir savefig()")
print(f"✓ pandas      → auto-save DataFrames (CSV + HTML)")
print(f"✓ stdout      → {_log_path.name}")
"""

# ─── Celda de setup Plotly (solo para notebooks con Plotly) ──────────────────
PLOTLY_CELL_SOURCE = """\
# ── Auto-guardado Plotly → IMAGES_DIR ───────────────────────────────────────
# Reemplaza fig.show() con una versión que también guarda HTML + PNG.
import plotly.io as _pio
import plotly.basedatatypes as _pbd

_plotly_count = [0]
_orig_plotly_show = _pbd.BaseFigure.show

def _patched_plotly_show(self, *a, **kw):
    _plotly_count[0] += 1
    n    = _plotly_count[0]
    stem = f"plotly_{n:02d}"
    # HTML siempre (sin dependencias extra)
    html_path = IMAGES_DIR / f"{stem}.html"
    self.write_html(str(html_path))
    print(f"  ✓ [plotly] {stem}.html")
    # PNG via kaleido (opcional)
    try:
        png_path = IMAGES_DIR / f"{stem}.png"
        self.write_image(str(png_path), scale=2)
        print(f"  ✓ [plotly] {stem}.png")
    except Exception as _ke:
        print(f"  ! PNG no disponible (instala kaleido): {_ke}")
    _orig_plotly_show(self, *a, **kw)

_pbd.BaseFigure.show = _patched_plotly_show
print("✓ Plotly → auto-save HTML + PNG en cada fig.show()")
"""


def build_cell(source: str, cell_id: str | None = None) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id or str(uuid.uuid4())[:8],
        "metadata": {},
        "outputs": [],
        "source": source,
    }


def get_source(cell: dict) -> str:
    s = cell.get("source", [])
    return "".join(s) if isinstance(s, list) else str(s)


def set_source(cell: dict, source: str) -> None:
    cell["source"] = source


SETUP_MARKER = "MILPÍN — Auto-guardado en ML/images/"
PLOTLY_MARKER = "Auto-guardado Plotly → IMAGES_DIR"


def patch_notebook(nb_path: Path) -> None:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    cells = nb["cells"]

    all_src = "\n".join(get_source(c) for c in cells if c["cell_type"] == "code")
    has_plotly = bool(
        re.search(r"import plotly|from plotly|go\.Figure|px\.", all_src)
    )

    # ── Reemplazar o insertar setup ─────────────────────────────────────────
    insert_idx = 1 if (cells and cells[0]["cell_type"] == "markdown") else 0

    new_cells = [c for c in cells
                 if SETUP_MARKER not in get_source(c)
                 and PLOTLY_MARKER not in get_source(c)]

    injected = 0
    new_cells.insert(insert_idx, build_cell(SETUP_CELL_SOURCE, "milpin_setup"))
    injected += 1

    if has_plotly:
        new_cells.insert(insert_idx + injected, build_cell(PLOTLY_CELL_SOURCE, "milpin_plotly"))
        injected += 1

    nb["cells"] = new_cells
    nb_path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")

    label = "matplotlib"
    if has_plotly:
        label = "Plotly + matplotlib"
    print(f"  OK {nb_path.name:<52} [{label}]  +{injected} celda(s)")


def main() -> None:
    print(f"\nProcesando notebooks en: {EXPERIMENTS}")
    print(f"Destino de salidas:      {EXPERIMENTS.parent / 'images'}\n")

    notebooks = sorted(EXPERIMENTS.glob("*.ipynb"))
    if not notebooks:
        print("  No se encontraron notebooks.")
        return

    for nb in notebooks:
        patch_notebook(nb)

    print(f"\nLISTO: {len(notebooks)} notebooks modificados.")
    print("   Ejecuta cada notebook para generar los archivos en ML/images/\n")


if __name__ == "__main__":
    main()
