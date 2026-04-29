"""
settings.py — Configuración centralizada del proyecto MILPÍN AgTech v2.0.

Usa pydantic-settings para cargar desde backend/.env con tipado fuerte.
Agrupa las configs por dominio (BaseSettings por componente) para no mezclar
variables de BD, voz, ETL, etc.

Uso:
    from settings import nasa_settings
    print(nasa_settings.anio_inicio)

Cada clase tiene su propio `env_prefix`, de modo que NASA_ANIO_INICIO no colisiona
con, por ejemplo, OLLAMA_URL si se agrega en el futuro.
"""
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Directorio raíz del repo: <repo>/backend/settings.py → <repo>/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR  = Path(__file__).resolve().parent


class NasaPowerSettings(BaseSettings):
    """
    Configuración del pipeline ETL NASA POWER.

    Lee de backend/.env con prefijo `NASA_`:
        NASA_ANIO_INICIO=2000
        NASA_ANIO_FIN=2024
        NASA_RAW_DIR=./data/raw/nasa_power
        NASA_REQUEST_TIMEOUT_S=60

    Si no hay .env, usa los defaults razonables para Valle del Yaqui.

    Las variables meteorológicas se dejan fijas en código (no como env) porque
    están ligadas al modelo físico FAO-56: cambiar qué variables se descargan
    implicaría cambios en balance_hidrico.calcular_eto_penman_monteith_serie.
    """
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="NASA_",
        extra="ignore",
    )

    # Período histórico a descargar
    anio_inicio: int = 2000
    anio_fin: int = 2024

    # Endpoint NASA POWER (Daily point API, comunidad Agricultura)
    api_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    api_community: str = "AG"

    # Red
    request_timeout_s: float = 60.0
    courtesy_sleep_s: float = 1.0  # pausa entre requests para evitar rate-limit

    # Cache en disco del JSON crudo (para no re-hit NASA en re-ejecuciones)
    raw_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "raw" / "nasa_power",
        description="Carpeta donde cachear los JSON crudos por parcela.",
    )

    # Umbrales de sanidad ET0 calibrados para Valle del Yaqui, Sonora (lat ~27°N)
    # Zona hiperárida. Media anual documentada: 5-7 mm/día.
    et0_umbral_pico: float = 12.0
    et0_media_min: float = 2.0
    et0_media_max: float = 8.0

    # Variables NASA POWER (fijas: ligadas al cálculo FAO-56)
    variables: List[str] = [
        "T2M_MAX",            # Temperatura máxima 2m (°C)
        "T2M_MIN",            # Temperatura mínima 2m (°C)
        "RH2M",               # Humedad relativa 2m (%)
        "WS2M",               # Viento 2m (m/s)
        "ALLSKY_SFC_SW_DWN",  # Radiación solar superficial (MJ/m²/día)
        "PRECTOTCORR",        # Precipitación total corregida (mm/día)
    ]

    @field_validator("raw_dir", mode="before")
    @classmethod
    def _expand_raw_dir(cls, v):
        """Permite paths relativos en el .env; los resuelve contra PROJECT_ROOT."""
        if v is None:
            return v
        p = Path(v)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        return p


# Instancia única reutilizable (pydantic la valida al importar)
nasa_settings = NasaPowerSettings()
