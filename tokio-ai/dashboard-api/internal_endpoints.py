"""
Endpoints internos para que el MCP server consulte PostgreSQL
a través del dashboard API (que sí puede usar el socket Unix de Cloud SQL)
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Optional
import logging
# Importar funciones de conexión de app.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import _get_postgres_conn, _return_postgres_conn
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

async def internal_search_waf_logs(
    request: Request,
    ip: Optional[str] = None,
    pattern: Optional[str] = None,
    url_pattern: Optional[str] = None,
    host: Optional[str] = None,
    days: int = 7,
    limit: int = 100
):
    """
    Endpoint interno para que el MCP server consulte logs de WAF.
    Usa la conexión de PostgreSQL del dashboard API (que funciona con socket Unix).
    """
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL", "logs": []}
            )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                id, timestamp, ip, method, uri, status, blocked, 
                threat_type, severity, created_at, tenant_id, raw_log
            FROM waf_logs
            WHERE created_at > NOW() - INTERVAL %s
        """
        params = [f'{days} days']
        
        if ip:
            query += " AND ip = %s"
            params.append(ip)
        
        if host:
            query += " AND host ILIKE %s"
            params.append(f"%{host}%")
        
        if url_pattern:
            query += " AND uri ILIKE %s"
            params.append(f"%{url_pattern}%")
        elif pattern:
            query += " AND (uri ILIKE %s OR raw_log::text ILIKE %s)"
            params.extend([f"%{pattern}%", f"%{pattern}%"])
        
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        logs = [dict(row) for row in cursor.fetchall()]
        
        # Convertir datetime a string
        for log in logs:
            for key in ['timestamp', 'created_at']:
                if log.get(key) and hasattr(log[key], 'isoformat'):
                    log[key] = log[key].isoformat()
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return JSONResponse(content={
            "success": True,
            "logs": logs,
            "count": len(logs),
            "message": f"Encontrados {len(logs)} logs de WAF"
        })
    except Exception as e:
        logger.error(f"Error en internal_search_waf_logs: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "logs": []}
        )
