"""
Sistema de caché/persistencia para incidentes históricos en PostgreSQL
Permite búsquedas rápidas y eficientes de incidentes históricos
"""

import logging
import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2 import sql

logger = logging.getLogger(__name__)

def _get_connection():
    """Obtiene conexión a PostgreSQL"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'soar_db'),
        user=os.getenv('POSTGRES_USER', 'soar_user'),
        password=os.getenv('POSTGRES_PASSWORD', 'YOUR_POSTGRES_PASSWORD')
    )


def _ensure_schema():
    """Crea el esquema de base de datos si no existe"""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        # Tabla principal de incidentes históricos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents_cache (
                id BIGINT PRIMARY KEY,
                name TEXT,
                description JSONB,
                incident_type_ids JSONB,
                plan_status TEXT,
                severity_code INTEGER,
                owner_id INTEGER,
                owner_principal JSONB,
                reporter TEXT,
                create_date BIGINT,
                discovered_date BIGINT,
                end_date BIGINT,
                created_at TIMESTAMP,
                discovered_at TIMESTAMP,
                closed_at TIMESTAMP,
                tags JSONB,
                properties JSONB,
                members JSONB,
                raw_data JSONB,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT incidents_cache_id_key UNIQUE (id)
            );
        """)
        
        # Índices para búsquedas rápidas
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_create_date 
            ON incidents_cache(create_date);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_plan_status 
            ON incidents_cache(plan_status);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_created_at 
            ON incidents_cache(created_at);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_incident_type_ids 
            ON incidents_cache USING GIN(incident_type_ids);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_name 
            ON incidents_cache USING GIN(to_tsvector('spanish', name));
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_cache_description 
            ON incidents_cache USING GIN(to_tsvector('spanish', description::text));
        """)
        
        # Tabla de metadatos de sincronización
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents_sync_metadata (
                sync_id SERIAL PRIMARY KEY,
                last_sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_type TEXT, -- 'full', 'incremental', 'manual'
                incidents_synced INTEGER DEFAULT 0,
                sync_duration_seconds NUMERIC,
                status TEXT, -- 'success', 'failed', 'in_progress'
                error_message TEXT,
                sync_range_start BIGINT,
                sync_range_end BIGINT
            );
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Esquema de base de datos verificado/creado exitosamente")
        return True
    except Exception as e:
        logger.error(f"Error creando esquema: {e}")
        return False


def _normalize_incident_data(incident: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza los datos de un incidente para almacenamiento"""
    # Extraer incident_type_ids como array de números
    incident_type_ids = []
    for tid in incident.get('incident_type_ids', []):
        if isinstance(tid, dict):
            val = tid.get('id') or tid.get('value') or tid.get('type_id')
        else:
            val = tid
        if val is not None:
            try:
                incident_type_ids.append(int(val))
            except (ValueError, TypeError):
                pass
    
    # Convertir fechas a timestamps
    create_date = incident.get('create_date')
    discovered_date = incident.get('discovered_date')
    end_date = incident.get('end_date')
    
    created_at = None
    discovered_at = None
    closed_at = None
    
    if create_date:
        try:
            created_at = datetime.fromtimestamp(create_date / 1000.0) if isinstance(create_date, (int, float)) else None
        except:
            pass
    
    if discovered_date:
        try:
            discovered_at = datetime.fromtimestamp(discovered_date / 1000.0) if isinstance(discovered_date, (int, float)) else None
        except:
            pass
    
    if end_date:
        try:
            closed_at = datetime.fromtimestamp(end_date / 1000.0) if isinstance(end_date, (int, float)) else None
        except:
            pass
    
    return {
        'id': incident.get('id'),
        'name': incident.get('name'),
        'description': json.dumps(incident.get('description', {})) if incident.get('description') else None,
        'incident_type_ids': json.dumps(incident_type_ids),
        'plan_status': incident.get('plan_status'),
        'severity_code': incident.get('severity_code'),
        'owner_id': incident.get('owner_id'),
        'owner_principal': json.dumps(incident.get('owner_principal', {})) if incident.get('owner_principal') else None,
        'reporter': incident.get('reporter'),
        'create_date': create_date,
        'discovered_date': discovered_date,
        'end_date': end_date,
        'created_at': created_at,
        'discovered_at': discovered_at,
        'closed_at': closed_at,
        'tags': json.dumps(incident.get('tags', [])) if incident.get('tags') else None,
        'properties': json.dumps(incident.get('properties', {})) if incident.get('properties') else None,
        'members': json.dumps(incident.get('members', [])) if incident.get('members') else None,
        'raw_data': json.dumps(incident),  # Guardar datos completos
        'updated_at': datetime.now()
    }


