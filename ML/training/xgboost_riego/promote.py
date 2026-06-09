"""
Promote gate — decide si el modelo entrenado supera los umbrales mínimos
definidos en ml/configs/xgboost_riego.yaml antes de copiarlo a producción.
"""
import yaml
import sys
from pathlib import Path
from eval import evaluar

CONFIG_PATH = Path(__file__).parents[2] / "configs" / "xgboost_riego.yaml"


def promote(data_path: Path) -> bool:
    config = yaml.safe_load(open(CONFIG_PATH))
    gate = config["promote_gate"]
    metricas = evaluar(data_path)

    ok = (
        metricas["f1"] >= gate["min_f1"]
        and metricas["precision"] >= gate["min_precision"]
    )

    if ok:
        print(f"✓ Promote aprobado: F1={metricas['f1']:.3f}, Precision={metricas['precision']:.3f}")
    else:
        print(f"✗ Promote rechazado: F1={metricas['f1']:.3f} (min {gate['min_f1']}), "
              f"Precision={metricas['precision']:.3f} (min {gate['min_precision']})")
    return ok


if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not data:
        print("Uso: python promote.py <data_path.csv>")
        sys.exit(1)
    sys.exit(0 if promote(data) else 1)
