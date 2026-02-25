#!/usr/bin/env python3.11
"""
MCP Server para CYBORG-SENTINEL AI - Integración con SOAR, Kafka (FW/WAF) y PostgreSQL
"""

import asyncio
import json
import os
import sys
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

# Configurar proxy para conexiones HTTP/HTTPS (solo si está explícitamente definido)
_http_proxy = os.getenv('HTTP_PROXY', '').strip()
if _http_proxy:
    os.environ['http_proxy'] = _http_proxy
    os.environ['https_proxy'] = os.getenv('HTTPS_PROXY', _http_proxy).strip()

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logging.warning("MCP SDK no disponible")

# Configuración de logging
# Reducir nivel de logging de Kafka para evitar warnings excesivos
logging.getLogger('kafka').setLevel(logging.ERROR)  # Solo errores, no warnings
logging.getLogger('kafka.coordinator').setLevel(logging.ERROR)
logging.getLogger('kafka.coordinator.heartbeat').setLevel(logging.ERROR)
logging.getLogger('kafka.conn').setLevel(logging.ERROR)
logging.getLogger('kafka.consumer').setLevel(logging.ERROR)
logging.getLogger('kafka.cluster').setLevel(logging.ERROR)
logging.getLogger('kafka.consumer.fetcher').setLevel(logging.ERROR)
logging.getLogger('kafka.consumer.subscription_state').setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración del servidor MCP
app = Server("cyborg-sentinel-server") if MCP_AVAILABLE else None

# Feature flags para habilitar/deshabilitar tools por entorno
ENABLE_SOAR = os.getenv("TOKIO_ENABLE_SOAR", "false").lower() == "true"
ENABLE_KAFKA = os.getenv("TOKIO_ENABLE_KAFKA", "true").lower() == "true"
ENABLE_POSTGRESQL = os.getenv("TOKIO_ENABLE_POSTGRESQL", "true").lower() == "true"
ENABLE_HORUS = os.getenv("TOKIO_ENABLE_HORUS", "false").lower() == "true"
ENABLE_ATLASSIAN = os.getenv("TOKIO_ENABLE_ATLASSIAN", "false").lower() == "true"
ENABLE_VULNERABILITY = os.getenv("TOKIO_ENABLE_VULNERABILITY", "false").lower() == "true"
ENABLE_FILE_TOOLS = os.getenv("TOKIO_ENABLE_FILE_TOOLS", "false").lower() == "true"
ENABLE_TOKIO_TOOLS = os.getenv("TOKIO_ENABLE_TOKIO_TOOLS", "true").lower() == "true"
ENABLE_AUTOMATION_TOOLS = os.getenv("TOKIO_ENABLE_AUTOMATION_TOOLS", "true").lower() == "true"
ENABLE_SPOTIFY_TOOLS = os.getenv("TOKIO_ENABLE_SPOTIFY_TOOLS", "true").lower() == "true"

# Importar tools
try:
    from tools.soar_tools import (
        tool_get_incident,
        tool_list_incidents,
        tool_create_incident,
        tool_update_incident,
        tool_close_incident,
        tool_search_incidents,
        tool_get_incident_comments,
        tool_list_playbooks,
        tool_get_playbook,
        tool_check_playbook_status,
        tool_health_check_soar,
        tool_search_soar_wiki
    )
    SOAR_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SOAR tools no disponibles: {e}")
    SOAR_TOOLS_AVAILABLE = False

try:
    from tools.kafka_tools import (
        tool_search_fw_logs,
        tool_search_waf_logs,
        tool_check_ip_mitigation
    )
    KAFKA_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Kafka tools no disponibles: {e}")
    KAFKA_TOOLS_AVAILABLE = False

try:
    from tools.postgresql_tools import (
        tool_query_data,
        tool_insert_data,
        tool_update_data,
        tool_delete_data,
        tool_get_table_schema
    )
    POSTGRESQL_TOOLS_AVAILABLE = True
except ImportError:
    POSTGRESQL_TOOLS_AVAILABLE = False

try:
    from tools.horus_tools import (
        tool_get_ip_info
    )
    HORUS_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Horus tools no disponibles: {e}")
    HORUS_TOOLS_AVAILABLE = False

try:
    from tools.atlassian_tools import (
        tool_search_ip_in_confluence,
        tool_search_content_in_confluence,
        tool_search_ip_in_jira,
        tool_search_jira_issues,
        tool_get_jira_boards,
        tool_search_jira_boards,
        tool_get_jira_issue_types,
        tool_get_jira_issue,
        tool_create_jira_issue,
        tool_validate_jira_issue_creation,
        tool_search_jira_sandbox
    )
    ATLASSIAN_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Atlassian tools no disponibles: {e}")
    ATLASSIAN_TOOLS_AVAILABLE = False

try:
    from tools.vulnerability_tools import (
        tool_test_vulnerability,
        tool_test_vulnerability_with_log_monitoring
    )
    VULNERABILITY_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Vulnerability tools no disponibles: {e}")
    VULNERABILITY_TOOLS_AVAILABLE = False

