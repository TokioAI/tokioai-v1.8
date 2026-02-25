"""
Atlassian Tools - Herramientas para interactuar con la API de Atlassian (Jira y Confluence)
"""

import logging
import os
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Configuración de la API de Atlassian
ATLASSIAN_BASE_URL = os.getenv('ATLASSIAN_BASE_URL', 'https://api.atlassian.com')
ATLASSIAN_CLOUD_ID = os.getenv('ATLASSIAN_CLOUD_ID', '')
ATLASSIAN_ACCESS_TOKEN = os.getenv('ATLASSIAN_ACCESS_TOKEN', 'ATATT3xFfGF0Lnm3vgy5KmW6XrmtrRLuI7V7Hpha1i41swPpqTPRfI7DCjClbAQHmxvjaNQUIwyPvF6RXA_eEfYb2qIc5vDIZ5IOBSVBmcYemMTAgcEOv6ZbBrdvbu57l2ht-u6Nx1R7JeLlB3kVFAMnisq5_QsOaVQn0kVmT1JeeWZ84QVH-6w=41841964')
# Configuración para Basic Auth (email + API token)
ATLASSIAN_EMAIL = os.getenv('ATLASSIAN_EMAIL', 'jddieser@personal.com.ar')
ATLASSIAN_SITE_URL = os.getenv('ATLASSIAN_SITE_URL', 'https://tecocloud.atlassian.net')  # De tu ejemplo

# Configuración para el plugin de Jira de Cloud Valley
JIRA_PLUGIN_BASE_URL = os.getenv('JIRA_PLUGIN_BASE_URL', 'https://playground.cloudvalley.telecom.com.ar/api/jira-plugin')
JIRA_PLUGIN_TOKEN = os.getenv('JIRA_PLUGIN_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6ImN2MDAwMSIsInVzZXJJZCI6IjY3NmVhYTZkNDkzMTFmMDAxMjY3ZTc2OCIsImlhdCI6MTczNTMwNjgwMSwiZXhwIjoyNTM1MzQyODAxfQ.LRgBU9incB_d_i6--H2lHJq8uz77wcnnlAEC4TEzOWA')
JIRA_PLUGIN_ID = os.getenv('JIRA_PLUGIN_ID', '67583f0724dd4b17f865d9ed')

