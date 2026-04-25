"""
models.py — Modelos ORM de SQLAlchemy para el MVP de MILPÍN AgTech v2.0

6 tablas del MVP:
    usuarios          → Agricultores / operadores del ERP
    cultivos_catalogo → Parámetros FAO-56 por especie (tabla de referencia)
    parcelas          → Lotes de cultivo con atributos edáficos y geometría GeoJSON
    recomendaciones   → Recomendaciones de riego generadas por el motor FAO-56
    historial_riego   → Registro permanente de eventos de riego ejecutados
    clima_diario      → Series climáticas diarias por parcela (fuente: NASA POWER)

Nota sobre geometría (parcelas.geom):
    En el MVP, la geometría se almacena como JSONB (GeoJSON).
    En la Fase 2, se migrará a GEOMETRY(Polygon, 4326) via PostGIS + GeoAlchemy2.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ── Helper para UUID como PK ──────────────────────────────────────────────────
def uuid_pk():
    """Columna UUID como clave primaria con valor por defecto gen_random_uuid()."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


# ── 1. usuarios ───────────────────────────────────────────────────────────────
class Usuario(Base):
    """
    Agricultores, técnicos de campo y administradores del ERP MILPÍN.
    Es la entidad raíz: todas las parcelas pertenecen a un usuario.
    """
    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("email", name="uq_usuarios_email"),
        {"schema": None},  # Sin schema, usa el schema por defecto (public)
    )

    id_usuario: Mapped[uuid.UUID] = uuid_pk()
    nombre_completo: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    telefono: Mapped[Optional[str]] = mapped_column(String(20))
    modulo_dr041: Mapped[Optional[str]] = mapped_column(
        String(50),
        comment="Módulo de riego dentro del DR-041 (ej. 'Módulo 3')"
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relaciones
    parcelas: Mapped[list["Parcela"]] = relationship(
        "Parcela", back_populates="usuario", lazy="selectin"
    )


# ── 2. cultivos_catalogo ──────────────────────────────────────────────────────
class CultivoCatalogo(Base):
    """
    Catálogo de especies cultivadas con parámetros FAO-56 (Kc) y FAO-33 (Ky).
    Tabla de referencia: no cambia frecuentemente.
    Cultivos principales del Valle del Yaqui DR-041: trigo, cártamo, garbanzo, maíz.
    """
    __tablename__ = "cultivos_catalogo"

    id_cultivo: Mapped[uuid.UUID] = uuid_pk()
    nombre_comun: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre_cientifico: Mapped[Optional[str]] = mapped_column(String(120))

    # Coeficientes de cultivo Kc — FAO-56 Tabla 12
    kc_inicial: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    kc_medio: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    kc_final: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)

    # Factor de sensibilidad al estrés hídrico — FAO-33 Tabla 25
    ky_total: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)

    # Duración de etapas fenológicas (días)
    dias_etapa_inicial: Mapped[int] = mapped_column(Integer, nullable=False)
    dias_etapa_desarrollo: Mapped[int] = mapped_column(Integer, nullable=False)
    dias_etapa_media: Mapped[int] = mapped_column(Integer, nullable=False)
    dias_etapa_final: Mapped[int] = mapped_column(Integer, nullable=False)

    # Rendimiento potencial bajo condiciones óptimas de riego
    rendimiento_potencial_ton: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))

    # Relaciones
    parcelas: Mapped[list["Parcela"]] = relationship(
        "Parcela", back_populates="cultivo_actual", lazy="noload"
    )
    recomendaciones: Mapped[list["Recomendacion"]] = relationship(
        "Recomendacion", back_populates="cultivo", lazy="noload"
    )

    @property
    def ciclo_total_dias(self) -> int:
        """Duración total del ciclo agrícola en días."""
        return (
            self.dias_etapa_inicial
            + self.dias_etapa_desarrollo
            + self.dias_etapa_media
            + self.dias_etapa_final
        )


