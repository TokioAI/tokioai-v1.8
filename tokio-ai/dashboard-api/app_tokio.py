#!/usr/bin/env python3
"""
Dashboard API - Tokio AI
Versión simplificada con endpoints esenciales y CLI integrado

Este archivo extiende el app.py original agregando endpoints adicionales.
Para usar, simplemente importa este módulo en lugar de app.py
"""

# Importar el app.py original
import sys
import os

# Agregar el directorio del dashboard-api original al path
original_dashboard_path = os.path.join(os.path.dirname(__file__), '..', '..', 'dashboard-api')
if os.path.exists(original_dashboard_path):
    sys.path.insert(0, original_dashboard_path)

# Intentar importar app original, si no existe, crear uno básico
try:
    from app import app
    from db import get_postgres_connection
except ImportError:
    # Si no existe el app.py original, crear uno básico
    from fastapi import FastAPI
    app = FastAPI(title="Tokio AI - Dashboard API")
    def get_postgres_connection():
        import psycopg2
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DB", "soc_ai"),
            user=os.getenv("POSTGRES_USER", "soc_user"),
            password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))
        )

# Importar endpoints CLI
try:
    from endpoints_cli import execute_cli_command, create_tenant
except ImportError:
    # Si no existe, crear funciones básicas
    async def execute_cli_command(request):
        return {"success": False, "error": "CLI endpoints no disponibles"}
    async def create_tenant(request):
        return {"success": False, "error": "Tenant creation no disponible"}

from fastapi import Body
from fastapi.responses import JSONResponse

# Registrar endpoints adicionales (solo si no existen)
if not any(route.path == "/api/cli/execute" for route in app.routes):
    @app.post("/api/cli/execute", response_class=JSONResponse)
    async def cli_execute(request: dict = Body(...)):
        """Ejecuta un comando CLI"""
        return await execute_cli_command(request)

# Reemplazar endpoint POST /api/tenants si existe, o agregarlo
existing_tenant_post = [r for r in app.routes if r.path == "/api/tenants" and hasattr(r, 'methods') and 'POST' in r.methods]
if existing_tenant_post:
    # Remover endpoint existente
    app.routes = [r for r in app.routes if not (r.path == "/api/tenants" and hasattr(r, 'methods') and 'POST' in r.methods)]

@app.post("/api/tenants", response_class=JSONResponse)
async def create_tenant_endpoint(request: dict = Body(...)):
    """Crea un nuevo tenant"""
    return await create_tenant(request)

# El resto de los endpoints ya están en app.py original
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="YOUR_IP_ADDRESS", port=8000)