try:
    from tools.incident_cache import (
        sync_incidents_from_soar_api,
        get_cache_stats
    )
    from tools.cache_maintenance import (
        cleanup_old_incidents,
        get_cache_metrics,
        optimize_cache_indexes
    )
    INCIDENT_CACHE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Incident cache tools no disponibles: {e}")
    INCIDENT_CACHE_AVAILABLE = False

try:
    from tools.file_tools import (
        tool_write_file,
        tool_read_file
    )
    FILE_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"File tools no disponibles: {e}")
    FILE_TOOLS_AVAILABLE = False

try:
    from tools.tokio_tools import (
        tool_search_waf_logs_tokio,
        tool_list_episodes_tokio,
        tool_list_blocked_ips_tokio,
        tool_block_ip_tokio,
        tool_unblock_ip_tokio,
        tool_get_summary_tokio
    )
    TOKIO_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Tokio tools no disponibles: {e}")
    TOKIO_TOOLS_AVAILABLE = False

try:
    from tools.automation_tools import (
        tool_propose_tool,
        tool_propose_command,
        tool_list_automation_pending,
        tool_list_automation_approved,
        tool_run_approved_tool
    )
    AUTOMATION_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Automation tools no disponibles: {e}")
    AUTOMATION_TOOLS_AVAILABLE = False

try:
    from tools.spotify_tools import (
        tool_create_spotify_playlist,
        tool_search_spotify_tracks,
        tool_set_spotify_refresh_token
    )
    SPOTIFY_TOOLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Spotify tools no disponibles: {e}")
    SPOTIFY_TOOLS_AVAILABLE = False


