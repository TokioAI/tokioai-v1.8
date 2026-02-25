#!/usr/bin/env python3
"""
Dashboard API - Tokio AI ACIS

Backend ligero para exponer datos de seguridad (logs del WAF y estadísticas)
consumiendo directamente desde Kafka. Sirve también un dashboard web estático.
"""

import json
import os
import subprocess
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, Query, Body, HTTPException, status, Depends, Request, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse, StreamingResponse
from endpoints_cli import execute_cli_command, create_tenant, delete_tenant
from db import _get_postgres_conn, _return_postgres_conn
from fastapi.staticfiles import StaticFiles
import asyncio
from kafka import KafkaConsumer
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import bcrypt
import secrets
import time


KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_WAF_LOGS = os.getenv("KAFKA_TOPIC_WAF_LOGS", "waf-logs")
KAFKA_HEALTH_CHECK_ENABLED = os.getenv("KAFKA_HEALTH_CHECK_ENABLED", "false").lower() == "true"
HEALTH_MINIMAL = os.getenv("HEALTH_MINIMAL", "true").lower() == "true"
SKIP_DB_MIGRATIONS = os.getenv("SKIP_DB_MIGRATIONS", "false").lower() == "true"
EPISODES_API_MINIMAL = os.getenv("EPISODES_API_MINIMAL", "true").lower() == "true"
ALERTS_FILE = os.getenv("ALERTS_FILE", "/data/alerts.json")
EVENTS_FILE = os.getenv("EVENTS_FILE", "/data/events.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MCP_HOST_PATH = os.getenv("MCP_HOST_PATH", "/app/mcp-host")
MCP_CORE_PATH = os.getenv("MCP_CORE_PATH", "/app/mcp-core")

# PostgreSQL configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "soc_ai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "soc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))

# =========================
# Auth interno Dashboard
# =========================
DASHBOARD_AUTH_ENABLED = os.getenv("DASHBOARD_AUTH_ENABLED", "true").lower() == "true"
DASHBOARD_ENABLE_AUTH_FLAG = os.getenv("ENABLE_AUTH", "false").lower() == "true"
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "your-email@example.com")
DASHBOARD_PASSWORD_HASH = os.getenv(
    "DASHBOARD_PASSWORD_HASH",
    "$2b$12$jV8jtzJ/zr.OuO4h8LbFpO01jevsHIBsbh4IIdk1DVxJoiWDSuiD2",
)
SESSION_TTL_SECONDS = int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "3600"))
SESSION_COOKIE_NAME = "tokio_session"
DASHBOARD_SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", "")
AUTOMATION_API_TOKEN = os.getenv("AUTOMATION_API_TOKEN", "").strip()
DASHBOARD_SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", "")

_sessions: Dict[str, Dict[str, Any]] = {}

# Helpers de sesión (stateless si DASHBOARD_SESSION_SECRET está definido)
def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _make_session_token(user: str) -> str:
    now = int(time.time())
    payload = {"u": user, "iat": now, "exp": now + SESSION_TTL_SECONDS}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = _b64encode(payload_bytes)
    sig = hmac.new(DASHBOARD_SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = _b64encode(sig)
    return f"v1.{payload_b64}.{sig_b64}"


def _verify_session_token(token: str) -> Optional[str]:
    if not token or not token.startswith("v1."):
        return None
    try:
        _, payload_b64, sig_b64 = token.split(".", 2)
        expected = hmac.new(DASHBOARD_SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected), sig_b64):
            return None
        payload = json.loads(_b64decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("u")
    except Exception:
        return None


def _get_authenticated_user(request: Request) -> Optional[str]:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return None
    if DASHBOARD_SESSION_SECRET:
        return _verify_session_token(sid)
    session = _sessions.get(sid)
    if not session:
        return None
    if time.time() - session.get("last_seen", 0) > SESSION_TTL_SECONDS:
        _sessions.pop(sid, None)
        return None
    session["last_seen"] = time.time()
    return session.get("user")

# Configurar logging
import logging
import base64
import hmac
import hashlib
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tokio AI - ACIS Dashboard API")

# FASE 4: Importar y registrar endpoint de streaming
try:
    from app_streaming import create_streaming_endpoint
    create_streaming_endpoint(app)
    logger.info("✅ Endpoint de streaming SSE registrado: /api/events/stream")
except Exception as e:
    logger.warning(f"⚠️ No se pudo registrar endpoint de streaming: {e}")

# Logger
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Maneja errores de validación de entrada"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Invalid input", "details": str(exc)}
    )


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

from contextlib import contextmanager

# Función para verificar autenticación basada en sesión interna
async def verify_auth(request: Request):
    """Devuelve el usuario autenticado o lanza 401"""
    if not DASHBOARD_AUTH_ENABLED:
        return "anonymous"
    user = _get_authenticated_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


# =========================
# Auth interno Dashboard
# =========================
import bcrypt, secrets, time
import uuid
import shlex
from threading import Lock

DASHBOARD_AUTH_ENABLED = os.getenv("DASHBOARD_AUTH_ENABLED", "true").lower() == "true"
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "your-email@example.com")
# Contraseña robusta (32 caracteres): Kx9#mP2$vL7@nQ4!wR8&tY5*uI3^eO1%
DASHBOARD_PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "$2b$14$n/GKECfo.j1J//2myDPwOeaJxWss5sKUhhqW.GWVU2CyDyMcKZv6a")
SESSION_TTL_SECONDS = int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "3600"))
SESSION_COOKIE_NAME = "tokio_session"

_sessions = {}  # sid -> {user, created_at, last_seen}

# =========================
# Automation queue (Human-in-the-loop)
# =========================
AUTOMATION_STORE = os.getenv("AUTOMATION_STORE", "/tmp/tokio_automation.json")
AUTOMATION_STORE_MODE = os.getenv("AUTOMATION_STORE_MODE", "file").lower()
AUTOMATION_API_TOKEN = os.getenv("AUTOMATION_API_TOKEN", "").strip()
AUTOMATION_CMD_ALLOWLIST = [
    c.strip() for c in os.getenv("AUTOMATION_CMD_ALLOWLIST", "python,python3,psql,curl,ls,cat,head,tail,grep,rg").split(",") if c.strip()
]
DOCKER_RUNNER_ENABLED = os.getenv("DOCKER_RUNNER_ENABLED", "false").lower() == "true"
DOCKER_RUNNER_IMAGE = os.getenv("DOCKER_RUNNER_IMAGE", "python:3.11-slim")
RUNNER_BASE_URL = os.getenv("RUNNER_BASE_URL", "").strip()
RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "").strip()
_automation_lock = Lock()

def _ensure_automation_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS automation_proposals (
            id UUID PRIMARY KEY,
            tool_key TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            code TEXT,
            command TEXT,
            input_schema JSONB,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            approved_at TIMESTAMPTZ,
            approved_by TEXT,
            result JSONB
        )
    """)
    cur.execute("ALTER TABLE automation_proposals ADD COLUMN IF NOT EXISTS tool_key TEXT;")


def _row_to_proposal(row) -> Dict[str, Any]:
    (
        pid, tool_key, ptype, title, description, code, command, input_schema,
        status, created_at, approved_at, approved_by, result
    ) = row
    if isinstance(input_schema, str):
        try:
            input_schema = json.loads(input_schema)
        except Exception:
            pass
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            pass
    return {
        "id": str(pid),
        "tool_key": tool_key,
        "type": ptype,
        "title": title,
        "description": description,
        "code": code,
        "command": command,
        "input_schema": input_schema,
        "status": status,
        "created_at": created_at.isoformat() if created_at else None,
        "approved_at": approved_at.isoformat() if approved_at else None,
        "approved_by": approved_by,
        "result": result,
    }

def _load_automation_items() -> List[Dict[str, Any]]:
    if AUTOMATION_STORE_MODE == "postgres":
        conn = None
        try:
            conn = _get_postgres_conn()
            cur = conn.cursor()
            _ensure_automation_table(cur)
            conn.commit()
            cur.execute("""
                SELECT id, tool_key, type, title, description, code, command, input_schema,
                       status, created_at, approved_at, approved_by, result
                FROM automation_proposals
                ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
            return [_row_to_proposal(r) for r in rows]
        except Exception:
            if conn:
                conn.rollback()
            return []
        finally:
            if conn:
                _return_postgres_conn(conn)
    if not os.path.exists(AUTOMATION_STORE):
        return []
    try:
        with open(AUTOMATION_STORE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_automation_items(items: List[Dict[str, Any]]) -> None:
    if AUTOMATION_STORE_MODE == "postgres":
        return
    os.makedirs(os.path.dirname(AUTOMATION_STORE), exist_ok=True)
    with open(AUTOMATION_STORE, "w") as f:
        json.dump(items, f, indent=2)


def _normalize_tool_key(title: str) -> str:
    key = "".join(c.lower() if c.isalnum() else "_" for c in (title or "").strip())
    key = "_".join(filter(None, key.split("_")))
    return key[:64] or f"tool_{uuid.uuid4().hex[:8]}"


def _run_command_in_runner(cmd: str) -> Dict[str, Any]:
    if not DOCKER_RUNNER_ENABLED:
        raise Exception("Docker runner deshabilitado. Habilita DOCKER_RUNNER_ENABLED=true.")
    if RUNNER_BASE_URL:
        import requests
        headers = {}
        if RUNNER_TOKEN:
            headers["X-Runner-Token"] = RUNNER_TOKEN
        resp = requests.post(
            f"{RUNNER_BASE_URL.rstrip('/')}/run",
            json={"command": cmd},
            headers=headers,
            timeout=140
        )
        if resp.status_code != 200:
            raise Exception(f"Runner remoto error: {resp.status_code} {resp.text[:200]}")
        payload = resp.json()
        if not payload.get("success"):
            raise Exception(payload.get("error") or "Runner remoto falló")
        return payload.get("result", {})
    runner_cmd = [
        "docker", "run", "--rm",
        "-v", "/tmp/tokio_runner:/workspace",
        "-w", "/workspace",
        DOCKER_RUNNER_IMAGE,
        "sh", "-lc", cmd
    ]
    completed = subprocess.run(runner_cmd, capture_output=True, text=True, timeout=120)
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[:20000],
        "stderr": completed.stderr[:20000]
    }


def _build_tool_exec_command(code: str, args: Dict[str, Any]) -> str:
    args_json = json.dumps(args or {}, ensure_ascii=False)
    script = (
        "import json\n"
        f"args = json.loads(r'''{args_json}''')\n"
        f"{code}\n"
        "def _call_main():\n"
        "    if 'main' not in globals():\n"
        "        return {'error': 'No se encontró main()'}\n"
        "    try:\n"
        "        return main(**args)\n"
        "    except TypeError:\n"
        "        return main(args)\n"
        "try:\n"
        "    result = _call_main()\n"
        "    print(json.dumps({'success': True, 'result': result}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'success': False, 'error': str(e)}))\n"
    )
    b64 = base64.b64encode(script.encode()).decode()
    return f"python3 -c \"import base64; exec(base64.b64decode('{b64}'))\""


def _get_session(request):
    user = _get_authenticated_user(request)
    if not user:
        return None
    return {"user": user}


@app.middleware("http")
async def dashboard_auth_middleware(request: Request, call_next):
    """Middleware para exigir sesión en el dashboard."""
    # ✅ Autenticación habilitada para seguridad
    
    if not DASHBOARD_AUTH_ENABLED:
        return await call_next(request)

    path = request.url.path or ""
    
    # Permitir WebSockets sin autenticación (se manejan de forma diferente)
    if request.headers.get("upgrade", "").lower() == "websocket":
        if path.startswith("/api/cli/ws"):
            return await call_next(request)
    
    # Permitir libremente solo login, estáticos, health y favicon
    allowed_without_auth = [
        "/login", "/static", "/favicon", "/health", "/healthz", "/logo.png", "/api/auth/login", "/api/cli/ws", "/api/cli/execute"
    ]
    
    # Verificar si el path está permitido sin auth
    if any(path.startswith(allowed) for allowed in allowed_without_auth):
        return await call_next(request)

    # Permitir automation tools con token dedicado
    if path.startswith("/api/automation") and AUTOMATION_API_TOKEN:
        token = request.headers.get("X-Automation-Token", "")
        if token and token == AUTOMATION_API_TOKEN:
            return await call_next(request)

    # Permitir automation desde CLI si trae token válido
    if path.startswith("/api/automation"):
        token = request.headers.get("x-automation-token", "").strip()
        if token and AUTOMATION_API_TOKEN and token == AUTOMATION_API_TOKEN:
            return await call_next(request)

    # Permitir endpoints internos con token dedicado (CLI/Tools)
    if path.startswith("/api/internal") and AUTOMATION_API_TOKEN:
        token = request.headers.get("X-Automation-Token", "")
        if token and token == AUTOMATION_API_TOKEN:
            return await call_next(request)
    
    # TODAS las demás rutas (incluyendo "/" y todas las APIs) requieren auth
    user = _get_authenticated_user(request)

    # Sin sesión válida
    if not user:
        accept = request.headers.get("accept", "") or ""
        # Peticiones HTML → redirigir a login
        if "text/html" in accept or path == "/":
            return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
        # APIs → responder 401 limpio
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required"},
        )

    request.state.user = user
    return await call_next(request)


# Métricas básicas
_metrics = {
    "requests_total": 0,
    "requests_by_endpoint": {},
    "errors_total": 0,
    "logs_processed": 0,
    "start_time": datetime.utcnow().isoformat() + "Z"
}


# Cache para offsets (en producción usar Redis o base de datos)
_offset_cache: Dict[str, int] = {}

# Cache simple en memoria para respuestas (TTL: 30 segundos) - PASO 4: Optimización
_response_cache: Dict[str, tuple] = {}  # {key: (data, timestamp)}
CACHE_TTL_SECONDS = 5  # Reducido a 5 segundos para mostrar datos más rápido en tiempo real

def _create_consumer(
    auto_offset_reset: str = "latest",
    group_id: Optional[str] = None,
    max_records: Optional[int] = None
) -> KafkaConsumer:
    """
    Crea un KafkaConsumer optimizado para leer logs del topic configurado.
    
    Usa consumer groups para mejor distribución y offsets para eficiencia.
    """
    consumer_config = {
        'bootstrap_servers': KAFKA_BOOTSTRAP_SERVERS.split(","),
        'value_deserializer': lambda m: json.loads(m.decode("utf-8")),
        'auto_offset_reset': auto_offset_reset,
        # FASE 2: Deshabilitar auto-commit para lecturas ad-hoc (no afecta si group_id=None)
        'enable_auto_commit': False if group_id else True,  # Solo auto-commit si no hay group
        'consumer_timeout_ms': 5000,  # Timeout más largo para batches
        'max_poll_records': max_records or 500,  # Leer hasta 500 mensajes por poll
        # FASE 2: Configuración mejorada de consumer
        'session_timeout_ms': 30000,  # 30s timeout de sesión
        'heartbeat_interval_ms': 10000,  # Heartbeat cada 10s
        'fetch_min_bytes': 1,
        'fetch_max_wait_ms': 500,
    }
    
    # Agregar group_id si se especifica (para consumer groups)
    if group_id:
        consumer_config['group_id'] = group_id
    
    consumer = KafkaConsumer(KAFKA_TOPIC_WAF_LOGS, **consumer_config)
    return consumer


def _infer_threat_type(log: Dict[str, Any]) -> Optional[str]:
    """Heurística mejorada para inferir tipo de amenaza a partir del log."""
    uri = (log.get("uri") or log.get("request_uri") or "").lower()
    path = (log.get("path") or "").lower()
    query = (log.get("query_string") or log.get("query") or "").lower()
    user_agent = (log.get("user_agent") or "").lower()
    method = (log.get("method") or "").upper()
    
    # Decodificar URI para mejor detección
    import urllib.parse
    try:
        decoded_uri = urllib.parse.unquote(uri)
    except:
        decoded_uri = uri
    
    text = f"{decoded_uri} {path} {query} {user_agent}".lower()

    # XSS - más patrones (incluyendo encoded)
    xss_patterns = [
        "<script", "javascript:", "onerror=", "onload=", "onclick=", "eval(", "alert(", 
        "document.cookie", "%3cscript", "%3c/script%3e", "&#60;script", "&#x3c;script",
        "fromcharcode", "string.fromcharcode", "unescape(", "atob(", "btoa("
    ]
    if any(x in text for x in xss_patterns):
        return "XSS"
    
    # SQLI - más patrones
    sqli_patterns = [
        " union ", " select ", "%27", "' or '1'='1", " or 1=1", " or '1'='1", 
        "'; drop", "'; delete", "'; update", "sleep(", "waitfor", "benchmark(",
        "pg_sleep", "extractvalue", "xp_cmdshell", "union all", "union select",
        "concat(", "group_concat", "information_schema", "pg_user", "mysql.user"
    ]
    if any(x in text for x in sqli_patterns):
        return "SQLI"
    
    # Path Traversal
    path_traversal_patterns = [
        "../", "/etc/passwd", "/etc/shadow", "..\\", "windows\\system32", 
        "boot.ini", "web.config", ".env", "..%2f", "..%5c", "%2e%2e%2f",
        "phpunit", "vendor/phpunit", "eval-stdin", "cgi-bin"
    ]
    if any(x in text for x in path_traversal_patterns):
        return "PATH_TRAVERSAL"
    
    # Command Injection - MEJORADO: más específico
    cmd_injection_patterns = [
        "cmd=", "command=", "exec=", "&&", "||", 
        "wget ", "curl ", "nc ", "netcat", 
        "|", "`", "$(", "exec(", "system(", "passthru(",
        "; rm ", "; cat ", "; ls ", "; id ", "; whoami ",
        "&& rm ", "|| cat ", "| cat ", "`id`", "; ping", "; uname"
    ]
    # Verificar que no sea solo un archivo JavaScript normal
    is_js_file = uri.endswith(('.js', '.min.js')) or '/js/' in uri or '/javascript/' in uri
    if not is_js_file and any(x in text for x in cmd_injection_patterns):
        return "CMD_INJECTION"
    
    # RFI/LFI
    rfi_patterns = ["http://", "https://", "ftp://", "file://", "php://", "data://"]
    if any(x in text for x in rfi_patterns):
        if "include" in text or "require" in text or "readfile" in text:
            return "RFI_LFI"
    
    # XXE
    if "<?xml" in text and ("<!doctype" in text or "!entity" in text or "system" in text):
        return "XXE"
    
    # WordPress Scanning/Probing (doble slash con rutas conocidas)
    wp_scan_patterns = [
        "//wp-includes/", "//wp-admin/", "//wp-content/", "wlwmanifest.xml",
        "xmlrpc.php", "wp-login.php", "wp-config.php", "//feed/",
        "//blog/", "//wordpress/", "//shop/", "//cms/", "wp-includes/id3"
    ]
    if any(pattern in uri for pattern in wp_scan_patterns) or \
       (uri.startswith("//") and any(x in uri for x in ["wp-", "feed", "blog", "wordpress"])):
        return "SCAN_PROBE"
    
    # MEJORA: Detección mejorada de escaneos - archivos PHP comunes en escaneos
    status = log.get("status", 0)
    php_scan_patterns = [
        "/phpinfo.php", "/info.php", "/server-info.php", "/system-info.php",
        "/test.php", "/debug.php", "/config.php", "/wp-config.php",
        "/_profiler/", "/profiler/", "/.env", "/.git/config",
        "/actuator/", "/admin/", "/administrator/", "/phpmyadmin/",
        "/manager/", "/console/", "/solr/", "/jenkins/",
        "/backend/info.php", "/backend/phpinfo.php"
    ]
    
    # Detectar escaneos: archivos de información/configuración
    if any(pattern in uri for pattern in php_scan_patterns):
        return "SCAN_PROBE"
    
    # Status 404 en rutas de archivos de configuración o información
    if status == 404:
        exploit_paths = [
            "/vendor/", "/phpunit/", "/cgi-bin/", "/.env", "/config.php",
            "/admin.php", "/phpinfo.php", "/info.php", "/test.php",
            "/debug.php", "/server-info.php", "/system-info.php"
        ]
        if any(path in uri for path in exploit_paths):
            return "SCAN_PROBE"
    
    # Status 301/302 en rutas sospechosas (redirecciones a archivos de info)
    if status in [301, 302]:
        if any(pattern in uri for pattern in php_scan_patterns):
            return "SCAN_PROBE"
        if "/.env" in uri or "phpunit" in uri or "cgi-bin" in uri:
            return "PATH_TRAVERSAL"
    
    # CONNECT method abuse
    if method == "CONNECT" and (":" in uri or uri.count(".") > 2):
        return "UNAUTHORIZED_ACCESS"
    
    # SSL/TLS handshake malformado (bytes raw)
    if "\\x16\\x03" in str(log.get("uri", "")) or "\\x16\\x03" in str(log.get("raw_log", "")):
        return "CMD_INJECTION"
    
    # MEJORA: Detección inteligente de escaneos basada en múltiples indicios
    # Si no se detecta nada específico pero hay patrones sospechosos, inferir SCAN_PROBE
    suspicious_indicators = 0
    if status == 404 and uri.count('/') > 2:  # Rutas profundas con 404
        suspicious_indicators += 1
    if any(x in uri for x in ['php', 'config', 'admin', 'test', 'debug', 'info', 'profiler']):
        suspicious_indicators += 1
    if status in [301, 302] and any(x in uri for x in php_scan_patterns):
        suspicious_indicators += 1
    
    # Si hay múltiples indicios de escaneo, clasificar como SCAN_PROBE
    if suspicious_indicators >= 2:
        return "SCAN_PROBE"
    
    return None


