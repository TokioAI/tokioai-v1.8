"""
SOAR Tools - Herramientas para interactuar con la API de SOAR (incidentes)
"""

import logging
import os
import requests
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Configurar proxy para requests
# Permitir deshabilitar proxy para SOAR si está bloqueado
USE_PROXY_FOR_SOAR = os.getenv('SOAR_USE_PROXY', 'false').lower() == 'true'
PROXY_CONFIG = {
    'http': os.getenv('http_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080'),
    'https': os.getenv('https_proxy', 'http://proxyappl.telecom.arg.telecom.com.ar:8080')
} if USE_PROXY_FOR_SOAR else None

# Mapeo oficial de Códigos de Tipo de Incidente
# Estos códigos se usan para filtrar incidentes por tipo
INCIDENT_TYPE_MAPPING = {
    1107: 'paginas maliciosas',
    1016: 'reporte vulns criticas',
    1008: 'email phishing',
    1006: 'hacking realizado por el grupo va',
    1012: 'rehabilitacion de usuario',
    1140: 'detección de blue team',
    1011: 'usuario comprometido',
    1009: 'premalware',
    1160: 'alarme web sites activos'
}


def _get_soar_config() -> Dict[str, Any]:
    """Obtiene la configuración de SOAR desde variables de entorno"""
    base_url = os.getenv('SOAR_API_URL', 'http://localhost:8080').rstrip('/')
    # La API REST de SOAR está en /rest
    base_url = f"{base_url}/rest"
    
    return {
        'base_url': base_url,
        'api_key': os.getenv('SOAR_API_KEY', ''),
        'api_secret': os.getenv('SOAR_API_SECRET', ''),
        'org_id': os.getenv('SOAR_ORG_ID', ''),  # ID de la organización (requerido)
        'timeout': int(os.getenv('SOAR_TIMEOUT', '30')),  # Reducido a 30 segundos para fallar rápido si hay problemas
        'verify_ssl': os.getenv('SOAR_VERIFY_SSL', 'false').lower() == 'true'  # Por defecto false para entornos internos
    }


def _make_soar_request(method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
    """Realiza una petición HTTP a la API de SOAR"""
    config = _get_soar_config()
    # Construir URL sin duplicar paths
    base = config['base_url'].rstrip('/')
    endpoint_clean = endpoint.lstrip('/')
    url = f"{base}/{endpoint_clean}" if endpoint_clean else base
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Autenticación: soporta múltiples métodos
    if config['api_key']:
        if config['api_secret']:
            # Probar diferentes métodos de autenticación
            auth_method = os.getenv('SOAR_AUTH_METHOD', 'basic').lower()
            
            if auth_method == 'basic':
                # Método 1: Basic Auth (usuario: api_key, password: api_secret)
                import base64
                auth_str = base64.b64encode(f"{config['api_key']}:{config['api_secret']}".encode()).decode()
                headers['Authorization'] = f"Basic {auth_str}"
            elif auth_method == 'headers':
                # Método 2: Headers personalizados
                headers['X-API-Key'] = config['api_key']
                headers['X-API-Secret'] = config['api_secret']
            elif auth_method == 'apikey_secret':
                # Método 3: API-Key y API-Secret como headers estándar
                headers['API-Key'] = config['api_key']
                headers['API-Secret'] = config['api_secret']
            else:
                # Por defecto: Basic Auth
                import base64
                auth_str = base64.b64encode(f"{config['api_key']}:{config['api_secret']}".encode()).decode()
                headers['Authorization'] = f"Basic {auth_str}"
        else:
            # Método 2: Bearer token simple
            headers['Authorization'] = f"Bearer {config['api_key']}"
    
    try:
        logger.debug(f"Realizando petición {method} a {url}")
        # Determinar si usar proxy
        proxies_to_use = None
        if config.get('use_proxy') and PROXY_CONFIG and (PROXY_CONFIG.get('http') or PROXY_CONFIG.get('https')):
            proxies_to_use = PROXY_CONFIG
        else:
            # Forzar a no usar proxy si está deshabilitado
            proxies_to_use = {
                'http': None,
                'https': None
            }
        
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            proxies=proxies_to_use,
            timeout=config['timeout'],
            verify=config.get('verify_ssl', False),  # Por defecto false para certificados internos
            **kwargs
        )
        
        # Log de respuesta para debugging
        logger.debug(f"Respuesta: {response.status_code}")
        
        response.raise_for_status()
        
        # Intentar parsear JSON si hay contenido
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
        logger.error(f"Error HTTP en petición SOAR: {e}")
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
        logger.error(f"Error en petición SOAR: {e}")
        return {
            'success': False,
            'error': str(e),
            'status_code': None
        }


