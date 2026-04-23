"""
Built-in tool loader — Registers ALL core tools into the registry.

This includes system, network, docker, database, GCP, host, IoT,
calendar, router, cloudflare, hostinger, tunnel, infra,
task orchestrator, tenant, user preferences, and prompt guard tools.
"""
from __future__ import annotations

import logging
from ..registry import ToolRegistry

logger = logging.getLogger(__name__)


def load_builtin_tools(registry: ToolRegistry) -> int:
    """Register all built-in tools into the given registry.

    Returns:
        Number of tools registered.
    """
    count = 0

    # ── System tools ──────────────────────────────────────────────────────
    from .system_tools import bash, python_exec
    from .file_tools import (
        read_file, write_file, edit_file,
        search_code, find_files, list_files,
    )

    registry.register(
        name="bash",
        description="Ejecuta un comando bash (soporta curl, wget, git, ssh, etc.)",
        category="Sistema",
        parameters={"command": "Comando shell a ejecutar"},
        executor=bash,
        examples=[
            'TOOL:bash({"command": "ls -la /etc/"})',
            'TOOL:bash({"command": "ps aux | grep nginx"})',
        ],
    )
    count += 1

    registry.register(
        name="python",
        description="Ejecuta código Python en un archivo temporal",
        category="Sistema",
        parameters={"code": "Código Python a ejecutar"},
        executor=python_exec,
        examples=['TOOL:python({"code": "import os; print(os.getcwd())"})'],
    )
    count += 1

    registry.register(
        name="read_file",
        description=(
            "Lee un archivo con numeros de linea (cat -n). "
            "Soporta offset/limit para archivos grandes. "
            "Si path es un directorio, lista su contenido."
        ),
        category="Archivos",
        parameters={
            "path": "Ruta al archivo o directorio",
            "offset": "(Opcional) Linea desde la que empezar a leer (1-based)",
            "limit": "(Opcional) Maximo de lineas a leer (default: 2000)",
        },
        executor=read_file,
        examples=[
            'TOOL:read_file({"path": "/etc/hostname"})',
            'TOOL:read_file({"path": "src/main.py", "offset": 50, "limit": 30})',
        ],
    )
    count += 1

    registry.register(
        name="write_file",
        description="Escribe contenido CORTO a un archivo (<50 lineas). Crea directorios si no existen. "
                    "Para archivos grandes usa bash con cat heredoc: cat > file << 'EOF'",
        category="Archivos",
        parameters={
            "path": "Ruta al archivo",
            "content": "Contenido a escribir (MAX 50 lineas, para mas usa bash+heredoc)",
        },
        executor=write_file,
        examples=['TOOL:write_file({"path": "/tmp/test.txt", "content": "hola"})'],
    )
    count += 1

    registry.register(
        name="edit_file",
        description=(
            "Edita un archivo reemplazando un string exacto por otro. "
            "old_string debe ser unico en el archivo (o usar replace_all=true). "
            "Preferir sobre write_file para modificaciones parciales."
        ),
        category="Archivos",
        parameters={
            "path": "Ruta al archivo a editar",
            "old_string": "Texto exacto a reemplazar (debe ser unico)",
            "new_string": "Texto de reemplazo",
            "replace_all": "(Opcional) true para reemplazar TODAS las ocurrencias",
        },
        executor=edit_file,
        examples=[
            'TOOL:edit_file({"path": "src/main.py", "old_string": "def old_function():", "new_string": "def new_function():"})',
            'TOOL:edit_file({"path": "config.py", "old_string": "DEBUG = True", "new_string": "DEBUG = False"})',
        ],
    )
    count += 1

    registry.register(
        name="search_code",
        description=(
            "Busca un patron regex en archivos (como grep/ripgrep). "
            "Retorna coincidencias con path, linea y contexto."
        ),
        category="Archivos",
        parameters={
            "pattern": "Patron regex a buscar",
            "path": "(Opcional) Directorio donde buscar (default: directorio actual)",
            "include": "(Opcional) Filtro glob de archivos (ej: '*.py')",
            "context_lines": "(Opcional) Lineas de contexto alrededor de cada match",
            "max_results": "(Opcional) Maximo de resultados (default: 100)",
        },
        executor=search_code,
        examples=[
            'TOOL:search_code({"pattern": "def process_message", "include": "*.py"})',
            'TOOL:search_code({"pattern": "import asyncio", "path": "tokio_agent/", "include": "*.py"})',
        ],
    )
    count += 1

    registry.register(
        name="find_files",
        description=(
            "Busca archivos por patron glob (como find). "
            "Retorna paths ordenados por fecha de modificacion."
        ),
        category="Archivos",
        parameters={
            "pattern": "Patron glob (ej: '**/*.py', 'src/**/*.ts')",
            "path": "(Opcional) Directorio base (default: directorio actual)",
            "max_results": "(Opcional) Maximo de resultados (default: 200)",
        },
        executor=find_files,
        examples=[
            'TOOL:find_files({"pattern": "**/*.py"})',
            'TOOL:find_files({"pattern": "*.yml", "path": "/opt/tokioai-v2/"})',
        ],
    )
    count += 1

    registry.register(
        name="list_files",
        description="Lista archivos y directorios con metadata (fecha, tamaño).",
        category="Archivos",
        parameters={
            "path": "(Opcional) Directorio a listar (default: directorio actual)",
            "show_hidden": "(Opcional) Incluir archivos ocultos (default: false)",
        },
        executor=list_files,
        examples=[
            'TOOL:list_files({"path": "/opt/tokioai-v2/"})',
            'TOOL:list_files({"path": ".", "show_hidden": true})',
        ],
    )
    count += 1

    # ── Network tools ─────────────────────────────────────────────────────
    from .network_tools import curl, wget

    registry.register(
        name="curl",
        description="Ejecuta petición HTTP (GET, POST, PUT, DELETE)",
        category="Red",
        parameters={
            "url": "URL destino",
            "method": "(Opcional) Método HTTP, default GET",
            "headers": "(Opcional) Dict de headers",
            "data": "(Opcional) Cuerpo de la petición",
        },
        executor=curl,
        examples=['TOOL:curl({"url": "https://api.example.com/data"})'],
    )
    count += 1

    registry.register(
        name="wget",
        description="Descarga un archivo desde una URL",
        category="Red",
        parameters={
            "url": "URL a descargar",
            "output_path": "(Opcional) Ruta local para guardar",
        },
        executor=wget,
    )
    count += 1

    # ── Docker tools ──────────────────────────────────────────────────────
    try:
        from .docker_tools import docker_cmd

        registry.register(
            name="docker",
            description="Gestiona contenedores Docker (ps, logs, start, stop, restart, inspect, exec, stats, images)",
            category="Contenedores",
            parameters={"command": "Sub-comando docker (ej: 'ps', 'logs mi-container')"},
            executor=docker_cmd,
            examples=[
                'TOOL:docker({"command": "ps"})',
                'TOOL:docker({"command": "logs tokio-ai-modsecurity"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Docker tools no disponibles: {e}")

    # ── Database tools ────────────────────────────────────────────────────
    try:
        from .db_tools import postgres_query

        registry.register(
            name="postgres_query",
            description="Ejecuta una consulta SQL en PostgreSQL",
            category="Base de Datos",
            parameters={
                "query": "Consulta SQL",
                "database": "(Opcional) Nombre de la base de datos",
            },
            executor=postgres_query,
            examples=[
                'TOOL:postgres_query({"query": "SELECT COUNT(*) FROM blocked_ips"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ PostgreSQL tools no disponibles: {e}")

    # ── GCP tools ─────────────────────────────────────────────────────────
    try:
        from .gcp_tools import gcp_waf, gcp_compute, gcp_waf_deploy, gcp_waf_destroy

        registry.register(
            name="gcp_waf",
            description="Gestiona el WAF en GCP (ModSecurity + Nginx): status, blocked_ips, block_ip, unblock_ip, rules, logs, reload, health",
            category="GCP",
            parameters={
                "action": "Acción: status, blocked_ips, block_ip, unblock_ip, rules, logs, reload, audit_log, health",
                "params": "(Opcional) Parámetros adicionales (ip, lines, etc.)",
            },
            executor=gcp_waf,
            examples=[
                'TOOL:gcp_waf({"action": "status"})',
                'TOOL:gcp_waf({"action": "block_ip", "params": {"ip": "1.2.3.4"}})',
            ],
        )
        count += 1

        registry.register(
            name="gcp_compute",
            description="Gestiona instancias GCP Compute: list, status, start, stop, ssh, describe, firewall_list, firewall_add",
            category="GCP",
            parameters={
                "action": "Acción: list, status, start, stop, ssh, describe, firewall_list, firewall_add",
                "params": "(Opcional) Parámetros (instance, command, name, allow, etc.)",
            },
            executor=gcp_compute,
            examples=[
                'TOOL:gcp_compute({"action": "list"})',
                'TOOL:gcp_compute({"action": "ssh", "params": {"command": "docker ps"}})',
            ],
        )
        count += 1

        registry.register(
            name="gcp_waf_deploy",
            description="Despliega infraestructura WAF completa en GCP (VM, firewall, Docker, Nginx, Kafka, Postgres)",
            category="GCP",
            parameters={
                "params": "domain, backend, instance_name, machine_type, zone, disk_size, postgres_password",
            },
            executor=gcp_waf_deploy,
            examples=[
                'TOOL:gcp_waf_deploy({"params": {"domain": "example.com", "backend": "http://origin:8080"}})',
            ],
        )
        count += 1

        registry.register(
            name="gcp_waf_destroy",
            description="Destruye infraestructura WAF en GCP (IRREVERSIBLE, requiere confirm=true)",
            category="GCP",
            parameters={
                "params": "instance_name, zone, confirm=true",
            },
            executor=gcp_waf_destroy,
            examples=[
                'TOOL:gcp_waf_destroy({"params": {"instance_name": "tokio-waf-example", "confirm": true}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ GCP tools no disponibles: {e}")

    # ── Host tools ────────────────────────────────────────────────────────
    try:
        from .host_tools import host_control

        registry.register(
            name="host_control",
            description=(
                "Control remoto de host vía SSH: status, run, reboot, services, update, "
                "cron_list, cron_add, cron_remove, write_file, read_file, journalctl, "
                "systemctl, install_packages, list_web_backends, get_public_ip, "
                "setup_log_retention, network_info, disk_info"
            ),
            category="Host",
            parameters={
                "action": "Acción a ejecutar",
                "params": "(Opcional) Parámetros adicionales",
            },
            executor=host_control,
            examples=[
                'TOOL:host_control({"action": "status"})',
                'TOOL:host_control({"action": "run", "params": {"command": "uname -a"}})',
                'TOOL:host_control({"action": "cron_add", "params": {"schedule": "*/5 * * * *", "command": "/usr/local/bin/check.sh", "comment": "health_check"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Host tools no disponibles: {e}")

    # ── IoT tools ─────────────────────────────────────────────────────────
    try:
        from .iot_tools import iot_control

        registry.register(
            name="iot_control",
            description=(
                "Control IoT vía Home Assistant: alexa_speak, alexa_play_music, alexa_status, "
                "alexa_set_volume, light_control, switch_control, vacuum_control, get_state, "
                "sync_entities, list_entities, set_alias"
            ),
            category="IoT",
            parameters={
                "action": "Acción IoT",
                "params": "Parámetros específicos de la acción",
            },
            executor=iot_control,
            examples=[
                'TOOL:iot_control({"action": "alexa_speak", "params": {"text": "Hola mundo"}})',
                'TOOL:iot_control({"action": "light_control", "params": {"entity_id": "salon", "state": "on", "color": "azul"}})',
                'TOOL:iot_control({"action": "vacuum_control", "params": {"entity_id": "robot_vacuum", "vacuum_action": "start"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ IoT tools no disponibles: {e}")

    # ── Calendar tools ────────────────────────────────────────────────────
    try:
        from .calendar_tools import calendar_tool

        registry.register(
            name="calendar",
            description="Gestión de calendario ICS: query (hoy/semana/mes), summary, free_slots",
            category="Productividad",
            parameters={
                "action": "query, summary, free_slots",
                "params": "period (today/week/month/YYYY-MM-DD), file (ruta .ics)",
            },
            executor=calendar_tool,
            examples=[
                'TOOL:calendar({"action": "query", "params": {"period": "week"}})',
                'TOOL:calendar({"action": "free_slots", "params": {"period": "tomorrow"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Calendar tools no disponibles: {e}")

    # ── Router tools ──────────────────────────────────────────────────────
    try:
        from .router_tools import router_control

        registry.register(
            name="router_control",
            description=(
                "Control de router OpenWrt/GL.iNet vía SSH: health, firewall_status, "
                "wifi_status, detect_attack_signals, wifi_defense_status, "
                "wifi_defense_harden, recover_wifi, add_block_ip, remove_block_ip, run"
            ),
            category="Red",
            parameters={
                "action": "Acción del router",
                "params": "Parámetros (ip, command, confirm, etc.)",
            },
            executor=router_control,
            examples=[
                'TOOL:router_control({"action": "health"})',
                'TOOL:router_control({"action": "wifi_defense_status"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Router tools no disponibles: {e}")

    # ── Cloudflare tools ──────────────────────────────────────────────────
    try:
        from .cloudflare_tools import cloudflare_tool

        registry.register(
            name="cloudflare",
            description="Cloudflare API: configure_tunnel_route, remove_tunnel_route",
            category="Red",
            parameters={
                "action": "configure_tunnel_route o remove_tunnel_route",
                "params": "tunnel_id, account_id, hostname, service, api_token",
            },
            executor=cloudflare_tool,
            examples=[
                'TOOL:cloudflare({"action": "configure_tunnel_route", "params": {"hostname": "app.example.com", "service": "http://localhost:8080"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Cloudflare tools no disponibles: {e}")

    # ── Hostinger tools ───────────────────────────────────────────────────
    try:
        from .hostinger_tools import hostinger_tool

        registry.register(
            name="hostinger",
            description="Hostinger DNS: list_dns, add_dns, update_dns, delete_dns, publish_site, unpublish_site, setup_waf_dns",
            category="DNS",
            parameters={
                "action": "Acción DNS",
                "params": "domain, type, name, value, record_id, ip, waf_ip",
            },
            executor=hostinger_tool,
            examples=[
                'TOOL:hostinger({"action": "list_dns", "params": {"domain": "example.com"}})',
                'TOOL:hostinger({"action": "setup_waf_dns", "params": {"domain": "example.com", "waf_ip": "1.2.3.4"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Hostinger tools no disponibles: {e}")

    # ── Tunnel tools ──────────────────────────────────────────────────────
    try:
        from .tunnel_tools import tunnel_tool

        registry.register(
            name="tunnel",
            description="Cloudflared tunnel lifecycle: status, start, stop, restart, logs, deploy, info",
            category="Red",
            parameters={
                "action": "Acción del tunnel",
                "params": "tunnel_token, lines",
            },
            executor=tunnel_tool,
            examples=[
                'TOOL:tunnel({"action": "status"})',
                'TOOL:tunnel({"action": "deploy"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Tunnel tools no disponibles: {e}")

    # ── Infra tools ───────────────────────────────────────────────────────
    try:
        from .infra_tools import infra_tool

        registry.register(
            name="infra",
            description=(
                "Infraestructura local: system_info, processes, services, logs, network, "
                "disk_usage, backup_db, restore_db, check_ports, monitor"
            ),
            category="Infraestructura",
            parameters={
                "action": "Acción de infraestructura",
                "params": "service, lines, path, count, sort, host, database, etc.",
            },
            executor=infra_tool,
            examples=[
                'TOOL:infra({"action": "monitor"})',
                'TOOL:infra({"action": "backup_db", "params": {"output": "/workspace/backup.sql"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Infra tools no disponibles: {e}")

    # ── Task Orchestrator ─────────────────────────────────────────────────
    try:
        from .task_orchestrator import task_orchestrator

        registry.register(
            name="task_orchestrator",
            description=(
                "Orquestador de tareas autónomas: cron_list, cron_add, cron_remove, "
                "run_once, install_package, create_script, run_playbook, schedule_task"
            ),
            category="Automatización",
            parameters={
                "action": "Acción del orquestador",
                "params": "schedule, command, comment, package, path, content, steps[], name, method",
            },
            executor=task_orchestrator,
            examples=[
                'TOOL:task_orchestrator({"action": "cron_add", "params": {"schedule": "0 */6 * * *", "command": "/opt/check.sh", "comment": "health_6h"}})',
                'TOOL:task_orchestrator({"action": "run_playbook", "params": {"steps": [{"command": "echo hello", "description": "test"}]}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Task orchestrator no disponible: {e}")

    # ── Tenant tools ──────────────────────────────────────────────────────
    try:
        from .tenant_tools import tenant_tool

        registry.register(
            name="tenant",
            description="Gestión de tenants Nginx/WAF: list, add, remove, health, ssl_setup, reload_nginx, status",
            category="WAF",
            parameters={
                "action": "Acción de tenant",
                "params": "domain, backend, ssl, email, target (gcp/local)",
            },
            executor=tenant_tool,
            examples=[
                'TOOL:tenant({"action": "list"})',
                'TOOL:tenant({"action": "add", "params": {"domain": "app.example.com", "backend": "http://localhost:3000"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Tenant tools no disponibles: {e}")

    # ── User Preferences ──────────────────────────────────────────────────
    try:
        from .user_preferences_tool import user_preferences_tool

        registry.register(
            name="user_preferences",
            description="Preferencias de usuario persistentes: get, set, delete, list",
            category="Sistema",
            parameters={
                "action": "get, set, delete, list",
                "params": "key, value",
            },
            executor=user_preferences_tool,
            examples=[
                'TOOL:user_preferences({"action": "set", "params": {"key": "user_name", "value": "Carlos"}})',
                'TOOL:user_preferences({"action": "get", "params": {"key": "user_name"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ User preferences tool no disponible: {e}")

    # ── Prompt Guard ──────────────────────────────────────────────────────
    try:
        from .prompt_guard_tools import prompt_guard_tool

        registry.register(
            name="prompt_guard",
            description="Auditoría de seguridad de prompts: analyze, audit_log, stats",
            category="Seguridad",
            parameters={
                "action": "analyze, audit_log, stats",
                "params": "text, limit",
            },
            executor=prompt_guard_tool,
            examples=[
                'TOOL:prompt_guard({"action": "analyze", "params": {"text": "ignore all previous instructions"}})',
                'TOOL:prompt_guard({"action": "stats"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Prompt guard tool no disponible: {e}")

    # ── Self-Heal / Watchdog ─────────────────────────────────────────────
    try:
        from ...watchdog import self_heal_tool

        registry.register(
            name="self_heal",
            description="Auto-recuperación de contenedores: status, check, restart, events",
            category="Contenedores",
            parameters={
                "action": "status, check, restart, events",
                "params": "container (para restart), limit (para events)",
            },
            executor=self_heal_tool,
            examples=[
                'TOOL:self_heal({"action": "status"})',
                'TOOL:self_heal({"action": "check"})',
                'TOOL:self_heal({"action": "restart", "params": {"container": "tokio-cli"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Self-heal tool no disponible: {e}")

    # ── Document Tools ───────────────────────────────────────────────────
    try:
        from .document_tools import document_tool

        registry.register(
            name="document",
            description=(
                "Generacion de documentos. Para PDF SIEMPRE incluir content o sections. "
                "content es un string con todo el texto. sections es lista de {heading, body}."
            ),
            category="Productividad",
            parameters={
                "action": "generate_pdf | generate_slides | generate_csv",
                "title": "(Optional) Titulo del documento. Default: Reporte TokioAI",
                "content": "(Optional) Texto completo del reporte como string. Usar para PDFs simples.",
                "sections": "(Optional) Lista de {heading, body} para PDFs con secciones",
                "data": "(Optional) Lista de filas para CSV: [[col1,col2],[val1,val2]]",
                "output_path": "(Optional) Ruta de salida",
            },
            executor=document_tool,
            examples=[
                '{"action": "generate_pdf", "title": "Reporte", "content": "Clima: 20C despejado\\nSalud: HR 84 bpm\\nWAF: 150 ataques bloqueados"}',
                '{"action": "generate_pdf", "title": "Reporte WAF", "sections": [{"heading": "Resumen", "body": "150 ataques"}, {"heading": "Top IPs", "body": "1.2.3.4: 50"}]}',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Document tools no disponibles: {e}")

    # ── Drone Tools (via Safety Proxy on Raspi) ──────────────────────────
    try:
        from .drone_secure_tools import drone_secure

        registry.register(
            name="drone",
            description=(
                "Control SEGURO de drone DJI Tello via Safety Proxy en Raspberry Pi. "
                "IMPORTANTE: Antes de volar ejecutar wifi_connect para conectar al drone. "
                "Acciones basicas: wifi_connect, wifi_disconnect, wifi_status, "
                "connect, takeoff/despegar, land/aterrizar, move/mover, rotate/rotar, "
                "patrol/patrullar, snapshot/selfie/foto, stream_on, stream_off, "
                "battery/bateria, telemetry/telemetria, status/estado, "
                "kill (emergency stop), kill_reset, audit, geofence. "
                "VISION (visual servoing desde camara de Tokio): "
                "vision_register, vision_status, come_to_me, hover, dance, patrol, vision_idle. "
                "FPV (ojo volador — drone sigue personas con su propia camara 720p): "
                "fpv_start/ojo_volador (activa FPV + follow), fpv_stop (desactiva), "
                "fpv_status/fpv (estado del FPV: personas, target, obstaculos), "
                "fpv_mode (follow/explore/hover/idle), fpv_snapshot/fpv_foto (foto desde drone). "
                "FPV se activa automaticamente al despegar. El drone sigue personas, "
                "evita obstaculos, y Tokio narra lo que ve su ojo volador."
            ),
            category="IoT",
            parameters={
                "action": "Accion: wifi_connect, connect, takeoff, land, move, rotate, patrol, snapshot, kill, audit, geofence, vision_register, vision_status, come_to_me, hover, dance, vision_idle, fpv_start, fpv_stop, fpv_status, fpv_mode, fpv_snapshot, etc",
                "params": "direction, distance, degrees, pattern, size, duration, speed, mode (para vision_mode/fpv_mode)",
            },
            executor=drone_secure,
            examples=[
                'TOOL:drone({"action": "wifi_connect"})',
                'TOOL:drone({"action": "status"})',
                'TOOL:drone({"action": "connect"})',
                'TOOL:drone({"action": "takeoff"})',
                'TOOL:drone({"action": "move", "params": {"direction": "forward", "distance": 100}})',
                'TOOL:drone({"action": "patrol", "params": {"pattern": "square", "size": 150, "duration": 3}})',
                'TOOL:drone({"action": "snapshot"})',
                'TOOL:drone({"action": "land"})',
                'TOOL:drone({"action": "kill"})',
                'TOOL:drone({"action": "wifi_disconnect"})',
                'TOOL:drone({"action": "vision_register"})',
                'TOOL:drone({"action": "vision_status"})',
                'TOOL:drone({"action": "come_to_me"})',
                'TOOL:drone({"action": "hover"})',
                'TOOL:drone({"action": "dance"})',
                'TOOL:drone({"action": "fpv_start"})',
                'TOOL:drone({"action": "fpv_status"})',
                'TOOL:drone({"action": "fpv_snapshot"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Drone tools no disponibles: {e}")

    # ── PiCar-X Robot Tools (Raspberry Pi) ──────────────────────────────
    try:
        from .picar_tools import picar_control

        registry.register(
            name="picar",
            description=(
                "Control del robot PiCar-X (Sunfounder) via Safety Proxy en Raspberry Pi. "
                "Robot con cámara, sensores ultrasonido y grayscale, 2 motores y 3 servos. "
                "Acciones: status (estado completo), sensors (ultrasonido/grayscale/bateria), "
                "move (forward/backward/left/right/stop, speed, duration, angle), "
                "stop/parar (detener), kill/emergencia (emergency stop), "
                "camera (pan/tilt en grados), look/mirar (center/left/right/up/down), "
                "steer/girar (angulo direccion), "
                "obstacle_avoid/esquivar (modo autonomo esquivando obstaculos), "
                "line_track/seguir_linea (seguir linea en el piso), "
                "patrol/patrullar (patron: square/zigzag/circle), "
                "dance/bailar (movimientos divertidos), "
                "servo_test, motor_test, snapshot/foto, calibrate/calibrar, "
                "init (re-inicializar hardware), audit/historial (log de comandos)."
            ),
            category="IoT",
            parameters={
                "action": "Accion: status, sensors, move, stop, kill, camera, look, steer, obstacle_avoid, line_track, patrol, dance, servo_test, motor_test, snapshot, calibrate, init, audit",
                "params": "direction, speed, duration, angle, pan, tilt, pattern, servo, limit",
            },
            executor=picar_control,
            examples=[
                'TOOL:picar({"action": "status"})',
                'TOOL:picar({"action": "sensors"})',
                'TOOL:picar({"action": "move", "params": {"direction": "forward", "speed": 30, "duration": 2}})',
                'TOOL:picar({"action": "move", "params": {"direction": "left", "speed": 25, "duration": 1}})',
                'TOOL:picar({"action": "stop"})',
                'TOOL:picar({"action": "camera", "params": {"pan": 45, "tilt": -20}})',
                'TOOL:picar({"action": "look", "params": {"direction": "left"}})',
                'TOOL:picar({"action": "obstacle_avoid", "params": {"duration": 20, "speed": 30}})',
                'TOOL:picar({"action": "patrol", "params": {"pattern": "square", "duration": 30}})',
                'TOOL:picar({"action": "dance"}})',
                'TOOL:picar({"action": "snapshot"})',
                'TOOL:picar({"action": "kill"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ PiCar-X tools no disponibles: {e}")

    # ── PiDog Robot Tools (Raspberry Pi) ───────────────────────────────
    try:
        from .pidog_tools import pidog_control

        registry.register(
            name="pidog",
            description=(
                "Control del robot PiDog (Sunfounder) via Proxy en Raspberry Pi. "
                "Robot cuadrupedo con camara, sensor ultrasonico, touch sensor, RGB LEDs, speaker. "
                "Acciones: status (estado completo), sensors (distancia/touch), "
                "sounds (listar sonidos), actions (listar acciones disponibles), "
                "do_action (stand/sit/forward/backward/turn_left/turn_right/trot/lie/stretch/push_up/wag_tail/shake_head), "
                "preset (bark/howling/hand_shake/high_five/scratch/lick_hand/attack/body_twisting/pant), "
                "speak (reproducir sonido: single_bark_1/howling/angry/growl_1/woohoo), "
                "wake_up (secuencia despertar completa), "
                "patrol/patrullar (patrulla autonoma con evasion de obstaculos), "
                "stop_patrol (detener patrulla), "
                "interactive/interactivo (modo reactivo: responde al tacto y obstaculos), "
                "stop_interactive (detener interactivo), "
                "head/cabeza (mover cabeza: yaw/roll/pitch), "
                "tail/cola (mover cola: angle), "
                "rgb (LEDs: mode=breath/flash/off, color=blue/red/purple/green), "
                "stop/parar (detener todo), snapshot/foto (foto con camara)."
            ),
            category="IoT",
            parameters={
                "action": "Accion: status, sensors, sounds, actions, do_action, preset, speak, wake_up, patrol, stop_patrol, interactive, stop_interactive, head, tail, rgb, stop, snapshot",
                "params": "name (accion/preset/sonido), steps, speed, duration, yaw, roll, pitch, angle, mode, color",
            },
            executor=pidog_control,
            examples=[
                'TOOL:pidog({"action": "status"})',
                'TOOL:pidog({"action": "sensors"})',
                'TOOL:pidog({"action": "do_action", "params": {"name": "forward", "steps": 10}})',
                'TOOL:pidog({"action": "do_action", "params": {"name": "sit"}})',
                'TOOL:pidog({"action": "preset", "params": {"name": "bark"}})',
                'TOOL:pidog({"action": "preset", "params": {"name": "hand_shake"}})',
                'TOOL:pidog({"action": "speak", "params": {"name": "howling"}})',
                'TOOL:pidog({"action": "wake_up"})',
                'TOOL:pidog({"action": "patrol"})',
                'TOOL:pidog({"action": "stop_patrol"})',
                'TOOL:pidog({"action": "interactive", "params": {"duration": 30}})',
                'TOOL:pidog({"action": "head", "params": {"yaw": 30, "pitch": -15}})',
                'TOOL:pidog({"action": "tail", "params": {"angle": 45}})',
                'TOOL:pidog({"action": "rgb", "params": {"mode": "breath", "color": "purple"}})',
                'TOOL:pidog({"action": "stop"})',
                'TOOL:pidog({"action": "snapshot"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ PiDog tools no disponibles: {e}")

    # ── Coffee Machine Tools (Raspberry Pi) ─────────────────────────────
    try:
        from .coffee_tools import coffee_control

        registry.register(
            name="coffee",
            description=(
                "Control de máquina de café con Raspberry Pi: brew, recipes, status, "
                "history, emotion, emotions, emergency_stop, test_pumps, calibrate, custom"
            ),
            category="IoT",
            parameters={
                "action": "Acción de la máquina de café",
                "params": "recipe, water_ml, milk_ml, pump, duration, mood, limit",
            },
            executor=coffee_control,
            examples=[
                'TOOL:coffee({"action": "brew", "params": {"recipe": "cafe_con_leche"}})',
                'TOOL:coffee({"action": "brew", "params": {"recipe": "espresso"}})',
                'TOOL:coffee({"action": "brew", "params": {"recipe": "cortado"}})',
                'TOOL:coffee({"action": "recipes"})',
                'TOOL:coffee({"action": "status"})',
                'TOOL:coffee({"action": "history"})',
                'TOOL:coffee({"action": "emotion", "params": {"mood": "happy"}})',
                'TOOL:coffee({"action": "emergency_stop"})',
                'TOOL:coffee({"action": "custom", "params": {"water_ml": 100, "milk_ml": 50}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Coffee tools no disponibles: {e}")

    # ── Raspi Vision Tools (Hailo-8L AI Camera) ───────────────────────
    try:
        from .raspi_vision_tools import raspi_vision

        registry.register(
            name="raspi_vision",
            description=(
                "Control del sistema Raspberry Pi: vision con Hailo-8L AI, monitor de salud BLE, Home Assistant, WiFi defense. "
                "Vision: see (que ve Tokio), status (estado), snapshot (foto), thoughts (pensamientos IA), "
                "say (mensaje en pantalla), teach (registrar cara), faces (caras conocidas), emotion, model, look_at. "
                "Salud: health (reporte COMPLETO de salud del usuario: HR, presion, SpO2, historial, promedios, evaluacion), "
                "health_status (datos actuales del smartwatch), "
                "health_store (registrar lectura manual: glucose/cholesterol/hemoglobin/uric_acid con metric y value), "
                "health_full (informe COMPLETO combinando smartwatch + Accu-Answer iSaw con analisis). "
                "Casa: ha_status (Home Assistant). WiFi: wifi (defensa WiFi). "
                "AI Brain: ai_status, ai_memory, ai_correct (corregir algo que dice mal), "
                "ai_teach (ensenar un hecho), ai_forget (olvidar observacion erronea), ai_person, ai_environment. "
                "IMPORTANTE: Cuando el usuario pide CORREGIR algo, usar ai_correct, NO repetir see/look."
            ),
            category="IoT",
            parameters={
                "action": "Accion: see, status, snapshot, thoughts, say, teach, faces, emotion, model, look_at, health, health_status, health_store, health_full, ha_status, wifi, ai_status, ai_memory, ai_correct, ai_teach, ai_forget, ai_person, ai_environment",
                "params": "Parametros segun accion: text, color, name, role, emotion, message, model, x, y, correction, key, value, fact, notes",
            },
            executor=raspi_vision,
            examples=[
                'TOOL:raspi_vision({"action": "see"})',
                'TOOL:raspi_vision({"action": "health"})',
                'TOOL:raspi_vision({"action": "status"})',
                'TOOL:raspi_vision({"action": "thoughts"})',
                'TOOL:raspi_vision({"action": "say", "params": {"text": "Hola desde Telegram!"}})',
                'TOOL:raspi_vision({"action": "teach", "params": {"name": "Sofi", "role": "friend"}})',
                'TOOL:raspi_vision({"action": "ai_correct", "params": {"correction": "El cartel dice NIPERIA, no Nigeria"}})',
                'TOOL:raspi_vision({"action": "ai_teach", "params": {"key": "cartel_pared", "value": "NIPERIA Lab"}})',
                'TOOL:raspi_vision({"action": "ai_forget", "params": {"key": "observacion_incorrecta"}})',
                'TOOL:raspi_vision({"action": "snapshot"})',
                'TOOL:raspi_vision({"action": "wifi"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Raspi vision tools no disponibles: {e}")

    # ── Security & Pentest Tools ──────────────────────────────────────────
    try:
        from .security_tools import security_control

        registry.register(
            name="security",
            description=(
                "Herramientas de seguridad ofensiva y defensiva: "
                "nmap/scan (network scanning), wifi_scan, wifi_monitor (deauth/jamming detection), "
                "vuln_scan/vuln (vulnerability assessment), web_test/web (headers/dirs/cors/tech), "
                "net/red (arp/routes/ports/connections/firewall/tailscale/traceroute), "
                "password/credenciales (strength/hash_crack/ssh_audit)"
            ),
            category="Security",
            parameters={
                "action": "Accion de seguridad",
                "params": "Parametros especificos",
            },
            executor=security_control,
            examples=[
                'TOOL:security({"action": "nmap", "params": {"target": "192.168.8.0/24", "scan_type": "quick"}})',
                'TOOL:security({"action": "wifi_scan"})',
                'TOOL:security({"action": "wifi_monitor", "params": {"action": "check_deauth"}})',
                'TOOL:security({"action": "vuln_scan", "params": {"target": "https://example.com", "type": "all"}})',
                'TOOL:security({"action": "web_test", "params": {"target": "https://example.com", "test": "dirs"}})',
                'TOOL:security({"action": "net", "params": {"action": "ports"}})',
                'TOOL:security({"action": "password", "params": {"action": "strength", "password": "test123"}})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ Security tools no disponibles: {e}")

    # ── SITREP — Unified Situational Awareness ─────────────────────────
    try:
        from .sitrep_tool import sitrep
        registry.register(
            name="sitrep",
            description=(
                "Reporte de situación unificado: estado de TODOS los sistemas, "
                "nivel de amenaza DEFCON, WAF, WiFi, salud, drone, HA, infraestructura. "
                "Un solo comando para ver todo. "
                "Actions: full (completo), quick (rápido), threats (amenazas), "
                "health (salud), infra (infraestructura)"
            ),
            category="Security",
            parameters={
                "action": "full|quick|threats|health|infra",
                "params": "(Opcional) Parámetros adicionales",
            },
            executor=sitrep,
            examples=[
                'TOOL:sitrep({"action": "full"})',
                'TOOL:sitrep({"action": "quick"})',
                'TOOL:sitrep({"action": "threats"})',
            ],
        )
        count += 1
    except Exception as e:
        logger.warning(f"⚠️ SITREP tool no disponible: {e}")

    logger.info(f"✅ {count} tools builtin registradas")
    return count
