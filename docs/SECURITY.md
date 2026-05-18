# Seguridad MILPÍN

## Deudas críticas activas

### 1. Credenciales en `.env` (ALTA)
`backend/.env` contiene password postgres en texto plano.
- Rotar contraseña inmediatamente en prod.
- Agregar `backend/.env` a `.gitignore`.
- Migrar a variables de entorno del sistema o secrets manager.

### 2. Path traversal en voz (ALTA)
`backend/API/voice_endpoint.py` usa el nombre de archivo del upload sin sanitizar:
```python
temp_path = f"temp_{audio_file.filename}"  # ← VULNERABLE
```
Fixes necesarios:
- Usar `uuid.uuid4()` como nombre de archivo temporal.
- Validar `content-type` (solo audio/*).
- Límite de tamaño de archivo (max 10MB).

### 3. CORS abierto (MEDIA)
`allow_origins=["*"]` en `backend/main.py`.
- Reemplazar por allowlist de dominios conocidos.

### 4. Sin autenticación (MEDIA)
`id_usuario` entra como UUID en body sin verificación.
- Implementar JWT o sesiones antes de exponer a internet.
