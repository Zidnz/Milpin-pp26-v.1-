"""
Detección de drift para modelos MILPÍN.
Métricas implementadas: PSI (Population Stability Index), KS test.

Uso:
    from ml.monitoring.drift import calcular_psi, calcular_ks
"""

import numpy as np
from scipy import stats


def calcular_psi(referencia: np.ndarray, produccion: np.ndarray, bins: int = 10) -> float:
    """
    Population Stability Index.
    PSI < 0.1  → estable
    PSI 0.1-0.2 → monitorear
    PSI > 0.2  → reentrenar
    """
    ref_counts, bin_edges = np.histogram(referencia, bins=bins)
    prod_counts, _ = np.histogram(produccion, bins=bin_edges)

    ref_pct = ref_counts / len(referencia) + 1e-6
    prod_pct = prod_counts / len(produccion) + 1e-6

    psi = float(np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct)))
    return psi


def calcular_ks(referencia: np.ndarray, produccion: np.ndarray) -> dict:
    """
    Kolmogorov-Smirnov test.
    Retorna {'statistic': float, 'p_value': float, 'drift': bool}
    """
    stat, p_val = stats.ks_2samp(referencia, produccion)
    return {
        "statistic": float(stat),
        "p_value": float(p_val),
        "drift": bool(p_val < 0.05),
    }
