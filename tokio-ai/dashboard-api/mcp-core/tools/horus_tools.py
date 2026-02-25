"""
Horus Tools - Herramientas para interactuar con la API de Horus (CS-Horus-API)
"""

import logging
import os
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configuración de la API de Horus
HORUS_API_BASE = os.getenv('HORUS_API_BASE', 'https://cs-horus-api.telecom.com.ar:3000/api/v1')
HORUS_API_TOKEN = os.getenv('HORUS_API_TOKEN', 'SVJUQzowMDQ5YTljNDk3YzY3YzljZGNhMWMwMzVjYTgyYzhiZDdiNjcxYWU4NGJhYzgxNjg2YWEwZjVjZTUyYmNlZTAw')

def _make_horus_request(method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API de Horus"""
    url = f"{HORUS_API_BASE.rstrip('/')}/{endpoint.lstrip('/')}"
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {HORUS_API_TOKEN}'
    }
    
    # Actualizar headers si se proporcionan
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        del kwargs['headers']
    
    try:
        logger.debug(f"Realizando petición {method} a {url}")
        
        # Horus está en la red interna, NO usar proxy (el proxy bloquea con 403)
        # Forzar conexión directa
        proxies = {
            'http': None,
            'https': None
        }
        
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            proxies=proxies,
            verify=False,  # Certificados internos
            timeout=30,
            **kwargs
        )
        
        logger.debug(f"Respuesta: {response.status_code}")
        response.raise_for_status()
        
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {'raw_response': response.text}
        
        return {
            'success': True,
            'data': data,
            'status_code': response.status_code
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP en petición Horus: {e}")
        error_detail = {}
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
            except:
                error_detail = {'message': e.response.text}
        
        return {
            'success': False,
            'error': str(e),
            'error_detail': error_detail,
            'status_code': e.response.status_code if hasattr(e, 'response') and e.response else None
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en petición Horus: {e}")
        return {
            'success': False,
            'error': str(e),
            'status_code': None
        }


async def tool_get_ip_info(ip_or_hostname: str) -> Dict[str, Any]:
    """Obtiene información de aseguramientos de una IP o hostname desde la API de Horus
    
    Args:
        ip_or_hostname: IP o hostname a consultar
    
    Returns:
        Dict con información de aseguramientos o error
    """
    try:
        logger.info(f"Obteniendo información de Horus para: {ip_or_hostname}")
        
        result = _make_horus_request('GET', f'aseguramientos/{ip_or_hostname}')
        return result
    except Exception as e:
        logger.error(f"Error obteniendo info de Horus: {e}")
        return {"success": False, "error": str(e)}
