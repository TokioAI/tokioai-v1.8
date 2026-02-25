"""
Endpoints adicionales para el CLI y gestión de tenants
"""
import os
import subprocess
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

# Structured logging
import logging
try:
    import structlog
    logger = structlog.get_logger().bind(service="dashboard-api", component="endpoints_cli")
except ImportError:
    logger = logging.getLogger(__name__)

# Importar _get_postgres_conn desde db.py (resuelve import circular)
from db import _get_postgres_conn

def get_postgres_connection():
    """Wrapper para obtener conexión PostgreSQL - devuelve conexión directa, no context manager"""
    return _get_postgres_conn()

# Importar SOCAssistantTools
def get_soc_tools():
    """Obtiene instancia de SOCAssistantTools"""
    from soc_assistant.tools import SOCAssistantTools
    return SOCAssistantTools()


async def execute_cli_command(request: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Ejecuta un comando CLI a través del MCP server
    """
    try:
        command = request.get('command', '').strip()
        if not command:
            return {
                "success": False,
                "error": "Comando vacío"
            }
        
        # Parsear comando
        parts = command.split()
        cmd_name = parts[0] if parts else ""
        
        # Obtener herramientas SOC con manejo de errores
        try:
            tools = get_soc_tools()
        except Exception as e:
            logger.error(f"Error obteniendo herramientas SOC: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Error inicializando herramientas: {str(e)}. Verifica las dependencias (google-generativeai)."
            }
        
        # Mapeo de comandos a funciones
        if cmd_name == "block_ip":
            if len(parts) < 2:
                return {
                    "success": False,
                    "error": "Uso: block_ip <ip> [duration]"
                }
            ip = parts[1]
            duration = parts[2] if len(parts) > 2 else "24h"
            try:
                result = await tools.block_ip(ip, duration)
                return {
                    "success": result.get("success", False),
                    "output": result.get("message", ""),
                    "error": result.get("error")
                }
            except Exception as e:
                logger.error(f"Error bloqueando IP: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Error bloqueando IP: {str(e)}"
                }
        
        elif cmd_name == "unblock_ip":
            if len(parts) < 2:
                return {
                    "success": False,
                    "error": "Uso: unblock_ip <ip>"
                }
            ip = parts[1]
            try:
                result = await tools.unblock_ip(ip)
                return {
                    "success": result.get("success", False),
                    "output": result.get("message", ""),
                    "error": result.get("error")
                }
            except Exception as e:
                logger.error(f"Error desbloqueando IP: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Error desbloqueando IP: {str(e)}"
                }
        
        elif cmd_name == "query_logs":
            # Parsear filtros opcionales
            filters = {}
            for i in range(1, len(parts)):
                if parts[i].startswith("--"):
                    key = parts[i][2:]
                    if i + 1 < len(parts):
                        filters[key] = parts[i + 1]
            
            try:
                result = await tools.get_attack_logs(
                    limit=int(filters.get("limit", 50)),
                    tenant_id=filters.get("tenant_id")
                )
                return {
                    "success": True,
                    "output": json.dumps(result, indent=2, default=str)
                }
            except Exception as e:
                logger.error(f"Error consultando logs: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Error consultando logs: {str(e)}"
                }
        
        elif cmd_name == "get_stats":
            try:
                result = await tools.get_waf_stats()
                return {
                    "success": True,
                    "output": json.dumps(result, indent=2, default=str)
                }
            except Exception as e:
                logger.error(f"Error obteniendo estadísticas: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Error obteniendo estadísticas: {str(e)}"
                }
        
        else:
            return {
                "success": False,
                "error": f"Comando desconocido: {cmd_name}. Use /help para ver comandos disponibles."
            }
    
    except Exception as e:
        logger.error(f"Error ejecutando comando CLI: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def create_tenant(request: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Crea un nuevo tenant y lo agrega al proxy WAF
    Ahora incluye backend_url y publica evento a Kafka
    """
    try:
        from nginx_manager import NginxTenantManager
        from kafka import KafkaProducer
        import json as json_lib
        
        name = request.get('name')
        domain = request.get('domain')
        backend_url = request.get('backend_url', 'http://localhost:3000')
        
        if not name or not domain:
            return {
                "success": False,
                "error": "name y domain son requeridos"
            }
        
        # Validar formato de dominio
        if not domain.replace('.', '').replace('-', '').isalnum():
            return {
                "success": False,
                "error": "Formato de dominio inválido"
            }
        
        # Validar formato de backend_url
        if not backend_url.startswith(('http://', 'https://')):
            return {
                "success": False,
                "error": "backend_url debe comenzar con http:// o https://"
            }
        
        # Obtener conexión a PostgreSQL desde el pool
        conn = get_postgres_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Verificar si el dominio ya existe
            cursor.execute("SELECT id FROM tenants WHERE domain = %s", (domain,))
            existing = cursor.fetchone()
            if existing:
                return {
                    "success": False,
                    "error": f"El dominio {domain} ya existe"
                }
            
            # Crear tenant en la base de datos con backend_url
            cursor.execute("""
                INSERT INTO tenants (name, domain, backend_url, status, created_at)
                VALUES (%s, %s, %s, 'active', NOW())
                RETURNING id, name, domain, backend_url, status, created_at
            """, (name, domain, backend_url))
            
            tenant = dict(cursor.fetchone())
            tenant_id = tenant['id']
            conn.commit()
            
            # Convertir datetime
            if tenant.get('created_at') and hasattr(tenant['created_at'], 'isoformat'):
                tenant['created_at'] = tenant['created_at'].isoformat()
            
            cursor.close()
            
            # Agregar tenant a Nginx usando NginxTenantManager
            nginx_manager = NginxTenantManager()
            nginx_success = await nginx_manager.add_tenant(
                tenant_id=tenant_id,
                domain=domain,
                tenant_name=name,
                backend_url=backend_url
            )
            
            if not nginx_success:
                logger.warning(f"⚠️ No se pudo agregar tenant a Nginx, pero el tenant fue creado en DB")
            
            # Publicar evento a Kafka
            try:
                kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092").split(",")
                producer = KafkaProducer(
                    bootstrap_servers=kafka_servers,
                    value_serializer=lambda v: json_lib.dumps(v).encode('utf-8')
                )
                
                event = {
                    "event": "tenant.created",
                    "tenant_id": tenant_id,
                    "domain": domain,
                    "name": name,
                    "backend_url": backend_url,
                    "timestamp": tenant['created_at']
                }
                
                producer.send("tenant-events", value=event)
                producer.flush()
                producer.close()
                logger.info(f"✅ Evento tenant.created publicado a Kafka para tenant {tenant_id}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo publicar evento a Kafka: {e}")
                # No fallar si Kafka no está disponible
            
            return {
                "success": True,
                "tenant": tenant,
                "dns_instructions": (
                    f"Crea/actualiza DNS para {domain} apuntando al proxy TokioAI. "
                    "En modo túnel usa CNAME al target del túnel."
                ),
                "vm_ip": os.getenv("PROXY_PUBLIC_IP", ""),
                "message": f"Tenant {name} ({domain}) creado exitosamente"
            }
        except Exception as db_error:
            conn.rollback()
            logger.error(f"Error en operación de base de datos: {db_error}", exc_info=True)
            raise
    
    except Exception as e:
        logger.error(f"Error creando tenant: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def delete_tenant(tenant_id: int) -> Dict[str, Any]:
    """
    VORTEX 9: Elimina un tenant y su configuración de Nginx
    Vibración 3: Elegante en su simplicidad
    Vibración 6: Rigurosa en su eficiencia
    Vibración 9: Máxima abstracción - un método hace todo
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Obtener información del tenant antes de eliminarlo
            cursor.execute("SELECT domain, name FROM tenants WHERE id = %s", (tenant_id,))
            tenant = cursor.fetchone()
            
            if not tenant:
                cursor.close()
                return {
                    "success": False,
                    "error": f"Tenant con ID {tenant_id} no encontrado"
                }
            
            domain = tenant['domain']
            tenant_name = tenant['name']
            
            # Eliminar tenant de la base de datos
            cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
            conn.commit()
            cursor.close()
        
        # Eliminar configuración de Nginx usando NginxTenantManager
        try:
            from nginx_manager import NginxTenantManager
            nginx_manager = NginxTenantManager()
            nginx_success = await nginx_manager.remove_tenant(domain)
            
            if nginx_success:
                logger.info(f"✅ Configuración de Nginx eliminada para {domain}")
            else:
                logger.warning(f"⚠️ No se pudo eliminar configuración de Nginx para {domain}")
        except Exception as e:
            logger.warning(f"⚠️ Error eliminando configuración de Nginx: {e}")
        
        # Publicar evento a Kafka
        try:
            from kafka import KafkaProducer
            import json as json_lib
            
            kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092").split(",")
            producer = KafkaProducer(
                bootstrap_servers=kafka_servers,
                value_serializer=lambda v: json_lib.dumps(v).encode('utf-8')
            )
            
            event = {
                "event": "tenant.deleted",
                "tenant_id": tenant_id,
                "domain": domain,
                "name": tenant_name,
                "timestamp": datetime.now().isoformat()
            }
            
            producer.send("tenant-events", value=event)
            producer.flush()
            producer.close()
            logger.info(f"✅ Evento tenant.deleted publicado a Kafka")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo publicar evento a Kafka: {e}")
        
        return {
            "success": True,
            "message": f"Tenant {tenant_name} ({domain}) eliminado exitosamente"
        }
    
    except Exception as e:
        logger.error(f"Error eliminando tenant: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
