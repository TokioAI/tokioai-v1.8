"""
Tool Executor - Unified execution for base, MCP, and generated tools
"""
import time
import logging
import json
import importlib.util
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from pathlib import Path

from .mcp_client import MCPClient

logger = logging.getLogger(__name__)

@dataclass
class ToolResult:
    """Result of tool execution"""
    tool_name: str
    success: bool
    output: str
    error: Optional[str] = None
    execution_time: float = 0.0
    args: Optional[Dict] = None

class ToolRegistry:
    """Registry of all available tools"""

    def __init__(self):
        # Tool name -> tool definition
        self.tools: Dict[str, Dict] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        category: str,
        parameters: List[str],
        executor_func
    ):
        """Register a tool"""
        self.tools[name] = {
            "name": name,
            "description": description,
            "category": category,
            "parameters": parameters,
            "executor": executor_func
        }

        logger.debug(f"Registered tool: {name}")

    def get_tool(self, name: str) -> Optional[Dict]:
        """Get tool by name"""
        return self.tools.get(name)

    def list_tools(self) -> List[Dict]:
        """List all registered tools"""
        return [
            {k: v for k, v in tool.items() if k != "executor"}
            for tool in self.tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        """Check if tool exists"""
        return name in self.tools

class ToolExecutor:
    """
    Unified tool executor for base, MCP, and generated tools.

    Tool priority:
    1. Base tools (tokio-core/tools/base/*.py)
    2. Generated tools (workspace/tools/*.py)
    3. MCP tools (via mcp_client)
    """

    def __init__(self, workspace, mcp_client: MCPClient):
        self.workspace = workspace
        self.mcp_client = mcp_client
        self.registry = ToolRegistry()

        # Load base tools
        self._load_base_tools()

        # Load generated tools from workspace
        self._load_generated_tools()

    def _load_base_tools(self):
        """Load base tools from tokio-core"""
        # Base tools from tokio-core
        # For now, register common built-in tools
        # (Can be extended to dynamically load from tokio-core/tools/)

        # Bash tool
        self.registry.register_tool(
            name="bash",
            description="Execute bash command (supports curl, wget, python, and any shell command)",
            category="System",
            parameters=["command"],
            executor_func=self._execute_bash
        )
        
        # Python tool (executes Python code)
        self.registry.register_tool(
            name="python",
            description="Execute Python code",
            category="System",
            parameters=["code"],
            executor_func=self._execute_python
        )
        
        # Curl tool (wrapper for common HTTP requests)
        self.registry.register_tool(
            name="curl",
            description="Execute curl command for HTTP requests",
            category="Network",
            parameters=["url", "method", "headers", "data"],
            executor_func=self._execute_curl
        )
        
        # Wget tool (wrapper for wget commands)
        self.registry.register_tool(
            name="wget",
            description="Execute wget command for downloading files",
            category="Network",
            parameters=["url", "output"],
            executor_func=self._execute_wget
        )

        # PostgreSQL query tool
        self.registry.register_tool(
            name="postgres_query",
            description="Execute PostgreSQL query",
            category="Database",
            parameters=["query"],
            executor_func=self._execute_postgres
        )

        # Docker tool
        self.registry.register_tool(
            name="docker",
            description="Execute docker command (ps, logs, start/stop/restart, inspect, exec, stats, run)",
            category="Container",
            parameters=["command"],
            executor_func=self._execute_docker
        )

        # Tenant Management Tools
        try:
            from .tools.tenant_tools import add_tenant, remove_tenant, list_tenants, check_tenant_health

            self.registry.register_tool(
                name="add_tenant",
                description="Add a new tenant with full nginx/WAF/SSL configuration",
                category="Tenant Management",
                parameters=["domain", "backend_url", "backend_port"],
                executor_func=add_tenant
            )

            self.registry.register_tool(
                name="remove_tenant",
                description="Remove a tenant and cleanup configuration",
                category="Tenant Management",
                parameters=["domain"],
                executor_func=remove_tenant
            )

            self.registry.register_tool(
                name="list_tenants",
                description="List all configured tenants",
                category="Tenant Management",
                parameters=[],
                executor_func=list_tenants
            )

            self.registry.register_tool(
                name="check_tenant_health",
                description="Check health status of a tenant",
                category="Tenant Management",
                parameters=["domain"],
                executor_func=check_tenant_health
            )

            logger.info("✅ Loaded tenant management tools")

        except Exception as e:
            logger.warning(f"⚠️ Could not load tenant tools: {e}")

        # Infrastructure Control Tools
        try:
            from .tools.infra_tools import (
                get_system_info, list_processes, control_service, view_logs,
                backup_database, restore_database, get_disk_usage, get_network_stats,
                cleanup_docker
            )

            tools = [
                ("get_system_info", "Get complete system information (CPU, RAM, disk)", []),
                ("list_processes", "List top processes by CPU/Memory", ["limit"]),
                ("control_service", "Control systemd service (start/stop/restart)", ["service", "action"]),
                ("view_logs", "View service logs", ["service", "lines"]),
                ("backup_database", "Backup PostgreSQL database", ["backup_path"]),
                ("restore_database", "Restore database from backup", ["backup_path"]),
                ("get_disk_usage", "Get disk usage statistics", ["path"]),
                ("get_network_stats", "Get network statistics", []),
                ("cleanup_docker", "Clean up unused Docker resources", [])
            ]

            funcs = [get_system_info, list_processes, control_service, view_logs,
                    backup_database, restore_database, get_disk_usage, get_network_stats,
                    cleanup_docker]

            for (name, desc, params), func in zip(tools, funcs):
                self.registry.register_tool(
                    name=name,
                    description=desc,
                    category="Infrastructure",
                    parameters=params,
                    executor_func=func
                )

            logger.info("✅ Loaded infrastructure tools")

        except Exception as e:
            logger.warning(f"⚠️ Could not load infra tools: {e}")

        # IoT Tools
        try:
            from .tools.iot_tools import (
                alexa_speak, alexa_play_music, alexa_weather, alexa_status, alexa_set_volume,
                alexa_volume_up, alexa_volume_down, alexa_mute,
                ha_control_switch, ha_control_light, ha_control_vacuum, ha_get_state,
                ha_sync_entities, ha_list_entities, ha_set_alias, ha_clean_unavailable_entities,
                control_smart_plug, get_plug_status,
                vacuum_control, vacuum_status, control_lights, set_scene, get_sensor_data
            )

            iot_tools = [
                ("alexa_speak", "Make Alexa speak text", ["text", "device_name"]),
                ("alexa_play_music", "Play music on Alexa", ["query", "device_name"]),
                ("alexa_weather", "Ask Alexa for weather information", ["device_name", "location"]),
                ("alexa_status", "Get Alexa device status (state, volume, media) - SILENT, no TTS", ["device_name"]),
                ("alexa_set_volume", "Set Alexa volume (0-100) - SILENT, no TTS", ["device_name", "level"]),
                ("alexa_volume_up", "Increase Alexa volume by step (default 10%) - SILENT, no TTS", ["device_name", "step"]),
                ("alexa_volume_down", "Decrease Alexa volume by step (default 10%) - SILENT, no TTS", ["device_name", "step"]),
                ("alexa_mute", "Mute/unmute Alexa - SILENT, no TTS", ["device_name", "mute"]),
                ("ha_control_switch", "Control Home Assistant switch (on/off/toggle). Entity ID: switch.xxx", ["entity_id", "state"]),
                ("ha_control_light", "Control Home Assistant light (on/off, brightness, RGB/HS). Entity ID: light.xxx", ["entity_id", "state", "brightness", "rgb_color", "color"]),
                ("ha_control_vacuum", "Control Home Assistant vacuum (start/stop/pause/return_to_base/locate/clean_spot). Entity ID: vacuum.xxx", ["entity_id", "action"]),
                ("ha_get_state", "Get state of any Home Assistant entity (switch, light, vacuum, etc.)", ["entity_id"]),
                ("ha_sync_entities", "Sync Home Assistant entities into persistent memory cache", []),
                ("ha_list_entities", "List Home Assistant entities by domain (light/switch/vacuum/etc). Automatically filters unavailable entities and obsolete Alexa devices.", ["domain"]),
                ("ha_set_alias", "Create persistent alias for a Home Assistant entity", ["alias", "entity_id"]),
                ("ha_clean_unavailable_entities", "Remove unavailable entities from cache (useful for cleaning obsolete Alexa devices)", ["domain"]),
                ("control_smart_plug", "Control smart plug (on/off)", ["device_id", "action"]),
                ("get_plug_status", "Get smart plug status", ["device_id"]),
                ("vacuum_control", "Control vacuum cleaner", ["action", "device_id"]),
                ("vacuum_status", "Get vacuum status", ["device_id"]),
                ("control_lights", "Control smart lights", ["room", "state", "brightness"]),
                ("set_scene", "Activate lighting scene", ["scene_name"]),
                ("get_sensor_data", "Get sensor data", ["sensor_id"])
            ]

            iot_funcs = [
                alexa_speak, alexa_play_music, alexa_weather, alexa_status, alexa_set_volume,
                alexa_volume_up, alexa_volume_down, alexa_mute,
                ha_control_switch, ha_control_light, ha_control_vacuum, ha_get_state,
                ha_sync_entities, ha_list_entities, ha_set_alias, ha_clean_unavailable_entities,
                control_smart_plug, get_plug_status,
                vacuum_control, vacuum_status, control_lights, set_scene, get_sensor_data
            ]

            for (name, desc, params), func in zip(iot_tools, iot_funcs):
                self.registry.register_tool(
                    name=name,
                    description=desc,
                    category="IoT",
                    parameters=params,
                    executor_func=func
                )

            logger.info("✅ Loaded IoT tools")

        except Exception as e:
            logger.warning(f"⚠️ Could not load IoT tools: {e}")

        # Router Security/Operations Tool (OpenWrt/GL.iNet universal via SSH)
        try:
            from .tools.router_tools import router_control
            self.registry.register_tool(
                name="router_control",
                description=(
                    "Universal router control over SSH (OpenWrt/GL.iNet): health, firewall status, "
                    "Wi-Fi status, attack signal detection, Wi-Fi recovery, and IP block/unblock."
                ),
                category="Network Security",
                parameters=["action", "params"],
                executor_func=router_control
            )
            logger.info("✅ Loaded router control tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load router control tool: {e}")

        # Host (Raspberry Pi) control tool over SSH: cron, scripts, systemctl, logs, packages
        try:
            from .tools.host_tools import host_control, list_web_backends
            self.registry.register_tool(
                name="host_control",
                description=(
                    "Administra el host por SSH (Raspberry Pi): health, logs, systemctl, cron, "
                    "escritura de archivos/scripts e instalación de paquetes. "
                    "Acciones peligrosas requieren params.confirm=true."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=host_control,
            )
            self.registry.register_tool(
                name="list_web_backends",
                description=(
                    "Detecta puertos/backend web activos (HTTP) en host sin depender de ss/lsof/netstat."
                ),
                category="Infrastructure",
                parameters=[],
                executor_func=list_web_backends,
            )
            logger.info("✅ Loaded host control tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load host control tool: {e}")

        # Hostinger DNS Management Tool
        try:
            from .tools.hostinger_tools import hostinger_dns, publish_site, unpublish_site, proxy_logs
            self.registry.register_tool(
                name="hostinger_dns",
                description=(
                    "Gestiona registros DNS en Hostinger: listar dominios, listar/crear/actualizar/eliminar "
                    "registros DNS (A, CNAME, TXT, etc.). Requiere HOSTINGER_API_KEY."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=hostinger_dns,
            )
            self.registry.register_tool(
                name="publish_site",
                description=(
                    "Publica un sitio web detrás del proxy WAF de TokioAI automáticamente: "
                    "crea tenant en WAF y actualiza DNS en Hostinger. Requiere HOSTINGER_API_KEY y PROXY_PUBLIC_IP."
                ),
                category="Infrastructure",
                parameters=["domain", "backend_url", "name", "proxy_ip", "use_cname"],
                executor_func=publish_site,
            )
            self.registry.register_tool(
                name="unpublish_site",
                description=(
                    "Saca un sitio del proxy sin romper la web: elimina DNS proxy, restaura snapshot DNS previo "
                    "y opcionalmente elimina tenant WAF."
                ),
                category="Infrastructure",
                parameters=["domain", "host", "keep_tenant"],
                executor_func=unpublish_site,
            )
            self.registry.register_tool(
                name="proxy_logs",
                description=(
                    "Estado unificado del sitio publicado: modo/target en estado local, DNS actual y health-check."
                ),
                category="Infrastructure",
                parameters=["domain", "host"],
                executor_func=proxy_logs,
            )
            logger.info("✅ Loaded Hostinger DNS tools")
        except Exception as e:
            logger.warning(f"⚠️ Could not load Hostinger DNS tools: {e}")

        # Task Orchestrator (autonomous playbooks)
        try:
            from .tools.task_orchestrator import task_orchestrator
            self.registry.register_tool(
                name="task_orchestrator",
                description=(
                    "Orquesta tareas autónomas con estado persistente (planned/running/verifying/done/failed), "
                    "playbooks idempotentes y notificación opcional a Telegram."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=task_orchestrator,
            )
            logger.info("✅ Loaded task orchestrator tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load task orchestrator tool: {e}")

        # Tunnel manager (cloudflared tunnel-first)
        try:
            from .tools.tunnel_tools import tunnel_manager
            self.registry.register_tool(
                name="tunnel_manager",
                description=(
                    "Gestiona túnel cloudflared en host (status/deploy/restart/logs/stop) "
                    "para publicar sin abrir puertos."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=tunnel_manager,
            )
            logger.info("✅ Loaded tunnel manager tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load tunnel manager tool: {e}")

        # Cloudflare API tool (configure tunnel routes for SSL)
        try:
            from .tools.cloudflare_api_tools import cloudflare_tool
            self.registry.register_tool(
                name="cloudflare_api",
                description=(
                    "Configura rutas públicas de túnel Cloudflare vía API para habilitar SSL "
                    "sin mover dominio a Cloudflare DNS."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=cloudflare_tool,
            )
            logger.info("✅ Loaded Cloudflare API tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load Cloudflare API tool: {e}")

        # GCP WAF Full Stack Deploy/Destroy/Query Tool (Terraform)
        try:
            from .tools.gcp_waf_tools import gcp_waf
            self.registry.register_tool(
                name="gcp_waf",
                description=(
                    "Stack auto-escalable WAF en GCP via Python SDK (no requiere terraform/gcloud). "
                    "Actions: setup (verificar prereqs), deploy (domain, backend_url, mode=auto|simple, max_replicas=3), "
                    "scale (domain, min_replicas, max_replicas, target_size), "
                    "destroy (domain), status (domain), "
                    "query (analysis: top_ips|top_attacks|episodes|summary|hourly_traffic, o SQL custom, o ip='X.X.X.X' para buscar IP específica con days=N), "
                    "block (ip, type=block|unblock, reason, duration_hours — bloqueo/desbloqueo real en proxy Nginx). "
                    "La Raspi NO descarga nada — consulta PG remota."
                ),
                category="Infrastructure",
                parameters=["action", "params"],
                executor_func=gcp_waf,
            )
            logger.info("✅ Loaded GCP WAF tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load GCP WAF tool: {e}")

        # User Preference Tools (save/recall across sessions)
        try:
            self.registry.register_tool(
                name="save_user_preference",
                description=(
                    "Guarda una preferencia PERMANENTE del usuario (nombre, apodo, idioma, "
                    "configuraciones, etc.). Sobrevive reinicios. Clave-valor."
                ),
                category="Memory",
                parameters=["key", "value"],
                executor_func=self._save_user_preference,
            )
            self.registry.register_tool(
                name="recall_preferences",
                description=(
                    "Devuelve TODAS las preferencias guardadas del usuario (nombre, apodo, "
                    "configuraciones, etc.)."
                ),
                category="Memory",
                parameters=[],
                executor_func=self._recall_preferences,
            )
            logger.info("✅ Loaded user preference tools")
        except Exception as e:
            logger.warning(f"⚠️ Could not load preference tools: {e}")

        # Calendar Tool
        try:
            from .tools.calendar_tools import calendar_tool
            self.registry.register_tool(
                name="calendar_tool",
                description=(
                    "Consulta, analiza y comparte eventos de calendario (.ics). "
                    "Actions: query (period=today|tomorrow|week|month|YYYY-MM-DD), "
                    "summary (resumen general), share (period, contact, format=text|telegram), "
                    "free_slots (horarios libres). Soporta Exchange, Google Calendar, Apple."
                ),
                category="Calendar",
                parameters=["action", "params"],
                executor_func=calendar_tool,
            )
            logger.info("✅ Loaded calendar tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load calendar tool: {e}")

        # Prompt guard audit tools
        try:
            from .tools.prompt_guard_tools import prompt_guard_audit
            self.registry.register_tool(
                name="prompt_guard_audit",
                description=(
                    "Consulta estado/auditoría del Prompt-WAF (archivo de eventos, entradas recientes)."
                ),
                category="Security",
                parameters=["action", "params"],
                executor_func=prompt_guard_audit,
            )
            logger.info("✅ Loaded prompt guard audit tool")
        except Exception as e:
            logger.warning(f"⚠️ Could not load prompt guard audit tool: {e}")

        logger.info(f"✅ Loaded {len(self.registry.tools)} base tools")

    def _load_generated_tools(self):
        """Load dynamically generated tools from workspace"""
        generated_tools = self.workspace.list_generated_tools()

        for tool_name in generated_tools:
            try:
                tool_path = self.workspace.tools_path / f"{tool_name}.py"

                # Load module dynamically
                spec = importlib.util.spec_from_file_location(tool_name, tool_path)
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Expect execute() function
                if hasattr(module, "execute"):
                    self.registry.register_tool(
                        name=tool_name,
                        description=getattr(module, "DESCRIPTION", "Generated tool"),
                        category="Generated",
                        parameters=getattr(module, "PARAMETERS", []),
                        executor_func=module.execute
                    )

                    logger.info(f"✅ Loaded generated tool: {tool_name}")

            except Exception as e:
                logger.error(f"Failed to load generated tool {tool_name}: {e}")

    async def execute(
        self,
        tool_name: str,
        args: Dict,
        timeout: int = 60
    ) -> ToolResult:
        """
        Execute a tool with given arguments.

        Priority: base tools -> generated tools -> MCP tools
        """
        start_time = time.time()

        try:
            # 1. Try base/generated tools (registry)
            if self.registry.has_tool(tool_name):
                logger.info(f"🔧 Executing tool: {tool_name}")
                result = await self._execute_local_tool(tool_name, args, timeout)

            # 2. Try MCP tools
            elif await self._is_mcp_tool(tool_name):
                logger.info(f"🔧 Executing MCP tool: {tool_name}")
                result = await self._execute_mcp_tool(tool_name, args)

            # 3. Tool not found
            else:
                error_msg = f"Tool '{tool_name}' not found in registry or MCP"
                logger.error(error_msg)
                result = ToolResult(
                    tool_name=tool_name,
                    success=False,
                    output="",
                    error=error_msg,
                    args=args
                )

            # Add execution time
            result.execution_time = time.time() - start_time

            return result

        except Exception as e:
            logger.error(f"Tool execution error [{tool_name}]: {e}")
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=str(e),
                execution_time=time.time() - start_time,
                args=args
            )

    async def _execute_local_tool(
        self,
        tool_name: str,
        args: Dict,
        timeout: int
    ) -> ToolResult:
        """Execute local (base or generated) tool"""
        tool = self.registry.get_tool(tool_name)

        if not tool:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"Tool {tool_name} not in registry",
                args=args
            )

        try:
            executor_func = tool["executor"]

            # Call executor (may be sync or async)
            import asyncio
            if asyncio.iscoroutinefunction(executor_func):
                output = await executor_func(**args)
            else:
                output = executor_func(**args)

            return ToolResult(
                tool_name=tool_name,
                success=True,
                output=str(output),
                args=args
            )

        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=str(e),
                args=args
            )

    async def _execute_mcp_tool(self, tool_name: str, args: Dict) -> ToolResult:
        """Execute MCP tool"""
        try:
            mcp_result = await self.mcp_client.call_tool(tool_name, args)

            return ToolResult(
                tool_name=tool_name,
                success=mcp_result.get("success", False),
                output=mcp_result.get("output", ""),
                error=mcp_result.get("error"),
                args=args
            )

        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"MCP execution failed: {str(e)}",
                args=args
            )

    async def _is_mcp_tool(self, tool_name: str) -> bool:
        """Check if tool exists in MCP"""
        tool = await self.mcp_client.find_tool(tool_name)
        return tool is not None

    async def list_all_tools(self) -> List[Dict]:
        """List all available tools (local + MCP)"""
        # Local tools
        local_tools = self.registry.list_tools()

        # MCP tools
        mcp_tools = []
        try:
            mcp_tools_raw = await self.mcp_client.list_tools()

            for tool in mcp_tools_raw:
                mcp_tools.append({
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "category": "MCP",
                    "parameters": list(tool.get("inputSchema", {}).get("properties", {}).keys())
                })

        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")

        return local_tools + mcp_tools

    # ========================================================================
    # Built-in Tool Implementations
    # ========================================================================

    async def _execute_bash(self, command: str) -> str:
        """Execute bash command with automatic tool installation, validation, and intelligent timeouts"""
        import subprocess
        import re

        # Validation: Check for empty or dangerous commands
        if not command or len(command.strip()) == 0:
            return "Error: Comando vacío"
        
        # Detect dangerous patterns (but allow them if explicitly needed)
        dangerous_patterns = ['rm -rf /', 'format c:', 'dd if=/dev/zero', 'mkfs']
        command_lower = command.lower()
        for pattern in dangerous_patterns:
            if pattern in command_lower and '--force' not in command_lower:
                return f"Error: Comando peligroso detectado: {pattern}. Si realmente necesitas ejecutarlo, agrega --force"

        # Intelligent timeout based on command complexity
        # Simple commands (echo, ls, cat, etc.): 10s
        # Medium commands (curl, wget, grep): 30s
        # Complex commands (compilation, large operations): 120s
        simple_commands = ['echo', 'ls', 'cat', 'pwd', 'whoami', 'date', 'uptime', 'uname']
        medium_commands = ['curl', 'wget', 'grep', 'find', 'ps', 'df', 'free', 'top']
        
        is_simple = any(cmd in command for cmd in simple_commands) and len(command.split()) < 5
        is_medium = any(cmd in command for cmd in medium_commands) or '|' in command or '>' in command
        
        if is_simple:
            timeout = 10
        elif is_medium:
            timeout = 30
        else:
            timeout = 120  # Complex operations

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            # If command failed, check if it's because a tool is missing
            if result.returncode != 0:
                # Check for common "command not found" errors
                error_msg = result.stderr.lower() if result.stderr else ""
                not_found_patterns = [
                    r"command not found",
                    r"no such file or directory",
                    r"not found",
                    r"not installed"
                ]
                
                # Try to extract the missing command name
                missing_tool = None
                for pattern in not_found_patterns:
                    if re.search(pattern, error_msg):
                        # Try to extract command name (e.g., "crontab: command not found" -> "crontab")
                        match = re.search(r"^([a-z0-9_-]+):", error_msg)
                        if match:
                            missing_tool = match.group(1)
                            break
                
                # If we found a missing tool, try to install it
                if missing_tool:
                    install_output = await self._try_install_tool(missing_tool)
                    if install_output:
                        output += f"\n\n🔧 Intentando instalar {missing_tool}...\n{install_output}\n\n"
                        # Retry the original command
                        retry_result = subprocess.run(
                            command,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=120
                        )
                        if retry_result.returncode == 0:
                            output += f"✅ {missing_tool} instalado correctamente. Comando ejecutado:\n{retry_result.stdout}"
                            if retry_result.stderr:
                                output += f"\nSTDERR:\n{retry_result.stderr}"
                            return output
                        else:
                            output += f"\n⚠️ Instalación completada, pero el comando aún falla:\n{retry_result.stderr}"
                
                output += f"\nReturn code: {result.returncode}"

            return output

        except subprocess.TimeoutExpired:
            return f"Error: Comando excedió el tiempo límite de {timeout} segundos. Intenta con un comando más simple o divide la tarea en pasos más pequeños."
        except Exception as e:
            return f"Error ejecutando bash: {str(e)}"
    
    async def _try_install_tool(self, tool_name: str) -> str:
        """Try to install a missing tool automatically"""
        import subprocess
        
        # Map common tool names to package names
        tool_packages = {
            "crontab": "cron",
            "cron": "cron",
            "curl": "curl",
            "wget": "wget",
            "ssh": "openssh-client",
            "python": "python3",
            "python3": "python3",
            "pip": "python3-pip",
            "git": "git",
            "docker": "docker.io",
            "docker-compose": "docker-compose",
            "jq": "jq",
            "vim": "vim",
            "nano": "nano",
            "htop": "htop",
            "netstat": "net-tools",
            "ifconfig": "net-tools",
            "nmap": "nmap",
            "tcpdump": "tcpdump",
            "wireshark": "wireshark",
            "ffmpeg": "ffmpeg",
            "ffprobe": "ffmpeg"
        }
        
        package_name = tool_packages.get(tool_name.lower(), tool_name)
        
        try:
            # Try apt-get install (Debian/Ubuntu)
            result = subprocess.run(
                f"apt-get update && apt-get install -y {package_name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                return f"✅ Instalado {package_name} usando apt-get"
            else:
                # Try alternative package managers
                # Try yum (RHEL/CentOS)
                result = subprocess.run(
                    f"yum install -y {package_name}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    return f"✅ Instalado {package_name} usando yum"
                
                # Try pip for Python packages
                if tool_name.startswith("python") or "pip" in tool_name:
                    result = subprocess.run(
                        f"pip3 install {package_name}",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode == 0:
                        return f"✅ Instalado {package_name} usando pip3"
                
                return f"⚠️ No se pudo instalar {package_name} automáticamente. Error: {result.stderr}"
                
        except Exception as e:
            return f"⚠️ Error al intentar instalar {package_name}: {str(e)}"
    
    async def _execute_python(self, code: str) -> str:
        """Execute Python code"""
        import subprocess
        import tempfile
        import os
        
        try:
            # Create temporary Python file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                tmp_file = f.name
            
            # Execute Python file
            result = subprocess.run(
                ['python3', tmp_file],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Cleanup
            os.unlink(tmp_file)
            
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            
            if result.returncode != 0:
                return f"Python execution failed with code {result.returncode}\n{output}"
            
            return output or "Python code executed successfully (no output)"
            
        except subprocess.TimeoutExpired:
            return "Error: Python execution timed out after 120 seconds"
        except Exception as e:
            return f"Error executing Python: {str(e)}"
    
    async def _execute_curl(self, url: str, method: str = "GET", headers: Optional[Dict] = None, data: Optional[str] = None) -> str:
        """Execute curl command"""
        import subprocess
        from typing import Dict, Optional
        
        try:
            cmd = ['curl', '-s', '-X', method.upper()]
            
            # Add headers
            if headers:
                for key, value in headers.items():
                    cmd.extend(['-H', f'{key}: {value}'])
            
            # Add data
            if data:
                cmd.extend(['-d', data])
            
            cmd.append(url)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            
            if result.returncode != 0:
                return f"Curl failed with code {result.returncode}\n{output}"
            
            return output or "Curl executed successfully (no output)"
            
        except subprocess.TimeoutExpired:
            return "Error: Curl request timed out after 60 seconds"
        except Exception as e:
            return f"Error executing curl: {str(e)}"
    
    async def _execute_wget(self, url: str, output: Optional[str] = None) -> str:
        """Execute wget command"""
        import subprocess
        from typing import Optional
        
        try:
            cmd = ['wget', '-q', '--spider'] if not output else ['wget', '-q', '-O', output]
            cmd.append(url)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output_text = result.stdout
            if result.stderr:
                output_text += f"\n[stderr]\n{result.stderr}"
            
            if result.returncode != 0:
                return f"Wget failed with code {result.returncode}\n{output_text}"
            
            if output:
                return f"File downloaded to {output}\n{output_text}"
            else:
                return output_text or "Wget executed successfully"
            
        except subprocess.TimeoutExpired:
            return "Error: Wget request timed out after 60 seconds"
        except Exception as e:
            return f"Error executing wget: {str(e)}"

    async def _execute_postgres(self, query: str) -> str:
        """Execute PostgreSQL query"""
        import psycopg2

        try:
            # Get connection params from environment
            import os
            conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "tokio_db"),
                user=os.getenv("POSTGRES_USER", "tokio"),
                password=os.getenv("POSTGRES_PASSWORD", "tokio123")
            )

            cursor = conn.cursor()
            cursor.execute(query)

            # Fetch results if SELECT
            if query.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                # Format as table
                result = f"Columns: {', '.join(columns)}\n\n"
                for row in rows:
                    result += " | ".join(str(v) for v in row) + "\n"

                return result or "No rows returned"

            else:
                # For INSERT/UPDATE/DELETE
                conn.commit()
                return f"Query executed successfully. Rows affected: {cursor.rowcount}"

        except Exception as e:
            return f"PostgreSQL error: {str(e)}"

        finally:
            if 'conn' in locals():
                conn.close()

    async def _execute_docker(self, command: str) -> str:
        """Execute docker command"""
        import docker
        import shlex

        try:
            client = docker.from_env()

            # Parse command
            parts = shlex.split(command or "")
            action = parts[0] if parts else ""

            if action == "ps":
                # List containers
                containers = client.containers.list(all=True)
                result = "CONTAINER ID | NAME | STATUS | IMAGE\n"
                result += "-" * 60 + "\n"

                for c in containers:
                    result += f"{c.short_id} | {c.name} | {c.status} | {c.image.tags[0] if c.image.tags else 'none'}\n"

                return result

            elif action == "logs":
                # Get container logs
                if len(parts) < 2:
                    return "Error: Container name required"

                container_name = parts[1]
                container = client.containers.get(container_name)
                logs = container.logs(tail=50).decode('utf-8')

                return f"Logs for {container_name}:\n{logs}"

            elif action in {"stop", "start", "restart"}:
                if len(parts) < 2:
                    return f"Error: Container name required for docker {action}"
                container_name = parts[1]
                container = client.containers.get(container_name)
                if action == "stop":
                    container.stop(timeout=15)
                elif action == "start":
                    container.start()
                else:
                    container.restart(timeout=15)
                container.reload()
                return f"Container {container_name} {action} executed. Current status: {container.status}"

            elif action == "inspect":
                if len(parts) < 2:
                    return "Error: Container name required"
                container_name = parts[1]
                container = client.containers.get(container_name)
                container.reload()
                info = {
                    "name": container.name,
                    "id": container.short_id,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "none",
                    "ports": container.attrs.get("NetworkSettings", {}).get("Ports", {}),
                    "started_at": container.attrs.get("State", {}).get("StartedAt"),
                }
                return json.dumps(info, ensure_ascii=False, indent=2)

            elif action == "exec":
                if len(parts) < 3:
                    return "Error: Usage docker exec <container> <command>"
                container_name = parts[1]
                cmd_to_run = " ".join(parts[2:])
                container = client.containers.get(container_name)
                exec_result = container.exec_run(cmd_to_run)
                output = exec_result.output.decode("utf-8", errors="replace") if exec_result.output else ""
                return (
                    f"Exec in {container_name}\n"
                    f"Exit code: {exec_result.exit_code}\n\n"
                    f"{output}"
                )

            elif action == "run":
                # Minimal safe wrapper for:
                # docker run [flags] <image> [--cmd "..."]
                # Supports flags before/after image.
                if len(parts) < 2:
                    return (
                        "Error: Usage docker run <image> [--name <name>] "
                        "[-p host:container] [-d] [--cmd \"...\"]"
                    )

                image = None
                name = None
                ports = {}
                detach = True
                run_cmd = None

                i = 1
                while i < len(parts):
                    p = parts[i]
                    # First non-flag token is the image
                    if image is None and not p.startswith("-"):
                        image = p
                        i += 1
                        continue
                    if p in {"--name", "-n"} and i + 1 < len(parts):
                        name = parts[i + 1]
                        i += 2
                        continue
                    if p in {"-p", "--publish"} and i + 1 < len(parts):
                        mapping = parts[i + 1]
                        if ":" in mapping:
                            host_p, cont_p = mapping.split(":", 1)
                            host_p = host_p.strip()
                            cont_p = cont_p.strip()
                            if host_p and cont_p:
                                ports[f"{cont_p}/tcp"] = int(host_p)
                        i += 2
                        continue
                    if p in {"-d", "--detach"}:
                        detach = True
                        i += 1
                        continue
                    if p == "--no-detach":
                        detach = False
                        i += 1
                        continue
                    if p == "--cmd" and i + 1 < len(parts):
                        run_cmd = parts[i + 1]
                        i += 2
                        continue
                    # Ignore unknown flags for compatibility with LLM-generated commands
                    i += 1

                if not image:
                    return "Error: Docker image required for run (ej: nginx:alpine)"

                kwargs = {
                    "image": image,
                    "detach": detach,
                    "remove": False,
                }
                if name:
                    kwargs["name"] = name
                if ports:
                    kwargs["ports"] = ports
                if run_cmd:
                    kwargs["command"] = run_cmd

                container = client.containers.run(**kwargs)
                container.reload()
                info = {
                    "name": container.name,
                    "id": container.short_id,
                    "status": container.status,
                    "image": image,
                    "ports": container.attrs.get("NetworkSettings", {}).get("Ports", {}),
                }
                return json.dumps(info, ensure_ascii=False, indent=2)

            elif action == "stats":
                # Get container stats
                if len(parts) < 2:
                    return "Error: Container name required"

                container_name = parts[1]
                container = client.containers.get(container_name)
                stats = container.stats(stream=False)

                # Extract key metrics
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']
                cpu_percent = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0.0

                mem_usage = stats['memory_stats']['usage'] / (1024 * 1024)  # MB
                mem_limit = stats['memory_stats']['limit'] / (1024 * 1024)  # MB

                return f"Stats for {container_name}:\nCPU: {cpu_percent:.2f}%\nMemory: {mem_usage:.2f}MB / {mem_limit:.2f}MB"

            else:
                return f"Unsupported docker command: {action}"

        except Exception as e:
            return f"Docker error: {str(e)}"

    # ========================================================================
    # User Preference Tool Implementations
    # ========================================================================

    async def _save_user_preference(self, key: str, value: str) -> str:
        """Save a permanent user preference."""
        if not key or not value:
            return json.dumps({"ok": False, "error": "key y value son requeridos"})
        try:
            ok = self.workspace.save_preference(key.strip(), value.strip())
            return json.dumps({
                "ok": ok,
                "key": key.strip().lower(),
                "value": value.strip(),
                "message": f"Preferencia '{key}' guardada permanentemente." if ok else "No se pudo guardar.",
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    async def _recall_preferences(self) -> str:
        """Recall all saved user preferences."""
        try:
            prefs = self.workspace.get_all_preferences()
            return json.dumps({
                "ok": True,
                "preferences": prefs,
                "count": len(prefs),
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
