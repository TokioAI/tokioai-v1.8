/**
 * MCP Host - Conecta con servidor MCP y gestiona tools para TOKIO AI
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { LLMProvider, Message } from './llm/base.js';
import { CoreLoop } from './core-loop.js';
import chalk from 'chalk';
import * as readline from 'readline';

export interface Tool {
  name: string;
  description: string;
  inputSchema?: {
    type: string;
    properties?: Record<string, any>;
    required?: string[];
  };
}

export class MCPHost {
  private client: Client | null = null;
  private transport: StdioClientTransport | null = null;
  private config: any;
  private tools: Tool[] = [];

  constructor(config: any) {
    this.config = config;
  }

  /**
   * Conecta al servidor MCP
   */
  async connect(): Promise<void> {
    if (this.client) {
      return; // Ya conectado
    }

    this.transport = new StdioClientTransport({
      command: this.config.mcpServer.command,
      args: this.config.mcpServer.args,
      env: this.config.mcpServer.env
    });

    this.client = new Client(
      {
        name: 'tokio-host',
        version: '1.0.0'
      },
      {
        capabilities: {}
      }
    );

    // Conectar
    await this.client.connect(this.transport);

    // Listar tools disponibles
    const toolsResponse = await this.client.listTools();
    this.tools = toolsResponse.tools.map(tool => ({
      name: tool.name,
      description: tool.description || '',
      inputSchema: tool.inputSchema
    }));
  }

  /**
   * Desconecta del servidor MCP
   */
  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.close();
      this.client = null;
    }
    if (this.transport) {
      this.transport = null;
    }
  }

  /**
   * Lista todas las tools disponibles
   */
  async listTools(): Promise<Tool[]> {
    if (!this.client) {
      throw new Error('No conectado al servidor MCP');
    }
    return this.tools;
  }

  /**
   * Ejecuta una tool con timeout aumentado para queries largas y reconexión automática
   */
  async callTool(toolName: string, arguments_: Record<string, any>): Promise<any> {
    // Si no hay cliente, intentar reconectar
    if (!this.client) {
      console.warn('⚠️  Cliente MCP desconectado, intentando reconectar...');
      try {
        await this.connect();
      } catch (reconnectError) {
        throw new Error(`No conectado al servidor MCP y falló la reconexión: ${reconnectError}`);
      }
    }

    // Tools que pueden tomar más tiempo (queries a tablas grandes, pruebas de vulnerabilidades)
    const slowTools = ['get_cache_stats', 'search_fw_logs', 'search_waf_logs', 'query_data', 'sync_incidents_to_cache', 'test_vulnerability', 'test_vulnerability_with_log_monitoring'];
    const isSlowTool = slowTools.includes(toolName);
    
    // Para tools lentas, usar timeout más largo (120 segundos en lugar de 60)
    // Nota: El SDK de MCP no expone directamente el timeout, pero podemos
    // manejar el error y reintentar si es necesario
    try {
      if (!this.client) {
        throw new Error('No conectado al servidor MCP');
      }
      const result = await this.client.callTool({
        name: toolName,
        arguments: arguments_
      });
      return result.content;
    } catch (error: any) {
      // Si es error de conexión, intentar reconectar una vez
      const errorMsg = String(error?.message || '');
      if (errorMsg.includes('Not connected') || errorMsg.includes('Connection closed')) {
        console.warn('⚠️  Conexión perdida, intentando reconectar...');
        try {
          await this.disconnect();
          await this.connect();
          // Reintentar la llamada después de reconectar
          if (!this.client) {
            throw new Error('No se pudo reconectar al servidor MCP');
          }
          const result = await this.client.callTool({
            name: toolName,
            arguments: arguments_
          });
          return result.content;
        } catch (reconnectError: any) {
          throw new Error(`Error reconectando al servidor MCP: ${String(reconnectError)}`);
        }
      }
      
      // Si es timeout y es una tool lenta, dar mensaje más descriptivo
      if (error.code === -32001 && isSlowTool) {
        throw new Error(`La tool ${toolName} está tomando más tiempo del esperado. Esto puede ocurrir con tablas muy grandes. Intenta con parámetros más restrictivos (menos días, límites más pequeños). Error original: ${errorMsg}`);
      }
      throw error;
    }
  }

  /**
   * Construye el system prompt con las tools disponibles
   */
  private buildSystemPrompt(mode: 'agent' | 'plan' | 'ask'): string {
    // Preparar contexto con tools disponibles
    const toolsContext = this.tools.map(tool => {
      let toolDesc = `**${tool.name}**: ${tool.description}`;
      
      if (tool.inputSchema?.properties) {
        const params = Object.entries(tool.inputSchema.properties)
          .map(([name, schema]: [string, any]) => {
            const desc = schema.description || schema.type || 'any';
            const required = tool.inputSchema?.required?.includes(name) ? ' (requerido)' : '';
            return `    - ${name} (${schema.type || 'any'}): ${desc}${required}`;
          })
          .join('\n');
        toolDesc += `\n  Parámetros:\n${params}`;
      }
      
      return toolDesc;
    }).join('\n\n');

    let modeInstruction = '';
    if (mode === 'ask') {
      modeInstruction = 'MODO ASK: Responde de forma directa y concisa. Solo usa tools si el usuario lo pide explícitamente.';
    } else if (mode === 'plan') {
      modeInstruction = 'MODO PLAN: Antes de ejecutar cualquier herramienta, describe detalladamente los pasos que vas a seguir y espera confirmación (simulada) o simplemente detente tras explicar el plan.';
    } else {
      modeInstruction = 'MODO AGENT: Tienes autonomía total para usar herramientas y completar la tarea de forma exhaustiva. ⚠️ EJECUTA LAS HERRAMIENTAS DIRECTAMENTE usando el formato JSON. NO muestres código Python, NO muestres ejemplos, NO preguntes confirmación - EJECUTA DIRECTAMENTE.';
    }

    const systemPrompt = `Eres TOKIO AI, un sistema avanzado de orquestación de seguridad (SOAR) y análisis de Red Team.
Fecha actual: ${new Date().toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' })}.

${modeInstruction}

Tienes acceso a las siguientes herramientas (tools) del servidor MCP:

${toolsContext}

⚠️⚠️⚠️ REGLA ABSOLUTA - NUNCA VIOLAR ⚠️⚠️⚠️:
- NUNCA digas que "no puedes" hacer algo, que "no tienes acceso", que "es simulado", o que "depende de datos disponibles".
- SIEMPRE revisa la lista de herramientas arriba. Si existe una herramienta para lo que el usuario pide, ÚSALA DIRECTAMENTE.
- ⚠️ HERRAMIENTAS DISPONIBLES EN TOKIO AI:
  * Buscar en logs WAF → USA "search_waf_logs_tokio" (NO uses search_waf_logs)
  * Ver episodios → USA "list_episodes_tokio"
  * Ver bloqueos → USA "list_blocked_ips_tokio"
  * Bloquear IP → USA "block_ip_tokio"
  * Resumen general → USA "get_summary_tokio"
- ⚠️ NO uses herramientas que no están disponibles: get_ip_info, search_incidents, list_incidents, get_incident (estas requieren SOAR API que no está disponible)
- ⚠️ CREACIÓN DE TOOLS/COMANDOS (HUMAN-IN-THE-LOOP):
  * Si el usuario pide "crear tool", "crear herramienta", "crear comando", "proponer tool" o similar:
    - Debes usar "propose_tool_tokio" o "propose_command_tokio".
    - Incluye el código dentro del JSON de la tool (campo "code") sin explicaciones extra.
    - Está PERMITIDO incluir código Python dentro del JSON cuando uses "propose_tool_tokio".
    - Si piden un escaneo (nmap/sqlmap/etc), crea una tool mínima con validación básica y un input_schema claro.
  * Cuando el usuario indique que ya aprobó la tool:
    - Usa "list_automation_approved_tokio" para obtener el id/tool_key.
    - Luego ejecuta la tool con "run_approved_tool_tokio" pasando "tool_id" o "tool_key" y "args".
- Si el usuario pide buscar en logs WAF → USA "search_waf_logs_tokio" DIRECTAMENTE
- Si el usuario pide ver episodios → USA "list_episodes_tokio" DIRECTAMENTE
- Si el usuario pide ver bloqueos → USA "list_blocked_ips_tokio" DIRECTAMENTE
- Si el usuario pide bloquear una IP → USA "block_ip_tokio" DIRECTAMENTE
- Si el usuario pide un resumen → USA "get_summary_tokio" DIRECTAMENTE
- NUNCA expliques que no puedes hacerlo - EJECUTA LA HERRAMIENTA DIRECTAMENTE.

INSTRUCCIONES DE OPERACIÓN:
1. **IDENTIDAD**: Responde como TOKIO AI. Tu objetivo es detectar, analizar y ayudar a mitigar amenazas.

2. **PRECISIÓN Y CUMPLIMIENTO DE SOLICITUDES - REGLA ABSOLUTA**:
   - ⚠️⚠️⚠️ CRÍTICO: Ejecuta SOLO las herramientas que el usuario solicita EXPLÍCITAMENTE. NUNCA ejecutes herramientas adicionales "por si acaso" o "para ser útil".
   - Si el usuario pide "buscar en logs WAF", SOLO ejecuta "search_waf_logs". NO ejecutes "search_incidents", "list_incidents", "check_ip_mitigation" u otras herramientas a menos que el usuario lo pida EXPLÍCITAMENTE.
   - Si el usuario pide "buscar incidentes", solo ejecuta "list_incidents" o "search_incidents". NO ejecutes herramientas adicionales.
   - Si el usuario pide "buscar" o "listar", solo busca/lista. NO analices, NO pruebes, NO valides, NO busques en otras fuentes a menos que se pida explícitamente.
   - Si el usuario pide "analizar" o "revisar", entonces sí puedes usar herramientas adicionales para el análisis.
   - Si el usuario pide "probar" o "validar", entonces sí ejecuta "test_vulnerability" y herramientas relacionadas.
   - ⚠️ CRÍTICO: Si el usuario menciona "Kafka", "logs", "WAF", "Firewall", "tráfico", usa SOLO las herramientas correspondientes (search_waf_logs, search_fw_logs). NO busques en incidentes, NO busques en otras fuentes a menos que se pida explícitamente.
   - ⚠️⚠️⚠️ REGLA ABSOLUTA: NO seas proactivo. NO ejecutes herramientas adicionales "para ayudar" o "para completar el análisis". Ejecuta EXACTAMENTE lo que el usuario pidió, nada más, nada menos.

3. **CORRELACIÓN KAFKA-SOAR** (solo cuando se pida análisis):
   - Cuando el usuario pida ANALIZAR un incidente con una IP atacante, busca esa IP en los logs de Firewall (search_fw_logs) y WAF (search_waf_logs).
   - Usa "check_ip_mitigation" SOLO cuando el usuario pida verificar mitigación o análisis de IPs.
   - IMPORTANTE: La tool "get_incident" ahora incluye automáticamente comentarios, adjuntos, estado detallado y propietario. NO necesitas llamar a "get_incident_comments" por separado.
3. **INFORMACIÓN DE IPs**:
   - Si necesitas información adicional de una IP o hostname (aseguramientos, configuración de seguridad), usa "get_ip_info" de la API de Horus.
   - Si necesitas buscar referencias a una IP en tickets o incidentes, usa "search_ip_in_jira" para buscar en Jira.
   - Si necesitas buscar referencias a una IP en documentación o incidentes, usa "search_ip_in_confluence" para buscar en Confluence.
4. **BÚSQUEDA EN ATLASSIAN/JIRA**:
   - Usa "search_ip_in_jira" para buscar una IP en todos los issues de Jira (summary, description, comments).
   - Usa "search_jira_issues" para buscar issues generales en Jira usando JQL.
5. **BÚSQUEDA EN ATLASSIAN/CONFLUENCE**:
   - Usa "search_ip_in_confluence" para buscar una IP en todas las páginas y contenido de Confluence.
   - Usa "search_content_in_confluence" para buscar contenido general en Confluence.
6. **PRUEBAS DE VULNERABILIDADES Y VALIDACIÓN**:
   - ⚠️ IMPORTANTE: Cuando el usuario pida realizar pruebas, validar vulnerabilidades, o verificar mitigaciones, DEBES usar la herramienta "test_vulnerability".
   - La herramienta "test_vulnerability" puede realizar pruebas REALES de vulnerabilidades SSL/TLS, puertos, servicios, etc.
   - NO digas que no puedes hacer pruebas - TIENES acceso a "test_vulnerability" que puede ejecutar pruebas reales.
   - Si el usuario pide "realiza algunas pruebas" o "valida la mitigación", usa "test_vulnerability" con los parámetros apropiados.
   - Para validar vulnerabilidades SSL/TLS (como BEAST), usa: test_vulnerability(ip="IP_DEL_SERVIDOR", port=443, vulnerability_type="SSL/TLS", test_vpn=False)
   - Si acabas de analizar incidentes, usa las IPs de esos incidentes para las pruebas. Extrae la IP del campo "source_ip" o "dest_ip" de los incidentes.
   - También utiliza las búsquedas en logs (search_fw_logs, search_waf_logs) para ver si hay intentos previos o firmas de WAF disparadas.
   - Si el usuario pregunta sobre incidentes que acabas de analizar, usa la información del contexto de la conversación para extraer IPs y realizar pruebas.
7. **BÚSQUEDA EN LOGS DE WAF (TOKIO AI)**:
   - ⚠️⚠️⚠️ CRÍTICO: Cuando el usuario pida buscar en logs de WAF, SIEMPRE usa "search_waf_logs_tokio" (NO uses search_waf_logs).
   - Esta herramienta busca en los logs de WAF que están persistidos en PostgreSQL.
   - "search_waf_logs_tokio": Busca en logs de WAF (Web Application Firewall) - usa para IPs que acceden a servicios web.
   - ⚠️ NUNCA digas que "no puedes acceder a los logs del WAF" - TIENES esta herramienta disponible y funciona REALMENTE.
   - Si el usuario pide "buscar en logs WAF", "logs de WAF", o menciona una IP para buscar en logs, EJECUTA DIRECTAMENTE "search_waf_logs_tokio" con esa IP.
   - Ejemplo: Usuario dice "busca la IP YOUR_IP_ADDRESS en logs de WAF" → Ejecuta: search_waf_logs_tokio(ip="YOUR_IP_ADDRESS", days=7)
   - ⚠️ IMPORTANTE: Los logs se guardan en PostgreSQL durante 7 DÍAS. El parámetro "days" por defecto es 7 días. SIEMPRE usa days=7 para buscar en todo el rango disponible.
8. **PLAYBOOKS Y SALUD**:
   - Usa "list_playbooks" para ver los playbooks disponibles y "get_playbook" para detalles específicos.
   - Usa "health_check_soar" para verificar la salud del SOAR. Ideal para tests diarios automáticos.

REGLAS DE RESPUESTA - ESTRICTAS (TOKIO AI):
- ⚠️⚠️⚠️ REGLA PRINCIPAL ABSOLUTA: Ejecuta SOLO las herramientas que el usuario solicita EXPLÍCITAMENTE. NUNCA ejecutes herramientas adicionales.
- ⚠️ HERRAMIENTAS DISPONIBLES EN TOKIO AI (USA SOLO ESTAS):
  * "search_waf_logs_tokio" - Buscar en logs WAF
  * "list_episodes_tokio" - Listar episodios
  * "list_blocked_ips_tokio" - Listar IPs bloqueadas
  * "block_ip_tokio" - Bloquear una IP
  * "get_summary_tokio" - Obtener resumen general
- ⚠️ NO USES estas herramientas (NO están disponibles en Tokio AI):
  * get_ip_info (requiere Horus API)
  * search_incidents, list_incidents, get_incident (requieren SOAR API)
  * search_fw_logs (usa search_waf_logs_tokio en su lugar)
- Si el usuario pide "buscar en logs WAF", SOLO ejecuta "search_waf_logs_tokio". NO ejecutes otras herramientas.
- Si el usuario pide "ver episodios", ejecuta "list_episodes_tokio".
- Si el usuario pide "ver bloqueos", ejecuta "list_blocked_ips_tokio".
- Si el usuario pide "bloquear IP", ejecuta "block_ip_tokio".
- Si el usuario pide "resumen", ejecuta "get_summary_tokio".
- ⚠️ CRÍTICO: En MODO AGENT, SIEMPRE ejecuta las herramientas directamente usando el formato JSON. NO muestres código Python, NO muestres ejemplos, NO preguntes confirmación - EJECUTA DIRECTAMENTE.
- EXCEPCIÓN: Cuando uses "propose_tool_tokio", el código Python debe ir dentro del JSON (campo "code").
- ⚠️⚠️⚠️ CRÍTICO ABSOLUTO: NUNCA digas que "no puedes hacer algo", que "no tienes acceso", que "es simulado", o que "depende de datos disponibles". SIEMPRE revisa las herramientas disponibles arriba y ÚSALAS DIRECTAMENTE.
- Si el usuario menciona "logs de WAF" o pide buscar una IP en logs, EJECUTA DIRECTAMENTE "search_waf_logs_tokio" con esa IP.
- Si el usuario dice "no puedo acceder" o algo similar, IGNÓRALO - tú SÍ puedes usando las herramientas disponibles.
- Si necesitas usar una tool, responde SOLO con el JSON de "call_tool" (sin explicaciones adicionales, sin código Python, sin ejemplos):
{
  "action": "call_tool",
  "tool": "nombre_de_la_tool",
  "arguments": { ... }
}
- Si estás en MODO PLAN, NO ejecutes la tool todavía, solo propón el JSON en tu explicación del plan.
- Si estás en MODO ASK, puedes explicar antes de ejecutar.
- Si estás en MODO AGENT, EJECUTA DIRECTAMENTE sin preguntar ni mostrar código.
- Una vez ejecutada la tool, proporciona un análisis detallado en texto normal. NO repitas el JSON.
- Si el usuario pide realizar pruebas o validar algo, entonces SÍ usa las herramientas disponibles (test_vulnerability, search_fw_logs, etc.). NO digas que no puedes hacerlo - TIENES herramientas disponibles.
- Si el usuario pregunta sobre incidentes que acabas de analizar, usa el contexto de la conversación para extraer información (IPs, puertos, etc.) y realizar las pruebas solicitadas.
- ⚠️ NUNCA muestres código Python o ejemplos de código. SIEMPRE usa el formato JSON para ejecutar herramientas.

REGLAS PARA TAREAS LARGAS (MÚLTIPLES ELEMENTOS):
- Si te piden analizar múltiples incidentes, IPs, o hacer una tarea extensa, trabaja de manera SISTEMÁTICA:
  1. Primero lista/obtén TODOS los elementos a analizar (ej: lista de 20 incidentes)
  2. Analiza uno por uno de manera ORDENADA, completando cada análisis antes de pasar al siguiente
  3. Reporta tu progreso periódicamente (ej: "Analizando incidente 1 de 20...", "Completados 5 de 20...")
  4. Si la tarea es muy larga, divide en lotes y reporta qué has completado
  5. SIEMPRE completa el análisis del elemento actual antes de pasar al siguiente
- Si estás cerca del límite de iteraciones, proporciona un RESUMEN claro del progreso y qué falta por hacer
- Si una tarea se interrumpe, proporciona un resumen detallado de qué se completó y qué falta
- NO te detengas a mitad de analizar un elemento - siempre termina el elemento actual

⚠️⚠️⚠️ REGLA CRÍTICA - CIERRE DE INCIDENTES ⚠️⚠️⚠️:
- ⚠️ NUNCA cierres incidentes automáticamente cuando solo se te pide listar, buscar o ver el estado de los incidentes.
- ⚠️ Si el usuario pide "listar incidentes", "buscar incidentes", "ver estado de incidentes", o "mostrar incidentes", SOLO lista/muestra los incidentes. NO los cierres, NO evalúes si deben cerrarse, NO tomes acciones sobre ellos.
- ⚠️ SOLO puedes usar "close_incident" cuando el usuario lo solicite EXPLÍCITAMENTE con frases como:
  * "cierra el incidente X"
  * "cierra estos incidentes"
  * "puedes cerrar el incidente Y"
  * "cierra los incidentes que cumplan condición Z"
- ⚠️ Si el usuario pide "analizar incidentes" o "revisar incidentes", puedes EVALUAR si se pueden cerrar (analizar su estado, verificar si están resueltos, etc.), pero NO los cierres automáticamente. Solo proporciona tu evaluación y recomendación.
- ⚠️ Si evalúas que un incidente puede cerrarse, di algo como: "Este incidente parece estar resuelto y podría cerrarse. ¿Deseas que lo cierre?" o "Recomiendo cerrar este incidente porque [razón]. ¿Procedo con el cierre?"
- ⚠️ REGLA ABSOLUTA: El cierre de incidentes es una acción que requiere autorización explícita del analista. NUNCA cierres incidentes sin que el usuario lo pida directamente.
- ⚠️ Si listas incidentes y algunos están en estado "closed" o "resolved", solo muéstralos como están. NO intentes cerrar otros incidentes relacionados.
`;

    return systemPrompt;
  }

  /**
   * Procesa un prompt usando el LLM y ejecuta tools según sea necesario
   * Ahora usa CoreLoop mejorado con streaming
   */
  async processPrompt(prompt: string, llm: LLMProvider, mode: 'agent' | 'plan' | 'ask' = 'agent', conversationHistory?: Message[]): Promise<string> {
    // Construir system prompt
    const systemPrompt = this.buildSystemPrompt(mode);
    
    // Crear CoreLoop
    const coreLoop = new CoreLoop(this, llm, systemPrompt);
    
    // Restaurar historial si existe
    if (conversationHistory && conversationHistory.length > 0) {
      // Restaurar el historial en el CoreLoop
      coreLoop.setConversationHistory(conversationHistory);
    }
    
    // Procesar con CoreLoop
    const response = await coreLoop.processPrompt(prompt, mode);
    
    // VORTEX 9: Almacenar CoreLoop para acceso al historial actualizado
    (this as any)._lastCoreLoop = coreLoop;
    
    return response;
  }
  
  /**
   * Obtiene el historial actualizado del último CoreLoop
   * VORTEX 9: Acceso al historial sin duplicación
   */
  getLastHistory(): Message[] {
    const coreLoop = (this as any)._lastCoreLoop;
    return coreLoop ? coreLoop.getHistory() : [];
  }

  async startInteractiveChat(llm: LLMProvider, initialMode: 'agent' | 'plan' | 'ask' = 'agent'): Promise<void> {
    // Construir system prompt
    const systemPrompt = this.buildSystemPrompt(initialMode);
    
    // Crear CoreLoop con REPL mejorado
    const coreLoop = new CoreLoop(this, llm, systemPrompt);
    
    // Iniciar REPL interactivo
    await coreLoop.startInteractiveREPL(initialMode);
  }
}
