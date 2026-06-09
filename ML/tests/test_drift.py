"""Tests para ml/monitoring/drift.py"""
import numpy as np
import pytest
from ml.monitoring.drift import calcular_psi, calcular_ks


def test_psi_distribuciones_iguales():
    rng = np.random.default_rng(42)
    ref = rng.normal(0, 1, 500)
    prod = rng.normal(0, 1, 500)
    psi = calcular_psi(ref, prod)
    assert psi < 0.1, f"PSI esperado <0.1, obtenido {psi:.3f}"


def test_psi_drift_severo():
    rng = np.random.default_rng(42)
    ref = rng.normal(0, 1, 500)
    prod = rng.normal(5, 1, 500)  # shift significativo
    psi = calcular_psi(ref, prod)
    assert psi > 0.2, f"PSI esperado >0.2, obtenido {psi:.3f}"


def test_ks_sin_drift():
    rng = np.random.default_rng(42)
    ref = rng.normal(0, 1, 300)
    prod = rng.normal(0, 1, 300)
    resultado = calcular_ks(ref, prod)
    assert not resultado["drift"], "No debería detectar drift en distribuciones iguales"