# ── 3. parcelas ───────────────────────────────────────────────────────────────
class Parcela(Base):
    """
    Lote de cultivo con características físicas del suelo y geometría espacial.

    Geometría: almacenada como JSONB (GeoJSON) en el MVP.
    Migración a PostGIS GEOMETRY(Polygon,4326) planificada para Fase 2.

    Agua disponible total (mm):
        ADT = (capacidad_campo - punto_marchitez) * profundidad_raiz_cm * 10
    """
    __tablename__ = "parcelas"

    id_parcela: Mapped[uuid.UUID] = uuid_pk()

    # FKs
    id_usuario: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuarios.id_usuario", ondelete="RESTRICT"),
        nullable=False,
    )
    id_cultivo_actual: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cultivos_catalogo.id_cultivo", ondelete="SET NULL"),
        nullable=True,
        comment="NULL = parcela en barbecho o sin siembra activa",
    )

    # Identificación
    nombre_parcela: Mapped[Optional[str]] = mapped_column(String(100))

    # Geometría como GeoJSON (MVP) — se migra a PostGIS en Fase 2
    geom: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="GeoJSON Polygon del lote. Migrar a GEOMETRY(Polygon,4326) en Fase 2."
    )
    area_ha: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4),
        comment="Superficie en hectáreas. Calcular con ST_Area(geom) en Fase 2."
    )

    # Características edáficas
    tipo_suelo: Mapped[Optional[str]] = mapped_column(
        String(50),
        comment="arcilloso, franco-arcilloso, franco, franco-arenoso"
    )
    conductividad_electrica: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2),
        comment="CE en dS/m. CE > 4 dS/m = estrés salino activo"
    )
    profundidad_raiz_cm: Mapped[Optional[int]] = mapped_column(
        Integer,
        comment="Profundidad efectiva de raíces en cm"
    )
    capacidad_campo: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4),
        comment="Humedad volumétrica a CC (m³/m³)"
    )
    punto_marchitez: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4),
        comment="Humedad volumétrica en PMP (m³/m³)"
    )

    # Sistema de riego
    sistema_riego: Mapped[Optional[str]] = mapped_column(
        String(30),
        comment="gravedad, goteo, aspersion, microaspersion"
    )

    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relaciones
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="parcelas")
    cultivo_actual: Mapped[Optional["CultivoCatalogo"]] = relationship(
        "CultivoCatalogo", back_populates="parcelas"
    )
    historial_riego: Mapped[list["HistorialRiego"]] = relationship(
        "HistorialRiego", back_populates="parcela", lazy="noload",
        order_by="HistorialRiego.fecha_riego.desc()"
    )
    recomendaciones: Mapped[list["Recomendacion"]] = relationship(
        "Recomendacion", back_populates="parcela", lazy="noload"
    )
    costos_ciclo: Mapped[list["CostoCiclo"]] = relationship(
        "CostoCiclo", back_populates="parcela", lazy="noload"
    )
    clima_diario: Mapped[list["ClimaDiario"]] = relationship(
        "ClimaDiario", back_populates="parcela", lazy="noload",
        cascade="all, delete-orphan",
        order_by="ClimaDiario.fecha.desc()"
    )

    @property
    def agua_disponible_mm(self) -> Optional[float]:
        """
        Agua disponible total (ADT) en mm.
        ADT = (CC - PMP) × profundidad_raiz_cm × 10
        """
        if None in (self.capacidad_campo, self.punto_marchitez, self.profundidad_raiz_cm):
            return None
        return (
            float(self.capacidad_campo - self.punto_marchitez)
            * self.profundidad_raiz_cm
            * 10.0
        )


