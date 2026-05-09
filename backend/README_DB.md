# MILPÍN AgTech v2.0 — Configuración de Base de Datos (MVP)

## Estado actual del entorno

| Componente | Requerido | Estado |
|---|---|---|
| Python 3.10+ | ✓ | ✓ Disponible |
| PostgreSQL 15+ | ✓ | ✗ Instalar |
| pip / venv | ✓ | ✓ Disponible |
| asyncpg | ✓ | ✗ `pip install` |
| sqlalchemy[asyncio] | ✓ | ✗ `pip install` |

---

## Paso 1 — Instalar PostgreSQL 15 en Ubuntu

```bash
# Agregar repositorio oficial de PostgreSQL
sudo apt update
sudo apt install -y curl ca-certificates
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | sudo gpg --dearmor -o /usr/share/keyrings/postgresql.gpg

echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] \
    https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    | sudo tee /etc/apt/sources.list.d/pgdg.list

sudo apt update
sudo apt install -y postgresql-15

# Verificar instalación
psql --version   # Debe mostrar: psql (PostgreSQL) 15.x
```

## Paso 2 — Crear base de datos y usuario MILPÍN

```bash
# Iniciar servicio
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Crear usuario y base de datos
sudo -u postgres psql <<SQL
CREATE USER milpin WITH PASSWORD 'milpin_pass';
CREATE DATABASE milpin_mvp OWNER milpin;
GRANT ALL PRIVILEGES ON DATABASE milpin_mvp TO milpin;
\q
SQL

# Verificar conexión
psql -U milpin -d milpin_mvp -c "SELECT version();"
```

## Paso 3 — Instalar dependencias Python

```bash
# Desde la carpeta /backend
cd /ruta/a/tu/proyecto/backend

# Crear entorno virtual (recomendado)
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

## Paso 4 — Configurar variables de entorno

Crea el archivo `.env` en la carpeta `/backend`:

```bash
# backend/.env
DATABASE_URL=postgresql+asyncpg://milpin:milpin_pass@localhost:5432/milpin_mvp
```

> **Alternativa para desarrollo rápido sin PostgreSQL (SQLite):**
> ```
> DATABASE_URL=sqlite+aiosqlite:///./milpin_dev.db
> ```
> Con SQLite no necesitas instalar nada extra (excepto `aiosqlite`).
> Las consultas espaciales PostGIS no estarán disponibles.

## Paso 5 — Inicializar la base de datos

```bash
# Crea las 5 tablas y carga el catálogo de cultivos FAO-56
python init_db.py

# Verificar conexión únicamente
python init_db.py --check

# RESET completo (borra y recrea todo — solo desarrollo)
python init_db.py --reset
```

Salida esperada:
```
============================================================
  MILPÍN AgTech v2.0 — Inicialización de Base de Datos
============================================================
✓ Conexión a base de datos: OK

Creando tablas...
  ✓ Tablas creadas (o ya existían).

Cargando cultivos del catálogo FAO-56...
  + Cultivo insertado: Trigo
  + Cultivo insertado: Cártamo
  + Cultivo insertado: Garbanzo
  + Cultivo insertado: Maíz
  + Cultivo insertado: Algodón
  ✓ 5 cultivos nuevos insertados.
============================================================
  ✓ Base de datos inicializada correctamente.
============================================================
```

## Paso 6 — Iniciar el backend

```bash
uvicorn main:app --reload --port 8000
```

Verifica en el navegador: http://localhost:8000/docs

Los endpoints de BD estarán disponibles bajo `/api/`:
- `GET  /api/cultivos`           → Lista cultivos del catálogo
- `POST /api/usuarios`           → Crear agricultor
- `POST /api/parcelas`           → Registrar lote
- `POST /api/riego`              → Registrar evento de riego
- `GET  /api/parcelas/{id}/kpi`  → KPI de consumo vs. baseline DR-041

---

## Archivos creados en esta implementación

```
backend/
├── database.py        ← Motor SQLAlchemy async + factory de sesiones
├── models.py          ← 5 modelos ORM (usuarios, parcelas, cultivos, riego, reco)
├── init_db.py         ← Script de inicialización y seed de datos
├── schema.sql         ← DDL de referencia para PostgreSQL
├── requirements.txt   ← Dependencias actualizadas
├── main.py            ← Actualizado: lifespan + router de BD
└── API/
    └── db_api.py      ← 12 endpoints CRUD para las 5 tablas
```

---

## Solución de problemas comunes

**Error: `connection refused` en el puerto 5432**
```bash
sudo systemctl status postgresql    # ¿Está corriendo?
sudo systemctl start postgresql
```

**Error: `role "milpin" does not exist`**
```bash
sudo -u postgres createuser --pwprompt milpin
sudo -u postgres createdb -O milpin milpin_mvp
```

**Error: `asyncpg` no instalado**
```bash
pip install asyncpg sqlalchemy[asyncio]
```

**Usar SQLite para desarrollo inmediato (sin instalar PostgreSQL)**
```bash
pip install aiosqlite
# En .env:
# DATABASE_URL=sqlite+aiosqlite:///./milpin_dev.db
```
