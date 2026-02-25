#!/usr/bin/env node
/**
 * SOAR MCP Host
 * Host profesional MCP que conecta LLMs con servidores MCP para gestión de incidentes SOAR
 */

import 'dotenv/config';
import { Command } from 'commander';
import chalk from 'chalk';
import ora from 'ora';
import { MCPHost } from './mcp-host.js';
import { createLLMProvider } from './llm/factory.js';
import { loadConfig } from './config.js';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

// Configurar dotenv para buscar en la raíz del proyecto
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
dotenv.config({ path: join(__dirname, '../../.env') });

const program = new Command();

program
  .name('soar-mcp-host')
  .description('MCP Host profesional para SOAR')
  .version('1.0.0');

program
  .command('chat')
  .description('Iniciar sesión de chat interactivo con el analista SOAR')
  .option('-p, --prompt <prompt>', 'Prompt inicial')
  .option('-m, --model <model>', 'Modelo LLM a usar', 'gemini-2.0-flash')
  .option('--mode <mode>', 'Modo inicial (agent, plan, ask)', 'agent')
  .option('--sandbox', 'Modo sandbox aislado: tools experimentales, sin afectar prod')
  .action(async (options) => {
    if (options.sandbox) {
      process.env.TOKIO_SANDBOX = 'true';
      console.log(chalk.yellow('⚠️  MODO SANDBOX — Las tools nuevas NO afectan producción'));
    }
    const spinner = ora('Inicializando MCP Host...').start();
    
    try {
      const config = await loadConfig();
      const mcpHost = new MCPHost(config);
      
      spinner.text = 'Conectando al servidor MCP...';
      await mcpHost.connect();
      
      spinner.text = 'Inicializando LLM...';
      let llm;
      try {
        llm = createLLMProvider();
        spinner.succeed(`LLM inicializado: ${process.env.LLM_PROVIDER || 'gemini'}`);
      } catch (error: any) {
        spinner.warn(`⚠️  LLM no disponible: ${error.message}`);
        // Fallback a Gemini si está disponible
        if (config.geminiApiKey) {
          const { GeminiLLM } = await import('./llm/gemini.js');
          llm = new GeminiLLM(config.geminiApiKey, options.model);
          spinner.succeed('LLM inicializado (fallback a Gemini)');
        } else {
          throw new Error('No hay provider LLM disponible');
        }
      }
      
      spinner.succeed('MCP Host listo');
      
      if (options.prompt) {
        // Modo no interactivo
        console.log(chalk.blue('\n📝 Procesando prompt...\n'));
        console.log(chalk.gray(`Prompt: ${options.prompt}`));
        console.log(chalk.gray(`Modo: ${options.mode}\n`));
        
        try {
          // VORTEX 9: Obtener historial de variable de entorno o flag (máxima compatibilidad)
          let conversationHistory = undefined;
          const historySource = options.history || process.env.MCP_CONVERSATION_HISTORY;
          if (historySource) {
            try {
              conversationHistory = JSON.parse(historySource);
            } catch (e) {
              console.warn(chalk.yellow('⚠️  Error parseando historial, continuando sin historial'));
            }
          }
          
          const response = await mcpHost.processPrompt(options.prompt, llm, options.mode as any, conversationHistory);
          
          // VORTEX 9: Obtener historial actualizado del CoreLoop
          const updatedHistory = mcpHost.getLastHistory();
          
          // VORTEX 9: Un solo objeto JSON con todo (máxima abstracción)
          const result = {
            response: response,
            history: updatedHistory
          };
          
          // VORTEX 6: Salida estructurada para fácil parsing (antes de la respuesta legible)
          console.log(JSON.stringify(result));
          console.log(chalk.green('\n✅ Respuesta:\n'));
          console.log(response);
          console.log();
        } catch (error) {
          console.error(chalk.red('\n❌ Error procesando prompt:'), error);
        } finally {
          await mcpHost.disconnect();
          process.exit(0);
        }
      } else {
        // Modo interactivo - mostrar banner visual
        const { showBanner, getSystemStatus } = await import('./ui/banner.js');
        const apiBaseUrl = process.env.DASHBOARD_API_BASE_URL || 'http://localhost:8000';
        const systemStatus = await getSystemStatus(apiBaseUrl);
        await showBanner(systemStatus);
        
        await mcpHost.startInteractiveChat(llm, options.mode as any);
      }
    } catch (error) {
      spinner.fail('Error inicializando MCP Host');
      console.error(chalk.red('\n❌ Error:'), error);
      process.exit(1);
    }
  });

program
  .command('tools')
  .description('Listar todas las tools disponibles del servidor MCP')
  .action(async () => {
    const spinner = ora('Conectando al servidor MCP...').start();
    
    try {
      const config = await loadConfig();
      const mcpHost = new MCPHost(config);
      await mcpHost.connect();
      
      spinner.succeed('Conectado al servidor MCP');
      
      const tools = await mcpHost.listTools();
      
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
      
      await mcpHost.disconnect();
    } catch (error) {
      spinner.fail('Error conectando al servidor MCP');
      console.error(chalk.red('\n❌ Error:'), error);
      process.exit(1);
    }
  });

program.parse();