# ── 4. recomendaciones ────────────────────────────────────────────────────────
class Recomendacion(Base):
    """
    Recomendación de riego generada por el motor FAO-56 de MILPÍN.

    Almacena tanto los inputs (snapshot en parametros_json) como los outputs
    del modelo, garantizando trazabilidad completa del algoritmo.

    El campo 'aceptada' captura el feedback del agricultor:
        pendiente → el agricultor aún no ha respondido
        aceptada  → ejecutó el riego según lo recomendado
        modificada → ejecutó el riego con lámina diferente
        ignorada  → no ejecutó el riego
    """
    __tablename__ = "recomendaciones"
    __table_args__ = (
        CheckConstraint(
            "nivel_urgencia IN ('critico', 'moderado', 'preventivo')",
            name="ck_recomendaciones_urgencia"
        ),
        CheckConstraint(
            "aceptada IN ('pendiente', 'aceptada', 'modificada', 'ignorada')",
            name="ck_recomendaciones_aceptada"
        ),
    )

    id_recomendacion: Mapped[uuid.UUID] = uuid_pk()

    # FKs
    id_parcela: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcelas.id_parcela", ondelete="RESTRICT"),
        nullable=False,
    )
    id_cultivo: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cultivos_catalogo.id_cultivo", ondelete="SET NULL"),
        nullable=True,
    )

    # Outputs del modelo
    fecha_generacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fecha_riego_sugerida: Mapped[Optional[date]] = mapped_column(Date)
    lamina_recomendada_mm: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    eto_referencia: Mapped[Optional[float]] = mapped_column(Numeric(8, 3))
    etc_calculada: Mapped[Optional[float]] = mapped_column(Numeric(8, 3))
    deficit_acumulado_mm: Mapped[Optional[float]] = mapped_column(Numeric(8, 2))
    dias_sin_riego: Mapped[Optional[int]] = mapped_column(Integer)

    # Clasificación y trazabilidad
    nivel_urgencia: Mapped[Optional[str]] = mapped_column(String(20))
    algoritmo_version: Mapped[Optional[str]] = mapped_column(
        String(30), default="fao56-mvp-v1.0"
    )

    # Feedback del agricultor
    aceptada: Mapped[str] = mapped_column(
        String(20), default="pendiente", server_default="pendiente"
    )
    lamina_ejecutada_mm: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2),
        comment="Lámina real aplicada (si fue modificada respecto a la recomendada)"
    )

    # Snapshot de inputs del modelo (trazabilidad completa)
    parametros_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="Snapshot de todos los parámetros de entrada al momento del cálculo"
    )

    # Relaciones
    parcela: Mapped["Parcela"] = relationship("Parcela", back_populates="recomendaciones")
    cultivo: Mapped[Optional["CultivoCatalogo"]] = relationship(
        "CultivoCatalogo", back_populates="recomendaciones"
    )
    historial_riego: Mapped[list["HistorialRiego"]] = relationship(
        "HistorialRiego", back_populates="recomendacion", lazy="noload"
    )


# ── 5. historial_riego ────────────────────────────────────────────────────────
class HistorialRiego(Base):
    """
    Registro permanente de cada evento de riego ejecutado en una parcela.

    Es la tabla de medición del KPI central del proyecto:
        volumen_m3_ha vs. baseline DR-041 de 8,000 m³/ha/ciclo.

    El campo id_recomendacion es NULL para riegos manuales sin recomendación previa.
    El campo origen_decision permite distinguir entre decisiones del sistema,
    manuales, o iniciadas por el asistente de voz.
    """
    __tablename__ = "historial_riego"
    __table_args__ = (
        CheckConstraint(
            "metodo_riego IN ('gravedad', 'goteo', 'aspersion', 'microaspersion')",
            name="ck_riego_metodo"
        ),
        CheckConstraint(
            "origen_decision IN ('sistema', 'manual', 'voz')",
            name="ck_riego_origen"
        ),
    )

    id_riego: Mapped[uuid.UUID] = uuid_pk()

    # FKs
    id_parcela: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcelas.id_parcela", ondelete="RESTRICT"),
        nullable=False,
    )
    id_recomendacion: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recomendaciones.id_recomendacion", ondelete="SET NULL"),
        nullable=True,
        comment="NULL para riegos manuales sin recomendación previa",
    )

    # Datos del evento
    fecha_riego: Mapped[date] = mapped_column(Date, nullable=False)
    volumen_m3_ha: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2),
        comment="Volumen en m³/ha. KPI vs. baseline 8,000 m³/ha/ciclo DR-041"
    )
    lamina_mm: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2),
        comment="Lámina en mm (1 mm = 10 m³/ha)"
    )
    duracion_horas: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    metodo_riego: Mapped[Optional[str]] = mapped_column(String(30))
    origen_decision: Mapped[Optional[str]] = mapped_column(
        String(20), default="manual"
    )
    costo_energia_mxn: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2),
        comment="Costo = volumen_m3_ha × area_ha × tarifa_m3. Baseline: $1.68/m³"
    )
    observaciones: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relaciones
    parcela: Mapped["Parcela"] = relationship(
        "Parcela", back_populates="historial_riego"
    )
    recomendacion: Mapped[Optional["Recomendacion"]] = relationship(
        "Recomendacion", back_populates="historial_riego"
    )