def _make_atlassian_request(method: str, endpoint: str, cloud_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API de Atlassian/Confluence"""
    
    # Si no se proporciona cloud_id, usar el de las variables de entorno
    if not cloud_id:
        cloud_id = ATLASSIAN_CLOUD_ID
    
    # Usar Basic Auth con email + token (más confiable que OAuth con API tokens)
    import base64
    auth_string = f"{ATLASSIAN_EMAIL}:{ATLASSIAN_ACCESS_TOKEN}"
    encoded = base64.b64encode(auth_string.encode()).decode()
    
    # Si tenemos cloud_id, usar la API vía api.atlassian.com
    # Si no, intentar directamente desde el sitio
    if cloud_id:
        # Construir URL base para Confluence
        # Formato: https://api.atlassian.com/ex/confluence/{cloud_id}/rest/api/...
        base_url = f"https://api.atlassian.com/ex/confluence/{cloud_id}/rest/api"
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        # Para OAuth, usar Bearer token
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {ATLASSIAN_ACCESS_TOKEN}'
        }
    else:
        # Intentar directamente desde el sitio usando Basic Auth
        # Formato Confluence: https://site.atlassian.net/wiki/rest/api/content/search
        site_url = ATLASSIAN_SITE_URL.rstrip('/')
        # Si el sitio termina en .net, asumir Confluence
        if site_url.endswith('.net'):
            url = f"{site_url}/wiki/rest/api/{endpoint.lstrip('/')}"
        else:
            url = f"{site_url}/rest/api/{endpoint.lstrip('/')}"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {encoded}'
        }
    
    # Actualizar headers si se proporcionan
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        del kwargs['headers']
    
    try:
        logger.debug(f"Realizando petición {method} a {url}")
        
        # Si estamos usando directamente el sitio (sin cloud_id), forzar sin proxy
        # El proxy bloquea conexiones a Atlassian
        if not cloud_id:
            proxies = {'http': None, 'https': None}
        else:
            # Atlassian puede estar bloqueado por proxy, intentar sin proxy por defecto
            # Si ATLASSIAN_USE_PROXY está configurado, usarlo
            USE_PROXY = os.getenv('ATLASSIAN_USE_PROXY', 'false').lower() == 'true'
            proxies = {
                'http': None,
                'https': None
            }
            if USE_PROXY:
                proxies = {
                    'http': os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080'),
                    'https': os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
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
        logger.error(f"Error HTTP en petición Atlassian: {e}")
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
        logger.error(f"Error en petición Atlassian: {e}")
        return {
            'success': False,
            'error': str(e),
            'status_code': None
        }


def _get_confluence_cloud_ids() -> List[str]:
    """Obtiene los cloud_ids de Confluence accesibles con el token"""
    try:
        headers = {
            'Authorization': f'Bearer {ATLASSIAN_ACCESS_TOKEN}',
            'Accept': 'application/json'
        }
        
        # Obtener los sites accesibles
        url = 'https://api.atlassian.com/oauth/token/accessible-resources'
        
        # Intentar sin proxy primero (Atlassian puede estar bloqueado por proxy)
        USE_PROXY = os.getenv('ATLASSIAN_USE_PROXY', 'false').lower() == 'true'
        proxies = {
            'http': None,
            'https': None
        }
        
        # Si está configurado para usar proxy, intentarlo
        if USE_PROXY or os.getenv('SOAR_USE_PROXY', 'false').lower() == 'true':
            proxies = {
                'http': os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080'),
                'https': os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
            }
        
        try:
            response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            
            if response.status_code == 200:
                resources = response.json()
                # Filtrar solo Confluence
                confluence_ids = [r.get('id') for r in resources if 'confluence' in [s.lower() for s in r.get('scopes', [])] or r.get('name', '').lower().find('confluence') >= 0]
                return confluence_ids if confluence_ids else [r.get('id') for r in resources[:1]]  # Si no hay Confluence específico, usar el primero
        except requests.exceptions.ProxyError:
            # Si el proxy falla, intentar sin proxy
            logger.warning("Proxy bloqueado para Atlassian, intentando sin proxy")
            proxies = {'http': None, 'https': None}
            response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            if response.status_code == 200:
                resources = response.json()
                confluence_ids = [r.get('id') for r in resources if 'confluence' in [s.lower() for s in r.get('scopes', [])] or r.get('name', '').lower().find('confluence') >= 0]
                return confluence_ids if confluence_ids else [r.get('id') for r in resources[:1]]
        return []
    except Exception as e:
        logger.warning(f"Error obteniendo cloud_ids: {e}")
        return []


async def tool_search_ip_in_confluence(ip: str, limit: int = 50, cloud_id: Optional[str] = None) -> Dict[str, Any]:
    """Busca una IP en las páginas, comentarios y contenido de Confluence
    
    Args:
        ip: IP a buscar
        limit: Límite de resultados
        cloud_id: Cloud ID de Atlassian (opcional, se obtiene automáticamente si no se proporciona)
    
    Returns:
        Dict con resultados de búsqueda en Confluence
    """
    try:
        logger.info(f"Buscando IP {ip} en Confluence")
        
        # Si no se proporciona cloud_id, intentar obtenerlo automáticamente
        # Pero no es crítico - _make_atlassian_request puede usar directamente el sitio
        if not cloud_id:
            cloud_id = ATLASSIAN_CLOUD_ID
            if not cloud_id:
                # Intentar obtenerlo, pero no fallar si no se puede
                # _make_atlassian_request usará directamente el sitio si cloud_id es None
                cloud_ids = _get_confluence_cloud_ids()
                if cloud_ids:
                    cloud_id = cloud_ids[0]
                    logger.info(f"Cloud ID obtenido automáticamente: {cloud_id}")
                else:
                    # Si no hay cloud_id, está bien - usaremos directamente el sitio
                    logger.info("No se obtuvo cloud_id, usando directamente el sitio")
                    cloud_id = None
        
        # Usar Content Search API de Confluence (CQL - Confluence Query Language)
        # Buscar en todo el contenido que contenga la IP
        cql_query = f'text ~ "{ip}" OR title ~ "{ip}"'
        
        # Usar el endpoint de búsqueda de contenido
        search_params = {
            'cql': cql_query,
            'limit': limit,
            'expand': 'space,version,body.storage'
        }
        
        result = _make_atlassian_request('GET', 'content/search', cloud_id=cloud_id, params=search_params)
        
        if result.get('success'):
            results = result.get('data', {}).get('results', [])
            
            # Formatear resultados
            formatted_results = []
            for item in results:
                formatted_results.append({
                    'id': item.get('id'),
                    'title': item.get('title'),
                    'type': item.get('type'),  # page, blogpost, etc.
                    'space_key': item.get('space', {}).get('key') if isinstance(item.get('space'), dict) else None,
                    'space_name': item.get('space', {}).get('name') if isinstance(item.get('space'), dict) else None,
                    'url': item.get('_links', {}).get('webui') if isinstance(item.get('_links'), dict) else None,
                    'excerpt': item.get('excerpt'),
                    'last_modified': item.get('version', {}).get('when') if isinstance(item.get('version'), dict) else None
                })
            
            result['data'] = {
                'ip': ip,
                'cloud_id': cloud_id,
                'results': formatted_results,
                'total': len(formatted_results)
            }
        
        return result
    except Exception as e:
        logger.error(f"Error buscando IP en Confluence: {e}")


# ============================================================================
# HERRAMIENTAS PARA EL PLUGIN DE JIRA DE CLOUD VALLEY
# ============================================================================

def _make_jira_plugin_request(method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API del plugin de Jira de Cloud Valley"""
    try:
        url = f"{JIRA_PLUGIN_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        
        headers = {
            'Authorization': f'Bearer {JIRA_PLUGIN_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Agregar pluginId a los parámetros si no está presente
        if params is None:
            params = {}
        if 'pluginId' not in params:
            params['pluginId'] = JIRA_PLUGIN_ID
        
        # Configurar proxy si es necesario
        USE_PROXY = os.getenv('JIRA_PLUGIN_USE_PROXY', 'true').lower() == 'true'
        proxies = None
        if USE_PROXY:
            http_proxy = os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
            https_proxy = os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
            proxies = {
                'http': http_proxy,
                'https': https_proxy
            }
        
        logger.debug(f"Realizando petición {method} a {url} con params={params}")
        
        # Intentar con proxy primero, luego sin proxy si falla
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, proxies=proxies, timeout=30, verify=False)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, params=params, json=json_data, proxies=proxies, timeout=30, verify=False)
            else:
                return {
                    'success': False,
                    'error': f'Método HTTP no soportado: {method}'
                }
            response.raise_for_status()
        except (requests.exceptions.ProxyError, requests.exceptions.SSLError) as e:
            # Si el proxy falla, intentar sin proxy
            logger.warning(f"Proxy bloqueado para Jira Plugin, intentando sin proxy: {e}")
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, proxies=None, timeout=30, verify=False)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, params=params, json=json_data, proxies=None, timeout=30, verify=False)
            response.raise_for_status()
        
        try:
            return {
                'success': True,
                'data': response.json()
            }
        except ValueError:
            return {
                'success': True,
                'data': response.text
            }
            
    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP en petición Jira Plugin: {e}")
        return {
            'success': False,
            'error': f'Error HTTP {e.response.status_code}: {e.response.text[:200]}'
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en petición Jira Plugin: {e}")
        return {
            'success': False,
            'error': str(e)
        }

        return {"success": False, "error": str(e)}


async def tool_search_content_in_confluence(query: str, content_type: Optional[str] = None, limit: int = 50, cloud_id: Optional[str] = None) -> Dict[str, Any]:
    """Busca contenido en Confluence usando CQL (Confluence Query Language)
    
    Args:
        query: Texto a buscar
        content_type: Tipo de contenido (page, blogpost, comment, etc.) - opcional
        limit: Límite de resultados
        cloud_id: Cloud ID de Atlassian (opcional, se obtiene automáticamente si no se proporciona)
    
    Returns:
        Dict con resultados de búsqueda
    """
    try:
        logger.info(f"Buscando en Confluence: {query}")
        
        # Si no se proporciona cloud_id, intentar obtenerlo automáticamente
        if not cloud_id:
            cloud_id = ATLASSIAN_CLOUD_ID
            if not cloud_id:
                cloud_ids = _get_confluence_cloud_ids()
                if cloud_ids:
                    cloud_id = cloud_ids[0]
                else:
                    logger.info("No se obtuvo cloud_id, usando directamente el sitio")
                    cloud_id = None
        
        # Construir CQL query
        cql_query = f'text ~ "{query}"'
        if content_type:
            cql_query += f' AND type = {content_type}'
        
        search_params = {
            'cql': cql_query,
            'limit': limit,
            'expand': 'space,version'
        }
        
        result = _make_atlassian_request('GET', 'content/search', cloud_id=cloud_id, params=search_params)
        
        if result.get('success'):
            results = result.get('data', {}).get('results', [])
            result['data'] = {
                'query': query,
                'cloud_id': cloud_id,
                'results': results,
                'total': len(results)
            }
        
        return result
    except Exception as e:
        logger.error(f"Error buscando contenido en Confluence: {e}")
        return {"success": False, "error": str(e)}


def _get_cloud_id_from_site() -> Optional[str]:
    """Obtiene el cloud_id directamente desde el sitio de Atlassian usando Basic Auth
    
    Si Basic Auth funciona pero no devuelve cloud_id, retorna None
    porque podemos usar directamente el sitio sin cloud_id
    """
    try:
        import base64
        import re
        
        # Usar Basic Auth con email + API token
        auth_string = f"{ATLASSIAN_EMAIL}:{ATLASSIAN_ACCESS_TOKEN}"
        encoded = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {encoded}',
            'Accept': 'application/json'
        }
        
        proxies = {'http': None, 'https': None}
        
        # Intentar obtener serverInfo desde el sitio
        site_url = ATLASSIAN_SITE_URL.rstrip('/')
        url = f"{site_url}/rest/api/3/serverInfo"
        
        logger.info(f"Verificando conexión a {site_url}...")
        
        response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            base_url = data.get('baseUrl', '')
            
            # Si el baseUrl contiene /ex/jira/{cloud_id}/, extraerlo
            # Si no, retornar None porque podemos usar directamente el sitio
            match = re.search(r'/ex/jira/([a-f0-9-]+)', base_url)
            if match:
                cloud_id = match.group(1)
                logger.info(f"Cloud ID obtenido: {cloud_id}")
                return cloud_id
            else:
                logger.info(f"Conexión exitosa a {site_url}, usando directamente el sitio (sin cloud_id)")
                return None  # Podemos usar directamente el sitio
        
        return None
    except Exception as e:
        logger.warning(f"Error verificando conexión al sitio: {e}")
        return None


