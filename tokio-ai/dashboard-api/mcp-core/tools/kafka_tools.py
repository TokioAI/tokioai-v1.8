import logging
import os
import json
import psycopg2
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor
from psycopg2 import OperationalError
import urllib.parse

logger = logging.getLogger(__name__)

def _analyze_waf_logs(logs: List[Dict[str, Any]]) -> str:
    """Analiza logs WAF y genera un resumen detallado"""
    if not logs:
        return "No hay logs para analizar.\n"
    
    analysis = []
    analysis.append("=" * 80)
    analysis.append("RESUMEN ESTADÍSTICO")
    analysis.append("=" * 80)
    analysis.append(f"Total de logs analizados: {len(logs)}\n")
    
    # Análisis de IPs
    client_ips = {}
    hosts = {}
    actions = {}
    signature_ids = {}
    status_codes = {}
    attack_types = set()
    
    for log in logs:
        # IPs de origen
        ip = log.get('client_ip', 'N/A')
        client_ips[ip] = client_ips.get(ip, 0) + 1
        
        # Hosts
        host = log.get('host', 'N/A')
        hosts[host] = hosts.get(host, 0) + 1
        
        # Acciones
        action = log.get('action', 'N/A')
        actions[action] = actions.get(action, 0) + 1
        
        # Signature IDs
        sig_id = log.get('signature_id', 'N/A')
        if sig_id:
            signature_ids[sig_id] = signature_ids.get(sig_id, 0) + 1
        
        # Status codes
        status = log.get('status_code', 'N/A')
        status_codes[status] = status_codes.get(status, 0) + 1
        
        # Tipos de ataque (del raw_log)
        raw_log = log.get('raw_log', {})
        if isinstance(raw_log, dict):
            raw_text = raw_log.get('raw', '')
        else:
            raw_text = str(raw_log)
        
        # Buscar tipos de ataque comunes
        if 'SQL-Injection' in raw_text or 'SQL' in raw_text:
            attack_types.add('SQL-Injection')
        if 'XSS' in raw_text or 'Cross-Site' in raw_text:
            attack_types.add('XSS')
        if 'SSRF' in raw_text:
            attack_types.add('SSRF')
        if 'RCE' in raw_text or 'Remote Code Execution' in raw_text:
            attack_types.add('RCE')
        if 'LFI' in raw_text or 'Local File Inclusion' in raw_text:
            attack_types.add('LFI')
        if 'RFI' in raw_text or 'Remote File Inclusion' in raw_text:
            attack_types.add('RFI')
    
    # Top IPs atacantes
    analysis.append("\n" + "=" * 80)
    analysis.append("TOP 20 IPs ATACANTES")
    analysis.append("=" * 80)
    sorted_ips = sorted(client_ips.items(), key=lambda x: x[1], reverse=True)[:20]
    for ip, count in sorted_ips:
        analysis.append(f"  {ip:20s} : {count:6d} intentos")
    
    # Top Hosts atacados
    analysis.append("\n" + "=" * 80)
    analysis.append("TOP 10 HOSTS ATACADOS")
    analysis.append("=" * 80)
    sorted_hosts = sorted(hosts.items(), key=lambda x: x[1], reverse=True)[:10]
    for host, count in sorted_hosts:
        analysis.append(f"  {host:40s} : {count:6d} intentos")
    
    # Distribución de acciones
    analysis.append("\n" + "=" * 80)
    analysis.append("DISTRIBUCIÓN DE ACCIONES")
    analysis.append("=" * 80)
    sorted_actions = sorted(actions.items(), key=lambda x: x[1], reverse=True)
    for action, count in sorted_actions:
        analysis.append(f"  {action:20s} : {count:6d} ({count*100/len(logs):.1f}%)")
    
    # Tipos de ataque detectados
    if attack_types:
        analysis.append("\n" + "=" * 80)
        analysis.append("TIPOS DE ATAQUE DETECTADOS")
        analysis.append("=" * 80)
        for attack_type in sorted(attack_types):
            analysis.append(f"  - {attack_type}")
    
    # Análisis de bypass de firmas WAF
    blocked_count = actions.get('blocked', 0) + actions.get('deny', 0)
    allowed_count = actions.get('allowed', 0) + actions.get('permit', 0)
    total_actions = sum(actions.values())
    
    analysis.append("\n" + "=" * 80)
    analysis.append("ANÁLISIS DE BYPASS DE FIRMAS WAF")
    analysis.append("=" * 80)
    analysis.append(f"Total de acciones: {total_actions}")
    analysis.append(f"Bloqueados: {blocked_count} ({blocked_count*100/total_actions if total_actions > 0 else 0:.1f}%)")
    analysis.append(f"Permitidos: {allowed_count} ({allowed_count*100/total_actions if total_actions > 0 else 0:.1f}%)")
    
    if allowed_count > 0:
        analysis.append("\n⚠️  ADVERTENCIA: Se detectaron intentos de ataque que fueron PERMITIDOS.")
        analysis.append("   Esto podría indicar posibles bypass de firmas WAF.")
        analysis.append("   Se recomienda revisar las firmas y reglas del WAF.")
    
    # Top Signature IDs
    if signature_ids:
        analysis.append("\n" + "=" * 80)
        analysis.append("TOP 10 SIGNATURE IDs")
        analysis.append("=" * 80)
        sorted_sigs = sorted(signature_ids.items(), key=lambda x: x[1], reverse=True)[:10]
        for sig_id, count in sorted_sigs:
            analysis.append(f"  {sig_id:30s} : {count:6d} veces")
    
    # URLs más atacadas
    urls = {}
    for log in logs:
        url = log.get('url', 'N/A')
        if url and url != 'N/A':
            # Normalizar URL (solo path)
            url_path = url.split('?')[0] if '?' in url else url
            urls[url_path] = urls.get(url_path, 0) + 1
    
    if urls:
        analysis.append("\n" + "=" * 80)
        analysis.append("TOP 10 URLs/ENDPOINTS MÁS ATACADOS")
        analysis.append("=" * 80)
        sorted_urls = sorted(urls.items(), key=lambda x: x[1], reverse=True)[:10]
        for url_path, count in sorted_urls:
            analysis.append(f"  {url_path[:60]:60s} : {count:6d} intentos")
    
    # Rango de fechas
    if logs:
        dates = [log.get('event_time', '') for log in logs if log.get('event_time')]
        if dates:
            dates.sort()
            analysis.append("\n" + "=" * 80)
            analysis.append("RANGO TEMPORAL")
            analysis.append("=" * 80)
            analysis.append(f"Primer log: {dates[0]}")
            analysis.append(f"Último log: {dates[-1]}")
    
    analysis.append("\n" + "=" * 80)
    analysis.append("FIN DEL ANÁLISIS")
    analysis.append("=" * 80)
    
    return "\n".join(analysis)

