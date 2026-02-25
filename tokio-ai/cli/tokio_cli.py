#!/usr/bin/env python3
"""
TokioAI CLI Standalone - Estilo OpenClaw
Ejecuta independientemente del dashboard
"""
import os
import sys
import json
import asyncio
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# Intentar importar httpx para conexión HTTP al servicio CLI
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# Agregar tokio-core al path
# Detectar si estamos en contenedor Docker o en host
script_dir = Path(__file__).parent
if Path("/app").exists():
    # Estamos en contenedor Docker
    app_dir = Path("/app")
    project_root = app_dir
else:
    # Estamos en host
    project_root = script_dir.parent.parent

# Buscar tokio-core en varias ubicaciones posibles
possible_paths = [
    project_root / "tokio-core",
    project_root / "tokio_core",  # symlink
    Path("/app/tokio-core"),
    Path("/app/tokio_core"),
    script_dir.parent.parent / "tokio-core",
]

tokio_core_dir = None
for path in possible_paths:
    if path.exists():
        tokio_core_dir = path
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        break

# También agregar la raíz del proyecto
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Crear symlink temporal si no existe (para compatibilidad con dashboard)
if tokio_core_dir:
    tokio_core_symlink = project_root / "tokio_core"
    if tokio_core_dir.exists() and not tokio_core_symlink.exists():
        try:
            os.symlink(str(tokio_core_dir), str(tokio_core_symlink))
        except OSError:
            pass

try:
    # Intentar importar desde tokio_core (symlink o módulo)
    from tokio_core import get_engine
    from tokio_core.engine_openclaw import OpenClawEngine
    from tokio_core.self_healing import SelfHealingSystem
    from tokio_core.llm.factory import create_llm_provider