def _get_jira_cloud_ids() -> List[str]:
    """Obtiene los cloud_ids de Jira accesibles con el token"""
    # Primero intentar obtener desde el sitio directamente (más confiable con Basic Auth)
    cloud_id_from_site = _get_cloud_id_from_site()
    if cloud_id_from_site:
        return [cloud_id_from_site]
    
    # Si no funciona, intentar con OAuth
    try:
        headers = {
            'Authorization': f'Bearer {ATLASSIAN_ACCESS_TOKEN}',
            'Accept': 'application/json'
        }
        
        url = 'https://api.atlassian.com/oauth/token/accessible-resources'
        
        # Intentar sin proxy primero (Atlassian puede estar bloqueado por proxy)
        USE_PROXY = os.getenv('ATLASSIAN_USE_PROXY', 'false').lower() == 'true'
        proxies = {
            'http': None,
            'https': None
        }
        
        if USE_PROXY or os.getenv('SOAR_USE_PROXY', 'false').lower() == 'true':
            proxies = {
                'http': os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080'),
                'https': os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
            }
        
        try:
            response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            
            if response.status_code == 200:
                resources = response.json()
                # Filtrar solo Jira
                jira_ids = [r.get('id') for r in resources if 'jira' in [s.lower() for s in r.get('scopes', [])] or r.get('name', '').lower().find('jira') >= 0]
                return jira_ids if jira_ids else [r.get('id') for r in resources[:1]]
        except requests.exceptions.ProxyError:
            proxies = {'http': None, 'https': None}
            response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            if response.status_code == 200:
                resources = response.json()
                jira_ids = [r.get('id') for r in resources if 'jira' in [s.lower() for s in r.get('scopes', [])] or r.get('name', '').lower().find('jira') >= 0]
                return jira_ids if jira_ids else [r.get('id') for r in resources[:1]]
        return []
    except Exception as e:
        logger.warning(f"Error obteniendo cloud_ids de Jira: {e}")
        return []