async def tool_get_incident(incident_id: str, include_details: bool = True) -> Dict[str, Any]:
    """Obtiene un incidente específico por ID desde SOAR con información completa
    
    Args:
        incident_id: ID del incidente a obtener
        include_details: Si True, incluye comentarios, adjuntos y detalles adicionales (default: True)
    
    Returns:
        Dict con el incidente enriquecido o error
    """
    try:
        logger.info(f"Obteniendo incidente {incident_id} (include_details={include_details})")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado. Es requerido para acceder a la API."}
        
        # Obtener incidente base
        result = _make_soar_request('GET', f"orgs/{config['org_id']}/incidents/{incident_id}")
        
        if not result.get('success'):
            return result
        
        incident_data = result.get('data', {})
        
        # Enriquecer con detalles adicionales si se solicita
        if include_details:
            # 1. Obtener comentarios/notas
            comments_result = await tool_get_incident_comments(incident_id)
            if comments_result.get('success'):
                incident_data['comments'] = comments_result.get('data', [])
                incident_data['comments_count'] = len(incident_data['comments'])
            else:
                incident_data['comments'] = []
                incident_data['comments_count'] = 0
            
            # 2. Obtener adjuntos/archivos
            try:
                attachments_result = _make_soar_request('GET', f"orgs/{config['org_id']}/incidents/{incident_id}/attachments")
                if attachments_result.get('success'):
                    incident_data['attachments'] = attachments_result.get('data', [])
                    incident_data['attachments_count'] = len(incident_data['attachments'])
                else:
                    incident_data['attachments'] = []
                    incident_data['attachments_count'] = 0
            except Exception as e:
                logger.warning(f"No se pudieron obtener adjuntos: {e}")
                incident_data['attachments'] = []
                incident_data['attachments_count'] = 0
            
            # 3. Extraer información clave del estado
            plan_status = incident_data.get('plan_status', '')
            owner_id = incident_data.get('owner_id')
            owner_principal = incident_data.get('owner_principal', {})
            
            # Obtener nombre del propietario
            owner_name = 'No asignado'
            if owner_principal and isinstance(owner_principal, dict):
                owner_name = owner_principal.get('display_name') or owner_principal.get('name') or owner_principal.get('email') or 'Desconocido'
            elif owner_id:
                # Intentar obtener información del usuario desde la API
                try:
                    user_result = _make_soar_request('GET', f"orgs/{config['org_id']}/users/{owner_id}")
                    if user_result.get('success') and user_result.get('data'):
                        user_data = user_result.get('data', {})
                        owner_name = user_data.get('display_name') or user_data.get('name') or user_data.get('email') or str(owner_id)
                except:
                    owner_name = f"Usuario {owner_id}"  # Fallback si no se puede obtener
            
            # Analizar comentarios para determinar quién tomó el incidente
            assigned_by = None
            assigned_at = None
            comments = incident_data.get('comments', [])
            
            if comments:
                # Buscar en comentarios quién asignó/tomó el incidente
                for comment in comments:
                    comment_text = str(comment.get('text', '') or comment.get('body', '') or comment.get('content', '')).lower()
                    comment_creator = comment.get('creator_id') or comment.get('user_id') or comment.get('user', {})
                    
                    # Buscar patrones que indiquen asignación
                    assignment_keywords = ['asignado', 'asigné', 'tomé', 'tomo', 'asignar', 'tomar', 'owner', 'propietario']
                    if any(keyword in comment_text for keyword in assignment_keywords):
                        if isinstance(comment_creator, dict):
                            assigned_by = comment_creator.get('display_name') or comment_creator.get('name') or comment_creator.get('email')
                        elif comment_creator:
                            # Intentar obtener nombre del usuario
                            try:
                                user_result = _make_soar_request('GET', f"orgs/{config['org_id']}/users/{comment_creator}")
                                if user_result.get('success') and user_result.get('data'):
                                    user_data = user_result.get('data', {})
                                    assigned_by = user_data.get('display_name') or user_data.get('name') or user_data.get('email')
                            except:
                                assigned_by = f"Usuario {comment_creator}"
                        
                        assigned_at = comment.get('create_date')
                        break  # Tomar el primer comentario de asignación encontrado
            
            # Si no se encontró en comentarios, usar el propietario actual
            if not assigned_by and owner_name and owner_name != 'No asignado':
                assigned_by = owner_name
            
            # Resumen del estado
            incident_data['status_summary'] = {
                'plan_status': plan_status,
                'status_label': 'Cerrado' if plan_status == 'C' else ('Abierto' if plan_status == 'A' else 'Desconocido'),
                'owner_id': owner_id,
                'owner_name': owner_name,
                'assigned_by': assigned_by or 'No lo tomó nadie',
                'assigned_at': assigned_at,
                'is_open': plan_status == 'A',
                'is_closed': plan_status == 'C'
            }
            
            # 4. Fechas clave
            create_date = incident_data.get('create_date')
            discovered_date = incident_data.get('discovered_date')
            end_date = incident_data.get('end_date')
            
            if create_date:
                incident_data['created_at'] = datetime.fromtimestamp(create_date / 1000.0).isoformat() if isinstance(create_date, (int, float)) else None
            if discovered_date:
                incident_data['discovered_at'] = datetime.fromtimestamp(discovered_date / 1000.0).isoformat() if isinstance(discovered_date, (int, float)) else None
            if end_date:
                incident_data['closed_at'] = datetime.fromtimestamp(end_date / 1000.0).isoformat() if isinstance(end_date, (int, float)) else None
            
            # 5. Crear un resumen compacto al inicio para facilitar el análisis por LLM
            # Esto evita que el LLM tenga que buscar información en campos anidados
            incident_data['incident_summary'] = {
                'id': incident_data.get('id'),
                'name': incident_data.get('name', 'Sin nombre'),
                'incident_type_ids': [t.get('id') if isinstance(t, dict) else t for t in incident_data.get('incident_type_ids', [])],
                'incident_type_names': [t.get('name') if isinstance(t, dict) else INCIDENT_TYPE_MAPPING.get(t, f'Tipo {t}') for t in incident_data.get('incident_type_ids', [])],
                'plan_status': plan_status,
                'plan_status_label': 'Abierto' if plan_status == 'A' else ('Cerrado' if plan_status == 'C' else 'Desconocido'),
                'owner_id': owner_id,
                'owner_name': owner_name,
                'taken_by': assigned_by or 'No lo tomó nadie',
                'reporter': incident_data.get('reporter', 'Desconocido'),
                'severity_code': incident_data.get('severity_code', 'N/A'),
                'created_at': incident_data.get('created_at'),
                'discovered_at': incident_data.get('discovered_at'),
                'closed_at': incident_data.get('closed_at'),
                'description_preview': (str(incident_data.get('description', {}).get('content', '')) if isinstance(incident_data.get('description'), dict) else str(incident_data.get('description', '')))[:500] if incident_data.get('description') else 'Sin descripción',
                'comments_count': incident_data.get('comments_count', 0),
                'attachments_count': incident_data.get('attachments_count', 0),
                'members': [m.get('id') if isinstance(m, dict) else m for m in incident_data.get('members', [])] if incident_data.get('members') else []
            }
            
            # Extraer IPs y puertos de la descripción si hay
            desc_obj = incident_data.get('description', '')
            if isinstance(desc_obj, dict):
                description_full = str(desc_obj.get('content', '')).lower()
            else:
                description_full = str(desc_obj).lower()
            import re
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            ips_found = list(set(re.findall(ip_pattern, description_full)))
            port_pattern = r'port[:\s]*(\d+)|puerto[:\s]*(\d+)|:(\d+)\b'
            ports_found = list(set([p for match in re.findall(port_pattern, description_full) for p in match if p]))
            
            if ips_found:
                incident_data['incident_summary']['ips_mentioned'] = ips_found
            if ports_found:
                incident_data['incident_summary']['ports_mentioned'] = ports_found
            
            # Resumir comentarios: mostrar solo los creados por usuarios (no sistema)
            # IMPORTANTE: Incluir el texto COMPLETO de cada comentario, no truncar
            human_comments = []
            for comment in comments:
                user_id = comment.get('user_id') or comment.get('creator_id')
                if user_id and user_id != 0:  # Excluir System User
                    # NO TRUNCAR - incluir texto completo del comentario
                    comment_text = str(comment.get('text', '') or comment.get('body', '') or comment.get('content', ''))
                    user_fname = comment.get('user_fname') or ''
                    user_lname = comment.get('user_lname') or ''
                    user_name = f"{user_fname} {user_lname}".strip() if (user_fname or user_lname) else f"Usuario {user_id}"
                    human_comments.append({
                        'user_id': user_id,
                        'user_name': user_name,
                        'text': comment_text,  # Texto completo, no preview
                        'text_length': len(comment_text),  # Para referencia
                        'created': datetime.fromtimestamp(comment.get('create_date', 0) / 1000.0).isoformat() if comment.get('create_date') else None
                    })
            
            if human_comments:
                incident_data['incident_summary']['human_comments'] = human_comments
                incident_data['incident_summary']['human_comments_count'] = len(human_comments)
        
        # Mover incident_summary al inicio si existe, para que sea lo primero que vea el LLM
        if 'incident_summary' in incident_data:
            summary = incident_data.pop('incident_summary')
            incident_data = {'incident_summary': summary, **incident_data}
        
        result['data'] = incident_data
        return result
    except Exception as e:
        logger.error(f"Error obteniendo incidente: {e}")
        return {"success": False, "error": str(e)}


