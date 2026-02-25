"""
Endpoint para ejecutar comandos del MCP Host CLI
Conecta el terminal web con el MCP server real
"""
import os
import json
import subprocess
import asyncio
import logging
import time
import uuid
import re
from threading import Lock
from typing import Dict, Any, Optional, List, AsyncGenerator
from fastapi import Body, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
import sys

logger = logging.getLogger(__name__)

# Configuración del MCP
MCP_HOST_PATH = os.path.join(os.path.dirname(__file__), "mcp-host")
MCP_CORE_PATH = os.path.join(os.path.dirname(__file__), "mcp-core")
# Obtener API key de múltiples fuentes posibles
GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY") or 
    os.getenv("GOOGLE_AI_API_KEY") or 
    os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or
    ""
)

# VORTEX 9: Memoria unificada - un solo punto de verdad
class ConversationMemory:
    """Memoria de conversación que se auto-actualiza y propaga"""
    _sessions: Dict[str, List[Dict]] = {}
    _max_history = 30
    
    @classmethod
    def get(cls, session_id: str) -> List[Dict]:
        """Obtiene historial - si no existe, crea vacío"""
        return cls._sessions.get(session_id, [])
    
    @classmethod
    def append(cls, session_id: str, role: str, content: str):
        """Agrega mensaje y auto-limpia excesos (vibración 9: auto-evolución)"""
        if session_id not in cls._sessions:
            cls._sessions[session_id] = []
        
        cls._sessions[session_id].append({"role": role, "content": content})
        
        # Auto-limpieza: mantener solo últimos N mensajes (energía libre)
        if len(cls._sessions[session_id]) > cls._max_history:
            cls._sessions[session_id] = cls._sessions[session_id][-cls._max_history:]
    
    @classmethod
    def update_from_response(cls, session_id: str, response: str):
        """Actualiza desde respuesta del LLM (flujo unidireccional)"""
        cls.append(session_id, "assistant", response)
    
    @classmethod
    def to_json(cls, session_id: str) -> str:
        """Serializa para transmisión (vibración 6: eficiencia)"""
        return json.dumps(cls.get(session_id))

# Reemplazar _conversation_sessions con ConversationMemory
_conversation_sessions = ConversationMemory  # Compatibilidad hacia atrás

# Control de procesos en ejecución (para cancelación)
_running_processes: Dict[str, subprocess.Popen] = {}
_process_lock = Lock()
_cancel_flags = set()

# Jobs para SSE (CLI pro)
_mcp_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = Lock()
_JOB_TTL_SECONDS = 3600

_NOISE_PATTERNS = [
    '🔧 PYTHONPATH', '📝 Procesando prompt', 'Prompt:', 'Modo:',
    '✅ GEMINI_API_KEY', '🌀', 'Inicializando MCP Host',
    'Conectando al servidor MCP', 'Inicializando LLM', 'MCP Host listo'
]
_LOG_LINE_RE = re.compile(r'^\d{4}-\d{2}-\d{2} .* - (INFO|WARNING|ERROR) -')

def _classify_line(line: str) -> str:
    if not line:
        return "empty"
    if _LOG_LINE_RE.match(line):
        if "ERROR" in line or "Traceback" in line:
            return "error"
        return "noise"
    if any(pat in line for pat in _NOISE_PATTERNS):
        return "noise"
    if "Traceback" in line or "Exception" in line:
        return "error"
    return "output"

# Verificar que los directorios existan
if not os.path.exists(MCP_HOST_PATH):
    logger.warning(f"MCP Host path no existe: {MCP_HOST_PATH}")
if not os.path.exists(MCP_CORE_PATH):
    logger.warning(f"MCP Core path no existe: {MCP_CORE_PATH}")

def get_mcp_config() -> Dict[str, Any]:
    """Obtiene la configuración del MCP server"""
    return {
        "mcpServer": {
            "command": "python3",
            "args": [
                os.path.join(MCP_CORE_PATH, "mcp_server.py")
            ],
            "env": {
                **os.environ,
                "PYTHONPATH": MCP_CORE_PATH
            }
        },
        "geminiApiKey": GEMINI_API_KEY
    }

def _register_job(job: Dict[str, Any]) -> str:
    job_id = job["job_id"]
    with _jobs_lock:
        _mcp_jobs[job_id] = job
    return job_id

