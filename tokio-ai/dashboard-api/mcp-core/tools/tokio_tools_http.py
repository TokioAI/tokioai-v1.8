"""
Versión HTTP de las tools de Tokio AI
Usa endpoints internos del dashboard API para consultar PostgreSQL
"""
import logging
import os
import urllib.parse
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Intentar importar aiohttp, si no está disponible usar requests
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    try:
        import requests
        HAS_REQUESTS = True
    except ImportError:
        HAS_REQUESTS = False

async def tool_search_waf_logs_tokio_http(
    ip: Optional[str] = None,
    pattern: Optional[str] = None,
    url_pattern: Optional[str] = None,
    host: Optional[str] = None,
    days: int = 7,
    limit: int = 100
) -> Dict[str, Any]:
    """Busca logs de WAF usando endpoint interno del dashboard API"""
    try:
        # Obtener URL base del dashboard API
        port = os.getenv('PORT', '8080')
        dashboard_url = f'http://localhost:{port}'
        
        # Construir URL con parámetros
        params = {
            'days': days,
            'limit': limit
        }
        if ip:
            params['ip'] = ip
        if pattern:
            params['pattern'] = pattern
        if url_pattern:
            params['url_pattern'] = url_pattern
        if host:
            params['host'] = host
        
        url = f"{dashboard_url}/api/internal/search-waf-logs?" + urllib.parse.urlencode(params)
        
        # Hacer petición HTTP al endpoint interno
        if HAS_AIOHTTP:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result
                    else:
                        error_text = await response.text()
                        logger.error(f"Error en endpoint interno: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"Error del endpoint interno: {response.status} - {error_text}",
                            "logs": []
                        }
        elif HAS_REQUESTS:
            response = requests.post(url, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error en endpoint interno: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"Error del endpoint interno: {response.status_code} - {response.text}",
                    "logs": []
                }
        else:
            return {
                "success": False,
                "error": "No hay librerías HTTP disponibles (aiohttp o requests)",
                "logs": []
            }
    except Exception as e:
        logger.error(f"Error buscando logs WAF vía HTTP: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error: {str(e)}",
            "logs": []
        }