async def sync_incidents_to_cache(
    incidents: List[Dict[str, Any]],
    sync_type: str = 'manual'
) -> Dict[str, Any]:
    """Sincroniza una lista de incidentes a la base de datos de caché
    
    Args:
        incidents: Lista de incidentes a sincronizar
        sync_type: Tipo de sincronización ('full', 'incremental', 'manual')
    
    Returns:
        Dict con el resultado de la sincronización
    """
    try:
        start_time = datetime.now()
        _ensure_schema()
        
        conn = _get_connection()
        cursor = conn.cursor()
        
        synced_count = 0
        errors = []
        
        for incident in incidents:
            try:
                normalized = _normalize_incident_data(incident)
                incident_id = normalized['id']
                
                if not incident_id:
                    continue
                
                # Usar INSERT ... ON CONFLICT para actualizar si existe
                insert_query = sql.SQL("""
                    INSERT INTO incidents_cache (
                        id, name, description, incident_type_ids, plan_status,
                        severity_code, owner_id, owner_principal, reporter,
                        create_date, discovered_date, end_date,
                        created_at, discovered_at, closed_at,
                        tags, properties, members, raw_data, updated_at
                    ) VALUES (
                        %(id)s, %(name)s, %(description)s::jsonb, %(incident_type_ids)s::jsonb,
                        %(plan_status)s, %(severity_code)s, %(owner_id)s,
                        %(owner_principal)s::jsonb, %(reporter)s,
                        %(create_date)s, %(discovered_date)s, %(end_date)s,
                        %(created_at)s, %(discovered_at)s, %(closed_at)s,
                        %(tags)s::jsonb, %(properties)s::jsonb, %(members)s::jsonb,
                        %(raw_data)s::jsonb, %(updated_at)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        incident_type_ids = EXCLUDED.incident_type_ids,
                        plan_status = EXCLUDED.plan_status,
                        severity_code = EXCLUDED.severity_code,
                        owner_id = EXCLUDED.owner_id,
                        owner_principal = EXCLUDED.owner_principal,
                        reporter = EXCLUDED.reporter,
                        create_date = EXCLUDED.create_date,
                        discovered_date = EXCLUDED.discovered_date,
                        end_date = EXCLUDED.end_date,
                        created_at = EXCLUDED.created_at,
                        discovered_at = EXCLUDED.discovered_at,
                        closed_at = EXCLUDED.closed_at,
                        tags = EXCLUDED.tags,
                        properties = EXCLUDED.properties,
                        members = EXCLUDED.members,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = EXCLUDED.updated_at
                """)
                
                cursor.execute(insert_query, normalized)
                synced_count += 1
            except Exception as e:
                errors.append(f"Error sincronizando incidente {incident.get('id')}: {e}")
                logger.warning(f"Error sincronizando incidente {incident.get('id')}: {e}")
        
        conn.commit()
        
        # Registrar metadatos de sincronización
        duration = (datetime.now() - start_time).total_seconds()
        cursor.execute("""
            INSERT INTO incidents_sync_metadata (
                sync_type, incidents_synced, sync_duration_seconds, status, error_message
            ) VALUES (%s, %s, %s, %s, %s)
        """, (
            sync_type,
            synced_count,
            duration,
            'success' if not errors else 'failed',
            json.dumps(errors) if errors else None
        ))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return {
            'success': True,
            'synced_count': synced_count,
            'total_incidents': len(incidents),
            'duration_seconds': duration,
            'errors': errors if errors else None
        }
    except Exception as e:
        logger.error(f"Error en sync_incidents_to_cache: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def search_incidents_from_cache(
    incident_type_ids: Optional[List[int]] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Busca incidentes en la base de datos de caché
    
    Args:
        incident_type_ids: Lista de IDs de tipo de incidente a buscar
        status: Estado del incidente ('open', 'closed', 'A', 'C')
        start_date: Fecha de inicio en formato YYYY-MM-DD o timestamp
        end_date: Fecha de fin en formato YYYY-MM-DD o timestamp
        query: Texto a buscar en nombre/descripción
        limit: Límite de resultados
        offset: Offset para paginación
    
    Returns:
        Dict con los incidentes encontrados
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        conditions = []
        params = []
        param_counter = 1
        
        # Filtrar por tipo de incidente
        if incident_type_ids:
            type_conditions = []
            for type_id in incident_type_ids:
                type_conditions.append(f"incident_type_ids @> %s::jsonb")
                params.append(json.dumps([type_id]))
            if type_conditions:
                conditions.append(f"({' OR '.join(type_conditions)})")
        
        # Filtrar por estado
        if status:
            status_lower = status.lower()
            if status_lower in ['open', 'abierto', 'a', 'active']:
                conditions.append("plan_status = 'A'")
            elif status_lower in ['closed', 'cerrado', 'c']:
                conditions.append("plan_status = 'C'")
            else:
                conditions.append(f"plan_status = %s")
                params.append(status)
        
        # Filtrar por fecha
        if start_date:
            try:
                if len(start_date) == 10:  # YYYY-MM-DD
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    conditions.append(f"created_at >= %s")
                    params.append(start_dt)
                else:
                    # Timestamp
                    start_ts = int(float(start_date) * 1000) if float(start_date) < 1e12 else int(start_date)
                    conditions.append(f"create_date >= %s")
                    params.append(start_ts)
            except (ValueError, TypeError):
                logger.warning(f"Formato de fecha inválido para start_date: {start_date}")
        
        if end_date:
            try:
                if len(end_date) == 10:  # YYYY-MM-DD
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    conditions.append(f"created_at <= %s")
                    params.append(end_dt)
                else:
                    # Timestamp
                    end_ts = int(float(end_date) * 1000) if float(end_date) < 1e12 else int(end_date)
                    conditions.append(f"create_date <= %s")
                    params.append(end_ts)
            except (ValueError, TypeError):
                logger.warning(f"Formato de fecha inválido para end_date: {end_date}")
        
        # Búsqueda de texto
        if query:
            conditions.append("""
                (to_tsvector('spanish', name) @@ plainto_tsquery('spanish', %s)
                OR to_tsvector('spanish', description::text) @@ plainto_tsquery('spanish', %s))
            """)
            params.extend([query, query])
        
        # Construir query
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Contar total
        count_query = f"SELECT COUNT(*) FROM incidents_cache WHERE {where_clause}"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()['count']
        
        # Obtener resultados
        select_query = f"""
            SELECT 
                id, name, description, incident_type_ids, plan_status,
                severity_code, owner_id, owner_principal, reporter,
                create_date, discovered_date, end_date,
                created_at, discovered_at, closed_at,
                tags, properties, members, raw_data
            FROM incidents_cache
            WHERE {where_clause}
            ORDER BY create_date DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        cursor.execute(select_query, params)
        
        rows = cursor.fetchall()
        
        # Convertir a formato de incidente (con manejo robusto de JSON)
        incidents = []
        for row in rows:
            # Manejo seguro de campos JSON
            description = {}
            if row['description']:
                try:
                    if isinstance(row['description'], str):
                        description = json.loads(row['description'])
                    else:
                        description = row['description']
                except (json.JSONDecodeError, TypeError):
                    description = {}
            
            incident_type_ids = []
            if row['incident_type_ids']:
                try:
                    if isinstance(row['incident_type_ids'], str):
                        incident_type_ids = json.loads(row['incident_type_ids'])
                    else:
                        incident_type_ids = row['incident_type_ids']
                except (json.JSONDecodeError, TypeError):
                    incident_type_ids = []
            
            owner_principal = {}
            if row['owner_principal']:
                try:
                    if isinstance(row['owner_principal'], str):
                        owner_principal = json.loads(row['owner_principal'])
                    else:
                        owner_principal = row['owner_principal']
                except (json.JSONDecodeError, TypeError):
                    owner_principal = {}
            
            incident = {
                'id': row['id'],
                'name': row['name'],
                'description': description,
                'incident_type_ids': incident_type_ids,
                'plan_status': row['plan_status'],
                'severity_code': row['severity_code'],
                'owner_id': row['owner_id'],
                'owner_principal': owner_principal,
                'reporter': row['reporter'],
                'create_date': row['create_date'],
                'discovered_date': row['discovered_date'],
                'end_date': row['end_date'],
            }
            incidents.append(incident)
        
        cursor.close()
        conn.close()
        
        return {
            'success': True,
            'data': {
                'data': incidents,
                'count': len(incidents),
                'total': total_count
            }
        }
    except Exception as e:
        logger.error(f"Error buscando en caché: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def sync_incidents_from_soar_api(
    days_back: int = 365,
    incident_type_ids: Optional[List[int]] = None,
    max_incidents: int = 50000,
    batch_size: int = 2000
) -> Dict[str, Any]:
    """Sincroniza incidentes históricos desde la API SOAR a la base de datos de caché
    
    Args:
        days_back: Cuántos días hacia atrás sincronizar (default: 365 días = 1 año)
        incident_type_ids: Lista de IDs de tipo de incidente a sincronizar (opcional, si None sincroniza todos)
        max_incidents: Máximo número de incidentes a sincronizar (default: 50000)
        batch_size: Tamaño de lote para procesar incidentes (default: 2000)
    
    Returns:
        Dict con el resultado de la sincronización
    """
    try:
        from tools.soar_tools import _get_soar_config, _make_soar_request, tool_list_incidents
        
        logger.info(f"Iniciando sincronización de incidentes históricos: {days_back} días atrás, max={max_incidents}, tipo={incident_type_ids}")
        start_time = datetime.now()
        _ensure_schema()
        
        config = _get_soar_config()
        if not config['org_id']:
            return {"success": False, "error": "SOAR_ORG_ID no está configurado"}
        
        # Calcular fecha de inicio
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        all_incidents = []
        
        logger.info(f"Sincronizando incidentes desde {start_date.date()} hasta {end_date.date()}")
        
        # Si hay filtro por tipo, usar tool_list_incidents que ya tiene la lógica optimizada
        if incident_type_ids and len(incident_type_ids) > 0:
            logger.info(f"Usando búsqueda optimizada por tipo de incidente: {incident_type_ids}")
            # Usar tool_list_incidents que ya filtra correctamente por tipo
            # Buscar más incidentes para asegurar que encontramos todos
            search_limit = min(max_incidents, 5000)  # Limitar a 5000 para tipo específico
            
            result = await tool_list_incidents(
                incident_type=str(incident_type_ids[0]),
                start_date=start_date_str,
                end_date=end_date_str,
                limit=search_limit,
                use_cache=False,  # No usar caché para sincronizar
                auto_paginate=True  # Usar paginación automática
            )
            
            if result.get('success'):
                incidents = result.get('data', {}).get('data', [])
                all_incidents = incidents[:max_incidents]  # Limitar al máximo solicitado
                logger.info(f"Encontrados {len(all_incidents)} incidentes de tipo {incident_type_ids[0]}")
            else:
                logger.error(f"Error en búsqueda por tipo: {result.get('error')}")
                return result
        else:
            # Sin filtro por tipo: obtener todos los incidentes
            current_offset = 0
            page_size = batch_size
            total_fetched = 0
            start_timestamp = int(start_date.timestamp() * 1000)
            
            # Paginación para obtener todos los incidentes
            while total_fetched < max_incidents:
                query_data = {
                    'start': current_offset,
                    'length': page_size
                }
                
                logger.info(f"Obteniendo página: offset={current_offset}, length={page_size}")
                result = _make_soar_request('POST', f"orgs/{config['org_id']}/incidents/query_paged", json=query_data)
                
                if not result.get('success') or not result.get('data'):
                    logger.warning(f"No se pudo obtener más incidentes en offset {current_offset}")
                    break
                
                data = result['data']
                incidents = data.get('data', [])
                
                if not incidents:
                    logger.info("No hay más incidentes para sincronizar")
                    break
                
                # Filtrar por fecha
                filtered_incidents = []
                for inc in incidents:
                    create_date = inc.get('create_date')
                    if create_date:
                        inc_create_ts = create_date if isinstance(create_date, int) else int(create_date)
                        if inc_create_ts >= start_timestamp:
                            filtered_incidents.append(inc)
                
                if filtered_incidents:
                    all_incidents.extend(filtered_incidents)
                    total_fetched += len(filtered_incidents)
                    logger.info(f"Agregados {len(filtered_incidents)} incidentes (total: {total_fetched})")
                
                # Si recibimos menos incidentes que el tamaño de página, terminamos
                if len(incidents) < page_size:
                    break
                
                current_offset += page_size
                
                # Si ya tenemos suficientes incidentes, parar
                if total_fetched >= max_incidents:
                    break
        
        # Sincronizar todos los incidentes obtenidos
        if all_incidents:
            logger.info(f"Sincronizando {len(all_incidents)} incidentes a la base de datos...")
            sync_result = await sync_incidents_to_cache(all_incidents, sync_type='full')
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return {
                'success': True,
                'synced_count': sync_result.get('synced_count', 0),
                'total_fetched': total_fetched,
                'duration_seconds': duration,
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'errors': sync_result.get('errors')
            }
        else:
            return {
                'success': True,
                'synced_count': 0,
                'total_fetched': 0,
                'message': 'No se encontraron incidentes para sincronizar en el rango especificado'
            }
    except Exception as e:
        logger.error(f"Error en sync_incidents_from_soar_api: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def get_cache_stats() -> Dict[str, Any]:
    """Obtiene estadísticas de la caché de incidentes (optimizado para evitar timeouts)"""
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Usar estimación rápida de PostgreSQL para COUNT en tablas grandes
        # Esto es mucho más rápido que COUNT(*) en tablas grandes
        try:
            cursor.execute("""
                SELECT reltuples::BIGINT as estimate 
                FROM pg_class 
                WHERE relname = 'incidents_cache'
            """)
            total_estimate = cursor.fetchone()['estimate']
            # Si la estimación es muy baja o 0, hacer COUNT real pero con timeout
            if total_estimate and total_estimate > 0:
                total = total_estimate
                use_estimate = True
            else:
                # Fallback a COUNT real si la estimación no está disponible
                cursor.execute("SELECT COUNT(*) as total FROM incidents_cache")
                total = cursor.fetchone()['total']
                use_estimate = False
        except:
            # Si falla la estimación, usar COUNT real
            cursor.execute("SELECT COUNT(*) as total FROM incidents_cache")
            total = cursor.fetchone()['total']
            use_estimate = False
        
        # Por estado - optimizado con límite de tiempo implícito
        # Usar muestreo si la tabla es muy grande
        try:
            if use_estimate and total > 100000:
                # Para tablas muy grandes, usar muestreo
                cursor.execute("""
                    SELECT plan_status, COUNT(*) as count
                    FROM (
                        SELECT plan_status 
                        FROM incidents_cache 
                        TABLESAMPLE SYSTEM (1)
                    ) sampled
                    GROUP BY plan_status
                """)
                by_status_raw = cursor.fetchall()
                # Escalar los resultados al tamaño real estimado
                sample_size = sum(row['count'] for row in by_status_raw)
                by_status = {}
                if sample_size > 0:
                    scale_factor = total / sample_size
                    for row in by_status_raw:
                        by_status[row['plan_status']] = int(row['count'] * scale_factor)
                else:
                    by_status = {}
            else:
                cursor.execute("""
                    SELECT plan_status, COUNT(*) as count
                    FROM incidents_cache
                    GROUP BY plan_status
                """)
                by_status = {row['plan_status']: row['count'] for row in cursor.fetchall()}
        except Exception as e:
            logger.warning(f"Error obteniendo estadísticas por estado: {e}")
            by_status = {}
        
        # Rango de fechas - usar índices para ser rápido
        try:
            cursor.execute("""
                SELECT 
                    MIN(created_at) as oldest,
                    MAX(created_at) as newest
                FROM incidents_cache
            """)
            date_range = cursor.fetchone()
        except Exception as e:
            logger.warning(f"Error obteniendo rango de fechas: {e}")
            date_range = {'oldest': None, 'newest': None}
        
        # Última sincronización
        try:
            cursor.execute("""
                SELECT last_sync_at, sync_type, incidents_synced, status
                FROM incidents_sync_metadata
                ORDER BY last_sync_at DESC
                LIMIT 1
            """)
            last_sync = cursor.fetchone()
        except Exception as e:
            logger.warning(f"Error obteniendo última sincronización: {e}")
            last_sync = None
        
        cursor.close()
        conn.close()
        
        return {
            'success': True,
            'data': {
                'total_incidents': total,
                'by_status': by_status,
                'date_range': {
                    'oldest': date_range['oldest'].isoformat() if date_range['oldest'] else None,
                    'newest': date_range['newest'].isoformat() if date_range['newest'] else None
                },
                'last_sync': {
                    'at': last_sync['last_sync_at'].isoformat() if last_sync and last_sync['last_sync_at'] else None,
                    'type': last_sync['sync_type'] if last_sync else None,
                    'incidents_synced': last_sync['incidents_synced'] if last_sync else None,
                    'status': last_sync['status'] if last_sync else None
                }
            }
        }
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        return {
            'success': False,
            'error': str(e)
        }
