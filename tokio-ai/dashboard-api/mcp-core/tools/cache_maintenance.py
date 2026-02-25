"""
Módulo de mantenimiento y limpieza automática de la caché de incidentes
Incluye políticas de retención, limpieza automática y optimización
"""

import logging
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Configuración de retención (puede ser configurado por variables de entorno)
CACHE_RETENTION_DAYS = int(os.getenv('CACHE_RETENTION_DAYS', '730'))  # Por defecto: 2 años
CACHE_CLEANUP_INTERVAL_HOURS = int(os.getenv('CACHE_CLEANUP_INTERVAL_HOURS', '24'))  # Limpiar cada 24 horas
CACHE_MAX_INCIDENTS = int(os.getenv('CACHE_MAX_INCIDENTS', '500000'))  # Máximo 500K incidentes
CACHE_MIN_RETENTION_DAYS = 365  # Mínimo 1 año de retención

def _get_connection():
    """Obtiene conexión a PostgreSQL"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'soar_db'),
        user=os.getenv('POSTGRES_USER', 'soar_user'),
        password=os.getenv('POSTGRES_PASSWORD', 'YOUR_POSTGRES_PASSWORD')
    )


async def cleanup_old_incidents(
    retention_days: Optional[int] = None,
    max_incidents: Optional[int] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Limpia incidentes antiguos de la caché según política de retención
    
    Args:
        retention_days: Días de retención (si None, usa CACHE_RETENTION_DAYS)
        max_incidents: Máximo número de incidentes a mantener (si None, usa CACHE_MAX_INCIDENTS)
        dry_run: Si True, solo calcula qué se eliminaría sin eliminar realmente
    
    Returns:
        Dict con estadísticas de la limpieza
    """
    try:
        retention = retention_days or CACHE_RETENTION_DAYS
        max_inc = max_incidents or CACHE_MAX_INCIDENTS
        
        # No permitir menos de 1 año de retención
        if retention < CACHE_MIN_RETENTION_DAYS:
            retention = CACHE_MIN_RETENTION_DAYS
            logger.warning(f"Retención ajustada al mínimo: {retention} días")
        
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cutoff_date = datetime.now() - timedelta(days=retention)
        cutoff_timestamp = int(cutoff_date.timestamp() * 1000)
        
        # Contar cuántos incidentes se eliminarían
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM incidents_cache
            WHERE create_date < %s
        """, (cutoff_timestamp,))
        
        to_delete_by_date = cursor.fetchone()['count']
        
        # Contar total de incidentes
        cursor.execute("SELECT COUNT(*) as total FROM incidents_cache")
        total_incidents = cursor.fetchone()['total']
        
        # Si excede el máximo, eliminar los más antiguos
        to_delete_by_count = 0
        if total_incidents > max_inc:
            to_delete_by_count = total_incidents - max_inc
        
        total_to_delete = max(to_delete_by_date, to_delete_by_count)
        
        if dry_run:
            logger.info(f"DRY RUN: Se eliminarían {total_to_delete} incidentes")
            cursor.close()
            conn.close()
            return {
                'success': True,
                'dry_run': True,
                'to_delete': total_to_delete,
                'by_date': to_delete_by_date,
                'by_count': to_delete_by_count,
                'total_current': total_incidents,
                'retention_days': retention
            }
        
        # Eliminar incidentes antiguos
        deleted = 0
        if to_delete_by_date > 0:
            cursor.execute("""
                DELETE FROM incidents_cache
                WHERE create_date < %s
            """, (cutoff_timestamp,))
            deleted_by_date = cursor.rowcount
            deleted += deleted_by_date
            logger.info(f"Eliminados {deleted_by_date} incidentes más antiguos que {retention} días")
        
        # Si todavía excede el máximo, eliminar los más antiguos hasta llegar al límite
        if total_incidents - deleted > max_inc:
            remaining = total_incidents - deleted - max_inc
            cursor.execute("""
                DELETE FROM incidents_cache
                WHERE id IN (
                    SELECT id FROM incidents_cache
                    ORDER BY create_date ASC
                    LIMIT %s
                )
            """, (remaining,))
            deleted_by_count = cursor.rowcount
            deleted += deleted_by_count
            logger.info(f"Eliminados {deleted_by_count} incidentes adicionales para respetar límite máximo")
        
        conn.commit()
        
        # Ejecutar VACUUM para optimizar el espacio
        cursor.execute("VACUUM ANALYZE incidents_cache")
        conn.commit()
        
        # Obtener tamaño actualizado
        cursor.execute("SELECT pg_size_pretty(pg_total_relation_size('incidents_cache')) as size")
        new_size = cursor.fetchone()['size']
        
        cursor.close()
        conn.close()
        
        logger.info(f"Limpieza completada: {deleted} incidentes eliminados. Tamaño actual: {new_size}")
        
        return {
            'success': True,
            'deleted': deleted,
            'deleted_by_date': to_delete_by_date,
            'deleted_by_count': to_delete_by_count if total_incidents - deleted > max_inc else 0,
            'remaining': total_incidents - deleted,
            'retention_days': retention,
            'new_size': new_size
        }
    except Exception as e:
        logger.error(f"Error en cleanup_old_incidents: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def get_cache_metrics() -> Dict[str, Any]:
    """Obtiene métricas detalladas de la caché"""
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Tamaño y conteos
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE plan_status = 'A') as abiertos,
                COUNT(*) FILTER (WHERE plan_status = 'C') as cerrados,
                pg_size_pretty(pg_total_relation_size('incidents_cache')) as tamaño_total,
                pg_size_pretty(pg_relation_size('incidents_cache')) as tamaño_tabla,
                MIN(created_at) as mas_antiguo,
                MAX(created_at) as mas_reciente
            FROM incidents_cache
        """)
        stats = cursor.fetchone()
        
        # Distribución por año
        cursor.execute("""
            SELECT 
                EXTRACT(YEAR FROM created_at) as año,
                COUNT(*) as count
            FROM incidents_cache
            GROUP BY EXTRACT(YEAR FROM created_at)
            ORDER BY año DESC
        """)
        by_year = {int(row['año']): row['count'] for row in cursor.fetchall()}
        
        # Capacidad estimada
        cursor.execute("""
            SELECT 
                pg_size_pretty(pg_database_size(current_database())) as tamaño_db,
                pg_size_pretty(pg_database_size(current_database()) - pg_database_size(current_database()) % 1073741824) as tamaño_disponible_estimado
        """)
        db_size = cursor.fetchone()
        
        # Estimar capacidad
        max_estimated = CACHE_MAX_INCIDENTS
        
        cursor.close()
        conn.close()
        
        return {
            'success': True,
            'metrics': {
                'total_incidents': stats['total'],
                'open_incidents': stats['abiertos'],
                'closed_incidents': stats['cerrados'],
                'total_size': stats['tamaño_total'],
                'table_size': stats['tamaño_tabla'],
                'oldest': stats['mas_antiguo'].isoformat() if stats['mas_antiguo'] else None,
                'newest': stats['mas_reciente'].isoformat() if stats['mas_reciente'] else None,
                'by_year': by_year,
                'retention_days': CACHE_RETENTION_DAYS,
                'max_incidents': CACHE_MAX_INCIDENTS,
                'estimated_capacity': max_estimated,
                'db_size': db_size['tamaño_db'] if db_size else 'N/A'
            }
        }
    except Exception as e:
        logger.error(f"Error obteniendo métricas: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def optimize_cache_indexes() -> Dict[str, Any]:
    """Optimiza los índices de la caché"""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        
        logger.info("Optimizando índices de la caché...")
        cursor.execute("REINDEX TABLE incidents_cache")
        cursor.execute("ANALYZE incidents_cache")
        conn.commit()
        
        cursor.close()
        conn.close()
        
        logger.info("Índices optimizados exitosamente")
        
        return {
            'success': True,
            'message': 'Índices optimizados correctamente'
        }
    except Exception as e:
        logger.error(f"Error optimizando índices: {e}")
        return {
            'success': False,
            'error': str(e)
        }
