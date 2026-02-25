"""
Tools específicas para Tokio AI
Usa endpoint interno del dashboard API para consultar PostgreSQL
"""
import logging
import os
import json
import psycopg2
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor
import urllib.parse

logger = logging.getLogger(__name__)
# Usar endpoints internos del dashboard por defecto (más seguro)
DASHBOARD_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000")
if DASHBOARD_URL and os.path.exists("/proc"):  # Verificar que estamos en un entorno con dashboard
    TOKIO_TOOLS_MODE = "http"  # ✅ Usar endpoints internos (no expone PostgreSQL)
else:
    TOKIO_TOOLS_MODE = os.getenv("TOKIO_TOOLS_MODE", "direct").lower()
TOKIO_POSTGRES_USE_PUBLIC_IP = os.getenv("TOKIO_POSTGRES_USE_PUBLIC_IP", "false").lower() == "true"

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

def _get_connection():
    """Obtiene conexión a PostgreSQL para Tokio AI"""
    postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
    postgres_port = os.getenv('POSTGRES_PORT', '5432')
    postgres_db = os.getenv('POSTGRES_DB', 'soc_ai')
    postgres_user = os.getenv('POSTGRES_USER', 'soc_user')
    postgres_password = os.getenv('POSTGRES_PASSWORD') or 'YOUR_POSTGRES_PASSWORD'
    
    # Si el host es un socket Unix de Cloud SQL, usarlo salvo que se fuerce IP pública
    if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME'POSTGRES_HOST_PUBLIC', 'YOUR_IP_ADDRESS')
            logger.info(f"🔧 MCP server: Usando IP pública de Cloud SQL: {postgres_host}")
        else:
            logger.info(f"🔧 MCP server: Usando socket Cloud SQL: {postgres_host}")
    else:
        logger.info(f"🔧 MCP server: Usando host configurado: {postgres_host}")
    
    logger.info(f"🔌 Conectando a PostgreSQL: {postgres_host}:{postgres_port}/{postgres_db} (user: {postgres_user})")
    
    try:
        # Intentar conexión con timeout y keepalives
        conn = psycopg2.connect(
            host=postgres_host,
            port=int(postgres_port),
            database=postgres_db,
            user=postgres_user,
            password=postgres_password,
            connect_timeout=10,  # Timeout aumentado a 10 segundos
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
        logger.info("✅ Conexión a PostgreSQL exitosa")
        return conn
    except psycopg2.OperationalError as e:
        error_msg = str(e)
        logger.error(f"❌ Error conectando a PostgreSQL: {error_msg}")
        # Mensajes más claros y útiles
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise Exception(f"Timeout conectando a PostgreSQL en {postgres_host}:{postgres_port}. El servidor no responde. Verifica que la IP esté autorizada en Cloud SQL.")
        elif "password" in error_msg.lower() or "authentication" in error_msg.lower():
            raise Exception(f"Error de autenticación con PostgreSQL. Verifica usuario ({postgres_user}) y contraseña.")
        elif "connection" in error_msg.lower() or "refused" in error_msg.lower() or "ECONNREFUSED" in error_msg:
            raise Exception(f"No se pudo conectar a PostgreSQL en {postgres_host}:{postgres_port}. Verifica que el servidor esté accesible y que la IP esté autorizada en Cloud SQL.")
        elif "no route to host" in error_msg.lower() or "network is unreachable" in error_msg.lower():
            raise Exception(f"Red no accesible para PostgreSQL en {postgres_host}:{postgres_port}. Verifica configuración de red y firewall.")
        else:
            raise Exception(f"Error de PostgreSQL: {error_msg}")
    except Exception as e:
        logger.error(f"❌ Error inesperado conectando a PostgreSQL: {e}")
        raise

async def tool_search_waf_logs_tokio(
    ip: Optional[str] = None,
    pattern: Optional[str] = None,
    url_pattern: Optional[str] = None,
    host: Optional[str] = None,
    days: int = 7,  # Aumentado de 2 a 7 días por defecto
    limit: int = 1000  # Aumentado de 50 a 1000 para búsquedas de IP
) -> Dict[str, Any]:
    """
    VORTEX 9: Un solo método que abstrae toda la complejidad
    Vibración 3: Elegante en su simplicidad
    Vibración 6: Optimizada con parámetros conservadores
    Vibración 9: Máxima abstracción - DatabaseVortex hace todo
    
    Args:
        ip: IP a buscar (opcional)
        pattern: Patrón de texto a buscar en uri o raw_log (opcional, case-insensitive)
        url_pattern: Patrón específico para buscar solo en la columna uri (opcional)
        host: Host a buscar (opcional, búsqueda parcial)
        days: Días hacia atrás (default: 2 - optimizado)
        limit: Límite de resultados (default: 50 - optimizado)
    """
    try:
        if TOKIO_TOOLS_MODE == "http":
            from .db_vortex import DatabaseVortex
            params = {
                'days': days,
                'limit': limit,
                **({k: v for k, v in {
                    'ip': ip,
                    'pattern': pattern,
                    'url_pattern': url_pattern,
                    'host': host
                }.items() if v})
            }
            return await DatabaseVortex.query(
                endpoint="/api/internal/search-waf-logs",
                params=params,
                max_retries=3,
                retry_delay=1.0
            )
        # Modo directo
        return await _search_waf_logs_direct(
            ip=ip,
            pattern=pattern,
            url_pattern=url_pattern,
            host=host,
            days=days,
            limit=limit
        )
    except ImportError:
        logger.error("❌ DatabaseVortex no disponible, usando fallback")
        return {
            "success": False,
            "error": "DatabaseVortex no está disponible. Verifica la instalación.",
            "logs": []
        }
    except Exception as e:
        logger.error(f"❌ Error en tool_search_waf_logs_tokio: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error consultando logs: {str(e)}",
            "logs": []
        }

async def _search_waf_logs_direct(
    ip: Optional[str] = None,
    pattern: Optional[str] = None,
    url_pattern: Optional[str] = None,
    host: Optional[str] = None,
    days: int = 7,
    limit: int = 100
) -> Dict[str, Any]:
    """Fallback: búsqueda directa en PostgreSQL - MEJORADA para encontrar IPs"""
    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Buscar en ambos campos timestamp y created_at por compatibilidad
        query = """
            SELECT 
                id, timestamp, ip, method, uri, status, blocked, 
                threat_type, severity, created_at, tenant_id, raw_log
            FROM waf_logs
            WHERE (created_at > NOW() - INTERVAL %s OR timestamp > NOW() - INTERVAL %s)
        """
        params = [f'{days} days', f'{days} days']
        
        if ip:
            # Búsqueda flexible: exacta o con ILIKE para variaciones
            query += " AND (ip = %s OR ip::text ILIKE %s)"
            params.extend([ip, f"%{ip}%"])
        
        if host:
            query += " AND host ILIKE %s"
            params.append(f"%{host}%")
        
        if url_pattern:
            query += " AND uri ILIKE %s"
            params.append(f"%{url_pattern}%")
        elif pattern:
            query += " AND (uri ILIKE %s OR raw_log::text ILIKE %s)"
            params.extend([f"%{pattern}%", f"%{pattern}%"])
        
        query += " ORDER BY COALESCE(timestamp, created_at) DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        logs = [dict(row) for row in cursor.fetchall()]
        
        # Si no hay resultados y se buscó una IP, verificar total histórico
        if len(logs) == 0 and ip:
            debug_query = "SELECT COUNT(*) as total FROM waf_logs WHERE ip = %s OR ip::text ILIKE %s"
            cursor.execute(debug_query, [ip, f"%{ip}%"])
            debug_result = cursor.fetchone()
            total_historical = debug_result.get("total", 0) if debug_result else 0
            
            # Convertir datetime a string
            for log in logs:
                for key in ['timestamp', 'created_at']:
                    if log.get(key) and hasattr(log[key], 'isoformat'):
                        log[key] = log[key].isoformat()
            
            return {
                "success": True,
                "logs": [],
                "count": 0,
                "message": f"No se encontraron logs para IP {ip} en los últimos {days} días. Total histórico: {total_historical} registros.",
                "debug": {
                    "ip_searched": ip,
                    "days": days,
                    "total_historical": total_historical
                }
            }
        
        # Convertir datetime a string
        for log in logs:
            for key in ['timestamp', 'created_at']:
                if log.get(key) and hasattr(log[key], 'isoformat'):
                    log[key] = log[key].isoformat()
        
        return {
            "success": True,
            "logs": logs,
            "count": len(logs),
            "message": f"Encontrados {len(logs)} logs de WAF" + (f" para IP {ip}" if ip else "")
        }
    except Exception as e:
        logger.error(f"Error en búsqueda directa: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error de conexión: {str(e)}",
            "logs": []
        }
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

async def _list_episodes_direct(
    limit: int = 50,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """Lista episodios directamente desde PostgreSQL (robusto a columnas faltantes)."""
    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'episodes'
        """)
        columns = {row["column_name"] for row in cursor.fetchall()}
        base_fields = ["episode_id", "src_ip", "decision", "created_at", "total_requests"]
        select_fields = [f for f in base_fields if f in columns]
        optional_fields = ["episode_start", "episode_end", "unique_uris", "request_rate", "risk_score"]
        for field in optional_fields:
            if field in columns:
                select_fields.append(field)
        if not select_fields:
            return {"success": True, "episodes": [], "count": 0, "message": "No hay columnas compatibles en episodes"}
        query = f"SELECT {', '.join(select_fields)} FROM episodes WHERE created_at > NOW() - INTERVAL '7 days'"
        params = []
        if status and "decision" in columns:
            query += " AND decision = %s"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cursor.execute(query, params)
        episodes = [dict(row) for row in cursor.fetchall()]
        for ep in episodes:
            for key in ["episode_start", "episode_end", "created_at"]:
                if ep.get(key) and hasattr(ep[key], "isoformat"):
                    ep[key] = ep[key].isoformat()
        return {
            "success": True,
            "episodes": episodes,
            "count": len(episodes),
            "message": f"Encontrados {len(episodes)} episodios"
        }
    except Exception as e:
        logger.error(f"Error listando episodios directo: {e}", exc_info=True)
        return {"success": False, "error": str(e), "episodes": []}
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

async def _list_blocked_ips_direct(
    limit: int = 50,
    active_only: bool = True
) -> Dict[str, Any]:
    """Lista IPs bloqueadas directamente desde PostgreSQL."""
    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'blocked_ips'
        """)
        columns = {row["column_name"] for row in cursor.fetchall()}
        base_fields = ["id", "ip", "blocked_at", "expires_at", "reason", "active"]
        optional_fields = ["threat_type", "severity", "classification_source"]
        select_fields = [f for f in base_fields if f in columns]
        for field in optional_fields:
            if field in columns:
                select_fields.append(field)
        if not select_fields or "ip" not in columns:
            return {"success": True, "blocked_ips": [], "count": 0, "message": "No hay columnas compatibles en blocked_ips"}
        query = f"SELECT {', '.join(select_fields)} FROM blocked_ips"
        params = []
        if active_only and "active" in columns:
            query += " WHERE active = TRUE AND (expires_at IS NULL OR expires_at > NOW())"
        query += " ORDER BY blocked_at DESC LIMIT %s"
        params.append(limit)
        cursor.execute(query, params)
        blocked = [dict(row) for row in cursor.fetchall()]
        for block in blocked:
            for key in ["blocked_at", "expires_at"]:
                if block.get(key) and hasattr(block[key], "isoformat"):
                    block[key] = block[key].isoformat()
        return {
            "success": True,
            "blocked_ips": blocked,
            "count": len(blocked),
            "message": f"Encontradas {len(blocked)} IPs bloqueadas"
        }
    except Exception as e:
        logger.error(f"Error listando bloqueos directo: {e}", exc_info=True)
        return {"success": False, "error": str(e), "blocked_ips": []}
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

async def _get_summary_direct(days: int = 7) -> Dict[str, Any]:
    """Resumen directo desde PostgreSQL (robusto a tablas faltantes)."""
    conn = None
    cursor = None
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SET LOCAL statement_timeout = '8000ms'")
        days_used = days
        approximate = False
        try:
            cursor.execute("""
                SELECT COUNT(*) as total, 
                       COUNT(DISTINCT ip) as unique_ips,
                       COUNT(*) FILTER (WHERE blocked = TRUE) as blocked_count
                FROM waf_logs
                WHERE created_at > NOW() - INTERVAL %s
            """, (f"{days} days",))
            waf_stats = dict(cursor.fetchone())
        except Exception as e:
            logger.warning(f"Resumen WAF lento, fallback 1d: {e}")
            approximate = True
            days_used = 1
            cursor.execute("""
                SELECT COUNT(*) as total, 
                       COUNT(DISTINCT ip) as unique_ips,
                       COUNT(*) FILTER (WHERE blocked = TRUE) as blocked_count
                FROM waf_logs
                WHERE created_at > NOW() - INTERVAL '1 day'
            """)
            waf_stats = dict(cursor.fetchone())
        episode_stats = {"total": 0, "blocked_episodes": 0}
        try:
            cursor.execute("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE decision = 'BLOCK') as blocked_episodes
                FROM episodes
                WHERE created_at > NOW() - INTERVAL %s
            """, (f"{days_used} days",))
            episode_stats = dict(cursor.fetchone())
        except Exception as e:
            logger.warning(f"Resumen episodios no disponible: {e}")
        blocked_count = 0
        try:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM blocked_ips
                WHERE active = TRUE AND (expires_at IS NULL OR expires_at > NOW())
            """)
            row = cursor.fetchone()
            blocked_count = row.get("total", 0) if isinstance(row, dict) else row[0]
        except Exception as e:
            logger.warning(f"Resumen bloqueos no disponible: {e}")
        return {
            "success": True,
            "summary": {
                "waf_logs": {
                    "total": waf_stats.get("total", 0),
                    "unique_ips": waf_stats.get("unique_ips", 0),
                    "blocked": waf_stats.get("blocked_count", 0)
                },
                "episodes": {
                    "total": episode_stats.get("total", 0),
                    "blocked": episode_stats.get("blocked_episodes", 0)
                },
                "blocked_ips": {
                    "active": blocked_count
                }
            },
            "period_days": days_used,
            "approximate": approximate
        }
    except Exception as e:
        logger.error(f"Error obteniendo resumen directo: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

async def tool_list_episodes_tokio(
    limit: int = 50,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """Lista episodios de seguridad
    
    Args:
        limit: Límite de resultados (default: 50)
        status: Filtrar por estado (opcional)
    """
    try:
        if TOKIO_TOOLS_MODE == "http":
            from .db_vortex import DatabaseVortex
            params = {
                "limit": limit,
                **({"status": status} if status else {})
            }
            return await DatabaseVortex.query(
                endpoint="/api/internal/list-episodes",
                params=params,
                max_retries=3,
                retry_delay=1.0
            )
        try:
            return await _list_episodes_direct(limit=limit, status=status)
        except Exception as e:
            if os.getenv("DASHBOARD_API_BASE_URL"):
                logger.warning(f"Fallback HTTP list-episodes: {e}")
                from .db_vortex import DatabaseVortex
                params = {
                    "limit": limit,
                    **({"status": status} if status else {})
                }
                return await DatabaseVortex.query(
                    endpoint="/api/internal/list-episodes",
                    params=params,
                    max_retries=3,
                    retry_delay=1.0
                )
            raise
    except Exception as e:
        logger.error(f"Error listando episodios: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "episodes": []
        }

async def tool_list_blocked_ips_tokio(
    limit: int = 50,
    active_only: bool = True
) -> Dict[str, Any]:
    """Lista IPs bloqueadas
    
    Args:
        limit: Límite de resultados (default: 50)
        active_only: Solo IPs activas (default: True)
    """
    try:
        if TOKIO_TOOLS_MODE == "http":
            from .db_vortex import DatabaseVortex
            params = {
                "limit": limit,
                "active_only": active_only
            }
            return await DatabaseVortex.query(
                endpoint="/api/internal/list-blocked-ips",
                params=params,
                max_retries=3,
                retry_delay=1.0
            )
        try:
            return await _list_blocked_ips_direct(limit=limit, active_only=active_only)
        except Exception as e:
            if os.getenv("DASHBOARD_API_BASE_URL"):
                logger.warning(f"Fallback HTTP list-blocked-ips: {e}")
                from .db_vortex import DatabaseVortex
                params = {
                    "limit": limit,
                    "active_only": active_only
                }
                return await DatabaseVortex.query(
                    endpoint="/api/internal/list-blocked-ips",
                    params=params,
                    max_retries=3,
                    retry_delay=1.0
                )
            raise
    except Exception as e:
        logger.error(f"Error listando IPs bloqueadas: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "blocked_ips": []
        }

async def tool_block_ip_tokio(
    ip: str,
    duration_hours: int = 24,
    reason: str = "Bloqueo manual desde CLI"
) -> Dict[str, Any]:
    """Bloquea una IP
    
    Args:
        ip: IP a bloquear
        duration_hours: Duración en horas (default: 24)
        reason: Razón del bloqueo
    """
    try:
        from .db_vortex import DatabaseVortex
        params = {
            "ip": ip,
            "duration_hours": duration_hours,
            "reason": reason
        }
        return await DatabaseVortex.query(
            endpoint="/api/internal/block-ip",
            params=params,
            max_retries=3,
            retry_delay=1.0
        )
    except Exception as e:
        logger.error(f"Error bloqueando IP: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def tool_unblock_ip_tokio(
    ip: str,
    reason: str = "Desbloqueo manual desde CLI"
) -> Dict[str, Any]:
    """Desbloquea una IP"""
    try:
        from .db_vortex import DatabaseVortex
        params = {
            "ip": ip,
            "reason": reason
        }
        return await DatabaseVortex.query(
            endpoint="/api/internal/unblock-ip",
            params=params,
            max_retries=3,
            retry_delay=1.0
        )
    except Exception as e:
        logger.error(f"Error desbloqueando IP: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

async def tool_get_summary_tokio(
    days: int = 7
) -> Dict[str, Any]:
    """Obtiene un resumen de ataques, episodios y bloqueos
    
    Args:
        days: Días hacia atrás (default: 7)
    """
    try:
        if TOKIO_TOOLS_MODE == "http":
            from .db_vortex import DatabaseVortex
            return await DatabaseVortex.query(
                endpoint="/api/internal/get-summary",
                params={"days": days},
                max_retries=3,
                retry_delay=1.0
            )
        try:
            return await _get_summary_direct(days=days)
        except Exception as e:
            if os.getenv("DASHBOARD_API_BASE_URL"):
                logger.warning(f"Fallback HTTP get-summary: {e}")
                from .db_vortex import DatabaseVortex
                return await DatabaseVortex.query(
                    endpoint="/api/internal/get-summary",
                    params={"days": days},
                    max_retries=3,
                    retry_delay=1.0
                )
            raise
    except Exception as e:
        logger.error(f"Error obteniendo resumen: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