async def tool_list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    incident_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
    auto_paginate: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Lista incidentes con filtros opcionales usando los Códigos de Tipo oficiales.
    Soporta búsquedas históricas extensas con paginación automática.
    
    Args:
        status: Estado del incidente (open/closed)
        severity: Severidad del incidente
        limit: Límite de resultados
        offset: Offset para paginación
        incident_type: Tipo de incidente (código numérico o nombre)
        tags: Lista de tags
        start_date: Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)
        end_date: Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)
        use_cache: Si es True, intenta usar la caché de PostgreSQL primero (default: True)
        auto_paginate: Si es True, hace paginación automática para búsquedas históricas (default: True)
    """
    try:
        logger.info(f"Listando incidentes: status={status}, type={incident_type}, start_date={start_date}, end_date={end_date}, limit={limit}, offset={offset}")
        config = _get_soar_config()
        
        # Convertir incident_type a lista de IDs si es necesario
        incident_type_ids = None
        if incident_type:
            incident_type_mapping = INCIDENT_TYPE_MAPPING
            search_term = incident_type.lower()
            
            # Si es un número, usarlo directamente
            if search_term.isdigit():
                incident_type_ids = [int(search_term)]
            else:
                # Buscar en el mapeo
                for code, name in incident_type_mapping.items():
                    if search_term in name.lower() or name.lower() in search_term:
                        incident_type_ids = [code]
                        break
        
        # Intentar usar caché si está disponible y se solicita
        if use_cache:
            try:
                from tools.incident_cache import search_incidents_from_cache, get_cache_stats
                
                # Verificar si hay datos en caché antes de buscar
                cache_stats = await get_cache_stats()
                has_cache_data = cache_stats.get('success') and cache_stats.get('data', {}).get('total_incidents', 0) > 0
                
                if has_cache_data:
                    # Intentar búsqueda en caché
                    cache_result = await search_incidents_from_cache(
                        incident_type_ids=incident_type_ids,
                        status=status,
                        start_date=start_date,
                        end_date=end_date,
                        limit=limit,
                        offset=offset
                    )
                    
                    if cache_result.get('success') and cache_result.get('data', {}).get('count', 0) > 0:
                        logger.info(f"✅ Resultados encontrados en caché: {cache_result.get('data', {}).get('count')} incidentes")
                        return {
                            'success': True,
                            'data': cache_result.get('data'),
                            'source': 'cache'
                        }
                    elif cache_result.get('success'):
                        logger.info("Caché disponible pero sin resultados para estos filtros, buscando en API SOAR")
                else:
                    logger.info("Caché vacío o no disponible, buscando en API SOAR directamente")
            except ImportError:
                logger.debug("Módulo de caché no disponible, usando API SOAR directamente")
            except Exception as e:
                logger.warning(f"Error usando caché, continuando con API SOAR: {e}")
        
        # Usar el mapeo global de tipos de incidente
        incident_type_mapping = INCIDENT_TYPE_MAPPING

        # Calcular rango de fechas y determinar estrategia de búsqueda
        start_timestamp = None
        end_timestamp = None
        days_ago = 0
        
        if start_date:
            try:
                if len(start_date) == 10:  # YYYY-MM-DD
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    start_timestamp = int(start_dt.timestamp() * 1000)
                else:
                    start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                    start_dt = datetime.fromtimestamp(start_ts)
                    start_timestamp = int(start_ts * 1000) if start_ts < 1e12 else int(start_date)
                
                days_ago = (datetime.now() - start_dt).days
            except (ValueError, TypeError) as e:
                logger.warning(f"Formato de fecha inválido para start_date: {start_date} - {e}")
        
        if end_date:
            try:
                if len(end_date) == 10:  # YYYY-MM-DD
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    end_timestamp = int(end_dt.timestamp() * 1000)
                else:
                    end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                    end_dt = datetime.fromtimestamp(end_ts)
                    end_timestamp = int(end_ts * 1000) if end_ts < 1e12 else int(end_date)
            except (ValueError, TypeError) as e:
                logger.warning(f"Formato de fecha inválido para end_date: {end_date} - {e}")

        # Estrategia de paginación automática para búsquedas históricas extensas
        # Si es una búsqueda histórica (más de 90 días) y auto_paginate está activado,
        # hacer múltiples requests paginados
        all_filtered_incidents = []
        max_pages = 50  # Límite de seguridad para evitar loops infinitos
        page_size = 2000  # Tamaño de página para API SOAR
        current_offset = offset
        pages_fetched = 0
        
        if auto_paginate and days_ago > 90:
            logger.info(f"Búsqueda histórica detectada ({days_ago} días atrás). Usando paginación automática...")
            
            while len(all_filtered_incidents) < limit and pages_fetched < max_pages:
                query_data = {
                    'start': current_offset,
                    'length': page_size
                }
                
                logger.info(f"Buscando página {pages_fetched + 1} (offset={current_offset}, length={page_size})")
                result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents/query_paged", json=query_data)
                
                if not result.get('success') or not result.get('data'):
                    break
                
                data = result['data']
                incidents = data.get('data', [])
                
                if not incidents:
                    logger.info("No hay más incidentes en la API")
                    break
                
                # Filtrar incidentes
                filtered = _filter_incidents(
                    incidents, 
                    start_timestamp, 
                    end_timestamp, 
                    status, 
                    incident_type, 
                    incident_type_mapping
                )
                
                all_filtered_incidents.extend(filtered)
                pages_fetched += 1
                current_offset += page_size
                
                # Si no encontramos suficientes incidentes en esta página, continuar
                if len(incidents) < page_size:
                    break
                
                # Si ya tenemos suficientes resultados, parar
                if len(all_filtered_incidents) >= limit:
                    break
            
            # Limitar a los resultados solicitados
            all_filtered_incidents = all_filtered_incidents[:limit]
            
            return {
                'success': True,
                'data': {
                    'data': all_filtered_incidents,
                    'count': len(all_filtered_incidents),
                    'total': len(all_filtered_incidents),  # Aproximado
                    'pages_fetched': pages_fetched,
                    'source': 'api_paginated'
                }
            }
        else:
            # Búsqueda normal sin paginación automática
            # Calcular query_length basado en el rango de fechas
            # Cuando buscamos por tipo de incidente, necesitamos buscar más incidentes
            # porque query_paged no devuelve incident_type_ids completos y necesitamos obtenerlos individualmente
            query_length = limit
            if days_ago > 365:  # Más de un año
                query_length = min(limit * 50, 20000) if not incident_type else min(limit * 100, 20000)
            elif days_ago > 180:  # Más de 6 meses
                query_length = min(limit * 30, 15000) if not incident_type else min(limit * 80, 15000)
            elif days_ago > 90:  # Más de 3 meses
                query_length = min(limit * 20, 10000) if not incident_type else min(limit * 60, 10000)
            elif days_ago > 30:  # Más de 1 mes
                query_length = min(limit * 15, 8000) if not incident_type else min(limit * 40, 8000)
            elif days_ago > 7:  # Más de 1 semana
                query_length = min(limit * 10, 5000) if not incident_type else min(limit * 30, 5000)
            elif days_ago > 0:
                # Para rangos recientes (ayer/hoy = ~1-2 días), usar límites MUY bajos para evitar timeouts
                if days_ago <= 3:
                    # Para hoy/ayer, usar límite MUY conservador
                    query_length = min(limit * 2, 200) if not incident_type else min(limit * 5, 500)
                    logger.info(f"Rango de fecha muy reciente ({days_ago} días), usando query_length conservador: {query_length}")
                else:
                    query_length = min(limit * 5, 2000) if not incident_type else min(limit * 20, 3000)
            elif incident_type:
                # Si buscamos por tipo sin fecha, buscar más para encontrar los incidentes
                query_length = min(limit * 30, 5000)
            elif status:
                # Para búsquedas por status sin fecha, usar límite conservador
                query_length = min(limit * 2, 500)  # Reducido aún más: 2x y máximo 500
            
            # Construir query_data con filtros nativos de SOAR API
            query_data = {
                'start': offset,
                'length': query_length
            }
            
            # Agregar filtros nativos de SOAR si están disponibles
            # SOAR API soporta filtros en query_paged usando el formato de filtros
            filters = []
            
            # Filtrar por tipo de incidente usando filtros nativos
            if incident_type_ids and len(incident_type_ids) > 0:
                # SOAR API usa filtros con condiciones
                type_filter = {
                    'conditions': [{
                        'field_name': 'incident_type_ids',
                        'method': 'contains',
                        'value': incident_type_ids[0]  # Por ahora solo el primero
                    }]
                }
                filters.append(type_filter)
                logger.info(f"Agregando filtro nativo por tipo de incidente: {incident_type_ids[0]}")
            
            # Filtrar por estado usando filtros nativos
            if status:
                status_value = 'A' if status.lower() in ['open', 'abierto', 'active', 'a'] else 'C' if status.lower() in ['closed', 'cerrado', 'c'] else None
                if status_value:
                    status_filter = {
                        'conditions': [{
                            'field_name': 'plan_status',
                            'method': 'equals',
                            'value': status_value
                        }]
                    }
                    filters.append(status_filter)
                    logger.info(f"Agregando filtro nativo por estado: {status_value}")
            
            if filters:
                query_data['filters'] = filters
            
            logger.info(f"Buscando {query_data['length']} incidentes en API SOAR con filtros: {filters if filters else 'ninguno'}")
            
            # Para búsquedas con fecha específica (hoy/ayer), usar timeout más corto
            original_timeout = None
            if start_date or end_date:
                try:
                    from datetime import timedelta
                    if start_date:
                        if len(start_date) == 10:  # YYYY-MM-DD
                            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                        else:
                            start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                            start_dt = datetime.fromtimestamp(start_ts)
                    else:
                        start_dt = datetime.now() - timedelta(days=7)
                    if end_date:
                        if len(end_date) == 10:  # YYYY-MM-DD
                            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                        else:
                            end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                            end_dt = datetime.fromtimestamp(end_ts)
                    else:
                        end_dt = datetime.now()
                    days_range = (end_dt - start_dt).days
                    # Si es rango muy pequeño (hoy = 0 días), usar timeout más corto
                    if days_range <= 1:
                        logger.info(f"Rango de fecha muy pequeño ({days_range} días), usando timeout reducido (15s)")
                        original_timeout = config.get('timeout', 30)
                        config['timeout'] = 15  # 15 segundos para búsquedas de hoy
                except Exception as e:
                    logger.debug(f"Error calculando rango de fecha para timeout: {e}")
            
            result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents/query_paged", json=query_data)
            
            # Restaurar timeout original si se modificó
            if original_timeout is not None:
                config['timeout'] = original_timeout
            
            if result.get('success') and result.get('data'):
                data = result['data']
                incidents = data.get('data', [])
                
                # PROBLEMA CRÍTICO: query_paged NO devuelve incident_type_ids completos
                # Necesitamos obtener cada incidente individualmente si hay filtro por tipo
                if incident_type and incidents:
                    logger.warning(f"⚠️  query_paged no devuelve incident_type_ids completos. Obteniendo incidentes individualmente para verificar tipo...")
                    incidents_with_types = []
                    # Reducir límite para evitar que se cuelgue - procesar solo una muestra razonable
                    # Si hay filtros de fecha recientes (ayer/hoy), usar límite MUY bajo
                    # Si hay filtros de fecha antiguos, usar límite medio
                    if start_date or end_date:
                        # Detectar si es un rango pequeño (ayer/hoy = ~2 días)
                        try:
                            if start_date:
                                if len(start_date) == 10:  # YYYY-MM-DD
                                    start = datetime.strptime(start_date, '%Y-%m-%d')
                                else:
                                    start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                                    start = datetime.fromtimestamp(start_ts)
                            else:
                                start = datetime.now() - timedelta(days=7)
                            if end_date:
                                if len(end_date) == 10:  # YYYY-MM-DD
                                    end = datetime.strptime(end_date, '%Y-%m-%d')
                                else:
                                    end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                                    end = datetime.fromtimestamp(end_ts)
                            else:
                                end = datetime.now()
                            days_range = (end - start).days
                            # Si es rango pequeño (≤3 días como ayer/hoy), usar límite MUY bajo
                            if days_range <= 3:
                                max_incidents_to_check = 50  # MUY bajo para rangos pequeños (ayer/hoy)
                                logger.info(f"Rango de fecha pequeño detectado ({days_range} días), usando límite bajo: 50 incidentes")
                            elif days_range <= 7:
                                max_incidents_to_check = 100  # Bajo para rangos de una semana
                            else:
                                max_incidents_to_check = 200  # Medio para rangos mayores
                        except Exception as e:
                            logger.warning(f"Error calculando rango de fechas: {e}, usando límite seguro")
                            max_incidents_to_check = 50  # Default seguro y bajo
                    elif days_ago <= 3:
                        # Búsqueda reciente sin fecha específica (últimos 3 días)
                        max_incidents_to_check = 50  # Muy bajo para búsquedas recientes
                    elif days_ago > 30:
                        max_incidents_to_check = 200  # Medio para búsquedas antiguas
                    else:
                        max_incidents_to_check = 100  # Bajo para búsquedas recientes sin fecha específica
                    
                    # Límite máximo absoluto para evitar que se cuelgue
                    max_incidents_to_check = min(max_incidents_to_check, 200)
                    logger.info(f"Verificando tipos en {min(max_incidents_to_check, len(incidents))} incidentes (de {len(incidents)} totales)...")
                    for idx, inc in enumerate(incidents[:min(max_incidents_to_check, len(incidents))]):
                        # Log cada 50 incidentes para ver progreso
                        if idx > 0 and idx % 50 == 0:
                            logger.info(f"Procesados {idx}/{min(max_incidents_to_check, len(incidents))} incidentes...")
                        
                        inc_id = inc.get('id')
                        if not inc_id:
                            continue
                        
                        # Obtener incidente individual para tener tipos completos
                        try:
                            inc_result = await tool_get_incident(str(inc_id), include_details=False)
                            if inc_result.get('success') and inc_result.get('data'):
                                inc_full = inc_result['data']
                                # Verificar tipo en el incidente completo
                                type_ids = inc_full.get('incident_type_ids', [])
                                codes = []
                                for tid in type_ids:
                                    if isinstance(tid, dict):
                                        val = tid.get('id') or tid.get('value') or tid.get('type_id')
                                    else:
                                        val = tid
                                    if val is not None:
                                        try:
                                            codes.append(int(val))
                                        except:
                                            pass
                                
                                # Verificar si coincide con el tipo buscado
                                search_term = incident_type.lower()
                                if search_term.isdigit():
                                    code_to_search = int(search_term)
                                    if code_to_search in codes:
                                        incidents_with_types.append(inc_full)
                                        logger.info(f"✅ Incidente {inc_id} tiene tipo {code_to_search}")
                                else:
                                    # Buscar por nombre en el mapeo
                                    for code, name in incident_type_mapping.items():
                                        if search_term in name.lower() or name.lower() in search_term:
                                            if code in codes:
                                                incidents_with_types.append(inc_full)
                                                logger.info(f"✅ Incidente {inc_id} tiene tipo {code} ({name})")
                                                break
                        except Exception as e:
                            logger.warning(f"Error obteniendo incidente {inc_id}: {e}")
                            continue
                    
                    incidents = incidents_with_types
                    # Limitar resultados finales al límite solicitado
                    if len(incidents) > limit:
                        logger.info(f"Limitando resultados de {len(incidents)} a {limit} incidentes")
                        incidents = incidents[:limit]
                
                filtered_incidents = _filter_incidents(
                    incidents,
                    start_timestamp,
                    end_timestamp,
                    status,
                    incident_type,
                    incident_type_mapping
                )
                
                data['data'] = filtered_incidents[:limit]
                data['count'] = len(data['data'])
                result['data'] = data
            
            return result
    except Exception as e:
        logger.error(f"Error listando incidentes: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _filter_incidents(
    incidents: List[Dict[str, Any]],
    start_timestamp: Optional[int],
    end_timestamp: Optional[int],
    status: Optional[str],
    incident_type: Optional[str],
    incident_type_mapping: Dict[int, str]
) -> List[Dict[str, Any]]:
    """Filtra una lista de incidentes según los criterios proporcionados"""
    filtered_incidents = []
    
    for inc in incidents:
        # 0. Filtrar por fecha si se proporcionaron (aplicar antes de otros filtros)
        if start_timestamp or end_timestamp:
            create_date = inc.get('create_date')
            if create_date:
                inc_create_ts = create_date if isinstance(create_date, int) else int(create_date)
                
                if start_timestamp and inc_create_ts < start_timestamp:
                    continue
                
                if end_timestamp and inc_create_ts > end_timestamp:
                    continue
        
        # 1. Filtrar por status
        if status:
            inc_status = str(inc.get('plan_status', '')).lower()
            is_open = any(x in inc_status for x in ['a', 'open', 'active', 'abierto', 'activo'])
            is_closed = any(x in inc_status for x in ['c', 'closed', 'cerrado', 'inactivo', 'resolved'])
            
            if status.lower() in ['open', 'abierto', 'active', 'a']:
                if not is_open: 
                    continue
            elif status.lower() in ['closed', 'cerrado', 'c']:
                if not is_closed: 
                    continue

        # 2. Filtrar por tipo (ESTRICTO POR CÓDIGO)
        if incident_type:
            search_term = incident_type.lower()
            
            # Extraer IDs/Códigos del incidente actual
            current_codes = []
            incident_type_ids = inc.get('incident_type_ids', [])
            if not incident_type_ids:
                # Si no hay incident_type_ids, intentar buscar en otros campos
                incident_type_ids = inc.get('incident_types', [])
            
            # LOG DETALLADO para debugging
            logger.debug(f"Incidente {inc.get('id')}: incident_type_ids RAW = {incident_type_ids}, tipo = {type(incident_type_ids)}")
            
            for tid in incident_type_ids:
                if isinstance(tid, dict):
                    val = tid.get('id') or tid.get('value') or tid.get('type_id')
                    logger.debug(f"  - Tipo de incidente es dict: {tid}, extrayendo id/value/type_id = {val}")
                else:
                    val = tid
                    logger.debug(f"  - Tipo de incidente es primitivo: {tid}")
                if val is not None:
                    try:
                        code_int = int(val)
                        current_codes.append(code_int)
                        logger.debug(f"  - Código extraído: {code_int}")
                    except (ValueError, TypeError) as e:
                        logger.debug(f"  - Error convirtiendo {val} a int: {e}")
                        pass
            
            logger.debug(f"Incidente {inc.get('id')}: códigos extraídos = {current_codes}")
            
            # Ver si el término buscado corresponde a uno de nuestros códigos
            id_match = False
            
            # Primero verificar si el término es un número (código directo)
            if search_term.isdigit():
                code_to_search = int(search_term)
                if code_to_search in current_codes:
                    id_match = True
                    logger.info(f"✅ Match encontrado: Incidente {inc.get('id')} tiene tipo {code_to_search}")
                else:
                    # Log detallado cuando no coincide
                    if current_codes:
                        logger.warning(f"⚠️  Incidente {inc.get('id')} NO tiene tipo {code_to_search}, tiene tipos: {current_codes}")
                    else:
                        logger.warning(f"⚠️  Incidente {inc.get('id')} NO tiene tipos de incidente (vacío), incident_type_ids RAW: {incident_type_ids}")
            
            # También buscar por nombre en el mapeo
            if not id_match:
                for code, name in incident_type_mapping.items():
                    if search_term in name.lower() or name.lower() in search_term:
                        if code in current_codes:
                            id_match = True
                            logger.info(f"✅ Match por nombre: Incidente {inc.get('id')} tiene tipo {code} ({name})")
                            break
            
            # También búsqueda por texto en el nombre (solo si buscamos por texto, no por código)
            text_match = False
            if not search_term.isdigit() and search_term in str(inc.get('name', '')).lower():
                text_match = True
                logger.info(f"✅ Match por texto en nombre: Incidente {inc.get('id')} contiene '{search_term}' en nombre")
            
            if not (id_match or text_match):
                logger.debug(f"  - Incidente {inc.get('id')} NO pasa el filtro de tipo '{incident_type}'")
                continue
        
        filtered_incidents.append(inc)
    
    return filtered_incidents


async def tool_create_incident(
    title: str,
    description: str,
    severity: str,
    source_ip: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Crea un nuevo incidente en SOAR
    
    Args:
        title: Título del incidente (campo 'name' en SOAR)
        description: Descripción detallada
        severity: Severidad (low, medium, high, critical) - usar códigos numéricos si es necesario
        source_ip: IP de origen (opcional) - se agregará como artifact
        tags: Tags asociados (opcional)
    
    Returns:
        Dict con el incidente creado
    """
    try:
        logger.info(f"Creando incidente: {title}")
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado. Es requerido para acceder a la API."}
        
        # Según la documentación, usar FullIncidentDataDTO para crear
        data = {
            'name': title,  # El campo 'name' es el título en SOAR
            'description': {
                'format': 'text',
                'content': description
            }
        }
        
        # Mapear severidad a códigos si es necesario (puede requerir ajuste según la API)
        severity_map = {
            'low': 4,
            'medium': 5,
            'high': 6,
            'critical': 7
        }
        if severity.lower() in severity_map:
            data['severity_code'] = severity_map[severity.lower()]
        
        if tags:
            data['tags'] = [{'tag_type': 'user', 'name': tag} for tag in tags]
        
        # Si hay source_ip, se puede agregar como artifact después de crear el incidente
        result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents", json=data)
        
        # Si se creó exitosamente y hay source_ip, agregarlo como artifact
        if result.get('success') and source_ip and result.get('data', {}).get('id'):
            inc_id = result['data']['id']
            artifact_data = {
                'type': {'name': 'IP Address'},
                'value': source_ip
            }
            artifact_result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents/{inc_id}/artifacts", json=artifact_data)
            if artifact_result.get('success'):
                logger.info(f"Artifact de IP {source_ip} agregado al incidente {inc_id}")
        
        return result
    except Exception as e:
        logger.error(f"Error creando incidente: {e}")
        return {"success": False, "error": str(e)}