except ImportError:
    try:
        # Fallback: importar directamente desde tokio-core
        from engine_openclaw import OpenClawEngine
        from engine import TokioEngine, get_engine
        from self_healing import SelfHealingSystem
        from llm.factory import create_llm_provider
    except ImportError as e:
        print(f"❌ Error importando tokio-core: {e}")
        print(f"   Script dir: {script_dir}")
        print(f"   Project root: {project_root}")
        print(f"   Tokio-core dir: {tokio_core_dir}")
        print(f"   Paths probados: {possible_paths}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# Intentar importar rich, si no está usar input básico
try:
    from rich.console import Console
    from rich.prompt import Prompt
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠️  rich no está instalado. Instala con: pip install rich")
    print("   Usando interfaz básica...")

logger = logging.getLogger(__name__)

# Workspace del agente (estilo OpenClaw)
# Usar directorio local si no hay permisos para /data
default_home = Path.home() / ".tokioai"
if os.getenv("TOKIOAI_HOME"):
    AGENT_HOME = Path(os.getenv("TOKIOAI_HOME"))
else:
    # Intentar /data primero, si falla usar home
    try:
        test_dir = Path("/data/tokioai")
        test_dir.mkdir(parents=True, exist_ok=True)
        AGENT_HOME = test_dir
    except (PermissionError, OSError):
        AGENT_HOME = default_home

AGENT_HOME.mkdir(parents=True, exist_ok=True)

SOUL_FILE = AGENT_HOME / "SOUL.md"
MEMORY_FILE = AGENT_HOME / "MEMORY.md"
CONFIG_FILE = AGENT_HOME / "CONFIG.json"
SESSION_DIR = AGENT_HOME / "sessions"
LOGS_DIR = AGENT_HOME / "logs"
SESSION_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Inicializar archivos si no existen
if not SOUL_FILE.exists():
    SOUL_FILE.write_text("""# TokioAI Soul 🦞

## Quién soy
Soy TokioAI, un agente autónomo de seguridad SOC con arquitectura OpenClaw.
Mi propósito es gestionar infraestructura de seguridad, analizar amenazas, ejecutar acciones de mitigación,
y **auto-repararme** cuando algo falla.

## Cómo trabajo
- **Autónomo**: NUNCA pregunto, siempre actúo
- **Auto-reparación**: Si algo falla, busco 3 alternativas y me arreglo solo
- **Auto-configuración**: Me adapto al entorno automáticamente
- **Persistente**: Todo se guarda en disco (SOUL.md, MEMORY.md, CONFIG.json)
- **Inteligente**: Uso el engine de TokioAI para procesar todo
- **Directo**: Ejecuto sin ceremonia

## Principios OpenClaw
1. NUNCA digo "no puedo" - siempre encuentro una forma
2. Los archivos en disco son mi fuente de verdad
3. Guardo todo en MEMORY.md para no olvidar
4. Respondo SIEMPRE en español
5. **Auto-reparación**: Si fallo, me arreglo solo
6. **Presencia**: Funciono desde CLI, Dashboard, Telegram, WebSocket
""", encoding="utf-8")

if not MEMORY_FILE.exists():
    MEMORY_FILE.write_text(f"""# TokioAI Memory

Creado: {datetime.now().isoformat()}

## Notas
- Todo lo importante va aquí
- Esta es mi memoria de largo plazo
""", encoding="utf-8")

if not CONFIG_FILE.exists():
    CONFIG_FILE.write_text(json.dumps({
        "version": "3.0-openclaw",
        "created": datetime.now().isoformat(),
        "auto_repair": True,
        "auto_config": True,
        "model": "gemini-2.0-flash",
        "max_retries": 3,
        "presence": {
            "cli": True,
            "dashboard": True,
            "telegram": False,
            "websocket": True
        }
    }, indent=2), encoding="utf-8")


class TokioCLI:
    """CLI standalone estilo OpenClaw"""
    
    def __init__(self):
        self.console = Console() if RICH_AVAILABLE else None
        self.workspace = AGENT_HOME
        self.engine = None
        self.openclaw_engine = None
        self.self_healing = None
        self._engine_initializing = False
        self.conversation_history = []
        self.session_id = f"session-{int(time.time())}"
        self.session_file = SESSION_DIR / f"{self.session_id}.jsonl"
        
        # Cargar configuración
        try:
            self.config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            self.config = {}
        self.soul = SOUL_FILE.read_text(encoding="utf-8")
        
        # Session log
        self.log_entry("session_start", {"config": self.config})
    
    def log_entry(self, event_type: str, data: Dict):
        """Guardar evento en session log"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        }
        try:
            with open(self.session_file, "a", encoding="utf-8", errors="replace") as f:
                json_str = json.dumps(entry, ensure_ascii=False)
                f.write(json_str + "\n")
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            # Si hay problemas de encoding, usar ASCII y reemplazar caracteres problemáticos
            with open(self.session_file, "a", encoding="utf-8", errors="replace") as f:
                # Convertir data a string seguro
                safe_data = {}
                for k, v in data.items():
                    try:
                        safe_data[k] = str(v).encode('utf-8', errors='replace').decode('utf-8')
                    except:
                        safe_data[k] = repr(v)
                entry["data"] = safe_data
                json_str = json.dumps(entry, ensure_ascii=False)
                f.write(json_str + "\n")
    
    def save_memory(self, content: str):
        """Guardar en MEMORY.md"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n## {timestamp}\n{content}\n")
    
    def read_memory(self, lines: int = 50) -> str:
        """Leer últimas entradas de memoria"""
        content = MEMORY_FILE.read_text(encoding="utf-8")
        all_lines = content.split("\n")
        return "\n".join(all_lines[-lines:])
    
    def print(self, text: str, style: str = ""):
        """Print con rich o sin rich"""
        if self.console:
            self.console.print(text, style=style)
        else:
            print(text)
    
    async def initialize_engine(self):
        """Inicializar engine de TokioAI estilo OpenClaw"""
        if self.openclaw_engine:
            return
        
        if self._engine_initializing:
            while self._engine_initializing:
                await asyncio.sleep(0.1)
            return
        
        if not get_engine or not OpenClawEngine:
            self.print("❌ TokioAI Engine no disponible", "red")
            return
        
        self._engine_initializing = True
        try:
            self.print("🚀 Inicializando TokioAI Engine (OpenClaw)...", "yellow")
            
            # Obtener engine base
            self.engine = await get_engine()
            
            # Crear engine OpenClaw
            if OpenClawEngine:
                try:
                    logger.info(f"Inicializando OpenClawEngine con workspace: {AGENT_HOME}")
                    self.openclaw_engine = OpenClawEngine(
                        workspace_dir=AGENT_HOME,
                        llm=self.engine.llm,
                        tool_registry=self.engine.tool_registry,
                        sandbox=self.engine.sandbox
                    )
                    logger.info("✅ OpenClawEngine inicializado correctamente")
                except Exception as e:
                    logger.error(f"❌ Error inicializando OpenClawEngine: {e}", exc_info=True)
                    self.print(f"❌ Error inicializando OpenClawEngine: {str(e)[:200]}", "red")
                    raise
            
            # Inicializar self-healing si está habilitado
            if self.config.get("auto_repair", True) and SelfHealingSystem and create_llm_provider:
                try:
                    llm = create_llm_provider()
                    self.self_healing = SelfHealingSystem(llm, max_retries=self.config.get("max_retries", 3))
                except Exception as e:
                    logger.warning(f"No se pudo inicializar self-healing: {e}")
            
            tools_count = len(self.engine.tool_registry.tools) if self.engine else 0
            self.print(f"✅ Engine OpenClaw listo ({tools_count} tools)", "green")
            self.log_entry("engine_initialized", {"tools_count": tools_count, "mode": "openclaw"})
        except Exception as e:
            self.print(f"❌ Error inicializando engine: {str(e)[:200]}", "red")
            self.log_entry("engine_error", {"error": str(e)})
            raise
        finally:
            self._engine_initializing = False
    
    async def handle_command(self, command: str):
        """Procesar comando del usuario - Usa el servicio CLI HTTP (tokio-cli:8100)"""
        self.log_entry("user_command", {"command": command})
        
        # Comandos especiales OpenClaw
        if command.startswith("/"):
            await self.handle_special_command(command)
            return
        
        # Usar el servicio CLI HTTP en lugar del engine directo
        try:
            self.print("🤖 Procesando con CLI Service...", "yellow")
            
            # Importar cli_client
            try:
                # Intentar importar desde el dashboard-api
                import sys
                dashboard_api_path = Path("/app")
                if not dashboard_api_path.exists():
                    # Si no estamos en contenedor, buscar en el proyecto
                    dashboard_api_path = self.workspace.parent.parent / "dashboard-api"
                
                if str(dashboard_api_path) not in sys.path:
                    sys.path.insert(0, str(dashboard_api_path))
                
                from cli_client import get_cli_client
                
            except ImportError:
                # Fallback: usar httpx directamente
                import httpx
                self.print("⚠️  Usando conexión HTTP directa (cli_client no disponible)", "yellow")
                
                async with httpx.AsyncClient(timeout=120.0) as client:
                    # Crear job
                    job_response = await client.post(
                        "http://tokio-cli:8100/api/cli/jobs",
                        json={"command": command, "session_id": getattr(self, 'session_id', None)}
                    )
                    
                    if job_response.status_code != 200:
                        self.print(f"❌ Error creando job: {job_response.text[:200]}", "red")
                        return
                    
                    job_data = job_response.json()
                    job_id = job_data.get("job_id")
                    
                    if not job_id:
                        self.print(f"❌ No se recibió job_id: {job_data}", "red")
                        return
                    
                    # Esperar resultado
                    max_wait = 60
                    waited = 0
                    while waited < max_wait:
                        await asyncio.sleep(2)
                        result_response = await client.get(f"http://tokio-cli:8100/api/cli/jobs/{job_id}")
                        
                        if result_response.status_code != 200:
                            self.print(f"❌ Error obteniendo resultado: {result_response.text[:200]}", "red")
                            return
                        
                        job_result = result_response.json()
                        status = job_result.get("status")
                        
                        if status == "completed":
                            result_text = job_result.get("result", "")
                            if result_text:
                                self.print(result_text)
                            else:
                                self.print("✅ Comando completado", "green")
                            return
                        elif status == "failed":
                            error_msg = job_result.get("error", "Error desconocido")
                            self.print(f"❌ {error_msg[:200]}", "red")
                            return
                        
                        waited += 2
                    
                    self.print("⏱️  Timeout esperando resultado", "yellow")
                    return
            
            # Usar cli_client (método preferido)
            client = get_cli_client()
            result = await client.execute_and_wait(command, session_id=getattr(self, 'session_id', None), timeout=120)
            
            if result.get("success"):
                response = result.get("result", result.get("output", ""))
                
                if response and response.strip():
                    self.print(response)
                else:
                    self.print("✅ Comando completado", "green")
            else:
                error_msg = result.get("error", "Error desconocido")
                self.print(f"❌ {error_msg[:200]}", "red")
                self.log_entry("command_error", {"error": error_msg, "command": command})
                
        except Exception as e:
            error_msg = str(e)
            self.print(f"❌ {error_msg[:200]}", "red")
            self.log_entry("command_error", {"error": error_msg, "command": command})
            logger.error(f"Error ejecutando comando: {e}", exc_info=True)
    
    async def handle_special_command(self, command: str):
        """Manejar comandos especiales estilo OpenClaw"""
        cmd = command.lower().strip()
        
        if cmd == "/help":
            help_text = """🦞 TokioAI - Arquitectura OpenClaw

**Comandos básicos:**
  /help      - Esta ayuda
  /status    - Estado del sistema
  /memory    - Ver memoria reciente
  /soul      - Ver alma (SOUL.md)
  /config    - Ver/editar configuración
  
**Auto-reparación:**
  /repair    - Forzar auto-reparación del sistema
  
**Sistema:**
  /tools     - Listar tools disponibles
  /health    - Health check completo
  /logs      - Ver logs recientes

**Uso:**
  Escribe comandos en lenguaje natural y TokioAI los procesará automáticamente.
"""
            self.print(help_text)
            
        elif cmd == "/status":
            tools_count = len(self.engine.tool_registry.tools) if self.engine else 0
            status_text = f"""📊 Estado del Sistema:

**Engine:**
  Estado: {'✅ Activo (OpenClaw)' if self.openclaw_engine else '❌ No inicializado'}
  Tools: {tools_count}
  Auto-reparación: {'✅ Activada' if self.config.get('auto_repair') else '❌ Desactivada'}

**Configuración:**
  Modelo: {self.config.get('model', 'N/A')}
  Max retries: {self.config.get('max_retries', 3)}
  Workspace: {AGENT_HOME}
"""
            self.print(status_text)
            
        elif cmd == "/memory":
            memory = self.read_memory()
            if self.console:
                self.console.print(Markdown(memory))
            else:
                self.print(memory)
            
        elif cmd == "/soul":
            if self.console:
                self.console.print(Markdown(self.soul))
            else:
                self.print(self.soul)
            
        elif cmd == "/config":
            config_text = json.dumps(self.config, indent=2, ensure_ascii=False)
            self.print(f"```json\n{config_text}\n```")
            
        elif cmd == "/tools":
            # Inicializar engine si no está inicializado
            if not self.openclaw_engine:
                await self.initialize_engine()
            
            if not self.engine or not self.openclaw_engine:
                self.print("❌ Engine no inicializado", "red")
                return
            tools = self.engine.tool_registry.list_tools()
            tools_text = "\n".join([
                f"  • {t.name}: {t.description[:60]}"
                for t in tools[:20]
            ])
            self.print(f"📦 Tools ({len(tools)}):\n{tools_text}")
            
        elif cmd == "/health":
            health = await self.health_check()
            health_text = json.dumps(health, indent=2, ensure_ascii=False)
            self.print(f"```json\n{health_text}\n```")
            
        elif cmd == "/logs":
            # Mostrar logs de la sesión actual
            if self.session_file.exists():
                try:
                    with open(self.session_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()[-30:]  # Últimas 30 líneas
                        logs = "".join(lines)
                        self.print(f"📋 Logs de sesión ({self.session_id}):\n```\n{logs}\n```")
                except Exception as e:
                    self.print(f"❌ Error leyendo logs: {e}", "red")
            else:
                self.print("No hay logs aún para esta sesión", "yellow")
            
        else:
            self.print(f"❌ Comando desconocido: {command}\nUsa /help para ver comandos", "red")
    
    async def health_check(self) -> Dict:
        """Health check completo estilo OpenClaw"""
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {}
        }
        
        if self.engine:
            health["components"]["engine"] = {
                "status": "healthy",
                "tools": len(self.engine.tool_registry.tools),
                "running": self.engine.running
            }
        else:
            health["components"]["engine"] = {"status": "not_initialized"}
        
        health["components"]["self_healing"] = {
            "status": "healthy" if self.self_healing else "disabled",
            "enabled": self.config.get("auto_repair", True)
        }
        
        health["components"]["files"] = {
            "soul": SOUL_FILE.exists(),
            "memory": MEMORY_FILE.exists(),
            "config": CONFIG_FILE.exists()
        }
        
        if not all([
            health["components"]["files"]["soul"],
            health["components"]["files"]["memory"],
            health["components"]["files"]["config"]
        ]):
            health["status"] = "degraded"
        
        if not self.engine:
            health["status"] = "degraded"
        
        return health
    
    async def run(self):
        """Loop principal del CLI"""
        # Banner
        if self.console:
            banner = Panel.fit(
                "[bold cyan]🦞 TokioAI v3.0 - CLI Standalone[/bold cyan]\n"
                "[green]✅ Conectado[/green]\n"
                "[green]✅ Auto-reparación activada[/green]\n"
                "\n"
                "Escribe /help para ver comandos",
                border_style="cyan"
            )
            self.console.print(banner)
        else:
            self.print("🦞 TokioAI v3.0 - CLI Standalone")
            self.print("✅ Conectado")
            self.print("✅ Auto-reparación activada")
            self.print("\nEscribe /help para ver comandos\n")
        
        # Loop principal
        while True:
            try:
                # Prompt
                if self.console:
                    command = Prompt.ask("\n[bold cyan]TOKIO[/bold cyan]")
                else:
                    command = input("\nTOKIO> ").strip()
                
                if not command:
                    continue
                
                if command.lower() in ['exit', 'quit', 'q']:
                    self.print("👋 Saliendo...", "yellow")
                    break
                
                if command.startswith("/"):
                    await self.handle_special_command(command)
                else:
                    await self.handle_command(command)
                    
            except KeyboardInterrupt:
                self.print("\n👋 Saliendo...", "yellow")
                break
            except EOFError:
                self.print("\n👋 Saliendo...", "yellow")
                break
            except Exception as e:
                self.print(f"❌ Error: {e}", "red")
                logger.error(f"Error en CLI: {e}", exc_info=True)
        
        # Guardar fin de sesión
        self.log_entry("session_end", {})


async def main():
    """Función principal"""
    cli = TokioCLI()
    await cli.run()


if __name__ == "__main__":
    # Configurar logging básico
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Saliendo...")
    except Exception as e:
        print(f"❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