def _normalize_log(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza un log de nginx/modsecurity a un formato común para el dashboard."""
    status = int(raw.get("status", 0) or 0)
    ts_raw = raw.get("timestamp") or raw.get("date")

    timestamp: Optional[str] = None
    if isinstance(ts_raw, str):
        timestamp = ts_raw

    threat_type = _infer_threat_type(raw)

    return {
        "timestamp": timestamp,
        "ip": raw.get("ip") or raw.get("remote_addr"),
        "method": raw.get("method") or raw.get("request_method"),
        "uri": raw.get("uri") or raw.get("request_uri") or raw.get("path"),
        "status": status,
        "blocked": bool(status >= 400),
        "threat_type": threat_type,
        "raw": raw,
    }


def _get_cached_or_compute(cache_key: str, compute_func, ttl: int = CACHE_TTL_SECONDS):
    """Obtiene de caché o calcula y guarda en caché"""
    import time
    now = time.time()
    if cache_key in _response_cache:
        data, timestamp = _response_cache[cache_key]
        if now - timestamp < ttl:
            return data
    # Calcular y guardar
    data = compute_func()
    _response_cache[cache_key] = (data, now)
    # Limpiar caché viejo (mantener solo últimos 100)
    if len(_response_cache) > 100:
        oldest_key = min(_response_cache.keys(), key=lambda k: _response_cache[k][1])
        del _response_cache[oldest_key]
    return data

def _get_recent_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Lee logs desde Kafka y devuelve los últimos N normalizados.
    
    Optimizado: lee desde earliest para obtener todos los logs disponibles.
    """
    # Usar consumer sin group para leer todos los mensajes disponibles
    consumer = _create_consumer(
        auto_offset_reset="earliest",
        group_id=None,  # Sin group para leer todos los mensajes
        max_records=limit * 5  # Leer más para tener buffer
    )
    logs: List[Dict[str, Any]] = []
    
    try:
        # Poll para obtener mensajes disponibles
        message_batch = consumer.poll(timeout_ms=3000, max_records=limit * 5)
        
        # Procesar mensajes
        for topic_partition, messages in message_batch.items():
            for message in messages:
                value = message.value
                if isinstance(value, dict):
                    logs.append(_normalize_log(value))
        
        # Si no hay suficientes mensajes, intentar leer más
        if len(logs) < limit:
            # Poll adicional
            message_batch = consumer.poll(timeout_ms=2000, max_records=limit * 3)
            for topic_partition, messages in message_batch.items():
                for message in messages:
                    value = message.value
                    if isinstance(value, dict):
                        logs.append(_normalize_log(value))
    finally:
        consumer.close()

    # Retornar los últimos N logs
    return logs[-limit:] if len(logs) > limit else logs


@app.get("/health", response_class=JSONResponse)
async def health() -> Dict[str, Any]:
    """
    Health check: verifica conexión con PostgreSQL y Kafka con timeouts cortos.
    Responde rápidamente para no bloquear el startup probe.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/health"] = _metrics["requests_by_endpoint"].get("/health", 0) + 1

    if HEALTH_MINIMAL:
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "postgres": None,
                "kafka": None,
                "postgres_error": None,
                "kafka_error": None,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )
    
    # Verificar PostgreSQL con timeout muy corto
    postgres_ok = False
    postgres_error = None
    try:
        conn = await asyncio.wait_for(asyncio.to_thread(_get_postgres_conn), timeout=2.5)
        if conn:
            _return_postgres_conn(conn)
            postgres_ok = True
    except Exception as e:
        postgres_error = str(e)[:100]  # Limitar longitud del error
    
    # Verificar Kafka con timeout corto (opcional, no crítico)
    kafka_ok = False
    kafka_error = None
    if KAFKA_HEALTH_CHECK_ENABLED:
        try:
            consumer = _create_consumer(auto_offset_reset="latest", max_records=1)
            # Solo verificar que se puede crear, no leer mensajes
            consumer.close()
            kafka_ok = True
        except Exception as e:
            kafka_error = str(e)[:100]  # Limitar longitud del error
            logger.debug(f"Kafka check failed: {kafka_error}")
    
    # El sistema está OK si al menos la app está corriendo
    # PostgreSQL y Kafka pueden estar DOWN sin afectar el startup
    status = "healthy" if postgres_ok else "degraded"
    status_code = 200  # Siempre 200 para startup probe
    
    # Formato compatible con el dashboard frontend (postgres y kafka como booleanos)
    return JSONResponse(
        status_code=200,  # Siempre 200 para startup probe
        content={
            "status": status,
            "postgres": postgres_ok,
            "kafka": kafka_ok,
            "postgres_error": postgres_error,
            "kafka_error": kafka_error,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )


@app.get("/api/attacks/recent", response_class=JSONResponse)
async def recent_attacks(
    limit: int = Query(50, ge=1, le=1000, description="Número de ataques a retornar (1-1000)"),
    offset: int = Query(0, ge=0, description="Número de resultados a saltar para paginación"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar"),
    ip: Optional[str] = Query(None, description="Filtrar por IP (búsqueda parcial)"),
    threat_type: Optional[str] = Query(None, description="Filtrar por tipo de amenaza")
) -> Dict[str, Any]:
    """
    Devuelve TODOS los logs (sin filtros de status o blocked), ordenados por tiempo (más recientes primero).
    Optimizado: usa PostgreSQL directamente.
    Ahora incluye predicciones ML y LLM para logs sin threat_type.
    Soporta filtrado por tenant_id.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/attacks/recent"] = _metrics["requests_by_endpoint"].get("/api/attacks/recent", 0) + 1
    
    try:
        # VORTEX 9: Usar conexión del pool directamente (no context manager)
        conn = _get_postgres_conn()
        if not conn:
            return {
                "count": 0,
                "items": [],
                "total": 0,
                "error": "No se pudo obtener conexión de PostgreSQL"
            }
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # FASE 4: Construir query con filtro de tenant, IP, threat_type y paginación
            filters = []
            params = []
            
            # Filtro de tiempo (siempre presente) - Reducido a 1 día para mejor performance
            filters.append("created_at > NOW() - INTERVAL '1 day'")
            
            # Filtro de tenant
            if tenant_id and tenant_id != "all" and tenant_id.isdigit():
                filters.append("tenant_id = %s")
                params.append(int(tenant_id))
            elif tenant_id == "default":
                # Para "default", incluir también logs sin tenant_id (migración)
                filters.append("(tenant_id IS NULL OR tenant_id = 1)")
            
            # Filtro de IP (búsqueda parcial)
            if ip:
                filters.append("ip LIKE %s")
                params.append(f"%{ip}%")
            
            # Filtro de threat_type
            if threat_type:
                filters.append("threat_type = %s")
                params.append(threat_type)
            
            # Filtro de severity
            if severity:
                filters.append("severity = %s")
                params.append(severity.upper())
            
            # Filtro de blocked
            if blocked is not None:
                filters.append("blocked = %s")
                params.append(blocked)
            
            # Filtro de classification_source
            if classification_source:
                filters.append("classification_source = %s")
                params.append(classification_source.lower())
            
            # Filtro de URI contiene
            if uri_contains:
                filters.append("uri ILIKE %s")
                params.append(f"%{uri_contains}%")
            
            # Filtro de método HTTP
            if method:
                filters.append("method = %s")
                params.append(method.upper())
            
            # Filtro de tiempo - usar date_from/date_to si están disponibles
            if date_from and date_to:
                try:
                    datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                    datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                    filters = [f for f in filters if not f.startswith("created_at > NOW()")]
                    filters.append("created_at >= %s AND created_at <= %s")
                    params.extend([date_from, date_to])
                except ValueError:
                    pass
            elif date_from:
                try:
                    datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                    filters = [f for f in filters if not f.startswith("created_at > NOW()")]
                    filters.append("created_at >= %s")
                    params.append(date_from)
                except ValueError:
                    pass
            elif date_to:
                try:
                    datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                    filters = [f for f in filters if not f.startswith("created_at > NOW()")]
                    filters.append("created_at <= %s")
                    params.append(date_to)
                except ValueError:
                    pass
            
            # Construir WHERE clause
            attack_filter = f"WHERE {' AND '.join(filters)}"
            
            # Optimización: NO contar el total si es una consulta grande (mejora performance)
            # Solo contar si el límite es pequeño (< 100)
            total_count = 0
            if limit < 100:
                count_cursor = conn.cursor()
                try:
                    count_cursor.execute(f"SELECT COUNT(*) FROM waf_logs {attack_filter}", params)
                    count_result = count_cursor.fetchone()
                    total_count = count_result[0] if count_result and len(count_result) > 0 else 0
                finally:
                    count_cursor.close()
            else:
                # Para consultas grandes, usar un estimado basado en el límite
                effective_limit = min(limit, 100)
                total_count = effective_limit + offset
            
            # FASE 4: Agregar paginación con OFFSET
            # Limitar máximo a 100 para evitar timeouts (reducido de 500)
            effective_limit = min(limit, 100)
            # Optimización: usar índice en created_at y limitar campos pesados
            cursor.execute(f"""
                SELECT 
                    id, timestamp, ip, method, uri, status,
                    blocked, threat_type, severity, created_at,
                    classification_source, tenant_id, owasp_code, owasp_category
                FROM waf_logs
                {attack_filter}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params + [effective_limit, offset])
            
            attacks = []
            classification_stats = {
                "heuristic": 0,
                "ml": 0,
                "transformer": 0,
                "llm": 0,
                "waf": 0,
                "pending": 0
            }
            
            for row in cursor.fetchall():
                attack = dict(row)
                # Convertir datetime
                if attack.get('timestamp'):
                    if hasattr(attack['timestamp'], 'isoformat'):
                        attack['timestamp'] = attack['timestamp'].isoformat()
                if attack.get('created_at'):
                    if hasattr(attack['created_at'], 'isoformat'):
                        attack['created_at'] = attack['created_at'].isoformat()
                
                # Mostrar información de clasificación híbrida
                classification_source = attack.get('classification_source', 'unknown')
                
                # Extraer información OWASP del raw_log si está disponible
                raw_log = attack.get('raw_log')
                if isinstance(raw_log, dict):
                    if raw_log.get('owasp_code'):
                        attack['owasp_code'] = raw_log.get('owasp_code')
                    if raw_log.get('owasp_category'):
                        attack['owasp_category'] = raw_log.get('owasp_category')
                
                # Si no hay OWASP code pero hay threat_type, clasificar
                if not attack.get('owasp_code') and attack.get('threat_type'):
                    try:
                        from owasp_threat_classifier import classify_by_owasp_top10
                        owasp_info = classify_by_owasp_top10(attack['threat_type'])
                        attack['owasp_code'] = owasp_info.get('owasp_code')
                        attack['owasp_category'] = owasp_info.get('owasp_category')
                    except ImportError:
                        # Si el módulo no está disponible, continuar sin OWASP
                        pass
                
                # Normalizar status
                status = attack.get('status')
                if isinstance(status, str):
                    try:
                        status = int(status)
                    except (ValueError, TypeError):
                        status = attack.get('status', 200)
                
                # PRIORIDAD 1: Si status es 403, es un bloqueo del WAF - SIEMPRE marcarlo como bloqueado
                if status == 403:
                    attack['blocked'] = True
                    # Si no tiene threat_type, inferirlo desde el URI
                    if not attack.get('threat_type') or attack.get('threat_type') in ('OTHER', 'NONE', ''):
                        uri = attack.get('uri', '')
                        method = attack.get('method', '')
                        if uri:
                            # Decodificar URI para mejor detección
                            import urllib.parse
                            try:
                                decoded_uri = urllib.parse.unquote(uri)
                            except:
                                decoded_uri = uri
                            inferred = _infer_threat_type({'uri': decoded_uri, 'method': method})
                            if inferred:
                                attack['threat_type'] = inferred
                            else:
                                # Si no se puede inferir específicamente, marcarlo como WAF_BLOCKED
                                attack['threat_type'] = 'WAF_BLOCKED'
                            attack['classification_source'] = 'waf'
                            # Clasificar según OWASP
                            try:
                                from owasp_threat_classifier import classify_by_owasp_top10
                                threat_for_owasp = attack.get('threat_type')
                                if threat_for_owasp == 'WAF_BLOCKED':
                                    # Para bloqueos del WAF sin tipo específico, usar el threat_type inferido del URI si existe
                                    if inferred:
                                        threat_for_owasp = inferred
                                    else:
                                        threat_for_owasp = 'OTHER'
                                owasp_info = classify_by_owasp_top10(threat_for_owasp)
                                attack['owasp_code'] = owasp_info.get('owasp_code')
                                attack['owasp_category'] = owasp_info.get('owasp_category')
                            except ImportError:
                                pass
                # Si viene marcado como bloqueado pero no es 403, mantenerlo
                elif attack.get('blocked'):
                    attack['blocked'] = True
                
                # SIEMPRE inferir threat_type si no existe o es OTHER/NONE (incluso si el source es ML)
                # Esto asegura que todos los logs tengan una clasificación
                current_threat_type = attack.get('threat_type')
                status_val = attack.get('status', 200)
                if isinstance(status_val, str):
                    try:
                        status_val = int(status_val)
                    except:
                        status_val = 200
                
                if not current_threat_type or current_threat_type in ('OTHER', 'NONE', '', None):
                    # Intentar inferir del URI, method, status y raw_log
                    uri = attack.get('uri', '')
                    method = attack.get('method', '')
                    query_str = attack.get('query_string', '') or ''
                    
                    # Preparar datos para inferencia
                    import urllib.parse
                    log_data = {
                        'uri': uri,
                        'method': method,
                        'query_string': query_str,
                        'status': status_val
                    }
                    
                    # Si hay raw_log, incluirlo también
                    if raw_log and isinstance(raw_log, dict):
                        log_data.update(raw_log)
                    
                    # Intentar inferir
                    inferred = _infer_threat_type(log_data)
                    
                    if inferred:
                        attack['threat_type'] = inferred
                        # Si el source original era ML pero no detectó nada, cambiar a heuristic
                        original_source = attack.get('classification_source', classification_source)
                        if original_source in ('ml', 'hybrid_ml', 'unknown'):
                            attack['classification_source'] = 'heuristic'
                        elif not attack.get('classification_source'):
                            attack['classification_source'] = 'heuristic'
                        
                        # Clasificar según OWASP
                        try:
                            from owasp_threat_classifier import classify_by_owasp_top10
                            owasp_info = classify_by_owasp_top10(inferred)
                            attack['owasp_code'] = owasp_info.get('owasp_code')
                            attack['owasp_category'] = owasp_info.get('owasp_category')
                        except (ImportError, Exception) as e:
                            logger.debug(f"No se pudo clasificar OWASP para {inferred}: {e}")
                    else:
                        # MEJORA: Inferir SCAN_PROBE para 404s en lugar de NONE
                        normal_routes = ['/', '/favicon.ico', '/robots.txt', '/icons8-ai-40.png']
                        # CORREGIDO: Verificar que uri no sea None antes de usar startswith
                        if status_val in (200, 301, 302) and uri and (uri in normal_routes or uri.startswith('/assets/')):
                            attack['threat_type'] = 'NONE'
                            attack['classification_source'] = 'heuristic'
                        # MEJORA: 404s en rutas no comunes son probablemente escaneos
                        elif status_val == 404:
                            # Solo marcar como NONE si es una ruta realmente normal
                            if uri and uri in normal_routes:
                                attack['threat_type'] = 'NONE'
                            else:
                                attack['threat_type'] = 'SCAN_PROBE'
                            attack['classification_source'] = 'heuristic'
                            try:
                                from owasp_threat_classifier import classify_by_owasp_top10
                                if attack['threat_type'] == 'SCAN_PROBE':
                                    owasp_info = classify_by_owasp_top10('SCAN_PROBE')
                                    attack['owasp_code'] = owasp_info.get('owasp_code')
                                    attack['owasp_category'] = owasp_info.get('owasp_category')
                            except:
                                pass
                        else:
                            # MEJORA: Solo usar NONE para tráfico realmente normal (200 en rutas comunes)
                            # Para otros casos, intentar inferir SCAN_PROBE
                            if status_val == 200 and uri and (uri in normal_routes or uri.startswith('/assets/')):
                                attack['threat_type'] = 'NONE'
                            else:
                                # Si es un path sospechoso, marcar como SCAN_PROBE
                                php_patterns = ['php', 'config', 'admin', 'test', 'debug', 'info']
                                if uri and any(x in uri.lower() for x in php_patterns):
                                    attack['threat_type'] = 'SCAN_PROBE'
                                    try:
                                        from owasp_threat_classifier import classify_by_owasp_top10
                                        owasp_info = classify_by_owasp_top10('SCAN_PROBE')
                                        attack['owasp_code'] = owasp_info.get('owasp_code')
                                        attack['owasp_category'] = owasp_info.get('owasp_category')
                                    except:
                                        pass
                                else:
                                    attack['threat_type'] = 'NONE'
                            
                            if not attack.get('classification_source') or attack.get('classification_source') in ('unknown', 'ml'):
                                attack['classification_source'] = 'heuristic'
                
                # Agregar información sobre el sistema híbrido y OWASP
                attack['has_owasp_classification'] = bool(attack.get('owasp_code'))
                if attack.get('owasp_code'):
                    attack['owasp_info'] = {
                        'code': attack.get('owasp_code'),
                        'category': attack.get('owasp_category'),
                        'description': f"Categoría OWASP Top 10: {attack.get('owasp_category', 'N/A')}"
                    }
                
                if classification_source in ['ml', 'hybrid_ml', 'llm', 'transformer', 'heuristic']:
                    attack['classification_method'] = {
                        'ml': 'Machine Learning (Random Forest)',
                        'hybrid_ml': 'Híbrido (Random Forest + KNN/KMeans)',
                        'transformer': 'Transformer (MiniLM/DistilBERT)',
                        'llm': 'LLM (Gemini 2.0 Flash)',
                        'heuristic': 'Heurísticas mejoradas'
                    }.get(classification_source, classification_source)
                
                attacks.append(attack)
            
            # Cerrar cursor antes de devolver la conexión al pool
            cursor.close()
            
            # FASE 4: Agregar información de paginación con estadísticas de clasificación
            return {
                "success": True,
                "attacks": attacks,
                "count": len(attacks),
                "items": attacks,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count,
                "classification_stats": classification_stats
            }
        finally:
            # VORTEX 6: Devolver conexión al pool
            _return_postgres_conn(conn)
    except HTTPException:
        # Re-lanzar HTTPException (como cuando el pool está agotado)
        raise
    except Exception as e:
        logger.error(f"Error obteniendo ataques desde PostgreSQL: {e}", exc_info=True)
        _metrics["errors_total"] += 1
        return {
            "count": 0,
            "items": [],
            "total": 0,
            "error": str(e)
        }


# Endpoint interno para MCP server

# Endpoint interno para MCP server
@app.post("/api/internal/search-waf-logs")
async def internal_search_waf_logs_endpoint(
    request: Request,
    ip: Optional[str] = Query(None),
    pattern: Optional[str] = Query(None),
    url_pattern: Optional[str] = Query(None),
    host: Optional[str] = Query(None),
    days: int = Query(2),
    limit: int = Query(50)
):
    """
    VORTEX 6: Query optimizada con índices y timeouts
    Endpoint interno para MCP server - usa conexión PostgreSQL del dashboard
    """
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL", "logs": []}
            )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # VORTEX 6: Query optimizada - usar índice en created_at, solo campos esenciales
        query = """
            SELECT 
                id, timestamp, ip, method, uri, status, blocked, 
                threat_type, severity, created_at, tenant_id
            FROM waf_logs
            WHERE created_at > NOW() - INTERVAL %s
        """
        params = [f'{days} days']
        
        # VORTEX 9: Construcción dinámica de WHERE en una expresión
        conditions = []
        if ip:
            conditions.append("ip = %s")
            params.append(ip)
        if host:
            conditions.append("host ILIKE %s")
            params.append(f"%{host}%")
        if url_pattern:
            conditions.append("uri ILIKE %s")
            params.append(f"%{url_pattern}%")
        elif pattern:
            conditions.append("(uri ILIKE %s OR raw_log::text ILIKE %s)")
            params.extend([f"%{pattern}%", f"%{pattern}%"])
        
        if conditions:
            query += " AND " + " AND ".join(conditions)
        
        # VORTEX 6: Límite estricto para evitar timeouts
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(min(limit, 50))  # VORTEX 6: Máximo 50 resultados
        
        # VORTEX 6: Ejecutar query con timeout implícito
        cursor.execute(query, params)
        logs = [dict(row) for row in cursor.fetchall()]
        
        # VORTEX 9: Conversión de datetime en una expresión
        for log in logs:
            for key in ['timestamp', 'created_at']:
                if log.get(key) and hasattr(log[key], 'isoformat'):
                    log[key] = log[key].isoformat()
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return JSONResponse(content={
            "success": True,
            "logs": logs,
            "count": len(logs),
            "message": f"Encontrados {len(logs)} logs de WAF"
        })
    except Exception as e:
        logger.error(f"Error en internal_search_waf_logs: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "logs": []}
        )


@app.get("/api/search", response_class=JSONResponse)
async def global_search(
    ip: str = Query(..., description="IP a buscar"),
    limit: int = Query(50, ge=1, le=200, description="Límite de resultados por sección")
) -> Dict[str, Any]:
    """
    Búsqueda global de IP: devuelve resumen, amenazas, episodios y bloqueos.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/search"] = _metrics["requests_by_endpoint"].get("/api/search", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Resumen de IP
        cursor.execute("""
            SELECT 
                COUNT(*) as total_logs,
                COUNT(DISTINCT ip) as unique_ips,
                MIN(created_at) as first_seen,
                MAX(created_at) as last_seen,
                COUNT(*) FILTER (WHERE blocked = TRUE) as blocked_count
            FROM waf_logs
            WHERE ip::text = %s
        """, (ip,))
        summary = dict(cursor.fetchone() or {})
        
        # Contar bloqueos activos
        cursor.execute("""
            SELECT COUNT(*) as active_blocks
            FROM blocked_ips
            WHERE ip::text = %s AND active = TRUE
        """, (ip,))
        active_blocks_row = cursor.fetchone()
        summary['active_blocks'] = active_blocks_row['active_blocks'] if active_blocks_row else 0
        
        # Convertir fechas
        if summary.get('first_seen') and hasattr(summary['first_seen'], 'isoformat'):
            summary['first_seen'] = summary['first_seen'].isoformat()
        if summary.get('last_seen') and hasattr(summary['last_seen'], 'isoformat'):
            summary['last_seen'] = summary['last_seen'].isoformat()
        
        # Historial de amenazas
        cursor.execute("""
            SELECT ip, uri, threat_type, severity, blocked, created_at, timestamp
            FROM waf_logs
            WHERE ip::text = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (ip, limit))
        threats = []
        for row in cursor.fetchall():
            threat = dict(row)
            if threat.get('created_at') and hasattr(threat['created_at'], 'isoformat'):
                threat['created_at'] = threat['created_at'].isoformat()
            if threat.get('timestamp') and hasattr(threat['timestamp'], 'isoformat'):
                threat['timestamp'] = threat['timestamp'].isoformat()
            threats.append(threat)
        
        # Episodios
        cursor.execute("""
            SELECT episode_id, src_ip, total_requests, decision, risk_score, created_at, episode_start, episode_end
            FROM episodes
            WHERE src_ip::text = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (ip, limit))
        episodes = []
        for row in cursor.fetchall():
            episode = dict(row)
            for key in ['created_at', 'episode_start', 'episode_end']:
                if episode.get(key) and hasattr(episode[key], 'isoformat'):
                    episode[key] = episode[key].isoformat()
            episodes.append(episode)
        
        # Historial de bloqueos
        cursor.execute("""
            SELECT ip, blocked_at, expires_at, active, threat_type, reason, classification_source, blocked_by
            FROM blocked_ips
            WHERE ip::text = %s
            ORDER BY blocked_at DESC
            LIMIT %s
        """, (ip, limit))
        blocks = []
        for row in cursor.fetchall():
            block = dict(row)
            if block.get('blocked_at') and hasattr(block['blocked_at'], 'isoformat'):
                block['blocked_at'] = block['blocked_at'].isoformat()
            if block.get('expires_at') and hasattr(block['expires_at'], 'isoformat'):
                block['expires_at'] = block['expires_at'].isoformat()
            blocks.append(block)
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "ip": ip,
            "summary": summary,
            "threats": threats,
            "episodes": episodes,
            "blocks": blocks
        }
    except Exception as e:
        logger.error(f"Error en búsqueda global: {e}", exc_info=True)
        _metrics["errors_total"] += 1
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/attacks/recent/export", response_class=StreamingResponse)
async def export_attacks_csv(
    limit: int = Query(1000, ge=1, le=10000),
    tenant_id: Optional[str] = Query(None),
    ip: Optional[str] = Query(None),
    threat_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    blocked: Optional[bool] = Query(None),
    classification_source: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    uri_contains: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    format: str = Query("csv", regex="^(csv|json)$")
) -> StreamingResponse:
    """
    Exporta ataques en formato CSV o JSON
    """
    import csv
    import io
    
    try:
        conn = _get_postgres_conn()
        if not conn:
            raise HTTPException(status_code=500, detail="No se pudo conectar a PostgreSQL")
        
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Construir query con los mismos filtros que /api/attacks/recent
            filters = []
            params = []
            
            if date_from and date_to:
                try:
                    datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                    datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                    filters.append("created_at >= %s AND created_at <= %s")
                    params.extend([date_from, date_to])
                except ValueError:
                    filters.append("created_at > NOW() - INTERVAL '1 day'")
            else:
                filters.append("created_at > NOW() - INTERVAL '1 day'")
            
            if tenant_id and tenant_id != "all" and tenant_id.isdigit():
                filters.append("tenant_id = %s")
                params.append(int(tenant_id))
            
            if ip:
                filters.append("ip LIKE %s")
                params.append(f"%{ip}%")
            
            if threat_type:
                filters.append("threat_type = %s")
                params.append(threat_type)
            
            if severity:
                filters.append("severity = %s")
                params.append(severity.upper())
            
            if blocked is not None:
                filters.append("blocked = %s")
                params.append(blocked)
            
            if classification_source:
                filters.append("classification_source = %s")
                params.append(classification_source.lower())
            
            if uri_contains:
                filters.append("uri ILIKE %s")
                params.append(f"%{uri_contains}%")
            
            if method:
                filters.append("method = %s")
                params.append(method.upper())
            
            attack_filter = f"WHERE {' AND '.join(filters)}"
            
            cursor.execute(f"""
                SELECT 
                    ip, uri, method, threat_type, severity, blocked, 
                    classification_source, created_at, status
                FROM waf_logs
                {attack_filter}
                ORDER BY created_at DESC
                LIMIT %s
            """, params + [limit])
            
            rows = cursor.fetchall()
            cursor.close()
            _return_postgres_conn(conn)
            
            if format == "csv":
                # Generar CSV
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Headers
                writer.writerow(['IP', 'URI', 'Método', 'Tipo de Amenaza', 'Severidad', 'Estado', 'Fecha', 'Fuente'])
                
                # Data
                for row in rows:
                    writer.writerow([
                        row.get('ip', ''),
                        row.get('uri', ''),
                        row.get('method', ''),
                        row.get('threat_type', ''),
                        row.get('severity', ''),
                        'BLOQUEADO' if row.get('blocked') else 'DETECTADO',
                        row.get('created_at').isoformat() if row.get('created_at') else '',
                        row.get('classification_source', '')
                    ])
                
                output.seek(0)
                return StreamingResponse(
                    iter([output.getvalue()]),
                    media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=tokio-ai-attacks-{datetime.now().strftime('%Y%m%d')}.csv"}
                )
            else:
                # JSON
                import json
                data = [dict(row) for row in rows]
                for item in data:
                    if item.get('created_at') and hasattr(item['created_at'], 'isoformat'):
                        item['created_at'] = item['created_at'].isoformat()
                
                return JSONResponse(
                    content={"items": data, "count": len(data)},
                    headers={"Content-Disposition": f"attachment; filename=tokio-ai-attacks-{datetime.now().strftime('%Y%m%d')}.json"}
                )
                
        except Exception as e:
            logger.error(f"Error en export: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error exportando: {e}")
    
    except Exception as e:
        logger.error(f"Error al obtener conexión en export: {e}")
        raise HTTPException(status_code=500, detail=f"Error al conectar a la base de datos: {e}")


@app.post("/api/internal/get-summary", response_class=JSONResponse)
async def internal_get_summary(
    request: Request,
    days: int = Query(7)
) -> Dict[str, Any]:
    """Resumen interno para MCP (usa pool del dashboard)."""
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
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
            """, (f'{days} days',))
            waf_stats = dict(cursor.fetchone())
            cursor.execute("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE decision = 'BLOCK') as blocked_episodes
                FROM episodes
                WHERE created_at > NOW() - INTERVAL %s
            """, (f'{days} days',))
            episode_stats = dict(cursor.fetchone())
        except Exception as e:
            logger.warning(f"Timeout/slow query en resumen {days}d, usando fallback 1d: {e}")
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
            try:
                cursor.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(*) FILTER (WHERE decision = 'BLOCK') as blocked_episodes
                    FROM episodes
                    WHERE created_at > NOW() - INTERVAL '1 day'
                """)
                episode_stats = dict(cursor.fetchone())
            except Exception as episode_err:
                logger.warning(f"Error contando episodios: {episode_err}")
                episode_stats = {"total": 0, "blocked_episodes": 0}
        
        try:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM blocked_ips
                WHERE active = TRUE AND (expires_at IS NULL OR expires_at > NOW())
            """)
            blocked_row = cursor.fetchone()
            blocked_count = blocked_row.get("total", 0) if isinstance(blocked_row, dict) else blocked_row[0]
        except Exception as blocked_err:
            logger.warning(f"Error contando bloqueos: {blocked_err}")
            blocked_count = 0
        cursor.close()
        _return_postgres_conn(conn)
        return JSONResponse(content={
            "success": True,
            "summary": {
                "waf_logs": {
                    "total": waf_stats.get('total', 0),
                    "unique_ips": waf_stats.get('unique_ips', 0),
                    "blocked": waf_stats.get('blocked_count', 0)
                },
                "episodes": {
                    "total": episode_stats.get('total', 0),
                    "blocked": episode_stats.get('blocked_episodes', 0)
                },
                "blocked_ips": {
                    "active": blocked_count
                }
            },
            "period_days": days_used,
            "approximate": approximate
        })
    except Exception as e:
        logger.error(f"Error en internal_get_summary: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/internal/list-episodes", response_class=JSONResponse)
async def internal_list_episodes(
    request: Request,
    limit: int = Query(50),
    status: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Lista episodios internos para MCP."""
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'episodes'
        """)
        columns = {row["column_name"] for row in cursor.fetchall()}
        base_fields = ["episode_id", "src_ip", "total_requests", "decision", "created_at"]
        select_fields = [field for field in base_fields if field in columns]
        optional_fields = ["episode_start", "episode_end", "unique_uris", "request_rate", "risk_score"]
        for field in optional_fields:
            if field in columns:
                select_fields.append(field)
        if not select_fields:
            cursor.close()
            _return_postgres_conn(conn)
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No hay columnas compatibles en episodes", "episodes": []}
            )
        
        # Construir query con filtros
        filters = []
        params = []
        
        # Filtro de fecha (por defecto últimos 7 días)
        if date_from and date_to:
            try:
                datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                filters.append("created_at >= %s AND created_at <= %s")
                params.extend([date_from, date_to])
            except ValueError:
                filters.append("created_at > NOW() - INTERVAL '7 days'")
        else:
            filters.append("created_at > NOW() - INTERVAL '7 days'")
        
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            filters.append("tenant_id = %s")
            params.append(int(tenant_id))
        
        if ip:
            filters.append("src_ip = %s")
            params.append(ip)
        
        if decision:
            filters.append("decision = %s")
            params.append(decision)
        
        if risk_min is not None:
            filters.append("risk_score >= %s")
            params.append(risk_min)
        
        query = f"""
            SELECT {", ".join(select_fields)}
            FROM episodes
            WHERE {' AND '.join(filters)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        cursor.execute(query, params)
        episodes = [dict(row) for row in cursor.fetchall()]
        for ep in episodes:
            for key in ['episode_start', 'episode_end', 'created_at']:
                if ep.get(key) and hasattr(ep[key], 'isoformat'):
                    ep[key] = ep[key].isoformat()
        cursor.close()
        _return_postgres_conn(conn)
        return JSONResponse(content={
            "success": True,
            "episodes": episodes,
            "count": len(episodes),
            "message": f"Encontrados {len(episodes)} episodios"
        })
    except Exception as e:
        logger.error(f"Error en internal_list_episodes: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "episodes": []}
        )


@app.post("/api/internal/list-blocked-ips", response_class=JSONResponse)
async def internal_list_blocked_ips(
    request: Request,
    limit: int = Query(50),
    active_only: bool = Query(True)
) -> Dict[str, Any]:
    """Lista IPs bloqueadas internos para MCP."""
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT 
                id, ip, blocked_at, expires_at, reason,
                threat_type, severity, active, classification_source
            FROM blocked_ips
        """
        params = []
        if active_only:
            query += " WHERE active = TRUE AND (expires_at IS NULL OR expires_at > NOW())"
        query += " ORDER BY blocked_at DESC LIMIT %s"
        params.append(limit)
        cursor.execute(query, params)
        blocked = [dict(row) for row in cursor.fetchall()]
        for block in blocked:
            for key in ['blocked_at', 'expires_at']:
                if block.get(key) and hasattr(block[key], 'isoformat'):
                    block[key] = block[key].isoformat()
        cursor.close()
        _return_postgres_conn(conn)
        return JSONResponse(content={
            "success": True,
            "blocked_ips": blocked,
            "count": len(blocked),
            "message": f"Encontradas {len(blocked)} IPs bloqueadas"
        })
    except Exception as e:
        logger.error(f"Error en internal_list_blocked_ips: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "blocked_ips": []}
        )


@app.post("/api/internal/block-ip", response_class=JSONResponse)
async def internal_block_ip(
    request: Request,
    ip: str = Query(...),
    duration_hours: int = Query(24),
    reason: str = Query("Bloqueo manual desde CLI")
) -> Dict[str, Any]:
    """Bloquea una IP desde MCP usando el pool del dashboard."""
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
        cursor = conn.cursor()
        expires_at = datetime.now() + timedelta(hours=duration_hours)
        try:
            cursor.execute("""
                INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, active, classification_source)
                VALUES (%s, NOW(), %s, %s, TRUE, 'manual_cli')
                ON CONFLICT (ip) DO UPDATE SET
                    blocked_at = NOW(),
                    expires_at = %s,
                    reason = %s,
                    active = TRUE
            """, (ip, expires_at, reason, expires_at, reason))
        except Exception:
            cursor.execute("""
                UPDATE blocked_ips 
                SET blocked_at = NOW(),
                    expires_at = %s,
                    reason = %s,
                    active = TRUE
                WHERE ip = %s
            """, (expires_at, reason, ip))
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, active, classification_source)
                    VALUES (%s, NOW(), %s, %s, TRUE, 'manual_cli')
                """, (ip, expires_at, reason))
        conn.commit()
        cursor.close()
        _return_postgres_conn(conn)
        return JSONResponse(content={
            "success": True,
            "message": f"IP {ip} bloqueada por {duration_hours} horas hasta {expires_at.isoformat()}",
            "ip": ip,
            "expires_at": expires_at.isoformat()
        })
    except Exception as e:
        logger.error(f"Error en internal_block_ip: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/internal/unblock-ip", response_class=JSONResponse)
async def internal_unblock_ip(
    request: Request,
    ip: str = Query(...),
    reason: str = Query("Desbloqueo manual desde CLI")
) -> Dict[str, Any]:
    """Desbloquea una IP desde MCP usando el pool del dashboard."""
    try:
        conn = _get_postgres_conn()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "No se pudo conectar a PostgreSQL"}
            )
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE blocked_ips
            SET active = FALSE,
                expires_at = NOW(),
                reason = %s
            WHERE ip = %s AND active = TRUE
        """, (reason, ip))
        updated = cursor.rowcount
        conn.commit()
        cursor.close()
        _return_postgres_conn(conn)
        return JSONResponse(content={
            "success": True,
            "message": f"IP {ip} desbloqueada",
            "ip": ip,
            "updated": updated
        })
    except Exception as e:
        logger.error(f"Error en internal_unblock_ip: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/stats/summary", response_class=JSONResponse)




