"""
TokioAI Agent — The autonomous agent loop.

Implements: Think → Act → Observe → Learn
With robust tool parsing, error recovery, and no infinite loops.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .llm import BaseLLM, LLMResponse, create_llm
from .llm.base import ToolUseBlock
from .tools import ToolRegistry, ToolExecutor, ToolResult
from .tools.builtin.loader import load_builtin_tools
from .tools.plugins.loader import load_plugins
from .memory.workspace import Workspace
from .memory.session import SessionManager
from .context_builder import build_system_prompt
from .context.auto_compact import AutoCompactor
from .context.auto_memory import AutoMemoryExtractor
from .context.token_counter import estimate_conversation_tokens, get_context_usage
from .error_learner import ErrorLearner
from .entity_sync import sync_after_response, notify_incoming_message, on_security_event
from .self_healing import SelfHealingEngine
from .security.prompt_guard import PromptGuard
from .security.input_sanitizer import sanitize_command, sanitize_sql
from .watchdog import get_watchdog
from .skills import get_skill_registry
from .skills.bundled import register_bundled_skills
from .subagents import SubAgentManager
from .subagents.tool import execute_subagent_tool
from .subagents.coordinator_prompt import get_coordinator_context, should_use_coordinator

logger = logging.getLogger(__name__)

# Regex to extract tool calls from LLM output
# Matches: TOOL:name({"key": "value"})  or  TOOL:name()
TOOL_CALL_RE = re.compile(
    r'TOOL:(\w+)\((\{.*?\}|\(\))\)',
    re.DOTALL,
)

# Also match simpler format without braces for empty args
TOOL_CALL_SIMPLE_RE = re.compile(
    r'TOOL:(\w+)\(\)',
)


class TokioAgent:
    """The main autonomous agent."""

    MAX_TOOL_ROUNDS = 0  # Max consecutive tool-use rounds per message (0 = unlimited)
    MAX_TOTAL_TIME = 0  # Max seconds per message (0 = unlimited)

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        workspace: Optional[Workspace] = None,
        plugin_dirs: Optional[List[str]] = None,
        on_tool_start: Optional[Callable] = None,
        on_tool_end: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None,
    ):
        # Initialize components
        self.workspace = workspace or Workspace()
        self.llm = llm or create_llm()
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.error_learner = ErrorLearner()
        self.prompt_guard = PromptGuard(strict_mode=True)
        self.session_manager = SessionManager(self.workspace)

        # Event callbacks for UI
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._on_thinking = on_thinking

        # Load all tools (builtin + plugins)
        load_builtin_tools(self.registry)
        self._load_extra_tools(plugin_dirs)

        # Watchdog
        self.watchdog = get_watchdog()

        # Self-healing engine
        self.self_healing = SelfHealingEngine(
            on_event=lambda t, m, s: asyncio.ensure_future(on_security_event(t, m, s))
        )

        # Auto-compaction (Claude Code-style context management)
        self.auto_compactor = AutoCompactor(self.llm)

        # Auto-memory extraction (background memory persistence)
        self.auto_memory = AutoMemoryExtractor(self.llm, self.workspace)

        # Skills system (slash commands)
        self.skill_registry = get_skill_registry()
        register_bundled_skills()

        # Subagent manager (parallel workers)
        self.subagent_manager = SubAgentManager(
            llm=self.llm,
            registry=self.registry,
            executor=self.executor,
        )
        self._register_subagent_tool()

        # Stats
        self._stats = {
            "messages_processed": 0,
            "tools_executed": 0,
            "errors_recovered": 0,
            "total_tokens": 0,
            "compactions": 0,
            "memories_extracted": 0,
        }

        logger.info(
            f"🚀 TokioAI Agent initialized: "
            f"LLM={self.llm.display_name()}, "
            f"Tools={self.registry.count()}"
        )

    def start_background_tasks(self):
        """Start background tasks (watchdog, self-healing, etc.). Call once after event loop is running."""
        self.watchdog.start()
        self.self_healing.start()

    async def process_message(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        images: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Process a user message through the Think → Act → Observe → Learn loop.

        Args:
            user_message: The user's input.
            session_id: Optional session ID for conversation continuity.
            images: Optional list of images [{"data": base64, "media_type": "image/..."}].

        Returns:
            The agent's final response.
        """
        start_time = time.monotonic()
        self._stats["messages_processed"] += 1

        # ── ENTITY: Show thinking face while processing ──
        asyncio.ensure_future(notify_incoming_message(session_id or ""))

        # ── SECURITY: Prompt Guard ──
        guard_result = self.prompt_guard.check(user_message)
        if guard_result.blocked:
            threat_names = ", ".join(t[0] for t in guard_result.threats)
            logger.warning(f"🛡️ Input blocked: {threat_names}")
            return (
                "🛡️ Tu mensaje fue bloqueado por el sistema de seguridad. "
                f"Razón: {guard_result.threats[0][2] if guard_result.threats else 'contenido sospechoso'}. "
                "Por favor, reformula tu solicitud."
            )
        # Use sanitized input
        user_message = guard_result.sanitized_input

        # ── SKILLS: Expand /commands into full prompts ──
        if user_message.startswith("/"):
            expanded = self.skill_registry.expand(user_message)
            if expanded:
                logger.info(f"Skill expanded: {user_message.split()[0]}")
                user_message = expanded

        # Ensure session exists
        if not session_id:
            session_id = self.session_manager.create_session()

        # Record user message
        self.session_manager.add_message(session_id, "user", user_message)

        # Build system prompt (with per-user isolation)
        extra = self._get_extra_instructions()

        # Add coordinator context for complex tasks
        if should_use_coordinator(user_message):
            extra.append(get_coordinator_context())

        system_prompt = build_system_prompt(
            workspace=self.workspace,
            registry=self.registry,
            extra_instructions=extra,
            session_id=session_id,
        )

        # Get conversation history (excludes the message we just added)
        full_conversation = self.session_manager.get_conversation(session_id)
        # Remove the last message (the one we just added) since it's passed as user_prompt
        # But only if there are at least 2 messages — don't lose all context
        if full_conversation and len(full_conversation) > 1:
            conversation = full_conversation[:-1]
        else:
            conversation = None

        # ── AUTO-COMPACT: Check if context needs compaction ──
        if conversation and self.auto_compactor.should_compact(
            system_prompt, conversation, user_message
        ):
            logger.info("Context near limit — running auto-compaction")
            compacted = await self.auto_compactor.compact(system_prompt, conversation)
            if compacted:
                # Replace session messages with compacted version
                self.session_manager.replace_messages(session_id, compacted)
                # Re-add the current user message
                self.session_manager.add_message(session_id, "user", user_message)
                # Refresh conversation
                full_conversation = self.session_manager.get_conversation(session_id)
                conversation = full_conversation[:-1] if len(full_conversation) > 1 else None
                self._stats["compactions"] += 1
                logger.info(f"Compaction complete — conversation now {len(compacted)} messages")

        # ── Get tool definitions for native tool use ──
        anthropic_tools = self.registry.to_anthropic_tools()

        # ── Build messages for the API (native format) ──
        api_messages = list(conversation or [])

        # Add user message with images if present
        if images:
            user_content = []
            for img in images:
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("media_type", "image/jpeg"),
                        "data": img["data"],
                    },
                })
            user_content.append({"type": "text", "text": user_message})
            api_messages.append({"role": "user", "content": user_content})
        else:
            api_messages.append({"role": "user", "content": user_message})

        # ── Think → Act → Observe → Learn loop (native tool use) ──
        final_response = ""

        max_rounds = self.MAX_TOOL_ROUNDS or 999999
        for round_num in range(max_rounds):
            elapsed = time.monotonic() - start_time
            if self.MAX_TOTAL_TIME and elapsed > self.MAX_TOTAL_TIME:
                final_response = "Tiempo maximo alcanzado."
                break

            if self._on_thinking:
                self._on_thinking(round_num + 1)

            try:
                response = await self.llm.generate_with_tools(
                    system_prompt=system_prompt,
                    messages=api_messages,
                    tools=anthropic_tools,
                    max_tokens=16384,
                )
                self._stats["total_tokens"] += response.input_tokens + response.output_tokens
            except Exception as e:
                logger.error(f"LLM error: {e}")
                # Fallback to legacy generate without tools
                try:
                    response = await self.llm.generate(
                        system_prompt=system_prompt,
                        user_prompt=user_message,
                        conversation=conversation,
                        max_tokens=16384,
                    )
                    self._stats["total_tokens"] += response.input_tokens + response.output_tokens
                    final_response = response.text
                except Exception as e2:
                    final_response = f"Error comunicando con el LLM: {e2}"
                break

            # Handle truncated response (max_tokens hit mid-tool-use)
            if response.finish_reason == "max_tokens":
                if response.has_tool_use:
                    api_messages.append({"role": "assistant", "content": self._serialize_content(response.raw.content)})
                    trunc_results = []
                    for tool_block in response.tool_use:
                        trunc_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": "ERROR: Tu respuesta fue truncada (max_tokens). "
                                       "Divide el contenido en partes mas pequenas. "
                                       "Para archivos grandes, usa bash con cat/heredoc o escribe por secciones.",
                            "is_error": True,
                        })
                    api_messages.append({"role": "user", "content": trunc_results})
                    logger.warning("Response truncated at max_tokens, retrying")
                    continue
                else:
                    final_response = response.text
                    break

            # Check if model wants to use tools
            if not response.has_tool_use:
                final_response = response.text
                break

            # Add assistant response to conversation (with tool_use blocks)
            api_messages.append({"role": "assistant", "content": self._serialize_content(response.raw.content)})

            # Execute each tool and build tool_result blocks
            tool_results = []
            for tool_block in response.tool_use:
                # Validate required arguments
                tool_def = self.registry.get(tool_block.name)
                if tool_def and tool_def.parameters:
                    required = [
                        p for p, desc in tool_def.parameters.items()
                        if "optional" not in desc.lower() and "default" not in desc.lower()
                    ]
                    missing = [p for p in required if p not in tool_block.input]
                    if missing:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": f"ERROR: Argumentos faltantes: {', '.join(missing)}. "
                                       f"Reintenta con contenido mas corto o dividido en partes.",
                            "is_error": True,
                        })
                        continue

                if self._on_tool_start:
                    self._on_tool_start(tool_block.name, tool_block.input)

                # Sanitize and execute
                args = self._sanitize_tool_args(tool_block.name, tool_block.input)
                timeout = self._get_tool_timeout(tool_block.name)

                try:
                    if tool_block.name == "subagent":
                        from .subagents.tool import execute_subagent_tool
                        raw = await asyncio.wait_for(
                            execute_subagent_tool(self.subagent_manager, args),
                            timeout=timeout,
                        )
                        result = ToolResult(tool_name="subagent", success=True, output=raw if isinstance(raw, str) else str(raw))
                    else:
                        result = await asyncio.wait_for(
                            self.executor.execute(tool_block.name, args),
                            timeout=timeout,
                        )
                except asyncio.TimeoutError:
                    result = ToolResult(
                        tool_name=tool_block.name,
                        success=False,
                        output="",
                        error=f"Timeout after {timeout}s",
                    )

                self._stats["tools_executed"] += 1

                if self._on_tool_end:
                    self._on_tool_end(tool_block.name, result)

                # Track errors
                if result.success:
                    self.error_learner.reset_tool(tool_block.name)
                else:
                    suggestion = self.error_learner.analyze_error(
                        tool_block.name, result.error or ""
                    )
                    if suggestion is None:
                        self._stats["errors_recovered"] += 1

                # Build tool_result content
                output = result.output or result.error or ""
                if len(output) > 8000:
                    output = output[:8000] + "\n[TRUNCADO]"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": output,
                    "is_error": not result.success,
                })

            # Add tool results to conversation
            api_messages.append({"role": "user", "content": tool_results})

            # If response also had text, include it
            if response.text:
                final_response = response.text

        else:
            final_response = final_response or "Maximo de iteraciones alcanzado. Usa --max-rounds 0 para modo ilimitado."

        clean_response = final_response.strip()

        # Record assistant response
        self.session_manager.add_message(session_id, "assistant", clean_response)

        # Check if user shared their name (per-user isolated)
        self._detect_user_info(user_message, session_id)

        # ── AUTO-MEMORY: Extract durable memories in background ──
        asyncio.ensure_future(self._run_auto_memory(session_id, clean_response))

        # ── ENTITY: Sync emotion + display after response ──
        asyncio.ensure_future(sync_after_response(
            user_message=user_message,
            response=clean_response,
            session_id=session_id or "",
        ))

        return clean_response

    async def _run_auto_memory(self, session_id: str, last_response: str) -> None:
        """Run auto-memory extraction in background (non-blocking)."""
        try:
            messages = self.session_manager.get_conversation(session_id)
            count = await self.auto_memory.extract_if_needed(
                messages=messages,
                session_id=session_id,
                last_response=last_response,
            )
            if count > 0:
                self._stats["memories_extracted"] += count
        except Exception as e:
            logger.debug(f"Auto-memory extraction error: {e}")

    @staticmethod
    def _serialize_content(content) -> list:
        """Serialize Anthropic content blocks to plain dicts for API re-submission."""
        result = []
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                result.append({"type": "text", "text": block.text})
            elif block_type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            else:
                # Unknown block type, try to convert
                if hasattr(block, "model_dump"):
                    result.append(block.model_dump())
                elif isinstance(block, dict):
                    result.append(block)
        return result

    def _are_independent(self, tool_calls: List[Tuple[str, Dict]]) -> bool:
        """Check if tool calls are independent (can run in parallel)."""
        names = [name for name, _ in tool_calls]
        # Different tools are likely independent
        # Same tool called multiple times with different args is also independent
        # Tools that modify state should not run in parallel
        stateful = {"bash", "write_file", "python", "host_control", "docker",
                    "task_orchestrator", "self_heal", "subagent"}
        return not any(n in stateful for n in names)

    async def _execute_single_tool(self, tool_name: str, tool_args: Dict) -> str:
        """Execute a single tool call and return formatted result text."""
        if self._on_tool_start:
            self._on_tool_start(tool_name, tool_args)

        tool_args = self._sanitize_tool_args(tool_name, tool_args)

        # Adaptive timeout
        timeout = self._get_tool_timeout(tool_name)
        try:
            result = await asyncio.wait_for(
                self.executor.execute(tool_name, tool_args),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._stats["tools_executed"] += 1
            return (
                f"\n## Error in {tool_name} (timeout after {timeout}s):\n"
                f"Tool execution timed out.\n"
            )

        self._stats["tools_executed"] += 1

        if self._on_tool_end:
            self._on_tool_end(tool_name, result)

        if result.success:
            self.error_learner.reset_tool(tool_name)
            output = result.output or ""
            if len(output) > 8000:
                output = output[:8000] + "\n[TRUNCADO]"
            return f"\n## Result of {tool_name}:\n{output}\n"
        else:
            suggestion = self.error_learner.analyze_error(tool_name, result.error or "")
            if suggestion is None:
                return (
                    f"\n## Error in {tool_name} (max retries reached):\n"
                    f"{result.error}\n"
                    f"Do NOT retry this tool. Use an alternative approach.\n"
                )
            else:
                self._stats["errors_recovered"] += 1
                return (
                    f"\n## Error in {tool_name}:\n"
                    f"{result.error}\n"
                    f"Suggestion: {suggestion}\n"
                )

    async def _execute_tools_parallel(self, tool_calls: List[Tuple[str, Dict]]) -> str:
        """Execute independent tools in parallel."""
        tasks = []
        for tool_name, tool_args in tool_calls:
            tasks.append(self._execute_single_tool(tool_name, tool_args))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        text = ""
        for r in results:
            if isinstance(r, Exception):
                text += f"\n## Error: {r}\n"
            else:
                text += r
        return text

    def _get_tool_timeout(self, tool_name: str) -> float:
        """Get adaptive timeout for a tool based on its type."""
        slow_tools = {"gcp_waf_deploy", "gcp_compute", "task_orchestrator"}
        medium_tools = {"docker", "host_control", "router_control", "self_heal",
                        "document", "postgres_query", "bash"}
        robot_tools = {"pidog", "picar", "drone", "coffee"}
        if tool_name in slow_tools:
            return 300.0
        if tool_name in medium_tools:
            return 120.0
        if tool_name in robot_tools:
            return 30.0
        return 60.0

    def _extract_tool_calls(
        self, text: str
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract tool calls from LLM output.

        Supports formats:
            TOOL:name({"key": "value"})
            TOOL:name()
        """
        calls = []

        # Try the full format first
        for match in TOOL_CALL_RE.finditer(text):
            name = match.group(1)
            args_str = match.group(2)
            try:
                if args_str == "()" or args_str == "{}":
                    args = {}
                else:
                    args = json.loads(args_str)
                calls.append((name, args))
            except json.JSONDecodeError:
                # Try to fix common JSON issues
                fixed = self._fix_json(args_str)
                if fixed is not None:
                    calls.append((name, fixed))
                else:
                    logger.warning(f"Could not parse tool args: {args_str[:100]}")

        # Also check simple format
        if not calls:
            for match in TOOL_CALL_SIMPLE_RE.finditer(text):
                name = match.group(1)
                calls.append((name, {}))

        # Deduplicate (same tool+args in same response)
        seen = set()
        unique_calls = []
        for name, args in calls:
            key = f"{name}:{json.dumps(args, sort_keys=True)}"
            if key not in seen:
                seen.add(key)
                unique_calls.append((name, args))

        return unique_calls

    def _fix_json(self, s: str) -> Optional[Dict]:
        """Attempt to fix common JSON parsing issues."""
        # Remove trailing/leading whitespace
        s = s.strip()

        # Try wrapping in braces
        if not s.startswith("{"):
            s = "{" + s + "}"

        # Fix single quotes
        s = s.replace("'", '"')

        # Fix trailing commas
        s = re.sub(r',\s*}', '}', s)
        s = re.sub(r',\s*]', ']', s)

        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    def _clean_response(self, text: str) -> str:
        """Remove tool call syntax from the final response."""
        # Remove TOOL: lines
        cleaned = TOOL_CALL_RE.sub("", text)
        cleaned = TOOL_CALL_SIMPLE_RE.sub("", cleaned)

        # Clean up excessive whitespace
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def _sanitize_tool_args(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply security sanitization to tool arguments."""
        if tool_name == "bash" and "command" in args:
            is_safe, sanitized, warning = sanitize_command(args["command"])
            if not is_safe:
                # Replace the command with an echo of the warning
                args["command"] = f"echo '{warning}'"
                logger.warning(f"🛡️ Blocked bash command: {warning}")
            elif warning:
                logger.info(f"🛡️ Bash warning: {warning}")

        elif tool_name == "postgres_query" and "query" in args:
            is_safe, sanitized, warning = sanitize_sql(args["query"])
            if not is_safe:
                args["query"] = f"SELECT '{warning}' as security_block"
                logger.warning(f"🛡️ Blocked SQL: {warning}")
            elif warning:
                logger.info(f"🛡️ SQL warning: {warning}")

        return args

    def _detect_user_info(self, message: str, session_id: str = "") -> None:
        """Detect if the user shared personal info to remember (per-user)."""
        lower = message.lower()

        # Extract user_id from session_id
        user_id = ""
        if session_id and session_id.startswith("telegram-"):
            user_id = session_id.replace("telegram-", "")

        # Detect name patterns
        name_patterns = [
            r"(?:me llamo|mi nombre es|soy|llamame|llámame)\s+(\w+)",
            r"(?:my name is|i'm|call me)\s+(\w+)",
        ]
        for pattern in name_patterns:
            m = re.search(pattern, lower)
            if m:
                name = m.group(1).capitalize()
                self.workspace.set_preference("user_name", name, user_id=user_id)
                self.workspace.add_memory(f"El usuario se llama {name}", user_id=user_id)
                logger.info(f"👤 Detected user name: {name} (user_id={user_id})")
                break

    def _get_extra_instructions(self) -> List[str]:
        """Get extra instructions from skills, error learner, etc."""
        instructions = []

        # Error learner context
        error_ctx = self.error_learner.get_context_for_prompt()
        if error_ctx:
            instructions.append(error_ctx)

        return instructions

    def _register_subagent_tool(self) -> None:
        """Register the subagent tool for worker orchestration."""
        manager = self.subagent_manager

        async def _subagent_executor(**kwargs):
            return await execute_subagent_tool(manager, kwargs)

        self.registry.register(
            name="subagent",
            description=(
                "Lanzar y gestionar workers autonomos para tareas complejas. "
                "Workers corren en paralelo con su propio loop de herramientas. "
                "Acciones: spawn, spawn_parallel, wait, wait_all, kill, status, results."
            ),
            category="orchestration",
            parameters={
                "action": "spawn|spawn_parallel|wait|wait_all|kill|status|results",
                "task": "La tarea para el worker (requerido en spawn)",
                "worker_type": "research|implement|verify|general (default: general)",
                "description": "Descripcion corta del worker (3-5 palabras)",
                "context": "Contexto adicional para el worker",
                "agent_id": "ID del worker (para wait/kill/results)",
                "tasks": "Lista de tareas (para spawn_parallel)",
            },
            executor=_subagent_executor,
            source="builtin",
            examples=[
                'TOOL:subagent({"action": "spawn", "task": "Buscar todos los archivos Python que usan asyncio en el proyecto", "worker_type": "research", "description": "Search asyncio usage"})',
                'TOOL:subagent({"action": "spawn_parallel", "tasks": [{"task": "Buscar imports no usados", "worker_type": "research", "description": "unused imports"}, {"task": "Buscar funciones duplicadas", "worker_type": "research", "description": "duplicate functions"}]})',
                'TOOL:subagent({"action": "wait_all"})',
                'TOOL:subagent({"action": "status"})',
            ],
        )

    def _load_extra_tools(self, plugin_dirs: Optional[List[str]]) -> None:
        """Load plugin tools."""
        dirs = plugin_dirs or []

        # Check for v1.8 tools
        v18_dir = "/home/tokio/tokioai-v1.8/tokio-cli/engine/tools"
        import os
        if os.path.isdir(v18_dir):
            dirs.append(v18_dir)

        if dirs:
            load_plugins(self.registry, dirs)

    async def process_message_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        images: Optional[List[Dict[str, str]]] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ):
        """Streaming version with native tool use. Yields (event_type, data) tuples.

        Event types:
            ("thinking", round_num)      — Starting a thinking round
            ("token", text)              — Streaming text token from LLM
            ("tool_start", (name, args)) — Tool execution starting
            ("tool_end", (name, output)) — Tool execution finished
            ("done", response)           — Processing complete
            ("error", message)           — Error occurred
        """
        start_time = time.monotonic()
        self._stats["messages_processed"] += 1

        asyncio.ensure_future(notify_incoming_message(session_id or ""))

        # Security check
        guard_result = self.prompt_guard.check(user_message)
        if guard_result.blocked:
            threat_names = ", ".join(t[0] for t in guard_result.threats)
            yield ("done", f"⚠️ Bloqueado por seguridad: {threat_names}")
            return

        # Session management
        if not session_id:
            session_id = self.session_manager.create_session()
        self.session_manager.add_message(session_id, "user", user_message)

        # Skill detection
        extra = self._get_extra_instructions()
        if user_message.startswith("/"):
            parts = user_message.split(maxsplit=1)
            cmd = parts[0][1:]
            args = parts[1] if len(parts) > 1 else ""
            skill = self.skill_registry.get(cmd)
            if skill:
                extra.append(skill.get_prompt(args))

        if should_use_coordinator(user_message):
            extra.append(get_coordinator_context())

        system_prompt = build_system_prompt(
            self.workspace, self.registry,
            extra_instructions=extra if extra else None,
            session_id=session_id,
        )

        # Get conversation and auto-compact
        full_conversation = self.session_manager.get_conversation(session_id)
        conversation = full_conversation[:-1] if len(full_conversation) > 1 else None

        if conversation and self.auto_compactor.should_compact(
            system_prompt, conversation, user_message
        ):
            compacted = await self.auto_compactor.compact(system_prompt, conversation)
            if compacted:
                self.session_manager.replace_messages(session_id, compacted)
                self.session_manager.add_message(session_id, "user", user_message)
                full_conversation = self.session_manager.get_conversation(session_id)
                conversation = full_conversation[:-1] if len(full_conversation) > 1 else None
                self._stats["compactions"] += 1

        # Build API messages and tool definitions
        anthropic_tools = self.registry.to_anthropic_tools()
        api_messages = list(conversation or [])

        if images:
            user_content = []
            for img in images:
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("media_type", "image/jpeg"),
                        "data": img["data"],
                    },
                })
            user_content.append({"type": "text", "text": user_message})
            api_messages.append({"role": "user", "content": user_content})
        else:
            api_messages.append({"role": "user", "content": user_message})

        # ── Native tool use loop with streaming ──
        final_response = ""

        max_rounds = self.MAX_TOOL_ROUNDS or 999999
        for round_num in range(max_rounds):
            if cancel_event and cancel_event.is_set():
                final_response = "Cancelado."
                break

            elapsed = time.monotonic() - start_time
            if self.MAX_TOTAL_TIME and elapsed > self.MAX_TOTAL_TIME:
                final_response = "Tiempo maximo alcanzado."
                break

            yield ("thinking", round_num + 1)

            # Stream from LLM with native tool use
            try:
                llm_response = None
                streamed_text = ""
                tool_uses_building = {}  # id -> {name, json_parts}

                async for event_type, event_data in self.llm.stream_with_tools(
                    system_prompt=system_prompt,
                    messages=api_messages,
                    tools=anthropic_tools,
                    max_tokens=16384,
                ):
                    if cancel_event and cancel_event.is_set():
                        break

                    if event_type == "text":
                        streamed_text += event_data
                        yield ("token", event_data)
                    elif event_type == "content_block_end":
                        # Text block ended — tools may follow, show spinner
                        if streamed_text:
                            yield ("preparing", None)
                    elif event_type == "tool_start":
                        tool_uses_building[event_data["id"]] = {
                            "name": event_data["name"],
                            "json_parts": [],
                        }
                    elif event_type == "tool_json":
                        # Accumulate JSON for the current tool
                        for tid in tool_uses_building:
                            tool_uses_building[tid]["json_parts"].append(event_data)
                    elif event_type == "done":
                        llm_response = event_data

                if cancel_event and cancel_event.is_set():
                    final_response = "⛔ Cancelado."
                    break

                if llm_response:
                    self._stats["total_tokens"] += llm_response.input_tokens + llm_response.output_tokens

                    # Handle truncated response (max_tokens hit mid-tool-use)
                    if llm_response.finish_reason == "max_tokens":
                        if llm_response.has_tool_use:
                            # Response was cut off mid-tool-use — tell the LLM to retry with smaller output
                            api_messages.append({"role": "assistant", "content": self._serialize_content(llm_response.raw.content)})
                            # Send error for each truncated tool
                            trunc_results = []
                            for tool_block in llm_response.tool_use:
                                trunc_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_block.id,
                                    "content": "ERROR: Tu respuesta fue truncada (max_tokens). "
                                               "Divide el contenido en partes mas pequenas. "
                                               "Para archivos grandes, usa bash con cat/heredoc o escribe por secciones.",
                                    "is_error": True,
                                })
                            api_messages.append({"role": "user", "content": trunc_results})
                            logger.warning(f"Response truncated at max_tokens, asking LLM to retry with smaller output")
                            continue  # Retry this round
                        else:
                            # Text was truncated but no tools — just use what we have
                            final_response = llm_response.text
                            break

                    if not llm_response.has_tool_use:
                        final_response = llm_response.text
                        break

                    # Add assistant response to conversation
                    api_messages.append({"role": "assistant", "content": self._serialize_content(llm_response.raw.content)})

                    # Execute tools
                    tool_results = []
                    for tool_block in llm_response.tool_use:
                        # Validate required arguments before executing
                        tool_def = self.registry.get(tool_block.name)
                        if tool_def and tool_def.parameters:
                            required = [
                                p for p, desc in tool_def.parameters.items()
                                if "optional" not in desc.lower() and "default" not in desc.lower()
                            ]
                            missing = [p for p in required if p not in tool_block.input]
                            if missing:
                                err_msg = (f"ERROR: Argumentos faltantes: {', '.join(missing)}. "
                                           f"La respuesta fue probablemente truncada. "
                                           f"Reintenta con contenido mas corto o dividido en partes.")
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_block.id,
                                    "content": err_msg,
                                    "is_error": True,
                                })
                                yield ("tool_end", (tool_block.name, f"Args incompletos: {', '.join(missing)}"))
                                continue

                        yield ("tool_start", (tool_block.name, tool_block.input))

                        args = self._sanitize_tool_args(tool_block.name, tool_block.input)
                        timeout = self._get_tool_timeout(tool_block.name)

                        try:
                            if tool_block.name == "subagent":
                                from .subagents.tool import execute_subagent_tool
                                raw = await asyncio.wait_for(
                                    execute_subagent_tool(self.subagent_manager, args),
                                    timeout=timeout,
                                )
                                result = ToolResult(tool_name="subagent", success=True, output=raw if isinstance(raw, str) else str(raw))
                            else:
                                tool_task = asyncio.create_task(
                                    self.executor.execute(tool_block.name, args)
                                )
                                # Wait for tool OR cancel
                                if cancel_event:
                                    cancel_waiter = asyncio.create_task(cancel_event.wait())
                                    done, pending = await asyncio.wait(
                                        {tool_task, cancel_waiter},
                                        timeout=timeout,
                                        return_when=asyncio.FIRST_COMPLETED,
                                    )
                                    for p in pending:
                                        p.cancel()
                                        try:
                                            await p
                                        except (asyncio.CancelledError, Exception):
                                            pass
                                    if tool_task in done:
                                        result = tool_task.result()
                                    else:
                                        result = ToolResult(tool_name=tool_block.name, success=False, output="", error="Cancelado por el usuario.")
                                else:
                                    result = await asyncio.wait_for(tool_task, timeout=timeout)
                        except asyncio.TimeoutError:
                            result = ToolResult(tool_name=tool_block.name, success=False, output="", error=f"Timeout after {timeout}s")

                        self._stats["tools_executed"] += 1

                        output = result.output or result.error or ""
                        if len(output) > 8000:
                            output = output[:8000] + "\n[TRUNCADO]"

                        yield ("tool_end", (tool_block.name, output))

                        if result.success:
                            self.error_learner.reset_tool(tool_block.name)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": output,
                            "is_error": not result.success,
                        })

                    api_messages.append({"role": "user", "content": tool_results})
                else:
                    # No response received
                    final_response = streamed_text or "Sin respuesta del LLM."
                    break

            except Exception as e:
                logger.error(f"LLM stream error: {e}")
                yield ("error", str(e))
                return

        else:
            final_response = final_response or "Maximo de iteraciones alcanzado. Usa --max-rounds 0 para modo ilimitado."

        clean_response = final_response.strip()
        self.session_manager.add_message(session_id, "assistant", clean_response)
        self._detect_user_info(user_message, session_id)
        asyncio.ensure_future(self._run_auto_memory(session_id, clean_response))
        asyncio.ensure_future(sync_after_response(
            user_message=user_message, response=clean_response, session_id=session_id or "",
        ))

        yield ("done", clean_response)

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            **self._stats,
            "llm": self.llm.display_name(),
            "tools_count": self.registry.count(),
            "tools": self.registry.list_names(),
            "auto_memory": self.auto_memory.get_stats(),
            "subagents": self.subagent_manager.get_status(),
        }
