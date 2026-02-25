"""
Sistema de herramientas para el SOC AI Assistant
Proporciona acceso a todas las funcionalidades del sistema
"""
import os
import json
import logging
import psycopg2
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import requests

logger = logging.getLogger(__name__)

# Intentar importar kafka-python, si no está disponible, block_ip/unblock_ip no funcionarán completamente
try:
    from kafka import KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logger.warning("kafka-python no disponible, block_ip/unblock_ip pueden no funcionar completamente")


class SOCAssistantTools:
    """Herramientas disponibles para el asistente SOC AI"""
    
    def __init__(self):
        """Inicializa las herramientas con conexión a la base de datos"""
        self.db_conn = None
        self._init_db_connection()
        
        # Mapeo de herramientas disponibles
        self.tools_map = {
            "get_waf_stats": {
                "description": "Obtiene estadísticas generales del WAF",
                "parameters": ["tenant_id (opcional)"]
            },
            "get_attack_logs": {
                "description": "Obtiene logs de ataques recientes",
                "parameters": ["limit (opcional, default: 50)", "tenant_id (opcional)"]
            },
            "get_incidents": {
                "description": "Obtiene incidentes de seguridad",
                "parameters": ["limit (opcional, default: 20)", "tenant_id (opcional)"]
            },
            "get_redteam_campaigns": {
                "description": "Obtiene el historial de campañas del Red Team",
                "parameters": ["limit (opcional, default: 10)", "tenant_id (opcional)"]
            },
            "get_redteam_campaign_details": {
                "description": "Obtiene detalles específicos de una campaña de Red Team",
                "parameters": ["campaign_id (requerido)"]
            },
            "run_redteam_campaign": {
                "description": "Ejecuta una nueva campaña de Red Team",
                "parameters": ["attack_types (opcional, lista)", "tenant_id (opcional)"]
            },
            "get_waf_rules": {
                "description": "Obtiene las reglas del WAF",
                "parameters": ["tenant_id (opcional)", "enabled_only (opcional, default: true)"]
            },
            "get_suggestions": {
                "description": "Obtiene sugerencias de mejora del Red Team",
                "parameters": ["tenant_id (opcional)"]
            },
            "apply_suggestions": {
                "description": "Aplica sugerencias de mejora y relanza Red Team",
                "parameters": ["tenant_id (opcional)"]
            },
            "get_tenant_info": {
                "description": "Obtiene información de tenants",
                "parameters": []
            },
            "get_realtime_stats": {
                "description": "Obtiene estadísticas en tiempo real",
                "parameters": []
            },
            "analyze_waf": {
                "description": "Analiza la defensa del WAF",
                "parameters": ["tenant_id (opcional)"]
            },
            "get_bypasses": {
                "description": "Obtiene bypasses exitosos detectados",
                "parameters": ["limit (opcional, default: 20)", "tenant_id (opcional)"]
            },
            "get_mitigations": {
                "description": "Obtiene mitigaciones aplicadas",
                "parameters": ["limit (opcional, default: 20)", "tenant_id (opcional)"]
            },
            "stop_redteam": {
                "description": "Detiene el escaneo/campaña actual del Red Team",
                "parameters": []
            },
            "start_redteam": {
                "description": "Inicia el servicio Red Team",
                "parameters": []
            },
            "get_blocked_ips": {
                "description": "Obtiene las IPs bloqueadas por el agente IA (análisis SOC)",
                "parameters": ["limit (opcional, default: 50)", "tenant_id (opcional)"]
            },
            "block_ip": {
                "description": "Bloquea una IP directamente desde el assistant",
                "parameters": ["ip (requerido)", "duration (opcional, default: 1h)", "reason (opcional)"]
            },
            "unblock_ip": {
                "description": "Desbloquea una IP previamente bloqueada",
                "parameters": ["ip (requerido)", "reason (opcional)"]
            },
            "get_attack_statistics": {
                "description": "Obtiene estadísticas detalladas de ataques (por tipo, OWASP, IPs más activas, etc.)",
                "parameters": ["tenant_id (opcional)", "time_window (opcional, default: 24h)"]
            },
            "get_agent_decisions": {
                "description": "Obtiene las decisiones recientes del agente IA (bloqueos de IPs, análisis SOC de ventanas temporales). Esta es la herramienta principal para ver qué decisiones ha tomado el agente IA automáticamente.",
                "parameters": ["limit (opcional, default: 50)", "tenant_id (opcional)"]
            },
            "query_episodes": {
                "description": "Consulta episodios con filtros específicos (IP, decisión BLOCK/ALLOW/UNCERTAIN, risk_score mínimo, etc.). Úsalo para ver episodios bloqueados automáticamente por el sistema de análisis por episodios. Esta es la herramienta RECOMENDADA para consultar episodios bloqueados.",
                "parameters": ["ip (opcional)", "decision (opcional: ALLOW, BLOCK, UNCERTAIN)", "risk_score_min (opcional)", "hours (opcional, default: 24)", "limit (opcional, default: 50)"]
            },
            "query_blocked_ips": {
                "description": "Consulta IPs bloqueadas desde la tabla blocked_ips. Esta herramienta muestra todos los bloqueos automáticos y manuales con sus detalles (razón, threat_type, fecha de expiración, etc.). IMPORTANTE: Si se especifica una IP, automáticamente busca bloqueos históricos (activos e inactivos) para dar contexto completo. Usa active_only=False cuando busques una IP específica para ver también bloqueos que ya expiraron.",
                "parameters": ["ip (opcional - si se especifica, busca históricos automáticamente)", "active_only (opcional, default: true - usar false para ver también bloqueos expirados)", "hours (opcional, default: 24)", "limit (opcional, default: 100)"]
            },
            "get_episode_stats": {
                "description": "Obtiene estadísticas agregadas de episodios (total episodios, bloqueados, permitidos, inciertos, promedio de risk_score, etc.)",
                "parameters": ["hours (opcional, default: 24)"]
            },
            "get_blocking_effectiveness": {
                "description": "Analiza efectividad de bloqueos (IPs bloqueadas vs re-ataques después del bloqueo). Muestra qué tan efectivos son los bloqueos automáticos.",
                "parameters": ["hours (opcional, default: 24)"]
            }
        }
    
    def _init_db_connection(self):
        """Inicializa conexión a PostgreSQL"""
        try:
            self.db_conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'postgres-persistence'),
                port=os.getenv('POSTGRES_PORT', '5432'),
                database=os.getenv('POSTGRES_DB', 'soc_ai'),
                user=os.getenv('POSTGRES_USER', 'soc_user'),
                password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))
            )
            logger.info("✅ Conexión a DB establecida para SOC Assistant Tools")
        except Exception as e:
            logger.error(f"Error conectando a DB: {e}")
            self.db_conn = None
    
    def get_available_tools(self) -> Dict[str, Dict[str, str]]:
        """Retorna la lista de herramientas disponibles"""
        return self.tools_map
    
    async def get_waf_stats(self, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene estadísticas generales del WAF"""
        try:
            # Consultar directamente desde la base de datos en lugar de HTTP
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Obtener estadísticas de waf_logs
            # Nota: la columna es 'ip', no 'source_ip'
            query = """
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(CASE WHEN blocked = true THEN 1 END) as blocked,
                    COUNT(CASE WHEN blocked = false THEN 1 END) as allowed,
                    COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '24 hours'
            """
            cursor.execute(query)
            stats_row = cursor.fetchone()
            
            # Obtener top threats
            # Nota: la columna es 'threat_type', no 'attack_type'
            query_threats = """
                SELECT threat_type, COUNT(*) as count
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '24 hours'
                AND threat_type IS NOT NULL
                GROUP BY threat_type
                ORDER BY count DESC
                LIMIT 10
            """
            cursor.execute(query_threats)
            threats = {row[0]: row[1] for row in cursor.fetchall()}
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "total_requests": stats_row[0] or 0,
                    "blocked": stats_row[1] or 0,
                    "allowed": stats_row[2] or 0,
                    "unique_ips": stats_row[3] or 0,
                    "by_threat_type": threats
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo stats: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_attack_logs(self, limit: int = 50, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene logs de ataques recientes"""
        try:
            # Limitar a máximo 200 para evitar sobrecarga
            limit = min(limit, 200)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = [limit]
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.insert(0, int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            query = f"""
                SELECT 
                    id, timestamp, ip, method, uri, status, blocked,
                    threat_type, severity, raw_log, created_at
                FROM waf_logs
                WHERE blocked = true
                {tenant_filter}
                ORDER BY timestamp DESC
                LIMIT %s
            """
            
            cursor.execute(query, params)
            logs = []
            for row in cursor.fetchall():
                logs.append({
                    "id": row[0],
                    "timestamp": row[1].isoformat() if row[1] else None,
                    "source_ip": row[2],
                    "method": row[3],
                    "uri": row[4][:200] + "..." if row[4] and len(row[4]) > 200 else row[4],
                    "status": row[5],
                    "blocked": row[6],
                    "threat_type": row[7],
                    "severity": row[8],
                    "raw_log": row[9],
                    "created_at": row[10].isoformat() if row[10] else None
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(logs),
                    "items": logs,
                    "summary": {
                        "total": len(logs),
                        "by_threat_type": {}
                    }
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo attack logs: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_incidents(self, limit: int = 20, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene incidentes de seguridad"""
        try:
            # Limitar a máximo 100 para evitar sobrecarga
            limit = min(limit, 100)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = [limit]
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.insert(0, int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            query = f"""
                SELECT 
                    id, tenant_id, title, description, severity, status,
                    incident_type, source_ip, affected_urls, detected_at,
                    resolved_at, assigned_to, resolution_notes
                FROM incidents
                WHERE 1=1
                {tenant_filter}
                ORDER BY detected_at DESC
                LIMIT %s
            """
            
            cursor.execute(query, params)
            incidents = []
            for row in cursor.fetchall():
                incidents.append({
                    "id": row[0],
                    "tenant_id": row[1],
                    "title": row[2],
                    "description": row[3][:500] + "..." if row[3] and len(row[3]) > 500 else row[3],
                    "severity": row[4],
                    "status": row[5],
                    "incident_type": row[6],
                    "source_ip": row[7],
                    "affected_urls": row[8],
                    "detected_at": row[9].isoformat() if row[9] else None,
                    "resolved_at": row[10].isoformat() if row[10] else None,
                    "assigned_to": row[11],
                    "resolution_notes": row[12]
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(incidents),
                    "items": incidents
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo incidents: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_redteam_campaigns(self, limit: int = 10, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene el historial de campañas del Red Team"""
        try:
            # Limitar a máximo 50 para evitar sobrecarga
            limit = min(limit, 50)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            query = f"""
                SELECT 
                    campaign_id,
                    MIN(tested_at) as campaign_start,
                    MAX(tested_at) as campaign_end,
                    COUNT(*) as total_tests,
                    COUNT(CASE WHEN success = true THEN 1 END) as successful_bypasses,
                    COUNT(CASE WHEN blocked = true THEN 1 END) as blocked_attempts,
                    COUNT(DISTINCT attack_type) as attack_types_tested,
                    STRING_AGG(DISTINCT attack_type, ', ') as attack_types
                FROM redteam_test_history
                WHERE campaign_id IS NOT NULL
                {tenant_filter}
                GROUP BY campaign_id
                ORDER BY campaign_start DESC
                LIMIT %s
            """
            params.append(limit)
            
            cursor.execute(query, params)
            campaigns = []
            for row in cursor.fetchall():
                campaign_id, start, end, total, successful, blocked, types_count, types = row
                success_rate = (successful / total * 100) if total > 0 else 0
                
                campaigns.append({
                    "campaign_id": campaign_id,
                    "start_time": start.isoformat() if start else None,
                    "end_time": end.isoformat() if end else None,
                    "total_tests": total,
                    "successful_bypasses": successful,
                    "blocked_attempts": blocked,
                    "attack_types_tested": types_count,
                    "attack_types": types,
                    "success_rate": round(success_rate, 2)
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(campaigns),
                    "campaigns": campaigns
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo campaigns: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_redteam_campaign_details(self, campaign_id: str, **kwargs) -> Dict[str, Any]:
        """Obtiene detalles específicos de una campaña"""
        if not self.db_conn:
            return {"success": False, "error": "No hay conexión a la base de datos"}
        
        try:
            cursor = self.db_conn.cursor()
            
            # Obtener información de la campaña
            query_campaign = """
                SELECT 
                    campaign_id,
                    MIN(tested_at) as campaign_start,
                    MAX(tested_at) as campaign_end,
                    COUNT(*) as total_tests,
                    COUNT(CASE WHEN success = true THEN 1 END) as successful_bypasses,
                    COUNT(CASE WHEN blocked = true THEN 1 END) as blocked_attempts,
                    COUNT(DISTINCT attack_type) as attack_types_tested
                FROM redteam_test_history
                WHERE campaign_id = %s
                GROUP BY campaign_id
            """
            cursor.execute(query_campaign, (campaign_id,))
            campaign_row = cursor.fetchone()
            
            if not campaign_row:
                cursor.close()
                return {"success": False, "error": f"Campaña {campaign_id} no encontrada"}
            
            campaign_id, start, end, total, successful, blocked, types = campaign_row
            
            # Obtener detalles de las pruebas
            query_tests = """
                SELECT 
                    attack_type,
                    payload,
                    bypass_technique,
                    success,
                    blocked,
                    response_status,
                    response_time_ms,
                    tested_at
                FROM redteam_test_history
                WHERE campaign_id = %s
                ORDER BY tested_at ASC
            """
            cursor.execute(query_tests, (campaign_id,))
            tests = []
            for row in cursor.fetchall():
                at_type, payload, bypass, success, blocked, status, time_ms, tested = row
                tests.append({
                    "attack_type": at_type,
                    "payload": payload[:200] + "..." if payload and len(payload) > 200 else payload,
                    "bypass_technique": bypass,
                    "success": success,
                    "blocked": blocked,
                    "response_status": status,
                    "response_time_ms": time_ms,
                    "tested_at": tested.isoformat() if tested else None
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "campaign_id": campaign_id,
                    "start_time": start.isoformat() if start else None,
                    "end_time": end.isoformat() if end else None,
                    "total_tests": total,
                    "successful_bypasses": successful,
                    "blocked_attempts": blocked,
                    "attack_types_tested": types,
                    "success_rate": (successful / total * 100) if total > 0 else 0,
                    "tests": tests
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo campaign details: {e}")
            return {"success": False, "error": str(e)}
    
    async def run_redteam_campaign(self, attack_types: Optional[List[str]] = None, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Ejecuta una nueva campaña de Red Team"""
        try:
            # Disparar campaña mediante trigger file con parámetros JSON
            trigger_file = "/data/redteam_trigger"
            try:
                os.makedirs("/data", exist_ok=True)
                # Escribir parámetros en formato JSON
                trigger_data = {
                    "action": "trigger",
                    "attack_types": attack_types if attack_types else None,
                    "tenant_id": tenant_id
                }
                with open(trigger_file, "w") as f:
                    json.dump(trigger_data, f)
                logger.info(f"✅ Archivo trigger creado: {trigger_file} con attack_types: {attack_types}")
            except Exception as e:
                logger.error(f"Error creando archivo trigger: {e}")
                return {
                    "success": False,
                    "error": f"No se pudo crear el archivo trigger: {str(e)}"
                }
            
            # Esperar un poco para que el servicio procese el trigger
            import time
            time.sleep(3)  # Aumentado a 3 segundos
            
            # Obtener la última campaña creada (puede ser una nueva o una existente)
            if self.db_conn:
                try:
                    cursor = self.db_conn.cursor()
                    cursor.execute("""
                        SELECT campaign_id, MAX(tested_at) as last_test
                        FROM redteam_test_history
                        WHERE campaign_id IS NOT NULL
                        GROUP BY campaign_id
                        ORDER BY last_test DESC
                        LIMIT 1
                    """)
                    result = cursor.fetchone()
                    cursor.close()
                    
                    if result:
                        campaign_id = result[0]
                        return {
                            "success": True,
                            "message": f"Campaña disparada exitosamente. ID de campaña: {campaign_id}. El servicio Red Team está procesando la campaña.",
                            "campaign_id": campaign_id,
                            "data": {
                                "message": f"Campaña disparada exitosamente. ID: {campaign_id}",
                                "campaign_id": campaign_id,
                                "status": "triggered"
                            }
                        }
                except Exception as db_error:
                    logger.error(f"Error consultando DB para campaign: {db_error}")
                    # Continuar aunque falle la consulta
            
            # Si no hay campaña aún, retornar éxito de todas formas (la campaña se está ejecutando)
            return {
                "success": True,
                "message": "Campaña disparada exitosamente. El servicio Red Team está procesando la campaña. Los resultados estarán disponibles en unos momentos.",
                "data": {
                    "message": "Campaña disparada. El servicio está procesando la solicitud.",
                    "status": "triggered"
                }
            }
        except Exception as e:
            logger.error(f"Error ejecutando campaign: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "data": {
                    "error": str(e)
                }
            }
    
    async def get_waf_rules(self, tenant_id: str = "default", enabled_only: bool = True, **kwargs) -> Dict[str, Any]:
        """Obtiene las reglas del WAF"""
        try:
            # Usar la URL de Cloud Run si está disponible, sino intentar detectar automáticamente
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.get(f"{base_url}/api/intelligent-redteam/analysis?tenant_id={tenant_id}")
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "data": data}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error obteniendo WAF rules: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_suggestions(self, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene sugerencias de mejora"""
        try:
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.get(f"{base_url}/api/intelligent-redteam/suggestions?tenant_id={tenant_id}")
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error obteniendo suggestions: {e}")
            return {"success": False, "error": str(e)}
    
    async def apply_suggestions(self, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Aplica sugerencias de mejora"""
        try:
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.post(
                f"{base_url}/api/intelligent-redteam/apply-and-retest",
                json={"tenant_id": tenant_id}
            )
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error aplicando suggestions: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_tenant_info(self, **kwargs) -> Dict[str, Any]:
        """Obtiene información de tenants"""
        try:
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.get(f"{base_url}/api/tenants")
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error obteniendo tenant info: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_realtime_stats(self, **kwargs) -> Dict[str, Any]:
        """Obtiene estadísticas en tiempo real"""
        try:
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.get(f"{base_url}/api/real-time/stats")
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error obteniendo realtime stats: {e}")
            return {"success": False, "error": str(e)}
    
    async def analyze_waf(self, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Analiza la defensa del WAF"""
        try:
            base_url = os.getenv('DASHBOARD_API_URL') or os.getenv('SERVICE_URL') or 'https://YOUR_CLOUD_RUN_URL'
            response = requests.get(f"{base_url}/api/intelligent-redteam/analysis?tenant_id={tenant_id}")
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error analizando WAF: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bypasses(self, limit: int = 20, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene bypasses exitosos"""
        try:
            # Si estamos dentro de Docker, usar el nombre del servicio o consultar directamente la DB
            # En lugar de hacer HTTP request, consultar directamente la base de datos
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Consultar bypasses desde la base de datos
            tenant_filter = ""
            params = [limit]
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.insert(0, int(tenant_id))
            else:
                # Para "default", incluir también registros sin tenant_id
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            query = f"""
                SELECT 
                    id, tenant_id, source_ip, attack_type, bypass_method,
                    request_data, response_data, mitigated, detected_at
                FROM detected_bypasses
                WHERE 1=1
                {tenant_filter}
                ORDER BY detected_at DESC
                LIMIT %s
            """
            
            cursor.execute(query, params)
            bypasses = []
            for row in cursor.fetchall():
                # Extraer payload del request_data si es JSON
                payload = ""
                if row[5]:  # request_data
                    try:
                        if isinstance(row[5], dict):
                            payload = json.dumps(row[5])
                        else:
                            payload = str(row[5])
                    except:
                        payload = str(row[5]) if row[5] else ""
                
                bypasses.append({
                    "id": row[0],
                    "tenant_id": row[1],
                    "source_ip": row[2],
                    "attack_type": row[3],
                    "bypass_method": row[4],
                    "payload": payload,
                    "request_data": row[5],
                    "response_data": row[6],
                    "mitigated": row[7],
                    "detected_at": row[8].isoformat() if row[8] else None
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(bypasses),
                    "items": bypasses
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo bypasses: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_mitigations(self, limit: int = 20, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene mitigaciones aplicadas (reglas WAF + IPs bloqueadas por agente IA)"""
        try:
            # Limitar a máximo 100 para evitar sobrecarga
            limit = min(limit, 100)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            mitigations = []
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            # 1. Obtener reglas WAF creadas automáticamente
            try:
                query_rules = f"""
                    SELECT 
                        tr.id, tr.tenant_id, tr.rule_name, tr.rule_type,
                        tr.pattern, tr.action, tr.enabled, tr.created_by,
                        tr.created_at, tr.updated_at,
                        db.source_ip, db.attack_type, db.bypass_method
                    FROM tenant_rules tr
                    LEFT JOIN detected_bypasses db ON tr.id = db.mitigation_rule_id
                    WHERE tr.created_by = 'auto-mitigation-system'
                    {tenant_filter}
                    ORDER BY tr.created_at DESC
                    LIMIT %s
                """
                params_rules = params + [limit]
                cursor.execute(query_rules, params_rules)
                
                for row in cursor.fetchall():
                    mitigations.append({
                        "type": "waf_rule",
                        "id": row[0],
                        "tenant_id": row[1],
                        "rule_name": row[2],
                        "rule_type": row[3],
                        "pattern": row[4][:200] + "..." if row[4] and len(row[4]) > 200 else row[4],
                        "action": row[5],
                        "enabled": row[6],
                        "created_by": row[7],
                        "created_at": row[8].isoformat() if row[8] else None,
                        "updated_at": row[9].isoformat() if row[9] else None,
                        "source_ip": row[10],
                        "attack_type": row[11],
                        "bypass_method": row[12]
                    })
            except Exception as e:
                logger.warning(f"Error obteniendo reglas WAF: {e}")
            
            # 2. Obtener IPs bloqueadas por el agente IA (desde waf_logs)
            try:
                query_blocked_ips = f"""
                    SELECT DISTINCT ON (ip)
                        ip,
                        MAX(timestamp) as blocked_at,
                        MAX(threat_type) as threat_type,
                        MAX(severity) as severity,
                        MAX(owasp_code) as owasp_code,
                        MAX(owasp_category) as owasp_category,
                        COUNT(*) as total_logs,
                        ARRAY_AGG(DISTINCT threat_type) FILTER (WHERE threat_type IS NOT NULL) as threat_types
                    FROM waf_logs
                    WHERE classification_source = 'time_window_soc_analysis'
                    AND blocked = TRUE
                    AND timestamp > NOW() - INTERVAL '24 hours'
                    {tenant_filter}
                    GROUP BY ip
                    ORDER BY ip, MAX(timestamp) DESC
                    LIMIT %s
                """
                params_ips = params + [limit]
                cursor.execute(query_blocked_ips, params_ips)
                
                for row in cursor.fetchall():
                    blocked_at = row[1]
                    if hasattr(blocked_at, 'isoformat'):
                        blocked_at = blocked_at.isoformat()
                    
                    threat_types = row[7]
                    if threat_types and isinstance(threat_types, list):
                        threat_types = list(threat_types)
                    
                    mitigations.append({
                        "type": "blocked_ip",
                        "ip": row[0],
                        "blocked_at": blocked_at,
                        "threat_type": row[2],
                        "severity": row[3],
                        "owasp_code": row[4],
                        "owasp_category": row[5],
                        "total_logs": row[6],
                        "threat_types": threat_types,
                        "source": "time_window_soc_analysis"
                    })
            except Exception as e:
                logger.warning(f"Error obteniendo IPs bloqueadas: {e}")
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(mitigations),
                    "items": mitigations
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo mitigations: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def stop_redteam(self, **kwargs) -> Dict[str, Any]:
        """Detiene el escaneo/campaña actual del Red Team"""
        try:
            # Crear archivo de control para detener
            control_file = "/data/redteam_control"
            os.makedirs("/data", exist_ok=True)
            with open(control_file, "w") as f:
                f.write("stop")
            
            return {
                "success": True,
                "message": "Señal STOP enviada al Red Team. El escaneo se detendrá después de completar la prueba actual."
            }
        except Exception as e:
            logger.error(f"Error deteniendo Red Team: {e}")
            return {"success": False, "error": str(e)}
    
    async def start_redteam(self, **kwargs) -> Dict[str, Any]:
        """Inicia el servicio Red Team"""
        try:
            # Crear archivo de control para iniciar
            control_file = "/data/redteam_control"
            os.makedirs("/data", exist_ok=True)
            with open(control_file, "w") as f:
                f.write("start")
            
            return {
                "success": True,
                "message": "Señal START enviada al Red Team. El servicio se reanudará."
            }
        except Exception as e:
            logger.error(f"Error iniciando Red Team: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_blocked_ips(self, limit: int = 50, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene las IPs bloqueadas por el agente IA"""
        try:
            limit = min(limit, 200)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            # Obtener IPs bloqueadas desde waf_logs con classification_source = 'time_window_soc_analysis'
            query = f"""
                SELECT DISTINCT ON (ip)
                    ip,
                    MAX(timestamp) as blocked_at,
                    MAX(threat_type) as threat_type,
                    MAX(severity) as severity,
                    MAX(owasp_code) as owasp_code,
                    MAX(owasp_category) as owasp_category,
                    COUNT(*) as total_logs,
                    ARRAY_AGG(DISTINCT threat_type) FILTER (WHERE threat_type IS NOT NULL) as threat_types,
                    ARRAY_AGG(DISTINCT uri) FILTER (WHERE uri IS NOT NULL) as sample_uris
                FROM waf_logs
                WHERE classification_source = 'time_window_soc_analysis'
                AND blocked = TRUE
                AND timestamp > NOW() - INTERVAL '48 hours'
                {tenant_filter}
                GROUP BY ip
                ORDER BY ip, MAX(timestamp) DESC
                LIMIT %s
            """
            params.append(limit)
            cursor.execute(query, params)
            
            blocked_ips = []
            for row in cursor.fetchall():
                blocked_at = row[1]
                if hasattr(blocked_at, 'isoformat'):
                    blocked_at = blocked_at.isoformat()
                
                threat_types = row[7]
                if threat_types and isinstance(threat_types, list):
                    threat_types = list(threat_types)
                
                sample_uris = row[8]
                if sample_uris and isinstance(sample_uris, list):
                    sample_uris = list(sample_uris)[:5]
                
                blocked_ips.append({
                    "ip": row[0],
                    "blocked_at": blocked_at,
                    "threat_type": row[2],
                    "severity": row[3],
                    "owasp_code": row[4],
                    "owasp_category": row[5],
                    "total_logs": row[6],
                    "threat_types": threat_types,
                    "sample_uris": sample_uris,
                    "source": "time_window_soc_analysis"
                })
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(blocked_ips),
                    "blocked_ips": blocked_ips
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo blocked IPs: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def block_ip(self, ip: str, duration: str = "1h", reason: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Bloquea una IP directamente desde el assistant - ESCRIBE DIRECTAMENTE EN PostgreSQL"""
        try:
            if not ip:
                return {"success": False, "error": "IP es requerida"}
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            # Parsear duración (ej: "1h", "24h", "1d" -> segundos)
            duration_seconds = 3600  # default 1 hora
            if duration:
                if duration.endswith("h"):
                    duration_seconds = int(duration[:-1]) * 3600
                elif duration.endswith("d"):
                    duration_seconds = int(duration[:-1]) * 86400
                elif duration.endswith("m"):
                    duration_seconds = int(duration[:-1]) * 60
                else:
                    try:
                        duration_seconds = int(duration)
                    except:
                        pass
            
            # Calcular expires_at
            expires_at = datetime.now() + timedelta(seconds=duration_seconds)
            
            cursor = self.db_conn.cursor()
            block_reason = reason or f"Bloqueado manualmente desde SOC Assistant"
            
            # Insertar DIRECTAMENTE en blocked_ips (NO usar Kafka - igual que los demás métodos)
            cursor.execute("""
                INSERT INTO blocked_ips (
                    ip, blocked_at, expires_at, reason, 
                    classification_source, threat_type, severity, active
                )
                VALUES (%s, NOW(), %s, %s, 'soc_assistant_manual', 'MANUAL_BLOCK', 'high', TRUE)
                ON CONFLICT (ip) WHERE active = TRUE
                DO UPDATE SET
                    blocked_at = NOW(),
                    expires_at = EXCLUDED.expires_at,
                    reason = EXCLUDED.reason,
                    threat_type = EXCLUDED.threat_type,
                    severity = EXCLUDED.severity,
                    classification_source = 'soc_assistant_manual',
                    updated_at = NOW()
            """, (ip, expires_at, block_reason[:500]))
            
            self.db_conn.commit()
            cursor.close()
            
            logger.info(f"✅ IP {ip} bloqueada desde SOC Assistant por {duration}")
            
            return {
                "success": True,
                "message": f"IP {ip} bloqueada exitosamente por {duration}. El bloqueo se aplicará inmediatamente.",
                "ip": ip,
                "duration": duration,
                "duration_seconds": duration_seconds,
                "reason": block_reason
            }
        except Exception as e:
            logger.error(f"Error bloqueando IP: {e}", exc_info=True)
            if self.db_conn:
                self.db_conn.rollback()
            return {"success": False, "error": str(e)}
    
    async def unblock_ip(self, ip: str, reason: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Desbloquea una IP previamente bloqueada"""
        try:
            if not ip:
                return {"success": False, "error": "IP es requerida"}
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Primero intentar desbloquear desde blocked_ips (nueva tabla de episodios)
            try:
                # Buscar IP con múltiples formatos (INET, texto, CIDR)
                cursor.execute("""
                    SELECT ip, blocked_at, active, expires_at
                    FROM blocked_ips
                    WHERE (ip = %s::inet OR ip::text = %s OR ip::text LIKE %s)
                    AND active = TRUE
                    ORDER BY blocked_at DESC
                    LIMIT 1
                """, (ip, ip, f"{ip}%"))
                
                blocked_result = cursor.fetchone()
                
                if blocked_result:
                    # Desbloquear en blocked_ips
                    unblock_reason = reason or "Desbloqueado manualmente por analista"
                    cursor.execute("""
                        UPDATE blocked_ips
                        SET active = FALSE,
                            unblocked_at = NOW(),
                            unblock_reason = %s
                        WHERE (ip = %s::inet OR ip::text = %s OR ip::text LIKE %s)
                        AND active = TRUE
                    """, (unblock_reason, ip, ip, f"{ip}%"))
                    
                    rows_updated = cursor.rowcount
                    self.db_conn.commit()
                    cursor.close()
                    
                    if rows_updated > 0:
                        logger.info(f"✅ IP {ip} desbloqueada desde blocked_ips ({rows_updated} registro(s) actualizado(s))")
                        
                        return {
                            "success": True,
                            "message": f"IP {ip} desbloqueada exitosamente. El desbloqueo se aplicará inmediatamente.",
                            "ip": ip,
                            "reason": unblock_reason,
                            "blocks_removed": rows_updated
                        }
                else:
                    # Si no encuentra activa, buscar inactivas para informar
                    cursor.execute("""
                        SELECT COUNT(*) 
                        FROM blocked_ips
                        WHERE (ip = %s::inet OR ip::text = %s OR ip::text LIKE %s)
                        AND active = FALSE
                    """, (ip, ip, f"{ip}%"))
                    inactive_count = cursor.fetchone()[0]
                    
                    if inactive_count > 0:
                        cursor.close()
                        return {
                            "success": False,
                            "error": f"IP {ip} no está bloqueada actualmente (hay {inactive_count} bloqueo(s) histórico(s) que ya fueron desbloqueados)"
                        }
            except Exception as e:
                logger.error(f"Error desbloqueando desde blocked_ips: {e}", exc_info=True)
                # Continuar con el método anterior
            
            # Método anterior: verificar waf_logs
            cursor.execute("""
                SELECT COUNT(*) 
                FROM waf_logs 
                WHERE ip = %s 
                AND blocked = TRUE 
                AND classification_source = 'time_window_soc_analysis'
                AND timestamp > NOW() - INTERVAL '48 hours'
            """, (ip,))
            count = cursor.fetchone()[0]
            
            cursor.close()
            
            if count == 0:
                return {
                    "success": False,
                    "error": f"IP {ip} no está bloqueada actualmente"
                }
            
            # El bloqueo expira automáticamente después de 1 hora, pero podemos enviar señal de desbloqueo
            # Enviar mensaje a Kafka para que el sistema procese el desbloqueo
            if not KAFKA_AVAILABLE:
                return {
                    "success": True,
                    "message": f"IP {ip} será desbloqueada automáticamente (el bloqueo es temporal). Nota: kafka-python no está disponible para desbloqueo inmediato.",
                    "ip": ip
                }
            
            try:
                kafka_bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'YOUR_IP_ADDRESS:9093')
                producer = KafkaProducer(
                    bootstrap_servers=kafka_bootstrap,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    acks='all',
                    retries=3,
                    request_timeout_ms=10000
                )
                
                unblock_message = {
                    "action": "unblock_ip",
                    "ip": ip,
                    "reason": reason or f"Desbloqueado manualmente desde SOC Assistant",
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                
                producer.send('threats-detected', value=unblock_message)
                producer.flush(timeout=10)
                producer.close()
                
                logger.info(f"✅ IP {ip} desbloqueada desde SOC Assistant")
                
                return {
                    "success": True,
                    "message": f"IP {ip} enviada a desbloqueo. El desbloqueo se aplicará en breve.",
                    "ip": ip,
                    "reason": reason
                }
            except Exception as e:
                logger.error(f"Error enviando señal de desbloqueo: {e}")
                return {
                    "success": True,
                    "message": f"IP {ip} será desbloqueada automáticamente (el bloqueo es temporal). Nota: el sistema de desbloqueo inmediato requiere configuración adicional.",
                    "ip": ip
                }
        except Exception as e:
            logger.error(f"Error desbloqueando IP: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_attack_statistics(self, tenant_id: str = "default", time_window: str = "24h", **kwargs) -> Dict[str, Any]:
        """Obtiene estadísticas detalladas de ataques"""
        try:
            # Parsear time_window (ej: "24h", "7d", "1h" -> intervalo SQL)
            time_interval = "24 hours"
            if time_window:
                if time_window.endswith("h"):
                    hours = int(time_window[:-1])
                    time_interval = f"{hours} hours"
                elif time_window.endswith("d"):
                    days = int(time_window[:-1])
                    time_interval = f"{days} days"
                elif time_window.endswith("m"):
                    minutes = int(time_window[:-1])
                    time_interval = f"{minutes} minutes"
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            stats = {}
            
            # 1. Estadísticas generales
            query_general = f"""
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(CASE WHEN blocked = TRUE THEN 1 END) as blocked,
                    COUNT(CASE WHEN blocked = FALSE THEN 1 END) as allowed,
                    COUNT(DISTINCT ip) as unique_ips,
                    COUNT(DISTINCT CASE WHEN blocked = TRUE THEN ip END) as unique_blocked_ips
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '{time_interval}'
                {tenant_filter}
            """
            cursor.execute(query_general, params)
            row = cursor.fetchone()
            stats["general"] = {
                "total_requests": row[0] or 0,
                "blocked": row[1] or 0,
                "allowed": row[2] or 0,
                "unique_ips": row[3] or 0,
                "unique_blocked_ips": row[4] or 0,
                "block_rate": round((row[1] / row[0] * 100) if row[0] > 0 else 0, 2)
            }
            
            # 2. Por tipo de amenaza
            query_threats = f"""
                SELECT threat_type, COUNT(*) as count, COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '{time_interval}'
                AND threat_type IS NOT NULL
                {tenant_filter}
                GROUP BY threat_type
                ORDER BY count DESC
                LIMIT 20
            """
            cursor.execute(query_threats, params)
            stats["by_threat_type"] = [
                {"threat_type": row[0], "count": row[1], "unique_ips": row[2]}
                for row in cursor.fetchall()
            ]
            
            # 3. Por categoría OWASP
            query_owasp = f"""
                SELECT owasp_category, owasp_code, COUNT(*) as count, COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '{time_interval}'
                AND owasp_category IS NOT NULL
                {tenant_filter}
                GROUP BY owasp_category, owasp_code
                ORDER BY count DESC
                LIMIT 20
            """
            cursor.execute(query_owasp, params)
            stats["by_owasp"] = [
                {"owasp_category": row[0], "owasp_code": row[1], "count": row[2], "unique_ips": row[3]}
                for row in cursor.fetchall()
            ]
            
            # 4. IPs más activas (ataques)
            query_top_ips = f"""
                SELECT ip, COUNT(*) as count, COUNT(DISTINCT threat_type) as unique_threats,
                       MAX(timestamp) as last_seen
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '{time_interval}'
                AND blocked = TRUE
                {tenant_filter}
                GROUP BY ip
                ORDER BY count DESC
                LIMIT 20
            """
            cursor.execute(query_top_ips, params)
            stats["top_attacking_ips"] = []
            for row in cursor.fetchall():
                last_seen = row[3]
                if hasattr(last_seen, 'isoformat'):
                    last_seen = last_seen.isoformat()
                stats["top_attacking_ips"].append({
                    "ip": row[0],
                    "attack_count": row[1],
                    "unique_threats": row[2],
                    "last_seen": last_seen
                })
            
            # 5. Por fuente de clasificación
            query_source = f"""
                SELECT classification_source, COUNT(*) as count
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '{time_interval}'
                AND classification_source IS NOT NULL
                {tenant_filter}
                GROUP BY classification_source
                ORDER BY count DESC
            """
            cursor.execute(query_source, params)
            stats["by_classification_source"] = {
                row[0]: row[1] for row in cursor.fetchall()
            }
            
            cursor.close()
            
            return {
                "success": True,
                "data": stats,
                "time_window": time_window,
                "time_interval": time_interval
            }
        except Exception as e:
            logger.error(f"Error obteniendo attack statistics: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_agent_decisions(self, limit: int = 50, tenant_id: str = "default", **kwargs) -> Dict[str, Any]:
        """Obtiene las decisiones recientes del agente IA (bloqueos de IPs, análisis SOC)"""
        try:
            limit = min(limit, 200)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            from psycopg2.extras import RealDictCursor
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            # Obtener decisiones desde waf_logs con classification_source = 'time_window_soc_analysis'
            query = f"""
                SELECT DISTINCT ON (ip)
                    ip,
                    MAX(timestamp) as blocked_at,
                    MAX(threat_type) as threat_type,
                    MAX(severity) as severity,
                    MAX(owasp_code) as owasp_code,
                    MAX(owasp_category) as owasp_category,
                    COUNT(*) as total_logs,
                    ARRAY_AGG(DISTINCT threat_type) FILTER (WHERE threat_type IS NOT NULL) as threat_types,
                    ARRAY_AGG(DISTINCT uri) FILTER (WHERE uri IS NOT NULL) as sample_uris,
                    MAX(classification_source) as classification_source
                FROM waf_logs
                WHERE classification_source = 'time_window_soc_analysis'
                AND blocked = TRUE
                AND timestamp > NOW() - INTERVAL '48 hours'
                {tenant_filter}
                GROUP BY ip
                ORDER BY ip, MAX(timestamp) DESC
                LIMIT %s
            """
            params.append(limit)
            cursor.execute(query, params)
            
            decisions = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                blocked_at = row_dict.get('blocked_at')
                if blocked_at and hasattr(blocked_at, 'isoformat'):
                    blocked_at = blocked_at.isoformat()
                
                threat_types = row_dict.get('threat_types')
                if threat_types and isinstance(threat_types, list):
                    threat_types = list(threat_types)
                
                sample_uris = row_dict.get('sample_uris')
                if sample_uris and isinstance(sample_uris, list):
                    sample_uris = list(sample_uris)[:5]
                
                decisions.append({
                    "ip": row_dict.get('ip'),
                    "blocked_at": blocked_at,
                    "threat_type": row_dict.get('threat_type'),
                    "severity": row_dict.get('severity'),
                    "owasp_code": row_dict.get('owasp_code'),
                    "owasp_category": row_dict.get('owasp_category'),
                    "total_logs": row_dict.get('total_logs', 0),
                    "threat_types": threat_types,
                    "sample_uris": sample_uris,
                    "classification_source": row_dict.get('classification_source') or "time_window_soc_analysis",
                    "decision_type": "block_ip",
                    "source": "soc_agent"
                })
            
            # También intentar obtener desde tabla blocked_ips si existe (time_window_soc_analysis)
            try:
                cursor.execute(f"""
                    SELECT 
                        ip,
                        blocked_at,
                        expires_at,
                        reason,
                        threat_type,
                        severity,
                        classification_source
                    FROM blocked_ips
                    WHERE active = TRUE
                    AND (expires_at IS NULL OR expires_at > NOW())
                    AND classification_source = 'time_window_soc_analysis'
                    {tenant_filter if tenant_filter else ''}
                    ORDER BY blocked_at DESC
                    LIMIT %s
                """, (params[:-1] + [limit]) if tenant_filter else [limit])
                
                blocked_ips_dict = {d['ip']: d for d in decisions}
                
                for row in cursor.fetchall():
                    row_dict = dict(row)  # RealDictCursor devuelve dicts
                    blocked_ip_data = {
                        "ip": row_dict.get('ip'),
                        "blocked_at": row_dict.get('blocked_at').isoformat() if row_dict.get('blocked_at') and hasattr(row_dict.get('blocked_at'), 'isoformat') else row_dict.get('blocked_at'),
                        "expires_at": row_dict.get('expires_at').isoformat() if row_dict.get('expires_at') and hasattr(row_dict.get('expires_at'), 'isoformat') else row_dict.get('expires_at'),
                        "reason": row_dict.get('reason'),
                        "threat_type": row_dict.get('threat_type'),
                        "severity": row_dict.get('severity'),
                        "classification_source": row_dict.get('classification_source') or "time_window_soc_analysis",
                        "decision_type": "block_ip",
                        "source": "soc_agent"
                    }
                    
                    # Combinar con datos de waf_logs si ya existe
                    if row_dict.get('ip') in blocked_ips_dict:
                        blocked_ips_dict[row_dict.get('ip')]['reason'] = blocked_ip_data.get('reason')
                        blocked_ips_dict[row_dict.get('ip')]['expires_at'] = blocked_ip_data.get('expires_at')
                    else:
                        decisions.append(blocked_ip_data)
            except Exception as e:
                logger.debug(f"Tabla blocked_ips no disponible o error: {e}")
            
            # NUEVO: También consultar episodios bloqueados automáticamente (classification_source = 'episode_analysis')
            try:
                from psycopg2.extras import RealDictCursor
                cursor_episodes = self.db_conn.cursor(cursor_factory=RealDictCursor)
                
                cursor_episodes.execute(f"""
                    SELECT 
                        bi.ip,
                        bi.blocked_at,
                        bi.expires_at,
                        bi.reason,
                        bi.threat_type,
                        bi.severity,
                        bi.classification_source,
                        e.episode_id,
                        e.total_requests,
                        e.unique_uris,
                        e.risk_score,
                        e.decision,
                        e.episode_start,
                        e.episode_end
                    FROM blocked_ips bi
                    LEFT JOIN LATERAL (
                        SELECT e.*
                        FROM episodes e
                        WHERE e.src_ip::text = bi.ip::text
                        AND e.created_at >= bi.blocked_at - INTERVAL '1 hour'
                        AND e.created_at <= bi.blocked_at + INTERVAL '1 hour'
                        ORDER BY ABS(EXTRACT(EPOCH FROM (e.created_at - bi.blocked_at))) ASC
                        LIMIT 1
                    ) e ON TRUE
                    WHERE bi.classification_source = 'episode_analysis'
                    AND bi.active = TRUE
                    AND (bi.expires_at IS NULL OR bi.expires_at > NOW())
                    AND bi.blocked_at > NOW() - INTERVAL '48 hours'
                    {tenant_filter if tenant_filter else ''}
                    ORDER BY bi.blocked_at DESC
                    LIMIT %s
                """, (params[:-1] + [limit]) if tenant_filter else [limit])
                
                blocked_ips_dict = {d['ip']: d for d in decisions}
                
                for row in cursor_episodes.fetchall():
                    row_dict = dict(row)
                    blocked_ip_data = {
                        "ip": row_dict['ip'],
                        "blocked_at": row_dict['blocked_at'].isoformat() if hasattr(row_dict['blocked_at'], 'isoformat') else row_dict['blocked_at'],
                        "expires_at": row_dict['expires_at'].isoformat() if row_dict['expires_at'] and hasattr(row_dict['expires_at'], 'isoformat') else row_dict['expires_at'],
                        "reason": row_dict.get('reason'),
                        "threat_type": row_dict.get('threat_type'),
                        "severity": row_dict.get('severity'),
                        "classification_source": row_dict.get('classification_source') or "episode_analysis",
                        "episode_id": row_dict.get('episode_id'),
                        "total_requests": row_dict.get('total_requests'),
                        "unique_uris": row_dict.get('unique_uris'),
                        "risk_score": float(row_dict.get('risk_score', 0)) if row_dict.get('risk_score') else None,
                        "decision": row_dict.get('decision'),
                        "episode_start": row_dict['episode_start'].isoformat() if row_dict.get('episode_start') and hasattr(row_dict['episode_start'], 'isoformat') else row_dict.get('episode_start'),
                        "episode_end": row_dict['episode_end'].isoformat() if row_dict.get('episode_end') and hasattr(row_dict['episode_end'], 'isoformat') else row_dict.get('episode_end'),
                        "decision_type": "block_ip",
                        "source": "episode_analysis"
                    }
                    
                    # Combinar si ya existe
                    if row_dict['ip'] in blocked_ips_dict:
                        # Actualizar con datos de episodio si son más completos
                        if blocked_ip_data.get('episode_id'):
                            blocked_ips_dict[row_dict['ip']].update({
                                'episode_id': blocked_ip_data.get('episode_id'),
                                'total_requests': blocked_ip_data.get('total_requests'),
                                'unique_uris': blocked_ip_data.get('unique_uris'),
                                'risk_score': blocked_ip_data.get('risk_score'),
                                'classification_source': 'episode_analysis'
                            })
                    else:
                        decisions.append(blocked_ip_data)
                
                cursor_episodes.close()
            except Exception as e:
                logger.debug(f"Error consultando episodios bloqueados: {e}")
            
            # Ordenar por fecha de bloqueo (más recientes primero)
            decisions.sort(key=lambda x: x.get('blocked_at', ''), reverse=True)
            decisions = decisions[:limit]
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "count": len(decisions),
                    "decisions": decisions
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo agent decisions: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def query_episodes(self, ip: Optional[str] = None, decision: Optional[str] = None, 
                            risk_score_min: Optional[float] = None, hours: int = 24, limit: int = 50, **kwargs) -> Dict[str, Any]:
        """Consulta episodios con filtros específicos"""
        try:
            from psycopg2.extras import RealDictCursor
            limit = min(limit, 200)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
            
            # Verificar si la columna sample_uris existe
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'episodes' 
                AND column_name = 'sample_uris'
            """)
            has_sample_uris = cursor.fetchone() is not None
            
            # Verificar si existe intelligence_analysis
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'episodes' 
                AND column_name = 'intelligence_analysis'
            """)
            has_intelligence = cursor.fetchone() is not None
            
            # Construir query dinámicamente
            base_fields = """
                episode_id, src_ip, episode_start, episode_end,
                total_requests, unique_uris, request_rate,
                risk_score, decision, llm_consulted,
                presence_flags, status_code_ratio
            """
            sample_uris_field = "sample_uris" if has_sample_uris else "'[]'::jsonb as sample_uris"
            intelligence_field = "intelligence_analysis" if has_intelligence else "'{}'::jsonb as intelligence_analysis"
            
            query = f"""
                SELECT 
                    {base_fields},
                    {sample_uris_field},
                    {intelligence_field}
                FROM episodes
                WHERE created_at > NOW() - INTERVAL %s
            """
            params = [f"{hours} hours"]
            
            if ip:
                query += " AND src_ip::text = %s"
                params.append(ip)
            
            if decision:
                query += " AND decision = %s"
                params.append(decision)
            
            if risk_score_min is not None:
                query += " AND risk_score >= %s"
                params.append(risk_score_min)
            
            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            episodes = []
            for row in cursor.fetchall():
                episode_dict = dict(row)
                # Convertir timestamps a ISO format
                for key in ['episode_start', 'episode_end']:
                    if episode_dict.get(key) and hasattr(episode_dict[key], 'isoformat'):
                        episode_dict[key] = episode_dict[key].isoformat()
                episodes.append(episode_dict)
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "episodes": episodes,
                    "count": len(episodes)
                }
            }
        except Exception as e:
            logger.error(f"Error consultando episodios: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def query_blocked_ips(self, ip: Optional[str] = None, active_only: bool = True, 
                               hours: int = 24, limit: int = 100, **kwargs) -> Dict[str, Any]:
        """Consulta IPs bloqueadas desde blocked_ips
        
        Si se especifica una IP, busca sin límite de tiempo para encontrar bloqueos históricos.
        También incluye episodios relacionados para dar más contexto.
        
        IMPORTANTE: Cuando se busca una IP específica, automáticamente busca tanto bloqueos
        activos como históricos (incluso si ya expiraron) para dar una respuesta completa.
        """
        try:
            from psycopg2.extras import RealDictCursor
            limit = min(limit, 200)
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
            
            # Si se especifica una IP, buscar sin límite de tiempo (búsqueda histórica completa)
            # Cuando se busca una IP específica, automáticamente buscar TODOS los bloqueos
            # (activos e inactivos) para dar una respuesta completa, independientemente del
            # valor de active_only
            if ip:
                # Para búsquedas de IP específica, siempre buscar todos los bloqueos
                # Esto permite encontrar bloqueos incluso si ya expiraron
                # Usar comparación con tipo INET directamente o convertir ambos lados
                query = """
                    SELECT 
                        ip, blocked_at, expires_at, reason,
                        threat_type, severity, classification_source, active
                    FROM blocked_ips
                    WHERE ip = %s::inet OR ip::text = %s OR ip::text LIKE %s
                    ORDER BY blocked_at DESC
                    LIMIT %s
                """
                # Buscar con diferentes formatos: IP directa, IP/32, IP/128
                ip_pattern = f"{ip}%"
                params = [ip, ip, ip_pattern, limit]
                # NO aplicamos filtro de active_only cuando se busca una IP específica
                # Queremos ver todos los bloqueos históricos
            else:
                query = """
                    SELECT 
                        ip, blocked_at, expires_at, reason,
                        threat_type, severity, classification_source, active
                    FROM blocked_ips
                    WHERE blocked_at > NOW() - INTERVAL %s
                """
                params = [f"{hours} hours"]
                
                if active_only:
                    query += " AND active = TRUE AND (expires_at IS NULL OR expires_at > NOW())"
            
                query += " ORDER BY blocked_at DESC LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
            blocked_ips = []
            for row in cursor.fetchall():
                blocked_ip_dict = dict(row)
                # Convertir timestamps a ISO format
                for key in ['blocked_at', 'expires_at']:
                    if blocked_ip_dict.get(key) and hasattr(blocked_ip_dict[key], 'isoformat'):
                        blocked_ip_dict[key] = blocked_ip_dict[key].isoformat()
                blocked_ips.append(blocked_ip_dict)
            
            # Si se busca una IP específica, también buscar episodios relacionados
            related_episodes = []
            if ip:
                # Buscar episodios incluso si no hay bloqueos encontrados (para dar contexto completo)
                try:
                    cursor.execute("""
                        SELECT 
                            episode_id, episode_start, episode_end, decision,
                            risk_score, total_requests, unique_uris, 
                            presence_flags, status_code_ratio, llm_label
                        FROM episodes
                        WHERE src_ip = %s::inet OR src_ip::text = %s OR src_ip::text LIKE %s
                        ORDER BY episode_start DESC
                        LIMIT 10
                    """, [ip, ip, f"{ip}%"])
                    
                    for row in cursor.fetchall():
                        ep_dict = dict(row)
                        for key in ['episode_start', 'episode_end']:
                            if ep_dict.get(key) and hasattr(ep_dict[key], 'isoformat'):
                                ep_dict[key] = ep_dict[key].isoformat()
                        related_episodes.append(ep_dict)
                except Exception as e:
                    logger.warning(f"Error obteniendo episodios relacionados: {e}")
                    # Continuar sin episodios relacionados si hay error
            
            cursor.close()
            
            result = {
                "success": True,
                "data": {
                    "blocked_ips": blocked_ips,
                    "count": len(blocked_ips),
                    "active_count": sum(1 for bi in blocked_ips if bi.get('active'))
                }
            }
            
            if related_episodes:
                result["data"]["related_episodes"] = related_episodes
                result["data"]["episodes_count"] = len(related_episodes)
            
            return result
        except Exception as e:
            logger.error(f"Error consultando IPs bloqueadas: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_episode_stats(self, hours: int = 24, **kwargs) -> Dict[str, Any]:
        """Obtiene estadísticas agregadas de episodios"""
        try:
            from psycopg2.extras import RealDictCursor
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_episodes,
                    COUNT(*) FILTER (WHERE decision = 'BLOCK') as blocked_episodes,
                    COUNT(*) FILTER (WHERE decision = 'ALLOW') as allowed_episodes,
                    COUNT(*) FILTER (WHERE decision = 'UNCERTAIN') as uncertain_episodes,
                    COUNT(*) FILTER (WHERE llm_consulted = TRUE) as llm_consulted_count,
                    AVG(risk_score) as avg_risk_score,
                    AVG(total_requests) as avg_requests_per_episode,
                    COUNT(DISTINCT src_ip) as unique_ips
                FROM episodes
                WHERE created_at > NOW() - INTERVAL %s
            """, [f"{hours} hours"])
            
            stats = dict(cursor.fetchone())
            cursor.close()
            
            return {
                "success": True,
                "data": stats
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de episodios: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_blocking_effectiveness(self, hours: int = 24, **kwargs) -> Dict[str, Any]:
        """Analiza efectividad de bloqueos"""
        try:
            from psycopg2.extras import RealDictCursor
            
            if not self.db_conn:
                self._init_db_connection()
            
            if not self.db_conn:
                return {"success": False, "error": "No hay conexión a la base de datos"}
            
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)
            
            # IPs bloqueadas
            cursor.execute("""
                SELECT COUNT(DISTINCT ip) as total_blocked
                FROM blocked_ips
                WHERE blocked_at > NOW() - INTERVAL %s
                AND active = TRUE
            """, [f"{hours} hours"])
            total_blocked = cursor.fetchone()['total_blocked']
            
            # IPs que intentaron atacar después de ser bloqueadas
            cursor.execute("""
                SELECT COUNT(DISTINCT e.src_ip) as re_attack_count
                FROM episodes e
                INNER JOIN blocked_ips bi ON bi.ip::text = e.src_ip::text
                WHERE e.created_at > bi.blocked_at
                AND e.created_at <= bi.blocked_at + INTERVAL '1 hour'
                AND e.decision = 'BLOCK'
                AND e.created_at > NOW() - INTERVAL %s
            """, [f"{hours} hours"])
            re_attack_count = cursor.fetchone()['re_attack_count']
            
            effectiveness = (1 - (re_attack_count / total_blocked)) * 100 if total_blocked > 0 else 100
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "total_blocked": total_blocked,
                    "re_attack_count": re_attack_count,
                    "effectiveness_percent": round(effectiveness, 2)
                }
            }
        except Exception as e:
            logger.error(f"Error obteniendo efectividad de bloqueos: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def close(self):
        """Cierra la conexión a la base de datos"""
        if self.db_conn:
            try:
                self.db_conn.close()
                logger.info("Conexión a DB cerrada para SOC Assistant Tools")
            except Exception as e:
                logger.error(f"Error cerrando conexión DB: {e}")
            finally:
                self.db_conn = None