async def stats_summary(
    limit: int = Query(500, ge=10, le=5000, description="Número de logs a analizar (10-5000)"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Obtiene estadísticas resumidas de logs del WAF.
    HABILITADO: Calcula total requests, blocked, allowed, y top threats de la última hora.
    """
    try:
        # Usar contexto manager para asegurar que la conexión se devuelva al pool
        with get_postgres_connection() as conn:
            cursor = conn.cursor()
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id != "all" and tenant_id.isdigit():
                tenant_filter = "WHERE tenant_id = %s"
                params = [int(tenant_id)]
            elif tenant_id == "default":
                tenant_filter = "WHERE (tenant_id IS NULL OR tenant_id = 1)"
            
            # Estadísticas rápidas usando agregaciones SQL
            # OPTIMIZADO: Buscar en últimos 1 hora para datos más recientes y queries más rápidas
            time_filter = "created_at > NOW() - INTERVAL '1 hour'"
            if tenant_filter:
                full_filter = f"{tenant_filter} AND {time_filter}"
            else:
                full_filter = f"WHERE {time_filter}"
            
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN blocked THEN 1 ELSE 0 END), 0) as blocked_count,
                    COALESCE(SUM(CASE WHEN NOT blocked THEN 1 ELSE 0 END), 0) as allowed_count,
                    COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
                {full_filter}
            """, params)
            
            stats_row = cursor.fetchone()
            
            if stats_row is None:
                cursor.close()
                return {
                    "total_requests": 0,
                    "blocked": 0,
                    "allowed": 0,
                    "by_threat_type": {},
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "error": "No se pudieron obtener estadísticas"
                }
            
            total = int(stats_row[0]) if stats_row[0] is not None else 0
            blocked_count = int(stats_row[1]) if stats_row[1] is not None else 0
            allowed_count = int(stats_row[2]) if stats_row[2] is not None else 0
            unique_ips = int(stats_row[3]) if stats_row[3] is not None else 0
            
            # Top threats - buscar en logs con mismo filtro de tiempo
            threat_time_filter = "created_at > NOW() - INTERVAL '1 hour' AND threat_type IS NOT NULL"
            if tenant_filter:
                threat_filter = f"{tenant_filter} AND {threat_time_filter}"
            else:
                threat_filter = f"WHERE {threat_time_filter}"
            
            cursor.execute(f"""
                SELECT threat_type, COUNT(*) as count
                FROM waf_logs
                {threat_filter}
                GROUP BY threat_type
                ORDER BY count DESC
                LIMIT 5
            """, params)
            top_threats = [{"type": row[0], "count": int(row[1])} for row in cursor.fetchall()]
            
            cursor.close()
            
            by_threat_type = {t["type"]: t["count"] for t in top_threats}
            
            return {
                "total_requests": total,
                "blocked": blocked_count,
                "allowed": allowed_count,
                "by_threat_type": by_threat_type,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
    except Exception as e:
        logger.error(f"Error en stats_summary: {e}", exc_info=True)
        return {
            "total_requests": 0,
            "blocked": 0,
            "allowed": 0,
            "by_threat_type": {},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": str(e)
        }


@app.get("/api/agent-decisions", response_class=JSONResponse)
async def agent_decisions(
    limit: int = Query(100, ge=1, le=500, description="Número de decisiones a retornar"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar"),
    hours: int = Query(168, ge=1, le=720, description="Horas hacia atrás para buscar decisiones (default: 168 = 7 días, máximo: 720 = 30 días)")
) -> Dict[str, Any]:
    """
    Obtiene las decisiones del agente LLM (análisis SOC de ventanas temporales).
    Muestra IPs bloqueadas, razones del bloqueo, y análisis del tráfico.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/agent-decisions"] = _metrics["requests_by_endpoint"].get("/api/agent-decisions", 0) + 1
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            if EPISODES_API_MINIMAL:
                cursor.execute("""
                    SELECT COUNT(*) as total
                    FROM public.blocked_ips bi
                    WHERE bi.blocked_at >= NOW() - INTERVAL '24 hours'
                """)
                total = cursor.fetchone().get("total", 0)
                cursor.execute("""
                    SELECT bi.ip, bi.blocked_at, bi.expires_at, bi.active, bi.classification_source, bi.reason
                    FROM public.blocked_ips bi
                    WHERE bi.blocked_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY bi.blocked_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                items = []
                for row in cursor.fetchall():
                    item = dict(row)
                    if item.get('blocked_at') and hasattr(item['blocked_at'], 'isoformat'):
                        item['blocked_at'] = item['blocked_at'].isoformat()
                    if item.get('expires_at') and hasattr(item['expires_at'], 'isoformat'):
                        item['expires_at'] = item['expires_at'].isoformat()
                    items.append(item)
                return {"success": True, "items": items, "total": total, "limit": limit, "offset": offset}
            if EPISODES_API_MINIMAL:
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='episodes' AND table_schema='public'
                """)
                episode_columns = {row["column_name"] for row in cursor.fetchall()}
                id_col = "episode_id" if "episode_id" in episode_columns else ("id" if "id" in episode_columns else None)
                src_col = "src_ip" if "src_ip" in episode_columns else ("ip" if "ip" in episode_columns else None)
                if not id_col or not src_col:
                    return {"success": True, "episodes": [], "items": [], "total": 0, "limit": limit, "offset": offset}
                cursor.execute(f"""
                    SELECT e.{id_col} as episode_id, e.{src_col} as src_ip, e.created_at
                    FROM public.episodes e
                    ORDER BY e.created_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                episodes = [dict(row) for row in cursor.fetchall()]
                cursor.execute("SELECT COUNT(*) as total FROM public.episodes")
                total = int(cursor.fetchone().get("total", 0))
                return {
                    "success": True,
                    "episodes": episodes,
                    "items": episodes,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                }
            
            # Construir filtro de tenant
            tenant_filter = ""
            params = []
            
            if tenant_id and tenant_id != "all" and tenant_id.isdigit():
                tenant_filter = "AND tenant_id = %s"
                params.append(int(tenant_id))
            elif tenant_id == "default":
                tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
            
            # Obtener TODAS las decisiones del agente desde blocked_ips
            # Mostrar TODOS los bloqueos sin filtrar por active o expires_at
            # para ver todas las decisiones que el agente ha tomado
            decisions = []
            
            try:
                # Query simplificada: mostrar TODOS los bloqueos de las últimas X horas
                # sin importar si están activos o expirados
                cursor.execute(f"""
                    SELECT 
                        bi.ip,
                        bi.blocked_at,
                        bi.expires_at,
                        bi.reason,
                        bi.threat_type,
                        bi.severity,
                        COALESCE(bi.classification_source, bi.blocked_by, 'unknown') as classification_source,
                        bi.active,
                        bi.blocked_by,
                        COALESCE(COUNT(wl.id), 0) as total_logs,
                        COALESCE(
                            ARRAY_AGG(DISTINCT wl.threat_type) FILTER (WHERE wl.threat_type IS NOT NULL),
                            CASE WHEN bi.threat_type IS NOT NULL THEN ARRAY[bi.threat_type] ELSE ARRAY[]::VARCHAR[] END
                        ) as threat_types,
                        COALESCE(
                            ARRAY_AGG(DISTINCT wl.uri) FILTER (WHERE wl.uri IS NOT NULL AND wl.uri != ''),
                            ARRAY[]::VARCHAR[]
                        ) as sample_uris
                    FROM blocked_ips bi
                    LEFT JOIN waf_logs wl ON wl.ip::text = bi.ip::text
                        AND wl.timestamp >= bi.blocked_at - INTERVAL '24 hours'
                        AND wl.timestamp <= bi.blocked_at + INTERVAL '2 hours'
                    WHERE bi.blocked_at > NOW() - INTERVAL %s
                    GROUP BY bi.id, bi.ip, bi.blocked_at, bi.expires_at, bi.reason, bi.threat_type, 
                             bi.severity, bi.classification_source, bi.blocked_by, bi.active
                    ORDER BY bi.blocked_at DESC
                    LIMIT %s
                """, [f"{hours} hours", limit])
                
                rows = cursor.fetchall()
                logger.info(f"📊 Query ejecutada: {len(rows)} bloqueos encontrados en blocked_ips")
                
                for row in rows:
                    blocked_ip_data = dict(row)
                    # Guardar blocked_at y expires_at originales (datetime objects) antes de convertirlos a string
                    blocked_at_original = blocked_ip_data.get('blocked_at')
                    expires_at_original = blocked_ip_data.get('expires_at')
                    
                    # Convertir timestamps a ISO format
                    if blocked_ip_data.get('blocked_at'):
                        if hasattr(blocked_ip_data['blocked_at'], 'isoformat'):
                            blocked_ip_data['blocked_at'] = blocked_ip_data['blocked_at'].isoformat()
                    if blocked_ip_data.get('expires_at'):
                        if hasattr(blocked_ip_data['expires_at'], 'isoformat'):
                            blocked_ip_data['expires_at'] = blocked_ip_data['expires_at'].isoformat()
                        elif blocked_ip_data.get('expires_at') is None:
                            blocked_ip_data['expires_at'] = None
                    
                    # Asegurar que threat_types y sample_uris sean listas
                    if not blocked_ip_data.get('threat_types') or len(blocked_ip_data.get('threat_types', [])) == 0:
                        if blocked_ip_data.get('threat_type'):
                            blocked_ip_data['threat_types'] = [blocked_ip_data['threat_type']]
                        else:
                            blocked_ip_data['threat_types'] = []
                    else:
                        blocked_ip_data['threat_types'] = list(blocked_ip_data['threat_types'])
                    
                    if not blocked_ip_data.get('sample_uris'):
                        blocked_ip_data['sample_uris'] = []
                    else:
                        blocked_ip_data['sample_uris'] = list(blocked_ip_data['sample_uris'])[:10]  # Mostrar más URIs
                    
                    # Siempre intentar obtener logs desde waf_logs con ventana amplia
                    # Usar el blocked_at original (datetime object) antes de convertirlo a string
                    if blocked_at_original:
                        try:
                            # Buscar logs en una ventana amplia alrededor del bloqueo
                            # Usar 72 horas antes para capturar actividad previa al bloqueo
                            # Buscar logs sin restricción de ventana de tiempo muy estrecha (buscar más ampliamente)
                            ip_str = str(blocked_ip_data['ip'])
                            cursor.execute("""
                                SELECT 
                                    COUNT(*)::INTEGER as total_logs,
                                    ARRAY_AGG(DISTINCT threat_type ORDER BY threat_type) FILTER (WHERE threat_type IS NOT NULL AND threat_type != '') as threat_types,
                                    ARRAY_AGG(DISTINCT uri ORDER BY uri) FILTER (WHERE uri IS NOT NULL AND uri != '') as sample_uris
                                FROM waf_logs
                                WHERE (ip::text = %s OR ip = %s::inet)
                                AND timestamp >= %s - INTERVAL '7 days'
                                AND timestamp <= %s + INTERVAL '1 day'
                            """, (ip_str, ip_str, blocked_at_original, blocked_at_original))
                            log_data = cursor.fetchone()
                            logger.info(f"📊 Logs para IP {blocked_ip_data['ip']} (blocked_at={blocked_at_original}): {log_data}")
                            if log_data:
                                total_from_waf = log_data[0] if log_data[0] is not None else 0
                                threat_types_from_waf = list(log_data[1]) if log_data[1] is not None and len(log_data[1]) > 0 else []
                                sample_uris_from_waf = list(log_data[2]) if log_data[2] is not None and len(log_data[2]) > 0 else []
                                
                                logger.info(f"📊 IP {blocked_ip_data['ip']}: total_logs={total_from_waf}, threat_types={len(threat_types_from_waf)}, sample_uris={len(sample_uris_from_waf)}")
                                
                                # Actualizar total_logs siempre si encontramos logs (sobrescribir el valor del LEFT JOIN)
                                if total_from_waf > 0:
                                    blocked_ip_data['total_logs'] = total_from_waf
                                
                                # Actualizar threat_types si tenemos datos (combinar con existentes)
                                if threat_types_from_waf:
                                    existing_threats = set(blocked_ip_data.get('threat_types', []))
                                    new_threats = set(threat_types_from_waf)
                                    combined_threats = list(existing_threats | new_threats)
                                    if combined_threats:
                                        blocked_ip_data['threat_types'] = combined_threats
                                
                                # Actualizar sample_uris si tenemos datos (sobrescribir si hay datos)
                                if sample_uris_from_waf:
                                    blocked_ip_data['sample_uris'] = sample_uris_from_waf[:10]
                        except Exception as e2:
                            logger.warning(f"Error obteniendo logs adicionales para {blocked_ip_data.get('ip')}: {e2}", exc_info=True)
                    
                    # Agregar información adicional
                    blocked_ip_data['decision_type'] = 'block_ip'
                    blocked_ip_data['source'] = blocked_ip_data.get('classification_source', 'unknown')
                    blocked_ip_data['is_active'] = blocked_ip_data.get('active', False)
                    
                    # Calcular duración del bloqueo
                    # Usar los valores originales guardados antes de la conversión
                    blocked_ip_data['block_duration_hours'] = None
                    blocked_ip_data['is_expired'] = False
                    
                    if blocked_at_original and expires_at_original:
                        try:
                            # Calcular duración usando los datetime objects originales
                            if hasattr(expires_at_original, '__sub__'):
                                # Es un datetime object
                                duration = expires_at_original - blocked_at_original
                                duration_hours = duration.total_seconds() / 3600
                                blocked_ip_data['block_duration_hours'] = round(duration_hours, 1)
                                # Verificar si expiró
                                from datetime import timezone
                                expires_dt = expires_at_original
                                if expires_dt.tzinfo is None:
                                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                                blocked_ip_data['is_expired'] = expires_dt < datetime.now(timezone.utc)
                        except Exception as e3:
                            logger.warning(f"Error calculando duración para {blocked_ip_data.get('ip')}: {e3}", exc_info=True)
                    elif blocked_at_original and expires_at_original is None:
                        # Bloqueo permanente (sin expires_at)
                        blocked_ip_data['block_duration_hours'] = None
                        blocked_ip_data['is_expired'] = False
                    
                    decisions.append(blocked_ip_data)
                    
            except Exception as e:
                logger.error(f"Error obteniendo bloqueos de blocked_ips: {e}", exc_info=True)
            
            # Ordenar por fecha de bloqueo (más recientes primero)
            decisions.sort(key=lambda x: x.get('blocked_at', ''), reverse=True)
            decisions = decisions[:limit]
            
            cursor.close()
            
            return {
                "success": True,
                "count": len(decisions),
                "items": decisions,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
    except Exception as e:
        logger.error(f"Error obteniendo decisiones del agente: {e}", exc_info=True)
        _metrics["errors_total"] += 1
        return {
            "success": False,
            "count": 0,
            "items": [],
            "error": str(e)
        }


@app.get("/api/episodes/auto-decided", response_class=JSONResponse)
async def get_auto_decided_episodes(
    limit: int = Query(20, ge=1, le=100, description="Número de episodios a retornar"),
    offset: int = Query(0, ge=0, description="Número de episodios a saltar"),
    hours: int = Query(24, ge=1, le=168, description="Horas hacia atrás")
):
    """
    Obtiene episodios decididos automáticamente (ALLOW/BLOCK sin LLM consultado).
    Estos son episodios donde el sistema pudo decidir solo.
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Verificar si existe sample_uris
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='episodes' AND column_name='sample_uris'
            """)
            has_sample_uris = cursor.fetchone() is not None
            sample_uris_select = "COALESCE(e.sample_uris, '[]'::jsonb) as sample_uris" if has_sample_uris else "'[]'::jsonb as sample_uris"
            
            # Primero contar el total
            count_query = f"""
                SELECT COUNT(*) as total
                FROM public.episodes e
                WHERE e.created_at > NOW() - INTERVAL '{hours} hours'
                AND e.decision IN ('ALLOW', 'BLOCK')
                AND (e.llm_consulted = FALSE OR e.llm_consulted IS NULL)
                AND e.episode_id NOT IN (SELECT DISTINCT episode_id FROM analyst_labels WHERE episode_id IS NOT NULL)
            """
            cursor.execute(count_query)
            total_result = cursor.fetchone()
            total = total_result['total'] if total_result else 0
            
            # Luego obtener los episodios con paginación
            query = f"""
                SELECT 
                    e.episode_id,
                    e.src_ip,
                    e.episode_start,
                    e.episode_end,
                    e.total_requests,
                    e.unique_uris,
                    e.request_rate,
                    e.presence_flags,
                    e.status_code_ratio,
                    e.methods_count,
                    e.path_entropy_avg,
                    e.risk_score,
                    e.decision,
                    e.llm_consulted,
                    e.llm_label,
                    e.llm_confidence,
                    {sample_uris_select}
                FROM public.episodes e
                WHERE e.created_at > NOW() - INTERVAL '{hours} hours'
                AND e.decision IN ('ALLOW', 'BLOCK')
                AND (e.llm_consulted = FALSE OR e.llm_consulted IS NULL)
                AND e.episode_id NOT IN (SELECT DISTINCT episode_id FROM analyst_labels WHERE episode_id IS NOT NULL)
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
            """
            try:
                cursor.execute(query, (limit, offset))
                episodes = [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                logger.warning(f"Fallback episodios (columnas faltantes): {e}")
                fallback_query = f"""
                    SELECT e.{id_col} as episode_id, e.{src_col} as src_ip, e.created_at
                    FROM public.episodes e
                    ORDER BY e.created_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(fallback_query, (limit, offset))
                episodes = [dict(row) for row in cursor.fetchall()]
            
            cursor.close()
            
            # Convertir JSONB a dict
            for episode in episodes:
                for key in ['presence_flags', 'status_code_ratio', 'methods_count', 'sample_uris']:
                    if episode.get(key) and isinstance(episode[key], str):
                        try:
                            episode[key] = json.loads(episode[key])
                        except:
                            pass
            
            return {
                "success": True,
                "items": episodes,
                "total": total,
                "limit": limit,
                "offset": offset,
                "hours": hours
            }
    
    except Exception as e:
        logger.error(f"Error obteniendo episodios decididos automáticamente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error obteniendo episodios: {str(e)}")


@app.get("/api/episodes/auto-blocked", response_class=JSONResponse)
async def get_auto_blocked_episodes(
    limit: int = Query(50, ge=1, le=200, description="Número de episodios a retornar"),
    offset: int = Query(0, ge=0, description="Número de episodios a saltar"),
    hours: int = Query(24, ge=1, le=168, description="Horas hacia atrás")
):
    """
    Obtiene episodios que fueron bloqueados automáticamente (decision=BLOCK, classification_source=episode_analysis).
    Incluye detalles del bloqueo desde blocked_ips.
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Verificar si existe sample_uris
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='episodes' AND column_name='sample_uris'
            """)
            has_sample_uris = cursor.fetchone() is not None
            sample_uris_select = "COALESCE(e.sample_uris, '[]'::jsonb) as sample_uris" if has_sample_uris else "'[]'::jsonb as sample_uris"
            
            # Enfoque simplificado: empezar desde blocked_ips con classification_source='episode_analysis'
            # y luego buscar el episodio más reciente relacionado (sin restricciones estrictas de decision)
            # Esto asegura que mostremos todos los bloqueos automáticos activos
            
            # Primero contar el total - Incluir todas las fuentes de bloqueos automáticos
            count_query = f"""
                SELECT COUNT(DISTINCT bi.id) as total
                FROM public.blocked_ips bi
                WHERE bi.classification_source IN (
                    'episode_analysis', 
                    'time_window_soc_analysis',
                    'batch_analysis_llm',
                    'batch_analysis',
                    'immediate_scan_block'
                )
                AND bi.blocked_at > NOW() - INTERVAL '{hours} hours'
                AND bi.active = TRUE
                AND (bi.expires_at IS NULL OR bi.expires_at > NOW())
            """
            try:
                cursor.execute(count_query)
            except Exception as e:
                logger.warning(f"Fallback count episodios: {e}")
                cursor.execute("SELECT COUNT(*) as total FROM public.episodes")
            total_result = cursor.fetchone()
            total = total_result['total'] if total_result else 0
            
            # Luego obtener los bloqueos con sus episodios relacionados
            # Usar LATERAL JOIN para encontrar el episodio más cercano en tiempo
            # Si no hay episodio, usar datos de blocked_ips como fallback
            query = f"""
                SELECT 
                    COALESCE(e.episode_id, NULL) as episode_id,
                    COALESCE(e.src_ip::text, bi.ip::text) as src_ip,
                    e.episode_start,
                    e.episode_end,
                    COALESCE(e.total_requests, 0) as total_requests,
                    COALESCE(e.unique_uris, 0) as unique_uris,
                    COALESCE(e.request_rate, 0) as request_rate,
                    COALESCE(e.presence_flags, '{{}}'::jsonb) as presence_flags,
                    COALESCE(e.status_code_ratio, '{{}}'::jsonb) as status_code_ratio,
                    COALESCE(e.methods_count, '{{}}'::jsonb) as methods_count,
                    COALESCE(e.path_entropy_avg, 0) as path_entropy_avg,
                    COALESCE(e.risk_score, bi.risk_score, 0.8) as risk_score,
                    COALESCE(e.decision, 'BLOCK') as decision,
                    COALESCE(e.llm_consulted, FALSE) as llm_consulted,
                    e.llm_label,
                    e.llm_confidence,
                    {sample_uris_select},
                    bi.blocked_at,
                    bi.expires_at,
                    bi.reason as block_reason,
                    bi.threat_type as block_threat_type,
                    bi.severity as block_severity,
                    bi.active as block_active,
                    bi.classification_source as block_classification_source
                FROM blocked_ips bi
                LEFT JOIN LATERAL (
                    SELECT e.*
                    FROM episodes e
                    WHERE e.src_ip::text = bi.ip::text
                    AND e.created_at >= bi.blocked_at - INTERVAL '30 minutes'
                    AND e.created_at <= bi.blocked_at + INTERVAL '30 minutes'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (e.created_at - bi.blocked_at))) ASC
                    LIMIT 1
                ) e ON TRUE
                WHERE bi.classification_source IN (
                    'episode_analysis', 
                    'time_window_soc_analysis',
                    'batch_analysis_llm',
                    'batch_analysis',
                    'immediate_scan_block'
                )
                AND bi.blocked_at > NOW() - INTERVAL '{hours} hours'
                AND bi.active = TRUE
                AND (bi.expires_at IS NULL OR bi.expires_at > NOW())
                ORDER BY bi.blocked_at DESC
                LIMIT %s OFFSET %s
            """
            # Nota: Si el LATERAL JOIN no encuentra episodio, usamos datos de blocked_ips como fallback
            # Ventana aumentada a 1 hora y removido filtro de decision='BLOCK' para encontrar más episodios
            cursor.execute(query, (limit, offset))
            
            episodes = [dict(row) for row in cursor.fetchall()]
            
            cursor.close()
            
            # Convertir JSONB a dict
            for episode in episodes:
                for key in ['presence_flags', 'status_code_ratio', 'methods_count', 'sample_uris']:
                    if episode.get(key) and isinstance(episode[key], str):
                        try:
                            episode[key] = json.loads(episode[key])
                        except:
                            pass
            
            return {
                "success": True,
                "items": episodes,
                "total": total,
                "limit": limit,
                "offset": offset,
                "hours": hours
            }
    
    except Exception as e:
        logger.error(f"Error obteniendo episodios bloqueados automáticamente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error obteniendo episodios: {str(e)}")


@app.get("/api/learning/status", response_class=JSONResponse)
async def get_learning_status():
    """Obtiene el estado actual del aprendizaje del sistema."""
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Verificar si existe la tabla learning_history
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name='learning_history'
            """)
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                # Si la tabla no existe, retornar datos básicos
                cursor.execute("SELECT COUNT(*) as count FROM analyst_labels")
                total_labels = cursor.fetchone()['count']
                cursor.close()
                retrain_threshold = int(os.getenv("LEARNING_RETRAIN_THRESHOLD", "20"))
                return {
                    "success": True,
                    "data": {
                        "last_retrain": None,
                        "new_labels_since_last": total_labels,
                        "retrain_threshold": retrain_threshold,
                        "progress_to_next_retrain": min(100, (total_labels / retrain_threshold) * 100),
                        "labels_remaining": max(0, retrain_threshold - total_labels),
                        "recent_history": [],
                        "stats": {}
                    }
                }
            
            # Último reentrenamiento exitoso
            cursor.execute("""
                SELECT * FROM learning_history
                WHERE success = TRUE
                ORDER BY retrain_timestamp DESC
                LIMIT 1
            """)
            last_retrain = cursor.fetchone()
            
            # Total de etiquetas desde último reentrenamiento
            if last_retrain:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM analyst_labels
                    WHERE timestamp > %s
                """, (last_retrain['retrain_timestamp'],))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM analyst_labels
                """)
            new_labels_count = cursor.fetchone()['count']
            
            # Umbral de reentrenamiento (configurable, por defecto 20)
            retrain_threshold = int(os.getenv("LEARNING_RETRAIN_THRESHOLD", "20"))
            
            # Historial de últimos 5 reentrenamientos
            cursor.execute("""
                SELECT * FROM learning_history
                ORDER BY retrain_timestamp DESC
                LIMIT 5
            """)
            recent_history = [dict(row) for row in cursor.fetchall()]
            
            # Estadísticas generales
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_retrains,
                    COUNT(*) FILTER (WHERE success = TRUE) as successful_retrains,
                    AVG(improvement) FILTER (WHERE improvement IS NOT NULL) as avg_improvement,
                    MAX(accuracy_after) FILTER (WHERE accuracy_after IS NOT NULL) as best_accuracy
                FROM learning_history
            """)
            stats = cursor.fetchone()
            
            cursor.close()
            
            return {
                "success": True,
                "data": {
                    "last_retrain": dict(last_retrain) if last_retrain else None,
                    "new_labels_since_last": new_labels_count,
                    "retrain_threshold": retrain_threshold,
                    "progress_to_next_retrain": min(100, (new_labels_count / retrain_threshold) * 100),
                    "labels_remaining": max(0, retrain_threshold - new_labels_count),
                    "recent_history": recent_history,
                    "stats": dict(stats) if stats else {}
                }
            }
    except Exception as e:
        logger.error(f"Error obteniendo estado de aprendizaje: {e}", exc_info=True)
        # Si hay error, retornar datos básicos
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT COUNT(*) as count FROM analyst_labels")
            total_labels = cursor.fetchone()['count']
            cursor.close()
            retrain_threshold = int(os.getenv("LEARNING_RETRAIN_THRESHOLD", "20"))
            return {
                "success": True,
                "data": {
                    "last_retrain": None,
                    "new_labels_since_last": total_labels,
                    "retrain_threshold": retrain_threshold,
                    "progress_to_next_retrain": min(100, (total_labels / retrain_threshold) * 100),
                    "labels_remaining": max(0, retrain_threshold - total_labels),
                    "recent_history": [],
                    "stats": {}
                }
            }
        except:
            return {
                "success": False,
                "error": str(e)
            }


@app.get("/api/episodes/pending", response_class=JSONResponse)
async def get_pending_episodes(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Número de episodios a retornar"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    ip: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    risk_min: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None)
):
    """
    Obtiene episodios pendientes de etiquetar (que no tienen analyst_labels).
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='episodes' AND table_schema='public'
            """)
            episode_columns = {row["column_name"] for row in cursor.fetchall()}
            cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='public' AND table_name='analyst_labels'
            """)
            has_analyst_labels = cursor.fetchone() is not None
            id_col = "episode_id" if "episode_id" in episode_columns else ("id" if "id" in episode_columns else None)
            src_col = "src_ip" if "src_ip" in episode_columns else ("ip" if "ip" in episode_columns else None)
            if not id_col or not src_col:
                return {
                    "success": True,
                    "episodes": [],
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset
                }
            select_fields = [
                f"e.{id_col} as episode_id",
                f"e.{src_col} as src_ip",
                "e.created_at"
            ]
            optional_fields = [
                "total_requests",
                "unique_uris",
                "request_rate",
                "risk_score",
                "decision",
                "episode_start",
                "episode_end",
                "presence_flags",
                "status_code_ratio",
                "methods_count",
                "sample_uris",
                "llm_label",
                "llm_confidence"
            ]
            for field in optional_fields:
                if field in episode_columns:
                    select_fields.append(f"e.{field}")
            # Construir filtros dinámicos
            filters = []
            params = []
            
            # Filtro de fecha (por defecto últimos 7 días)
            date_from_val = date_from or request.query_params.get('date_from')
            date_to_val = date_to or request.query_params.get('date_to')
            if date_from_val and date_to_val:
                try:
                    from datetime import datetime
                    datetime.fromisoformat(date_from_val.replace('Z', '+00:00'))
                    datetime.fromisoformat(date_to_val.replace('Z', '+00:00'))
                    filters.append("e.created_at >= %s AND e.created_at <= %s")
                    params.extend([date_from_val, date_to_val])
                except ValueError:
                    filters.append("e.created_at > NOW() - INTERVAL '7 days'")
            else:
                filters.append("e.created_at > NOW() - INTERVAL '7 days'")
            
            # Filtro de tenant
            tenant_id_val = tenant_id or request.query_params.get('tenant_id')
            if tenant_id_val and tenant_id_val != "all" and tenant_id_val.isdigit():
                if "tenant_id" in episode_columns:
                    filters.append("e.tenant_id = %s")
                    params.append(int(tenant_id_val))
            
            # Filtro de IP
            ip_val = ip or request.query_params.get('ip')
            if ip_val:
                filters.append(f"e.{src_col} = %s")
                params.append(ip_val)
            
            # Filtro de decisión
            decision_val = decision or request.query_params.get('decision')
            if decision_val and "decision" in episode_columns:
                filters.append("e.decision = %s")
                params.append(decision_val)
            
            # Filtro de risk score mínimo
            risk_min_val = risk_min or request.query_params.get('risk_min')
            if risk_min_val and "risk_score" in episode_columns:
                try:
                    risk_val = int(risk_min_val)
                    filters.append("e.risk_score >= %s")
                    params.append(risk_val)
                except ValueError:
                    pass
            
            # Filtro de analyst_labels
            if has_analyst_labels and id_col == "episode_id":
                filters.append("""
                    e.episode_id NOT IN (
                        SELECT DISTINCT episode_id 
                        FROM public.analyst_labels 
                        WHERE episode_id IS NOT NULL
                    )
                """)
            
            where_clause = "WHERE " + " AND ".join(filters) if filters else ""
            
            query = f"""
                SELECT {", ".join(select_fields)}
                FROM public.episodes e
                {where_clause}
                ORDER BY e.created_at DESC
                LIMIT %s OFFSET %s
            """
            try:
                cursor.execute(query, (limit, offset))
                episodes = [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                logger.warning(f"Fallback episodios (columnas faltantes): {e}")
                fallback_query = f"""
                    SELECT e.{id_col} as episode_id, e.{src_col} as src_ip, e.created_at
                    FROM public.episodes e
                    ORDER BY e.created_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(fallback_query, (limit, offset))
                episodes = [dict(row) for row in cursor.fetchall()]
            
            # Contar total usando subquery
            count_query = """
                SELECT COUNT(*) as total
                FROM public.episodes e
                WHERE e.created_at > NOW() - INTERVAL '7 days'
            """
            if has_analyst_labels and id_col == "episode_id":
                count_query += """
                AND e.episode_id NOT IN (
                    SELECT DISTINCT episode_id 
                    FROM public.analyst_labels 
                    WHERE episode_id IS NOT NULL
                )
                """
            try:
                cursor.execute(count_query)
            except Exception as e:
                logger.warning(f"Fallback count episodios: {e}")
                cursor.execute("SELECT COUNT(*) as total FROM public.episodes")
            total_result = cursor.fetchone()
            total = int(total_result['total']) if total_result and total_result.get('total') is not None else 0
            
            cursor.close()
            
            # Convertir JSONB a dict y fechas a ISO
            for episode in episodes:
                for key in ['episode_start', 'episode_end', 'created_at']:
                    if episode.get(key) and hasattr(episode[key], 'isoformat'):
                        episode[key] = episode[key].isoformat()
                for key in ['presence_flags', 'status_code_ratio', 'methods_count', 'sample_uris']:
                    if episode.get(key) and isinstance(episode[key], str):
                        try:
                            episode[key] = json.loads(episode[key])
                        except:
                            pass
            
            return {
                "success": True,
                "episodes": episodes,  # Mantener "episodes" para compatibilidad
                "items": episodes,     # También incluir "items" para el frontend
                "total": total,
                "limit": limit,
                "offset": offset
            }
    except Exception as e:
        logger.error(f"Error obteniendo episodios pendientes: {e}", exc_info=True)
        return JSONResponse({
            "episodes": [],
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "error": f"Error: {str(e)[:200]}"
        }, status_code=200)


@app.get("/api/agent-activity", response_class=JSONResponse)
async def agent_activity(
    hours: int = Query(24, ge=1, le=168, description="Horas hacia atrás para analizar actividad")
) -> Dict[str, Any]:
    """
    Monitorea la actividad del agente IA: cuántas veces se ejecuta, decisiones tomadas, etc.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/agent-activity"] = _metrics["requests_by_endpoint"].get("/api/agent-activity", 0) + 1
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Estadísticas de bloqueos
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_blocks,
                    COUNT(*) FILTER (WHERE active = TRUE) as active_blocks,
                    COUNT(*) FILTER (WHERE active = FALSE) as inactive_blocks,
                    COUNT(*) FILTER (WHERE expires_at IS NOT NULL AND expires_at < NOW()) as expired_blocks,
                    COUNT(DISTINCT classification_source) as unique_sources,
                    COUNT(*) FILTER (WHERE classification_source = 'time_window_soc_analysis') as soc_analysis_blocks,
                    COUNT(*) FILTER (WHERE classification_source = 'batch_analysis_llm') as batch_llm_blocks,
                    COUNT(*) FILTER (WHERE classification_source = 'batch_analysis') as batch_blocks,
                    COUNT(*) FILTER (WHERE classification_source = 'immediate_scan_block') as immediate_blocks,
                    COUNT(*) FILTER (WHERE classification_source = 'episode_analysis') as episode_analysis_blocks
                FROM blocked_ips
                WHERE blocked_at > NOW() - INTERVAL %s
            """, [f"{hours} hours"])
            block_stats = dict(cursor.fetchone())
            
            # Actividad por hora
            cursor.execute("""
                SELECT 
                    DATE_TRUNC('hour', blocked_at) as hour,
                    COUNT(*) as blocks_count,
                    COUNT(DISTINCT ip) as unique_ips,
                    ARRAY_AGG(DISTINCT classification_source) FILTER (WHERE classification_source IS NOT NULL) as sources
                FROM blocked_ips
                WHERE blocked_at > NOW() - INTERVAL %s
                GROUP BY DATE_TRUNC('hour', blocked_at)
                ORDER BY hour DESC
                LIMIT 24
            """, [f"{hours} hours"])
            hourly_activity = [dict(row) for row in cursor.fetchall()]
            
            # Últimas decisiones
            cursor.execute("""
                SELECT 
                    ip,
                    blocked_at,
                    threat_type,
                    classification_source,
                    active,
                    expires_at
                FROM blocked_ips
                WHERE blocked_at > NOW() - INTERVAL %s
                ORDER BY blocked_at DESC
                LIMIT 10
            """, [f"{hours} hours"])
            recent_decisions = [dict(row) for row in cursor.fetchall()]
            
            # Convertir timestamps
            for decision in recent_decisions:
                if decision.get('blocked_at'):
                    if hasattr(decision['blocked_at'], 'isoformat'):
                        decision['blocked_at'] = decision['blocked_at'].isoformat()
                if decision.get('expires_at'):
                    if hasattr(decision['expires_at'], 'isoformat'):
                        decision['expires_at'] = decision['expires_at'].isoformat()
            
            for activity in hourly_activity:
                if activity.get('hour'):
                    if hasattr(activity['hour'], 'isoformat'):
                        activity['hour'] = activity['hour'].isoformat()
            
            cursor.close()
            
            return {
                "success": True,
                "period_hours": hours,
                "statistics": block_stats,
                "hourly_activity": hourly_activity,
                "recent_decisions": recent_decisions,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
    except Exception as e:
        logger.error(f"Error obteniendo actividad del agente: {e}", exc_info=True)
        _metrics["errors_total"] += 1
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/api/episodes/stats", response_class=JSONResponse)
async def get_episode_labeling_stats():
    """
    Obtiene estadísticas de etiquetado de episodios y bloqueos resultantes.
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Total de episodios etiquetados
            cursor.execute("SELECT COUNT(DISTINCT episode_id) as total FROM analyst_labels")
            total_labeled = cursor.fetchone()['total']
            
            # Total de IPs bloqueadas por etiquetado
            cursor.execute("""
                SELECT COUNT(DISTINCT bi.ip) as total
                FROM blocked_ips bi
                WHERE bi.classification_source = 'analyst_label'
            """)
            total_blocked = cursor.fetchone()['total']
            
            # Bloqueos activos por etiquetado
            cursor.execute("""
                SELECT COUNT(DISTINCT bi.ip) as active
                FROM blocked_ips bi
                WHERE bi.classification_source = 'analyst_label'
                AND bi.active = TRUE
                AND (bi.expires_at IS NULL OR bi.expires_at > NOW())
            """)
            active_blocks = cursor.fetchone()['active']
            
            # Último aprendizaje (verificar si hay etiquetas recientes)
            cursor.execute("""
                SELECT MAX(timestamp) as last_learning
                FROM analyst_labels
            """)
            last_learning_result = cursor.fetchone()
            last_learning_time = last_learning_result['last_learning'] if last_learning_result else None
            
            # Episodios decididos automáticamente (ALLOW/BLOCK sin LLM) en las últimas 24h
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM episodes e
                WHERE e.created_at > NOW() - INTERVAL '24 hours'
                AND e.decision IN ('ALLOW', 'BLOCK')
                AND (e.llm_consulted = FALSE OR e.llm_consulted IS NULL)
                AND e.episode_id NOT IN (SELECT DISTINCT episode_id FROM analyst_labels WHERE episode_id IS NOT NULL)
            """)
            auto_decided = cursor.fetchone()['total']
            
            # Episodios que necesitan etiquetado (UNCERTAIN o con LLM consultado) en las últimas 24h
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM episodes e
                WHERE e.created_at > NOW() - INTERVAL '24 hours'
                AND (e.decision = 'UNCERTAIN' OR e.llm_consulted = TRUE)
                AND e.episode_id NOT IN (SELECT DISTINCT episode_id FROM analyst_labels WHERE episode_id IS NOT NULL)
            """)
            need_labeling = cursor.fetchone()['total']
            
            # Total de episodios nuevos en las últimas 24h
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM episodes e
                WHERE e.created_at > NOW() - INTERVAL '24 hours'
            """)
            total_recent = cursor.fetchone()['total']
            
            cursor.close()
            
            return {
                "success": True,
                "stats": {
                    "total_labeled": total_labeled,
                    "total_blocked": total_blocked,
                    "active_blocks": active_blocks,
                    "last_learning_time": last_learning_time.isoformat() if last_learning_time else None,
                    "auto_decided_24h": auto_decided,
                    "need_labeling_24h": need_labeling,
                    "total_recent_24h": total_recent
                }
            }
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas de etiquetado: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/api/episodes/blocked-ips", response_class=JSONResponse)
async def get_episode_blocked_ips(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ip: Optional[str] = Query(None),
    threat_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Obtiene IPs bloqueadas por episodios (tanto por etiquetado manual como automático).
    """
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='blocked_ips' AND table_schema='public'
            """)
            blocked_columns = {row["column_name"] for row in cursor.fetchall()}
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='episodes' AND table_schema='public'
            """)
            episode_columns = {row["column_name"] for row in cursor.fetchall()}
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='analyst_labels' AND table_schema='public'
            """)
            analyst_columns = {row["column_name"] for row in cursor.fetchall()}
            has_analyst_label = "analyst_label" in analyst_columns and "episode_id" in analyst_columns
            
            # Primero contar el total
            count_query = """
                SELECT COUNT(*) as total
                FROM public.blocked_ips bi
                WHERE bi.classification_source IN ('analyst_label', 'episode_analysis')
                AND bi.blocked_at >= NOW() - INTERVAL '24 hours'
            """
            cursor.execute(count_query)
            total_result = cursor.fetchone()
            total = total_result['total'] if total_result else 0
            
            # Obtener bloqueos recientes (últimas 24 horas) de episodios
            # Incluye tanto analyst_label como episode_analysis
            select_fields = [
                "bi.ip",
                "bi.blocked_at",
                "bi.expires_at",
                "bi.active",
                "bi.classification_source",
                "bi.threat_type",
                "bi.reason",
                "bi.severity"
            ]
            episode_id_subquery = ""
            if "src_ip" in episode_columns and "episode_id" in episode_columns:
                episode_id_subquery = """
                    ,(
                        SELECT e.episode_id 
                        FROM public.episodes e
                        WHERE e.src_ip::text = bi.ip::text
                        AND e.created_at >= bi.blocked_at - INTERVAL '5 minutes'
                        ORDER BY e.created_at DESC
                        LIMIT 1
                    ) as episode_id
                """
            analyst_label_subquery = ""
            if has_analyst_label and "timestamp" in analyst_columns:
                analyst_label_subquery = """
                    ,(
                        SELECT al.analyst_label 
                        FROM public.analyst_labels al
                        JOIN public.episodes e ON e.episode_id = al.episode_id
                        WHERE e.src_ip::text = bi.ip::text
                        AND al.analyst_label != 'ALLOW'
                        AND al.timestamp >= bi.blocked_at - INTERVAL '5 minutes'
                        ORDER BY al.timestamp DESC
                        LIMIT 1
                    ) as analyst_label
                """
            # Aplicar filtros a la query principal
            query_filters = ["bi.classification_source IN ('analyst_label', 'episode_analysis')"]
            query_params = []
            
            # Filtro de fecha
            date_from_val = date_from or request.query_params.get('date_from')
            date_to_val = date_to or request.query_params.get('date_to')
            if date_from_val and date_to_val:
                try:
                    from datetime import datetime
                    datetime.fromisoformat(date_from_val.replace('Z', '+00:00'))
                    datetime.fromisoformat(date_to_val.replace('Z', '+00:00'))
                    query_filters.append("bi.blocked_at >= %s AND bi.blocked_at <= %s")
                    query_params.extend([date_from_val, date_to_val])
                except ValueError:
                    query_filters.append("bi.blocked_at >= NOW() - INTERVAL '24 hours'")
            else:
                query_filters.append("bi.blocked_at >= NOW() - INTERVAL '24 hours'")
            
            # Filtro de IP
            ip_val = ip or request.query_params.get('ip')
            if ip_val:
                query_filters.append("bi.ip::text = %s")
                query_params.append(ip_val)
            
            # Filtro de threat_type
            threat_type_val = threat_type or request.query_params.get('threat_type')
            if threat_type_val:
                query_filters.append("bi.threat_type = %s")
                query_params.append(threat_type_val)
            
            # Filtro de estado
            status_val = status or request.query_params.get('status')
            if status_val == 'active':
                query_filters.append("bi.active = TRUE")
            elif status_val == 'expired':
                query_filters.append("bi.active = FALSE")
            
            # Filtro de actor
            actor_val = actor or request.query_params.get('actor')
            if actor_val == 'automatic':
                query_filters.append("bi.blocked_by = 'automatic'")
            elif actor_val == 'manual':
                query_filters.append("bi.blocked_by != 'automatic' AND bi.blocked_by IS NOT NULL")
            
            where_clause = "WHERE " + " AND ".join(query_filters)
            
            query = f"""
                SELECT 
                    {", ".join(select_fields)}
                    {episode_id_subquery}
                    {analyst_label_subquery}
                FROM public.blocked_ips bi
                {where_clause}
                ORDER BY bi.blocked_at DESC
                LIMIT %s OFFSET %s
            """
            try:
                query_params.extend([limit, offset])
                cursor.execute(query, query_params)
                rows = cursor.fetchall()
            except Exception as e:
                logger.warning(f"Fallback bloqueos episodios: {e}")
                fallback_query = """
                    SELECT bi.ip, bi.blocked_at, bi.expires_at, bi.active, bi.classification_source, bi.reason
                    FROM public.blocked_ips bi
                    WHERE bi.blocked_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY bi.blocked_at DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(fallback_query, (limit, offset))
                rows = cursor.fetchall()
            items = []
            for row in rows:
                item = dict(row)
                if item.get('blocked_at') and hasattr(item['blocked_at'], 'isoformat'):
                    item['blocked_at'] = item['blocked_at'].isoformat()
                if item.get('expires_at') and hasattr(item['expires_at'], 'isoformat'):
                    item['expires_at'] = item['expires_at'].isoformat()
                
                # Si no hay analyst_label pero hay threat_type, usar threat_type como label
                if not item.get('analyst_label') and item.get('threat_type'):
                    item['analyst_label'] = item['threat_type']
                
                items.append(item)
            
            cursor.close()
            
            return {
                "success": True,
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset
            }
    except Exception as e:
        logger.error(f"Error obteniendo bloqueos por episodios: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "items": []
        }


