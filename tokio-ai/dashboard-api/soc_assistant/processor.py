"""
Procesador principal del SOC AI Assistant
Maneja la lógica de procesamiento de consultas y ejecución de herramientas
"""
import os
import json
import re
import logging
from typing import Dict, Any, List, Optional
import google.generativeai as genai

from .tools import SOCAssistantTools
from .conversation import ConversationManager

logger = logging.getLogger(__name__)


class SOCAssistantProcessor:
    """Procesador principal del asistente SOC AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa el procesador
        
        Args:
            api_key: API key de Gemini (opcional, usa env var si no se proporciona)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY', '')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')
        
        self.tools = SOCAssistantTools()
        self.conversation_manager = ConversationManager()
    
    async def process_query(
        self,
        message: str,
        mode: str = "ask",
        conversation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Procesa una consulta del usuario
        
        Args:
            message: Mensaje del usuario
            mode: Modo de operación (ask, agent, plan)
            conversation_id: ID de conversación (opcional)
            context: Contexto adicional (opcional)
        
        Returns:
            Respuesta del asistente con acciones ejecutadas
        """
        # Obtener o crear conversación
        conv_id = self.conversation_manager.get_or_create_conversation(conversation_id)
        
        # Agregar mensaje del usuario
        self.conversation_manager.add_message(conv_id, "user", message)
        
        # Actualizar contexto si se proporciona
        if context:
            self.conversation_manager.update_context(conv_id, context)
        
        # Obtener historial de conversación (aumentar a 15 mensajes para mejor contexto)
        history = self.conversation_manager.get_conversation_history(conv_id, limit=15)
        conv_context = self.conversation_manager.get_context(conv_id)
        
        # Normalizar términos comunes para episodios bloqueados
        # Mapear variaciones comunes a las herramientas correctas
        message_normalized = message.lower()
        
        # Si pregunta por episodios bloqueados, priorizar query_episodes
        if any(term in message_normalized for term in ["episodios bloqueados", "episodios bloqueados automáticamente", "episodios block"]):
            if "query_episodes" not in message:
                message = message + " [Usar herramienta: query_episodes con decision='BLOCK']"
        
        # Si pregunta por IPs bloqueadas, usar query_blocked_ips
        elif any(term in message_normalized for term in ["ips bloqueadas", "ip bloqueada", "bloqueos automáticos"]):
            if "query_blocked_ips" not in message:
                message = message + " [Usar herramienta: query_blocked_ips]"
        
        # Si pregunta por decisiones del agente (más general), puede usar ambas
        elif any(term in message_normalized for term in ["decisiones del agente", "decisiones agente", "agente ia", "agente ai", "decisiones ia", "decisiones ai"]):
            if "query_episodes" not in message and "query_blocked_ips" not in message:
                # Priorizar query_blocked_ips o query_episodes sobre get_agent_decisions
                message = message + " [Usar herramientas: query_blocked_ips Y query_episodes con decision='BLOCK']"
        
        # Construir prompt del sistema
        system_prompt = self._build_system_prompt(mode, conv_context)
        
        # Construir conversación para el LLM
        conversation = self._build_conversation(system_prompt, history, message)
        
        try:
            # Generar respuesta inicial
            response = self.model.generate_content(conversation)
            response_text = response.text
            
            # Parsear respuesta para detectar llamadas a herramientas
            tool_calls = self._extract_tool_calls(response_text)
            
            actions_taken = []
            tool_results = []
            
            # Ejecutar herramientas si es necesario
            if mode == "agent" and tool_calls:
                # Limitar número de herramientas ejecutadas simultáneamente
                max_tools = 5
                tool_calls = tool_calls[:max_tools]
                
                for tool_call in tool_calls:
                    result = await self._execute_tool(tool_call)
                    actions_taken.append({
                        "tool": tool_call["tool"],
                        "parameters": tool_call.get("parameters", {}),
                        "success": result.get("success", False)
                    })
                    # Agregar el nombre de la herramienta al resultado
                    result_with_tool = result.copy() if isinstance(result, dict) else {"success": False, "error": str(result)}
                    result_with_tool["tool"] = tool_call["tool"]
                    tool_results.append(result_with_tool)
                    
                    # Si hay un error crítico, detener ejecución
                    if not result.get("success") and "timeout" in str(result.get("error", "")).lower():
                        break
                
                # Generar respuesta final con resultados
                # Incluir el historial en el prompt final para mantener contexto
                final_prompt = self._build_final_prompt(
                    message,
                    response_text,
                    tool_results,
                    history
                )
                final_response = self.model.generate_content(final_prompt)
                response_text = final_response.text
            
            elif mode == "plan" and tool_calls:
                # En modo plan, solo mostrar qué se haría
                plan_text = self._build_plan_text(tool_calls)
                response_text = f"{response_text}\n\n📋 **Plan de Acción:**\n{plan_text}"
            
            # Agregar respuesta del asistente
            self.conversation_manager.add_message(
                conv_id,
                "assistant",
                response_text,
                metadata={
                    "mode": mode,
                    "actions_taken": actions_taken,
                    "tool_results": tool_results
                }
            )
            
            return {
                "response": response_text,
                "conversation_id": conv_id,
                "mode": mode,
                "actions_taken": actions_taken,
                "tool_results": tool_results
            }
        
        except Exception as e:
            logger.error(f"Error procesando query: {e}", exc_info=True)
            error_message = f"❌ Error procesando la consulta: {str(e)}"
            
            # Si es un timeout, mensaje más específico
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                error_message = "⏱️ La consulta tardó demasiado tiempo. Intenta con una consulta más específica o reduce el rango de datos solicitados."
            
            self.conversation_manager.add_message(conv_id, "assistant", error_message)
            return {
                "response": error_message,
                "conversation_id": conv_id,
                "mode": mode,
                "error": str(e)
            }
    
    def _build_system_prompt(self, mode: str, context: Dict[str, Any]) -> str:
        """Construye el prompt del sistema"""
        tools_info = self._format_tools_info()
        
        mode_descriptions = {
            "ask": "Solo responde preguntas. NO ejecutes acciones. Si necesitas datos, indica qué herramienta usarías pero NO la ejecutes.",
            "agent": "Puedes ejecutar acciones automáticamente cuando sea necesario. Usa las herramientas disponibles para obtener datos o ejecutar acciones.",
            "plan": "Crea un plan de acción detallado pero NO lo ejecutes. Indica qué herramientas usarías y en qué orden."
        }
        
        return f"""Eres el SOC AI Assistant, un asistente experto en seguridad con acceso completo al sistema SOC.

MODO ACTUAL: {mode.upper()}
{mode_descriptions.get(mode, mode_descriptions["ask"])}

HERRAMIENTAS DISPONIBLES:
{tools_info}

CONTEXTO DEL SISTEMA:
- WAF: ModSecurity con OWASP CRS
- Base de datos: PostgreSQL
- Red Team: Intelligent Red Team Agent con IA
- Tenants: Sistema multi-tenant
- Detecciones Avanzadas: El sistema ahora incluye detección inteligente de:
  * Zero-Day: Detecta ataques desconocidos/anómalos comparando con baseline estadístico
  * Ofuscación: Detecta URIs ofuscadas usando entropía de Shannon y patrones de encoding
  * DDoS: Detecta ataques distribuidos coordinados entre múltiples IPs
  Estos datos están en el campo 'intelligence_analysis' de los episodios cuando están disponibles.

INSTRUCCIONES CRÍTICAS:
1. Responde de forma clara, profesional y en español
2. ⚠️ MANTÉN EL CONTEXTO - MUY IMPORTANTE:
   - SIEMPRE lee el historial completo de la conversación antes de responder
   - Si el usuario hace una pregunta de seguimiento (ej: "revisa los últimos 10", "ejecuta ahora", "hazlo"), 
     DEBES entender que se refiere al tema de la conversación anterior
   - Si en mensajes anteriores se mencionó una acción específica (ej: "ejecutar campaña SQLI"), 
     y el usuario dice "ejecuta ahora" o "hazlo", DEBES ejecutar esa acción mencionada anteriormente
   - Si hablaban de "ataques SQLi", "los últimos 10" significa "los últimos 10 ataques SQLi"
   - Si hablaban de "campañas", "los últimos 10" significa "las últimas 10 campañas"
   - Si el usuario cambió de modo (ej: de ASK a AGENT) y dice "ejecuta ahora", se refiere a la última acción 
     que mencionaste o que el usuario pidió
   - NUNCA ignores el contexto anterior, siempre úsalo para interpretar la intención del usuario
3. Si el usuario pregunta sobre datos específicos, usa las herramientas para obtenerlos
4. Para ejecutar una herramienta, usa el formato: TOOL:nombre_herramienta(parámetros_json)
5. Ejemplos:
   - TOOL:get_redteam_campaign_details({{"campaign_id": "campaign_20251201_195227"}})
   - TOOL:get_waf_stats({{"tenant_id": "default"}})
   - TOOL:get_attack_logs({{"limit": 10, "tenant_id": "default"}})
   - TOOL:run_redteam_campaign({{"attack_types": ["SQLI", "XSS"]}})
6. Si no estás seguro del contexto, puedes hacer una pregunta de clarificación, pero primero 
   intenta inferir del historial de la conversación
7. Formatea las respuestas de forma clara y estructurada

CONTEXTO ACTUAL:
{json.dumps(context, indent=2) if context else "Ninguno"}
"""
    
    def _format_tools_info(self) -> str:
        """Formatea la información de herramientas para el prompt"""
        tools_map = self.tools.get_available_tools()
        info_lines = []
        
        # Priorizar herramientas de episodios al inicio
        episode_tools = ["query_episodes", "query_blocked_ips", "get_episode_stats", "get_blocking_effectiveness"]
        other_tools = [name for name in tools_map.keys() if name not in episode_tools]
        
        # Agregar herramientas de episodios primero
        info_lines.append("="*60)
        info_lines.append("🎯 HERRAMIENTAS DE EPISODIOS (RECOMENDADAS para bloqueos automáticos)")
        info_lines.append("="*60)
        for tool_name in episode_tools:
            if tool_name in tools_map:
                tool_info = tools_map[tool_name]
                params = ", ".join(tool_info.get("parameters", []))
                info_lines.append(f"- {tool_name}: {tool_info['description']}")
                if params:
                    info_lines.append(f"  Parámetros: {params}")
        
        info_lines.append("")
        info_lines.append("="*60)
        info_lines.append("📋 OTRAS HERRAMIENTAS")
        info_lines.append("="*60)
        for tool_name in other_tools:
            tool_info = tools_map[tool_name]
            params = ", ".join(tool_info.get("parameters", []))
            info_lines.append(f"- {tool_name}: {tool_info['description']}")
            if params:
                info_lines.append(f"  Parámetros: {params}")
        
        info_lines.append("")
        info_lines.append("⚠️ NOTA IMPORTANTE:")
        info_lines.append("  - Para consultar episodios bloqueados: usa 'query_episodes' con decision='BLOCK'")
        info_lines.append("  - Para ver IPs bloqueadas: usa 'query_blocked_ips'")
        info_lines.append("  - 'get_agent_decisions' también incluye episodios bloqueados pero puede estar incompleto")
        info_lines.append("")
        info_lines.append("🧠 DETECCIONES AVANZADAS:")
        info_lines.append("  - Los episodios pueden incluir 'intelligence_analysis' con:")
        info_lines.append("    * zero_day_risk: Indica posible ataque zero-day (alto riesgo)")
        info_lines.append("    * obfuscation_detected: Indica que las URIs están ofuscadas")
        info_lines.append("    * ddos_risk: Indica posible ataque DDoS distribuido")
        info_lines.append("    * enhanced_risk_score: Score de riesgo mejorado con detecciones avanzadas")
        info_lines.append("  - Cuando veas episodios, menciona estas detecciones si están presentes")
        
        return "\n".join(info_lines)
    
    def _build_conversation(
        self,
        system_prompt: str,
        history: List[Dict[str, Any]],
        current_message: str
    ) -> str:
        """Construye la conversación para el LLM"""
        parts = [system_prompt]
        
        # Agregar resumen del contexto si hay historial
        if len(history) > 0:
            parts.append("\n" + "="*60)
            parts.append("⚠️ HISTORIAL DE LA CONVERSACIÓN - LEE ESTO PRIMERO ⚠️")
            parts.append("="*60)
            parts.append("IMPORTANTE: El usuario puede hacer referencias a mensajes anteriores.")
            parts.append("Si dice 'ejecuta ahora', 'hazlo', 'revisa los últimos X', etc.,")
            parts.append("DEBES buscar en el historial qué acción o tema mencionó anteriormente.")
            parts.append("")
            parts.append("CONTEXTO RECIENTE:")
            
            # Extraer acciones/temas mencionados en los últimos mensajes
            recent_topics = []
            for msg in history[-5:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user" and content:
                    # Buscar menciones de acciones o herramientas
                    if "ejecutar" in content.lower() or "run" in content.lower():
                        recent_topics.append(f"Usuario pidió ejecutar algo relacionado con: {content[:150]}")
                    if "campaña" in content.lower() or "campaign" in content.lower():
                        recent_topics.append(f"Usuario mencionó campaña: {content[:150]}")
                    if "ataque" in content.lower() or "attack" in content.lower():
                        recent_topics.append(f"Usuario mencionó ataque: {content[:150]}")
                elif role == "assistant" and content:
                    # Buscar herramientas mencionadas
                    if "TOOL:" in content or "herramienta" in content.lower():
                        recent_topics.append(f"Asistente mencionó usar herramienta: {content[:150]}")
            
            if recent_topics:
                for topic in recent_topics[-3:]:  # Últimos 3 temas
                    parts.append(f"  - {topic}")
            
            parts.append("")
            parts.append("HISTORIAL COMPLETO:")
            parts.append("-"*60)
        
        # Agregar historial completo (últimos 10 mensajes para mejor contexto)
        for i, msg in enumerate(history[-10:], 1):  # Aumentado a 10 mensajes
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                parts.append(f"\n[{i}] 👤 Usuario: {content}")
            elif role == "assistant":
                parts.append(f"\n[{i}] 🤖 Asistente: {content[:300]}...")  # Truncar respuestas largas
        
        parts.append("\n" + "="*60)
        parts.append("MENSAJE ACTUAL DEL USUARIO:")
        parts.append("="*60)
        # Agregar mensaje actual
        parts.append(f"\n👤 Usuario: {current_message}")
        parts.append("\n🤖 Asistente (responde considerando TODO el historial anterior):")
        
        return "\n".join(parts)
    
    def _extract_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """Extrae llamadas a herramientas del texto"""
        tool_calls = []
        
        # Buscar patrones TOOL:nombre(params)
        pattern = r'TOOL:(\w+)\(([^)]*)\)'
        matches = re.finditer(pattern, text)
        
        for match in matches:
            tool_name = match.group(1)
            params_str = match.group(2).strip()
            
            # Parsear parámetros JSON
            try:
                if params_str:
                    params = json.loads(params_str)
                else:
                    params = {}
            except json.JSONDecodeError:
                # Si no es JSON válido, intentar parsear como string simple
                params = {"value": params_str}
            
            tool_calls.append({
                "tool": tool_name,
                "parameters": params
            })
        
        return tool_calls
    
    async def _execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta una herramienta"""
        tool_name = tool_call["tool"]
        parameters = tool_call.get("parameters", {})
        
        # Verificar si la herramienta existe
        tools_map = self.tools.get_available_tools()
        if tool_name not in tools_map:
            return {
                "success": False,
                "error": f"Herramienta '{tool_name}' no encontrada"
            }
        
        # Obtener método de la herramienta
        tool_method = getattr(self.tools, tool_name, None)
        if not tool_method:
            return {
                "success": False,
                "error": f"Método '{tool_name}' no implementado"
            }
        
        try:
            # Ejecutar herramienta con timeout adaptativo
            if callable(tool_method):
                import asyncio
                # Timeout adaptativo según la herramienta
                timeout_map = {
                    "run_redteam_campaign": 60.0,  # Campañas pueden tardar más
                    "apply_suggestions": 60.0,     # Aplicar sugerencias puede tardar
                    "analyze_waf": 45.0,           # Análisis puede ser complejo
                }
                timeout = timeout_map.get(tool_name, 30.0)
                
                try:
                    result = await asyncio.wait_for(tool_method(**parameters), timeout=timeout)
                    
                    # Validar que el resultado tenga la estructura esperada
                    if not isinstance(result, dict):
                        result = {"success": False, "error": "Resultado inválido de la herramienta"}
                    
                    return result
                except asyncio.TimeoutError:
                    logger.error(f"Timeout ejecutando herramienta {tool_name} (>{timeout}s)")
                    return {
                        "success": False,
                        "error": f"Timeout ejecutando {tool_name} (más de {int(timeout)} segundos). La operación puede estar procesando muchos datos."
                    }
            else:
                return {
                    "success": False,
                    "error": f"'{tool_name}' no es ejecutable"
                }
        except Exception as e:
            logger.error(f"Error ejecutando herramienta {tool_name}: {e}", exc_info=True)
            
            # Mensajes de error más amigables
            error_msg = str(e)
            if "connection" in error_msg.lower() or "connect" in error_msg.lower():
                error_msg = "Error de conexión a la base de datos. Verifica que el servicio esté disponible."
            elif "syntax" in error_msg.lower() or "sql" in error_msg.lower():
                error_msg = "Error en la consulta a la base de datos."
            
            return {
                "success": False,
                "error": error_msg
            }
    
    def _build_final_prompt(
        self,
        original_message: str,
        initial_response: str,
        tool_results: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Construye el prompt final con resultados de herramientas"""
        # Generar resúmenes inteligentes de los resultados
        summarized_results = []
        for r in tool_results:
            tool_name = r.get('tool', 'unknown')
            result_data = r.get('data', {})
            
            # Resumir resultados grandes
            summary = self._summarize_tool_result(tool_name, result_data)
            summarized_results.append({
                "tool": tool_name,
                "summary": summary,
                "full_data_available": True
            })
        
        # Construir texto de resultados con información completa
        results_text_parts = []
        for r in summarized_results:
            tool_name = r['tool']
            summary = r['summary']
            
            # Buscar el resultado completo original
            original_result = next((tr for tr in tool_results if tr.get('tool') == tool_name), None)
            
            results_text_parts.append(f"Herramienta: {tool_name}")
            results_text_parts.append(f"Resumen: {json.dumps(summary, indent=2, ensure_ascii=False)}")
            
            # Incluir información adicional del resultado original si es relevante
            if original_result:
                # Para run_redteam_campaign, los datos pueden estar en 'data' o directamente
                result_data = original_result.get('data', {}) if original_result.get('data') else original_result
                
                if original_result.get('success'):
                    # Mensaje principal
                    message = original_result.get('message') or result_data.get('message', '')
                    if message:
                        results_text_parts.append(f"Mensaje: {message}")
                    
                    # Campaign ID si está disponible
                    campaign_id = original_result.get('campaign_id') or result_data.get('campaign_id')
                    if campaign_id:
                        results_text_parts.append(f"ID de Campaña: {campaign_id}")
                    
                    # Status
                    status = result_data.get('status', '')
                    if status:
                        results_text_parts.append(f"Estado: {status}")
                elif not original_result.get('success'):
                    error_msg = original_result.get('error', 'Error desconocido')
                    results_text_parts.append(f"Error: {error_msg}")
            
            results_text_parts.append("")  # Línea en blanco entre resultados
        
        results_text = "\n".join(results_text_parts)
        
        # Construir contexto del historial si está disponible
        context_note = ""
        if history and len(history) > 0:
            recent_context = []
            for msg in history[-3:]:  # Últimos 3 mensajes para contexto
                role = msg.get("role", "")
                content = msg.get("content", "")[:200]  # Limitar longitud
                if role == "user":
                    recent_context.append(f"Usuario preguntó: {content}")
                elif role == "assistant":
                    recent_context.append(f"Asistente respondió: {content[:200]}")
            
            if recent_context:
                context_note = f"\n\nCONTEXTO RECIENTE DE LA CONVERSACIÓN:\n" + "\n".join(recent_context) + "\n"
        
        return f"""El usuario preguntó: {original_message}
{context_note}
Tu respuesta inicial fue: {initial_response}

Se ejecutaron las siguientes herramientas y obtuvieron estos resultados:

{results_text}

INSTRUCCIONES PARA LA RESPUESTA:
1. Responde en español, de forma profesional y estructurada
2. MANTÉN EL CONTEXTO: Si la pregunta del usuario es parte de una conversación continua, 
   asegúrate de que tu respuesta tenga sentido en ese contexto
3. INTERPRETA LOS RESULTADOS CORRECTAMENTE:
   - Si la herramienta es "run_redteam_campaign" y tiene "success: true" y "campaign_id", 
     significa que la campaña se ejecutó correctamente y tiene ese ID
   - Si tiene "message", ese es el mensaje principal del resultado
   - NO interpretes campos como "keys" o "has_more" a menos que sean explícitamente parte del resultado
   - Usa el campo "message" y "campaign_id" cuando estén disponibles
4. Si hay datos numéricos, preséntalos en formato de tabla o lista clara
5. Si hay muchos elementos (más de 10), muestra un resumen con los más importantes
6. Usa emojis apropiados para hacer la respuesta más visual (📊 para estadísticas, ⚠️ para alertas, ✅ para éxitos, etc.)
7. Si hay tablas de datos, formátalas claramente con encabezados
8. Destaca los puntos más importantes o críticos
9. Si hay errores, explícalos de forma clara y sugiere soluciones
10. Para campañas de Red Team: Si se ejecutó correctamente, menciona el campaign_id y explica que los resultados 
    estarán disponibles en unos momentos o que puede consultar los detalles con get_redteam_campaign_details

Genera una respuesta final clara y completa basándote en los resultados obtenidos y el contexto de la conversación."""
    
    def _build_plan_text(self, tool_calls: List[Dict[str, Any]]) -> str:
        """Construye texto de plan de acción"""
        plan_lines = []
        for i, tool_call in enumerate(tool_calls, 1):
            tool_name = tool_call["tool"]
            params = tool_call.get("parameters", {})
            plan_lines.append(f"{i}. Ejecutar {tool_name} con parámetros: {json.dumps(params, ensure_ascii=False)}")
        
        return "\n".join(plan_lines)
    
    def _summarize_tool_result(self, tool_name: str, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Genera un resumen inteligente de los resultados de una herramienta"""
        summary = {}
        
        if tool_name == "get_waf_stats":
            summary = {
                "total_requests": result_data.get("total_requests", 0),
                "blocked": result_data.get("blocked", 0),
                "allowed": result_data.get("allowed", 0),
                "unique_ips": result_data.get("unique_ips", 0),
                "top_threats": dict(list(result_data.get("by_threat_type", {}).items())[:5])
            }
        elif tool_name == "get_attack_logs":
            items = result_data.get("items", [])
            summary = {
                "total": result_data.get("count", 0),
                "sample_count": min(10, len(items)),
                "by_threat_type": {},
                "recent_attacks": items[:5] if items else []
            }
            # Agrupar por tipo de amenaza
            for item in items:
                threat = item.get("threat_type", "UNKNOWN")
                summary["by_threat_type"][threat] = summary["by_threat_type"].get(threat, 0) + 1
        elif tool_name == "get_incidents":
            items = result_data.get("items", [])
            summary = {
                "total": result_data.get("count", 0),
                "by_severity": {},
                "by_status": {},
                "recent_incidents": items[:5] if items else []
            }
            for item in items:
                severity = item.get("severity", "unknown")
                status = item.get("status", "unknown")
                summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1
                summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        elif tool_name == "get_redteam_campaigns":
            campaigns = result_data.get("campaigns", [])
            summary = {
                "total_campaigns": result_data.get("count", 0),
                "recent_campaigns": campaigns[:5] if campaigns else [],
                "avg_success_rate": sum(c.get("success_rate", 0) for c in campaigns) / len(campaigns) if campaigns else 0
            }
        elif tool_name == "get_bypasses":
            items = result_data.get("items", [])
            summary = {
                "total": result_data.get("count", 0),
                "mitigated": sum(1 for item in items if item.get("mitigated", False)),
                "by_attack_type": {},
                "recent_bypasses": items[:5] if items else []
            }
            for item in items:
                attack_type = item.get("attack_type", "UNKNOWN")
                summary["by_attack_type"][attack_type] = summary["by_attack_type"].get(attack_type, 0) + 1
        elif tool_name == "get_mitigations":
            items = result_data.get("items", [])
            summary = {
                "total": result_data.get("count", 0),
                "enabled": sum(1 for item in items if item.get("enabled", False)),
                "recent_mitigations": items[:5] if items else []
            }
        elif tool_name == "run_redteam_campaign":
            # Resultado específico para ejecución de campaña
            # result_data puede venir directamente o dentro de un campo 'data'
            actual_data = result_data.get("data", result_data) if isinstance(result_data, dict) else {}
            summary = {
                "success": result_data.get("success", actual_data.get("success", False)),
                "message": result_data.get("message", actual_data.get("message", "")),
                "campaign_id": result_data.get("campaign_id") or actual_data.get("campaign_id"),
                "status": result_data.get("status", actual_data.get("status", "unknown"))
            }
            # Si no hay status, inferirlo del success
            if summary["status"] == "unknown":
                summary["status"] = "Campaña ejecutada correctamente" if summary["success"] else "Error al ejecutar campaña"
        elif tool_name == "apply_suggestions":
            # Resultado específico para aplicar sugerencias
            summary = {
                "success": result_data.get("success", False),
                "message": result_data.get("message", ""),
                "suggestions_applied": result_data.get("suggestions_applied", 0) if isinstance(result_data, dict) else 0
            }
        elif tool_name == "analyze_waf":
            # Resultado específico para análisis de WAF
            if isinstance(result_data, dict):
                summary = {
                    "total_rules": result_data.get("total_rules", 0),
                    "protected_types": result_data.get("protected_types", []),
                    "coverage": result_data.get("coverage", 0),
                    "complexity": result_data.get("complexity", "unknown")
                }
            else:
                summary = {"analysis": "Análisis completado"}
        elif tool_name == "get_blocked_ips":
            blocked_ips = result_data.get("blocked_ips", [])
            summary = {
                "total": result_data.get("count", 0),
                "recent_blocked": blocked_ips[:10] if blocked_ips else [],
                "by_threat_type": {}
            }
            for ip_data in blocked_ips:
                threat_type = ip_data.get("threat_type", "UNKNOWN")
                summary["by_threat_type"][threat_type] = summary["by_threat_type"].get(threat_type, 0) + 1
        elif tool_name == "block_ip":
            summary = {
                "success": result_data.get("success", False),
                "ip": result_data.get("ip"),
                "message": result_data.get("message", ""),
                "duration": result_data.get("duration", "")
            }
        elif tool_name == "unblock_ip":
            summary = {
                "success": result_data.get("success", False),
                "ip": result_data.get("ip"),
                "message": result_data.get("message", "")
            }
        elif tool_name == "get_attack_statistics":
            if isinstance(result_data, dict):
                summary = {
                    "general": result_data.get("general", {}),
                    "top_threats": result_data.get("by_threat_type", [])[:10],
                    "top_owasp": result_data.get("by_owasp", [])[:10],
                    "top_ips": result_data.get("top_attacking_ips", [])[:10],
                    "classification_sources": result_data.get("by_classification_source", {})
                }
            else:
                summary = {"statistics": "Estadísticas obtenidas"}
        elif tool_name == "get_agent_decisions":
            decisions = result_data.get("decisions", [])
            summary = {
                "total": result_data.get("count", 0),
                "recent_decisions": decisions[:10] if decisions else [],
                "by_threat_type": {},
                "by_severity": {}
            }
            for decision in decisions:
                threat_type = decision.get("threat_type", "UNKNOWN")
                severity = decision.get("severity", "unknown")
                summary["by_threat_type"][threat_type] = summary["by_threat_type"].get(threat_type, 0) + 1
                summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1
        elif tool_name == "query_episodes":
            episodes = result_data.get("episodes", [])
            summary = {
                "total": result_data.get("count", 0),
                "by_decision": {},
                "by_threat_type": {},
                "recent_episodes": episodes[:10] if episodes else []
            }
            for episode in episodes:
                decision = episode.get("decision", "UNKNOWN")
                summary["by_decision"][decision] = summary["by_decision"].get(decision, 0) + 1
                # Extraer threat_types de presence_flags o muestras
                if episode.get("presence_flags"):
                    flags = episode.get("presence_flags", {})
                    if flags.get("wp-") or flags.get(".git"):
                        summary["by_threat_type"]["SCAN_PROBE"] = summary["by_threat_type"].get("SCAN_PROBE", 0) + 1
        elif tool_name == "query_blocked_ips":
            blocked_ips = result_data.get("blocked_ips", [])
            summary = {
                "total": result_data.get("count", 0),
                "active_count": result_data.get("active_count", 0),
                "by_threat_type": {},
                "by_classification_source": {},
                "recent_blocks": blocked_ips[:10] if blocked_ips else []
            }
            for blocked_ip in blocked_ips:
                threat_type = blocked_ip.get("threat_type", "UNKNOWN")
                source = blocked_ip.get("classification_source", "unknown")
                summary["by_threat_type"][threat_type] = summary["by_threat_type"].get(threat_type, 0) + 1
                summary["by_classification_source"][source] = summary["by_classification_source"].get(source, 0) + 1
        elif tool_name == "get_episode_stats":
            summary = {
                "total_episodes": result_data.get("total_episodes", 0),
                "blocked_episodes": result_data.get("blocked_episodes", 0),
                "allowed_episodes": result_data.get("allowed_episodes", 0),
                "uncertain_episodes": result_data.get("uncertain_episodes", 0),
                "avg_risk_score": round(result_data.get("avg_risk_score", 0), 2) if result_data.get("avg_risk_score") else 0,
                "unique_ips": result_data.get("unique_ips", 0)
            }
        elif tool_name == "get_blocking_effectiveness":
            summary = {
                "total_blocked": result_data.get("total_blocked", 0),
                "re_attack_count": result_data.get("re_attack_count", 0),
                "effectiveness_percent": result_data.get("effectiveness_percent", 100)
            }
        else:
            # Para otras herramientas, devolver un resumen más útil
            if isinstance(result_data, dict):
                # Incluir campos importantes directamente
                important_keys = ["success", "message", "campaign_id", "count", "total", "error"]
                summary = {k: result_data.get(k) for k in important_keys if k in result_data}
                # Si no hay campos importantes, mostrar estructura básica
                if not summary:
                    summary = {
                        "structure": f"Objeto con {len(result_data)} campos",
                        "main_fields": list(result_data.keys())[:5]
                    }
            else:
                summary = {"result": str(result_data)[:200]}
        
        return summary
    
    def close(self):
        """Cierra recursos"""
        self.tools.close()

