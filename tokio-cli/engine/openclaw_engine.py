"""
OpenClaw CLI Engine - Core autonomous agent loop

Think → Act → Observe → Learn

OpenClaw Principles:
1. Never Give Up - Always find alternatives when something fails
2. Complete Context - Use full context (3000+ chars), no truncation
3. Tool Mastery - Dynamically use 80+ tools
4. Error Learning - Remember failures, never repeat
5. Self-Repair - Auto-fix issues and recover
6. Workspace Persistence - SOUL, MEMORY, CONFIG
"""
import re
import json
import logging
import asyncio
import os
from typing import Dict, List, Optional, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential

from .workspace import Workspace
from .context_builder import ContextBuilder
from .tool_executor import ToolExecutor, ToolResult
from .error_learner import ErrorLearner
from .mcp_client import MCPClient
from .prompt_guard import PromptGuard

logger = logging.getLogger(__name__)

class OpenClawCLIEngine:
    """
    OpenClaw-based autonomous CLI agent engine.

    Main loop: Think → Act → Observe → Learn
    """

    def __init__(
        self,
        workspace_path: str = "/workspace/cli",
        llm_provider: str = "gemini",
        llm_api_key: Optional[str] = None
    ):
        # Initialize components
        self.workspace = Workspace(workspace_path)
        self.error_learner = ErrorLearner()
        self.prompt_guard = PromptGuard()

        # Initialize MCP client
        self.mcp_client = MCPClient()

        # Initialize tool executor
        self.tool_executor = ToolExecutor(self.workspace, self.mcp_client)

        # Initialize context builder
        self.context_builder = ContextBuilder(
            self.workspace,
            self.tool_executor.registry,
            self.error_learner
        )

        # LLM setup
        self.llm_provider = llm_provider
        self.llm_api_key = llm_api_key
        self._llm_client = None

        logger.info(f"🤖 OpenClaw Engine initialized (provider: {llm_provider})")

    async def initialize(self):
        """Initialize engine (connect to MCP, etc.)"""
        # Connect to MCP server (optional - can work without it)
        try:
            await self.mcp_client.connect()
            logger.info("✅ MCP server connected")
        except Exception as e:
            logger.warning(f"⚠️ MCP server unavailable: {e}")
            logger.warning("⚠️ Continuing without MCP tools...")

        # Initialize LLM client
        self._init_llm_client()

        logger.info("✅ OpenClaw Engine ready")

    def _init_llm_client(self):
        """Initialize LLM client based on provider"""
        if self.llm_provider == "gemini":
            api_key = self.llm_api_key or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not configured for Gemini provider")
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            # Use gemini-2.0-flash (default) or override with LLM_MODEL env var
            model_name = os.getenv("LLM_MODEL", "gemini-2.0-flash")
            self._llm_client = genai.GenerativeModel(model_name)
            logger.info(f"Using Gemini model: {model_name}")

        elif self.llm_provider == "anthropic":
            api_key = self.llm_api_key or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured for Anthropic provider")
            from anthropic import Anthropic
            self._llm_client = Anthropic(api_key=api_key)
            self._anthropic_model = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
            logger.info(f"Using Anthropic Claude model: {self._anthropic_model}")

        elif self.llm_provider == "openai":
            api_key = self.llm_api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured for OpenAI provider")
            from openai import OpenAI
            self._llm_client = OpenAI(api_key=api_key)
            # Use gpt-4o (default) or override with OPENAI_MODEL env var
            self._openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
            fallback_raw = os.getenv("OPENAI_FALLBACK_MODELS", "gpt-4o,gpt-4-turbo")
            self._openai_fallback_models = [m.strip() for m in fallback_raw.split(",") if m.strip()]
            logger.info(f"Using OpenAI model: {self._openai_model}")

        else:
            raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")

        logger.info(f"🧠 LLM client initialized: {self.llm_provider}")

    async def process_message(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        max_iterations: int = 10,
        stream_callback: Optional[callable] = None,
        session_id: str = "default"
    ) -> str:
        """
        Process user message using OpenClaw loop.

        Args:
            message: User command/question
            conversation_history: Previous messages in session
            max_iterations: Max iterations before giving up
            stream_callback: Optional callback for streaming updates

        Returns:
            Final response string

        OpenClaw Loop:
        1. Think - Build context and call LLM
        2. Act - Extract and execute tools
        3. Observe - Check results
        4. Learn - Update memory if important
        5. Repeat if needed (never give up!)
        """
        conversation_history = conversation_history or []

        # ================================================================
        # 0. KEYWORD INTERCEPTOR - Force tool calls for known patterns
        #    Skip if message starts with "__NOCAL__" (anti-recursion flag)
        # ================================================================
        if message.startswith("__NOCAL__"):
            message = message[len("__NOCAL__"):]
            intercepted = None
        else:
            # Check for model questions first (direct response, no LLM)
            model_response = self._intercept_model_question(message)
            if model_response:
                logger.info("🎯 Model question intercepted, responding directly")
                return model_response
            
            intercepted = self._intercept_known_patterns(message)
        if intercepted:
            logger.info(f"🎯 Intercepted pattern, forcing tool call: {intercepted['tool']}")
            try:
                result = await self.tool_executor.execute(
                    intercepted["tool"], intercepted["args"]
                )
                # Extract text from ToolResult
                result_text = result.output if hasattr(result, 'output') else str(result)
                
                # CRITICAL: For calendar patterns, ALWAYS return directly, never let LLM process
                # This prevents the LLM from asking about calendar sources
                if intercepted.get("post_action") == "telegram_send":
                    telegram_result = await self._calendar_telegram_flow(message, result_text, conversation_history, max_iterations, stream_callback, session_id)
                    # Return immediately - do NOT let LLM process this
                    return telegram_result
                
                # For other calendar queries, also return directly
                return result_text
            except Exception as e:
                logger.error(f"❌ Intercepted call failed: {e}", exc_info=True)
                # Even on error, return a helpful message instead of falling through to LLM
                return f"⚠️ Error al procesar la solicitud de calendario: {str(e)}\n\nPor favor, intentá de nuevo."

        # Prompt-WAF gate (lightweight)
        try:
            assessment = self.prompt_guard.assess(message)
            self.prompt_guard.audit(session_id=session_id, message=message, assessment=assessment)
            if self.prompt_guard.should_block(assessment):
                return (
                    "⚠️ Bloqueé esta solicitud por riesgo alto de inyección/prompt abuse.\n"
                    "Reformula en términos operativos concretos (qué sistema, qué acción, qué objetivo) "
                    "sin pedir ignorar reglas ni exponer secretos."
                )
        except Exception as e:
            logger.warning(f"Prompt guard check failed (continuing): {e}")

        task_complete = False
        iteration = 0
        previous_failed = False

        tool_results_history = []
        # Track tool calls to detect infinite loops
        tool_call_history = []  # List of (tool_name, args_hash) tuples
        consecutive_failures = 0
        max_consecutive_failures = 3

        while not task_complete and iteration < max_iterations:
            iteration += 1

            logger.info(f"🔄 OpenClaw iteration {iteration}/{max_iterations}")

            if stream_callback:
                await stream_callback({
                    "type": "progress",
                    "message": f"Thinking... (iteration {iteration})"
                })

            # ================================================================
            # 1. THINK - Build context and call LLM
            # ================================================================

            context = self.context_builder.build_full_context(
                user_message=message,
                conversation_history=conversation_history,
                iteration=iteration,
                previous_attempt_failed=previous_failed
            )

            try:
                llm_response = await self._call_llm(
                    system_prompt=context["system"],
                    user_prompt=context["user"]
                )

                logger.debug(f"LLM response: {llm_response[:200]}...")

            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return f"❌ Error: Failed to get response from LLM ({str(e)})"

            # ================================================================
            # 2. ACT - Extract and execute tools
            # ================================================================

            tool_calls = self._extract_tool_calls(llm_response)

            if not tool_calls:
                # Direct response, no tools needed
                logger.info("✅ Direct response (no tools)")

                # Learn from this interaction
                self.workspace.update_memory_if_important(
                    message,
                    llm_response,
                    tool_results_history
                )

                return llm_response

            # Execute tools
            if stream_callback:
                await stream_callback({
                    "type": "progress",
                    "message": f"Executing {len(tool_calls)} tool(s)..."
                })

            tool_results = []

            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                # Detect infinite loops: same tool with same args repeated
                args_hash = hash(str(sorted(tool_args.items())))
                recent_calls = [(name, args) for name, args in tool_call_history[-5:]]
                
                if (tool_name, args_hash) in recent_calls:
                    logger.warning(f"⚠️ Infinite loop detected: {tool_name} with same args repeated")
                    # Skip this tool call and suggest alternative
                    tool_results.append(ToolResult(
                        tool_name=tool_name,
                        success=False,
                        output="",
                        error=f"Loop infinito detectado: {tool_name} ya se ejecutó recientemente con los mismos argumentos. Intenta un enfoque diferente.",
                        args=tool_args
                    ))
                    continue

                # Validate tool exists before executing
                if not self.tool_executor.registry.has_tool(tool_name):
                    logger.error(f"❌ Tool not found: {tool_name}")
                    tool_results.append(ToolResult(
                        tool_name=tool_name,
                        success=False,
                        output="",
                        error=f"Herramienta '{tool_name}' no encontrada. Herramientas disponibles: {', '.join([t['name'] for t in self.tool_executor.registry.list_tools()[:10]])}",
                        args=tool_args
                    ))
                    continue

                logger.info(f"🔧 Executing: {tool_name}({tool_args})")
                
                # Track this tool call
                tool_call_history.append((tool_name, args_hash))

                if stream_callback:
                    await stream_callback({
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args
                    })

                # Execute with retry
                result = await self._execute_tool_with_retry(
                    tool_name,
                    tool_args,
                    max_attempts=3
                )

                tool_results.append(result)

                # Add to history for learning
                tool_results_history.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "success": result.success,
                    "output": result.output[:500]  # Truncate for memory
                })

                # Stream result
                if stream_callback:
                    await stream_callback({
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": result.success,
                        "output": result.output[:500]
                    })

            # ================================================================
            # 3. OBSERVE - Check results
            # ================================================================

            all_success = all(r.success for r in tool_results)

            if all_success:
                # All tools succeeded - generate final response
                logger.info("✅ All tools executed successfully")
                
                # Reset consecutive failures counter on success
                consecutive_failures = 0

                if stream_callback:
                    await stream_callback({
                        "type": "progress",
                        "message": "Analyzing results..."
                    })

                final_response = await self._generate_final_response(
                    llm_response,
                    tool_results
                )

                # ============================================================
                # 4. LEARN - Update memory if important
                # ============================================================

                self.workspace.update_memory_if_important(
                    message,
                    final_response,
                    tool_results_history
                )

                return final_response

            else:
                # Some tools failed - learn and retry
                failed_count = sum(not r.success for r in tool_results)
                logger.warning(f"⚠️ {failed_count} tool(s) failed")
                
                consecutive_failures += 1
                
                # Circuit breaker: if too many consecutive failures, stop trying
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(f"❌ Circuit breaker: {consecutive_failures} consecutive failures, stopping")
                    return f"""❌ No se pudo completar la tarea después de {consecutive_failures} intentos fallidos consecutivos.

Última respuesta:
{llm_response}

Errores encontrados:
{self._build_failure_summary(tool_results)}

Sugerencias:
- Verifica que los comandos/herramientas sean correctos
- Intenta dividir la tarea en pasos más pequeños
- Usa una descripción más específica de lo que necesitas"""

                for result in tool_results:
                    if not result.success:
                        # Record error
                        self.error_learner.record_error(
                            result.tool_name,
                            result.error or "Unknown error",
                            result.args
                        )

                # Add failures to conversation for next iteration
                failure_summary = self._build_failure_summary(tool_results)

                conversation_history.append({
                    "role": "assistant",
                    "content": llm_response
                })

                conversation_history.append({
                    "role": "tool",
                    "content": failure_summary
                })

                previous_failed = True

                # Continue loop to retry with alternative approach

        # Max iterations reached
        logger.error(f"❌ Max iterations ({max_iterations}) reached without success")

        return f"""❌ Unable to complete the task after {max_iterations} attempts.

Last attempt summary:
{llm_response}

Please try:
- Breaking the task into smaller steps
- Being more specific about what you need
- Using different terminology

Error history:
{self.error_learner.get_error_context_for_prompt()}
"""

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call LLM with system and user prompts.
        Supports fallback: Claude → OpenAI → Gemini
        """
        import os
        
        # Determine fallback chain based on primary provider
        primary_provider = self.llm_provider
        fallback_chain = []
        
        if primary_provider == "anthropic":
            fallback_chain = ["anthropic", "openai", "gemini"]
        elif primary_provider == "openai":
            fallback_chain = ["openai", "gemini", "anthropic"]
        elif primary_provider == "gemini":
            fallback_chain = ["gemini", "openai", "anthropic"]
        else:
            fallback_chain = [primary_provider]
        
        last_error = None
        
        for provider in fallback_chain:
            try:
                if provider == "gemini":
                    # Initialize Gemini client if needed
                    if not hasattr(self, '_gemini_client') or self._gemini_client is None:
                        api_key = os.getenv("GEMINI_API_KEY")
                        if not api_key:
                            logger.warning("GEMINI_API_KEY not available for fallback")
                            continue
                        import google.generativeai as genai
                        genai.configure(api_key=api_key)
                        model_name = os.getenv("LLM_MODEL", "gemini-2.0-flash")
                        self._gemini_client = genai.GenerativeModel(model_name)
                    
                    # Gemini: Combine system and user into single prompt
                    full_prompt = f"{system_prompt}\n\n{user_prompt}"
                    response = await asyncio.to_thread(
                        self._gemini_client.generate_content,
                        full_prompt
                    )
                    logger.info(f"✅ LLM response from Gemini fallback")
                    return response.text

                elif provider == "anthropic":
                    # Initialize Anthropic client if needed
                    if not hasattr(self, '_anthropic_client') or self._anthropic_client is None:
                        api_key = os.getenv("ANTHROPIC_API_KEY")
                        if not api_key:
                            logger.warning("ANTHROPIC_API_KEY not available for fallback")
                            continue
                        from anthropic import Anthropic
                        self._anthropic_client = Anthropic(api_key=api_key)
                        self._anthropic_model = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
                    
                    # Anthropic: Separate system and user
                    response = await asyncio.to_thread(
                        self._anthropic_client.messages.create,
                        model=self._anthropic_model,
                        max_tokens=4096,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_prompt}]
                    )
                    logger.info(f"✅ LLM response from Anthropic ({self._anthropic_model})")
                    return response.content[0].text

                elif provider == "openai":
                    # Initialize OpenAI client if needed
                    if not hasattr(self, '_openai_client') or self._openai_client is None:
                        api_key = os.getenv("OPENAI_API_KEY")
                        if not api_key:
                            logger.warning("OPENAI_API_KEY not available for fallback")
                            continue
                        from openai import OpenAI
                        self._openai_client = OpenAI(api_key=api_key)
                        self._openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
                    
                    # OpenAI: Route to chat.completions or responses depending on model family.
                    models_to_try = [self._openai_model] + [
                        m for m in self._openai_fallback_models if m != self._openai_model
                    ]
                    
                    for model_name in models_to_try:
                        try:
                            endpoint = self._resolve_openai_endpoint(model_name)
                            if endpoint == "responses":
                                result = await self._call_openai_responses(model_name, system_prompt, user_prompt)
                                logger.info(f"✅ LLM response from OpenAI ({model_name})")
                                return result
                            result = await self._call_openai_chat(model_name, system_prompt, user_prompt)
                            logger.info(f"✅ LLM response from OpenAI ({model_name})")
                            return result
                        except Exception as e:
                            logger.warning(f"OpenAI model failed [{model_name}]: {e}")
                            continue
                    
                    # If all OpenAI models failed, continue to next provider
                    raise RuntimeError("All OpenAI models failed")
                    
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ {provider} fallback failed: {e}")
                continue
        
        # All providers failed
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def _resolve_openai_endpoint(self, model_name: str) -> str:
        """
        Route OpenAI models to the correct endpoint.
        Advanced reasoning/newer families usually require the responses API.
        """
        normalized = (model_name or "").lower()
        if normalized.startswith(("o1", "o3", "gpt-5")):
            return "responses"
        return "chat"

    async def _call_openai_chat(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 4096
        }
        # Keep responses deterministic enough but still natural.
        params["temperature"] = 0.3

        response = await asyncio.to_thread(
            self._llm_client.chat.completions.create,
            **params
        )
        return response.choices[0].message.content or ""

    async def _call_openai_responses(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        response = await asyncio.to_thread(
            self._llm_client.responses.create,
            model=model_name,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_output_tokens=4096
        )
        return self._extract_openai_responses_text(response)

    def _extract_openai_responses_text(self, response) -> str:
        """Extract text from OpenAI responses API payloads robustly."""
        if getattr(response, "output_text", None):
            return response.output_text

        parts: List[str] = []
        for item in (getattr(response, "output", None) or []):
            for content in (getattr(item, "content", None) or []):
                text = getattr(content, "text", None)
                if text:
                    parts.append(text)

        extracted = "\n".join(parts).strip()
        return extracted or "No textual response returned by model."

    def _extract_tool_calls(self, llm_response: str) -> List[Dict]:
        """
        Extract tool calls from LLM response.

        Format: TOOL:tool_name({"arg": "value"})
        Also supports: TOOL:tool_name()  -> args = {}

        Returns:
            List of {"name": str, "args": dict}
        """
        # Pattern:
        # - TOOL:name({"a": 1})
        # - TOOL:name()  (empty args)
        # - TOOL:name    (no parentheses)
        # Keep it permissive: models sometimes omit args and parentheses for no-arg tools.
        pattern = r"TOOL:(\w+)(?:\(\s*(\{.*?\})?\s*\))?"

        matches = re.findall(pattern, llm_response, flags=re.DOTALL)

        tool_calls = []

        for match in matches:
            tool_name = match[0]
            args_str = ""
            if len(match) > 1:
                args_str = (match[1] or "").strip()

            try:
                if not args_str:
                    args = {}
                else:
                    args = json.loads(args_str)
                tool_calls.append({
                    "name": tool_name,
                    "args": args
                })

                logger.debug(f"Extracted tool call: {tool_name}({args})")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse tool args for {tool_name}: {e}")
                # Try to auto-fix (OpenClaw principle: never give up!)
                # Could use LLM to fix malformed JSON
                continue

        return tool_calls

    async def _execute_tool_with_retry(
        self,
        tool_name: str,
        args: Dict,
        max_attempts: int = 3
    ) -> ToolResult:
        """
        Execute tool with automatic retry.

        OpenClaw Principle: Never give up - try alternatives on failure.
        """
        for attempt in range(1, max_attempts + 1):
            # Check if we should retry
            if attempt > 1:
                if not self.error_learner.should_retry(tool_name, args, attempt, max_attempts):
                    logger.info(f"🚫 Skipping retry for {tool_name} (learned not to)")
                    break

                logger.info(f"🔄 Retry attempt {attempt}/{max_attempts} for {tool_name}")
                await asyncio.sleep(1 * attempt)  # Exponential backoff

            # Execute
            result = await self.tool_executor.execute(tool_name, args)

            if result.success:
                return result

            # Failed - record error
            self.error_learner.record_error(tool_name, result.error or "Unknown error", args)

            # Try auto-fix on last attempt
            if attempt == max_attempts:
                logger.warning(f"⚠️ All retry attempts failed for {tool_name}")

        # Return last failed result
        return result

    async def _generate_final_response(
        self,
        llm_response: str,
        tool_results: List[ToolResult]
    ) -> str:
        """
        Generate final response incorporating tool results.

        Calls LLM again to synthesize tool outputs into coherent answer.
        """
        # Build tool results summary
        results_summary = "\n\n".join([
            f"**Tool: {r.tool_name}**\nArgs: {r.args}\nResult:\n{r.output}"
            for r in tool_results
        ])

        # Use the same system prompt with language rules
        system_prompt = self.context_builder.build_system_prompt()

        # Ask LLM to generate final response
        prompt = f"""Basándote en los resultados de las herramientas ejecutadas, proporciona una respuesta clara y concisa a la pregunta del usuario.