if MCP_AVAILABLE and app:
    @app.list_tools()
    async def list_tools() -> List[types.Tool]:
        tools = []
        
        if SOAR_TOOLS_AVAILABLE and ENABLE_SOAR:
            tools.extend([
                types.Tool(
                    name="get_incident",
                    description="Obtiene los detalles completos de un incidente por ID. Incluye automáticamente: estado, propietario, fechas, comentarios/notas, adjuntos y resumen del estado.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "incident_id": {"type": "string", "description": "ID del incidente"},
                            "include_details": {"type": "boolean", "default": True, "description": "Si True, incluye comentarios, adjuntos y detalles adicionales"}
                        },
                        "required": ["incident_id"]
                    }
                ),
                types.Tool(
                    name="list_incidents",
                    description="Lista incidentes con filtros (status, severity, incident_type, fechas). Permite buscar en todo el historial con rangos de fecha personalizados.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "description": "Filtrar por estado (open, closed)"},
                            "severity": {"type": "string", "description": "Filtrar por severidad"},
                            "limit": {"type": "integer", "default": 50},
                            "offset": {"type": "integer", "default": 0, "description": "Offset para paginación"},
                            "incident_type": {"type": "string", "description": "Filtrar por tipo o código"},
                            "start_date": {"type": "string", "description": "Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)"},
                            "end_date": {"type": "string", "description": "Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)"}
                        }
                    }
                ),
                types.Tool(
                    name="get_incident_comments",
                    description="Obtiene los comentarios y notas de un incidente específico",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "incident_id": {"type": "string", "description": "ID del incidente"}
                        },
                        "required": ["incident_id"]
                    }
                ),
                types.Tool(
                    name="search_incidents",
                    description="Busca incidentes usando búsqueda de texto completo en SOAR. Permite buscar en todo el historial con rangos de fecha personalizados. Busca en name, description, properties, artifacts y comments.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto a buscar (puede ser una IP, nombre, descripción, etc.)"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "start_date": {"type": "string", "description": "Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)"},
                            "end_date": {"type": "string", "description": "Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)"},
                            "search_all_history": {"type": "boolean", "default": False, "description": "Si es True, busca en todo el historial sin límite de incidentes (hasta 5000)"}
                        },
                        "required": ["query"]
                    }
                ),
                types.Tool(
                    name="close_incident",
                    description="Cierra un incidente con una razón de resolución. Usa el formato correcto de la API de SOAR con resolution_id, resolution_summary y plan_status.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "incident_id": {"type": "string", "description": "ID del incidente a cerrar"},
                            "resolution": {"type": "string", "description": "Razón de cierre (se guardará en resolution_summary)"},
                            "resolution_id": {"type": "integer", "default": 10, "description": "ID de resolución (10=Resolved, default)"}
                        },
                        "required": ["incident_id", "resolution"]
                    }
                ),
                types.Tool(
                    name="list_playbooks",
                    description="Lista los playbooks disponibles en SOAR con sus nombres y estados",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "default": 100, "description": "Límite de playbooks a listar"}
                        }
                    }
                ),
                types.Tool(
                    name="get_playbook",
                    description="Obtiene los detalles completos de un playbook específico por ID, incluyendo sus reglas, acciones y configuración",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "playbook_id": {"type": "string", "description": "ID del playbook"}
                        },
                        "required": ["playbook_id"]
                    }
                ),
                types.Tool(
                    name="check_playbook_status",
                    description="Verifica el estado y disponibilidad de un playbook. Incluye si está habilitado, acciones relacionadas, y si se ejecutó recientemente en algún incidente. Útil para verificar si un playbook está operativo.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "playbook_id": {"type": "string", "description": "ID del playbook"},
                            "playbook_name": {"type": "string", "description": "Nombre del playbook para buscar"}
                        }
                    }
                ),
                types.Tool(
                    name="health_check_soar",
                    description="Realiza un check de salud completo del SOAR mediante múltiples tests: conectividad API, lectura de incidentes, playbooks, autenticación. Ideal para monitoreo diario automático.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                types.Tool(
                    name="search_soar_wiki",
                    description="Busca en la wiki del SOAR (artículos de documentación/knowledge base). Útil para encontrar tutoriales, guías y documentación interna del SOAR.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto a buscar en la wiki del SOAR"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"}
                        },
                        "required": ["query"]
                    }
                )
            ])
        
        if INCIDENT_CACHE_AVAILABLE:
            tools.extend([
                types.Tool(
                    name="sync_incidents_to_cache",
                    description="Sincroniza incidentes históricos desde la API SOAR a la base de datos de caché PostgreSQL. Permite búsquedas rápidas y eficientes de incidentes históricos (meses o años atrás). Útil para sincronizar incidentes antes de hacer búsquedas históricas extensas.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "days_back": {"type": "integer", "default": 365, "description": "Cuántos días hacia atrás sincronizar (default: 365 = 1 año)"},
                            "incident_type_ids": {"type": "array", "items": {"type": "integer"}, "description": "Lista de IDs de tipo de incidente a sincronizar (opcional, si None sincroniza todos)"},
                            "max_incidents": {"type": "integer", "default": 50000, "description": "Máximo número de incidentes a sincronizar"},
                            "batch_size": {"type": "integer", "default": 2000, "description": "Tamaño de lote para procesar incidentes"}
                        }
                    }
                ),
                types.Tool(
                    name="get_cache_stats",
                    description="Obtiene estadísticas de la caché de incidentes: total de incidentes, distribución por estado, rango de fechas, y última sincronización. Útil para verificar el estado de la sincronización.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                types.Tool(
                    name="cleanup_old_incidents",
                    description="Limpia incidentes antiguos de la caché según política de retención configurada. Elimina incidentes más antiguos que el período de retención (por defecto 730 días = 2 años) o que excedan el máximo permitido (500K). Ejecuta VACUUM para optimizar el espacio. Útil para mantener la caché optimizada y las consultas rápidas.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "retention_days": {"type": "integer", "description": "Días de retención (default: 730 días = 2 años, mínimo: 365 días)"},
                            "max_incidents": {"type": "integer", "description": "Máximo número de incidentes a mantener (default: 500000)"},
                            "dry_run": {"type": "boolean", "default": False, "description": "Si True, solo calcula qué se eliminaría sin eliminar realmente"}
                        }
                    }
                ),
                types.Tool(
                    name="get_cache_metrics",
                    description="Obtiene métricas detalladas de la caché de incidentes incluyendo tamaño, distribución por año, capacidad estimada, y configuración de retención. Útil para monitorear el uso de la caché y planificar limpiezas.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                types.Tool(
                    name="optimize_cache_indexes",
                    description="Optimiza los índices de la caché de incidentes ejecutando REINDEX y ANALYZE. Mejora el rendimiento de las consultas. Útil ejecutarlo periódicamente o después de sincronizaciones grandes.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                )
            ])
        
        if FILE_TOOLS_AVAILABLE and ENABLE_FILE_TOOLS:
            tools.extend([
                types.Tool(
                    name="write_file",
                    description="Guarda contenido en un archivo de texto. Útil para guardar resultados de búsquedas, análisis, o cualquier salida de texto. Por defecto guarda en /irt/proyectos/soar-mcp-server/exports/",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Contenido a guardar en el archivo"
                            },
                            "filename": {
                                "type": "string",
                                "description": "Nombre del archivo (opcional, se genera automáticamente con timestamp si no se proporciona)"
                            },
                            "directory": {
                                "type": "string",
                                "description": "Directorio donde guardar (opcional, por defecto: /irt/proyectos/soar-mcp-server/exports)"
                            },
                            "append": {
                                "type": "boolean",
                                "default": False,
                                "description": "Si es True, agrega al final del archivo. Si es False, sobrescribe el archivo."
                            }
                        },
                        "required": ["content"]
                    }
                ),
                types.Tool(
                    name="read_file",
                    description="Lee el contenido de un archivo de texto.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filepath": {
                                "type": "string",
                                "description": "Ruta completa del archivo a leer"
                            }
                        },
                        "required": ["filepath"]
                    }
                )
            ])
        
        if KAFKA_TOOLS_AVAILABLE and ENABLE_KAFKA:
            tools.extend([
                types.Tool(
                    name="search_fw_logs",
                    description="Busca logs de Firewall persistidos desde Kafka (FW) con soporte para patrón, rangos de fechas y filtros avanzados. Optimizado para tablas grandes con timeout de 180s para rangos temporales largos.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP de origen o destino"},
                            "port": {"type": "integer", "description": "Puerto origen o destino"},
                            "action": {"type": "string", "description": "Acción (permit, deny, etc.)"},
                            "pattern": {"type": "string", "description": "Patrón de texto a buscar en raw_log (usando ILIKE, case-insensitive)"},
                            "start_date": {"type": "string", "description": "Fecha de inicio (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS). Si se especifica, ignora 'days'."},
                            "end_date": {"type": "string", "description": "Fecha de fin (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS). Si se especifica, ignora 'days'."},
                            "limit": {"type": "integer", "default": 100, "description": "Límite de resultados (máximo 1000, default: 100)"},
                            "days": {"type": "integer", "default": 7, "description": "Días hacia atrás para buscar (default: 7 días, solo se usa si no se especifican start_date/end_date)"}
                        }
                    }
                ),
                types.Tool(
                    name="search_waf_logs",
                    description="Busca logs de WAF persistidos desde Kafka con soporte para patrón, rangos de fechas y filtros avanzados. Optimizado para tablas grandes con timeout de 180s para rangos temporales largos. Soporta búsqueda de bypass de firmas WAF.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP del cliente atacante"},
                            "host": {"type": "string", "description": "Host atacado (búsqueda parcial con ILIKE)"},
                            "pattern": {"type": "string", "description": "Patrón de texto a buscar en url o raw_log (usando ILIKE, case-insensitive). Útil para buscar SQL injection, XSS, etc."},
                            "url_pattern": {"type": "string", "description": "Patrón específico para buscar solo en la columna url (usando ILIKE)"},
                            "start_date": {"type": "string", "description": "Fecha de inicio (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS). Si se especifica, ignora 'days'."},
                            "end_date": {"type": "string", "description": "Fecha de fin (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS). Si se especifica, ignora 'days'."},
                            "limit": {"type": "integer", "default": 100, "description": "Límite de resultados (máximo 1000, default: 100)"},
                            "days": {"type": "integer", "default": 7, "description": "Días hacia atrás para buscar (default: 7 días, solo se usa si no se especifican start_date/end_date)"}
                        }
                    }
                ),
                types.Tool(
                    name="check_ip_mitigation",
                    description="Verifica si una IP está siendo mitigada en FW o WAF",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a verificar"}
                        },
                        "required": ["ip"]
                    }
                )
            ])

        if POSTGRESQL_TOOLS_AVAILABLE and ENABLE_POSTGRESQL:
            tools.append(
                types.Tool(
                    name="query_data",
                    description="Ejecuta una consulta SQL personalizada o por tabla en PostgreSQL (solo lectura). Permite filtrar por rangos de fecha automáticamente.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "sql_query": {"type": "string", "description": "Consulta SQL completa (SELECT ...)"},
                            "table": {"type": "string", "description": "Tabla si no se usa sql_query"},
                            "columns": {"type": "array", "items": {"type": "string"}, "description": "Lista de columnas a seleccionar (si no se usa sql_query)"},
                            "where": {"type": "object", "description": "Condiciones WHERE como diccionario (si no se usa sql_query)"},
                            "limit": {"type": "integer", "default": 100, "description": "Límite de resultados"},
                            "order_by": {"type": "string", "description": "Columna para ordenar"},
                            "start_date": {"type": "string", "description": "Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)"},
                            "end_date": {"type": "string", "description": "Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)"},
                            "date_column": {"type": "string", "description": "Nombre de la columna de fecha para filtrar (por defecto: created_at, updated_at, timestamp, date)"}
                        }
                    }
                )
            )
        
        # Deshabilitar Horus (no disponible en Tokio AI)
        # if HORUS_TOOLS_AVAILABLE:
        #     tools.append(...)
        
        # Tokio AI Tools - Solo usar estas
        if TOKIO_TOOLS_AVAILABLE and ENABLE_TOKIO_TOOLS:
            tools.extend([
                types.Tool(
                    name="search_waf_logs_tokio",
                    description="Busca logs de WAF en PostgreSQL. Soporta búsqueda por IP, patrón de texto (SQLi, XSS, etc.), URL, host y rangos de fecha. Esta es la herramienta principal para buscar en logs de WAF.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a buscar (opcional)"},
                            "pattern": {"type": "string", "description": "Patrón de texto a buscar en uri o raw_log (case-insensitive). Útil para buscar SQLi, XSS, etc. (opcional)"},
                            "url_pattern": {"type": "string", "description": "Patrón específico para buscar solo en la columna uri (opcional)"},
                            "host": {"type": "string", "description": "Host a buscar (búsqueda parcial, opcional)"},
                            "days": {"type": "integer", "default": 7, "description": "Días hacia atrás (default: 7)"},
                            "limit": {"type": "integer", "default": 100, "description": "Límite de resultados (default: 100)"}
                        }
                    }
                ),
                types.Tool(
                    name="list_episodes_tokio",
                    description="Lista episodios de seguridad detectados",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "status": {"type": "string", "description": "Filtrar por estado (opcional)"}
                        }
                    }
                ),
                types.Tool(
                    name="list_blocked_ips_tokio",
                    description="Lista IPs bloqueadas activas",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "active_only": {"type": "boolean", "default": True, "description": "Solo IPs activas"}
                        }
                    }
                ),
                types.Tool(
                    name="block_ip_tokio",
                    description="Bloquea una IP por un período de tiempo",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a bloquear"},
                            "duration_hours": {"type": "integer", "default": 24, "description": "Duración en horas"},
                            "reason": {"type": "string", "default": "Bloqueo manual desde CLI", "description": "Razón del bloqueo"}
                        },
                        "required": ["ip"]
                    }
                ),
                types.Tool(
                    name="unblock_ip_tokio",
                    description="Desbloquea una IP bloqueada",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a desbloquear"},
                            "reason": {"type": "string", "default": "Desbloqueo manual desde CLI", "description": "Razón del desbloqueo"}
                        },
                        "required": ["ip"]
                    }
                ),
                types.Tool(
                    name="get_summary_tokio",
                    description="Obtiene un resumen de ataques, episodios y bloqueos",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "days": {"type": "integer", "default": 7, "description": "Días hacia atrás"}
                        }
                    }
                )
            ])

        if AUTOMATION_TOOLS_AVAILABLE and ENABLE_AUTOMATION_TOOLS:
            tools.extend([
                types.Tool(
                    name="propose_tool_tokio",
                    description="Propone una nueva tool para aprobación humana (no se ejecuta automáticamente).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Título de la tool"},
                            "description": {"type": "string", "description": "Descripción breve"},
                            "code": {"type": "string", "description": "Código Python de la tool"},
                            "input_schema": {"type": "object", "description": "Schema de entrada opcional"}
                        },
                        "required": ["title", "code"]
                    }
                ),
                types.Tool(
                    name="propose_command_tokio",
                    description="Propone un comando para ejecutar en sandbox con aprobación humana.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Título del comando"},
                            "description": {"type": "string", "description": "Descripción breve"},
                            "command": {"type": "string", "description": "Comando a ejecutar"}
                        },
                        "required": ["title", "command"]
                    }
                ),
                types.Tool(
                    name="list_automation_pending_tokio",
                    description="Lista propuestas pendientes de automatización.",
                    inputSchema={"type": "object", "properties": {}}
                ),
                types.Tool(
                    name="list_automation_approved_tokio",
                    description="Lista tools aprobadas disponibles para ejecución.",
                    inputSchema={"type": "object", "properties": {}}
                ),
                types.Tool(
                    name="run_approved_tool_tokio",
                    description="Ejecuta una tool aprobada por ID, tool_key o title.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "tool_id": {"type": "string", "description": "ID de la tool aprobada"},
                            "tool_key": {"type": "string", "description": "Clave normalizada de la tool"},
                            "title": {"type": "string", "description": "Título de la tool"},
                            "args": {"type": "object", "description": "Argumentos para la tool"}
                        }
                    }
                )
            ])
        
        if SPOTIFY_TOOLS_AVAILABLE and ENABLE_SPOTIFY_TOOLS:
            tools.extend([
                types.Tool(
                    name="create_spotify_playlist",
                    description="Crea una playlist en Spotify con el nombre y descripción especificados. Puede agregar tracks si se proporcionan sus URIs.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nombre de la playlist (requerido)"},
                            "description": {"type": "string", "description": "Descripción de la playlist (opcional)"},
                            "public": {"type": "boolean", "default": True, "description": "Si la playlist es pública (default: True)"},
                            "collaborative": {"type": "boolean", "default": False, "description": "Si la playlist es colaborativa (default: False)"},
                            "user_id": {"type": "string", "description": "ID del usuario de Spotify (opcional, se obtiene del token si no se proporciona)"},
                            "access_token": {"type": "string", "description": "Access token de usuario de Spotify (opcional, usa variable de entorno si no se proporciona)"},
                            "track_uris": {"type": "array", "items": {"type": "string"}, "description": "Lista de URIs de tracks para agregar (opcional, formato: spotify:track:ID)"}
                        },
                        "required": ["name"]
                    }
                ),
                types.Tool(
                    name="search_spotify_tracks",
                    description="Busca tracks en Spotify usando un término de búsqueda. Retorna URIs que pueden usarse para crear playlists.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Término de búsqueda (artista, canción, álbum, etc.)"},
                            "limit": {"type": "integer", "default": 20, "description": "Número máximo de resultados (default: 20, máximo: 50)"},
                            "access_token": {"type": "string", "description": "Access token (opcional, se renueva automáticamente)"}
                        },
                        "required": ["query"]
                    }
                ),
                types.Tool(
                    name="set_spotify_refresh_token",
                    description="Configura el refresh token de Spotify para renovación automática de tokens. Solo necesitas hacerlo una vez.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "refresh_token": {"type": "string", "description": "Refresh token obtenido del flujo OAuth2 de Spotify"}
                        },
                        "required": ["refresh_token"]
                    }
                )
            ])
        
        if VULNERABILITY_TOOLS_AVAILABLE and ENABLE_VULNERABILITY:
            tools.extend([
                types.Tool(
                    name="test_vulnerability",
                    description="Prueba si una vulnerabilidad reportada es realmente explotable. Busca información histórica en SOAR, Jira y Horus, analiza logs de FW y WAF, y realiza pruebas básicas de conectividad y explotabilidad. Proporciona un análisis de riesgo detallado y recomendaciones.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a probar"},
                            "port": {"type": "integer", "description": "Puerto a probar"},
                            "vulnerability_type": {"type": "string", "description": "Tipo de vulnerabilidad (ej: 'SMBv1', 'SSL/TLS', 'RDP', 'HTTP Basic Auth', 'IIS EOL', etc.)"},
                            "incident_id": {"type": "string", "description": "ID del incidente relacionado (opcional)"},
                            "test_type": {"type": "string", "default": "basic", "description": "Tipo de prueba: 'basic', 'advanced', o 'exploitation'"},
                            "search_logs": {"type": "boolean", "default": True, "description": "Si True, busca en logs de FW y WAF"},
                            "search_historical": {"type": "boolean", "default": True, "description": "Si True, busca información histórica en SOAR, Jira, etc."},
                            "test_vpn": {"type": "boolean", "default": True, "description": "Si True, ejecuta prueba desde VPN (puede causar timeout si el puerto 445 está bloqueado). Si False, omite la prueba VPN."},
                            "test_local": {"type": "boolean", "default": True, "description": "Si True, ejecuta prueba desde equipo local. Si False, omite la prueba local."}
                        },
                        "required": ["ip", "port", "vulnerability_type"]
                    }
                ),
                types.Tool(
                    name="test_vulnerability_with_log_monitoring",
                    description="Prueba vulnerabilidad con monitoreo de logs en tiempo real. Flujo completo: (1) Establece baseline de logs en Kafka (FW para IPs internas, WAF para IPs externas), (2) Ejecuta el test, (3) Espera X segundos para propagación, (4) Busca logs nuevos generados por el test, (5) Evalúa si el test fue detectado/bloqueado/permitido. Ideal para validar si las mitigaciones están funcionando.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a probar"},
                            "port": {"type": "integer", "description": "Puerto a probar"},
                            "vulnerability_type": {"type": "string", "description": "Tipo de vulnerabilidad (ej: 'SMBv1', 'SSL/TLS', 'RDP', 'HTTP Basic Auth')"},
                            "incident_id": {"type": "string", "description": "ID del incidente relacionado (opcional)"},
                            "test_type": {"type": "string", "default": "basic", "description": "Tipo de prueba: 'basic', 'advanced', o 'exploitation'"},
                            "wait_seconds": {"type": "integer", "default": 10, "description": "Segundos a esperar después del test para buscar logs (default: 10)"},
                            "test_vpn": {"type": "boolean", "default": True, "description": "Si True, ejecuta prueba desde VPN"},
                            "test_local": {"type": "boolean", "default": True, "description": "Si True, ejecuta prueba desde equipo local"}
                        },
                        "required": ["ip", "port", "vulnerability_type"]
                    }
                )
            ])
        
        if ATLASSIAN_TOOLS_AVAILABLE and ENABLE_ATLASSIAN:
            tools.extend([
                types.Tool(
                    name="search_ip_in_jira",
                    description="Busca una IP en los issues de Jira (summary, description, comments, etc.) usando JQL (Jira Query Language). Permite buscar en todo el historial con rangos de fecha personalizados. Útil para encontrar referencias a IPs en tickets, incidentes o documentación de Jira. El cloud_id se obtiene automáticamente si no se proporciona.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a buscar en Jira"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "cloud_id": {"type": "string", "description": "Cloud ID de Atlassian (opcional, se obtiene automáticamente)"},
                            "start_date": {"type": "string", "description": "Fecha de inicio en formato YYYY-MM-DD (opcional). Si no se proporciona, usa una fecha por defecto."},
                            "end_date": {"type": "string", "description": "Fecha de fin en formato YYYY-MM-DD (opcional). Si no se proporciona, usa la fecha actual."},
                            "search_all_history": {"type": "boolean", "default": False, "description": "Si es True, busca en todo el historial sin restricciones de fecha (último recurso)"}
                        },
                        "required": ["ip"]
                    }
                ),
                types.Tool(
                    name="search_jira_issues",
                    description="Busca issues en Jira usando JQL (Jira Query Language). Puede buscar por texto en summary, description, comments, etc. El cloud_id se obtiene automáticamente si no se proporciona.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto a buscar en Jira"},
                            "project": {"type": "string", "description": "Clave del proyecto (opcional, ej: PROJ)"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "cloud_id": {"type": "string", "description": "Cloud ID de Atlassian (opcional, se obtiene automáticamente)"}
                        },
                        "required": ["query"]
                    }
                ),
                types.Tool(
                    name="search_ip_in_confluence",
                    description="Busca una IP en todas las páginas, comentarios y contenido de Confluence usando CQL (Confluence Query Language). Útil para encontrar referencias a IPs en documentación o incidentes. El cloud_id se obtiene automáticamente si no se proporciona.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string", "description": "IP a buscar en Confluence"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "cloud_id": {"type": "string", "description": "Cloud ID de Atlassian (opcional, se obtiene automáticamente)"}
                        },
                        "required": ["ip"]
                    }
                ),
                types.Tool(
                    name="search_content_in_confluence",
                    description="Busca contenido en Confluence usando CQL (Confluence Query Language). Puede buscar por texto en páginas, blogs, comentarios, etc. El cloud_id se obtiene automáticamente si no se proporciona.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Texto a buscar en Confluence"},
                            "content_type": {"type": "string", "description": "Tipo de contenido (page, blogpost, comment, etc.) - opcional"},
                            "limit": {"type": "integer", "default": 50, "description": "Límite de resultados"},
                            "cloud_id": {"type": "string", "description": "Cloud ID de Atlassian (opcional, se obtiene automáticamente)"}
                        },
                        "required": ["query"]
                    }
                ),
                types.Tool(
                    name="get_jira_boards",
                    description="Obtiene todos los boards disponibles en Jira usando el plugin de Cloud Valley. Útil para listar los boards disponibles antes de trabajar con ellos.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "start_at": {"type": "integer", "default": 0, "description": "Índice de inicio para paginación"},
                            "limit": {"type": "integer", "default": 50, "description": "Número máximo de resultados"}
                        }
                    }
                ),
                types.Tool(
                    name="search_jira_boards",
                    description="Busca boards en Jira por nombre usando el plugin de Cloud Valley. Útil para encontrar un board específico.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nombre del board a buscar"}
                        },
                        "required": ["name"]
                    }
                ),
                types.Tool(
                    name="get_jira_issue_types",
                    description="Obtiene los tipos de issues disponibles para un proyecto en Jira usando el plugin de Cloud Valley. Necesario para crear issues.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "string", "description": "ID del proyecto"}
                        },
                        "required": ["project_id"]
                    }
                ),
                types.Tool(
                    name="get_jira_issue",
                    description="Obtiene un issue específico de Jira usando el plugin de Cloud Valley. Útil para obtener detalles completos de un issue por su ID o clave.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "issue_id_or_key": {"type": "string", "description": "ID o clave del issue (ej: ACNT-4057)"}
                        },
                        "required": ["issue_id_or_key"]
                    }
                ),
                types.Tool(
                    name="create_jira_issue",
                    description="Crea un nuevo issue en Jira usando el plugin de Cloud Valley. Permite crear issues con campos personalizados, etiquetas y subtareas.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "string", "description": "ID del proyecto"},
                            "issue_type_id": {"type": "string", "description": "ID del tipo de issue"},
                            "summary": {"type": "string", "description": "Resumen/título del issue"},
                            "description": {"type": "string", "description": "Descripción del issue (opcional)"},
                            "custom_fields": {"type": "object", "description": "Diccionario con campos personalizados (opcional)"},
                            "labels": {"type": "array", "items": {"type": "string"}, "description": "Lista de etiquetas (opcional)"},
                            "parent": {"type": "string", "description": "Clave del issue padre si es subtarea (opcional)"}
                        },
                        "required": ["project_id", "issue_type_id", "summary"]
                    }
                ),
                types.Tool(
                    name="validate_jira_issue_creation",
                    description="Valida la creación de un issue antes de crearlo realmente usando el plugin de Cloud Valley. Útil para verificar que todos los campos requeridos estén presentes.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "string", "description": "ID del proyecto"},
                            "issue_type_id": {"type": "string", "description": "ID del tipo de issue"},
                            "summary": {"type": "string", "description": "Resumen/título del issue"},
                            "description": {"type": "string", "description": "Descripción del issue (opcional)"},
                            "custom_fields": {"type": "object", "description": "Diccionario con campos personalizados (opcional)"}
                        },
                        "required": ["project_id", "issue_type_id", "summary"]
                    }
                ),
                types.Tool(
                    name="search_jira_sandbox",
                    description="Busca IPs, dominios o texto en issues de Jira Sandbox usando el plugin de Cloud Valley. Permite búsquedas exhaustivas por IP específica, dominio, texto en summary/description, o obtener un issue específico. Extrae automáticamente todas las IPs y dominios encontrados en los issues.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "search_term": {"type": "string", "description": "Texto a buscar en summary/description (opcional)"},
                            "ip": {"type": "string", "description": "IP específica a buscar (opcional, ej: YOUR_IP_ADDRESS)"},
                            "domain": {"type": "string", "description": "Dominio específico a buscar (opcional, ej: teco.com.ar)"},
                            "issue_key": {"type": "string", "description": "Clave de issue específico a obtener (opcional, ej: ACNT-4057)"},
                            "limit": {"type": "integer", "default": 50, "description": "Número máximo de issues a revisar (default: 50)"},
                            "start_from": {"type": "integer", "default": 4000, "description": "Número de issue desde donde empezar a buscar (default: 4000)"}
                        }
                    }
                )
            ])
        
        return tools
    
    @app.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
        try:
            result = None
            # SOAR Tools
            if name == "get_incident":
                result = await tool_get_incident(**arguments)
            elif name == "list_incidents":
                result = await tool_list_incidents(**arguments)
            elif name == "get_incident_comments":
                result = await tool_get_incident_comments(**arguments)
            elif name == "search_incidents":
                result = await tool_search_incidents(**arguments)
            elif name == "close_incident":
                result = await tool_close_incident(**arguments)
            elif name == "list_playbooks":
                result = await tool_list_playbooks(**arguments)
            elif name == "get_playbook":
                result = await tool_get_playbook(**arguments)
            elif name == "check_playbook_status":
                result = await tool_check_playbook_status(**arguments)
            elif name == "health_check_soar":
                result = await tool_health_check_soar(**arguments)
            elif name == "search_soar_wiki":
                result = await tool_search_soar_wiki(**arguments)
            # Kafka/DB Tools
            elif name == "search_fw_logs":
                result = await tool_search_fw_logs(**arguments)
            elif name == "search_waf_logs":
                result = await tool_search_waf_logs(**arguments)
            elif name == "check_ip_mitigation":
                result = await tool_check_ip_mitigation(**arguments)
            # Generic DB Tools
            elif name == "query_data":
                result = await tool_query_data(**arguments)
            # Tokio AI Tools
            elif name == "search_waf_logs_tokio":
                result = await tool_search_waf_logs_tokio(**arguments)
            elif name == "list_episodes_tokio":
                result = await tool_list_episodes_tokio(**arguments)
            elif name == "list_blocked_ips_tokio":
                result = await tool_list_blocked_ips_tokio(**arguments)
            elif name == "block_ip_tokio":
                result = await tool_block_ip_tokio(**arguments)
            elif name == "unblock_ip_tokio":
                result = await tool_unblock_ip_tokio(**arguments)
            elif name == "get_summary_tokio":
                result = await tool_get_summary_tokio(**arguments)
            elif name == "propose_tool_tokio":
                result = await tool_propose_tool(**arguments)
            elif name == "propose_command_tokio":
                result = await tool_propose_command(**arguments)
            elif name == "list_automation_pending_tokio":
                result = await tool_list_automation_pending()
            elif name == "list_automation_approved_tokio":
                result = await tool_list_automation_approved()
            elif name == "run_approved_tool_tokio":
                result = await tool_run_approved_tool(**arguments)
            # Spotify Tools
            elif name == "create_spotify_playlist":
                result = await tool_create_spotify_playlist(**arguments)
            elif name == "search_spotify_tracks":
                result = await tool_search_spotify_tracks(**arguments)
            elif name == "set_spotify_refresh_token":
                result = await tool_set_spotify_refresh_token(**arguments)
            # Horus API Tools (deshabilitado)
            # elif name == "get_ip_info":
            #     result = await tool_get_ip_info(**arguments)
            # Atlassian/Jira Tools
            elif name == "search_ip_in_jira":
                result = await tool_search_ip_in_jira(**arguments)
            elif name == "search_jira_issues":
                result = await tool_search_jira_issues(**arguments)
            # Vulnerability Testing Tools
            elif name == "test_vulnerability":
                result = await tool_test_vulnerability(**arguments)
            elif name == "test_vulnerability_with_log_monitoring":
                result = await tool_test_vulnerability_with_log_monitoring(**arguments)
            # Atlassian/Confluence Tools
            elif name == "search_ip_in_confluence":
                result = await tool_search_ip_in_confluence(**arguments)
            elif name == "search_content_in_confluence":
                result = await tool_search_content_in_confluence(**arguments)
            # Jira Plugin Tools (Cloud Valley)
            elif name == "get_jira_boards":
                result = await tool_get_jira_boards(**arguments)
            elif name == "search_jira_boards":
                result = await tool_search_jira_boards(**arguments)
            elif name == "get_jira_issue_types":
                result = await tool_get_jira_issue_types(**arguments)
            elif name == "get_jira_issue":
                result = await tool_get_jira_issue(**arguments)
            elif name == "create_jira_issue":
                result = await tool_create_jira_issue(**arguments)
            elif name == "validate_jira_issue_creation":
                result = await tool_validate_jira_issue_creation(**arguments)
            elif name == "search_jira_sandbox":
                result = await tool_search_jira_sandbox(**arguments)
            # Incident Cache Tools
            elif name == "sync_incidents_to_cache":
                result = await sync_incidents_from_soar_api(**arguments)
            elif name == "get_cache_stats":
                result = await get_cache_stats(**arguments)
            elif name == "cleanup_old_incidents":
                result = await cleanup_old_incidents(**arguments)
            elif name == "get_cache_metrics":
                result = await get_cache_metrics(**arguments)
            elif name == "optimize_cache_indexes":
                result = await optimize_cache_indexes(**arguments)
            # File Tools
            elif name == "write_file":
                result = await tool_write_file(**arguments)
            elif name == "read_file":
                result = await tool_read_file(**arguments)
            
            if result is None:
                result = {"success": False, "error": f"Tool '{name}' no disponible"}
            
            return [types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]
        except Exception as e:
            logger.error(f"Error en tool {name}: {e}")
            return [types.TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def main():
    if MCP_AVAILABLE and app:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