async def tool_update_incident(
    incident_id: str,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Actualiza un incidente existente usando PATCH
    
    Args:
        incident_id: ID del incidente a actualizar
        status: Nuevo estado (opcional) - usar plan_status_id según ConstDTO
        severity: Nueva severidad (opcional) - usar severity_code
        notes: Notas adicionales (opcional) - se agregará como comment
    
    Returns:
        Dict con el incidente actualizado
    """
    try:
        logger.info(f"Actualizando incidente {incident_id}")
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado. Es requerido para acceder a la API."}
        
        # Usar PATCH según la documentación
        patch_changes = []
        
        if status:
            # Necesitaríamos el plan_status_id, pero por ahora usamos el nombre
            patch_changes.append({
                'field': {'name': 'plan_status'},
                'old_value': None,  # No verificamos el valor anterior
                'new_value': {'name': status}
            })
        
        if severity:
            severity_map = {
                'low': 4,
                'medium': 5,
                'high': 6,
                'critical': 7
            }
            if severity.lower() in severity_map:
                patch_changes.append({
                    'field': {'name': 'severity_code'},
                    'old_value': None,
                    'new_value': severity_map[severity.lower()]
                })
        
        if not patch_changes:
            return {"success": False, "error": "No se proporcionaron campos para actualizar"}
        
        patch_data = {'changes': patch_changes}
        
        result = _make_soar_request('PATCH', f"orgs/{config['org_id']}/incidents/{incident_id}", json=patch_data)
        
        # Si hay notas, agregarlas como comment
        if result.get('success') and notes:
            comment_data = {
                'text': {
                    'format': 'text',
                    'content': notes
                }
            }
            comment_result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents/{incident_id}/comments", json=comment_data)
            if comment_result.get('success'):
                logger.info(f"Nota agregada como comment al incidente {incident_id}")
        
        return result
    except Exception as e:
        logger.error(f"Error actualizando incidente: {e}")
        return {"success": False, "error": str(e)}


async def tool_close_incident(incident_id: str, resolution: str, resolution_id: int = 10) -> Dict[str, Any]:
    """Cierra un incidente con una razón de resolución
    
    Args:
        incident_id: ID del incidente a cerrar
        resolution: Razón de cierre (se agregará en resolution_summary)
        resolution_id: ID de resolución (default: 10 = "Resolved")
    
    Returns:
        Dict con el incidente cerrado
    """
    try:
        logger.info(f"Cerrando incidente {incident_id} con resolución: {resolution}")
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado. Es requerido para acceder a la API."}
        
        # Formato correcto según la API de SOAR/Resilient
        patch_changes = [
            {
                "field": "resolution_id",
                "old_value": {},
                "new_value": {
                    "id": resolution_id
                }
            },
            {
                "field": "resolution_summary",
                "old_value": {"textarea": None},
                "new_value": {
                    "text": resolution
                }
            },
            {
                "field": "plan_status",
                "old_value": {
                    "text": "A"
                },
                "new_value": {
                    "text": "C"
                }
            }
        ]
        
        patch_data = {'changes': patch_changes}
        result = _make_soar_request('PATCH', f"orgs/{config['org_id']}/incidents/{incident_id}", json=patch_data)
        
        if result.get('success'):
            logger.info(f"Incidente {incident_id} cerrado exitosamente")
        else:
            logger.error(f"Error cerrando incidente: {result.get('error')}")
        
        return result
    except Exception as e:
        logger.error(f"Error cerrando incidente: {e}")
        return {"success": False, "error": str(e)}


async def tool_search_incidents(
    query: str,
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search_all_history: bool = False,
    use_cache: bool = True,
    auto_paginate: bool = True
) -> Dict[str, Any]:
    """Busca incidentes usando búsqueda de texto completo con soporte para búsquedas históricas extensas.
    Nota: Se prefiere list_incidents con filtros si se busca por IP o tipo específico.
    
    Args:
        query: Texto a buscar en los incidentes
        limit: Límite de resultados
        start_date: Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)
        end_date: Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)
        search_all_history: Si es True, busca en todo el historial sin límite de incidentes
        use_cache: Si es True, intenta usar la caché de PostgreSQL primero (default: True)
        auto_paginate: Si es True, hace paginación automática para búsquedas históricas (default: True)
    """
    try:
        logger.info(f"Buscando incidentes: query={query}, start_date={start_date}, end_date={end_date}, search_all_history={search_all_history}")
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado."}
        
        # Convertir fechas a timestamps si es necesario
        start_timestamp = None
        end_timestamp = None
        days_ago = 0
        
        if start_date:
            try:
                if len(start_date) == 10:  # Formato YYYY-MM-DD
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    start_timestamp = int(start_dt.timestamp() * 1000)
                    days_ago = (datetime.now() - start_dt).days
                else:
                    # Intentar como timestamp
                    start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                    start_dt = datetime.fromtimestamp(start_ts)
                    start_timestamp = int(start_ts * 1000) if start_ts < 1e12 else int(start_date)
                    days_ago = (datetime.now() - start_dt).days
            except (ValueError, TypeError) as e:
                logger.warning(f"Formato de fecha inválido para start_date: {start_date} - {e}")
        
        if end_date:
            try:
                if len(end_date) == 10:  # Formato YYYY-MM-DD
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    # Incluir todo el día (23:59:59)
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    end_timestamp = int(end_dt.timestamp() * 1000)
                else:
                    # Intentar como timestamp
                    end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                    end_dt = datetime.fromtimestamp(end_ts)
                    end_timestamp = int(end_ts * 1000) if end_ts < 1e12 else int(end_date)
            except (ValueError, TypeError) as e:
                logger.warning(f"Formato de fecha inválido para end_date: {end_date} - {e}")
        
        # Intentar usar caché si está disponible
        if use_cache:
            try:
                from tools.incident_cache import search_incidents_from_cache
                
                cache_result = await search_incidents_from_cache(
                    query=query,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    offset=0
                )
                
                if cache_result.get('success') and cache_result.get('data', {}).get('count', 0) > 0:
                    logger.info(f"✅ Resultados encontrados en caché: {cache_result.get('data', {}).get('count')} incidentes")
                    return {
                        'success': True,
                        'data': cache_result.get('data'),
                        'source': 'cache'
                    }
            except ImportError:
                logger.debug("Módulo de caché no disponible, usando API SOAR directamente")
            except Exception as e:
                logger.warning(f"Error usando caché, continuando con API SOAR: {e}")
        
        # Determinar límite de incidentes a buscar según parámetros
        # Para búsquedas históricas extensas, usar paginación automática
        if search_all_history or (auto_paginate and days_ago > 90):
            # Usar paginación automática para búsquedas históricas
            max_incidents_to_search = 20000 if search_all_history else 10000
        elif start_date or end_date:
            # Calcular basado en días atrás
            if days_ago > 365:
                max_incidents_to_search = 15000
            elif days_ago > 180:
                max_incidents_to_search = 10000
            elif days_ago > 90:
                max_incidents_to_search = 5000
            else:
                max_incidents_to_search = 2000
        else:
            max_incidents_to_search = 1000  # Por defecto, buscar hasta 1000 incidentes
        
        # Usar list_incidents con paginación automática si es necesario
        list_res = await tool_list_incidents(
            limit=max_incidents_to_search,
            start_date=start_date,
            end_date=end_date,
            use_cache=False,  # Ya intentamos caché arriba
            auto_paginate=auto_paginate and (search_all_history or days_ago > 90)
        )
        if list_res.get('success'):
            all_inc = list_res.get('data', {}).get('data', [])
            q = query.lower()
            filtered = []
            
            # Mapear términos comunes a tipos de incidente usando INCIDENT_TYPE_MAPPING
            # Por ejemplo: "red team" -> buscar en tipo "hacking realizado por el grupo va" (1006)
            # "blue team" -> buscar en tipo "detección de blue team" (1140)
            incident_type_codes_to_search = []
            query_normalized = q.replace('_', ' ').replace('-', ' ')
            
            # Mapear términos comunes
            if 'red team' in query_normalized or 'redteam' in query_normalized:
                incident_type_codes_to_search.append(1006)  # hacking realizado por el grupo va
            if 'blue team' in query_normalized or 'blueteam' in query_normalized:
                incident_type_codes_to_search.append(1140)  # detección de blue team
            if 'phishing' in query_normalized:
                incident_type_codes_to_search.append(1008)  # email phishing
            if 'vuln' in query_normalized or 'vulnerabilidad' in query_normalized:
                incident_type_codes_to_search.append(1016)  # reporte vulns criticas
            if 'malicios' in query_normalized or 'malware' in query_normalized:
                incident_type_codes_to_search.extend([1107, 1009])  # paginas maliciosas, premalware
            if 'usuario comprometido' in query_normalized:
                incident_type_codes_to_search.append(1011)  # usuario comprometido
            
            # Primera pasada: buscar en name, description, properties (rápido)
            # Y filtrar por fecha si se proporcionaron
            for inc in all_inc:
                # Filtrar por fecha si se proporcionaron
                if start_timestamp or end_timestamp:
                    create_date = inc.get('create_date')
                    if create_date:
                        inc_create_ts = create_date if isinstance(create_date, int) else int(create_date)
                        
                        # Filtrar por fecha de inicio
                        if start_timestamp and inc_create_ts < start_timestamp:
                            continue
                        
                        # Filtrar por fecha de fin
                        if end_timestamp and inc_create_ts > end_timestamp:
                            continue
                
                # Buscar en name, description, properties
                # Buscar en name, description
                name = str(inc.get('name', '')).lower()
                description = str(inc.get('description', '')).lower()
                
                if q in name or q in description:
                    filtered.append(inc)
                    continue
                
                # Buscar en properties (campos personalizados)
                properties = inc.get('properties', {})
                if isinstance(properties, dict):
                    properties_str = json.dumps(properties).lower()
                    if q in properties_str:
                        filtered.append(inc)
                        continue
            
            # Si encontramos resultados, retornar inmediatamente
            if filtered:
                return {
                    "success": True,
                    "data": {
                        "data": filtered[:limit],
                        "count": len(filtered[:limit])
                    }
                }
            
            # Segunda pasada: buscar en comentarios y artifacts solo si no encontramos nada (más lento)
            # Limitar a los primeros 100 incidentes para tener mejor cobertura pero sin ser demasiado lento
            for inc in all_inc[:100]:
                inc_id = inc.get('id')
                if not inc_id or inc in filtered:
                    continue
                
                try:
                    # Buscar en artifacts primero (más común para IPs)
                    artifacts_res = _make_soar_request('GET', f"orgs/{config['org_id']}/incidents/{inc_id}/artifacts")
                    if artifacts_res.get('success'):
                        artifacts = artifacts_res.get('data', [])
                        if isinstance(artifacts, list):
                            for artifact in artifacts:
                                artifact_value = str(artifact.get('value', '')).lower()
                                if q in artifact_value:
                                    filtered.append(inc)
                                    break
                    
                    if inc in filtered:
                        continue
                    
                    # Buscar en comentarios (solo si no encontramos en artifacts)
                    comments_res = await tool_get_incident_comments(inc_id)
                    if comments_res.get('success'):
                        comments = comments_res.get('data', [])
                        for comment in comments[:3]:  # Solo primeros 3 comentarios
                            comment_text = str(comment.get('text', '') or comment.get('body', '')).lower()
                            if q in comment_text:
                                filtered.append(inc)
                                break
                except:
                    pass  # Si falla obtener comentarios/artifacts, continuar
            
            return {
                "success": True,
                "data": {
                    "data": filtered[:limit],
                    "count": len(filtered[:limit])
                }
            }
            
        return {"success": False, "error": "No se pudo realizar la búsqueda"}
    except Exception as e:
        logger.error(f"Error buscando incidentes: {e}")
        return {"success": False, "error": str(e)}

async def tool_get_incident_comments(incident_id: str, include_full_text: bool = True) -> Dict[str, Any]:
    """Obtiene los comentarios/notas de un incidente específico (SIN TRUNCAR)
    
    Args:
        incident_id: ID del incidente
        include_full_text: Si True, incluye el texto completo de cada comentario (default: True)
        
    Returns:
        Dict con la lista de comentarios completos (sin truncar)
    """
    try:
        logger.info(f"Obteniendo comentarios del incidente {incident_id} (include_full_text={include_full_text})")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
            
        result = _make_soar_request('GET', f"orgs/{config['org_id']}/incidents/{incident_id}/comments")
        
        if result.get('success') and result.get('data'):
            comments = result.get('data', [])
            
            # Procesar comentarios para asegurar que el texto completo esté disponible
            processed_comments = []
            for comment in comments:
                # Extraer texto completo del comentario (SIN TRUNCAR)
                comment_text = str(comment.get('text', '') or comment.get('body', '') or comment.get('content', ''))
                
                # Crear objeto de comentario enriquecido
                processed_comment = {
                    'id': comment.get('id'),
                    'user_id': comment.get('user_id') or comment.get('creator_id'),
                    'user_fname': comment.get('user_fname', ''),
                    'user_lname': comment.get('user_lname', ''),
                    'user_name': f"{comment.get('user_fname', '')} {comment.get('user_lname', '')}".strip() or f"Usuario {comment.get('user_id', 'N/A')}",
                    'text': comment_text,  # Texto COMPLETO, sin truncar
                    'text_length': len(comment_text),
                    'create_date': comment.get('create_date'),
                    'created_at': datetime.fromtimestamp(comment.get('create_date', 0) / 1000.0).isoformat() if comment.get('create_date') else None,
                    'is_system': (comment.get('user_id') == 0 or not comment.get('user_id'))
                }
                
                # Incluir campos adicionales si existen
                if comment.get('attachments'):
                    processed_comment['attachments'] = comment.get('attachments')
                if comment.get('properties'):
                    processed_comment['properties'] = comment.get('properties')
                
                processed_comments.append(processed_comment)
            
            # Separar comentarios de usuarios y del sistema
            user_comments = [c for c in processed_comments if not c['is_system']]
            system_comments = [c for c in processed_comments if c['is_system']]
            
            result['data'] = processed_comments
            result['summary'] = {
                'total_comments': len(processed_comments),
                'user_comments_count': len(user_comments),
                'system_comments_count': len(system_comments),
                'total_text_length': sum(c['text_length'] for c in processed_comments)
            }
            result['user_comments'] = user_comments  # Comentarios de usuarios (más relevantes)
            result['system_comments'] = system_comments  # Comentarios del sistema (menos relevantes)
        
        return result
    except Exception as e:
        logger.error(f"Error obteniendo comentarios: {e}")
        return {"success": False, "error": str(e)}


async def tool_list_playbooks(limit: int = 100) -> Dict[str, Any]:
    """Lista los playbooks disponibles en SOAR
    
    Args:
        limit: Límite de resultados
    
    Returns:
        Dict con la lista de playbooks
    """
    try:
        logger.info(f"Listando playbooks disponibles")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
        
        # Usar query_paged (mismo método que para incidentes)
        query_data = {
            'start': 0,
            'length': limit
        }
        
        result = _make_soar_request('POST', f"orgs/{config['org_id']}/playbooks/query_paged", json=query_data)
        
        if result.get('success') and result.get('data'):
            data = result.get('data', {})
            playbooks = data.get('data', [])
            if isinstance(playbooks, list):
                # Retornar en el mismo formato que list_incidents
                result['data'] = {
                    'recordsTotal': data.get('recordsTotal', len(playbooks)),
                    'recordsFiltered': data.get('recordsFiltered', len(playbooks)),
                    'data': playbooks[:limit],
                    'count': len(playbooks[:limit])
                }
        
        return result
    except Exception as e:
        logger.error(f"Error listando playbooks: {e}")
        return {"success": False, "error": str(e)}


async def tool_get_playbook(playbook_id: str) -> Dict[str, Any]:
    """Obtiene los detalles de un playbook específico
    
    Args:
        playbook_id: ID del playbook
    
    Returns:
        Dict con los detalles del playbook
    """
    try:
        logger.info(f"Obteniendo playbook {playbook_id}")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
        
        result = _make_soar_request('GET', f"orgs/{config['org_id']}/playbooks/{playbook_id}")
        return result
    except Exception as e:
        logger.error(f"Error obteniendo playbook: {e}")
        return {"success": False, "error": str(e)}


async def tool_check_playbook_status(playbook_id: str = None, playbook_name: str = None) -> Dict[str, Any]:
    """Verifica el estado y disponibilidad de un playbook, incluyendo si está habilitado y sus condiciones
    
    Args:
        playbook_id: ID del playbook (opcional si se proporciona playbook_name)
        playbook_name: Nombre del playbook para buscar (opcional si se proporciona playbook_id)
    
    Returns:
        Dict con el estado del playbook, incluyendo si está habilitado, sus condiciones y acciones asociadas
    """
    try:
        logger.info(f"Verificando estado del playbook: id={playbook_id}, name={playbook_name}")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
        
        # Buscar el playbook por ID o nombre
        if playbook_id:
            playbook_result = await tool_get_playbook(playbook_id)
        elif playbook_name:
            playbooks_result = await tool_list_playbooks(limit=100)
            if not playbooks_result.get('success'):
                return {"success": False, "error": "No se pudo listar playbooks"}
            
            playbooks = playbooks_result.get('data', {}).get('data', [])
            matching = [p for p in playbooks if playbook_name.lower() in p.get('name', '').lower()]
            if not matching:
                return {"success": False, "error": f"No se encontró el playbook '{playbook_name}'"}
            
            playbook_id = matching[0].get('id')
            playbook_result = await tool_get_playbook(str(playbook_id))
        else:
            return {"success": False, "error": "Se requiere playbook_id o playbook_name"}
        
        if not playbook_result.get('success'):
            return playbook_result
        
        playbook_data = playbook_result.get('data', {})
        
        # Obtener detalles adicionales
        # El campo 'status' puede ser "enabled" o "disabled" (string)
        playbook_status = playbook_data.get('status', 'unknown')
        is_enabled = playbook_status == 'enabled'
        
        status_info = {
            "playbook_id": playbook_id,
            "name": playbook_data.get('display_name') or playbook_data.get('name', ''),
            "status": playbook_status,
            "enabled": is_enabled,
            "activation_type": playbook_data.get('activation_type', 'unknown'),
            "has_logical_errors": playbook_data.get('has_logical_errors', False),
            "timestamp": datetime.now().isoformat(),
        }
        
        # Verificar acciones asociadas
        actions_result = _make_soar_request('GET', f"orgs/{config['org_id']}/actions")
        if actions_result.get('success'):
            actions = actions_result.get('data', {}).get('entities', [])
            # Buscar acciones que mencionen el nombre del playbook o tengan workflows asociados
            playbook_name_lower = status_info['name'].lower()
            related_actions = [
                a for a in actions 
                if playbook_name_lower in a.get('name', '').lower() or 
                   playbook_id in str(a.get('workflows', []))
            ]
            
            status_info['related_actions'] = [
                {
                    'id': a.get('id'),
                    'name': a.get('name'),
                    'enabled': a.get('enabled', False)
                }
                for a in related_actions[:10]
            ]
            status_info['related_actions_count'] = len(related_actions)
        
        # Verificar si hay algún incidente reciente que tenga este playbook asociado
        incidents_result = await tool_list_incidents(limit=50)
        if incidents_result.get('success'):
            incidents = incidents_result.get('data', {}).get('data', [])
            recent_with_playbook = [
                inc for inc in incidents 
                if playbook_id in inc.get('playbooks', [])
            ]
            status_info['recent_incidents_with_playbook'] = len(recent_with_playbook)
            if recent_with_playbook:
                latest = recent_with_playbook[0]
                status_info['last_execution_incident'] = {
                    'id': latest.get('id'),
                    'name': latest.get('name'),
                    'create_date': datetime.fromtimestamp(latest.get('create_date', 0) / 1000.0).isoformat() if latest.get('create_date') else None
                }
        
        status_info['verification_result'] = "healthy" if is_enabled and not status_info['has_logical_errors'] else ("degraded" if is_enabled else "disabled")
        
        return {
            "success": True,
            "data": status_info
        }
    except Exception as e:
        logger.error(f"Error verificando estado del playbook: {e}")
        return {"success": False, "error": str(e)}


async def tool_health_check_soar() -> Dict[str, Any]:
    """
    Health check simplificado para Tokio AI - verifica PostgreSQL y Kafka
    """
    try:
        # Verificar PostgreSQL
        try:
            from tools.postgresql_tools import _get_connection
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            postgres_status = "healthy"
        except Exception as e:
            postgres_status = f"unhealthy: {str(e)[:100]}"
        
        # Verificar Kafka (opcional)
        kafka_status = "not_configured"
        try:
            from kafka import KafkaConsumer
            kafka_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', '')
            if kafka_servers:
                consumer = KafkaConsumer(
                    bootstrap_servers=kafka_servers.split(','),
                    consumer_timeout_ms=2000
                )
                consumer.close()
                kafka_status = "healthy"
        except Exception as e:
            kafka_status = f"unhealthy: {str(e)[:100]}"
        
        return {
            "success": True,
            "status": "operational" if postgres_status == "healthy" else "degraded",
            "services": {
                "postgresql": postgres_status,
                "kafka": kafka_status
            },
            "message": "Tokio AI health check completado"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)[:200]
        }

async def tool_health_check_soar_original() -> Dict[str, Any]:
    """Realiza un check de salud del SOAR mediante múltiples tests
    
    Returns:
        Dict con el estado de salud y resultados de tests
    """
    try:
        logger.info("Ejecutando health check del SOAR")
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
        
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "tests": []
        }
        
        # Test 1: Conectividad básica - GET orgs/{org_id}
        test1 = {"name": "API Connectivity", "status": "unknown", "details": {}}
        try:
            org_result = _make_soar_request('GET', f"orgs/{config['org_id']}")
            if org_result.get('success'):
                test1["status"] = "passed"
                test1["details"] = {"response_time_ms": "OK", "org_id": config['org_id']}
            else:
                test1["status"] = "failed"
                test1["details"] = {"error": org_result.get('error')}
                health_status["overall_status"] = "unhealthy"
        except Exception as e:
            test1["status"] = "failed"
            test1["details"] = {"error": str(e)}
            health_status["overall_status"] = "unhealthy"
        
        health_status["tests"].append(test1)
        
        # Test 2: Listar incidentes (test de lectura)
        test2 = {"name": "Incidents API", "status": "unknown", "details": {}}
        try:
            incidents_result = await tool_list_incidents(limit=5)
            if incidents_result.get('success'):
                test2["status"] = "passed"
                data = incidents_result.get('data', {})
                count = data.get('count', 0) if isinstance(data, dict) else 0
                test2["details"] = {"can_read_incidents": True, "sample_count": count}
            else:
                test2["status"] = "failed"
                test2["details"] = {"error": incidents_result.get('error')}
                health_status["overall_status"] = "unhealthy"
        except Exception as e:
            test2["status"] = "failed"
            test2["details"] = {"error": str(e)}
            health_status["overall_status"] = "unhealthy"
        
        health_status["tests"].append(test2)
        
        # Test 3: Listar playbooks (test de lectura de playbooks - NO CRÍTICO)
        test3 = {"name": "Playbooks API", "status": "unknown", "details": {}, "critical": False}
        try:
            playbooks_result = await tool_list_playbooks(limit=5)
            if playbooks_result.get('success'):
                test3["status"] = "passed"
                playbooks = playbooks_result.get('data', [])
                test3["details"] = {
                    "can_read_playbooks": True, 
                    "total_available": len(playbooks) if isinstance(playbooks, list) else 0
                }
            else:
                test3["status"] = "failed"
                error_msg = playbooks_result.get('error', 'Unknown error')
                test3["details"] = {
                    "error": error_msg,
                    "note": "Este endpoint puede requerir permisos especiales o no estar disponible en esta versión de SOAR"
                }
                # Solo marcar como degraded si otros tests críticos fallan
                if health_status["overall_status"] == "healthy":
                    health_status["overall_status"] = "degraded"
        except Exception as e:
            test3["status"] = "failed"
            test3["details"] = {
                "error": str(e),
                "note": "Endpoint de playbooks no disponible"
            }
            if health_status["overall_status"] == "healthy":
                health_status["overall_status"] = "degraded"
        
        health_status["tests"].append(test3)
        
        # Test 4: Verificar autenticación (test de permisos)
        test4 = {"name": "Authentication", "status": "unknown", "details": {}}
        try:
            if config.get('api_key'):
                test4["status"] = "passed"
                test4["details"] = {"api_key_configured": True, "org_id_configured": bool(config['org_id'])}
            else:
                test4["status"] = "failed"
                test4["details"] = {"error": "API key not configured"}
                health_status["overall_status"] = "unhealthy"
        except Exception as e:
            test4["status"] = "failed"
            test4["details"] = {"error": str(e)}
            health_status["overall_status"] = "unhealthy"
        
        health_status["tests"].append(test4)
        
        # Resumen final
        passed_tests = sum(1 for t in health_status["tests"] if t["status"] == "passed")
        failed_tests = sum(1 for t in health_status["tests"] if t["status"] == "failed")
        critical_tests = [t for t in health_status["tests"] if t.get("critical", True)]
        critical_failed = sum(1 for t in critical_tests if t["status"] == "failed")
        
        health_status["summary"] = {
            "total_tests": len(health_status["tests"]),
            "passed": passed_tests,
            "failed": failed_tests,
            "critical_failed": critical_failed,
            "overall_status": health_status["overall_status"],
            "recommendation": "SOAR operativo" if health_status["overall_status"] == "healthy" else 
                             ("SOAR con funcionalidad limitada" if health_status["overall_status"] == "degraded" else 
                              "SOAR no operativo - revisar inmediatamente")
        }
        
        return {
            "success": True,
            "data": health_status
        }
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return {"success": False, "error": str(e)}


async def tool_search_soar_wiki(query: str, limit: int = 50) -> Dict[str, Any]:
    """Busca en la wiki del SOAR (artículos de documentación/knowledge base)
    
    Args:
        query: Texto a buscar en la wiki
        limit: Límite de resultados
    
    Returns:
        Dict con resultados de búsqueda en la wiki del SOAR
    """
    try:
        logger.info(f"Buscando en wiki del SOAR: {query}")
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado. Es requerido para acceder a la API."}
        
        org_id = config['org_id']
        
        # En IBM Resilient/SOAR, la wiki puede estar en diferentes endpoints:
        # 1. Articles (artículos de knowledge base)
        # 2. Wiki pages
        # 3. Help articles
        # 4. Documentation
        
        # Intentar buscar en articles (knowledge base/articles)
        endpoints_to_try = [
            f'orgs/{org_id}/articles',
            f'orgs/{org_id}/articles/query_paged',
            f'orgs/{org_id}/kb_articles',
            f'orgs/{org_id}/kb_articles/query_paged',
            f'orgs/{org_id}/wiki',
            f'orgs/{org_id}/wiki/query_paged',
            f'orgs/{org_id}/help',
            f'orgs/{org_id}/documentation',
        ]
        
        results = []
        
        for endpoint in endpoints_to_try:
            try:
                # Intentar POST con query_paged
                if 'query_paged' in endpoint or 'articles' in endpoint or 'kb_articles' in endpoint:
                    query_data = {
                        'start': 0,
                        'length': limit,
                        'filters': [{
                            'conditions': [{
                                'field_name': 'name',
                                'method': 'contains',
                                'value': query
                            }]
                        }]
                    }
                    result = _make_soar_request('POST', endpoint, json=query_data)
                else:
                    # Intentar GET
                    result = _make_soar_request('GET', endpoint)
                
                if result.get('success'):
                    data = result.get('data', {})
                    
                    # Formatear según el tipo de respuesta
                    if isinstance(data, dict) and 'data' in data:
                        items = data.get('data', [])
                    elif isinstance(data, list):
                        items = data
                    else:
                        items = []
                    
                    # Filtrar por query si es necesario
                    if query:
                        filtered = []
                        query_lower = query.lower()
                        for item in items:
                            name = str(item.get('name', '')).lower()
                            description = str(item.get('description', '') or item.get('summary', '')).lower()
                            if query_lower in name or query_lower in description:
                                filtered.append(item)
                        items = filtered[:limit]
                    
                    if items:
                        results.extend(items)
                        logger.info(f"Encontrados {len(items)} resultados en {endpoint}")
                        break  # Si encontramos resultados, no necesitamos seguir buscando
            except Exception as e:
                logger.debug(f"Endpoint {endpoint} no funcionó: {e}")
                continue
        
        # Formatear resultados
        formatted_results = []
        for item in results[:limit]:
            formatted_results.append({
                'id': item.get('id'),
                'name': item.get('name'),
                'title': item.get('name') or item.get('title'),
                'summary': item.get('summary') or item.get('description') or item.get('body'),
                'type': item.get('type'),
                'created_date': item.get('created_date'),
                'updated_date': item.get('modified_date') or item.get('updated_date'),
                'url': item.get('url') or f"https://plresilweb1.telecom.com.ar/#articles/{item.get('id')}" if item.get('id') else None
            })
        
        return {
            "success": True,
            "data": {
                "query": query,
                "results": formatted_results,
                "total": len(formatted_results)
            }
        }
        
    except Exception as e:
        logger.error(f"Error buscando en wiki del SOAR: {e}")
        return {"success": False, "error": str(e)}
