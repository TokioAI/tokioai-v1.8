/**
 * Configuración del MCP Host
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export interface MCPHostConfig {
  mcpServer: {
    command: string;
    args: string[];
    env?: Record<string, string>;
  };
  geminiApiKey: string;
  defaultModel?: string;
}

export async function loadConfig(): Promise<MCPHostConfig> {
  // Cargar desde variables de entorno
  const geminiApiKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_AI_API_KEY || '';
  
  if (!geminiApiKey) {
    console.warn('⚠️  GEMINI_API_KEY o GOOGLE_AI_API_KEY no está configurado');
    console.warn('   Para configurarlo:');
    console.warn('   1. Edita el archivo .env en la raíz del proyecto');
    console.warn('   2. Agrega: GEMINI_API_KEY=tu_clave_aqui');
    console.warn('   3. Obtén tu clave en: https://aistudio.google.com/app/apikey');
  } else {
    console.log('✅ GEMINI_API_KEY configurada correctamente');
  }

  // Configuración del servidor MCP
  const mcpServerCmd = process.env.MCP_SERVER_CMD || 'python3.11';
  const mcpServerPath = process.env.MCP_SERVER_PATH || join(__dirname, '../../mcp-core/mcp_server.py');
  
    // Construir entorno para el proceso hijo
    // IMPORTANTE: Preservar todas las variables de entorno, especialmente PYTHONPATH
    const childEnv: Record<string, string> = {
      ...process.env,
      // Preservar PYTHONPATH si está configurado (importante para root)
      PYTHONPATH: process.env.PYTHONPATH || '',
      PYTHONUSERBASE: process.env.PYTHONUSERBASE || '',
      // Configurar proxy solo si SOAR_USE_PROXY es true
      http_proxy: process.env.SOAR_USE_PROXY === 'true' ? (process.env.http_proxy || 'http://proxyappl.telecom.arg.telecom.com.ar:8080') : '',
      https_proxy: process.env.SOAR_USE_PROXY === 'true' ? (process.env.https_proxy || 'http://proxyappl.telecom.arg.telecom.com.ar:8080') : '',
      SOAR_USE_PROXY: process.env.SOAR_USE_PROXY || 'false',
      SOAR_VERIFY_SSL: process.env.SOAR_VERIFY_SSL || 'false',
      GEMINI_API_KEY: geminiApiKey
    };
    
    // Debug: Log PYTHONPATH si está configurado (siempre mostrar si está configurado para root)
    if (process.env.PYTHONPATH) {
      console.log(`🔧 PYTHONPATH configurado para proceso hijo: ${process.env.PYTHONPATH}`);
    }
    
    const mcpServer = {
    command: mcpServerCmd,
    args: [mcpServerPath],
    env: childEnv
  };

  return {
    mcpServer,
    geminiApiKey,
    defaultModel: process.env.GEMINI_MODEL || 'gemini-2.0-flash'
  };
}
