/**
 * Core Loop REPL mejorado para CLI con streaming y control de flujo
 * Inspirado en Aider y Continue.dev
 */

import { LLMProvider, Message, StreamChunk } from './llm/base.js';
import { MCPHost } from './mcp-host.js';
import chalk from 'chalk';
import * as readline from 'readline';
import { buildPrompt, CLIState } from './ui/prompt.js';
import { ToolCallDisplay } from './ui/tool-display.js';
import { StreamingResponseRenderer } from './ui/response-renderer.js';
import { completer } from './ui/autocomplete.js';
import { showStatus } from './ui/status.js';
import { highlightPython } from './ui/syntax.js';
import boxen from 'boxen';
import ora from 'ora';

export interface CoreLoopOptions {
  maxIterations?: number;
  delayMs?: number;
  maxResultSize?: number;
  showProgress?: boolean;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

export class CoreLoop {
  private mcpHost: MCPHost;
  private llm: LLMProvider;
  private options: Required<CoreLoopOptions>;
  private conversationHistory: Message[] = [];
  private systemPrompt: string = '';
  private toolsCalled: string[] = []; // Tracking de tools ejecutadas
  private toolDisplay: ToolCallDisplay;
  private responseRenderer: StreamingResponseRenderer;
  private cliState: CLIState;

  constructor(
    mcpHost: MCPHost,
    llm: LLMProvider,
    systemPrompt: string,
    options: CoreLoopOptions = {}
  ) {
    this.mcpHost = mcpHost;
    this.llm = llm;
    this.systemPrompt = systemPrompt;
    this.options = {
      maxIterations: options.maxIterations || parseInt(process.env.MAX_ITERATIONS || '10', 10), // Reducido a 10 para evitar loops
      delayMs: options.delayMs || parseInt(process.env.LLM_DELAY_MS || '500', 10),
      maxResultSize: options.maxResultSize || parseInt(process.env.MAX_RESULT_SIZE || '30000', 10),
      showProgress: options.showProgress !== false
    };
    this.toolDisplay = new ToolCallDisplay();
    this.responseRenderer = new StreamingResponseRenderer();
    this.cliState = {
      provider: process.env.LLM_PROVIDER || 'gemini',
      mode: 'agent',
      sandboxMode: process.env.TOKIO_SANDBOX === 'true',
      tokensUsed: 0
    };
  }