def _make_jira_request(method: str, endpoint: str, cloud_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API de Jira"""
    
    if not cloud_id:
        cloud_id = ATLASSIAN_CLOUD_ID
    
    # Si no tenemos cloud_id, intentar obtenerlo automáticamente
    if not cloud_id:
        cloud_id = _get_cloud_id_from_site()
        if cloud_id:
            logger.info(f"Cloud ID obtenido automáticamente: {cloud_id}")
    
    # Usar Basic Auth con email + token (más confiable que OAuth con API tokens)
    import base64
    auth_string = f"{ATLASSIAN_EMAIL}:{ATLASSIAN_ACCESS_TOKEN}"
    encoded = base64.b64encode(auth_string.encode()).decode()
    
    # Si tenemos cloud_id, usar la API vía api.atlassian.com
    # Si no, intentar directamente desde el sitio
    if cloud_id:
        # Formato: https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/...
        base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        # Para OAuth, usar Bearer token
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {ATLASSIAN_ACCESS_TOKEN}'
        }
    else:
        # Intentar directamente desde el sitio usando Basic Auth
        site_url = ATLASSIAN_SITE_URL.rstrip('/')
        url = f"{site_url}/rest/api/3/{endpoint.lstrip('/')}"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {encoded}'
        }
    
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        del kwargs['headers']
    
    try:
        logger.debug(f"Realizando petición {method} a {url}")
        
        # Si estamos usando directamente el sitio (sin cloud_id), forzar sin proxy
        # El proxy bloquea conexiones a Atlassian
        if not cloud_id:
            proxies = {'http': None, 'https': None}
        else:
            USE_PROXY = os.getenv('ATLASSIAN_USE_PROXY', 'false').lower() == 'true'
            proxies = {
                'http': None,
                'https': None
            }
            if USE_PROXY:
                proxies = {
                    'http': os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080'),
                    'https': os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
                }
        
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            proxies=proxies,
            verify=False,
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
        logger.error(f"Error HTTP en petición Jira: {e}")
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
        logger.error(f"Error en petición Jira: {e}")
        return {
            'success': False,
            'error': str(e),
            'status_code': None
        }


async def tool_search_ip_in_jira(
    ip: str, 
    limit: int = 50, 
    cloud_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search_all_history: bool = False
) -> Dict[str, Any]:
    """Busca una IP en los issues de Jira (summary, description, comments, etc.)
    
    Args:
        ip: IP a buscar
        limit: Límite de resultados
        cloud_id: Cloud ID de Atlassian (opcional, se obtiene automáticamente si no se proporciona)
        start_date: Fecha de inicio en formato YYYY-MM-DD (opcional). Si no se proporciona, usa una fecha por defecto.
        end_date: Fecha de fin en formato YYYY-MM-DD (opcional). Si no se proporciona, usa la fecha actual.
        search_all_history: Si es True, busca en todo el historial sin restricciones de fecha (último recurso)
    
    Returns:
        Dict con resultados de búsqueda en Jira
    """
    try:
        logger.info(f"Buscando IP {ip} en Jira")
        
        # Si no se proporciona cloud_id, intentar obtenerlo automáticamente
        # Pero no es crítico - _make_jira_request puede usar directamente el sitio
        if not cloud_id:
            cloud_id = ATLASSIAN_CLOUD_ID
            if not cloud_id:
                # Intentar obtenerlo, pero no fallar si no se puede
                # _make_jira_request usará directamente el sitio si cloud_id es None
                cloud_id = _get_cloud_id_from_site()
                if cloud_id:
                    logger.info(f"Cloud ID de Jira obtenido automáticamente: {cloud_id}")
                else:
                    # Si no hay cloud_id, está bien - usaremos directamente el sitio
                    logger.info("No se obtuvo cloud_id, usando directamente el sitio")
                    cloud_id = None
        
        # Usar JQL (Jira Query Language) para buscar la IP
        # Buscar en summary, description, comments, y campos de texto personalizados
        # Jira requiere restricciones en las búsquedas, así que agregamos restricciones de fecha
        # El operador ~ busca "contains" en Jira
        
        # Determinar rango de fechas
        if start_date:
            # Validar formato de fecha
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                start_date_str = start_dt.strftime('%Y-%m-%d')
            except ValueError:
                logger.warning(f"Formato de fecha inválido para start_date: {start_date}, usando fecha por defecto")
                start_date_str = None
        else:
            start_date_str = None
        
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                end_date_str = end_dt.strftime('%Y-%m-%d')
            except ValueError:
                logger.warning(f"Formato de fecha inválido para end_date: {end_date}, usando fecha actual")
                end_date_str = None
        else:
            end_date_str = None
        
        # Si no se proporcionó start_date, usar una fecha por defecto (16 de enero del año actual o pasado)
        if not start_date_str:
            current_year = datetime.now().year
            jan_16 = datetime(current_year, 1, 16)
            # Si ya pasó el 16 de enero, usar el del año actual, sino el del año pasado
            if datetime.now() < jan_16:
                jan_16 = datetime(current_year - 1, 1, 16)
            start_date_str = jan_16.strftime('%Y-%m-%d')
        
        # Si no se proporcionó end_date, usar fecha actual
        if not end_date_str:
            end_date_str = datetime.now().strftime('%Y-%m-%d')
        
        # Construir queries JQL con diferentes estrategias
        jql_queries = []
        
        # Construir condición de búsqueda de IP
        ip_search_condition = f'(text ~ "{ip}" OR summary ~ "{ip}" OR description ~ "{ip}" OR comment ~ "{ip}")'
        
        # Construir condición de fecha para rango
        if start_date_str and end_date_str:
            date_condition_updated = f'updated >= "{start_date_str}" AND updated <= "{end_date_str}"'
            date_condition_created = f'created >= "{start_date_str}" AND created <= "{end_date_str}"'
        elif start_date_str:
            date_condition_updated = f'updated >= "{start_date_str}"'
            date_condition_created = f'created >= "{start_date_str}"'
        else:
            date_condition_updated = None
            date_condition_created = None
        
        # Si search_all_history es True, agregar query sin restricciones de fecha al final
        if not search_all_history:
            # Query con rango de fechas específico usando updated
            if date_condition_updated:
                jql_queries.append(f'{ip_search_condition} AND {date_condition_updated} ORDER BY updated DESC')
            
            # Query con rango de fechas específico usando created
            if date_condition_created:
                jql_queries.append(f'{ip_search_condition} AND {date_condition_created} ORDER BY created DESC')
            
            # Query con restricción relativa (último año)
            jql_queries.append(f'{ip_search_condition} AND updated >= -1y ORDER BY updated DESC')
            
            # Query con restricción relativa (últimos 6 meses)
            jql_queries.append(f'{ip_search_condition} AND updated >= -6M ORDER BY updated DESC')
            
            # Query con restricción relativa (último mes)
            jql_queries.append(f'{ip_search_condition} AND updated >= -1M ORDER BY updated DESC')
        else:
            # Si search_all_history es True, primero intentar queries con restricciones amplias
            # Query con restricción muy amplia (últimos 2 años)
            jql_queries.append(f'{ip_search_condition} AND updated >= -2y ORDER BY updated DESC')
            jql_queries.append(f'{ip_search_condition} AND created >= -2y ORDER BY created DESC')
            
            # Luego intentar sin restricciones (último recurso - puede fallar por políticas de Jira)
            jql_queries.append(f'{ip_search_condition} ORDER BY updated DESC')
        
        # Agregar queries con fragmentos de IP si no encontramos nada
        ip_parts = ip.split('.')
        if len(ip_parts) >= 2:
            ip_last_octets = '.'.join(ip_parts[-2:])
            if date_condition_updated:
                jql_queries.append(f'(text ~ "{ip_last_octets}" OR summary ~ "{ip_last_octets}" OR description ~ "{ip_last_octets}") AND {date_condition_updated} ORDER BY updated DESC')
        
        # Probar con diferentes queries hasta encontrar uno que funcione
        result = None
        for idx, jql_query in enumerate(jql_queries, 1):
            logger.info(f"Probando query Jira {idx}/{len(jql_queries)}: {jql_query[:100]}...")
            
            search_params = {
                'jql': jql_query,
                'maxResults': limit,
                'fields': 'summary,description,status,assignee,reporter,created,updated,comment,issuetype,project',
                'expand': 'changelog,renderedFields'
            }
            
            result = _make_jira_request('GET', 'search/jql', cloud_id=cloud_id, params=search_params)
            
            # Si el query funcionó (éxito o encontró resultados), usarlo
            if result.get('success'):
                data = result.get('data', {})
                total = data.get('total', 0)
                if total > 0:
                    logger.info(f"✅ Query {idx} encontró {total} issue(s)!")
                    break
                else:
                    logger.info(f"ℹ️  Query {idx} funcionó pero encontró 0 resultados")
            # Si el error no es sobre restricciones, continuar probando
            error_detail = result.get('error_detail', {})
            if error_detail and 'errorMessages' in error_detail:
                error_msg = ' '.join(error_detail['errorMessages']).lower()
                if 'restricción' not in error_msg and 'restriction' not in error_msg:
                    # Si el error no es sobre restricciones, puede ser otro problema, continuar
                    logger.info(f"⚠️  Query {idx} falló: {error_msg[:100]}")
                    continue
        
        # Si ningún query funcionó, usar el primero como último recurso
        if not result or not result.get('success'):
            jql_query = jql_queries[0]
            search_params = {
                'jql': jql_query,
                'maxResults': limit,
                'fields': 'summary,description,status,assignee,reporter,created,updated,comment,issuetype,project',
                'expand': 'changelog'
            }
            result = _make_jira_request('GET', 'search/jql', cloud_id=cloud_id, params=search_params)
        
        if result.get('success'):
            issues = result.get('data', {}).get('issues', [])
            total = result.get('data', {}).get('total', len(issues))
            
            # Si no encontramos resultados, puede ser un problema de permisos
            # La búsqueda web de Jira puede encontrar issues que el token de API no puede ver
            if total == 0:
                logger.warning("⚠️  No se encontraron issues. Esto puede deberse a:")
                logger.warning("   1. La IP no está en issues de Jira accesibles con este token")
                logger.warning("   2. El token de API no tiene permisos para acceder a ciertos proyectos")
                logger.warning("   3. La IP está en campos o proyectos que requieren permisos adicionales")
                logger.warning("   Sugerencia: Verificar permisos del token de API o buscar manualmente en la web")
            
            # Formatear resultados
            formatted_results = []
            for issue in issues:
                fields = issue.get('fields', {})
                formatted_results.append({
                    'key': issue.get('key'),  # Ej: PROJ-123
                    'summary': fields.get('summary'),
                    'description': fields.get('description'),
                    'status': fields.get('status', {}).get('name') if isinstance(fields.get('status'), dict) else None,
                    'assignee': fields.get('assignee', {}).get('displayName') if isinstance(fields.get('assignee'), dict) else None,
                    'reporter': fields.get('reporter', {}).get('displayName') if isinstance(fields.get('reporter'), dict) else None,
                    'issuetype': fields.get('issuetype', {}).get('name') if isinstance(fields.get('issuetype'), dict) else None,
                    'project': fields.get('project', {}).get('key') if isinstance(fields.get('project'), dict) else None,
                    'created': fields.get('created'),
                    'updated': fields.get('updated'),
                    'url': f"https://api.atlassian.com/ex/jira/{cloud_id}/browse/{issue.get('key')}" if cloud_id else f"{ATLASSIAN_SITE_URL.rstrip('/')}/browse/{issue.get('key')}",
                    'comments_count': len(fields.get('comment', {}).get('comments', [])) if isinstance(fields.get('comment'), dict) else 0
                })
            
            result['data'] = {
                'ip': ip,
                'cloud_id': cloud_id,
                'results': formatted_results,
                'total': result.get('data', {}).get('total', len(formatted_results))
            }
        
        return result
    except Exception as e:
        logger.error(f"Error buscando IP en Jira: {e}")
        return {"success": False, "error": str(e)}


async def tool_search_jira_issues(query: str, project: Optional[str] = None, limit: int = 50, cloud_id: Optional[str] = None) -> Dict[str, Any]:
    """Busca issues en Jira usando JQL (Jira Query Language)
    
    Args:
        query: Texto a buscar
        project: Clave del proyecto (opcional, ej: "PROJ")
        limit: Límite de resultados
        cloud_id: Cloud ID de Atlassian (opcional, se obtiene automáticamente si no se proporciona)
    
    Returns:
        Dict con resultados de búsqueda
    """
    try:
        logger.info(f"Buscando en Jira: {query}")
        
        if not cloud_id:
            cloud_id = ATLASSIAN_CLOUD_ID
            if not cloud_id:
                cloud_id = _get_cloud_id_from_site()
                if not cloud_id:
                    logger.info("No se obtuvo cloud_id, usando directamente el sitio")
                    cloud_id = None
        
        # Construir JQL query
        jql_query = f'text ~ "{query}"'
        if project:
            jql_query = f'project = {project} AND ({jql_query})'
        
        search_params = {
            'jql': jql_query,
            'maxResults': limit,
            'fields': 'summary,description,status,assignee,reporter,created,updated,issuetype,project',
            'expand': 'changelog'
        }
        
        result = _make_jira_request('GET', 'search/jql', cloud_id=cloud_id, params=search_params)
        
        if result.get('success'):
            issues = result.get('data', {}).get('issues', [])
            result['data'] = {
                'query': query,
                'cloud_id': cloud_id,
                'results': issues,
                'total': result.get('data', {}).get('total', len(issues))
            }
        
        return result
    except Exception as e:
        logger.error(f"Error buscando issues en Jira: {e}")
        return {"success": False, "error": str(e)}

# ============================================================================
# HERRAMIENTAS PARA EL PLUGIN DE JIRA DE CLOUD VALLEY
# ============================================================================

def _make_jira_plugin_request(method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API del plugin de Jira de Cloud Valley"""
    try:
        url = f"{JIRA_PLUGIN_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        
        headers = {
            "Authorization": f"Bearer {JIRA_PLUGIN_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Agregar pluginId a los parámetros si no está presente
        if params is None:
            params = {}
        if "pluginId" not in params:
            params["pluginId"] = JIRA_PLUGIN_ID
        
        # Configurar proxy si es necesario
        USE_PROXY = os.getenv("JIRA_PLUGIN_USE_PROXY", "true").lower() == "true"
        proxies = None
        if USE_PROXY:
            http_proxy = os.getenv("http_proxy", "http://proxyappl.telecom.arg.telecom.com.ar:8080")
            https_proxy = os.getenv("https_proxy", "http://proxyappl.telecom.arg.telecom.com.ar:8080")
            proxies = {
                "http": http_proxy,
                "https": https_proxy
            }
        
        logger.debug(f"Realizando petición {method} a {url} con params={params}")
        
        # Intentar con proxy primero, luego sin proxy si falla
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, proxies=proxies, timeout=30, verify=False)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, params=params, json=json_data, proxies=proxies, timeout=30, verify=False)
            else:
                return {
                    "success": False,
                    "error": f"Método HTTP no soportado: {method}"
                }
            response.raise_for_status()
        except (requests.exceptions.ProxyError, requests.exceptions.SSLError) as e:
            # Si el proxy falla, intentar sin proxy
            logger.warning(f"Proxy bloqueado para Jira Plugin, intentando sin proxy: {e}")
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, proxies=None, timeout=30, verify=False)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, params=params, json=json_data, proxies=None, timeout=30, verify=False)
            response.raise_for_status()
        
        try:
            return {
                "success": True,
                "data": response.json()
            }
        except ValueError:
            return {
                "success": True,
                "data": response.text
            }
            
    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP en petición Jira Plugin: {e}")
        return {
            "success": False,
            "error": f"Error HTTP {e.response.status_code}: {e.response.text[:200]}"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en petición Jira Plugin: {e}")
        return {
            "success": False,
            "error": str(e)
        }



async def tool_search_jira_sandbox(
    search_term: Optional[str] = None,
    ip: Optional[str] = None,
    domain: Optional[str] = None,
    issue_key: Optional[str] = None,
    limit: int = 50,
    start_from: int = 4000
) -> Dict[str, Any]:
    """Busca IPs, dominios o texto en issues de Jira Sandbox usando el plugin de Cloud Valley.
    
    Esta herramienta permite buscar información en Jira Sandbox de manera exhaustiva:
    - Buscar por IP específica
    - Buscar por dominio
    - Buscar por texto en summary/description
    - Obtener un issue específico por clave
    
    Args:
        search_term: Texto a buscar en summary/description (opcional)
        ip: IP específica a buscar (opcional)
        domain: Dominio específico a buscar (opcional)
        issue_key: Clave de issue específico a obtener (ej: ACNT-4057) (opcional)
        limit: Número máximo de issues a revisar (default: 50)
        start_from: Número de issue desde donde empezar a buscar (default: 4000)
    
    Returns:
        Dict con resultados de la búsqueda incluyendo IPs, dominios y issues encontrados
    """
    import re
    
    try:
        logger.info(f"Buscando en Jira Sandbox: search_term={search_term}, ip={ip}, domain={domain}, issue_key={issue_key}")
        
        def extract_text_from_adf(node):
            text = ""
            if isinstance(node, dict):
                if node.get('type') == 'text':
                    text += node.get('text', '')
                if 'content' in node:
                    for child in node.get('content', []):
                        text += extract_text_from_adf(child)
            return text
        
        def buscar_ips_y_dominios(texto):
            """Busca IPs y dominios en un texto"""
            # Buscar IPs
            ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', texto)
            ips_validas = []
            for ip in ips:
                parts = ip.split('.')
                if len(parts) == 4:
                    try:
                        if all(0 <= int(p) <= 255 for p in parts):
                            if ip not in ['YOUR_IP_ADDRESS', 'YOUR_IP_ADDRESS', 'YOUR_IP_ADDRESS']:
                                ips_validas.append(ip)
                    except:
                        pass
            
            # Buscar dominios (filtrando comunes de Jira/Atlassian)
            dominios = re.findall(r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b', texto)
            dominios_filtrados = []
            for dominio in dominios:
                dominio_lower = dominio.lower()
                if not any(x in dominio_lower for x in ['atlassian.net', 'gravatar.com', 'avatar-management', 'schema.org', 'w3.org']):
                    if len(dominio) > 4 and '.' in dominio and not dominio.startswith('2F'):
                        dominios_filtrados.append(dominio)
            
            return list(set(ips_validas)), list(set(dominios_filtrados))
        
        resultados = {
            'issues_revisados': 0,
            'issues_encontrados': [],
            'ips_encontradas': {},
            'dominios_encontrados': {},
            'issues_con_datos': []
        }
        
        # Si se especifica un issue_key, obtener solo ese
        if issue_key:
            result = _make_jira_plugin_request('GET', 'issue', params={'issueIdOrKey': issue_key})
            if result.get('success'):
                data = result.get('data', {})
                issue_data = data.get('data', data)
                if isinstance(issue_data, dict):
                    key = issue_data.get('key', 'N/A')
                    summary = issue_data.get('fields', {}).get('summary', '')
                    description = issue_data.get('fields', {}).get('description', '')
                    
                    desc_text = ""
                    if isinstance(description, dict):
                        desc_text = extract_text_from_adf(description)
                    elif isinstance(description, str):
                        desc_text = description
                    else:
                        desc_text = str(description)
                    
                    texto_completo = f"{summary} {desc_text}"
                    
                    # Buscar IPs y dominios
                    ips, dominios = buscar_ips_y_dominios(texto_completo)
                    
                    issue_info = {
                        'key': key,
                        'summary': summary,
                        'description_preview': desc_text[:200],
                        'ips': ips,
                        'domains': dominios
                    }
                    
                    # Verificar si coincide con los criterios de búsqueda
                    coincide = True
                    if ip and ip not in texto_completo:
                        coincide = False
                    if domain and domain.lower() not in texto_completo.lower():
                        coincide = False
                    if search_term and search_term.lower() not in texto_completo.lower():
                        coincide = False
                    
                    if coincide:
                        resultados['issues_encontrados'].append(issue_info)
                        resultados['issues_revisados'] = 1
                        
                        for ip_found in ips:
                            if ip_found not in resultados['ips_encontradas']:
                                resultados['ips_encontradas'][ip_found] = []
                            resultados['ips_encontradas'][ip_found].append(key)
                        
                        for dominio in dominios:
                            if dominio not in resultados['dominios_encontrados']:
                                resultados['dominios_encontrados'][dominio] = []
                            resultados['dominios_encontrados'][dominio].append(key)
            
            return {
                'success': True,
                'data': resultados
            }
        
        # Buscar en un rango de issues
        end_at = start_from + limit
        issues_a_revisar = [f'ACNT-{i}' for i in range(start_from, end_at)]
        
        for issue_key in issues_a_revisar:
            resultados['issues_revisados'] += 1
            
            result = _make_jira_plugin_request('GET', 'issue', params={'issueIdOrKey': issue_key})
            
            if result.get('success'):
                data = result.get('data', {})
                issue_data = data.get('data', data)
                
                if isinstance(issue_data, dict):
                    key = issue_data.get('key', 'N/A')
                    summary = issue_data.get('fields', {}).get('summary', '')
                    description = issue_data.get('fields', {}).get('description', '')
                    
                    desc_text = ""
                    if isinstance(description, dict):
                        desc_text = extract_text_from_adf(description)
                    elif isinstance(description, str):
                        desc_text = description
                    else:
                        desc_text = str(description)
                    
                    texto_completo = f"{summary} {desc_text}"
                    
                    # Verificar criterios de búsqueda
                    coincide = True
                    if ip and ip not in texto_completo:
                        coincide = False
                    if domain and domain.lower() not in texto_completo.lower():
                        coincide = False
                    if search_term and search_term.lower() not in texto_completo.lower():
                        coincide = False
                    
                    if coincide or not (ip or domain or search_term):  # Si no hay filtros, mostrar todos
                        # Buscar IPs y dominios
                        ips, dominios = buscar_ips_y_dominios(texto_completo)
                        
                        issue_info = {
                            'key': key,
                            'summary': summary[:100],
                            'ips': ips,
                            'domains': dominios
                        }
                        
                        resultados['issues_encontrados'].append(issue_info)
                        
                        for ip_found in ips:
                            if ip_found not in resultados['ips_encontradas']:
                                resultados['ips_encontradas'][ip_found] = []
                            resultados['ips_encontradas'][ip_found].append(key)
                        
                        for dominio in dominios:
                            if dominio not in resultados['dominios_encontrados']:
                                resultados['dominios_encontrados'][dominio] = []
                            resultados['dominios_encontrados'][dominio].append(key)
        
        return {
            'success': True,
            'data': resultados
        }
        
    except Exception as e:
        logger.error(f"Error buscando en Jira Sandbox: {e}")
        return {
            'success': False,
            'error': str(e)
        }