# -- 6. costos_ciclo -----------------------------------------------------------
class CostoCiclo(Base):
    """Resumen economico por parcela y ciclo agricola."""
    __tablename__ = "costos_ciclo"

    id_costo: Mapped[uuid.UUID] = uuid_pk()
    id_parcela: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcelas.id_parcela", ondelete="RESTRICT"),
        nullable=False,
    )
    ciclo_agricola: Mapped[str] = mapped_column(String(20), nullable=False)
    cultivo: Mapped[Optional[str]] = mapped_column(String(80))
    volumen_agua_total_m3: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_agua_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_fertilizantes_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_agroquimicos_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_semilla_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_maquinaria_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    costo_mano_obra_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    ingreso_estimado_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    margen_contribucion_mxn: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))

    parcela: Mapped["Parcela"] = relationship(
        "Parcela", back_populates="costos_ciclo"
    )


# -- 7. clima_diario -----------------------------------------------------------
class ClimaDiario(Base):
    """
    Serie climática diaria por parcela. Fuente primaria: NASA POWER API
    (modelo MERRA-2 + CERES), granularidad punto-geográfico × día.

    Se alimenta desde `tools/nasa_power_etl.py`. La columna `et0` se calcula
    con `backend/core/balance_hidrico.calcular_eto_penman_monteith_serie`
    sobre los 5 inputs meteorológicos, sin almacenar cálculos derivados
    adicionales (Kc, ETc, balance — esos son responsabilidad de la capa de
    recomendaciones).

    Clave primaria compuesta (id_parcela, fecha) = una observación por parcela
    por día. Las re-ejecuciones del ETL usan INSERT ... ON CONFLICT DO NOTHING
    para ser idempotentes.

    Imputación de NaN:
        - Variables continuas (T, HR, viento, radiación): interpolación lineal
          hasta 3 días consecutivos (responsabilidad del ETL).
        - Lluvia: NaN → 0, nunca interpolar.
    """
    __tablename__ = "clima_diario"

    # PK compuesta
    id_parcela: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcelas.id_parcela", ondelete="CASCADE"),
        primary_key=True,
    )
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)

    # Variables meteorológicas NASA POWER
    t_max: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), comment="Temperatura máxima diaria a 2m (°C)"
    )
    t_min: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), comment="Temperatura mínima diaria a 2m (°C)"
    )
    humedad_rel: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), comment="Humedad relativa media a 2m (%)"
    )
    viento: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), comment="Viento medio a 2m (m/s)"
    )
    radiacion: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 3), comment="Radiación solar superficial (MJ/m²/día)"
    )
    lluvia: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2), comment="Precipitación total diaria corregida (mm)"
    )

    # Valor derivado persistido (costoso de recalcular por serie completa)
    et0: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2),
        comment="Evapotranspiración de referencia FAO-56 Penman-Monteith (mm/día)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relación inversa
    parcela: Mapped["Parcela"] = relationship(
        "Parcela", back_populates="clima_diario"
    )