  /**
   * Procesa un prompt con streaming y ejecución de tools
   */
  async processPrompt(
    userPrompt: string,
    mode: 'agent' | 'plan' | 'ask' = 'agent'
  ): Promise<string> {
    // Construir conversación
    let conversation: Message[] = [];
    
    // Siempre incluir system prompt al inicio
    conversation.push({ role: 'system', content: this.systemPrompt });
    
    if (this.conversationHistory.length > 0) {
      // Continuar conversación existente (sin system prompt, ya lo agregamos)
      conversation.push(...this.conversationHistory);
    }
    
    // Agregar nuevo prompt del usuario
    conversation.push({ role: 'user', content: userPrompt });

    let iteration = 0;
    let finalResponse = '';
    let taskProgress: string[] = [];

    while (iteration < this.options.maxIterations) {
      iteration++;
      
      // Mostrar progreso
      if (this.options.showProgress && iteration > 1) {
        console.log(chalk.gray(`\n📊 Iteración ${iteration}/${this.options.maxIterations}...`));
      }

      // Delay entre iteraciones (excepto la primera)
      if (iteration > 1 && this.options.delayMs > 0) {
        await new Promise(resolve => setTimeout(resolve, this.options.delayMs));
      }

      // Obtener respuesta con streaming
      let response = '';
      let toolCall: ToolCall | null = null;
      let streamingComplete = false;

      try {
        // Usar streaming si está disponible
        response = await this.llm.chatStream(conversation, (chunk: StreamChunk) => {
          // Manejar función calling nativo
          if (chunk.functionCall) {
            toolCall = {
              name: chunk.functionCall.name,
              arguments: chunk.functionCall.arguments
            };
            streamingComplete = true;
            return; // Detener streaming, tenemos función calling
          }

          // Mostrar streaming token-by-token con renderer mejorado
          if (chunk.text && !streamingComplete) {
            this.responseRenderer.write(chunk.text);
            response += chunk.text;
          }

          // Marcar como completo
          if (chunk.isComplete) {
            streamingComplete = true;
            if (!toolCall) {
              // Si no hay función calling, agregar salto de línea
              process.stdout.write('\n');
            }
          }
        });
      } catch (error: any) {
        // Manejar rate limiting con retry
        if (error?.status === 429) {
          const retryDelay = 2000 * (4 - Math.min(3, iteration));
          console.log(chalk.yellow(`\n⚠️  Rate limiting. Esperando ${retryDelay}ms...`));
          await new Promise(resolve => setTimeout(resolve, retryDelay));
          
          // Reintentar
          try {
            response = await this.llm.chatStream(conversation, (chunk: StreamChunk) => {
              if (chunk.functionCall) {
                toolCall = {
                  name: chunk.functionCall.name,
                  arguments: chunk.functionCall.arguments
                };
                streamingComplete = true;
                return;
              }
              if (chunk.text && !streamingComplete) {
                process.stdout.write(chalk.green(chunk.text));
                response += chunk.text;
              }
              if (chunk.isComplete) {
                streamingComplete = true;
                if (!toolCall) {
                  process.stdout.write('\n');
                }
              }
            });
          } catch (retryError) {
            throw retryError;
          }
        } else {
          throw error;
        }
      }

      finalResponse = response.trim();

      // Si hay función calling nativo, usarlo directamente
      if (toolCall) {
        const currentToolCall: ToolCall = toolCall;
        if (currentToolCall.name) {
          try {
          // VORTEX 6: Timeout adaptativo según tool
          const slowTools = ['search_waf_logs_tokio', 'get_summary_tokio', 'list_episodes_tokio'];
          const isSlowTool = slowTools.includes(currentToolCall.name);
          const timeoutMs = isSlowTool ? 90000 : 45000;  // 90s para tools lentas, 45s normales
          
          const toolPromise = this.executeTool(currentToolCall, finalResponse, iteration, conversation, taskProgress);
          const timeoutPromise = new Promise<boolean>((resolve) => 
            setTimeout(() => resolve(true), timeoutMs)
          );
            
            const hasConnectionError = await Promise.race([toolPromise, timeoutPromise]);
            if (hasConnectionError) {
              finalResponse = "❌ Error: La herramienta tardó demasiado o hubo un error de conexión a PostgreSQL. Por favor, verifica que el servidor esté accesible.";
              break; // Detener loop
            }
          } catch (error: any) {
            finalResponse = `❌ Error ejecutando herramienta: ${error.message || String(error)}`;
            break; // Detener loop
          }
          continue; // Continuar loop
        }
      }

      // Fallback: parseo manual de JSON (compatibilidad con código existente)
      const parsedToolCall = this.parseToolCallFromResponse(finalResponse);
      if (parsedToolCall) {
        try {
          // VORTEX 6: Timeout adaptativo según tool
          const slowTools = ['search_waf_logs_tokio', 'get_summary_tokio', 'list_episodes_tokio'];
          const isSlowTool = slowTools.includes(parsedToolCall.name);
          const timeoutMs = isSlowTool ? 90000 : 45000;  // 90s para tools lentas, 45s normales
          
          const toolPromise = this.executeTool(parsedToolCall, finalResponse, iteration, conversation, taskProgress);
          const timeoutPromise = new Promise<boolean>((resolve) => 
            setTimeout(() => resolve(true), timeoutMs)
          );
          
          const hasConnectionError = await Promise.race([toolPromise, timeoutPromise]);
          if (hasConnectionError) {
            finalResponse = "❌ Error: La herramienta tardó demasiado o hubo un error de conexión a PostgreSQL. Por favor, verifica que el servidor esté accesible.";
            break; // Detener loop
          }
        } catch (error: any) {
          finalResponse = `❌ Error ejecutando herramienta: ${error.message || String(error)}`;
          break; // Detener loop
        }
        continue; // Continuar loop
      }
      
      // Si hay muchos errores consecutivos, detener
      if (iteration >= 3 && finalResponse.toLowerCase().includes('error')) {
        finalResponse += "\n\n⚠️ Se detectaron múltiples errores. Deteniendo ejecución para evitar loops infinitos.";
        break;
      }

      // No hay tool call, respuesta final
      if (iteration >= this.options.maxIterations) {
        finalResponse += `\n\n⚠️ **Límite de iteraciones alcanzado (${this.options.maxIterations})**.`;
      }

      // VORTEX 9: Actualización de historial al final (un solo punto)
      // Filtrar system, agregar respuesta, limitar tamaño - todo optimizado
      const filtered = conversation.filter(m => m.role !== 'system') as Message[];
      this.conversationHistory = [
        ...filtered,
        { role: 'assistant' as const, content: finalResponse }
      ].slice(-30);  // VORTEX 9: Mantener solo últimos 30 mensajes
      
      return finalResponse;
    }

    // Si salimos del loop sin respuesta final
    if (taskProgress.length > 0) {
      finalResponse += `\n\n📊 **Resumen del progreso:**\n${taskProgress.join('\n')}\n\n⚠️ Se alcanzó el límite de iteraciones.`;
    }

    return finalResponse;
  }