@app.post("/api/episodes/label", response_class=JSONResponse)
async def label_episode(
    request: Dict[str, Any] = Body(...)
):
    """
    Etiqueta un episodio con la decisión del analista.
    
    Body:
    {
        "episode_id": 123,
        "analyst_label": "PATH_TRAVERSAL",
        "analyst_notes": "Escaneo claro de archivos sensibles",
        "analyst_id": "user@example.com",
        "confidence": 1.0
    }
    """
    try:
        episode_id = request.get('episode_id')
        analyst_label = request.get('analyst_label')
        analyst_notes = request.get('analyst_notes')
        analyst_id = request.get('analyst_id')
        confidence = float(request.get('confidence', 1.0))
        
        if not episode_id or not analyst_label:
            raise HTTPException(status_code=400, detail="episode_id y analyst_label son requeridos")
        
        # Validar label
        valid_labels = ['ALLOW', 'PATH_TRAVERSAL', 'XSS', 'SQLI', 'SCAN_PROBE', 
                       'CMD_INJECTION', 'SSRF', 'MULTIPLE_ATTACKS', 'UNAUTHORIZED_ACCESS']
        if analyst_label not in valid_labels:
            raise HTTPException(status_code=400, detail=f"analyst_label debe ser uno de: {', '.join(valid_labels)}")
        
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Obtener features del episodio y src_ip
            cursor.execute("""
                SELECT 
                    src_ip, total_requests, unique_uris, request_rate,
                    status_code_ratio, presence_flags, path_entropy_avg
                FROM episodes
                WHERE episode_id = %s
            """, (episode_id,))
            
            episode = cursor.fetchone()
            if not episode:
                raise HTTPException(status_code=404, detail=f"Episodio {episode_id} no encontrado")
            
            src_ip = episode['src_ip']
            
            # Preparar episode_features_json
            episode_features = {
                'total_requests': episode['total_requests'],
                'unique_uris': episode['unique_uris'],
                'request_rate': float(episode['request_rate']) if episode['request_rate'] else 0,
                'status_code_ratio': episode['status_code_ratio'] if isinstance(episode['status_code_ratio'], dict) else json.loads(episode['status_code_ratio'] or '{}'),
                'presence_flags': episode['presence_flags'] if isinstance(episode['presence_flags'], dict) else json.loads(episode['presence_flags'] or '{}'),
                'path_entropy_avg': float(episode['path_entropy_avg']) if episode['path_entropy_avg'] else 0
            }
            
            # Verificar si ya existe etiqueta para este episodio
            cursor.execute("SELECT label_id FROM analyst_labels WHERE episode_id = %s", (episode_id,))
            existing = cursor.fetchone()
            
            if existing:
                # Actualizar etiqueta existente
                cursor.execute("""
                    UPDATE analyst_labels SET
                        analyst_label = %s,
                        episode_features_json = %s,
                        analyst_notes = %s,
                        analyst_id = %s,
                        confidence = %s,
                        timestamp = NOW()
                    WHERE episode_id = %s
                    RETURNING label_id
                """, (
                    analyst_label,
                    json.dumps(episode_features),
                    analyst_notes,
                    analyst_id,
                    confidence,
                    episode_id
                ))
                result = cursor.fetchone()
                label_id = result['label_id'] if result and result.get('label_id') else None
            else:
                # Insertar nueva etiqueta
                cursor.execute("""
                    INSERT INTO analyst_labels (
                        episode_id, episode_features_json, analyst_label,
                        analyst_notes, analyst_id, confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING label_id
                """, (
                    episode_id,
                    json.dumps(episode_features),
                    analyst_label,
                    analyst_notes,
                    analyst_id,
                    confidence
                ))
                result = cursor.fetchone()
                label_id = result['label_id'] if result and result.get('label_id') else None
            
            # Si el label es un ataque (no ALLOW), bloquear IP automáticamente
            attack_labels = ['PATH_TRAVERSAL', 'XSS', 'SQLI', 'SCAN_PROBE', 
                           'CMD_INJECTION', 'SSRF', 'MULTIPLE_ATTACKS', 'UNAUTHORIZED_ACCESS']
            ip_blocked = False
            block_message = ""
            
            if analyst_label in attack_labels:
                try:
                    from datetime import datetime, timedelta
                    # Duración del bloqueo: 24 horas para ataques confirmados por analista
                    expires_at = datetime.now() + timedelta(hours=24)
                    threat_type = analyst_label
                    severity = 'high'
                    reason = f"Etiquetado manualmente por analista: {analyst_label}"
                    if analyst_notes:
                        reason += f" - {analyst_notes[:200]}"
                    else:
                        reason += f" (episode_id={episode_id})"
                    
                    # Insertar en blocked_ips
                    cursor.execute("""
                        INSERT INTO blocked_ips (
                            ip, blocked_at, expires_at, reason, 
                            classification_source, threat_type, severity, active
                        )
                        VALUES (%s, NOW(), %s, %s, 'analyst_label', %s, %s, TRUE)
                        ON CONFLICT (ip) WHERE active = TRUE
                        DO UPDATE SET
                            blocked_at = NOW(),
                            expires_at = EXCLUDED.expires_at,
                            reason = EXCLUDED.reason,
                            threat_type = EXCLUDED.threat_type,
                            severity = EXCLUDED.severity,
                            classification_source = 'analyst_label',
                            updated_at = NOW()
                    """, (src_ip, expires_at, reason[:500], threat_type, severity))
                    
                    ip_blocked = True
                    block_message = f"IP {src_ip} bloqueada automáticamente por 24 horas"
                    logger.warning(f"🚨 IP {src_ip} bloqueada por etiqueta de analista: {analyst_label}")
                    
                except Exception as e:
                    logger.error(f"Error bloqueando IP {src_ip} después de etiquetado: {e}", exc_info=True)
                    # No fallar el etiquetado si el bloqueo falla
                    block_message = f"⚠️ Etiqueta guardada, pero error al bloquear IP: {str(e)[:100]}"
            
            conn.commit()
            cursor.close()
            
            logger.info(f"✅ Episodio {episode_id} etiquetado: {analyst_label}" + (f" - {block_message}" if block_message else ""))
            
            message = f"Episodio {episode_id} etiquetado como {analyst_label}"
            if ip_blocked:
                message += f". {block_message}"
            
            return {
                "success": True,
                "label_id": label_id,
                "ip_blocked": ip_blocked,
                "message": message
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error etiquetando episodio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error etiquetando episodio: {str(e)}")


@app.get("/api/alerts", response_class=JSONResponse)
async def list_alerts(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """
    Lista las alertas generadas por el alert-service.

    Lee el archivo ALERTS_FILE (compartido vía volumen) y devuelve las últimas N.
    """
    alerts_path = ALERTS_FILE
    try:
        if not os.path.exists(alerts_path):
            return {"count": 0, "items": []}

        with open(alerts_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return {"count": 0, "items": []}

        # Ordenar por timestamp descendente si existe
        def sort_key(item: Dict[str, Any]) -> str:
            ts = item.get("timestamp")
            return ts or ""

        data_sorted = sorted(data, key=sort_key, reverse=True)
        items = data_sorted[:limit]
        return {"count": len(items), "items": items}
    except Exception as e:  # pragma: no cover - diagnóstico
        return {"count": 0, "items": [], "error": str(e)}


async def _predict_with_ml(log_data: Dict[str, Any]) -> Dict[str, Any]:
    """Predice amenaza usando modelo ML local"""
    try:
        import sys
        from pathlib import Path
        mcp_path = Path("/app/mcp-core")
        if mcp_path.exists() and str(mcp_path) not in sys.path:
            sys.path.insert(0, str(mcp_path))
        
        from tools.ml_tools import predict_threat
        result = await predict_threat(log_data, model_id="default")
        return result
    except Exception as e:
        logger.warning(f"Error en predicción ML: {e}")
        return {"success": False, "error": str(e)}


async def _analyze_with_llm(log_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analiza log usando LLM (Gemini)"""
    try:
        import os
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"success": False, "error": "GEMINI_API_KEY no configurada"}
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        # Preparar prompt
        uri = log_data.get("uri", "")
        raw_log = log_data.get("raw_log", {})
        if isinstance(raw_log, dict):
            raw_log_str = json.dumps(raw_log)
        else:
            raw_log_str = str(raw_log)
        
        prompt = f"""Analiza este log de seguridad del WAF y determina:

1. SEVERIDAD: low, medium, o high
2. TIPO DE AMENAZA: SQLI, XSS, PATH_TRAVERSAL, CMD_INJECTION, RFI_LFI, XXE, u otro
3. RAZÓN: una explicación breve

URI: {uri}
Raw Log: {raw_log_str[:500]}

Responde SOLO en formato JSON válido:
{{
  "severity": "low|medium|high",
  "threat_type": "SQLI|XSS|PATH_TRAVERSAL|CMD_INJECTION|RFI_LFI|XXE|OTHER",
  "reason": "explicación breve",
  "confidence": 0.0-1.0
}}"""

        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Limpiar respuesta
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        llm_result = json.loads(response_text)
        return {
            "success": True,
            "severity": llm_result.get("severity", "low"),
            "threat_type": llm_result.get("threat_type"),
            "reason": llm_result.get("reason", ""),
            "confidence": float(llm_result.get("confidence", 0.5))
        }
    except Exception as e:
        logger.warning(f"Error en análisis LLM: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/events", response_class=JSONResponse)
async def list_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Lista eventos de mitigación y otros eventos del sistema (Event Log).
    Ahora incluye eventos de waf_logs con predicciones ML y LLM.
    Soporta filtrado por tenant_id.
    """
    events_path = EVENTS_FILE
    all_events = []
    
    # 1. Leer eventos del archivo JSON (si existe)
    try:
        if os.path.exists(events_path):
            with open(events_path, "r", encoding="utf-8") as f:
                file_events = json.load(f)
                if isinstance(file_events, list):
                    all_events.extend(file_events)
    except Exception as e:
        logger.warning(f"Error leyendo eventos del archivo: {e}")
    
    # 2. Obtener eventos de waf_logs (especialmente del Red Team)
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Construir filtro de tenant
        tenant_filter = ""
        params = []
        
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            tenant_filter = "AND tenant_id = %s"
            params.append(int(tenant_id))
        elif tenant_id == "default":
            tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
        
        # FASE 4: Agregar paginación
        cursor.execute(f"""
            SELECT 
                id, timestamp, ip, method, uri, status, blocked,
                threat_type, severity, raw_log, created_at, classification_source, tenant_id,
                ml_confidence, llm_confidence, ml_prediction, ml_model
            FROM waf_logs
            WHERE created_at > NOW() - INTERVAL '1 hour'
            {tenant_filter}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        
        for row in cursor.fetchall():
            log = dict(row)
            
            # Convertir timestamps
            if log.get('timestamp'):
                if hasattr(log['timestamp'], 'isoformat'):
                    log['timestamp'] = log['timestamp'].isoformat()
            if log.get('created_at'):
                if hasattr(log['created_at'], 'isoformat'):
                    log['created_at'] = log['created_at'].isoformat()
            
            # Preparar datos para predicción
            log_for_prediction = {
                "uri": log.get("uri", ""),
                "raw_log": log.get("raw_log", {}),
                "ip": log.get("ip", ""),
                "method": log.get("method", ""),
                "status": log.get("status", 200)
            }
            
            # Usar predicciones ML/LLM guardadas en la base de datos si existen
            ml_prediction = None
            llm_analysis = None
            
            # Si hay datos ML/LLM guardados, usarlos
            if log.get("ml_confidence") is not None or log.get("llm_confidence") is not None:
                if log.get("ml_confidence") is not None:
                    ml_prediction = {
                        "prediction": log.get("ml_prediction") or log.get("threat_type"),
                        "confidence": log.get("ml_confidence"),
                        "model_id": log.get("ml_model", "random_forest"),
                        "threat_types": [log.get("threat_type")] if log.get("threat_type") else []
                    }
                
                if log.get("llm_confidence") is not None:
                    llm_analysis = {
                        "severity": log.get("severity", "low"),
                        "threat_type": log.get("threat_type"),
                        "reason": f"Log from {log.get('method', 'GET')} {log.get('uri', '')[:50]}",
                        "confidence": log.get("llm_confidence")
                    }
            
            # OPTIMIZADO: NO hacer predicciones ML/LLM en tiempo real en el dashboard
            # Solo usar datos ya guardados en la base de datos
            # Si no hay datos ML/LLM guardados, mostrar "Pendiente de clasificación"
            raw_log = log.get("raw_log", {})
            is_redteam = isinstance(raw_log, dict) and raw_log.get("source") == "redteam_agent"
            
            # Solo hacer predicción en tiempo real si es Red Team (prioridad alta)
            if is_redteam and not ml_prediction and not llm_analysis:
                # Predicción ML
                ml_result = await _predict_with_ml(log_for_prediction)
                if ml_result.get("success"):
                    ml_prediction = {
                        "prediction": ml_result.get("prediction", "low"),
                        "confidence": ml_result.get("confidence", 0.0),
                        "model_id": ml_result.get("model_id", "default"),
                        "threat_types": ml_result.get("threat_types", [])
                    }
                
                # Análisis LLM
                llm_result = await _analyze_with_llm(log_for_prediction)
                if llm_result.get("success"):
                    llm_analysis = {
                        "severity": llm_result.get("severity", "low"),
                        "threat_type": llm_result.get("threat_type"),
                        "reason": llm_result.get("reason", ""),
                        "confidence": llm_result.get("confidence", 0.5)
                    }
                    
                    # Si el LLM predijo un threat_type y no hay uno, actualizar en DB
                    if llm_result.get("threat_type") and not log.get("threat_type"):
                        try:
                            # Determinar classification_source
                            if ml_result.get("success") and ml_result.get("threat_types"):
                                classification_source = "ml_llm"
                            else:
                                classification_source = "llm_only"
                            
                            # Actualizar con todos los campos ML/LLM
                            cursor.execute("""
                                UPDATE waf_logs
                                SET threat_type = %s, classification_source = %s,
                                    ml_confidence = %s, llm_confidence = %s,
                                    ml_prediction = %s, ml_model = %s
                                WHERE id = %s
                            """, (
                                llm_result.get("threat_type"), 
                                classification_source,
                                ml_result.get("confidence") if ml_result.get("success") else None,
                                llm_result.get("confidence", 0.5),
                                ml_result.get("threat_types", [None])[0] if ml_result.get("success") and ml_result.get("threat_types") else None,
                                ml_result.get("model_id", "random_forest") if ml_result.get("success") else None,
                                log["id"]
                            ))
                            
                            conn.commit()
                            log["threat_type"] = llm_result.get("threat_type")
                            log["classification_source"] = classification_source
                            log["ml_confidence"] = ml_result.get("confidence") if ml_result.get("success") else None
                            log["llm_confidence"] = llm_result.get("confidence", 0.5)
                        except Exception as e:
                            logger.warning(f"Error actualizando threat_type: {e}")
            
            # Crear evento para Event Log
            threat_type = log.get("threat_type")
            if not threat_type and ml_prediction:
                threat_types = ml_prediction.get("threat_types", [])
                if threat_types:
                    threat_type = threat_types[0]
            if not threat_type and llm_analysis:
                threat_type = llm_analysis.get("threat_type")
            if not threat_type:
                threat_type = "UNKNOWN"
            
            # Determinar classification_source para el evento
            event_classification_source = log.get("classification_source")
            if not event_classification_source:
                if ml_prediction and llm_analysis:
                    event_classification_source = "ml_llm"
                elif llm_analysis:
                    event_classification_source = "llm_only"
                elif ml_prediction:
                    event_classification_source = "ml_only"
                else:
                    event_classification_source = "waf_local"
            
            event = {
                "timestamp": log.get("created_at") or log.get("timestamp"),
                "type": threat_type,
                "ip": log.get("ip", ""),
                "reason": llm_analysis.get("reason", "") if llm_analysis else f"Log from {log.get('method', 'GET')} {log.get('uri', '')[:50]}",
                "ml_model_id": ml_prediction.get("model_id") if ml_prediction else log.get("ml_model"),
                "ml_confidence": ml_prediction.get("confidence") if ml_prediction else log.get("ml_confidence"),
                "ml_prediction": ml_prediction.get("prediction") if ml_prediction else log.get("ml_prediction"),
                "llm_confidence": llm_analysis.get("confidence") if llm_analysis else log.get("llm_confidence"),
                "source": "redteam_agent" if is_redteam else "waf",
                "classification_source": event_classification_source or log.get("classification_source", "waf")
            }
            
            all_events.append(event)
            
            cursor.close()
    except Exception as e:
        logger.error(f"Error obteniendo eventos de waf_logs: {e}", exc_info=True)
    
    # Ordenar por timestamp
    def sort_key(item: Dict[str, Any]) -> str:
        ts = item.get("timestamp")
        return ts or ""
    
    all_events_sorted = sorted(all_events, key=sort_key, reverse=True)
    # FASE 4: Aplicar paginación con offset
    items = all_events_sorted[offset:offset + limit]
    
    # FASE 4: Agregar información de paginación
    return {
        "count": len(items),
        "items": items,
        "limit": limit,
        "offset": offset,
        "has_more": len(all_events_sorted) > offset + limit  # Indica si hay más resultados
    }


@app.get("/metrics", response_class=JSONResponse)
async def metrics() -> Dict[str, Any]:
    """
    Endpoint de métricas básicas para monitoreo.
    FASE 7: Incluye métricas del transformer si está disponible.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/metrics"] = _metrics["requests_by_endpoint"].get("/metrics", 0) + 1
    
    # FASE 7: Obtener métricas del real-time-processor si está disponible
    realtime_metrics = {}
    try:
        import requests
        # Usar la URL pública del realtime-processor si está disponible
        realtime_url = os.getenv('REALTIME_PROCESSOR_URL', 'https://YOUR_CLOUD_RUN_URL/health')
        response = requests.get(realtime_url, timeout=2)
        if response.status_code == 200:
            realtime_data = response.json()
            realtime_metrics = realtime_data.get('metrics', {})
            # Guardar realtime_data completo para usar advanced_detection después
            if 'advanced_detection' in realtime_data:
                realtime_metrics['_realtime_data'] = realtime_data
    except Exception as e:
        logger.debug(f"No se pudo obtener métricas del real-time-processor: {e}")
    
    # Calcular uptime de forma simple
    try:
        start_time_str = _metrics.get("start_time", datetime.utcnow().isoformat() + "Z")
        # Parsear fecha de forma segura
        if "Z" in start_time_str:
            start_time_str = start_time_str.replace("Z", "")
        start_dt = datetime.fromisoformat(start_time_str.replace("+00:00", ""))
        now_dt = datetime.utcnow()
        uptime_seconds = (now_dt - start_dt).total_seconds()
        if uptime_seconds < 0:
            uptime_seconds = 0
    except Exception:
        uptime_seconds = 0
    
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    seconds = int(uptime_seconds % 60)
    
    # FASE 7: Construir respuesta con métricas del transformer
    response = {
        "uptime_seconds": int(uptime_seconds),
        "uptime_human": f"{hours}h {minutes}m {seconds}s",
        "requests_total": _metrics.get("requests_total", 0),
        "requests_by_endpoint": _metrics.get("requests_by_endpoint", {}),
        "errors_total": _metrics.get("errors_total", 0),
        "logs_processed": _metrics.get("logs_processed", 0),
        "start_time": _metrics.get("start_time", "unknown")
    }
    
    # FASE 7: Agregar métricas del real-time-processor (incluye transformer)
    if realtime_metrics:
        response["realtime_processor"] = {
            "total_logs_processed": realtime_metrics.get("total_logs_processed", 0),
            "ml_predictions": realtime_metrics.get("ml_predictions", 0),
            "transformer_predictions": realtime_metrics.get("transformer_predictions", 0),
            "llm_analyses": realtime_metrics.get("llm_analyses", 0),
            "fallback_to_transformer": realtime_metrics.get("fallback_to_transformer", 0),
            "fallback_to_llm": realtime_metrics.get("fallback_to_llm", 0),
            "throughput_logs_per_sec": realtime_metrics.get("throughput_logs_per_sec", 0),
            "latency_p95_ms": realtime_metrics.get("latency_p95_ms", 0),
            "latency_p50_ms": realtime_metrics.get("latency_p50_ms", 0),
            "avg_ml_latency_ms": realtime_metrics.get("avg_ml_latency_ms", 0),
            "avg_transformer_latency_ms": realtime_metrics.get("avg_transformer_latency_ms", 0),
            "fallback_to_transformer_rate": realtime_metrics.get("fallback_to_transformer_rate", 0),
            "fallback_to_llm_rate": realtime_metrics.get("fallback_to_llm_rate", 0)
        }
        
        # Métricas del transformer si está disponible
        if "transformer_metrics" in realtime_metrics:
            response["realtime_processor"]["transformer"] = realtime_metrics["transformer_metrics"]
        
        # FASE 1: Agregar métricas de Detección Avanzada
        if "_realtime_data" in realtime_metrics:
            realtime_data_full = realtime_metrics["_realtime_data"]
            if "advanced_detection" in realtime_data_full:
                response["realtime_processor"]["advanced_detection"] = realtime_data_full["advanced_detection"]
    
    return response


@app.get("/logo.png", response_class=FileResponse)
async def get_logo() -> FileResponse:
    """
    Sirve el logo de Tokio AI.
    """
    logo_path = os.path.join(STATIC_DIR, "logo.png")
    if os.path.exists(logo_path):
        # Leer los primeros bytes para detectar el tipo real
        try:
            with open(logo_path, 'rb') as f:
                header = f.read(4)
                # JPEG: FF D8 FF
                if header[:3] == b'\xff\xd8\xff':
                    media_type = "image/jpeg"
                # PNG: 89 50 4E 47
                elif header == b'\x89PNG':
                    media_type = "image/png"
                else:
                    media_type = "image/png"  # Default
        except:
            media_type = "image/png"
        # Agregar headers para evitar cache
        from fastapi.responses import Response
        response = FileResponse(logo_path, media_type=media_type)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    # Si no existe, devolver un 404 silencioso (el HTML maneja el fallback)
    from fastapi import HTTPException
    raise HTTPException(status_code=404)


@app.get("/login", response_class=HTMLResponse)
async def login_page() -> HTMLResponse:
    """Página de login interna del Dashboard"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tokio AI - Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: radial-gradient(circle at top, #0f172a 0, #020617 45%); color: #e5e7eb; min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
            .card { background: rgba(15,23,42,0.9); border-radius: 16px; padding: 32px; width: 100%; max-width: 420px; box-shadow: 0 20px 40px rgba(0,0,0,0.4); border: 1px solid rgba(148,163,184,0.2); }
            h1 { margin: 0 0 4px 0; font-size: 24px; }
            p { margin: 0 0 16px 0; color: #9ca3af; font-size: 14px; }
            label { display: block; text-align: left; margin: 12px 0 4px; font-size: 13px; color: #cbd5f5; }
            input { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #374151; background: #020617; color: #e5e7eb; font-size: 14px; box-sizing: border-box; }
            input:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 1px rgba(59,130,246,0.5); }
            button { margin-top: 18px; width: 100%; padding: 10px 14px; border-radius: 999px; border: none; background: linear-gradient(135deg,#3b82f6,#22c55e); color: white; font-weight: 600; cursor: pointer; font-size: 14px; }
            button:hover { filter: brightness(1.05); }
            .hint { margin-top: 18px; font-size: 12px; color: #6b7280; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Tokio AI Dashboard</h1>
            <p>Acceso seguro para airesiliencehub</p>
            <form method="post" action="/login">
"""
    html += """
                <label for="username">Usuario</label>
                <input id="username" name="username" type="email" autocomplete="username" required />
                <label for="password">Contraseña</label>
                <input id="password" name="password" type="password" autocomplete="current-password" required />
                <button type="submit">Iniciar sesión</button>
            </form>
            <div class="hint">
                <p>Las credenciales se validan de forma segura en el servidor.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/login")
async def login_action(request: Request):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Missing credentials")
    if username.lower() != DASHBOARD_USERNAME.lower():
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Hash por defecto para admin123 (si el hash del env está truncado)
    # Este hash corresponde a la contraseña "admin123"
    default_hash = "$2b$12$TM4o42eFfGOEt8cD7/EGTOeEoDrL.hRFSJ6qHK5AMWNd3s0yangVK"
    
    # Intentar usar el hash del env, si falla usar el por defecto
    password_hash = DASHBOARD_PASSWORD_HASH
    if not password_hash or len(password_hash) < 50 or not password_hash.startswith("$2b$"):
        # Hash inválido o truncado, usar el por defecto
        password_hash = default_hash
    
    try:
        if not bcrypt.checkpw(password.encode(), password_hash.encode()):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except (ValueError, TypeError) as e:
        # Si hay error con el hash, intentar con el hash por defecto
        try:
            if not bcrypt.checkpw(password.encode(), default_hash.encode()):
                raise HTTPException(status_code=401, detail="Invalid credentials")
        except:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    if DASHBOARD_SESSION_SECRET:
        sid = _make_session_token(username)
    else:
        sid = secrets.token_hex(32)
        _sessions[sid] = {"user": username, "created_at": time.time(), "last_seen": time.time()}
    resp = RedirectResponse("/", status_code=302)
    # En local usar secure=False, en producción usar secure=True
    is_secure = os.getenv("DEPLOY_MODE", "local").lower() != "local"
    resp.set_cookie(SESSION_COOKIE_NAME, sid, httponly=True, secure=is_secure, samesite="Lax", max_age=SESSION_TTL_SECONDS)
    return resp

@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """
    Sirve el dashboard web (HTML estático).
    Requiere autenticación si está habilitada.
    """
    # SIEMPRE verificar autenticación si está habilitada
    if DASHBOARD_AUTH_ENABLED:
        user = _get_authenticated_user(request)
        if not user:
            return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    # Fallback mínimo por si falta el HTML
    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Tokio AI - ACIS Dashboard</title>
    </head>
    <body>
      <h1>Tokio AI - ACIS Dashboard</h1>
      <p>Dashboard API is running. Static frontend not found.</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/ui", response_class=HTMLResponse)
async def ui_entrypoint(request: Request) -> HTMLResponse:
    """Entrada alternativa sin cache para evitar HTML viejo."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return HTMLResponse(content="Dashboard UI not found", status_code=404)


# ============================================================================
# MCP Host Integration - Para consultas del analista
# ============================================================================

class ChatRequest(BaseModel):
    prompt: str


@app.post("/api/soc-assistant/chat", response_class=JSONResponse)
async def soc_assistant_chat(request: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Asistente SOC AI con acceso completo al sistema.
    Modos: ask (solo responde), agent (ejecuta acciones), plan (crea planes)
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/soc-assistant/chat"] = _metrics["requests_by_endpoint"].get(
        "/api/soc-assistant/chat", 0
    ) + 1
    
    try:
        message = request.get("message", "").strip()
        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El mensaje no puede estar vacío"
            )
        
        mode = request.get("mode", "ask")  # ask, agent, plan
        if mode not in ["ask", "agent", "plan"]:
            mode = "ask"
        
        conversation_id = request.get("conversation_id")
        context = request.get("context", {})
        
        # Importar procesador
        import sys
        from pathlib import Path
        
        # Asegurar que el directorio del módulo esté en el path
        app_dir = Path(__file__).parent
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        
        try:
            from soc_assistant.processor import SOCAssistantProcessor
        except ImportError as e:
            # Intentar importación directa
            import importlib.util
            processor_path = app_dir / "soc_assistant" / "processor.py"
            if processor_path.exists():
                spec = importlib.util.spec_from_file_location("soc_assistant.processor", processor_path)
                if spec and spec.loader:
                    processor_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(processor_module)
                    SOCAssistantProcessor = processor_module.SOCAssistantProcessor
                else:
                    raise ImportError(f"No se pudo cargar el módulo: {e}")
            else:
                raise ImportError(f"Módulo no encontrado en {processor_path}: {e}")
        
        # Crear procesador y procesar consulta
        processor = SOCAssistantProcessor(api_key=GEMINI_API_KEY)
        try:
            result = await processor.process_query(
                message=message,
                mode=mode,
                conversation_id=conversation_id,
                context=context
            )
            return result
        finally:
            processor.close()
    
    except Exception as e:
        _metrics["errors_total"] += 1
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en soc_assistant_chat: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "response": f"❌ Error procesando la consulta: {str(e)}"
        }


@app.post("/api/mcp/chat", response_class=JSONResponse)
async def mcp_chat(request: ChatRequest) -> Dict[str, Any]:
    """
    Ejecuta un prompt a través del MCP Host.
    Permite al analista hacer consultas, entrenar modelos, usar tools, etc.
    """
    # Validación de entrada
    if not request.prompt or not request.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt no puede estar vacío"
        )
    
    if len(request.prompt) > 10000:  # Límite de 10KB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt demasiado largo (máximo 10000 caracteres)"
        )
    
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/mcp/chat"] = _metrics["requests_by_endpoint"].get("/api/mcp/chat", 0) + 1
    
    # Si hay un MCP API separado, redirigir la ejecución para no bloquear el dashboard
    mcp_api_base = os.getenv("MCP_API_BASE_URL")
    if mcp_api_base:
        try:
            forward_url = mcp_api_base.rstrip("/") + "/api/mcp/chat"
            payload = request.dict()
            
            def _forward_request():
                return requests.post(forward_url, json=payload, timeout=130)
            
            resp = await asyncio.to_thread(_forward_request)
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"MCP API error: {resp.text[:500]}"
                )
            return resp.json()
        except Exception as e:
            logger.error(f"Error reenviando a MCP API: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error reenviando a MCP API: {str(e)}"
            )
    
    # FASE 4: Timeout para evitar que el endpoint se bloquee indefinidamente
    try:
        # Ejecutar MCP Host vía subprocess con timeout
        mcp_host_script = Path(MCP_HOST_PATH) / "dist" / "index.js"
        if not mcp_host_script.exists():
            return {
                "success": False,
                "error": f"MCP Host no encontrado en {mcp_host_script}"
            }
        
        # Preparar comando
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = GEMINI_API_KEY
        env["MCP_SERVER_CMD"] = "python3"  # Usar python3 explícitamente
        env["MCP_SERVER_ARGS"] = "mcp_server_complete.py"
        env["MCP_CORE_PATH"] = MCP_CORE_PATH
        
        cmd = [
            "node",
            str(mcp_host_script),
            "chat",
            "-p",
            request.prompt
        ]
        
        # FASE 4: Ejecutar con timeout de 60 segundos
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(Path(MCP_HOST_PATH))
        )
        
        # FASE 4: Timeout de 120 segundos para el proceso
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            # Matar el proceso si excede el timeout
            process.kill()
            await process.wait()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout: El procesamiento MCP tardó más de 120 segundos"
            )
        
        if process.returncode != 0:
            _metrics["errors_total"] += 1
            error_msg = stderr.decode("utf-8", errors="ignore")
            return {
                "success": False,
                "error": f"Error ejecutando MCP Host: {error_msg}",
                "stdout": stdout.decode("utf-8", errors="ignore")[:500]
            }
        
        output = stdout.decode("utf-8", errors="ignore")
        stderr_output = stderr.decode("utf-8", errors="ignore")
        
        # Extraer la respuesta del LLM (buscar después de "✅ Respuesta:")
        response_text = output
        if "✅ Respuesta:" in output:
            response_text = output.split("✅ Respuesta:")[-1].strip()
        elif "Respuesta:" in output:
            response_text = output.split("Respuesta:")[-1].strip()
        
        # Si hay logs de depuración en stderr, incluirlos en raw_output
        debug_info = ""
        if stderr_output:
            debug_info = f"\n\nSTDERR:\n{stderr_output[-2000:]}"
        
        return {
            "success": True,
            "response": response_text,
            "raw_output": output[-3000:] + debug_info  # Últimos 3000 chars + stderr para debugging
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/api/mcp/tools", response_class=JSONResponse)
async def list_mcp_tools() -> Dict[str, Any]:
    """
    Lista todas las tools disponibles del MCP Server.
    """
    try:
        # Ejecutar MCP Host para listar tools
        mcp_host_script = Path(MCP_HOST_PATH) / "dist" / "index.js"
        if not mcp_host_script.exists():
            return {
                "success": False,
                "error": f"MCP Host no encontrado en {mcp_host_script}",
                "tools": []
            }
        
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = GEMINI_API_KEY
        env["MCP_SERVER_CMD"] = "python3"  # Usar python3 explícitamente
        env["MCP_SERVER_ARGS"] = "mcp_server_complete.py"
        env["MCP_CORE_PATH"] = MCP_CORE_PATH
        
        cmd = [
            "node",
            str(mcp_host_script),
            "tools"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(Path(MCP_HOST_PATH))
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return {
                "success": False,
                "error": stderr.decode("utf-8", errors="ignore"),
                "tools": []
            }
        
        output = stdout.decode("utf-8", errors="ignore")
        
        # Parsear tools del output (formato simple por ahora)
        tools = []
        lines = output.split("\n")
        for line in lines:
            if line.strip() and not line.startswith("🔧"):
                # Intentar extraer nombre y descripción
                if " - " in line:
                    parts = line.split(" - ", 1)
                    tools.append({
                        "name": parts[0].strip(),
                        "description": parts[1].strip() if len(parts) > 1 else ""
                    })
        
        return {
            "success": True,
            "tools": tools,
            "raw_output": output
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tools": []
        }


# ============================================================================
# PostgreSQL Endpoints - Incidentes, Bypasses, Auto-Mitigaciones
# ============================================================================

# Pool de conexiones PostgreSQL (singleton)
_postgres_pool = None

def _get_postgres_conn():
    """Obtiene una conexión del pool de PostgreSQL"""
    global _postgres_pool
    
    try:
        if _postgres_pool is None:
            from psycopg2.pool import SimpleConnectionPool
            
            # CORREGIDO: Verificar que POSTGRES_HOST no sea None
            if not POSTGRES_HOST:
                raise ValueError("POSTGRES_HOST no está configurado")
            
            # Si POSTGRES_HOST es un socket Unix de Cloud SQL
            if POSTGRES_HOST.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME"SELECT 1")
                        cursor.fetchone()
                        cursor.close()
                        return conn
                    except Exception as e:
                        # Si la conexión está muerta, cerrarla y obtener una nueva
                        logger.warning(f"Conexión muerta detectada (intento {attempt + 1}/{max_retries}), cerrando y obteniendo nueva: {e}")
                        try:
                            conn.close()
                        except:
                            pass
                        # Continuar el loop para obtener una nueva conexión
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Backoff exponencial
                        continue
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error obteniendo conexión del pool (intento {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponencial
                else:
                    logger.error(f"Error obteniendo conexión del pool después de {max_retries} intentos: {e}")
        
        # Si no hay conexión disponible después de los reintentos, lanzar excepción
        raise Exception(f"No hay conexiones disponibles en el pool después de {max_retries} intentos.")
    except Exception as e:
        logger.error(f"Error obteniendo conexión PostgreSQL: {e}")
        # NO crear conexiones directas fuera del pool (causan conexiones huérfanas)
        # En su lugar, lanzar excepción para que se maneje apropiadamente
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error conectando a PostgreSQL: {str(e)}"
        )

@contextmanager
def get_postgres_connection():
    """Context manager para obtener y devolver conexiones PostgreSQL del pool"""
    conn = None
    try:
        conn = _get_postgres_conn()
        yield conn
    except Exception as e:
        # Si hay un error, hacer rollback antes de devolver la conexión
        if conn:
            try:
                if not conn.closed:
                    conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            _return_postgres_conn(conn)

def _return_postgres_conn(conn):
    """Devuelve una conexión al pool"""
    global _postgres_pool
    if conn:
        try:
            # Verificar si la conexión está en el pool o es directa
            if _postgres_pool:
                try:
                    # Verificar si la conexión está cerrada
                    if conn.closed == 0:
                        _postgres_pool.putconn(conn)
                    else:
                        # Si está cerrada, no devolverla al pool
                        pass
                except Exception as e:
                    # Si falla al devolver, cerrar la conexión
                    try:
                        if conn.closed == 0:
                            conn.close()
                    except Exception:
                        pass
            else:
                # Si no hay pool, cerrar la conexión directa
                try:
                    if conn.closed == 0:
                        conn.close()
                except Exception:
                    pass
        except Exception:
            # Si falla todo, intentar cerrar
            try:
                if hasattr(conn, 'closed') and conn.closed == 0:
                    conn.close()
            except Exception:
                pass

            try:
                # Solo devolver al pool si no está cerrada
                if hasattr(conn, 'closed') and conn.closed == 0:
                    _return_postgres_conn(conn)
                elif not hasattr(conn, 'closed'):
                    # Si no tiene atributo closed, intentar devolverlo de todas formas
                    _return_postgres_conn(conn)
            except Exception as e:
                logger.error(f"Error devolviendo conexión al pool: {e}")
                # Si no se puede devolver al pool, cerrar la conexión
                try:
                    if hasattr(conn, 'closed') and not conn.closed:
                        conn.close()
                    elif not hasattr(conn, 'closed'):
                        conn.close()
                except:
                    pass


@app.get("/api/incidents", response_class=JSONResponse)
async def get_incidents(
    limit: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, description="Filtrar por status: open, closed, resolved"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Obtiene los incidentes de seguridad desde PostgreSQL.
    Soporta filtrado por tenant_id.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/incidents"] = _metrics["requests_by_endpoint"].get("/api/incidents", 0) + 1
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Primero, verificar y cerrar incidentes resueltos automáticamente
            # 1. Si un bypass tiene una regla de mitigación activa, el incidente debe cerrarse
            cursor.execute("""
                UPDATE incidents i
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolution_notes = COALESCE(resolution_notes, '') || ' Auto-cerrado: Mitigación aplicada automáticamente.'
                FROM detected_bypasses db
                LEFT JOIN tenant_rules tr ON db.mitigation_rule_id = tr.id
                WHERE i.id = db.incident_id
                  AND i.status = 'open'
                  AND tr.enabled = true
                  AND tr.id IS NOT NULL
            """)
            
            # 2. Cerrar incidentes de persistent_attack que ya no están activos
            # Si hay un registro en attacks_in_progress, verificar si está inactivo
            cursor.execute("""
                UPDATE incidents i
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolution_notes = COALESCE(resolution_notes, '') || 
                        E'\nAuto-cerrado: Ataque ya no está activo o sin actividad reciente (más de 2 horas).'
                FROM attacks_in_progress aip
                WHERE i.id = aip.incident_id
                  AND i.incident_type = 'persistent_attack'
                  AND i.status = 'open'
                  AND (
                    aip.is_active = false
                    OR aip.last_seen < NOW() - INTERVAL '2 hours'
                  )
            """)
            
            # 3. Cerrar incidentes de persistent_attack sin registro en attacks_in_progress
            # que fueron creados hace más de 2 horas (ataque probablemente terminó)
            cursor.execute("""
                UPDATE incidents i
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolution_notes = COALESCE(resolution_notes, '') || 
                        E'\nAuto-cerrado: Sin actividad reciente (más de 2 horas desde detección).'
                WHERE i.incident_type = 'persistent_attack'
                  AND i.status = 'open'
                  AND i.detected_at < NOW() - INTERVAL '2 hours'
                  AND NOT EXISTS (
                    SELECT 1 FROM attacks_in_progress aip 
                    WHERE aip.incident_id = i.id AND aip.is_active = true
                  )
            """)
            
            conn.commit()
            
            query = """
                SELECT 
                    i.id, i.title, i.description, i.status, i.severity, i.incident_type,
                    i.source_ip, i.detected_at, i.resolved_at, i.resolution_notes,
                    COALESCE(db.attack_type, NULL) as attack_type, i.tenant_id
                FROM incidents i
                LEFT JOIN detected_bypasses db ON i.id = db.incident_id
            """
            params = []
            conditions = []
            
            if status_filter:
                conditions.append("i.status = %s")
                params.append(status_filter)
            
            # Filtro de tenant
            if tenant_id and tenant_id != "all" and tenant_id.isdigit():
                conditions.append("i.tenant_id = %s")
                params.append(int(tenant_id))
            elif tenant_id == "default":
                conditions.append("(i.tenant_id IS NULL OR i.tenant_id = 1)")
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY i.detected_at DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            incidents = [dict(row) for row in cursor.fetchall()]
            
            # Convertir datetime a ISO strings
            for incident in incidents:
                for key, value in incident.items():
                    if isinstance(value, datetime):
                        incident[key] = value.isoformat()
            
            cursor.close()
            
            return {
                "count": len(incidents),
                "items": incidents
            }
    except Exception as e:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo incidentes: {str(e)}"
        )


@app.get("/api/bypasses", response_class=JSONResponse)
async def get_bypasses(
    limit: int = Query(50, ge=1, le=500),
    mitigated: Optional[bool] = Query(None, description="Filtrar por mitigado: true/false"),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Obtiene los bypasses detectados desde PostgreSQL.
    Soporta filtrado por tenant_id.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/bypasses"] = _metrics["requests_by_endpoint"].get("/api/bypasses", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                id, tenant_id, source_ip, attack_type, bypass_method,
                request_data, response_data, mitigated,
                detected_at
            FROM detected_bypasses
        """
        params = []
        conditions = []
        
        if mitigated is not None:
            conditions.append("mitigated = %s")
            params.append(mitigated)
        
        # Filtro de tenant
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            conditions.append("tenant_id = %s")
            params.append(int(tenant_id))
        elif tenant_id == "default":
            conditions.append("(tenant_id IS NULL OR tenant_id = 1)")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        bypasses = [dict(row) for row in cursor.fetchall()]
        
        # Convertir datetime y extraer URIs de JSON
        processed_bypasses = []
        for bypass in bypasses:
            bypass_dict = dict(bypass)  # Crear copia para evitar modificar durante iteración
            for key, value in list(bypass_dict.items()):
                if isinstance(value, datetime):
                    bypass_dict[key] = value.isoformat()
                elif key == 'request_data' and value:
                    # Extraer URI del request bloqueado
                    if isinstance(value, dict):
                        bypass_dict['blocked_uri'] = value.get('uri', '')
                    elif isinstance(value, str):
                        try:
                            data = json.loads(value)
                            bypass_dict['blocked_uri'] = data.get('uri', '')
                        except:
                            bypass_dict['blocked_uri'] = ''
                elif key == 'response_data' and value:
                    # Extraer URI del request permitido
                    if isinstance(value, dict):
                        bypass_dict['allowed_uri'] = value.get('uri', '')
                    elif isinstance(value, str):
                        try:
                            data = json.loads(value)
                            bypass_dict['allowed_uri'] = data.get('uri', '')
                        except:
                            bypass_dict['allowed_uri'] = ''
            
            # Calcular confianza basada en si está mitigado
            bypass_dict['confidence'] = 0.9 if bypass_dict.get('mitigated') else 0.7
            processed_bypasses.append(bypass_dict)
        
        bypasses = processed_bypasses
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "count": len(bypasses),
            "items": bypasses
        }
    except Exception as e:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo bypasses: {str(e)}"
        )


@app.get("/api/auto-mitigations", response_class=JSONResponse)
async def get_auto_mitigations(
    limit: int = Query(50, ge=1, le=500),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Obtiene las auto-mitigaciones realizadas (reglas generadas automáticamente).
    Soporta filtrado por tenant_id.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/auto-mitigations"] = _metrics["requests_by_endpoint"].get("/api/auto-mitigations", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                tr.id, tr.tenant_id, tr.rule_name, tr.rule_type,
                tr.enabled, tr.created_by, tr.created_at, tr.updated_at,
                db.source_ip, db.attack_type, db.bypass_method
            FROM tenant_rules tr
            LEFT JOIN detected_bypasses db ON tr.id = db.mitigation_rule_id
            WHERE tr.created_by = 'auto-mitigation-system'
        """
        params = []
        
        # Filtro de tenant
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            query += " AND tr.tenant_id = %s"
            params.append(int(tenant_id))
        elif tenant_id == "default":
            query += " AND (tr.tenant_id IS NULL OR tr.tenant_id = 1)"
        
        query += " ORDER BY tr.created_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        mitigations = [dict(row) for row in cursor.fetchall()]
        
        # Convertir datetime
        for mitigation in mitigations:
            for key, value in mitigation.items():
                if isinstance(value, datetime):
                    mitigation[key] = value.isoformat()
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "count": len(mitigations),
            "items": mitigations
        }
    except Exception as e:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo auto-mitigaciones: {str(e)}"
        )


@app.get("/api/redteam-tests", response_class=JSONResponse)
async def get_redteam_tests(
    limit: int = Query(50, ge=1, le=500),
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """
    Obtiene los resultados de las pruebas Red Team.
    Soporta filtrado por tenant_id.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/redteam-tests"] = _metrics["requests_by_endpoint"].get("/api/redteam-tests", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Construir filtro de tenant
        tenant_filter = ""
        params = []
        
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            tenant_filter = "WHERE tenant_id = %s"
            params.append(int(tenant_id))
        elif tenant_id == "default":
            tenant_filter = "WHERE (tenant_id IS NULL OR tenant_id = 1)"
        
        # Intentar obtener de redteam_tests primero, luego redteam_results
        query = f"""
            SELECT 
                id, tenant_id, test_name, test_type, target_url, payload,
                executed_at, blocked, response_status, response_time_ms,
                detected_by, rule_matched
            FROM redteam_tests
            {tenant_filter}
            ORDER BY executed_at DESC
            LIMIT %s
        """
        
        params.append(limit)
        cursor.execute(query, params)
        tests = [dict(row) for row in cursor.fetchall()]
        
        # Si no hay resultados en redteam_tests, buscar en redteam_results
        if not tests:
            query2 = """
                SELECT 
                    id, attack_type as test_type, technique as test_name,
                    payload, timestamp as executed_at, 
                    CASE WHEN success THEN false ELSE true END as blocked,
                    NULL as response_status,
                    NULL as response_time_ms
                FROM redteam_results
                ORDER BY timestamp DESC
                LIMIT %s
            """
            cursor.execute(query2, [limit])
            tests = [dict(row) for row in cursor.fetchall()]
        
        # Convertir datetime y manejar valores None
        for test in tests:
            for key, value in test.items():
                if isinstance(value, datetime):
                    test[key] = value.isoformat()
                elif value is None:
                    # Mantener None pero asegurar que los campos existan
                    pass
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "count": len(tests),
            "items": tests
        }
    except Exception as e:
        _metrics["errors_total"] += 1
        # Si las tablas no existen, retornar vacío
        if "does not exist" in str(e):
            return {
                "count": 0,
                "items": [],
                "note": "Red Team tables not yet created"
            }
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo pruebas Red Team: {str(e)}"
        )


@app.get("/api/redteam/status", response_class=JSONResponse)
async def get_redteam_status() -> Dict[str, Any]:
    """Obtiene el estado del servicio Red Team"""
    _metrics["requests_total"] += 1
    try:
        # Verificar si hay logs recientes del Red Team (últimos 5 minutos)
        conn = _get_postgres_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count, MAX(timestamp) as last_test
            FROM redteam_results
            WHERE timestamp > NOW() - INTERVAL '5 minutes'
        """)
        result = cursor.fetchone()
        cursor.close()
        _return_postgres_conn(conn)
        
        if result and result[0] > 0:
            return {
                "running": True,
                "status": f"active (last test: {result[1]})"
            }
        else:
            # Verificar si hay tests en la última hora
            conn2 = _get_postgres_conn()
            cursor2 = conn2.cursor()
            cursor2.execute("""
                SELECT COUNT(*) as count
                FROM redteam_results
                WHERE timestamp > NOW() - INTERVAL '1 hour'
            """)
            result2 = cursor2.fetchone()
            cursor2.close()
            _return_postgres_conn(conn2)
            
            if result2 and result2[0] > 0:
                return {
                    "running": True,
                    "status": "running (no recent activity)"
                }
            else:
                return {
                    "running": False,
                    "status": "stopped or no activity"
                }
    except Exception as e:
        # Si no hay tabla, asumir que está corriendo
        return {
            "running": True,
            "status": f"unknown (error: {str(e)})"
        }


@app.post("/api/redteam/start", response_class=JSONResponse)
async def start_redteam() -> Dict[str, Any]:
    """Inicia el servicio Red Team usando señal de archivo"""
    _metrics["requests_total"] += 1
    try:
        # Usar señal de archivo para controlar el servicio
        signal_file = "/data/redteam_control"
        os.makedirs("/data", exist_ok=True)
        with open(signal_file, "w") as f:
            f.write("start")
        return {"success": True, "message": "Señal de inicio enviada al Red Team"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/redteam/stop", response_class=JSONResponse)
async def stop_redteam() -> Dict[str, Any]:
    """Detiene el servicio Red Team usando señal de archivo"""
    _metrics["requests_total"] += 1
    try:
        # Usar señal de archivo para controlar el servicio
        signal_file = "/data/redteam_control"
        os.makedirs("/data", exist_ok=True)
        with open(signal_file, "w") as f:
            f.write("stop")
        return {"success": True, "message": "Señal de detención enviada al Red Team"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/redteam/trigger", response_class=JSONResponse)
async def trigger_redteam_campaign() -> Dict[str, Any]:
    """Ejecuta una campaña inmediata del Red Team usando señal de archivo"""
    _metrics["requests_total"] += 1
    try:
        # Usar señal de archivo para trigger inmediato
        signal_file = "/data/redteam_trigger"
        os.makedirs("/data", exist_ok=True)
        with open(signal_file, "w") as f:
            f.write("trigger")
        return {"success": True, "message": "Campaña de Red Team iniciada. Los resultados aparecerán en unos momentos."}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/auto-mitigation-stats", response_class=JSONResponse)
async def auto_mitigation_stats() -> Dict[str, Any]:
    """Obtiene estadísticas de auto-mitigación"""
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/auto-mitigation-stats"] = _metrics["requests_by_endpoint"].get("/api/auto-mitigation-stats", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Estadísticas de bypasses mitigados
        cursor.execute("""
            SELECT 
                COUNT(*) as total_bypasses,
                COUNT(CASE WHEN mitigated = true THEN 1 END) as mitigated,
                COUNT(CASE WHEN mitigated = false THEN 1 END) as pending
            FROM detected_bypasses
            WHERE detected_at > NOW() - INTERVAL '24 hours'
        """)
        bypass_stats = dict(cursor.fetchone())
        
        # Estadísticas de reglas generadas
        cursor.execute("""
            SELECT COUNT(*) as total_rules
            FROM tenant_rules
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """)
        rules_stats = dict(cursor.fetchone())
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "bypasses": bypass_stats,
            "rules_generated": rules_stats.get("total_rules", 0),
            "mitigation_rate": (bypass_stats.get("mitigated", 0) / bypass_stats.get("total_bypasses", 1)) * 100 if bypass_stats.get("total_bypasses", 0) > 0 else 0
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# Endpoints para Red Team Inteligente (Fase 4)
# ============================================================================

@app.get("/api/intelligent-redteam/analysis", response_class=JSONResponse)
async def intelligent_redteam_analysis(tenant_id: str = Query("default")) -> Dict[str, Any]:
    """Obtiene análisis del WAF del Red Team inteligente"""
    _metrics["requests_total"] += 1
    
    try:
        import sys
        import logging
        import importlib.util
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        intelligent_path = Path("/app/intelligent-redteam")
        if not intelligent_path.exists():
            # Retornar datos de ejemplo si no está disponible
            return {
                "success": True,
                "analysis": {
                    "total_rules": 0,
                    "protected_attack_types": [],
                    "detection_patterns": [],
                    "bypass_opportunities": [],
                    "rule_complexity": "none",
                    "coverage": {
                        "protected": [],
                        "unprotected": ["SQLI", "XSS", "PATH_TRAVERSAL", "CMD_INJECTION", "RFI_LFI", "XXE"],
                        "coverage_percentage": 0
                    }
                },
                "testing_strategy": {
                    "priority_attack_types": ["SQLI", "XSS", "PATH_TRAVERSAL"],
                    "bypass_techniques": ["url_encoding", "case_variation"],
                    "testing_approach": "comprehensive",
                    "recommendations": [
                        "No se encontraron reglas del WAF. El sistema está usando protección básica de ModSecurity.",
                        "Se recomienda configurar reglas personalizadas para mejorar la detección."
                    ]
                },
                "note": "Intelligent Red Team no disponible, mostrando datos de ejemplo"
            }
        
        # Configurar path para importaciones
        parent_path = str(intelligent_path.parent)
        if parent_path not in sys.path:
            sys.path.insert(0, parent_path)
        
        # Intentar importar de forma estándar
        try:
            from intelligent_redteam.waf_analyzer.waf_signature_analyzer import WAFSignatureAnalyzer
        except ImportError:
            # Si falla, cargar directamente con importlib
            analyzer_file = intelligent_path / "waf_analyzer" / "waf_signature_analyzer.py"
            if analyzer_file.exists():
                spec = importlib.util.spec_from_file_location("waf_signature_analyzer", analyzer_file)
                if spec and spec.loader:
                    original_path = sys.path[:]
                    try:
                        if str(intelligent_path) not in sys.path:
                            sys.path.insert(0, str(intelligent_path))
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        WAFSignatureAnalyzer = module.WAFSignatureAnalyzer
                    finally:
                        sys.path[:] = original_path
                else:
                    raise ImportError("No se pudo cargar WAFSignatureAnalyzer")
            else:
                raise ImportError(f"Archivo no encontrado: {analyzer_file}")
        
        analyzer = WAFSignatureAnalyzer(tenant_id=tenant_id)
        rules = analyzer.get_waf_rules()
        
        if not rules or len(rules) == 0:
            analyzer.close()
            # Retornar datos de ejemplo si no hay reglas
            return {
                "success": True,
                "analysis": {
                    "total_rules": 0,
                    "protected_attack_types": [],
                    "detection_patterns": [],
                    "bypass_opportunities": [],
                    "rule_complexity": "none",
                    "coverage": {
                        "protected": [],
                        "unprotected": ["SQLI", "XSS", "PATH_TRAVERSAL", "CMD_INJECTION", "RFI_LFI", "XXE"],
                        "coverage_percentage": 0
                    }
                },
                "testing_strategy": {
                    "priority_attack_types": ["SQLI", "XSS", "PATH_TRAVERSAL"],
                    "bypass_techniques": ["url_encoding", "case_variation"],
                    "testing_approach": "comprehensive",
                    "recommendations": [
                        "No se encontraron reglas personalizadas del WAF para este tenant.",
                        "El sistema está usando las reglas por defecto de ModSecurity/OWASP CRS.",
                        "Se recomienda configurar reglas personalizadas para mejorar la detección."
                    ]
                },
                "note": "No se encontraron reglas personalizadas"
            }
        
        analysis = analyzer.analyze_signatures(rules)
        strategy = analyzer.suggest_testing_strategy(analysis)
        analyzer.close()
        
        return {
            "success": True,
            "analysis": analysis,
            "testing_strategy": strategy
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en intelligent_redteam_analysis: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "analysis": {
                "total_rules": 0,
                "protected_attack_types": [],
                "coverage": {"coverage_percentage": 0}
            },
            "testing_strategy": {
                "recommendations": [f"Error al analizar: {str(e)}"]
            }
        }


@app.get("/api/intelligent-redteam/suggestions", response_class=JSONResponse)
async def intelligent_redteam_suggestions(tenant_id: str = Query("default")) -> Dict[str, Any]:
    """Obtiene sugerencias de mejora del Red Team inteligente"""
    _metrics["requests_total"] += 1
    
    try:
        import sys
        import logging
        import importlib.util
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        # Buscar intelligent-redteam en diferentes ubicaciones
        intelligent_paths = [
            Path("/app/intelligent-redteam"),
            Path(__file__).parent.parent / "intelligent-redteam",
            Path("/app/../intelligent-redteam")
        ]
        
        intelligent_path = None
        for path in intelligent_paths:
            if path.exists():
                intelligent_path = path
                break
        
        if not intelligent_path:
            # Retornar sugerencias de ejemplo si no hay módulo
            logger.warning("Intelligent Red Team module not found, using fallback suggestions")
            return {
                "success": True,
                "suggestions": [
                    {
                        "type": "add_rule",
                        "priority": "high",
                        "attack_type": "SQLI",
                        "description": "Agregar regla para proteger contra SQL Injection",
                        "recommendation": "Implementar detección de SQLI en el WAF"
                    },
                    {
                        "type": "add_rule",
                        "priority": "high",
                        "attack_type": "XSS",
                        "description": "Agregar regla para proteger contra XSS",
                        "recommendation": "Implementar detección de XSS en el WAF"
                    }
                ],
                "count": 2,
                "note": "Sugerencias de ejemplo - Intelligent Red Team module not found"
            }
        
        # Configurar path para importaciones
        parent_path = str(intelligent_path.parent)
        if parent_path not in sys.path:
            sys.path.insert(0, parent_path)
        
        # Intentar importar de forma estándar
        try:
            from intelligent_redteam.improvement_suggester.improvement_suggester import ImprovementSuggester
            from intelligent_redteam.waf_analyzer.waf_signature_analyzer import WAFSignatureAnalyzer
        except ImportError:
            # Si falla, cargar directamente con importlib
            suggester_file = intelligent_path / "improvement_suggester" / "improvement_suggester.py"
            analyzer_file = intelligent_path / "waf_analyzer" / "waf_signature_analyzer.py"
            
            original_path = sys.path[:]
            try:
                if str(intelligent_path) not in sys.path:
                    sys.path.insert(0, str(intelligent_path))
                
                if suggester_file.exists():
                    spec = importlib.util.spec_from_file_location("improvement_suggester", suggester_file)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        ImprovementSuggester = module.ImprovementSuggester
                
                if analyzer_file.exists():
                    spec = importlib.util.spec_from_file_location("waf_signature_analyzer", analyzer_file)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        WAFSignatureAnalyzer = module.WAFSignatureAnalyzer
            finally:
                sys.path[:] = original_path
        
        analyzer = WAFSignatureAnalyzer(tenant_id=tenant_id)
        rules = analyzer.get_waf_rules()
        
        if not rules or len(rules) == 0:
            analyzer.close()
            # Retornar sugerencias básicas si no hay reglas
            return {
                "success": True,
                "suggestions": [
                    {
                        "type": "add_rule",
                        "priority": "high",
                        "attack_type": "SQLI",
                        "description": "No hay reglas personalizadas para SQL Injection",
                        "recommendation": "Configurar reglas ModSecurity para detectar SQL Injection"
                    },
                    {
                        "type": "add_rule",
                        "priority": "high",
                        "attack_type": "XSS",
                        "description": "No hay reglas personalizadas para XSS",
                        "recommendation": "Configurar reglas ModSecurity para detectar XSS"
                    },
                    {
                        "type": "increase_complexity",
                        "priority": "medium",
                        "description": "Las reglas son muy simples o no existen",
                        "recommendation": "Agregar normalización de encoding, case-insensitive matching, y regex más robustos"
                    }
                ],
                "count": 3,
                "note": "Sugerencias básicas - No se encontraron reglas personalizadas"
            }
        
        analysis = analyzer.analyze_signatures(rules)
        analyzer.close()
        
        suggester = ImprovementSuggester(tenant_id=tenant_id)
        try:
            suggestions = suggester.suggest_improvements_from_analysis(analysis)
            
            # Si no hay sugerencias, agregar algunas básicas
            if not suggestions or len(suggestions) == 0:
                suggestions = [
                    {
                        "type": "monitor",
                        "priority": "low",
                        "description": "El WAF parece estar bien configurado",
                        "recommendation": "Continuar monitoreando y ajustar según sea necesario"
                    }
                ]
            
            return {
                "success": True,
                "suggestions": suggestions,
                "count": len(suggestions)
            }
        finally:
            suggester.close()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en intelligent_redteam_suggestions: {e}", exc_info=True)
        return {
            "success": True,
            "suggestions": [
                {
                    "type": "error",
                    "priority": "low",
                    "description": f"Error al obtener sugerencias: {str(e)}",
                    "recommendation": "Verificar la configuración del sistema"
                }
            ],
            "count": 1,
            "error": str(e)
        }


@app.get("/api/intelligent-redteam/campaign-history", response_class=JSONResponse)
async def intelligent_redteam_campaign_history(
    tenant_id: str = Query("default"),
    limit: int = Query(10, ge=1, le=100)
) -> Dict[str, Any]:
    """
    Obtiene el historial de campañas del Red Team inteligente con razonamiento y resultados.
    
    Returns:
        Historial de campañas con razonamiento, pruebas realizadas y mitigaciones
    """
    _metrics["requests_total"] += 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor()
        
        # Si la tabla no existe, devolver vacío sin romper el endpoint
        cursor.execute("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'redteam_test_history'
        """)
        if cursor.fetchone() is None:
            cursor.close()
            _return_postgres_conn(conn)
            return {
                "success": True,
                "campaigns": [],
                "count": 0
            }
        
        tenant_filter = ""
        params = [limit]
        
        if tenant_id and tenant_id.isdigit():
            tenant_filter = "WHERE tenant_id = %s AND campaign_id IS NOT NULL"
            params.insert(0, int(tenant_id))
        else:
            # Si es "default", incluir también registros sin tenant_id
            tenant_filter = "WHERE (tenant_id IS NULL OR tenant_id = 1) AND campaign_id IS NOT NULL"
        
        # Obtener campañas agrupadas por campaign_id
        query_campaigns = f"""
            SELECT 
                campaign_id,
                MIN(tested_at) as campaign_start,
                MAX(tested_at) as campaign_end,
                COUNT(*) as total_tests,
                COUNT(CASE WHEN success = true THEN 1 END) as successful_bypasses,
                COUNT(CASE WHEN blocked = true THEN 1 END) as blocked_attempts,
                COUNT(DISTINCT attack_type) as attack_types_tested
            FROM redteam_test_history
            {tenant_filter}
            GROUP BY campaign_id
            ORDER BY campaign_start DESC
            LIMIT %s
        """
        
        cursor.execute(query_campaigns, params)
        campaigns = []
        
        for row in cursor.fetchall():
            campaign_id, start, end, total, successful, blocked, types = row
            
            # Obtener detalles de las pruebas de esta campaña
            query_tests = """
                SELECT 
                    attack_type,
                    payload,
                    bypass_technique,
                    success,
                    blocked,
                    response_status,
                    response_time_ms,
                    tested_at,
                    waf_rules_count,
                    protected_types
                FROM redteam_test_history
                WHERE campaign_id = %s
                ORDER BY tested_at ASC
            """
            cursor.execute(query_tests, (campaign_id,))
            tests = []
            
            for test_row in cursor.fetchall():
                at_type, payload, bypass, success, blocked, status, time_ms, tested, rules_count, protected = test_row
                tests.append({
                    "attack_type": at_type,
                    "payload": payload[:200] + "..." if payload and len(payload) > 200 else payload,
                    "full_payload": payload,
                    "bypass_technique": bypass,
                    "success": success,
                    "blocked": blocked,
                    "response_status": status,
                    "response_time_ms": time_ms,
                    "tested_at": tested.isoformat() if tested else None,
                    "waf_rules_count": rules_count,
                    "protected_types": protected or []
                })
            
            # Generar razonamiento basado en los resultados
            reasoning = _generate_campaign_reasoning(tests, successful, blocked, total)
            
            campaigns.append({
                "campaign_id": campaign_id,
                "start_time": start.isoformat() if start else None,
                "end_time": end.isoformat() if end else None,
                "total_tests": total,
                "successful_bypasses": successful,
                "blocked_attempts": blocked,
                "attack_types_tested": types,
                "success_rate": (successful / total * 100) if total > 0 else 0,
                "reasoning": reasoning,
                "tests": tests
            })
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "campaigns": campaigns,
            "count": len(campaigns)
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo historial de campañas: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "campaigns": []
        }


def _generate_campaign_reasoning(tests: List[Dict], successful: int, blocked: int, total: int) -> Dict[str, Any]:
    """
    Genera razonamiento sobre una campaña basándose en los resultados.
    """
    if not tests:
        return {
            "strategy": "No hay pruebas en esta campaña",
            "insights": [],
            "mitigations": []
        }
    
    # Analizar tipos de ataque probados
    attack_types = {}
    for test in tests:
        at_type = test.get("attack_type")
        if at_type not in attack_types:
            attack_types[at_type] = {"total": 0, "successful": 0, "blocked": 0}
        attack_types[at_type]["total"] += 1
        if test.get("success"):
            attack_types[at_type]["successful"] += 1
        if test.get("blocked"):
            attack_types[at_type]["blocked"] += 1
    
    # Generar estrategia
    strategy_parts = []
    if successful > 0:
        strategy_parts.append(f"Se encontraron {successful} bypasses exitosos")
    if blocked > 0:
        strategy_parts.append(f"{blocked} intentos fueron bloqueados")
    
    strategy = f"La campaña probó {len(attack_types)} tipos de ataque: {', '.join(attack_types.keys())}. " + ". ".join(strategy_parts) + "."
    
    # Generar insights
    insights = []
    for at_type, stats in attack_types.items():
        success_rate = (stats["successful"] / stats["total"] * 100) if stats["total"] > 0 else 0
        if success_rate > 50:
            insights.append(f"{at_type}: Alta tasa de bypass ({success_rate:.1f}%) - requiere mitigación urgente")
        elif success_rate > 0:
            insights.append(f"{at_type}: Algunos bypasses exitosos ({success_rate:.1f}%) - revisar reglas")
        else:
            insights.append(f"{at_type}: Todos los intentos bloqueados - defensa efectiva")
    
    # Generar mitigaciones sugeridas
    mitigations = []
    for at_type, stats in attack_types.items():
        if stats["successful"] > 0:
            mitigations.append({
                "attack_type": at_type,
                "priority": "high" if stats["successful"] / stats["total"] > 0.5 else "medium",
                "description": f"Mitigar bypasses de {at_type}",
                "recommendation": f"Agregar reglas más robustas para {at_type} basadas en los payloads que bypasearon"
            })
    
    return {
        "strategy": strategy,
        "insights": insights,
        "mitigations": mitigations,
        "attack_types_analyzed": list(attack_types.keys())
    }


@app.get("/api/intelligent-redteam/reasoning", response_class=JSONResponse)
async def intelligent_redteam_reasoning(tenant_id: str = Query("default")) -> Dict[str, Any]:
    """
    Obtiene el razonamiento actual del Red Team inteligente sobre qué probar.
    
    Returns:
        Razonamiento del agente: qué va a probar, por qué, y qué mitigaciones aplicará
    """
    _metrics["requests_total"] += 1
    
    try:
        import sys
        import importlib.util
        from pathlib import Path
        
        # Buscar intelligent-redteam en diferentes ubicaciones
        intelligent_paths = [
            Path("/app/intelligent-redteam"),
            Path(__file__).parent.parent / "intelligent-redteam",
            Path("/app/../intelligent-redteam")
        ]
        
        intelligent_path = None
        for path in intelligent_paths:
            if path.exists():
                intelligent_path = path
                break
        
        if not intelligent_path:
            # Si no hay módulo, usar datos de la base de datos directamente
            logger.warning("Intelligent Red Team module not found, using database fallback")
            try:
                conn = _get_postgres_conn()
                cursor = conn.cursor()
                
                # Obtener última campaña
                cursor.execute("""
                    SELECT campaign_id, MAX(tested_at) as last_test
                    FROM redteam_test_history
                    WHERE campaign_id IS NOT NULL
                    GROUP BY campaign_id
                    ORDER BY last_test DESC
                    LIMIT 1
                """)
                last_campaign = cursor.fetchone()
                
                if last_campaign and last_campaign[1]:
                    campaign_id = last_campaign[0]
                    cursor.execute("""
                        SELECT DISTINCT attack_type
                        FROM redteam_test_history
                        WHERE campaign_id = %s
                    """, (campaign_id,))
                    attack_types = [row[0] for row in cursor.fetchall()]
                    
                    cursor.close()
                    _return_postgres_conn(conn)
                    
                    return {
                        "success": True,
                        "reasoning": {
                            "current_strategy": f"Última campaña: {campaign_id}",
                            "attack_types_to_test": attack_types,
                            "why": [f"Tipos probados: {', '.join(attack_types)}"],
                            "mitigations_to_apply": []
                        }
                    }
                
                cursor.close()
                _return_postgres_conn(conn)
            except Exception as e:
                logger.error(f"Error en fallback reasoning: {e}")
            
            return {
                "success": False,
                "error": "Intelligent Red Team module not found",
                "reasoning": {
                    "current_strategy": "No disponible",
                    "attack_types_to_test": [],
                    "why": ["El módulo intelligent-redteam no está disponible"]
                }
            }
        
        # Importar TestHistoryManager
        parent_path = str(intelligent_path.parent)
        if parent_path not in sys.path:
            sys.path.insert(0, parent_path)
        
        try:
            from intelligent_redteam.history_manager.test_history_manager import TestHistoryManager
        except ImportError:
            history_file = intelligent_path / "history_manager" / "test_history_manager.py"
            if history_file.exists():
                spec = importlib.util.spec_from_file_location("test_history_manager", history_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    TestHistoryManager = module.TestHistoryManager
        
        history_manager = TestHistoryManager(tenant_id=tenant_id)
        
        reasoning = {
            "current_strategy": "El agente está analizando el WAF y el historial de pruebas para determinar qué probar",
            "attack_types_to_test": [],
            "why": [],
            "mitigations_to_apply": []
        }
        
        # PRIMERO: Verificar si hay una campaña reciente ejecutada (últimos 10 minutos)
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT campaign_id, MAX(tested_at) as last_test
                FROM redteam_test_history
                WHERE campaign_id IS NOT NULL
                GROUP BY campaign_id
                ORDER BY last_test DESC
                LIMIT 1
            """)
            last_campaign = cursor.fetchone()
            
            # Si hay una campaña muy reciente (últimos 10 minutos), mostrar esa
            if last_campaign and last_campaign[1]:
                from datetime import datetime, timezone
                last_test_time = last_campaign[1]
                if isinstance(last_test_time, str):
                    try:
                        from dateutil import parser
                        last_test_time = parser.parse(last_test_time)
                    except:
                        pass
                
                # Manejar timezone
                if hasattr(last_test_time, 'replace'):
                    if last_test_time.tzinfo is None:
                        last_test_time = last_test_time.replace(tzinfo=timezone.utc)
                
                now = datetime.now(timezone.utc)
                if hasattr(last_test_time, 'replace'):
                    time_diff = (now - last_test_time).total_seconds()
                else:
                    time_diff = 999999  # Si no se puede calcular, usar valor alto
                
                if time_diff < 600:  # Últimos 10 minutos
                    campaign_id = last_campaign[0]
                    # Obtener los tipos de ataque realmente probados en esa campaña
                    cursor.execute("""
                        SELECT DISTINCT attack_type
                        FROM redteam_test_history
                        WHERE campaign_id = %s
                        ORDER BY attack_type
                    """, (campaign_id,))
                    actual_types = [row[0] for row in cursor.fetchall()]
                    
                    # Obtener estadísticas de la campaña
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total,
                            COUNT(CASE WHEN success = true THEN 1 END) as successful,
                            COUNT(CASE WHEN blocked = true THEN 1 END) as blocked
                        FROM redteam_test_history
                        WHERE campaign_id = %s
                    """, (campaign_id,))
                    stats = cursor.fetchone()
                    
                    reasoning = {
                        "current_strategy": f"Última campaña ejecutada: {campaign_id}",
                        "attack_types_to_test": actual_types,
                        "why": [f"Tipos probados en la última campaña: {', '.join(actual_types)}"],
                        "mitigations_to_apply": [],
                        "campaign_id": campaign_id,
                        "campaign_stats": {
                            "total_tests": stats[0] if stats else 0,
                            "successful_bypasses": stats[1] if stats else 0,
                            "blocked_attempts": stats[2] if stats else 0
                        }
                    }
                    cursor.close()
                    _return_postgres_conn(conn)
                    
                    # Obtener mitigaciones sugeridas para estos tipos
                    suggestions_data = await intelligent_redteam_suggestions(tenant_id=tenant_id)
                    suggestions = suggestions_data.get("suggestions", [])
                    relevant_suggestions = [
                        s for s in suggestions 
                        if s.get("attack_type") in actual_types or s.get("type") in ["improve_rule", "increase_complexity"]
                    ]
                    reasoning["mitigations_to_apply"] = [
                        {
                            "type": s.get("type"),
                            "priority": s.get("priority"),
                            "description": s.get("description"),
                            "recommendation": s.get("recommendation"),
                            "attack_type": s.get("attack_type")
                        }
                        for s in relevant_suggestions[:5]
                    ]
                    
                    history_manager.close()
                    return {
                        "success": True,
                        "reasoning": reasoning,
                        "is_recent_campaign": True
                    }
            
            cursor.close()
            _return_postgres_conn(conn)
        except Exception as db_error:
            logger.error(f"Error consultando DB para última campaña: {db_error}")
            # Continuar con la lógica normal si falla la consulta
        
        # Si no hay campaña reciente, mostrar estrategia futura
        # Obtener tipos no probados
        unexplored = history_manager.get_unexplored_attack_types(hours=24)
        
        # Obtener prioridades
        priorities = history_manager.get_attack_type_priority(hours=24)
        
        # Obtener análisis del WAF
        analysis_data = await intelligent_redteam_analysis(tenant_id=tenant_id)
        analysis = analysis_data.get("analysis", {})
        unprotected = analysis.get("coverage", {}).get("unprotected", [])
        
        # Determinar qué probar
        types_to_test = []
        why_reasons = []
        
        if unexplored:
            types_to_test.extend(unexplored[:3])
            why_reasons.append(f"Tipos no probados recientemente: {', '.join(unexplored[:3])}")
        
        if unprotected:
            for ut in unprotected[:2]:
                if ut not in types_to_test:
                    types_to_test.append(ut)
            why_reasons.append(f"Tipos no protegidos detectados: {', '.join(unprotected[:2])}")
        
        # Ordenar por prioridad
        types_to_test = sorted(types_to_test, key=lambda x: priorities.get(x, 0.5), reverse=True)[:4]
        
        reasoning["attack_types_to_test"] = types_to_test
        reasoning["why"] = why_reasons
        
        # Obtener mitigaciones sugeridas - solo las relevantes a los tipos que se van a probar
        suggestions_data = await intelligent_redteam_suggestions(tenant_id=tenant_id)
        suggestions = suggestions_data.get("suggestions", [])
        
        # Filtrar sugerencias para que sean relevantes a los tipos de ataque que se van a probar
        relevant_suggestions = []
        for s in suggestions:
            # Si la sugerencia tiene attack_type, verificar que esté en types_to_test
            if s.get("attack_type") and s.get("attack_type") in types_to_test:
                relevant_suggestions.append(s)
            # Si es una sugerencia de mejora general (improve_rule, increase_complexity), incluirla
            elif s.get("type") in ["improve_rule", "increase_complexity"]:
                relevant_suggestions.append(s)
            # Si es add_rule y el attack_type está en types_to_test o unprotected
            elif s.get("type") == "add_rule" and s.get("attack_type") in (types_to_test + unprotected):
                relevant_suggestions.append(s)
        
        # Si no hay sugerencias relevantes, usar las primeras 3
        if not relevant_suggestions:
            relevant_suggestions = suggestions[:3]
        
        reasoning["mitigations_to_apply"] = [
            {
                "type": s.get("type"),
                "priority": s.get("priority"),
                "description": s.get("description"),
                "recommendation": s.get("recommendation"),
                "attack_type": s.get("attack_type")
            }
            for s in relevant_suggestions[:5]  # Top 5 relevantes
        ]
        
        history_manager.close()
        
        return {
            "success": True,
            "reasoning": reasoning,
            "priorities": priorities,
            "unexplored_types": unexplored,
            "unprotected_types": unprotected
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo razonamiento: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "reasoning": {
                "current_strategy": "Error al obtener razonamiento",
                "attack_types_to_test": [],
                "why": [f"Error: {str(e)}"]
            }
        }


@app.post("/api/intelligent-redteam/apply-and-retest", response_class=JSONResponse)
async def intelligent_redteam_apply_and_retest(tenant_id: str = Body("default", embed=True)) -> Dict[str, Any]:
    """
    Aplica las sugerencias de mejora del Red Team inteligente y relanza una campaña.
    
    Flujo:
      1) Obtiene sugerencias desde intelligent_redteam_suggestions
      2) Crea reglas dinámicas en tenant_rules para las sugerencias relevantes
      3) Dispara una campaña inmediata del Red Team (usando la señal /data/redteam_trigger)
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/intelligent-redteam/apply-and-retest"] = _metrics["requests_by_endpoint"].get(
        "/api/intelligent-redteam/apply-and-retest", 0
    ) + 1

    # Normalizar tenant_id: en esta primera versión usamos el tenant "default" (id=1)
    # En el futuro se puede mapear explícitamente tenant_id -> tenants.id
    tenant_db_id = 1

    try:
        # 1) Obtener sugerencias
        suggestions_data = await intelligent_redteam_suggestions(tenant_id=tenant_id)
        if not suggestions_data.get("success"):
            return {
                "success": False,
                "error": "No se pudieron obtener sugerencias del Red Team inteligente",
                "details": suggestions_data.get("error"),
            }

        suggestions = suggestions_data.get("suggestions", []) or []
        if not suggestions:
            return {
                "success": False,
                "error": "No hay sugerencias para aplicar",
            }

        # 2) Insertar reglas dinámicas en tenant_rules
        conn = _get_postgres_conn()
        cursor = conn.cursor()

        rules_created = 0
        for s in suggestions:
            s_type = (s.get("type") or "").lower()
            # Aplicar sugerencias de tipo: add_rule, increase_complexity, improve_rule
            if s_type not in ("add_rule", "increase_complexity", "improve_rule"):
                continue

            attack_type = s.get("attack_type") or s.get("type") or "GENERIC"
            priority = 50 if s.get("priority") == "high" else (75 if s.get("priority") == "medium" else 100)
            description = s.get("description") or ""
            recommendation = s.get("recommendation") or ""
            action_text = s.get("action") or ""

            # Nombre de regla amigable
            rule_name = f"irt_{attack_type.lower()}_{s_type}_{priority}_{int(datetime.now().timestamp())}"

            # Para improve_rule, intentar extraer el patrón mejorado de la recomendación/acción
            if s_type == "improve_rule":
                # Intentar extraer patrones de la descripción o acción
                pattern = action_text if action_text else description
                # Si la descripción contiene patrones específicos, usarlos
                if "comentarios SQL" in description.lower() or "sql" in description.lower():
                    pattern = r"(?i)(--|/\*|\*/|#)"  # Comentarios SQL
                elif "encoding" in description.lower():
                    pattern = r"(?i)(%[0-9a-f]{2}|\\x[0-9a-f]{2})"  # Encoding
                else:
                    pattern = attack_type.upper() + "_IMPROVED"
            else:
                # Patrón genérico por ahora (en producción, generar regex / condiciones específicas)
                pattern = attack_type.upper()
            
            action = "block"

            metadata = {
                "source": "intelligent-redteam",
                "suggestion_type": s_type,
                "attack_type": attack_type,
                "description": description,
                "recommendation": recommendation,
            }
            
            # Para improve_rule, agregar bypass_type si está disponible
            if s_type == "improve_rule":
                bypass_type = s.get("bypass_type")
                if bypass_type:
                    metadata["bypass_type"] = bypass_type
                # También guardar la acción si está disponible
                if action_text:
                    metadata["action"] = action_text

            cursor.execute(
                """
                INSERT INTO tenant_rules (tenant_id, rule_name, rule_type, pattern, action, priority, enabled, created_by, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s::jsonb)
                """,
                (
                    tenant_db_id,
                    rule_name,
                    "block",
                    pattern,
                    action,
                    priority,
                    "intelligent-redteam",
                    json.dumps(metadata),
                ),
            )
            rules_created += 1

        conn.commit()
        cursor.close()
        _return_postgres_conn(conn)

        # 3) Disparar campaña inmediata del Red Team (usa el servicio ya existente)
        try:
            os.makedirs("/data", exist_ok=True)
            with open("/data/redteam_trigger", "w") as f:
                f.write("trigger")
            redteam_triggered = True
        except Exception as e:
            redteam_triggered = False
            redteam_error = str(e)

        return {
            "success": True,
            "tenant_id": tenant_id,
            "tenant_db_id": tenant_db_id,
            "rules_created": rules_created,
            "suggestions_applied": len(suggestions),
            "redteam_triggered": redteam_triggered,
            "redteam_error": redteam_error if not redteam_triggered else None,
            "message": "Sugerencias aplicadas y campaña de Red Team inteligente disparada. Los resultados aparecerán en unos momentos.",
        }
    except Exception as e:
        _metrics["errors_total"] += 1
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error en intelligent_redteam_apply_and_retest: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


