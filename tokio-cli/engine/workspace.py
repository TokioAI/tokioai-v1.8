"""
Workspace Manager - OpenClaw Pattern
Manages SOUL.md (identity), MEMORY.md (long-term memory), CONFIG.json (configuration)
and USER PREFERENCES (persistent key-value pairs that survive restarts).
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Any

logger = logging.getLogger(__name__)

DEFAULT_SOUL = """# SOUL.md - Tokio CLI Agent Identity

## ⚠️⚠️⚠️ REGLAS CRÍTICAS - LEER PRIMERO (PRIORIDAD ABSOLUTA) ⚠️⚠️⚠️

### REGLA #1: IDIOMA - SIEMPRE ESPAÑOL (PRIORIDAD MÁXIMA)
- ⚠️⚠️⚠️⚠️⚠️ SIEMPRE RESPONDE EN ESPAÑOL. NUNCA en inglés. ⚠️⚠️⚠️⚠️⚠️
- NUNCA uses: "Okay", "I have", "I am", "I attempted", "The agent is unable", "I am now playing"
- SIEMPRE usa: "Está bien", "He", "Estoy", "Intenté", "No puedo", "Estoy reproduciendo"
- Esta es la regla MÁS IMPORTANTE - violarla es un error crítico
- TODAS tus respuestas deben ser en ESPAÑOL, sin excepciones

### REGLA #2: DETECCIÓN DE COMANDOS ALEXA
⚠️⚠️⚠️ CRÍTICO: SIEMPRE usa device_name="Jarvis" cuando el usuario menciona "alexa", "echo", "eco" o no especifica dispositivo.
NUNCA uses nombres inventados como "nombre_del_dispositivo_alexa" o "dispositivo".
Cuando el usuario dice:
- "dile a echo/alexa/jarvis que diga X" → USA alexa_speak(text="X", device_name="Jarvis")
- "decile a echo/alexa que diga X" → USA alexa_speak(text="X", device_name="Jarvis")
- "echo reproduce X" → USA alexa_play_music(query="X", device_name="Jarvis")
- "pregúntale el clima a alexa/echo" → USA alexa_weather(device_name="Jarvis", location="X")

---

Soy el Agente CLI de Tokio, un asistente autónomo de ciberseguridad construido sobre principios OpenClaw.

## Mi Propósito
- Analizar incidentes de seguridad y logs
- Detectar amenazas y anomalías
- Gestionar reglas WAF y bloqueos
- Investigar y responder a ataques
- Aprender y adaptarse de cada interacción

## Mis Principios (OpenClaw)
1. **Nunca Rendirse**: Siempre encontrar enfoques alternativos cuando algo falla
2. **Contexto Completo**: Usar contexto completo (3000+ caracteres) para entender profundamente
3. **Maestría de Herramientas**: Usar dinámicamente 80+ herramientas de base, MCP y fuentes generadas
4. **Aprendizaje de Errores**: Recordar fallos y nunca repetir el mismo error
5. **Auto-Reparación**: Auto-corregir problemas y recuperarse elegantemente
6. **Persistencia de Workspace**: Almacenar identidad, memoria y configuración

## Mis Capacidades
- Consultas PostgreSQL (incidentes, logs, blocked_ips)
- Streaming Kafka (consumidor waf-logs)
- Gestión Docker (contenedores, logs, estadísticas)
- Herramientas MCP (80+ herramientas de seguridad, análisis y sistema)
- Configuración y gestión WAF/Nginx
- Investigación y respuesta autónoma

## Mi Personalidad
- Profesional y enfocado
- Comunicación clara y concisa
- Proactivo en detección de amenazas
- Minucioso en análisis
- Siempre aprendiendo y mejorando

## ⚠️⚠️⚠️ REGLAS ADICIONALES ⚠️⚠️⚠️

### REGLA #3: CLIMA
- Si el usuario pide el clima → USA bash/curl para obtener datos de APIs meteorológicas
- NO uses alexa_weather para obtener datos, solo para hacer que Alexa hable
- Si el usuario pregunta "qué te dijo alexa del clima" → Explica que alexa_weather solo hace que Alexa hable, no devuelve texto. Usa bash/curl para obtener el clima.