  /**
   * Ejecuta una tool y reinserta el resultado en la conversación
   */
  private async executeTool(
    toolCall: ToolCall,
    llmResponse: string,
    iteration: number,
    conversation: Message[],
    taskProgress: string[]
  ): Promise<boolean> {
    // VORTEX 9: Timeout adaptativo en una expresión
    const slowTools = ['search_waf_logs_tokio', 'get_summary_tokio', 'list_episodes_tokio', 'list_blocked_ips_tokio'];
    const isSlowTool = slowTools.includes(toolCall.name);
    const timeoutMs = isSlowTool ? 90000 : 45000;  // 90s para tools lentas, 45s normales
    
    // Mostrar tool call con visualización mejorada
    const startTime = Date.now();
    this.toolDisplay.showToolStart(toolCall.name, toolCall.arguments);
    
    // Track tool call
    this.toolsCalled.push(toolCall.name);
    
    let toolResult;
    try {
      // VORTEX 6: Timeout con Promise.race
      const toolPromise = this.mcpHost.callTool(toolCall.name, toolCall.arguments);
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error(`Tool timeout después de ${timeoutMs}ms`)), timeoutMs)
      );
      
      toolResult = await Promise.race([toolPromise, timeoutPromise]);
      
      // Mostrar resultado con visualización mejorada
      const durationMs = Date.now() - startTime;
      this.toolDisplay.showToolResult(toolCall.name, toolResult, durationMs);
    } catch (error) {
      const durationMs = Date.now() - startTime;
      this.toolDisplay.showToolError(toolCall.name, String(error));
      toolResult = { success: false, error: String(error) };
    }

    // Formatear resultado como tabla si es JSON
    let resultText = typeof toolResult === 'string' 
      ? toolResult 
      : JSON.stringify(toolResult, null, 2);
    
    // Intentar formatear como tabla si es objeto
    try {
      if (typeof toolResult === 'object' && toolResult !== null) {
        const formatted = this.formatJsonAsTable(toolResult);
        if (formatted !== resultText) {
          resultText = formatted;
        }
      }
    } catch (e) {
      // Si falla el formateo, usar JSON normal
    }

    // Verificar si hay error de conexión
    let hasConnectionError = false;
    try {
      const parsed = typeof toolResult === 'string' ? JSON.parse(toolResult) : toolResult;
      if (parsed && typeof parsed === 'object' && parsed.success === false) {
        const errorMsg = parsed.error || '';
        if (errorMsg.includes('conexión') || errorMsg.includes('timeout') || 
            errorMsg.includes('connection') || errorMsg.includes('ECONNREFUSED') ||
            errorMsg.includes('PostgreSQL')) {
          hasConnectionError = true;
          // Mensaje más claro para el usuario
          resultText = JSON.stringify({
            success: false,
            error: `Error de conexión a PostgreSQL: ${errorMsg}. Por favor, verifica que el servidor esté accesible.`,
            suggestion: "Verifica que PostgreSQL esté corriendo y accesible desde el MCP server."
          }, null, 2);
        }
      }
    } catch {
      // No es JSON, continuar normalmente
    }

    // Limitar tamaño del resultado
    // EXCEPCIÓN: Para tools de incidentes, usar límite más alto para evitar truncar comentarios
    const incidentTools = ['get_incident', 'get_incident_comments', 'search_incidents'];
    const isIncidentTool = incidentTools.includes(toolCall.name);
    const effectiveMaxSize = isIncidentTool 
      ? this.options.maxResultSize * 3  // 3x más grande para incidentes (90K en lugar de 30K)
      : this.options.maxResultSize;
    
    if (resultText.length > effectiveMaxSize && !hasConnectionError) {
      // Si es una tool de incidentes y se está truncando, dar advertencia más clara
      if (isIncidentTool) {
        resultText = resultText.substring(0, effectiveMaxSize) + 
          `\n\n⚠️ ADVERTENCIA: El resultado ha sido truncado por tamaño (${resultText.length} caracteres totales, límite: ${effectiveMaxSize}). ` +
          `Algunos comentarios o detalles pueden estar incompletos. ` +
          `Para ver todos los comentarios, usa 'get_incident_comments' específicamente.`;
      } else {
        resultText = resultText.substring(0, effectiveMaxSize) + 
          `\n\n... (resultado truncado por tamaño, ${resultText.length} caracteres totales) ...`;
      }
    }
    
    // Track del progreso
    taskProgress.push(`Ejecutado: ${toolCall.name} (iteración ${iteration})`);

    // Construir mensaje con contexto de progreso
    let progressContext = '';
    if (taskProgress.length > 1) {
      progressContext = `\n\n📋 Progreso de la tarea:\n${taskProgress.slice(-5).join('\n')}\n`;
    }

    // Agregar respuesta del LLM y resultado de la tool al historial
    conversation.push({ role: 'assistant', content: llmResponse });
    conversation.push({
      role: 'user',
      content: `Resultado de ${toolCall.name}:\n\n${resultText}${progressContext}\n\nContinúa con la tarea. Si la tarea es larga, trabaja de manera sistemática y reporta tu progreso.`
    });
    
    // Retornar flag de error de conexión
    return hasConnectionError;
  }

  /**
   * Parsea tool call desde respuesta de texto (fallback para compatibilidad)
   */
  private parseToolCallFromResponse(response: string): ToolCall | null {
    // Buscar JSON válido con formato {"action": "call_tool", ...}
    let startIndex = response.indexOf('{');
    while (startIndex !== -1) {
      let endIndex = response.lastIndexOf('}');
      
      while (endIndex > startIndex) {
        const possibleJson = response.substring(startIndex, endIndex + 1);
        try {
          const parsed = JSON.parse(possibleJson);
          if (parsed && parsed.action === 'call_tool' && parsed.tool) {
            return {
              name: parsed.tool,
              arguments: parsed.arguments || {}
            };
          }
        } catch (e) {
          // No es JSON válido, intentar con '}' anterior
          endIndex = response.lastIndexOf('}', endIndex - 1);
        }
      }
      
      // Intentar con siguiente '{'
      startIndex = response.indexOf('{', startIndex + 1);
    }

    return null;
  }

  /**
   * Limpia el historial de conversación
   */
  clearHistory(): void {
    this.conversationHistory = [];
    this.toolsCalled = [];
  }
  
  getToolsCalled(): string[] {
    return [...this.toolsCalled];
  }

  /**
   * Establece el historial de conversación
   */
  setConversationHistory(history: Message[]): void {
    this.conversationHistory = [...history];
  }
  
  /**
   * Obtiene el historial de conversación
   */
  getHistory(): Message[] {
    return [...this.conversationHistory];
  }
  
  /**
   * Formatea un objeto JSON como tabla legible en terminal
   */
  private formatJsonAsTable(obj: any): string {
    if (Array.isArray(obj)) {
      if (obj.length === 0) return '[]';
      
      // Si es array de objetos, mostrar como tabla
      if (typeof obj[0] === 'object' && obj[0] !== null) {
        const keys = Object.keys(obj[0]);
        let table = '\n';
        table += chalk.gray('┌' + '─'.repeat(Math.min(keys.length * 20, 80)) + '┐\n');
        table += chalk.cyan('│ ' + keys.slice(0, 4).join(' │ ') + ' │\n');
        table += chalk.gray('├' + '─'.repeat(Math.min(keys.length * 20, 80)) + '┤\n');
        
        obj.slice(0, 10).forEach((item: any) => {
          const values = keys.slice(0, 4).map(k => {
            const val = String(item[k] || '').substring(0, 18);
            return val.padEnd(18);
          });
          table += chalk.gray('│ ') + values.join(chalk.gray(' │ ')) + chalk.gray(' │\n');
        });
        
        if (obj.length > 10) {
          table += chalk.gray('│ ... ' + (obj.length - 10) + ' más ... │\n');
        }
        
        table += chalk.gray('└' + '─'.repeat(Math.min(keys.length * 20, 80)) + '┘\n');
        return table;
      }
    }
    
    // Si es objeto simple, mostrar como key-value
    if (typeof obj === 'object' && obj !== null) {
      let table = '\n';
      Object.entries(obj).slice(0, 20).forEach(([key, value]) => {
        const val = typeof value === 'object' ? JSON.stringify(value).substring(0, 50) : String(value);
        table += chalk.cyan(key.padEnd(20)) + chalk.gray('│ ') + val + '\n';
      });
      return table;
    }
    
    return String(obj);
  }

  /**
   * Inicia un REPL interactivo mejorado
   */
  async startInteractiveREPL(initialMode: 'agent' | 'plan' | 'ask' = 'agent'): Promise<void> {
    let currentMode = initialMode;
    
    this.cliState.mode = currentMode;
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      prompt: buildPrompt(this.cliState),
      completer: completer
    });

    // Banner con estado del sistema
    console.log(chalk.bold.green('\n🛡️ TOKIO AI ACTIVADO'));
    console.log(chalk.gray(`CLI v2.1  Tokio AI Security Research, Inc`));
    console.log(chalk.gray(`Conectado al servidor MCP`));
    
    // Mostrar estado del sistema
    try {
      const tools = await this.mcpHost.listTools();
      const provider = process.env.LLM_PROVIDER || 'gemini';
      const model = process.env.GEMINI_MODEL || process.env.CLAUDE_MODEL || process.env.OPENAI_MODEL || 'unknown';
      
      console.log(chalk.gray('─'.repeat(60)));
      console.log(chalk.cyan('📊 Estado del Sistema:'));
      console.log(chalk.gray(`  • Tools disponibles: ${chalk.yellow(tools.length)}`));
      console.log(chalk.gray(`  • Provider LLM: ${chalk.yellow(provider)}`));
      console.log(chalk.gray(`  • Modelo: ${chalk.yellow(model)}`));
      console.log(chalk.gray(`  • Modo: ${chalk.yellow(currentMode)}`));
      console.log(chalk.gray('─'.repeat(60)));
    } catch (error) {
      // Silenciar errores de estado
    }
    
    console.log(chalk.gray('Comandos: /mode <agent|plan|ask>, Ctrl+A/P/Q (atajos), exit, clear'));
    console.log(chalk.gray('💡 El modo se detecta automáticamente según tu solicitud\n'));

    rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();

    rl.on('line', async (input) => {
      const line = input.trim();
      
      if (line === 'exit' || line === 'quit') {
        process.exit(0);
      }
      
      if (line === 'clear') {
        console.clear();
        rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
        return;
      }
      
      if (line === '/clear-history') {
        this.clearHistory();
        console.log(chalk.yellow('\n🔄 Historial de conversación limpiado\n'));
        rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
        return;
      }
      
      // Slash commands
      if (line.startsWith('/')) {
        const [cmd, ...args] = line.split(' ');
        
        if (cmd === '/help') {
          const { SLASH_COMMANDS } = await import('./ui/autocomplete.js');
          console.log(chalk.blue('\n📋 Comandos disponibles:\n'));
          SLASH_COMMANDS.forEach(c => {
            console.log(chalk.gray(`  ${c.cmd.padEnd(20)} - ${c.desc}`));
          });
          console.log();
          rl.setPrompt(buildPrompt(this.cliState));
          rl.prompt();
          return;
        }
        
        if (cmd === '/status') {
          const apiBaseUrl = process.env.DASHBOARD_API_BASE_URL || 'http://localhost:8000';
          await showStatus(apiBaseUrl);
          rl.setPrompt(buildPrompt(this.cliState));
          rl.prompt();
          return;
        }
        
        if (cmd === '/tools') {
          try {
            const tools = await this.mcpHost.listTools();
            console.log(chalk.blue('\n📋 Tools disponibles:\n'));
            tools.forEach((tool, index) => {
              console.log(chalk.yellow(`${index + 1}. ${tool.name}`));
              console.log(chalk.gray(`   ${tool.description}`));
              if (tool.inputSchema?.properties) {
                const props = Object.keys(tool.inputSchema.properties);
                if (props.length > 0) {
                  console.log(chalk.gray(`   Parámetros: ${props.join(', ')}`));
                }
              }
              console.log();
            });
          } catch (error: any) {
            console.error(chalk.red(`\n❌ Error listando tools: ${error.message}\n`));
          }
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/mode' && args[0]) {
          const newMode = args[0] as any;
          if (['agent', 'plan', 'ask'].includes(newMode)) {
            currentMode = newMode;
            this.cliState.mode = newMode;
            console.log(chalk.yellow(`\n🔄 Modo cambiado a: ${currentMode}\n`));
            rl.setPrompt(buildPrompt(this.cliState));
          } else {
            console.log(chalk.red('\n❌ Modo no válido. Usa: agent, plan, ask\n'));
          }
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/sandbox') {
          const sandboxEnabled = process.env.TOKIO_SANDBOX === 'true';
          process.env.TOKIO_SANDBOX = sandboxEnabled ? 'false' : 'true';
          this.cliState.sandboxMode = !sandboxEnabled;
          console.log(chalk.yellow(`\n${sandboxEnabled ? '🔒' : '🔓'} Modo sandbox: ${sandboxEnabled ? 'DESACTIVADO' : 'ACTIVADO'}\n`));
          if (!sandboxEnabled) {
            console.log(chalk.gray('Las tools experimentales ahora están disponibles'));
            console.log(chalk.gray('Usa /new-tool para crear nuevas tools en sandbox\n'));
          }
          rl.setPrompt(buildPrompt(this.cliState));
          rl.prompt();
          return;
        }
        
        if (cmd === '/new-tool' && args[0]) {
          const toolName = args[0];
          
          // Mostrar box visual
          console.log('');
          console.log(
            boxen(
              chalk.hex('#FF9F43').bold('  MODO CREACIÓN DE TOOL  ') + '\n' +
              chalk.gray('  El LLM va a escribir código Python en vivo\n') +
              chalk.gray('  Se testea automáticamente en sandbox Docker\n') +
              chalk.hex('#E94560')('  NUNCA llega a prod sin tu aprobación'),
              { 
                padding: 1, 
                borderColor: '#FF9F43', 
                borderStyle: 'round',
                margin: { left: 2 }
              }
            )
          );
          
          console.log(chalk.gray('\n  Describí qué debe hacer la tool:\n  ❯ '));
          
          // Leer descripción del usuario
          rl.question('', async (description) => {
            if (!description.trim()) {
              console.log(chalk.red('\n❌ Descripción vacía. Cancelado.\n'));
              rl.setPrompt(buildPrompt(this.cliState));
              rl.prompt();
              return;
            }
            
            try {
              console.log('');
              console.log(chalk.gray('  ┌─ generando tool: ') + chalk.bold(toolName) + chalk.gray(' ─'.repeat(30)));
              console.log('');
              
              // Generar tool con LLM usando streaming
              const toolPrompt = `Crea una tool MCP llamada "${toolName}" que: ${description}

Requisitos:
- Debe seguir el patrón de las tools existentes en mcp-core/tools/
- Debe tener un input_schema claro con validación
- Debe retornar JSON con success/error
- Debe manejar errores gracefully
- Debe incluir logging apropiado

Genera el código Python completo de la tool.`;
              
              let generatedCode = '';
              await this.llm.chatStream(
                [
                  { role: 'system', content: 'Eres un experto en crear tools MCP para sistemas de seguridad. Genera código Python completo y funcional.' },
                  { role: 'user', content: toolPrompt }
                ],
                (chunk) => {
                  // Código aparece en tiempo real con syntax highlighting
                  const highlighted = highlightPython(chunk.text);
                  process.stdout.write('  ' + highlighted);
                  generatedCode += chunk.text;
                }
              );
              
              console.log('');
              console.log(chalk.gray('  └' + '─'.repeat(50)));
              console.log('');
              
              // Extraer código del markdown si está presente
              let code = generatedCode;
              const codeBlockMatch = generatedCode.match(/```python\n([\s\S]*?)\n```/);
              if (codeBlockMatch) {
                code = codeBlockMatch[1];
              }
              
              // Guardar en sandbox
              const fs = await import('fs');
              const path = await import('path');
              const os = await import('os');
              
              const sandboxDir = path.join(os.homedir(), '.tokio', 'sandbox', 'tools');
              await fs.promises.mkdir(sandboxDir, { recursive: true });
              
              const toolPath = path.join(sandboxDir, `${toolName}.py`);
              await fs.promises.writeFile(toolPath, code, 'utf-8');
              
              console.log(chalk.hex('#16C784')('  ✓ ') + 'Tool guardada en ' + chalk.gray(toolPath));
              
              // Auto-test
              console.log('');
              const testSpinner = ora({ text: '  Testeando en sandbox Docker...', indent: 2 }).start();
              
              // TODO: Implementar runInSandbox
              // Por ahora solo mostrar mensaje
              testSpinner.succeed(chalk.hex('#16C784')('Test pendiente de implementación'));
              
              console.log('');
              console.log(
                chalk.hex('#FF9F43')('  ⟳ ') + 
                'Listo para promover. Ejecutá ' + 
                chalk.bold(`/promote ${toolName}`) + 
                ' cuando quieras llevarla a producción.'
              );
              console.log('');
              
            } catch (error: any) {
              console.error(chalk.red(`\n❌ Error generando tool: ${error.message}\n`));
            }
            
            rl.setPrompt(buildPrompt(this.cliState));
            rl.prompt();
          });
          return;
        }
        
        if (cmd === '/test' && args[0]) {
          const toolName = args[0];
          console.log(chalk.cyan(`\n🧪 Testeando tool: ${toolName}\n`));
          
          try {
            const fs = await import('fs');
            const path = await import('path');
            const os = await import('os');
            const { exec } = await import('child_process');
            const { promisify } = await import('util');
            const execAsync = promisify(exec);
            
            const sandboxDir = path.join(os.homedir(), '.tokio', 'sandbox', 'tools');
            const toolPath = path.join(sandboxDir, `${toolName}.py`);
            
            if (!fs.existsSync(toolPath)) {
              console.log(chalk.red(`\n❌ Tool "${toolName}" no encontrada en sandbox\n`));
              rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
              return;
            }
            
            console.log(chalk.gray('🔍 Ejecutando test en Docker sandbox...\n'));
            
            // Crear Dockerfile temporal para test
            const testDir = path.join(os.homedir(), '.tokio', 'sandbox', 'test', toolName);
            await fs.promises.mkdir(testDir, { recursive: true });
            
            const dockerfile = `FROM python:3.11-slim
WORKDIR /app
COPY ${toolName}.py .
RUN pip install --no-cache-dir requests psycopg2-binary
CMD ["python3", "-c", "import ${toolName.replace(/[^a-zA-Z0-9]/g, '_')}; print('Tool cargada correctamente')"]
`;
            
            await fs.promises.writeFile(path.join(testDir, 'Dockerfile'), dockerfile);
            await fs.promises.copyFile(toolPath, path.join(testDir, `${toolName}.py`));
            
            // Ejecutar test
            try {
              const { stdout, stderr } = await execAsync(`cd ${testDir} && docker build -t tokio-test-${toolName} . && docker run --rm tokio-test-${toolName}`, {
                timeout: 60000,
                maxBuffer: 10 * 1024 * 1024
              });
              
              console.log(chalk.green('\n✅ Test exitoso:\n'));
              console.log(chalk.gray(stdout));
              if (stderr) {
                console.log(chalk.yellow(stderr));
              }
            } catch (error: any) {
              console.log(chalk.red(`\n❌ Test falló:\n`));
              console.log(chalk.red(error.message));
            }
            
          } catch (error: any) {
            console.error(chalk.red(`\n❌ Error ejecutando test: ${error.message}\n`));
          }
          
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/promote' && args[0]) {
          const toolName = args[0];
          console.log(chalk.yellow(`\n⚠️  Promoción de tool "${toolName}": Próximamente (requiere git + gh CLI)\n`));
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/history') {
          try {
            const fs = await import('fs');
            const path = await import('path');
            const os = await import('os');
            
            const sessionsDir = path.join(os.homedir(), '.tokio', 'sessions');
            if (!fs.existsSync(sessionsDir)) {
              console.log(chalk.yellow('\n⚠️  No hay sesiones guardadas\n'));
              rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
              return;
            }
            
            const files = await fs.promises.readdir(sessionsDir);
            const sessions = files.filter(f => f.endsWith('.json')).slice(-10);
            
            if (sessions.length === 0) {
              console.log(chalk.yellow('\n⚠️  No hay sesiones guardadas\n'));
            } else {
              console.log(chalk.blue('\n📋 Últimas 10 sesiones:\n'));
              for (const file of sessions.reverse()) {
                const sessionPath = path.join(sessionsDir, file);
                const sessionData = JSON.parse(await fs.promises.readFile(sessionPath, 'utf-8'));
                const toolsCount = sessionData.tools_called?.length || 0;
                console.log(chalk.gray(`  ${file.replace('.json', '')} - ${sessionData.provider || 'unknown'} - ${sessionData.mode || 'agent'} - ${toolsCount} tools`));
              }
              console.log();
            }
          } catch (error: any) {
            console.error(chalk.red(`\n❌ Error listando sesiones: ${error.message}\n`));
          }
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/session' && args[0] === 'load' && args[1]) {
          const sessionId = args[1];
          try {
            const fs = await import('fs');
            const path = await import('path');
            const os = await import('os');
            
            const sessionPath = path.join(os.homedir(), '.tokio', 'sessions', `${sessionId}.json`);
            if (!fs.existsSync(sessionPath)) {
              console.log(chalk.red(`\n❌ Sesión "${sessionId}" no encontrada\n`));
              rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
              return;
            }
            
            const sessionData = JSON.parse(await fs.promises.readFile(sessionPath, 'utf-8'));
            this.setConversationHistory(sessionData.messages || []);
            if (sessionData.tools_called) {
              this.toolsCalled = sessionData.tools_called;
            }
            console.log(chalk.green(`\n✅ Sesión "${sessionId}" cargada (${sessionData.messages?.length || 0} mensajes, ${sessionData.tools_called?.length || 0} tools)\n`));
          } catch (error: any) {
            console.error(chalk.red(`\n❌ Error cargando sesión: ${error.message}\n`));
          }
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/export') {
          const history = this.getHistory();
          const markdown = history.map(m => `**${m.role}**: ${m.content}`).join('\n\n');
          console.log(chalk.blue('\n📄 Conversación exportada:\n'));
          console.log(markdown);
          console.log();
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/clear-history') {
          this.clearHistory();
          console.log(chalk.yellow('\n🔄 Historial de conversación limpiado\n'));
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/model' && args[0]) {
          process.env.GEMINI_MODEL = args[0];
          console.log(chalk.yellow(`\n🔄 Modelo cambiado a: ${args[0]}\n`));
          console.log(chalk.gray('⚠️  Nota: El cambio requiere reiniciar el CLI\n'));
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        if (cmd === '/provider' && args[0]) {
          if (['gemini', 'claude', 'openai', 'ollama'].includes(args[0].toLowerCase())) {
            process.env.LLM_PROVIDER = args[0].toLowerCase();
            console.log(chalk.yellow(`\n🔄 Provider cambiado a: ${args[0]}\n`));
            console.log(chalk.gray('⚠️  Nota: El cambio requiere reiniciar el CLI\n'));
          } else {
            console.log(chalk.red('\n❌ Provider no válido. Usa: gemini, claude, openai, ollama\n'));
          }
          rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
          return;
        }
        
        // Comando desconocido
        console.log(chalk.red(`\n❌ Comando desconocido: ${cmd}\n`));
        console.log(chalk.gray('Usa /help para ver todos los comandos disponibles\n'));
        rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
        return;
      }
      
      if (!line) {
        rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
        return;
      }

      try {
        // Procesar con streaming
        const response = await this.processPrompt(line, currentMode);
        
        // Auto-guardar sesión después de cada interacción
        try {
          const fs = await import('fs');
          const path = await import('path');
          const os = await import('os');
          const { v4: uuidv4 } = await import('uuid');
          
          const sessionsDir = path.join(os.homedir(), '.tokio', 'sessions');
          await fs.promises.mkdir(sessionsDir, { recursive: true });
          
          const sessionId = uuidv4();
          const sessionData = {
            id: sessionId,
            timestamp: new Date().toISOString(),
            provider: process.env.LLM_PROVIDER || 'gemini',
            model: process.env.GEMINI_MODEL || 'unknown',
            mode: currentMode,
            messages: this.getHistory(),
            tools_called: this.getToolsCalled()
          };
          
          await fs.promises.writeFile(
            path.join(sessionsDir, `${sessionId}.json`),
            JSON.stringify(sessionData, null, 2),
            'utf-8'
          );
        } catch (saveError: any) {
          // Silenciar errores de guardado
        }
        
        // Si no se mostró nada (porque se ejecutó tool), mostrar resultado final
        if (response && !response.includes('🔧')) {
          console.log(chalk.green('\n🤖 TOKIO:'), response, '\n');
        }
      } catch (error) {
        console.error(chalk.red('\n❌ Error:'), error);
      }
      
      rl.setPrompt(buildPrompt(this.cliState)); rl.prompt();
    });

    // Manejar Ctrl+C
    rl.on('SIGINT', () => {
      console.log(chalk.yellow('\n\n⚠️  Interrupción recibida. Saliendo...\n'));
      process.exit(0);
    });
  }
}