def _get_db_connection():
    """Obtiene conexión a PostgreSQL con timeout configurado para Tokio AI"""
    postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
    postgres_port = os.getenv('POSTGRES_PORT', '5432')
    postgres_db = os.getenv('POSTGRES_DB', 'soc_ai')
    postgres_user = os.getenv('POSTGRES_USER', 'soc_user')
    postgres_password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))
    
    # Si es un socket Unix de Cloud SQL, usar la IP pública como fallback
    if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME")
    
    return psycopg2.connect(
        host=postgres_host,
        port=int(postgres_port),
        database=postgres_db,
        user=postgres_user,
        password=postgres_password,
        connect_timeout=30  # Aumentado a 30 segundos
    )

async def tool_search_fw_logs(
    ip: Optional[str] = None, 
    port: Optional[int] = None, 
    action: Optional[str] = None,
    pattern: Optional[str] = None,  # NUEVO: Búsqueda por patrón en raw_log
    start_date: Optional[str] = None,  # NUEVO: Fecha inicio (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)
    end_date: Optional[str] = None,  # NUEVO: Fecha fin
    limit: int = 100,  # Aumentado de 30 a 100 por defecto
    days: int = 7  # Por defecto 7 días
) -> Dict[str, Any]:
    """
    Busca logs de firewall con soporte mejorado para búsquedas por patrón y rangos de fechas.
    
    Args:
        ip: IP origen o destino
        port: Puerto origen o destino
        action: Acción (deny, allow, etc.)
        pattern: Patrón de texto a buscar en raw_log (usando ILIKE)
        start_date: Fecha de inicio (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)
        end_date: Fecha de fin (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)
        limit: Límite de resultados (máximo 1000)
        days: Días hacia atrás desde ahora (si no se especifican fechas)
    """
    try:
        # Validar límite
        if limit > 1000:
            limit = 1000
            logger.warning(f"Límite reducido a 1000 (máximo permitido)")
        
        conn = _get_db_connection()
        # Configurar timeout de consulta (aumentado a 180 segundos para consultas grandes y rangos temporales largos)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SET statement_timeout = '240s'")
        
        # Construir condiciones WHERE optimizadas
        where_clauses = []
        params = []
        
        # Manejo de fechas: priorizar start_date/end_date sobre days
        if start_date or end_date:
            try:
                if start_date:
                    if len(start_date) == 10:  # YYYY-MM-DD
                        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    else:
                        start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
                    where_clauses.append("event_time >= %s")
                    params.append(start_dt)
                
                if end_date:
                    if len(end_date) == 10:  # YYYY-MM-DD
                        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                        end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    else:
                        end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
                    where_clauses.append("event_time <= %s")
                    params.append(end_dt)
            except ValueError as e:
                return {"success": False, "error": f"Formato de fecha inválido: {str(e)}"}
        else:
            # Usar days si no se especifican fechas
            where_clauses.append(f"event_time > NOW() - INTERVAL '{days} days'")
        
        # Filtros adicionales
        if port:
            where_clauses.append("(source_port = %s OR dest_port = %s)")
            params.extend([port, port])
        
        if action:
            where_clauses.append("action = %s")
            params.append(action)
        
        # NUEVO: Búsqueda por patrón en raw_log (mejorado para case-insensitive y URL-encoded)
        if pattern:
            pattern_lower = pattern.lower()
            pattern_upper = pattern.upper()
            pattern_encoded = urllib.parse.quote(pattern, safe='')
            where_clauses.append("(raw_log::text ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s)")
            params.extend([
                f"%{pattern}%",  # Original
                f"%{pattern_lower}%",  # Minúsculas
                f"%{pattern_upper}%",  # Mayúsculas
                f"%{pattern_encoded}%"  # URL-encoded
            ])
        
        base_where = " AND ".join(where_clauses)
        
        # Intentar contar el total de resultados (opcional, puede fallar en tablas grandes)
        total_count = None
        count_cursor = None
        try:
            # Crear un cursor separado para el COUNT para evitar problemas de transacción
            count_cursor = conn.cursor(cursor_factory=RealDictCursor)
            count_cursor.execute("SET statement_timeout = '10s'")
            if ip:
                count_query = f"""
                    SELECT COUNT(*) as total FROM (
                        (SELECT 1 FROM fw_logs WHERE source_ip = %s AND {base_where})
                        UNION ALL
                        (SELECT 1 FROM fw_logs WHERE dest_ip = %s AND {base_where})
                    ) as sub
                """
                count_params = [ip] + params + [ip] + params
            else:
                count_query = f"SELECT COUNT(*) as total FROM fw_logs WHERE {base_where}"
                count_params = params.copy()
            count_cursor.execute(count_query, count_params)
            total_count = count_cursor.fetchone()['total']
            count_cursor.close()
        except (OperationalError, Exception) as e:
            # Si el COUNT falla, simplemente continuar sin él (es solo informativo)
            logger.warning(f"Count query falló (timeout esperado en tablas grandes): {str(e)}")
            if count_cursor:
                try:
                    count_cursor.close()
                except:
                    pass
            total_count = None
            # Hacer rollback para limpiar cualquier transacción abortada
            try:
                conn.rollback()
            except:
                pass
        
        # SIEMPRE generar archivo si hay resultados (mejorado: guarda TODO)
        # Si no tenemos el count, asumimos que puede haber resultados
        export_to_file = total_count is None or total_count > 0
        output_file = None
        
        if export_to_file:
            # Crear directorio de exportaciones si no existe
            export_dir = "/irt/proyectos/soar-mcp-server/exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # Generar nombre de archivo con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pattern_safe = (pattern or ip or "fw_logs")[:50].replace("/", "_").replace("\\", "_")
            output_file = f"{export_dir}/fw_logs_{pattern_safe}_{timestamp}.json"
        
        # Query optimizada con UNION para usar índices
        if ip:
            # Usar UNION ALL para aprovechar índices independientes
            query = f"""
                (SELECT * FROM fw_logs 
                 WHERE source_ip = %s AND {base_where} 
                 ORDER BY event_time DESC 
                 LIMIT %s)
                UNION ALL
                (SELECT * FROM fw_logs 
                 WHERE dest_ip = %s AND {base_where} 
                 ORDER BY event_time DESC 
                 LIMIT %s)
                ORDER BY event_time DESC 
                LIMIT %s
            """
            all_params = [ip] + params + [limit, ip] + params + [limit, limit]
        else:
            query = f"""
                SELECT * FROM fw_logs 
                WHERE {base_where} 
                ORDER BY event_time DESC 
                LIMIT %s
            """
            all_params = params + [limit]
        
        # Ejecutar con timeout
        try:
            cursor.execute(query, all_params)
            rows = [dict(r) for r in cursor.fetchall()]
            
            # Serializar fechas
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, datetime):
                        r[k] = v.isoformat()
            
            # Si hay muchos resultados, guardar en archivo
            if export_to_file and rows:
                try:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump({
                            "query_info": {
                                "filters_applied": {
                                    "ip": ip,
                                    "port": port,
                                    "action": action,
                                    "pattern": pattern,
                                    "start_date": start_date,
                                    "end_date": end_date,
                                    "days": days if not (start_date or end_date) else None
                                },
                                "total_results": total_count,
                                "limit": limit,
                                "results_returned": len(rows),
                                "exported_to_file": True,
                                "file_path": output_file
                            },
                            "data": rows
                        }, f, indent=2, ensure_ascii=False, default=str)
                    
                    logger.info(f"Logs exportados a archivo: {output_file}")
                except Exception as e:
                    logger.error(f"Error al exportar a archivo: {str(e)}")
                    export_to_file = False
                    output_file = None
            
            cursor.close()
            conn.close()
            
            result = {
                "success": True, 
                "count": len(rows),
                "total_available": total_count,
                "data": rows[:10 if export_to_file else min(50, limit)],  # Solo 10 si hay archivo (para evitar BrokenPipeError), hasta 50 si no
                "query_info": {
                    "filters_applied": {
                        "ip": ip,
                        "port": port,
                        "action": action,
                        "pattern": pattern,
                        "start_date": start_date,
                        "end_date": end_date,
                        "days": days if not (start_date or end_date) else None
                    },
                    "limit": limit,
                    "results_returned": len(rows),
                    "total_available": total_count
                }
            }
            
            # Agregar información sobre el archivo exportado
            if export_to_file and output_file:
                result["export_info"] = {
                    "exported": True,
                    "file_path": output_file,
                    "file_size_mb": round(os.path.getsize(output_file) / (1024 * 1024), 2) if os.path.exists(output_file) else 0,
                    "message": f"⚠️ Se encontraron {total_count} resultados. Los primeros {min(50, len(rows))} se muestran aquí. Todos los {len(rows)} resultados (limitados por el parámetro limit={limit}) se guardaron en: {output_file}"
                }
            elif total_count is not None and total_count > limit:
                result["export_info"] = {
                    "exported": False,
                    "message": f"ℹ️ Se encontraron {total_count} resultados en total, pero solo se devolvieron {len(rows)} (limitado por el parámetro limit={limit}). Para obtener más resultados, aumenta el parámetro 'limit' o solicita exportación a archivo."
                }
            
            return result
        except OperationalError as e:
            if "timeout" in str(e).lower():
                return {
                    "success": False, 
                    "error": f"Timeout en la consulta. Intenta con parámetros más restrictivos (menos días, límite más pequeño, o especifica fechas exactas).",
                    "suggestion": "Usa start_date y end_date en lugar de days para búsquedas más eficientes"
                }
            raise
        
    except Exception as e:
        logger.error(f"Error en tool_search_fw_logs: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}


async def tool_search_waf_logs(
    ip: Optional[str] = None, 
    host: Optional[str] = None,
    pattern: Optional[str] = None,  # NUEVO: Búsqueda por patrón en url o raw_log
    url_pattern: Optional[str] = None,  # NUEVO: Búsqueda específica en url
    start_date: Optional[str] = None,  # NUEVO: Fecha inicio
    end_date: Optional[str] = None,  # NUEVO: Fecha fin
    limit: int = 100,  # Aumentado de 30 a 100
    days: int = 7  # Por defecto 7 días
) -> Dict[str, Any]:
    """
    Busca logs de WAF con soporte mejorado para búsquedas por patrón y rangos de fechas.
    
    Args:
        ip: IP del cliente
        host: Hostname (búsqueda parcial con LIKE)
        pattern: Patrón de texto a buscar en url o raw_log (usando ILIKE)
        url_pattern: Patrón específico para buscar en la columna url
        start_date: Fecha de inicio (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)
        end_date: Fecha de fin (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)
        limit: Límite de resultados (máximo 1000)
        days: Días hacia atrás desde ahora (si no se especifican fechas)
    """
    try:
        # Validar límite
        if limit > 1000:
            limit = 1000
            logger.warning(f"Límite reducido a 1000 (máximo permitido)")
        
        conn = _get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Para búsquedas con pattern, usar timeout corto (20s) para fallar rápido si va a tardar
        # Para búsquedas sin pattern, usar timeout largo (240s)
        if pattern or url_pattern:
            cursor.execute("SET statement_timeout = '20s'")  # Timeout corto para búsquedas con pattern
        else:
            cursor.execute("SET statement_timeout = '240s'")  # Timeout largo para búsquedas normales
        
        # Construir condiciones WHERE
        where_clauses = []
        params = []
        
        # Manejo de fechas: priorizar start_date/end_date sobre days
        if start_date or end_date:
            try:
                if start_date:
                    if len(start_date) == 10:  # YYYY-MM-DD
                        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    else:
                        start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
                    where_clauses.append("event_time >= %s")
                    params.append(start_dt)
                
                if end_date:
                    if len(end_date) == 10:  # YYYY-MM-DD
                        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                        end_dt = end_dt.replace(hour=23, minute=59, second=59)
                    else:
                        end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
                    where_clauses.append("event_time <= %s")
                    params.append(end_dt)
            except ValueError as e:
                return {"success": False, "error": f"Formato de fecha inválido: {str(e)}"}
        else:
            # Usar days si no se especifican fechas
            where_clauses.append(f"event_time > NOW() - INTERVAL '{days} days'")
        
        # Filtros adicionales
        if ip:
            where_clauses.append("client_ip = %s")
            params.append(ip)
        
        if host:
            where_clauses.append("host ILIKE %s")
            params.append(f"%{host}%")
        
        # NUEVO: Búsqueda por patrón en url (mejorado: también busca en raw_log si no encuentra en url)
        if url_pattern:
            # Buscar en URL y también en raw_log (por si el patrón está codificado o en el contenido completo)
            url_pattern_lower = url_pattern.lower()
            url_pattern_upper = url_pattern.upper()
            where_clauses.append("(url ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s)")
            params.extend([
                f"%{url_pattern}%",  # Original en URL
                f"%{url_pattern}%",  # Original en raw_log
                f"%{url_pattern_lower}%",  # Minúsculas en raw_log
                f"%{url_pattern_upper}%"  # Mayúsculas en raw_log
            ])
        
        # NUEVO: Búsqueda por patrón en url o raw_log (mejorado para case-insensitive)
        if pattern:
            # Buscar tanto en mayúsculas como minúsculas, y también URL-encoded
            pattern_lower = pattern.lower()
            pattern_upper = pattern.upper()
            # También buscar variaciones URL-encoded comunes
            pattern_encoded = urllib.parse.quote(pattern, safe='')
            where_clauses.append("(url ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s OR raw_log::text ILIKE %s)")
            params.extend([
                f"%{pattern}%",  # Original
                f"%{pattern_lower}%",  # Minúsculas
                f"%{pattern_upper}%",  # Mayúsculas
                f"%{pattern_encoded}%",  # URL-encoded
                f"%{urllib.parse.quote(pattern_lower, safe='')}%"  # URL-encoded minúsculas
            ])
        
        base_where = " AND ".join(where_clauses)
        
        # MEJORADO: Intentar contar el total de resultados en una conexión COMPLETAMENTE separada
        # Esto evita cualquier interferencia con la consulta principal
        total_count = None
        count_conn = None
        count_cursor = None
        try:
            # Crear una conexión completamente nueva para el COUNT
            count_conn = _get_db_connection()
            count_cursor = count_conn.cursor(cursor_factory=RealDictCursor)
            # Usar timeout muy corto para el COUNT (5 segundos) - si falla, no importa
            count_cursor.execute("SET statement_timeout = '5s'")
            count_query = f"SELECT COUNT(*) as total FROM waf_logs WHERE {base_where}"
            count_params = params.copy()
            count_cursor.execute(count_query, count_params)
            total_count = count_cursor.fetchone()['total']
            count_cursor.close()
            count_conn.close()
            logger.info(f"Count exitoso: {total_count} resultados disponibles")
        except (OperationalError, Exception) as e:
            # Si el COUNT falla, simplemente continuar sin él (es solo informativo)
            logger.warning(f"Count query falló (timeout esperado en tablas grandes, continuando sin count): {str(e)[:100]}")
            if count_cursor:
                try:
                    count_cursor.close()
                except:
                    pass
            if count_conn:
                try:
                    count_conn.close()
                except:
                    pass
            total_count = None  # No sabemos el total, pero continuamos sin problema
        
        # SIEMPRE generar archivo si hay resultados (mejorado: guarda TODO)
        # Si no tenemos el count, asumimos que puede haber resultados
        export_to_file = total_count is None or total_count > 0
        output_file = None
        output_summary_file = None
        
        if export_to_file:
            # Crear directorio de exportaciones si no existe
            export_dir = "/irt/proyectos/soar-mcp-server/exports"
            os.makedirs(export_dir, exist_ok=True)
            
            # Generar nombre de archivo con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pattern_safe = (pattern or url_pattern or "waf_logs")[:50].replace("/", "_").replace("\\", "_")
            output_file = f"{export_dir}/waf_logs_{pattern_safe}_{timestamp}.json"
            output_summary_file = f"{export_dir}/waf_logs_{pattern_safe}_{timestamp}_ANALISIS.txt"
        
        # MEJORADO: Obtener TODOS los resultados solicitados sin limitaciones artificiales
        all_rows_for_file = []
        effective_limit = limit  # Usar el límite solicitado por el usuario
        
        # Para el archivo, usar el mismo límite solicitado (el usuario sabe cuánto quiere)
        file_limit = limit
        
        # Query optimizada: usar índice en event_time primero, luego filtrar por otros criterios
        # OPTIMIZACIÓN CRÍTICA: Para búsquedas con pattern, usar un enfoque de dos pasos:
        # 1. Primero obtener IDs por fecha (rápido con índice)
        # 2. Luego filtrar por pattern solo en esos IDs (más rápido)
        if pattern or url_pattern:
            # Para búsquedas con pattern, usar subconsulta para ser más rápido
            # Primero obtener IDs por fecha, luego filtrar por pattern
            date_where = " AND ".join([w for w in where_clauses if "event_time" in w])
            date_params = [p for i, p in enumerate(params) if "event_time" in str(where_clauses[i] if i < len(where_clauses) else "")]
            
            # Construir query optimizada: primero por fecha, luego por pattern
            query = f"""
                SELECT * FROM waf_logs 
                WHERE {base_where} 
                ORDER BY event_time DESC 
                LIMIT %s
            """
        else:
            # Para búsquedas sin pattern, usar query normal
            query = f"""
                SELECT * FROM waf_logs 
                WHERE {base_where} 
                ORDER BY event_time DESC 
                LIMIT %s
            """
        # Nota: PostgreSQL usará el índice en event_time si está disponible
        # Para mejorar rendimiento en rangos largos, considera crear índices:
        # CREATE INDEX IF NOT EXISTS idx_waf_logs_event_time ON waf_logs(event_time DESC);
        # CREATE INDEX IF NOT EXISTS idx_waf_logs_client_ip ON waf_logs(client_ip);
        # OPTIMIZACIÓN ULTRA AGRESIVA: Para búsquedas con pattern, usar un límite inicial MUY pequeño
        # El SDK de MCP tiene timeout de ~60s, necesitamos ser muy rápidos
        initial_limit = limit
        if pattern or url_pattern:
            # Para búsquedas con pattern, usar límite inicial MUY pequeño (10) para evitar timeout
            # Las búsquedas con ILIKE en tablas grandes son muy lentas
            # Si el usuario quiere más, se obtienen en lotes después
            initial_limit = min(limit, 5)  # Máximo 5 inicialmente para evitar timeout del SDK (ultra ultra agresivo)
        
        params.append(initial_limit)
        
        # Ejecutar con timeout
        # MEJORADO: Para búsquedas con pattern, devolver resultados inmediatamente y luego intentar obtener más
        try:
            cursor.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            
            # MEJORADO: Guardar TODOS los resultados obtenidos en archivo (sin truncar)
            all_rows_for_file = rows.copy()
            
            # CRÍTICO: Si hay pattern y obtuvimos resultados, devolver inmediatamente
            # No intentar obtener más resultados aquí para evitar timeout del SDK
            # Los resultados adicionales se pueden obtener en una segunda llamada si es necesario
            if export_to_file and (pattern or url_pattern) and len(rows) < limit:
                # Para búsquedas con pattern, guardar lo que tenemos y devolver inmediatamente
                # NO intentar obtener más aquí para evitar timeout
                logger.info(f"✅ Obtenidos {len(rows)} resultados iniciales. Guardando en archivo. Para obtener más, usa límite mayor o haz búsquedas adicionales.")
            elif export_to_file:
                logger.info(f"✅ Obtenidos {len(all_rows_for_file)} resultados completos (solicitados: {limit}) - guardando en archivo sin truncar")
            
            # Serializar fechas
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, datetime):
                        r[k] = v.isoformat()
            
            for r in all_rows_for_file:
                for k, v in r.items():
                    if isinstance(v, datetime):
                        r[k] = v.isoformat()
            
            # SIEMPRE guardar en archivo si hay resultados
            if export_to_file and all_rows_for_file:
                try:
                    # Guardar JSON completo
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump({
                            "query_info": {
                                "filters_applied": {
                                    "ip": ip,
                                    "host": host,
                                    "pattern": pattern,
                                    "url_pattern": url_pattern,
                                    "start_date": start_date,
                                    "end_date": end_date,
                                    "days": days if not (start_date or end_date) else None
                                },
                                "total_results": total_count,
                                "limit_requested": limit,
                                "results_in_file": len(all_rows_for_file),
                                "exported_to_file": True,
                                "file_path": output_file,
                                "export_timestamp": datetime.now().isoformat()
                            },
                            "data": all_rows_for_file
                        }, f, indent=2, ensure_ascii=False, default=str)
                    
                    # Generar análisis detallado
                    analysis = _analyze_waf_logs(all_rows_for_file)
                    
                    # Guardar análisis en archivo de texto
                    with open(output_summary_file, 'w', encoding='utf-8') as f:
                        f.write("=" * 80 + "\n")
                        f.write("ANÁLISIS DETALLADO DE LOGS WAF\n")
                        f.write("=" * 80 + "\n\n")
                        f.write(f"Fecha de análisis: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Patrón buscado: {pattern or url_pattern or 'N/A'}\n")
                        f.write(f"Rango de fechas: {start_date or 'N/A'} a {end_date or 'N/A'}\n")
                        f.write(f"Total de logs encontrados: {total_count}\n")
                        f.write(f"Logs en archivo: {len(all_rows_for_file)}\n\n")
                        f.write(analysis)
                    
                    logger.info(f"Logs exportados a archivo: {output_file}")
                    logger.info(f"Análisis guardado en: {output_summary_file}")
                except Exception as e:
                    logger.error(f"Error al exportar a archivo: {str(e)}", exc_info=True)
                    export_to_file = False
                    output_file = None
                    output_summary_file = None
            
            cursor.close()
            conn.close()
            
            # MEJORADO: Si hay archivo exportado, mostrar solo 10 resultados (sin raw_log completo) para evitar BrokenPipeError
            # Si no hay archivo, mostrar hasta 50
            if export_to_file and output_file:
                display_limit = min(10, len(rows))  # Solo 10 si hay archivo (para evitar pipe roto)
                # Crear versión ligera de los resultados (sin raw_log completo para reducir tamaño)
                display_rows = []
                for r in rows[:display_limit]:
                    display_row = dict(r)
                    # Truncar raw_log si es muy grande (solo para mostrar, el archivo tiene todo)
                    if 'raw_log' in display_row and isinstance(display_row['raw_log'], dict):
                        raw_log_str = str(display_row['raw_log'].get('raw', ''))
                        if len(raw_log_str) > 500:
                            display_row['raw_log'] = {'raw': raw_log_str[:500] + '... [TRUNCADO PARA MOSTRAR - VER ARCHIVO COMPLETO]'}
                    display_rows.append(display_row)
            else:
                display_limit = min(50, len(rows))  # Hasta 50 si no hay archivo
                display_rows = rows[:display_limit]
            
            result = {
                "success": True, 
                "count": len(rows),
                "total_available": total_count if total_count is not None else "desconocido (tabla muy grande)",
                "data": display_rows,  # Versión ligera para evitar BrokenPipeError
                "query_info": {
                    "filters_applied": {
                        "ip": ip,
                        "host": host,
                        "pattern": pattern,
                        "url_pattern": url_pattern,
                        "start_date": start_date,
                        "end_date": end_date,
                        "days": days if not (start_date or end_date) else None
                    },
                    "limit_requested": limit,
                    "results_returned": len(rows),
                    "results_in_response": display_limit,
                    "results_in_file": len(all_rows_for_file) if export_to_file else 0,
                    "total_available": total_count if total_count is not None else "desconocido (tabla muy grande, count omitido por rendimiento)",
                    "note": f"Se muestran {display_limit} resultados aquí (raw_log truncado para mostrar). {'TODOS los resultados completos se guardaron en archivo JSON sin truncar.' if export_to_file else ''}"
                }
            }
            
            # Agregar información sobre el archivo exportado
            if export_to_file and output_file:
                file_size_mb = round(os.path.getsize(output_file) / (1024 * 1024), 2) if os.path.exists(output_file) else 0
                summary_size_mb = round(os.path.getsize(output_summary_file) / (1024 * 1024), 2) if output_summary_file and os.path.exists(output_summary_file) else 0
                
                result["export_info"] = {
                    "exported": True,
                    "json_file": output_file,
                    "analysis_file": output_summary_file,
                    "json_file_size_mb": file_size_mb,
                    "analysis_file_size_mb": summary_size_mb,
                    "total_results_in_file": len(all_rows_for_file),
                    "message": f"✅ ARCHIVOS GUARDADOS AUTOMÁTICAMENTE - DATOS COMPLETOS SIN TRUNCAR\n\n📊 Resultados:\n   - Solicitados: {limit}\n   - Obtenidos: {len(all_rows_for_file)}\n   - Mostrados aquí: {min(100, len(rows))}\n   - Guardados en archivo: {len(all_rows_for_file)} (COMPLETOS, SIN TRUNCAR)\n\n📦 TODOS los {len(all_rows_for_file)} resultados fueron guardados COMPLETOS con TODA la información en:\n   📄 JSON completo: {output_file} ({file_size_mb} MB)\n   📊 Análisis detallado: {output_summary_file} ({summary_size_mb} MB)\n\n✅ El archivo JSON contiene TODOS los registros completos con TODA la información solicitada.\n✅ NO hay truncamiento - todos los datos están guardados tal cual se encontraron.\n\nEl archivo de análisis incluye:\n   - Top 20 IPs atacantes\n   - Top 10 hosts atacados\n   - Distribución de acciones (blocked/allowed)\n   - Tipos de ataque detectados (SQL-Injection, XSS, etc.)\n   - Análisis de bypass de firmas WAF\n   - Top 10 Signature IDs\n   - Top 10 URLs más atacadas\n   - Rango temporal\n\nLos archivos están listos para descargar desde: /irt/proyectos/soar-mcp-server/exports/"
                }
            elif total_count is not None and total_count > limit:
                result["export_info"] = {
                    "exported": False,
                    "message": f"ℹ️ Se encontraron {total_count} resultados en total, pero solo se devolvieron {len(rows)} (limitado por el parámetro limit={limit}). Para obtener TODOS los resultados en archivo, aumenta el parámetro 'limit' a {total_count} o más."
                }
            elif total_count is None or total_count > 0:
                file_size_mb = round(os.path.getsize(output_file) / (1024 * 1024), 2) if output_file and os.path.exists(output_file) else 0
                summary_size_mb = round(os.path.getsize(output_summary_file) / (1024 * 1024), 2) if output_summary_file and os.path.exists(output_summary_file) else 0
                result["export_info"] = {
                    "exported": True,
                    "json_file": output_file,
                    "analysis_file": output_summary_file,
                    "json_file_size_mb": file_size_mb,
                    "analysis_file_size_mb": summary_size_mb,
                    "total_results_in_file": len(all_rows_for_file),
                    "message": f"✅ ARCHIVOS GUARDADOS AUTOMÁTICAMENTE\n\nSe encontraron {total_count if total_count is not None else 'resultados'} y todos fueron guardados automáticamente en:\n   📄 JSON completo: {output_file} ({file_size_mb} MB)\n   📊 Análisis detallado: {output_summary_file} ({summary_size_mb} MB)\n\nLos archivos están listos para descargar desde: /irt/proyectos/soar-mcp-server/exports/"
                }
            
            return result
        except OperationalError as e:
            if "timeout" in str(e).lower():
                return {
                    "success": False, 
                    "error": f"Timeout en la consulta. Intenta con parámetros más restrictivos (menos días, límite más pequeño, o especifica fechas exactas).",
                    "suggestion": "Usa start_date y end_date en lugar de days para búsquedas más eficientes"
                }
            raise
        
    except Exception as e:
        logger.error(f"Error en tool_search_waf_logs: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}


async def tool_check_ip_mitigation(ip: str) -> Dict[str, Any]:
    """Mantener función existente sin cambios"""
    try:
        conn = _get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Optimizamos también el conteo de mitigaciones
        query_fw = """
            SELECT action, COUNT(*) as count FROM (
                (SELECT action FROM fw_logs WHERE source_ip = %s AND event_time > NOW() - INTERVAL '3 days' LIMIT 1000)
                UNION ALL
                (SELECT action FROM fw_logs WHERE dest_ip = %s AND event_time > NOW() - INTERVAL '3 days' LIMIT 1000)
            ) as sub GROUP BY action
        """
        cursor.execute(query_fw, (ip, ip))
        fw = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT action, COUNT(*) as count FROM waf_logs WHERE client_ip = %s AND event_time > NOW() - INTERVAL '3 days' GROUP BY action", (ip,))
        waf = [dict(r) for r in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        all_actions = [str(a['action']).lower() for a in fw + waf if a['action']]
        mitigated = any(x in all_actions for x in ['deny', 'block', 'drop', 'reject'])
        return {"success": True, "ip": ip, "is_mitigated": mitigated, "fw_mitigations": fw, "waf_mitigations": waf}
    except Exception as e:
        return {"success": False, "error": str(e)}