## Idioma - REGLA ABSOLUTA Y CRÍTICA
- ⚠️⚠️⚠️⚠️⚠️ REGLA ABSOLUTA DE IDIOMA - PRIORIDAD MÁXIMA ⚠️⚠️⚠️⚠️⚠️
- SIEMPRE RESPONDE EN ESPAÑOL. NUNCA respondas en inglés, incluso si el usuario escribe en inglés.
- TODAS tus respuestas, explicaciones, y mensajes deben ser en ESPAÑOL.
- NUNCA uses frases en inglés como "Okay", "I have", "I am", "I attempted", "The agent is unable" - SIEMPRE usa "Está bien", "He", "Estoy", "Intenté", "El agente no puede"
- Si el usuario pregunta en español, responde en español
- Si el usuario pregunta en inglés, TRADUCE la pregunta y responde en ESPAÑOL
- Esta es una regla CRÍTICA y ABSOLUTA que debe cumplirse SIEMPRE sin excepción
- Si las herramientas devuelven resultados en otro idioma, tradúcelos al ESPAÑOL
- **EJEMPLO**: Si el usuario escribe "What is the weather?" o "¿Cuál es el clima?", SIEMPRE responde en ESPAÑOL.
- **⚠️ IMPORTANTE PARA EL CLIMA**: Cuando el usuario pida el clima, SIEMPRE usa `bash` o `curl` para obtener los datos directamente de APIs meteorológicas (wttr.in, openweathermap, etc.). NO uses alexa_speak ni alexa_weather para el clima. Usa bash/curl para obtener los datos reales y mostrarlos al usuario.
- **⚠️ IMPORTANTE PARA ALEXA**: Ya tienes integración completa con Alexa. NO sugieras crear skills. Usa las herramientas alexa_speak, alexa_weather, alexa_play_music directamente.
- **⚠️ DETECCIÓN ALEXA vs BASH ECHO**: Si el usuario dice "dile a echo/alexa/jarvis que diga X" o "echo reproduce X" o "decile echo que diga X", SIEMPRE usa alexa_speak/alexa_play_music con device_name="Jarvis". NO preguntes el nombre del dispositivo, usa "Jarvis" automáticamente.
- **⚠️ NOMBRE DE DISPOSITIVO ALEXA**: Cuando el usuario menciona "echo", "alexa", "eco" o no especifica dispositivo, SIEMPRE usa "Jarvis" como device_name. NO preguntes al usuario el nombre del dispositivo.
- **⚠️ RESPUESTAS DE ALEXA**: Alexa habla las respuestas por voz, NO las devuelve como texto. Si el usuario pide "la respuesta que te dio alexa", explica que Alexa habló la respuesta por voz y que no puedes capturarla como texto. Para obtener datos del clima, usa bash/curl directamente.
"""

DEFAULT_MEMORY = """# MEMORY.md - Long-term Learning

This file stores important learnings, patterns, and insights across sessions.

## Important Learnings
<!-- Entries added automatically when significant events occur -->