def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        return _mcp_jobs.get(job_id)

def _cleanup_job(job_id: str) -> None:
    with _jobs_lock:
        job = _mcp_jobs.get(job_id)
        if not job:
            return
        done_at = job.get("done_at")
        if done_at and (time.time() - done_at) > _JOB_TTL_SECONDS:
            _mcp_jobs.pop(job_id, None)

async def _emit_job_event(job: Dict[str, Any], event: Dict[str, Any]) -> None:
    event.setdefault("ts", time.time())
    job["last_event_ts"] = event["ts"]
    await job["queue"].put(event)

async def _ensure_mcp_host_ready() -> Optional[str]:
    mcp_host_script = os.path.join(MCP_HOST_PATH, "dist", "index.js")
    if os.path.exists(mcp_host_script):
        return None

    logger.info("MCP host no compilado, compilando...")
    try:
        install_result = subprocess.run(
            ["npm", "install"],
            cwd=MCP_HOST_PATH,
            check=False,
            timeout=120,
            capture_output=True,
            text=True
        )
        if install_result.returncode != 0:
            logger.warning(f"npm install tuvo warnings: {install_result.stderr[:200]}")

        build_result = subprocess.run(
            ["npm", "run", "build"],
            cwd=MCP_HOST_PATH,
            check=False,
            timeout=180,
            capture_output=True,
            text=True
        )
        if build_result.returncode != 0:
            logger.error(f"Error compilando: {build_result.stderr}")
            return f"Error compilando MCP host: {build_result.stderr[:300]}"
    except subprocess.TimeoutExpired:
        return "Timeout compilando MCP host"
    except Exception as e:
        logger.error(f"Error compilando MCP host: {e}", exc_info=True)
        return f"MCP host no disponible. Error: {str(e)}"
    return None