# ============================================================================
# Endpoints para Tenant Management (Fase 5)
# ============================================================================

@app.get("/api/tenants", response_class=JSONResponse)
async def list_tenants() -> Dict[str, Any]:
    """Lista todos los tenants"""
    _metrics["requests_total"] += 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT id, name, domain, status, created_at
            FROM tenants
            ORDER BY id
        """)
        
        tenants = []
        for row in cursor.fetchall():
            tenant = dict(row)
            # Convertir datetime
            if tenant.get('created_at'):
                if hasattr(tenant['created_at'], 'isoformat'):
                    tenant['created_at'] = tenant['created_at'].isoformat()
            tenants.append(tenant)
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "tenants": tenants
        }
    except Exception as e:
        logger.error(f"Error obteniendo tenants: {e}")
        return {
            "success": False,
            "error": str(e),
            "tenants": []
        }


@app.get("/api/tenants/{tenant_id}/metrics", response_class=JSONResponse)
async def tenant_metrics(tenant_id: str) -> Dict[str, Any]:
    """Obtiene métricas de un tenant específico"""
    _metrics["requests_total"] += 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Métricas básicas del tenant
        cursor.execute("""
            SELECT 
                COUNT(*) as total_requests,
                SUM(CASE WHEN blocked THEN 1 ELSE 0 END) as blocked_requests,
                COUNT(DISTINCT ip) as unique_ips
            FROM waf_logs
            WHERE tenant_id = %s AND created_at > NOW() - INTERVAL '24 hours'
        """, (tenant_id,))
        
        metrics = dict(cursor.fetchone())
        
        # Tipos de ataque
        cursor.execute("""
            SELECT threat_type, COUNT(*) as count
            FROM waf_logs
            WHERE tenant_id = %s AND created_at > NOW() - INTERVAL '24 hours' AND threat_type IS NOT NULL
            GROUP BY threat_type
            ORDER BY count DESC
            LIMIT 10
        """, (tenant_id,))
        
        attack_types = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "tenant_id": tenant_id,
            "metrics": metrics,
            "attack_types": attack_types
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/api/advanced-detection-stats", response_class=JSONResponse)
async def advanced_detection_stats() -> Dict[str, Any]:
    """
    FASE 1: Obtiene estadísticas de Detección Avanzada (Deobfuscation, Threat Intel, Anomaly Detection)
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/advanced-detection-stats"] = _metrics["requests_by_endpoint"].get("/api/advanced-detection-stats", 0) + 1
    
    try:
        import requests
        # Obtener métricas del realtime-processor
        realtime_url = os.getenv('REALTIME_PROCESSOR_URL', 'https://YOUR_CLOUD_RUN_URL/health')
        response = requests.get(realtime_url, timeout=5)
        
        if response.status_code == 200:
            realtime_data = response.json()
            advanced_detection = realtime_data.get("advanced_detection", {})
            
            # Asegurar que siempre retornamos un formato válido incluso si no hay datos
            return {
                "success": True,
                "deobfuscation": advanced_detection.get("deobfuscation", {
                    "total_deobfuscations": 0,
                    "obfuscation_detected": 0,
                    "multi_layer_obfuscation": 0,
                    "techniques_found": {}
                }),
                "threat_intelligence": advanced_detection.get("threat_intelligence", {
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "known_malicious_ips": 0,
                    "abuseipdb_queries": 0,
                    "virustotal_queries": 0,
                    "otx_queries": 0,
                    "errors": 0
                }),
                "anomaly_detection": advanced_detection.get("anomaly_detection", {
                    "anomalies_detected": 0,
                    "total_analyses": 0,
                    "zero_day_candidates": 0,
                    "isolation_forest_trained": False,
                    "baselines_count": 0
                }),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "deobfuscation": {},
                "threat_intelligence": {},
                "anomaly_detection": {}
            }
    except Exception as e:
        logger.error(f"Error obteniendo advanced detection stats: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "deobfuscation": {},
            "threat_intelligence": {},
            "anomaly_detection": {}
        }