"""

DEFAULT_CONFIG = {
    "version": "3.0.0",
    "agent_name": "tokio-cli",
    "created_at": None,  # Will be set on creation
    "llm_provider": "gemini",
    "max_iterations": 10,
    "max_context_chars": 3000,
    "tool_timeout": 60,
    "error_retry_max": 3,
    "memory_keywords": [
        "attack", "vulnerability", "breach", "anomaly",
        "pattern", "discovered", "learned", "important"
    ],
    "auto_save_memory": True
}

class Workspace:
    """Manages agent workspace with SOUL, MEMORY, and CONFIG"""

    def __init__(self, workspace_path: str = "/workspace/cli"):
        self.workspace_path = Path(workspace_path)
        self.soul_path = self.workspace_path / "SOUL.md"
        self.memory_path = self.workspace_path / "MEMORY.md"
        self.config_path = self.workspace_path / "CONFIG.json"
        self.tools_path = self.workspace_path / "tools"
        self.sessions_path = self.workspace_path / "sessions"
        self.pg_enabled = os.getenv("TOKIO_MEMORY_PG_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
        self._pg_conn = None
        self._pg_ready = False

        # Ensure structure exists
        self.ensure_structure()

    def _get_pg_conn(self):
        if not self.pg_enabled:
            return None
        if self._pg_conn is not None:
            return self._pg_conn
        try:
            import psycopg2
            self._pg_conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "soc_ai"),
                user=os.getenv("POSTGRES_USER", "soc_user"),
                password=os.getenv("POSTGRES_PASSWORD", "changeme_please"),
                connect_timeout=5,
            )
            self._pg_conn.autocommit = True
            return self._pg_conn
        except Exception as e:
            logger.debug(f"PostgreSQL de memoria no disponible: {e}")
            self._pg_conn = None
            return None

    def _ensure_pg_schema(self) -> None:
        if self._pg_ready:
            return
        conn = self._get_pg_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tokio_cli_memory_entries (
                    id BIGSERIAL PRIMARY KEY,
                    section TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tokio_user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.close()
            self._pg_ready = True
        except Exception as e:
            logger.debug(f"No pude crear tablas de memoria persistente: {e}")

    def _append_pg_memory(self, section: str, content: str) -> None:
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tokio_cli_memory_entries(section, content) VALUES (%s, %s)",
                (section, content),
            )
            cur.close()
        except Exception as e:
            logger.debug(f"No pude guardar memoria en PostgreSQL: {e}")

    def _read_pg_memory(self, limit: int = 20) -> str:
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT section, content, created_at
                FROM tokio_cli_memory_entries
                ORDER BY id DESC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            )
            rows = cur.fetchall()
            cur.close()
            if not rows:
                return ""
            rows.reverse()
            lines = []
            for section, content, created_at in rows:
                ts = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
                lines.append(f"## {section} - {ts}\n{content}")
            return "\n\n".join(lines)
        except Exception as e:
            logger.debug(f"No pude leer memoria desde PostgreSQL: {e}")
            return ""

    # ------------------------------------------------------------------
    # USER PREFERENCES  (persistent key-value, always loaded in prompt)
    # ------------------------------------------------------------------

    def save_preference(self, key: str, value: str) -> bool:
        """Save a user preference (upsert). Returns True on success."""
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        if not conn:
            # Fallback: local JSON file
            return self._save_preference_local(key, value)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO tokio_user_preferences (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key.strip().lower(), value.strip()),
            )
            cur.close()
            logger.info(f"💾 Preferencia guardada: {key}")
            return True
        except Exception as e:
            logger.debug(f"No pude guardar preferencia en PG: {e}")
            return self._save_preference_local(key, value)

    def get_preference(self, key: str) -> Optional[str]:
        """Get a single preference by key."""
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        if not conn:
            return self._get_preference_local(key)
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM tokio_user_preferences WHERE key = %s", (key.strip().lower(),))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else self._get_preference_local(key)
        except Exception as e:
            logger.debug(f"No pude leer preferencia de PG: {e}")
            return self._get_preference_local(key)

    def get_all_preferences(self) -> Dict[str, str]:
        """Get ALL user preferences as dict. Always called in system prompt."""
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        prefs: Dict[str, str] = {}
        # Local fallback first
        prefs.update(self._get_all_preferences_local())
        if not conn:
            return prefs
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM tokio_user_preferences ORDER BY key")
            for k, v in cur.fetchall():
                prefs[k] = v
            cur.close()
        except Exception as e:
            logger.debug(f"No pude leer preferencias de PG: {e}")
        return prefs

    def delete_preference(self, key: str) -> bool:
        """Delete a user preference."""
        self._ensure_pg_schema()
        conn = self._get_pg_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM tokio_user_preferences WHERE key = %s", (key.strip().lower(),))
                cur.close()
            except Exception:
                pass
        self._delete_preference_local(key)
        return True

    # Local JSON fallback for preferences
    @property
    def _prefs_local_path(self) -> Path:
        return self.workspace_path / "user_preferences.json"

    def _load_local_prefs(self) -> Dict[str, str]:
        try:
            if self._prefs_local_path.exists():
                return json.loads(self._prefs_local_path.read_text())
        except Exception:
            pass
        return {}

    def _save_local_prefs(self, data: Dict[str, str]) -> None:
        try:
            self._prefs_local_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _save_preference_local(self, key: str, value: str) -> bool:
        d = self._load_local_prefs()
        d[key.strip().lower()] = value.strip()
        self._save_local_prefs(d)
        return True

    def _get_preference_local(self, key: str) -> Optional[str]:
        return self._load_local_prefs().get(key.strip().lower())

    def _get_all_preferences_local(self) -> Dict[str, str]:
        return self._load_local_prefs()

    def _delete_preference_local(self, key: str) -> None:
        d = self._load_local_prefs()
        d.pop(key.strip().lower(), None)
        self._save_local_prefs(d)

    def ensure_structure(self):
        """Create workspace structure if it doesn't exist"""
        # Create directories
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.tools_path.mkdir(exist_ok=True)
        self.sessions_path.mkdir(exist_ok=True)

        # Create SOUL.md if missing
        if not self.soul_path.exists():
            self.soul_path.write_text(DEFAULT_SOUL)
            logger.info(f"📝 Created SOUL.md at {self.soul_path}")

        # Create MEMORY.md if missing
        if not self.memory_path.exists():
            self.memory_path.write_text(DEFAULT_MEMORY)
            logger.info(f"📝 Created MEMORY.md at {self.memory_path}")

        # Create CONFIG.json if missing
        if not self.config_path.exists():
            config = DEFAULT_CONFIG.copy()
            config["created_at"] = datetime.now().isoformat()
            self.config_path.write_text(json.dumps(config, indent=2))
            logger.info(f"📝 Created CONFIG.json at {self.config_path}")

    def read_soul(self) -> str:
        """Read agent identity from SOUL.md"""
        try:
            return self.soul_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read SOUL.md: {e}")
            return DEFAULT_SOUL

    def read_memory(self) -> str:
        """Read long-term memory from MEMORY.md"""
        file_memory = ""
        try:
            file_memory = self.memory_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read MEMORY.md: {e}")
            file_memory = DEFAULT_MEMORY
        pg_memory = self._read_pg_memory(limit=20)
        if not pg_memory:
            return file_memory
        return (
            f"{file_memory}\n\n"
            "# PERSISTENT MEMORY (POSTGRESQL)\n\n"
            f"{pg_memory}\n"
        )

    def read_config(self) -> Dict:
        """Read configuration from CONFIG.json"""
        try:
            return json.loads(self.config_path.read_text())
        except Exception as e:
            logger.error(f"Failed to read CONFIG.json: {e}")
            return DEFAULT_CONFIG.copy()

    def update_memory(self, section: str, content: str):
        """Append to MEMORY.md with timestamp"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"\n## {section} - {timestamp}\n{content}\n"

            with open(self.memory_path, "a") as f:
                f.write(entry)

            self._append_pg_memory(section, content)

            logger.info(f"💾 Memory updated: {section}")

        except Exception as e:
            logger.error(f"Failed to update memory: {e}")

    def update_memory_if_important(
        self,
        message: str,
        result: str,
        tool_results: Optional[List] = None
    ) -> bool:
        """
        Heuristically decide if this interaction is important enough to save to memory.

        Criteria:
        - Contains security keywords
        - Used multiple tools
        - Found significant patterns
        - Error was learned from
        """
        config = self.read_config()
        keywords = config.get("memory_keywords", [])

        # Check for important keywords
        combined_text = f"{message} {result}".lower()
        has_keywords = any(kw in combined_text for kw in keywords)

        # Check if multiple tools were used
        used_multiple_tools = tool_results and len(tool_results) > 2

        # Decide if important
        if has_keywords or used_multiple_tools:
            # Create concise summary
            summary = f"**Query**: {message[:200]}\n\n**Key Findings**:\n{result[:500]}"

            if tool_results:
                tool_names = [t.get("tool") for t in tool_results if t.get("tool")]
                summary += f"\n\n**Tools Used**: {', '.join(tool_names)}"

            self.update_memory("Learning", summary)
            return True

        return False

    def save_generated_tool(self, tool_name: str, tool_code: str):
        """Persist dynamically generated tool"""
        try:
            tool_file = self.tools_path / f"{tool_name}.py"
            tool_file.write_text(tool_code)
            logger.info(f"🔧 Generated tool saved: {tool_name}")
        except Exception as e:
            logger.error(f"Failed to save generated tool {tool_name}: {e}")

    def list_generated_tools(self) -> List[str]:
        """List all generated tools in workspace"""
        try:
            return [f.stem for f in self.tools_path.glob("*.py")]
        except Exception as e:
            logger.error(f"Failed to list generated tools: {e}")
            return []

    def save_session_log(self, session_id: str, messages: List[Dict]):
        """Save session transcript as JSONL"""
        try:
            session_file = self.sessions_path / f"{session_id}.jsonl"

            with open(session_file, "a") as f:
                for msg in messages:
                    f.write(json.dumps(msg) + "\n")

            logger.debug(f"💾 Session log saved: {session_id}")

        except Exception as e:
            logger.error(f"Failed to save session log {session_id}: {e}")

    def load_session_log(self, session_id: str) -> List[Dict]:
        """Load session transcript from JSONL"""
        try:
            session_file = self.sessions_path / f"{session_id}.jsonl"

            if not session_file.exists():
                return []

            messages = []
            with open(session_file, "r") as f:
                for line in f:
                    messages.append(json.loads(line.strip()))

            return messages

        except Exception as e:
            logger.error(f"Failed to load session log {session_id}: {e}")
            return []

    def get_context_size(self) -> int:
        """Get recommended context size from config"""
        config = self.read_config()
        return config.get("max_context_chars", 3000)

    def get_max_iterations(self) -> int:
        """Get max iterations for OpenClaw loop"""
        config = self.read_config()
        return config.get("max_iterations", 10)