⚠️⚠️⚠️ REGLA CRÍTICA: SIEMPRE RESPONDE EN ESPAÑOL. NUNCA uses frases en inglés como "Okay", "I am", "is now playing". SIEMPRE usa "Está bien", "Estoy", "está reproduciendo".

Respuesta Original:
{llm_response}

Resultados de las Herramientas:
{results_summary}

Proporciona una respuesta clara en ESPAÑOL basándote en los resultados de las herramientas."""

        try:
            final_response = await self._call_llm(
                system_prompt=system_prompt,
                user_prompt=prompt
            )

            return final_response

        except Exception as e:
            logger.error(f"Failed to generate final response: {e}")

            # Fallback: Return tool results directly in Spanish
            return f"""Aquí están los resultados:

{results_summary}
"""

    def _build_failure_summary(self, tool_results: List[ToolResult]) -> str:
        """Build summary of tool failures for retry context"""
        failures = [r for r in tool_results if not r.success]

        summary = f"⚠️ {len(failures)} tool(s) failed:\n\n"

        for result in failures:
            summary += f"- **{result.tool_name}**: {result.error}\n"

            # Get alternative suggestion
            suggestion = self.error_learner.get_alternative_suggestion(
                result.tool_name,
                result.args or {}
            )

            if suggestion:
                summary += f"  💡 Suggestion: {suggestion}\n"

        summary += "\n**Try a different approach or alternative tools.**"

        return summary

    def _intercept_model_question(self, message: str) -> Optional[str]:
        """
        Intercept questions about what model is being used.
        Returns direct response with REAL model information, bypassing LLM.
        """
        import os
        import re as _re
        
        msg = message.lower().strip()
        
        # Detect model-related questions
        model_keywords = [
            "que modelo", "qué modelo", "que modelo estas", "qué modelo estás",
            "que modelo usas", "qué modelo usás", "que modelo usas para",
            "que modelo estas usando", "qué modelo estás usando",
            "modelo estas usando", "modelo usas", "modelo usas para",
            "con que modelo", "con qué modelo", "que llm", "qué llm",
        ]
        
        if any(kw in msg for kw in model_keywords):
            # Get REAL model information from environment
            llm_provider = os.getenv("LLM_PROVIDER", "openai")
            
            if llm_provider == "anthropic":
                claude_model = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
                # Format model name nicely
                if "opus" in claude_model.lower():
                    model_name = "Claude Opus"
                    if "4-5" in claude_model:
                        version = "4.5"
                    elif "4-1" in claude_model:
                        version = "4.1"
                    elif "4-0" in claude_model or "4.0" in claude_model:
                        version = "4.0"
                    else:
                        version = "3"
                    display_name = f"Claude Opus {version}"
                elif "sonnet" in claude_model.lower():
                    model_name = "Claude Sonnet"
                    if "4-5" in claude_model:
                        version = "4.5"
                    elif "4-0" in claude_model or "4.0" in claude_model:
                        version = "4.0"
                    elif "3-7" in claude_model:
                        version = "3.7"
                    elif "3-5" in claude_model:
                        version = "3.5"
                    else:
                        version = "3"
                    display_name = f"Claude Sonnet {version}"
                elif "haiku" in claude_model.lower():
                    model_name = "Claude Haiku"
                    if "4-5" in claude_model:
                        version = "4.5"
                    elif "3-5" in claude_model:
                        version = "3.5"
                    else:
                        version = "3"
                    display_name = f"Claude Haiku {version}"
                else:
                    display_name = claude_model
                
                return f"Estoy usando **{display_name} ({claude_model})** de Anthropic.\n\nEs el modelo más avanzado de Anthropic disponible, con capacidades extendidas de razonamiento y análisis. 🧠"
            
            elif llm_provider == "openai":
                openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
                # Format model name nicely
                if "gpt-4o" in openai_model.lower():
                    display_name = "GPT-4o"
                elif "gpt-4-turbo" in openai_model.lower():
                    display_name = "GPT-4 Turbo"
                elif "gpt-4" in openai_model.lower():
                    display_name = "GPT-4"
                else:
                    display_name = openai_model
                
                return f"Estoy usando **{display_name} ({openai_model})** de OpenAI.\n\nEs un modelo avanzado de OpenAI con excelente rendimiento en tareas complejas. 🚀"
            
            elif llm_provider == "gemini":
                gemini_model = os.getenv("LLM_MODEL", "gemini-2.0-flash")
                return f"Estoy usando **{gemini_model}** de Google (Gemini).\n\nEs un modelo rápido y eficiente de Google. ⚡"
            
            else:
                return f"Estoy usando el proveedor **{llm_provider}**.\n\n"
        
        return None

    def _intercept_known_patterns(self, message: str) -> Optional[Dict]:
        """
        Detect known user intent patterns and return forced tool calls.
        This bypasses the LLM for cases where it consistently ignores instructions.
        """
        msg = message.lower().strip()

        # ── Calendar patterns ──
        calendar_keywords = [
            "agenda", "calendario", "reuniones", "reunión", "meetings",
            "qué tengo", "que tengo", "mi semana", "mi día", "mi dia",
            "huecos libres", "horarios libres", "disponibilidad",
        ]
        share_keywords = [
            "envíale", "enviale", "mandále", "mandale", "compartí",
            "comparti", "enviar mi agenda", "manda mi agenda",
            "mandá mi", "manda mi", "envía mi", "envia mi",
            "pasale mi", "pasále mi",
        ]
        # Correction/regeneration keywords (when user wants to regenerate with corrections)
        correction_keywords = [
            "generalo", "genera", "hazlo", "haz", "corrige", "correge",
            "de nuevo", "otra vez", "regenera", "vuelve a",
            "el nombre es", "es", "se llama",
        ]

        is_calendar = any(k in msg for k in calendar_keywords)
        is_share = any(k in msg for k in share_keywords)
        is_correction = any(k in msg for k in correction_keywords)
        
        # If it's a correction message mentioning a name, treat as share (even without explicit "agenda")
        if is_correction:
            # Look for name pattern (capitalized words - 2+ words)
            import re as _re
            name_match = _re.search(
                r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)",
                message
            )
            if name_match:
                # If correction mentions a name, assume it's about regenerating agenda with corrected name
                # Treat as share request
                is_share = True
                is_calendar = True  # Also mark as calendar to trigger share logic

        if is_share and is_calendar:
            # Extract contact name (heuristic: after "a " before "por/para/de")
            import re as _re
            contact = "contacto"
            
            # Try multiple patterns to find the name
            # Pattern 1: "envíale mi agenda a [Nombre]"
            contact_match = _re.search(
                r"(?:enviale|envíale|mandale|mandále|compartí|comparti|pasale|pasále)\s+(?:mi\s+)?(?:agenda|calendario)\s+a\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?:\s+(?:por|para|de\s+hoy|hoy|mañana|lunes|martes|miércoles|jueves|viernes))",
                msg, _re.IGNORECASE
            )
            
            # Pattern 2: "a [Nombre]" (standalone)
            if not contact_match:
                contact_match = _re.search(
                    r"a\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)",
                    message  # Use original case
                )
            
            # Pattern 3: "el nombre es [Nombre]" or "[Nombre]" after correction keywords
            if not contact_match:
                contact_match = _re.search(
                    r"(?:el\s+nombre\s+es|se\s+llama|es)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)",
                    message, _re.IGNORECASE
                )
            
            # Pattern 4: Any capitalized name pattern (2+ words) in correction context
            # Extract first 2 capitalized words only
            if not contact_match and is_correction:
                all_caps = _re.findall(r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)", message)
                if len(all_caps) >= 2:
                    # Take first 2 capitalized words as name
                    contact = f"{all_caps[0]} {all_caps[1]}"
                    # Create a mock match object
                    class MockMatch:
                        def group(self, n):
                            return contact
                    contact_match = MockMatch()
            
            if contact_match:
                contact = contact_match.group(1).strip()
                # If contact contains correction keywords, extract only the name (first 2 words)
                if any(kw in contact.lower() for kw in ["generalo", "genera", "hazlo", "haz", "corrige", "de nuevo", "otra vez", "porfa", "perdon"]):
                    # Extract first 2 capitalized words only
                    name_parts = _re.findall(r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)", contact)
                    if len(name_parts) >= 2:
                        contact = f"{name_parts[0]} {name_parts[1]}"
                    elif len(name_parts) == 1:
                        contact = name_parts[0]

            # Determine period from message
            periods = []
            if "hoy" in msg:
                periods.append("today")
            if "mañana" in msg:
                periods.append("tomorrow")
            if "miércoles" in msg or "miercoles" in msg:
                # Calculate next Wednesday date
                from datetime import datetime, timedelta
                today = datetime.now()
                days_until_wed = (2 - today.weekday()) % 7
                if days_until_wed == 0 and "hoy" not in msg:
                    days_until_wed = 7
                wed_date = (today + timedelta(days=days_until_wed)).strftime("%Y-%m-%d")
                periods.append(wed_date)
            if "semana" in msg:
                periods.append("week")
            
            # If correction message and no period specified, default to week (covers multiple days)
            if not periods:
                if is_correction:
                    periods.append("week")  # Default to week for corrections (covers hoy+mañana+miércoles)
                else:
                    periods.append("today")

            # If multiple days requested, use 'week' to cover all
            if len(periods) > 1:
                period = "week"
            else:
                period = periods[0]

            logger.info(f"🎯 Calendar share intercepted: contact={contact}, period={period}")
            return {
                "tool": "calendar_tool",
                "args": {
                    "action": "share",
                    "params": {
                        "period": period,
                        "contact": contact,
                        "format": "telegram",
                    }
                },
                "post_action": "telegram_send",
                "contact": contact,
            }

        if is_calendar:
            # Determine period
            if "mañana" in msg:
                period = "tomorrow"
            elif "semana" in msg:
                period = "week"
            elif "mes" in msg:
                period = "month"
            elif "libre" in msg or "disponib" in msg or "hueco" in msg:
                return {
                    "tool": "calendar_tool",
                    "args": {"action": "free_slots", "params": {"period": "today"}},
                }
            elif "resumen" in msg:
                return {
                    "tool": "calendar_tool",
                    "args": {"action": "summary", "params": {}},
                }
            else:
                period = "today"
            return {
                "tool": "calendar_tool",
                "args": {"action": "query", "params": {"period": period}},
            }

        return None

    async def _calendar_telegram_flow(
        self, message, calendar_result, conversation_history,
        max_iterations, stream_callback, session_id
    ):
        """
        After getting calendar data, try to send via Telegram.
        If we can't find the contact's chat_id, return formatted text for the user.
        """
        import json as _json

        calendar_text = calendar_result if isinstance(calendar_result, str) else str(calendar_result)

        # Parse the calendar result
        try:
            cal_data = _json.loads(calendar_text)
            formatted = cal_data.get("formatted", cal_data.get("message", calendar_text))
        except (ValueError, TypeError):
            formatted = calendar_text

        # Try to find the contact's chat_id from getUpdates
        contact_name = ""
        import re as _re
        cm = _re.search(r"contact['\"]?\s*[:=]\s*['\"]?([^'\"}\n,]+)", str(calendar_result), _re.IGNORECASE)
        if not cm:
            cm = _re.search(r"a\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)", message)
        if cm:
            contact_name = cm.group(1).strip()

        # Try to send via Telegram Bot API
        try:
            # First, try to get chat_id from recent updates
            get_updates_result = await self.tool_executor.execute("bash", {
                "command": (
                    "curl -s \"https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates?limit=100\" "
                    "| python3 -c \""
                    "import sys,json; data=json.load(sys.stdin); "
                    "users={}; "
                    "[users.update({str(u.get('message',{}).get('chat',{}).get('id','')): "
                    "u.get('message',{}).get('from',{}).get('first_name','')}) "
                    "for u in data.get('result',[]) if u.get('message',{}).get('from')]; "
                    "print(json.dumps(users))\""
                )
            })

            chat_id = None
            if get_updates_result.success and get_updates_result.output:
                try:
                    users = _json.loads(get_updates_result.output.strip())
                    for cid, name in users.items():
                        if contact_name.lower().split()[0] in name.lower():
                            chat_id = cid
                            break
                except Exception:
                    pass

            if chat_id:
                # Send the message
                send_result = await self.tool_executor.execute("bash", {
                    "command": (
                        f"curl -s -X POST \"https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage\" "
                        f"-d chat_id={chat_id} "
                        f"--data-urlencode \"text={formatted}\" "
                        f"-d parse_mode=Markdown"
                    )
                })
                if send_result.success:
                    return f"✅ Agenda enviada a {contact_name} por Telegram.\n\n{formatted}"
                else:
                    return (
                        f"⚠️ No pude enviar por Telegram ({send_result.error}), "
                        f"pero acá tenés la agenda para que se la mandes:\n\n{formatted}"
                    )
            else:
                # Can't find chat_id - return text for user to share manually
                return (
                    f"📅 Tu agenda para {contact_name}:\n\n{formatted}\n\n"
                    f"⚠️ No pude enviar directamente porque {contact_name} nunca le escribió al bot. "
                    f"Pedile que le mande /start al bot y después lo intento de nuevo, "
                    f"o copiá y pegá el texto de arriba."
                )

        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
            return f"📅 Agenda para compartir con {contact_name}:\n\n{formatted}"

    async def shutdown(self):
        """Cleanup on shutdown"""
        logger.info("🛑 Shutting down OpenClaw Engine...")

        # Disconnect MCP
        await self.mcp_client.disconnect()

        logger.info("✅ OpenClaw Engine shut down")