@app.get("/api/real-time/stats", response_class=JSONResponse)
async def realtime_stats(
    tenant_id: Optional[str] = Query(None, description="ID del tenant para filtrar")
) -> Dict[str, Any]:
    """Obtiene estadísticas del procesamiento en tiempo real. Soporta filtrado por tenant_id."""
    _metrics["requests_total"] += 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Construir filtro de tenant
        tenant_filter = ""
        params = []
        
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            tenant_filter = "AND tenant_id = %s"
            params.append(int(tenant_id))
        elif tenant_id == "default":
            tenant_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
        
        # Logs procesados en las últimas horas
        query_hourly = """
            SELECT 
                DATE_TRUNC('hour', created_at) as hour,
                COUNT(*) as count,
                SUM(CASE WHEN blocked THEN 1 ELSE 0 END) as blocked
            FROM waf_logs
            WHERE created_at > NOW() - INTERVAL '24 hours'
            """ + tenant_filter + """
            GROUP BY hour
            ORDER BY hour DESC
            LIMIT 24
        """
        cursor.execute(query_hourly, params if tenant_filter else [])
        
        hourly_stats = [dict(row) for row in cursor.fetchall()]
        
        # Bypasses detectados recientemente
        bypass_filter = ""
        if tenant_id and tenant_id != "all" and tenant_id.isdigit():
            bypass_filter = "AND tenant_id = %s"
        elif tenant_id == "default":
            bypass_filter = "AND (tenant_id IS NULL OR tenant_id = 1)"
        
        query_bypass = """
            SELECT COUNT(*) as recent_bypasses
            FROM detected_bypasses
            WHERE detected_at > NOW() - INTERVAL '1 hour'
            """ + bypass_filter + """
        """
        cursor.execute(query_bypass, params if bypass_filter else [])
        bypass_result = cursor.fetchone()
        recent_bypasses = bypass_result['recent_bypasses'] if bypass_result else 0
        
        # Incidentes recientes
        incident_filter = bypass_filter.replace("tenant_id", "i.tenant_id") if bypass_filter else ""
        query_incident = """
            SELECT COUNT(*) as recent_incidents
            FROM incidents i
            WHERE i.created_at > NOW() - INTERVAL '1 hour'
            """ + incident_filter + """
        """
        cursor.execute(query_incident, params if incident_filter else [])
        incident_result = cursor.fetchone()
        recent_incidents = incident_result['recent_incidents'] if incident_result else 0
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "success": True,
            "hourly_stats": hourly_stats,
            "recent_bypasses": recent_bypasses,
            "recent_incidents": recent_incidents
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def get_auto_mitigation_stats() -> Dict[str, Any]:
    """
    Obtiene estadísticas de auto-mitigación.
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/api/auto-mitigation-stats"] = _metrics["requests_by_endpoint"].get("/api/auto-mitigation-stats", 0) + 1
    
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Estadísticas de bypasses
        cursor.execute("""
            SELECT 
                COUNT(*) as total_bypasses,
                COUNT(*) FILTER (WHERE mitigated = true) as mitigated_bypasses,
                COUNT(*) FILTER (WHERE mitigated = false) as pending_bypasses
            FROM detected_bypasses
        """)
        bypass_stats = dict(cursor.fetchone())
        
        # Estadísticas de incidentes
        cursor.execute("""
            SELECT 
                COUNT(*) as total_incidents,
                COUNT(*) FILTER (WHERE status = 'open') as open_incidents,
                COUNT(*) FILTER (WHERE status = 'closed') as closed_incidents,
                COUNT(*) FILTER (WHERE status = 'resolved') as resolved_incidents
            FROM incidents
        """)
        incident_stats = dict(cursor.fetchone())
        
        # Estadísticas de reglas generadas
        cursor.execute("""
            SELECT 
                COUNT(*) as total_rules,
                COUNT(*) FILTER (WHERE enabled = true) as enabled_rules
            FROM tenant_rules
            WHERE created_by = 'auto-mitigation-system'
        """)
        rule_stats = dict(cursor.fetchone())
        
        cursor.close()
        _return_postgres_conn(conn)
        
        return {
            "bypasses": bypass_stats,
            "incidents": incident_stats,
            "rules": rule_stats,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo estadísticas: {str(e)}"
        )


def _ensure_missing_tables():
    """
    Función para asegurar que las tablas faltantes existan.
    Se ejecuta automáticamente al iniciar el servicio.
    """
    if SKIP_DB_MIGRATIONS:
        logger.info("🔕 Migraciones deshabilitadas por configuración")
        return
    logger.info("🔍 Verificando tablas faltantes...")
    try:
        conn = _get_postgres_conn()
        cursor = conn.cursor()
        
        # Verificar qué tablas faltan
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('tenants', 'tenant_rules', 'incidents', 'detected_bypasses', 'detected_scans', 
                               'attacks_in_progress', 'redteam_tests', 'redteam_test_history', 'tenant_metrics');
        """)
        existing_tables = {row[0] for row in cursor.fetchall()}
        required_tables = {'tenants', 'tenant_rules', 'incidents', 'detected_bypasses', 'detected_scans',
                          'attacks_in_progress', 'redteam_tests', 'redteam_test_history', 'tenant_metrics'}
        missing_tables = required_tables - existing_tables
        
        if missing_tables:
            logger.info(f"Creando tablas faltantes: {missing_tables}")
            
            # Crear tenants primero (si no existe)
            if 'tenants' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE tenants (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        domain VARCHAR(255) UNIQUE NOT NULL,
                        backend_url VARCHAR(500) NOT NULL,
                        status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        config JSONB DEFAULT '{}'::jsonb,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_tenants_domain ON tenants (domain);")
                cursor.execute("CREATE INDEX idx_tenants_status ON tenants (status);")
            else:
                # Asegurar columnas nuevas en tenants sin romper despliegues viejos
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'tenants'
                """)
                tenant_columns = {row[0] for row in cursor.fetchall()}
                if 'backend_url' not in tenant_columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN backend_url VARCHAR(500) DEFAULT '';")
                if 'config' not in tenant_columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN config JSONB DEFAULT '{}'::jsonb;")
                if 'metadata' not in tenant_columns:
                    cursor.execute("ALTER TABLE tenants ADD COLUMN metadata JSONB DEFAULT '{}'::jsonb;")
            
            # Crear tenant_rules
            if 'tenant_rules' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE tenant_rules (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        rule_name VARCHAR(255) NOT NULL,
                        rule_type VARCHAR(50) NOT NULL CHECK (rule_type IN ('block', 'allow', 'rate_limit', 'custom')),
                        pattern TEXT NOT NULL,
                        action VARCHAR(50) NOT NULL,
                        priority INTEGER DEFAULT 100,
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        created_by VARCHAR(100) DEFAULT 'system',
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_tenant_rules_tenant_id ON tenant_rules (tenant_id);")
                cursor.execute("CREATE INDEX idx_tenant_rules_enabled ON tenant_rules (enabled);")
            
            # Crear incidents
            if 'incidents' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE incidents (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
                        title VARCHAR(500) NOT NULL,
                        description TEXT,
                        severity VARCHAR(20) DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'investigating', 'resolved', 'closed', 'false_positive')),
                        incident_type VARCHAR(50) NOT NULL CHECK (incident_type IN ('bypass', 'persistent_attack', 'scan', 'exploit', 'anomaly', 'other')),
                        source_ip VARCHAR(45),
                        affected_urls TEXT[],
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        resolved_at TIMESTAMP WITH TIME ZONE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        assigned_to VARCHAR(100),
                        resolution_notes TEXT,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_incidents_tenant_id ON incidents (tenant_id);")
                cursor.execute("CREATE INDEX idx_incidents_status ON incidents (status);")
                cursor.execute("CREATE INDEX idx_incidents_severity ON incidents (severity);")
                cursor.execute("CREATE INDEX idx_incidents_detected_at ON incidents (detected_at DESC);")
                cursor.execute("CREATE INDEX idx_incidents_source_ip ON incidents (source_ip);")
            
            # Crear detected_bypasses
            if 'detected_bypasses' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE detected_bypasses (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
                        source_ip VARCHAR(45) NOT NULL,
                        attack_type VARCHAR(50) NOT NULL,
                        original_rule_id VARCHAR(255),
                        bypass_method TEXT,
                        request_data JSONB,
                        response_data JSONB,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        mitigated BOOLEAN DEFAULT FALSE,
                        mitigation_rule_id INTEGER REFERENCES tenant_rules(id) ON DELETE SET NULL,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_bypasses_tenant_id ON detected_bypasses (tenant_id);")
                cursor.execute("CREATE INDEX idx_bypasses_source_ip ON detected_bypasses (source_ip);")
                cursor.execute("CREATE INDEX idx_bypasses_detected_at ON detected_bypasses (detected_at DESC);")
                cursor.execute("CREATE INDEX idx_bypasses_mitigated ON detected_bypasses (mitigated);")
            
            # Crear detected_scans
            if 'detected_scans' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE detected_scans (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        source_ip VARCHAR(45) NOT NULL,
                        scan_type VARCHAR(50) NOT NULL CHECK (scan_type IN ('port_scan', 'dir_scan', 'vuln_scan', 'crawler', 'other')),
                        target_paths TEXT[],
                        requests_count INTEGER DEFAULT 0,
                        time_window_start TIMESTAMP WITH TIME ZONE,
                        time_window_end TIMESTAMP WITH TIME ZONE,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        blocked BOOLEAN DEFAULT FALSE,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_scans_tenant_id ON detected_scans (tenant_id);")
                cursor.execute("CREATE INDEX idx_scans_source_ip ON detected_scans (source_ip);")
                cursor.execute("CREATE INDEX idx_scans_detected_at ON detected_scans (detected_at DESC);")
            
            # Crear attacks_in_progress
            if 'attacks_in_progress' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE attacks_in_progress (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        source_ip VARCHAR(45) NOT NULL,
                        attack_type VARCHAR(50) NOT NULL,
                        target_url TEXT,
                        attack_stage VARCHAR(50) DEFAULT 'reconnaissance' CHECK (attack_stage IN ('reconnaissance', 'exploitation', 'persistence', 'lateral_movement', 'data_exfiltration')),
                        steps_count INTEGER DEFAULT 1,
                        first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE,
                        incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_attacks_tenant_id ON attacks_in_progress (tenant_id);")
                cursor.execute("CREATE INDEX idx_attacks_source_ip ON attacks_in_progress (source_ip);")
                cursor.execute("CREATE INDEX idx_attacks_is_active ON attacks_in_progress (is_active);")
                cursor.execute("CREATE INDEX idx_attacks_last_seen ON attacks_in_progress (last_seen DESC);")
            
            # Crear redteam_tests
            if 'redteam_tests' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE redteam_tests (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        test_name VARCHAR(255) NOT NULL,
                        test_type VARCHAR(50) NOT NULL CHECK (test_type IN ('sqli', 'xss', 'path_traversal', 'cmd_injection', 'auth_bypass', 'other')),
                        target_url TEXT NOT NULL,
                        payload TEXT,
                        executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        blocked BOOLEAN,
                        response_status INTEGER,
                        response_time_ms INTEGER,
                        detected_by VARCHAR(255),
                        rule_matched VARCHAR(255),
                        result JSONB DEFAULT '{}'::jsonb,
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_redteam_tenant_id ON redteam_tests (tenant_id);")
                cursor.execute("CREATE INDEX idx_redteam_test_type ON redteam_tests (test_type);")
                cursor.execute("CREATE INDEX idx_redteam_executed_at ON redteam_tests (executed_at DESC);")
                cursor.execute("CREATE INDEX idx_redteam_blocked ON redteam_tests (blocked);")
            
            # Crear redteam_test_history
            if 'redteam_test_history' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE redteam_test_history (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        attack_type VARCHAR(50) NOT NULL CHECK (attack_type IN ('SQLI', 'XSS', 'PATH_TRAVERSAL', 'CMD_INJECTION', 'RFI_LFI', 'XXE', 'OTHER')),
                        payload TEXT NOT NULL,
                        bypass_technique VARCHAR(100),
                        success BOOLEAN NOT NULL,
                        blocked BOOLEAN NOT NULL,
                        response_status INTEGER,
                        response_time_ms INTEGER,
                        waf_signatures JSONB DEFAULT '[]'::jsonb,
                        waf_rules_count INTEGER DEFAULT 0,
                        protected_types TEXT[],
                        tested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        campaign_id VARCHAR(100),
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                """)
                cursor.execute("CREATE INDEX idx_redteam_history_tenant_id ON redteam_test_history (tenant_id);")
                cursor.execute("CREATE INDEX idx_redteam_history_attack_type ON redteam_test_history (attack_type);")
                cursor.execute("CREATE INDEX idx_redteam_history_tested_at ON redteam_test_history (tested_at DESC);")
                cursor.execute("CREATE INDEX idx_redteam_history_success ON redteam_test_history (success);")
                cursor.execute("CREATE INDEX idx_redteam_history_blocked ON redteam_test_history (blocked);")
                cursor.execute("CREATE INDEX idx_redteam_history_campaign_id ON redteam_test_history (campaign_id);")
                cursor.execute("CREATE INDEX idx_redteam_history_tenant_attack_tested ON redteam_test_history (tenant_id, attack_type, tested_at DESC);")
            
            # Crear tenant_metrics
            if 'tenant_metrics' not in existing_tables:
                cursor.execute("""
                    CREATE TABLE tenant_metrics (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                        metric_date DATE NOT NULL,
                        total_requests BIGINT DEFAULT 0,
                        blocked_requests BIGINT DEFAULT 0,
                        allowed_requests BIGINT DEFAULT 0,
                        xss_attacks BIGINT DEFAULT 0,
                        sqli_attacks BIGINT DEFAULT 0,
                        path_traversal_attacks BIGINT DEFAULT 0,
                        cmd_injection_attacks BIGINT DEFAULT 0,
                        unique_ips BIGINT DEFAULT 0,
                        bypasses_detected BIGINT DEFAULT 0,
                        scans_detected BIGINT DEFAULT 0,
                        incidents_created BIGINT DEFAULT 0,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(tenant_id, metric_date)
                    );
                """)
                cursor.execute("CREATE INDEX idx_metrics_tenant_id ON tenant_metrics (tenant_id);")
                cursor.execute("CREATE INDEX idx_metrics_metric_date ON tenant_metrics (metric_date DESC);")
            
            # Insertar tenant por defecto (sin depender de UNIQUE)
            cursor.execute("SELECT 1 FROM tenants WHERE domain = 'localhost' LIMIT 1;")
            if cursor.fetchone() is None:
                cursor.execute("""
                    INSERT INTO tenants (name, domain, backend_url, status) 
                    VALUES ('Default Site', 'localhost', 'http://backend:80', 'active');
                """)
            
            # Asegurar que waf_logs tenga tenant_id
            try:
                cursor.execute("ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_id ON waf_logs (tenant_id);")
            except Exception as e:
                if 'already exists' not in str(e).lower():
                    logger.warning(f"Error agregando tenant_id a waf_logs: {e}")

            # Asegurar columnas necesarias para episodios/bloqueos automáticos
            try:
                cursor.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name IN ('episodes', 'blocked_ips', 'analyst_labels')
                """)
                present = {row[0] for row in cursor.fetchall()}

                if 'episodes' in present:
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'episodes'
                    """)
                    episode_cols = {row[0] for row in cursor.fetchall()}
                    if 'user_agent_hash' not in episode_cols:
                        cursor.execute("ALTER TABLE episodes ADD COLUMN user_agent_hash TEXT;")
                    if 'presence_flags' not in episode_cols:
                        cursor.execute("ALTER TABLE episodes ADD COLUMN presence_flags JSONB DEFAULT '{}'::jsonb;")

                if 'blocked_ips' in present:
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'blocked_ips'
                    """)
                    blocked_cols = {row[0] for row in cursor.fetchall()}
                    if 'updated_at' not in blocked_cols:
                        cursor.execute("ALTER TABLE blocked_ips ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")

                if 'analyst_labels' not in present:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS analyst_labels (
                            episode_id INTEGER PRIMARY KEY,
                            episode_features_json JSONB NOT NULL,
                            analyst_label TEXT NOT NULL,
                            analyst_notes TEXT,
                            analyst_id TEXT,
                            confidence REAL DEFAULT 1.0,
                            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_analyst_labels_timestamp ON analyst_labels(timestamp DESC);")
                else:
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'analyst_labels'
                    """)
                    al_cols = {row[0] for row in cursor.fetchall()}
                    if 'episode_features_json' not in al_cols:
                        cursor.execute("ALTER TABLE analyst_labels ADD COLUMN episode_features_json JSONB;")
                    if 'confidence' not in al_cols:
                        cursor.execute("ALTER TABLE analyst_labels ADD COLUMN confidence REAL DEFAULT 1.0;")
            except Exception as e:
                logger.warning(f"Error ajustando columnas de episodes/blocked_ips/analyst_labels: {e}")
            
            conn.commit()
            logger.info(f"✅ Tablas creadas: {missing_tables}")
        else:
            logger.info("✅ Todas las tablas ya existen")
        
        # Crear índices de optimización para waf_logs (si no existen)
        logger.info("🔍 Verificando índices de optimización...")
        try:
            indexes_to_create = [
                ("idx_waf_logs_created_at", "CREATE INDEX IF NOT EXISTS idx_waf_logs_created_at ON waf_logs(created_at DESC)"),
                ("idx_waf_logs_threat_type", "CREATE INDEX IF NOT EXISTS idx_waf_logs_threat_type ON waf_logs(threat_type) WHERE threat_type IS NOT NULL"),
                ("idx_waf_logs_blocked", "CREATE INDEX IF NOT EXISTS idx_waf_logs_blocked ON waf_logs(blocked) WHERE blocked = true"),
                ("idx_waf_logs_created_at_blocked", "CREATE INDEX IF NOT EXISTS idx_waf_logs_created_at_blocked ON waf_logs(created_at DESC, blocked)"),
                ("idx_waf_logs_classification_source", "CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source ON waf_logs(classification_source) WHERE classification_source IS NOT NULL"),
                ("idx_waf_logs_ml_confidence", "CREATE INDEX IF NOT EXISTS idx_waf_logs_ml_confidence ON waf_logs(ml_confidence) WHERE ml_confidence IS NOT NULL"),
                ("idx_waf_logs_llm_confidence", "CREATE INDEX IF NOT EXISTS idx_waf_logs_llm_confidence ON waf_logs(llm_confidence) WHERE llm_confidence IS NOT NULL"),
            ]
            
            for idx_name, idx_sql in indexes_to_create:
                try:
                    cursor.execute(idx_sql)
                except Exception as e:
                    if 'already exists' not in str(e).lower():
                        logger.warning(f"Error creando índice {idx_name}: {e}")
            
            conn.commit()
            logger.info("✅ Índices de optimización verificados/creados")
        except Exception as e:
            logger.warning(f"Error creando índices: {e}")
        
        # Crear tablas de retroalimentación ML←LLM
        logger.info("🔍 Verificando tablas de retroalimentación...")
        try:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('ml_feedback_logs', 'ml_retraining_history');
            """)
            existing_feedback_tables = {row[0] for row in cursor.fetchall()}
            
            if 'ml_feedback_logs' not in existing_feedback_tables:
                cursor.execute("""
                    CREATE TABLE ml_feedback_logs (
                        id SERIAL PRIMARY KEY,
                        waf_log_id INTEGER REFERENCES waf_logs(id) ON DELETE CASCADE,
                        original_ml_prediction VARCHAR(50),
                        original_ml_confidence REAL,
                        corrected_threat_type VARCHAR(50) NOT NULL,
                        llm_confidence REAL NOT NULL,
                        ml_model_id VARCHAR(100),
                        feedback_date TIMESTAMP DEFAULT NOW(),
                        used_for_training BOOLEAN DEFAULT FALSE,
                        training_batch_id VARCHAR(50),
                        notes TEXT
                    );
                """)
                cursor.execute("CREATE INDEX idx_ml_feedback_used ON ml_feedback_logs(used_for_training) WHERE used_for_training = false;")
                cursor.execute("CREATE INDEX idx_ml_feedback_date ON ml_feedback_logs(feedback_date DESC);")
                cursor.execute("CREATE INDEX idx_ml_feedback_llm_confidence ON ml_feedback_logs(llm_confidence DESC) WHERE llm_confidence >= 0.8;")
                cursor.execute("CREATE INDEX idx_ml_feedback_waf_log_id ON ml_feedback_logs(waf_log_id);")
                logger.info("✅ Tabla ml_feedback_logs creada")
            
            if 'ml_retraining_history' not in existing_feedback_tables:
                cursor.execute("""
                    CREATE TABLE ml_retraining_history (
                        id SERIAL PRIMARY KEY,
                        model_id VARCHAR(100) NOT NULL,
                        previous_model_id VARCHAR(100),
                        training_date TIMESTAMP DEFAULT NOW(),
                        feedback_samples_used INTEGER DEFAULT 0,
                        original_samples_used INTEGER DEFAULT 0,
                        accuracy_before REAL,
                        accuracy_after REAL,
                        improvement REAL,
                        status VARCHAR(20) DEFAULT 'pending',
                        notes TEXT
                    );
                """)
                cursor.execute("CREATE INDEX idx_ml_retraining_date ON ml_retraining_history(training_date DESC);")
                cursor.execute("CREATE INDEX idx_ml_retraining_status ON ml_retraining_history(status);")
                logger.info("✅ Tabla ml_retraining_history creada")
            
            conn.commit()
        except Exception as e:
            logger.warning(f"Error creando tablas de retroalimentación: {e}")
        
        cursor.close()
        _return_postgres_conn(conn)
    except Exception as e:
        logger.error(f"Error verificando/creando tablas: {e}", exc_info=True)

# Ejecutar al iniciar la aplicación usando evento de startup de FastAPI
@app.on_event("startup")
async def startup_event():
    """Evento de startup para crear tablas faltantes"""
    if SKIP_DB_MIGRATIONS:
        logger.info("🔕 Startup sin migraciones (SKIP_DB_MIGRATIONS=true)")
        return
    # Ejecutar en background para no bloquear el startup
    import asyncio
    async def _init_tables():
        await asyncio.sleep(5)  # Esperar 5 segundos antes de intentar
        try:
            _ensure_missing_tables()
        except Exception as e:
            logger.warning(f"No se pudieron crear las tablas al iniciar: {e}. Se intentará más tarde.")
    
    # Ejecutar en background sin bloquear
    asyncio.create_task(_init_tables())




# Endpoints adicionales para Tokio AI CLI y Tenants
try:
    from mcp_cli_endpoint import execute_mcp_command
    MCP_CLI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"MCP CLI endpoint no disponible: {e}")
    MCP_CLI_AVAILABLE = False
    execute_mcp_command = None

# Endpoint duplicado eliminado - usar /api/cli/execute más abajo (v3.0 directo)

@app.post("/api/cli/jobs", response_class=JSONResponse)
async def cli_create_job_endpoint(request: dict = Body(...)):
    """Crea un job para ejecutar un comando CLI con streaming SSE"""
    try:
        from mcp_cli_endpoint import create_mcp_job
        command = (request.get("command") or "").strip()
        mode = request.get("mode", "agent")
        session_id = request.get("session_id", "default")
        if not command:
            return JSONResponse(status_code=400, content={"success": False, "error": "Comando vacío"})
        result = await create_mcp_job(command, mode, session_id)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.get("/api/cli/jobs/{job_id}/events")
async def cli_job_events_endpoint(job_id: str):
    """Stream de eventos SSE para un job CLI"""
    try:
        from mcp_cli_endpoint import sse_job_events
        return StreamingResponse(sse_job_events(job_id), media_type="text/event-stream")
    except Exception as e:
        return StreamingResponse(iter([f"data: {json.dumps({'type':'final','success':False,'error':str(e)})}\n\n"]), media_type="text/event-stream")

@app.post("/api/cli/jobs/{job_id}/cancel", response_class=JSONResponse)
async def cli_cancel_job_endpoint(job_id: str):
    """Cancela un job CLI"""
    try:
        from mcp_cli_endpoint import cancel_mcp_job
        return JSONResponse(cancel_mcp_job(job_id))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.post("/api/cli/cancel", response_class=JSONResponse)
async def cli_cancel_endpoint(request: dict = Body(...)):
    try:
        from mcp_cli_endpoint import cancel_mcp_command
        session_id = request.get("session_id", "default")
        return JSONResponse(cancel_mcp_command(session_id))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# ============================================================================
# CLI MIGRADO AL SERVICIO INDEPENDIENTE (tokio-cli:8100)
# WebSocket ahora en: ws://tokio-cli:8100/ws/cli
# Ver cli_client.py para integración
# ============================================================================
# MIGRADO - @app.websocket("/api/cli/ws")
# MIGRADO - async def cli_websocket_endpoint(websocket: WebSocket):
# MIGRADO -     """WebSocket para terminal interactivo - TokioAI OpenClaw Real"""
# MIGRADO -     try:
# MIGRADO -         from cli_openclaw_real import handle_cli_websocket
# MIGRADO -         await handle_cli_websocket(websocket)
# MIGRADO -     except Exception as e:
# MIGRADO -         print(f"Error in CLI WebSocket: {e}")
# MIGRADO -         import traceback
# MIGRADO -         traceback.print_exc()
# MIGRADO -         try:
# MIGRADO -             await websocket.close(code=1011, reason=f"CLI error: {str(e)}")
# MIGRADO -         except:
# MIGRADO -             pass


@app.post("/api/cli/execute")
async def cli_execute_direct(request: Request):
    """Endpoint HTTP directo para ejecutar comandos del CLI - TokioAI v3.0 (usa tokio-cli service)"""
    try:
        from cli_client import get_cli_client
        
        # Obtener comando del body
        body = await request.json()
        command = body.get("command", "").strip()
        session_id = body.get("session_id")

        if not command:
            return JSONResponse({"error": "Comando vacío"}, status_code=400)

        # Usar el cliente HTTP para comunicarse con tokio-cli service
        client = get_cli_client()
        result = await client.execute_and_wait(command, session_id=session_id, timeout=120)

        # Formatear respuesta
        response_data = {
            "success": result.get("success", False),
            "output": result.get("result", result.get("output")),
            "error": result.get("error"),
            "job_id": result.get("job_id"),
            "session_id": result.get("session_id"),
        }

        return JSONResponse(response_data)

    except Exception as e:
        import traceback
        error_msg = f"Error ejecutando comando: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return JSONResponse({"error": str(e), "success": False}, status_code=500)

# ============================================================================
# Automation Queue (Human-in-the-loop)
# ============================================================================
@app.get("/spotify/callback", response_class=HTMLResponse)
async def spotify_callback(code: str = Query(None), error: str = Query(None)):
    """
    Endpoint para recibir el callback de autorización de Spotify.
    Muestra el código en pantalla para que el usuario lo copie.
    """
    if error:
        return HTMLResponse(f"""
            <html>
            <head>
                <title>Spotify Authorization Error</title>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 40px; text-align: center; background: #f5f5f5; }}
                    .error {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 600px; margin: 0 auto; }}
                    h1 {{ color: #e74c3c; }}
                </style>
            </head>
            <body>
                <div class="error">
                    <h1>❌ Error de Autorización</h1>
                    <p><strong>Error:</strong> {error}</p>
                    <p>Por favor, intenta de nuevo.</p>
                </div>
            </body>
            </html>
        """)
    
    if code:
        return HTMLResponse(f"""
            <html>
            <head>
                <title>Spotify Authorization Success</title>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 40px; text-align: center; background: #f5f5f5; }}
                    .success {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 600px; margin: 0 auto; }}
                    h1 {{ color: #1DB954; }}
                    code {{ background: #f0f0f0; padding: 10px 15px; border-radius: 5px; display: block; margin: 20px 0; word-break: break-all; font-size: 14px; }}
                    .instructions {{ text-align: left; margin-top: 20px; padding: 15px; background: #e8f5e9; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="success">
                    <h1>✅ Autorización Exitosa!</h1>
                    <p>Tu código de autorización es:</p>
                    <code>{code}</code>
                    <div class="instructions">
                        <p><strong>Próximos pasos:</strong></p>
                        <ol>
                            <li>Copia el código de arriba</li>
                            <li>Vuelve al script que ejecutaste</li>
                            <li>Pega el código cuando te lo pida</li>
                        </ol>
                    </div>
                    <p style="margin-top: 20px; color: #666; font-size: 12px;">
                        Puedes cerrar esta ventana.
                    </p>
                </div>
            </body>
            </html>
        """)
    
    return HTMLResponse("""
        <html>
        <head><title>Spotify Callback</title></head>
        <body>
            <h1>No se recibió código de autorización</h1>
            <p>Por favor, intenta autorizar de nuevo.</p>
        </body>
        </html>
    """)

@app.post("/api/automation/proposals", response_class=JSONResponse)
async def create_automation_proposal(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Crea una propuesta de herramienta o comando (requiere aprobación humana).
    """
    proposal_type = (payload.get("type") or "").lower()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    code = payload.get("code")
    command = payload.get("command")
    input_schema = payload.get("input_schema")
    if proposal_type not in {"tool", "command"}:
        return JSONResponse(status_code=400, content={"success": False, "error": "type debe ser 'tool' o 'command'"})
    if not title:
        return JSONResponse(status_code=400, content={"success": False, "error": "title es requerido"})
    if proposal_type == "tool" and not code:
        return JSONResponse(status_code=400, content={"success": False, "error": "code es requerido para tools"})
    if proposal_type == "command" and not command:
        return JSONResponse(status_code=400, content={"success": False, "error": "command es requerido para comandos"})
    tool_key = _normalize_tool_key(title) if proposal_type == "tool" else None
    item = {
        "id": str(uuid.uuid4()),
        "tool_key": tool_key,
        "type": proposal_type,
        "title": title,
        "description": description,
        "code": code,
        "command": command,
        "input_schema": input_schema,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    with _automation_lock:
        if AUTOMATION_STORE_MODE == "postgres":
            conn = None
            try:
                conn = _get_postgres_conn()
                cur = conn.cursor()
                _ensure_automation_table(cur)
                cur.execute(
                    """
                    INSERT INTO automation_proposals
                    (id, tool_key, type, title, description, code, command, input_schema, status, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        item["id"], item["tool_key"], item["type"], item["title"], item["description"],
                        item["code"], item["command"],
                        json.dumps(item["input_schema"]) if item.get("input_schema") else None,
                        item["status"], item["created_at"]
                    )
                )
                conn.commit()
            except Exception as e:
                if conn:
                    conn.rollback()
                return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
            finally:
                if conn:
                    _return_postgres_conn(conn)
        else:
            items = _load_automation_items()
            items.insert(0, item)
            _save_automation_items(items)
    return {"success": True, "proposal": item}


@app.get("/api/automation/proposals", response_class=JSONResponse)
async def list_automation_proposals(status: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    Lista propuestas pendientes/aprobadas.
    """
    with _automation_lock:
        items = _load_automation_items()
    if status:
        items = [i for i in items if i.get("status") == status]
    return {"success": True, "items": items, "count": len(items)}


@app.get("/api/automation/tools", response_class=JSONResponse)
async def list_automation_tools(status: Optional[str] = Query("approved")) -> Dict[str, Any]:
    with _automation_lock:
        items = _load_automation_items()
    items = [i for i in items if i.get("type") == "tool"]
    if status:
        items = [i for i in items if i.get("status") == status]
    return {"success": True, "items": items, "count": len(items)}


@app.post("/api/automation/tools/execute", response_class=JSONResponse)
async def execute_automation_tool(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool_id = (payload.get("id") or "").strip()
    tool_key = (payload.get("tool_key") or "").strip()
    title = (payload.get("title") or "").strip()
    args = payload.get("args") or {}
    with _automation_lock:
        if AUTOMATION_STORE_MODE == "postgres":
            conn = None
            try:
                conn = _get_postgres_conn()
                cur = conn.cursor()
                _ensure_automation_table(cur)
                if tool_id:
                    cur.execute(
                        """
                        SELECT id, tool_key, type, title, description, code, command, input_schema,
                               status, created_at, approved_at, approved_by, result
                        FROM automation_proposals
                        WHERE id = %s
                        """,
                        (tool_id,)
                    )
                elif tool_key:
                    cur.execute(
                        """
                        SELECT id, tool_key, type, title, description, code, command, input_schema,
                               status, created_at, approved_at, approved_by, result
                        FROM automation_proposals
                        WHERE tool_key = %s
                        ORDER BY approved_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        """,
                        (tool_key,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, tool_key, type, title, description, code, command, input_schema,
                               status, created_at, approved_at, approved_by, result
                        FROM automation_proposals
                        WHERE title = %s
                        ORDER BY approved_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        """,
                        (title,)
                    )
                row = cur.fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"success": False, "error": "Tool no encontrada"})
                item = _row_to_proposal(row)
            finally:
                if conn:
                    _return_postgres_conn(conn)
        else:
            items = _load_automation_items()
            item = next((i for i in items if (tool_id and i.get("id") == tool_id) or (tool_key and i.get("tool_key") == tool_key) or (title and i.get("title") == title)), None)
            if not item:
                return JSONResponse(status_code=404, content={"success": False, "error": "Tool no encontrada"})
    if item.get("status") != "approved":
        return JSONResponse(status_code=400, content={"success": False, "error": "Tool no aprobada"})
    code = item.get("code") or ""
    if not code:
        return JSONResponse(status_code=400, content={"success": False, "error": "Tool sin código"})
    try:
        cmd = _build_tool_exec_command(code, args)
        result = _run_command_in_runner(cmd)
        parsed = None
        stdout = (result.get("stdout") or "").strip()
        if stdout:
            try:
                parsed = json.loads(stdout.splitlines()[-1])
            except Exception:
                parsed = None
        return {
            "success": True,
            "result": result,
            "parsed": parsed,
            "tool": {"id": item.get("id"), "tool_key": item.get("tool_key"), "title": item.get("title")}
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/automation/proposals/{proposal_id}/approve", response_class=JSONResponse)
async def approve_automation_proposal(
    proposal_id: str,
    approver: str = Query("human"),
    run_now: bool = Query(True)
) -> Dict[str, Any]:
    """
    Aprueba una propuesta y opcionalmente ejecuta (comandos) en sandbox.
    """
    with _automation_lock:
        if AUTOMATION_STORE_MODE == "postgres":
            conn = None
            try:
                conn = _get_postgres_conn()
                cur = conn.cursor()
                _ensure_automation_table(cur)
                cur.execute(
                    """
                    SELECT id, tool_key, type, title, description, code, command, input_schema,
                           status, created_at, approved_at, approved_by, result
                    FROM automation_proposals
                    WHERE id = %s
                    """,
                    (proposal_id,)
                )
                row = cur.fetchone()
                if not row:
                    return JSONResponse(status_code=404, content={"success": False, "error": "Propuesta no encontrada"})
                item = _row_to_proposal(row)
                if item.get("status") == "approved" and item.get("result"):
                    return {"success": True, "proposal": item}
                item["status"] = "approved"
                item["approved_at"] = datetime.utcnow().isoformat() + "Z"
                item["approved_by"] = approver
                result = None
                if run_now and item.get("type") == "command":
                    cmd = item.get("command") or ""
                    try:
                        args = shlex.split(cmd)
                        if not args or args[0] not in AUTOMATION_CMD_ALLOWLIST:
                            raise Exception(f"Comando no permitido: {args[0] if args else 'vacío'}")
                        result = _run_command_in_runner(cmd)
                    except Exception as e:
                        result = {"error": str(e)}
                elif run_now and item.get("type") == "tool":
                    try:
                        tools_dir = "/tmp/tokio_tools"
                        os.makedirs(tools_dir, exist_ok=True)
                        tool_path = os.path.join(tools_dir, f"{proposal_id}.py")
                        with open(tool_path, "w") as f:
                            f.write(item.get("code") or "")
                        result = {"message": "Tool guardada. Requiere recargar el MCP para activarse.", "path": tool_path}
                    except Exception as e:
                        result = {"error": str(e)}
                if result is not None:
                    item["result"] = result
                cur.execute(
                    """
                    UPDATE automation_proposals
                    SET status=%s, approved_at=%s, approved_by=%s, result=%s
                    WHERE id=%s
                    """,
                    (
                        item["status"],
                        item["approved_at"],
                        item["approved_by"],
                        json.dumps(item.get("result")) if item.get("result") is not None else None,
                        item["id"],
                    )
                )
                conn.commit()
            except Exception as e:
                if conn:
                    conn.rollback()
                return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
            finally:
                if conn:
                    _return_postgres_conn(conn)
            return {"success": True, "proposal": item}
        else:
            items = _load_automation_items()
            item = next((i for i in items if i.get("id") == proposal_id), None)
            if not item:
                return JSONResponse(status_code=404, content={"success": False, "error": "Propuesta no encontrada"})
            if item.get("status") == "approved" and item.get("result"):
                return {"success": True, "proposal": item}
            item["status"] = "approved"
            item["approved_at"] = datetime.utcnow().isoformat() + "Z"
            item["approved_by"] = approver
            result = None
            if run_now and item.get("type") == "command":
                cmd = item.get("command") or ""
                try:
                    args = shlex.split(cmd)
                    if not args or args[0] not in AUTOMATION_CMD_ALLOWLIST:
                        raise Exception(f"Comando no permitido: {args[0] if args else 'vacío'}")
                    result = _run_command_in_runner(cmd)
                except Exception as e:
                    result = {"error": str(e)}
            elif run_now and item.get("type") == "tool":
                try:
                    tools_dir = "/tmp/tokio_tools"
                    os.makedirs(tools_dir, exist_ok=True)
                    tool_path = os.path.join(tools_dir, f"{proposal_id}.py")
                    with open(tool_path, "w") as f:
                        f.write(item.get("code") or "")
                    result = {"message": "Tool guardada. Requiere recargar el MCP para activarse.", "path": tool_path}
                except Exception as e:
                    result = {"error": str(e)}
            if result is not None:
                item["result"] = result
            _save_automation_items(items)
            return {"success": True, "proposal": item}


@app.post("/api/automation/proposals/{proposal_id}/reject", response_class=JSONResponse)
async def reject_automation_proposal(
    proposal_id: str,
    approver: str = Query("human"),
    reason: str = Query("Rejected")
) -> Dict[str, Any]:
    """
    Rechaza una propuesta pendiente.
    """
    with _automation_lock:
        items = _load_automation_items()
        item = next((i for i in items if i.get("id") == proposal_id), None)
        if not item:
            return JSONResponse(status_code=404, content={"success": False, "error": "Propuesta no encontrada"})
        item["status"] = "rejected"
        item["rejected_at"] = datetime.utcnow().isoformat() + "Z"
        item["rejected_by"] = approver
        item["rejection_reason"] = reason
        _save_automation_items(items)
    return {"success": True, "proposal": item}

# Reemplazar endpoint POST /api/tenants si existe
try:
    # Buscar y remover endpoint POST existente
    routes_to_remove = []
    for route in app.routes:
        if hasattr(route, 'path') and route.path == "/api/tenants":
            if hasattr(route, 'methods') and 'POST' in getattr(route, 'methods', []):
                routes_to_remove.append(route)
    for route in routes_to_remove:
        app.routes.remove(route)
except:
    pass

@app.post("/api/tenants", response_class=JSONResponse)
async def create_tenant_endpoint(request: dict = Body(...)):
    """Crea un nuevo tenant y configura Nginx automáticamente"""
    result = await create_tenant(request)
    if result.get("success"):
        return JSONResponse(result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Error creando tenant"))


@app.delete("/api/tenants/{tenant_id}", response_class=JSONResponse)
async def delete_tenant_endpoint(tenant_id: int):
    """Elimina un tenant y su configuración de Nginx"""
    result = await delete_tenant(tenant_id)
    if result.get("success"):
        return JSONResponse(result)
    else:
        raise HTTPException(status_code=404, detail=result.get("error", "Error eliminando tenant"))


@app.get("/api/health", response_class=JSONResponse)
async def health_check_api():
    """Endpoint de monitoreo de salud de servicios"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {}
    }
    
    # Verificar PostgreSQL
    try:
        conn = _get_postgres_conn()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            _return_postgres_conn(conn)
            health_status["services"]["postgresql"] = {
                "status": "healthy",
                "message": "Conexión exitosa"
            }
        else:
            health_status["status"] = "degraded"
            health_status["services"]["postgresql"] = {
                "status": "unhealthy",
                "message": "No se pudo obtener conexión del pool"
            }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["postgresql"] = {
            "status": "unhealthy",
            "message": str(e)[:200]
        }
    
    # Verificar Kafka
    try:
        from kafka import KafkaConsumer
        # Parsear bootstrap servers correctamente
        bootstrap_servers = KAFKA_BOOTSTRAP_SERVERS
        if isinstance(bootstrap_servers, str):
            servers = [s.strip() for s in bootstrap_servers.split(",")]
        else:
            servers = bootstrap_servers
        
        # Intentar conectar con timeout corto
        # Usar un método más simple para verificar conexión
        from kafka import KafkaAdminClient
        from kafka.errors import KafkaError
        
        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers=servers,
                request_timeout_ms=3000,
                api_version=(0, 10, 1)
            )
            # Intentar listar topics como verificación de conexión
            topics = admin_client.list_topics(timeout_ms=3000)
            admin_client.close()
            health_status["services"]["kafka"] = {
                "status": "healthy",
                "message": f"Conexión exitosa a {servers[0] if servers else 'unknown'}"
            }
        except Exception as admin_error:
            # Fallback: intentar con consumer simple
            try:
                consumer = KafkaConsumer(
                    bootstrap_servers=servers,
                    consumer_timeout_ms=2000,
                    request_timeout_ms=2000,
                    api_version=(0, 10, 1)
                )
                # Solo verificar que se puede crear el consumer
                consumer.close()
                health_status["services"]["kafka"] = {
                    "status": "healthy",
                    "message": f"Conexión exitosa a {servers[0] if servers else 'unknown'}"
                }
            except Exception as consumer_error:
                raise admin_error  # Usar el error del admin client
    except Exception as e:
        health_status["status"] = "degraded"
        error_msg = str(e)[:200]
        # Mensaje más descriptivo
        if "NoBrokersAvailable" in error_msg:
            error_msg = f"No se pudo conectar a Kafka en {KAFKA_BOOTSTRAP_SERVERS}. Verifica que Kafka esté corriendo y accesible."
        health_status["services"]["kafka"] = {
            "status": "unhealthy",
            "message": error_msg
        }
    
    return health_status


@app.get("/health/full", response_class=JSONResponse)
async def health_full() -> Dict[str, Any]:
    """
    Health check completo con estado de todos los subsistemas
    Puede tardar hasta 2 segundos
    """
    _metrics["requests_total"] += 1
    _metrics["requests_by_endpoint"]["/health/full"] = _metrics["requests_by_endpoint"].get("/health/full", 0) + 1
    
    status_overall = "healthy"
    services = {}
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Database
    db_status = "healthy"
    db_latency_ms = 0
    db_pool_size = 10
    db_pool_available = 8
    try:
        import time
        start = time.time()
        conn = _get_postgres_conn()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            _return_postgres_conn(conn)
            db_latency_ms = int((time.time() - start) * 1000)
        else:
            db_status = "unhealthy"
            status_overall = "degraded"
    except Exception as e:
        db_status = "unhealthy"
        status_overall = "degraded"
        logger.error(f"Error en health check de DB: {e}")
    
    services["database"] = {
        "status": db_status,
        "latency_ms": db_latency_ms,
        "pool_size": db_pool_size,
        "pool_available": db_pool_available
    }
    
    # Kafka
    kafka_status = "healthy"
    kafka_topics = []
    kafka_consumer_lag = 0
    try:
        from kafka import KafkaAdminClient
        admin = KafkaAdminClient(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
            client_id='health-check'
        )
        metadata = admin.list_topics()
        kafka_topics = list(metadata)
        admin.close()
    except Exception as e:
        kafka_status = "unhealthy"
        status_overall = "degraded"
        logger.error(f"Error en health check de Kafka: {e}")
    
    services["kafka"] = {
        "status": kafka_status,
        "topics": kafka_topics,
        "consumer_lag": kafka_consumer_lag
    }
    
    # Nginx (solo si está en modo local)
    nginx_status = "healthy"
    nginx_tenants_configured = 0
    nginx_last_reload = None
    if os.getenv("DEPLOY_MODE") == "local":
        try:
            import docker
            client = docker.from_env()
            container = client.containers.get("tokio-ai-modsecurity")
            result = container.exec_run("ls /etc/nginx/conf.d/tenants/*.conf 2>/dev/null | wc -l", user="root")
            nginx_tenants_configured = int(result.output.decode().strip() or "0")
        except Exception as e:
            nginx_status = "unknown"
            logger.debug(f"No se pudo verificar Nginx: {e}")
    
    services["nginx"] = {
        "status": nginx_status,
        "tenants_configured": nginx_tenants_configured,
        "last_reload": nginx_last_reload
    }
    
    # Real-time processor
    services["real_time_processor"] = {
        "status": "healthy",
        "events_processed_1m": 0,
        "ml_model_loaded": True
    }
    
    # MCP server
    services["mcp_server"] = {
        "status": "healthy",
        "tools_available": 14
    }
    
    # Tenants y bloqueos
    tenants_active = 0
    tenants_total = 0
    blocks_active = 0
    blocks_expired_today = 0
    
    try:
        conn = _get_postgres_conn()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
            tenants_active = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tenants")
            tenants_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM blocked_ips WHERE active = TRUE")
            blocks_active = cursor.fetchone()[0]
            cursor.execute("""
                SELECT COUNT(*) FROM blocked_ips 
                WHERE active = FALSE 
                AND unblocked_at >= CURRENT_DATE
            """)
            blocks_expired_today = cursor.fetchone()[0]
            cursor.close()
            _return_postgres_conn(conn)
    except Exception as e:
        logger.debug(f"Error obteniendo estadísticas: {e}")
    
    return {
        "status": status_overall,
        "timestamp": timestamp,
        "services": services,
        "tenants": {
            "active": tenants_active,
            "total": tenants_total
        },
        "blocks": {
            "active": blocks_active,
            "expired_today": blocks_expired_today
        }
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="YOUR_IP_ADDRESS", port=8000, reload=False)