def _build_mcp_command_env(command: str, mode: str, session_id: str) -> Dict[str, Any]:
    mcp_host_script = os.path.join(MCP_HOST_PATH, "dist", "index.js")
    env = os.environ.copy()

    current_api_key = (
        os.getenv("GEMINI_API_KEY") or 
        os.getenv("GOOGLE_AI_API_KEY") or 
        os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or
        GEMINI_API_KEY or
        ""
    )
    if current_api_key:
        env["GEMINI_API_KEY"] = current_api_key
        env["GOOGLE_AI_API_KEY"] = current_api_key
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = current_api_key
        os.environ["GEMINI_API_KEY"] = current_api_key
        os.environ["GOOGLE_AI_API_KEY"] = current_api_key
    else:
        raise RuntimeError("GEMINI_API_KEY no está configurada. Configura GEMINI_API_KEY en Cloud Run.")

    env["MCP_SERVER_PATH"] = os.path.join(MCP_CORE_PATH, "mcp_server.py")
    env["MCP_SERVER_CMD"] = "python3"
    env["PYTHONPATH"] = MCP_CORE_PATH

    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    use_public_ip = os.getenv("TOKIO_POSTGRES_USE_PUBLIC_IP", "false").lower() == "true"
    if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME")

    env["POSTGRES_HOST"] = postgres_host
    env["POSTGRES_HOST_PUBLIC"] = postgres_host
    env["POSTGRES_PORT"] = os.getenv("POSTGRES_PORT", "5432")
    env["POSTGRES_DB"] = os.getenv("POSTGRES_DB", "soc_ai")
    env["POSTGRES_USER"] = os.getenv("POSTGRES_USER", "soc_user")
    env["POSTGRES_PASSWORD"] = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")

    env["KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "YOUR_IP_ADDRESS:9093")
    env["DASHBOARD_API_BASE_URL"] = os.getenv(
        "DASHBOARD_API_BASE_URL",
        "https://YOUR_DASHBOARD_API_URL"
    )
    env["AUTOMATION_API_TOKEN"] = os.getenv("AUTOMATION_API_TOKEN", "")
    env["SOAR_USE_PROXY"] = os.getenv("SOAR_USE_PROXY", "false")

    memory = ConversationMemory
    memory.append(session_id, "user", command)
    history_json = memory.to_json(session_id)
    if history_json:
        env["MCP_CONVERSATION_HISTORY"] = history_json

    cmd = ["node", mcp_host_script, "chat", "-p", command, "-m", "gemini-2.0-flash", "--mode", mode]
    return {"cmd": cmd, "env": env}

def _clean_mcp_output(session_id: str, output: str, error_output: Optional[str]) -> Dict[str, Any]:
    memory = ConversationMemory
    history_updated = None
    cleaned_output = ""

    lines = output.split('\n')
    cleaned_lines = []
    skip_response_header = False
    json_found = False

    for line in lines:
        if not json_found and (line.strip().startswith('{"history":') or line.strip().startswith('{"response":')):
            try:
                parsed = json.loads(line)
                history_updated = parsed.get('history', [])
                if history_updated:
                    memory._sessions[session_id] = history_updated[-memory._max_history:]
                if parsed.get('response'):
                    cleaned_lines.append(parsed['response'])
                json_found = True
                continue
            except Exception:
                pass

        if any(skip in line for skip in _NOISE_PATTERNS) or line.startswith('TOKIO (agent)>') or line.startswith('✅ Conectado al MCP Host'):
            continue

        if '✅ Respuesta:' in line:
            skip_response_header = True
            continue

        if skip_response_header and not line.strip():
            skip_response_header = False
            continue

        skip_response_header = False

        if line.strip():
            cleaned_lines.append(line)

    cleaned_output = '\n'.join(cleaned_lines).strip()

    if cleaned_output:
        final_lines = []
        prev_line = None
        for line in cleaned_output.split('\n'):
            line_stripped = line.strip()
            if line_stripped and line_stripped != prev_line:
                final_lines.append(line)
                prev_line = line_stripped
        cleaned_output = '\n'.join(final_lines).strip()

    if not cleaned_output and error_output:
        error_lines = error_output.split('\n')
        cleaned_error = []
        for line in error_lines:
            if _classify_line(line) != "noise":
                cleaned_error.append(line)
        if cleaned_error:
            cleaned_output = '\n'.join(cleaned_error).strip()

    return {
        "cleaned_output": cleaned_output,
        "history_updated": history_updated
    }

async def _stream_reader(job: Dict[str, Any], stream: asyncio.StreamReader, stream_name: str) -> None:
    try:
        while True:
            chunk = await stream.read(1024)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if text:
                job[f"raw_{stream_name}"] = job.get(f"raw_{stream_name}", "") + text
                job["had_output"] = True
                buffer_key = f"buffer_{stream_name}"
                job[buffer_key] = job.get(buffer_key, "") + text
                if "\n" in job[buffer_key]:
                    lines = job[buffer_key].split("\n")
                    job[buffer_key] = lines[-1]
                    for line in lines[:-1]:
                        line = line.strip()
                        if not line:
                            continue
                        line_type = _classify_line(line)
                        if line_type == "noise":
                            stage = "info"
                            if "Inicializando MCP Host" in line:
                                stage = "connecting"
                            elif "Procesando prompt" in line or line.startswith("Prompt:"):
                                stage = "thinking"
                            elif "MCP Host listo" in line:
                                stage = "ready"
                            await _emit_job_event(job, {
                                "type": "status",
                                "stage": stage,
                                "detail": line
                            })
                            continue
                        if line_type == "error":
                            await _emit_job_event(job, {
                                "type": "error",
                                "message": line
                            })
                            continue
                        if "Ejecutando tool:" in line:
                            await _emit_job_event(job, {
                                "type": "status",
                                "stage": "tool_call",
                                "detail": line
                            })
                            continue
                        if "Iteración" in line or "Iteracion" in line:
                            await _emit_job_event(job, {
                                "type": "status",
                                "stage": "iteration",
                                "detail": line
                            })
                            continue
                        await _emit_job_event(job, {
                            "type": "output",
                            "stream": stream_name,
                            "data": line + "\n"
                        })
    except Exception as e:
        await _emit_job_event(job, {
            "type": "error",
            "message": f"Error leyendo {stream_name}: {e}"
        })

async def _run_mcp_job(job_id: str) -> None:
    job = _get_job(job_id)
    if not job:
        return

    await _emit_job_event(job, {"type": "status", "stage": "starting"})
    compile_error = await _ensure_mcp_host_ready()
    if compile_error:
        await _emit_job_event(job, {"type": "final", "success": False, "error": compile_error, "output": ""})
        job["done_at"] = time.time()
        return

    try:
        cmd_env = _build_mcp_command_env(job["command"], job["mode"], job["session_id"])
    except Exception as e:
        await _emit_job_event(job, {"type": "final", "success": False, "error": str(e), "output": ""})
        job["done_at"] = time.time()
        return

    cmd = cmd_env["cmd"]
    env = cmd_env["env"]
    await _emit_job_event(job, {"type": "status", "stage": "running"})

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=MCP_HOST_PATH,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    with _process_lock:
        _running_processes[job_id] = proc
        _running_processes[job["session_id"]] = proc

    stdout_task = asyncio.create_task(_stream_reader(job, proc.stdout, "stdout"))
    stderr_task = asyncio.create_task(_stream_reader(job, proc.stderr, "stderr"))

    try:
        returncode = await asyncio.wait_for(proc.wait(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        returncode = 124

    await stdout_task
    await stderr_task

    with _process_lock:
        _running_processes.pop(job_id, None)
        if _running_processes.get(job["session_id"]) is proc:
            _running_processes.pop(job["session_id"], None)

    raw_stdout = job.get("raw_stdout", "")
    raw_stderr = job.get("raw_stderr", "")
    cleaned = _clean_mcp_output(job["session_id"], raw_stdout, raw_stderr)
    cleaned_output = cleaned.get("cleaned_output") or ""
    error_lines = []
    if raw_stderr:
        for line in raw_stderr.split('\n'):
            if _classify_line(line) == "error":
                error_lines.append(line.strip())

    success = returncode == 0 or (cleaned_output and not error_lines)

    final_output = ""
    if not job.get("had_output") and cleaned_output:
        final_output = cleaned_output

    error_msg = None
    if not success:
        if error_lines:
            error_msg = "\n".join(error_lines)[:500]
        else:
            error_msg = "Error ejecutando MCP host"

    await _emit_job_event(job, {
        "type": "final",
        "success": success,
        "output": final_output,
        "error": None if success else error_msg
    })
    job["done_at"] = time.time()

async def create_mcp_job(command: str, mode: str, session_id: str) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "command": command,
        "mode": mode,
        "session_id": session_id,
        "queue": asyncio.Queue(),
        "created_at": time.time(),
        "done_at": None,
        "last_event_ts": time.time()
    }
    _register_job(job)
    asyncio.create_task(_run_mcp_job(job_id))
    return {"success": True, "job_id": job_id}

async def sse_job_events(job_id: str) -> AsyncGenerator[str, None]:
    job = _get_job(job_id)
    if not job:
        yield f"data: {json.dumps({'type':'final','success':False,'error':'Job no encontrado','output':''})}\n\n"
        return

    while True:
        try:
            event = await asyncio.wait_for(job["queue"].get(), timeout=15)
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") == "final":
                break
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type':'ping','ts':time.time()})}\n\n"
        finally:
            _cleanup_job(job_id)

def cancel_mcp_job(job_id: str) -> Dict[str, Any]:
    _cancel_flags.add(job_id)
    with _process_lock:
        proc = _running_processes.get(job_id)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    job = _get_job(job_id)
    if job:
        asyncio.create_task(_emit_job_event(job, {
            "type": "final",
            "success": False,
            "error": "Comando cancelado por el usuario",
            "output": ""
        }))
        job["done_at"] = time.time()
    return {"success": True, "message": "Cancel solicitado"}

async def execute_mcp_command(command: str, mode: str = "agent", session_id: str = "default") -> Dict[str, Any]:
    """
    Ejecuta un comando a través del MCP host
    """
    try:
        if not command or not command.strip():
            return {
                "success": False,
                "error": "Comando vacío"
            }
        
        # Verificar que el MCP host esté disponible
        mcp_host_script = os.path.join(MCP_HOST_PATH, "dist", "index.js")
        
        # Si no existe el script compilado, intentar compilar
        if not os.path.exists(mcp_host_script):
            logger.info("MCP host no compilado, compilando...")
            try:
                # Instalar dependencias
                install_result = subprocess.run(
                    ["npm", "install"],
                    cwd=MCP_HOST_PATH,
                    check=False,
                    timeout=120,
                    capture_output=True,
                    text=True
                )
                if install_result.returncode != 0:
                    logger.warning(f"npm install tuvo warnings: {install_result.stderr[:200]}")
                
                # Compilar TypeScript
                build_result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=MCP_HOST_PATH,
                    check=False,
                    timeout=180,
                    capture_output=True,
                    text=True
                )
                if build_result.returncode != 0:
                    logger.error(f"Error compilando: {build_result.stderr}")
                    return {
                        "success": False,
                        "error": f"Error compilando MCP host: {build_result.stderr[:300]}"
                    }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "Timeout compilando MCP host"
                }
            except Exception as e:
                logger.error(f"Error compilando MCP host: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"MCP host no disponible. Error: {str(e)}"
                }
        
        # Crear archivo de configuración temporal
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config = get_mcp_config()
            json.dump(config, f)
            config_file = f.name
        
        try:
            # Ejecutar MCP host en modo no interactivo
            env = os.environ.copy()
            
            # CRÍTICO: Asegurar que la API key esté disponible en todas las variables posibles
            # Obtener de nuevo desde el entorno actual (puede haber cambiado)
            current_api_key = (
                os.getenv("GEMINI_API_KEY") or 
                os.getenv("GOOGLE_AI_API_KEY") or 
                os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or
                GEMINI_API_KEY or
                ""
            )
            
            if current_api_key:
                env["GEMINI_API_KEY"] = current_api_key
                env["GOOGLE_AI_API_KEY"] = current_api_key
                env["GOOGLE_GENERATIVE_AI_API_KEY"] = current_api_key
                # También establecer en el proceso actual para que esté disponible
                os.environ["GEMINI_API_KEY"] = current_api_key
                os.environ["GOOGLE_AI_API_KEY"] = current_api_key
                logger.info(f"✅ GEMINI_API_KEY configurada (primeros 10 chars: {current_api_key[:10]}...)")
            else:
                logger.error("❌ GEMINI_API_KEY NO está disponible en el entorno")
                return {
                    "success": False,
                    "error": "GEMINI_API_KEY no está configurada. Por favor, configura la variable de entorno GEMINI_API_KEY en Cloud Run."
                }
            
            env["MCP_SERVER_PATH"] = os.path.join(MCP_CORE_PATH, "mcp_server.py")
            env["MCP_SERVER_CMD"] = "python3"
            env["PYTHONPATH"] = MCP_CORE_PATH
            
            # Configurar variables de entorno para PostgreSQL y Kafka
            # Usar las mismas variables que el dashboard API
            postgres_host = os.getenv("POSTGRES_HOST", "localhost")
            # Si es un socket Unix de Cloud SQL, usarlo salvo que se fuerce IP pública
            use_public_ip = os.getenv("TOKIO_POSTGRES_USE_PUBLIC_IP", "false").lower() == "true"
            if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME")
            
            env["POSTGRES_HOST"] = postgres_host
            env["POSTGRES_HOST_PUBLIC"] = postgres_host  # Asegurar que esté disponible
            env["POSTGRES_PORT"] = os.getenv("POSTGRES_PORT", "5432")
            env["POSTGRES_DB"] = os.getenv("POSTGRES_DB", "soc_ai")
            env["POSTGRES_USER"] = os.getenv("POSTGRES_USER", "soc_user")
            # Asegurar que la contraseña esté disponible
            postgres_password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")
            env["POSTGRES_PASSWORD"] = postgres_password
            logger.info(f"🔧 Configurando PostgreSQL para MCP: {postgres_host}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']} (user: {env['POSTGRES_USER']})")
            env["KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "YOUR_IP_ADDRESS:9093")
            # Asegurar base URL del dashboard para modo HTTP
            env["DASHBOARD_API_BASE_URL"] = os.getenv(
                "DASHBOARD_API_BASE_URL",
                "https://YOUR_DASHBOARD_API_URL"
            )

            # Token para automation tools (si está configurado)
            env["AUTOMATION_API_TOKEN"] = os.getenv("AUTOMATION_API_TOKEN", "")
            if not env["AUTOMATION_API_TOKEN"]:
                logger.warning("⚠️ AUTOMATION_API_TOKEN no configurado; propose_tool puede fallar")
            
            # Log de configuración (sin mostrar password)
            logger.info(f"🔧 PostgreSQL configurado para MCP: {postgres_host}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}")
            
            # Deshabilitar proxy por defecto (a menos que se configure explícitamente)
            env["SOAR_USE_PROXY"] = os.getenv("SOAR_USE_PROXY", "false")
            
            # Debug: verificar que la API key esté en el entorno
            if GEMINI_API_KEY:
                logger.debug(f"🔑 GEMINI_API_KEY disponible (primeros 10 chars: {GEMINI_API_KEY[:10]}...)")
            else:
                logger.error("❌ GEMINI_API_KEY NO está disponible")
            
            # VORTEX 9: Un solo punto de acceso a memoria
            memory = ConversationMemory
            
            # Agregar comando del usuario a memoria (flujo entrada)
            memory.append(session_id, "user", command)
            
            # Obtener historial serializado (vibración 6: eficiencia de transmisión)
            history_json = memory.to_json(session_id)
            
            # Ejecutar MCP host con la API key en el entorno y historial
            # VORTEX 9: Pasar historial como variable de entorno en lugar de flag (más robusto)
            cmd = ["node", mcp_host_script, "chat", "-p", command, "-m", "gemini-2.0-flash", "--mode", mode]
            if history_json:
                # Pasar historial como variable de entorno en lugar de --history (evita problemas con commander)
                env["MCP_CONVERSATION_HISTORY"] = history_json
            
            max_retries = int(os.getenv("MCP_HOST_RETRIES", "2"))
            backoff = float(os.getenv("MCP_HOST_RETRY_BACKOFF", "1.5"))
            result = None
            for attempt in range(max_retries + 1):
                if session_id in _cancel_flags:
                    _cancel_flags.discard(session_id)
                    return {"success": False, "error": "Comando cancelado por el usuario", "output": ""}
                try:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=MCP_HOST_PATH,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    with _process_lock:
                        _running_processes[session_id] = proc
                    try:
                        stdout, stderr = proc.communicate(timeout=120)
                    finally:
                        with _process_lock:
                            _running_processes.pop(session_id, None)
                    result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    with _process_lock:
                        running = _running_processes.pop(session_id, None)
                    if running:
                        running.kill()
                    result = subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="Timeout ejecutando MCP host (120s)")
                if result and result.returncode == 0 and (result.stdout or "").strip():
                    break
                if attempt < max_retries:
                    time.sleep(backoff * (attempt + 1))
            
            # Debug: mostrar stderr si hay problemas
            if result.stderr and ("GEMINI_API_KEY" in result.stderr or "403" in result.stderr or "Forbidden" in result.stderr):
                logger.warning(f"⚠️ Posible problema con API key en stderr: {result.stderr[:200]}")
            
            # Capturar tanto stdout como stderr
            output = result.stdout or ""
            error_output = result.stderr or ""
            
            # Si hay salida en stderr pero no en stdout, puede ser información útil
            if not output and error_output and "Error" not in error_output:
                output = error_output
                error_output = None
            
            # VORTEX 9: Parsear respuesta que incluye historial actualizado
            memory = ConversationMemory
            history_updated = None
            cleaned_output = ""
            
            # Limpiar salidas de debug/verbose del MCP host
            lines = output.split('\n')
            cleaned_lines = []
            skip_response_header = False
            in_response = False
            json_found = False
            
            for line in lines:
                # VORTEX 9: Extraer JSON con historial primero (una sola pasada)
                if not json_found and (line.strip().startswith('{"history":') or line.strip().startswith('{"response":')):
                    try:
                        parsed = json.loads(line)
                        history_updated = parsed.get('history', [])
                        if history_updated:
                            memory._sessions[session_id] = history_updated[-memory._max_history:]
                        # Extraer respuesta del JSON si está disponible
                        if parsed.get('response'):
                            cleaned_lines.append(parsed['response'])
                        json_found = True
                        continue
                    except:
                        pass
                
                # Filtrar líneas de debug/configuración
                skip_patterns = [
                    '🔧 PYTHONPATH', '📝 Procesando prompt', 'Prompt:', 'Modo:', 
                    '✅ GEMINI_API_KEY', '⚠️', '🌀', 'Inicializando MCP Host',
                    'Conectando al servidor MCP', 'Inicializando LLM', 'MCP Host listo',
                    'TOKIO (agent)>', '✅ Conectado al MCP Host'
                ]
                if any(skip in line for skip in skip_patterns):
                    continue
                
                # Detectar inicio de respuesta
                if '✅ Respuesta:' in line:
                    skip_response_header = True
                    in_response = True
                    continue
                
                # Saltar línea vacía después de "✅ Respuesta:"
                if skip_response_header and not line.strip():
                    skip_response_header = False
                    continue
                
                skip_response_header = False
                
                # Mantener líneas con contenido útil
                if line.strip():
                    cleaned_lines.append(line)
            
            cleaned_output = '\n'.join(cleaned_lines).strip()
            
            # Remover duplicados: si hay líneas idénticas consecutivas, mantener solo una
            if cleaned_output:
                final_lines = []
                prev_line = None
                for line in cleaned_output.split('\n'):
                    line_stripped = line.strip()
                    if line_stripped and line_stripped != prev_line:
                        final_lines.append(line)
                        prev_line = line_stripped
                cleaned_output = '\n'.join(final_lines).strip()
            
            # Si no hay salida limpia pero hay error, usar el error
            if not cleaned_output and error_output:
                # Filtrar también el error_output
                error_lines = error_output.split('\n')
                cleaned_error = []
                for line in error_lines:
                    if not any(skip in line for skip in skip_patterns):
                        cleaned_error.append(line)
                if cleaned_error:
                    cleaned_output = '\n'.join(cleaned_error).strip()
            
            if result.returncode == 0:
                if cleaned_output:
                    return {
                        "success": True,
                        "output": cleaned_output,
                        "error": error_output if error_output and "Error" in error_output else None
                    }
                else:
                    return {
                        "success": True,
                        "output": "Comando procesado correctamente. (Sin salida visible)",
                        "error": None
                    }
            else:
                if session_id in _cancel_flags or result.returncode in (-9, -15, 143):
                    _cancel_flags.discard(session_id)
                    return {"success": False, "error": "Comando cancelado por el usuario", "output": ""}
                return {
                    "success": False,
                    "error": error_output or cleaned_output or "Error desconocido",
                    "output": cleaned_output
                }
        finally:
            # Limpiar archivo temporal
            try:
                os.unlink(config_file)
            except:
                pass
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Timeout: El comando tardó más de 120 segundos"
        }
    except Exception as e:
        logger.error(f"Error ejecutando comando MCP: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def mcp_command_endpoint(request: Dict[str, Any] = Body(...)) -> JSONResponse:
    """
    Endpoint para ejecutar comandos del MCP CLI
    """
    command = request.get("command", "").strip()
    mode = request.get("mode", "agent")
    
    session_id = request.get("session_id", "default")
    result = await execute_mcp_command(command, mode, session_id=session_id)
    return JSONResponse(result)


def cancel_mcp_command(session_id: str) -> Dict[str, Any]:
    _cancel_flags.add(session_id)
    with _process_lock:
        proc = _running_processes.get(session_id)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return {"success": True, "message": "Cancel solicitado"}


async def mcp_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint para terminal interactivo con MCP
    """
    await websocket.accept()
    
    try:
        while True:
            # Recibir comando del cliente
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "cancel":
                session_id = message.get("session_id", "default")
                _cancel_flags.add(session_id)
                with _process_lock:
                    proc = _running_processes.get(session_id)
                if proc:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                await websocket.send_text(json.dumps({
                    "type": "result",
                    "success": False,
                    "output": "",
                    "error": "Comando cancelado por el usuario"
                }))
                continue

            command = message.get("command", "").strip()
            mode = message.get("mode", "agent")
            session_id = message.get("session_id", "default")
            
            if not command:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Comando vacío"
                }))
                continue
            
            # Ejecutar comando y enviar resultado
            result = await execute_mcp_command(command, mode, session_id=session_id)
            
            await websocket.send_text(json.dumps({
                "type": "result",
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error")
            }))
    
    except WebSocketDisconnect:
        logger.info("Cliente desconectado del WebSocket MCP")
    except Exception as e:
        logger.error(f"Error en WebSocket MCP: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": str(e)
            }))
        except:
            pass
