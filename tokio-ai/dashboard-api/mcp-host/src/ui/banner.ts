import gradient from 'gradient-string';
import chalk from 'chalk';
import { theme } from './theme.js';

export interface SystemStatus {
  overall: 'healthy' | 'degraded' | 'unhealthy';
  tenants: {
    active: number;
    total: number;
  };
  blocks: {
    active: number;
    expired_today: number;
  };
  kafka: 'healthy' | 'unhealthy' | 'unknown';
  database: 'healthy' | 'unhealthy' | 'unknown';
  nginx: 'healthy' | 'unhealthy' | 'unknown';
  realtime_processor: 'healthy' | 'unhealthy' | 'unknown';
  mcp_server: 'healthy' | 'unhealthy' | 'unknown';
}

export async function showBanner(systemStatus: SystemStatus) {
  console.clear();
  
  // ASCII art con gradient rojo→azul (colores tokio)
  const logo = `
 ████████╗ ██████╗ ██╗  ██╗██╗ ██████╗      █████╗ ██╗
    ██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗    ██╔══██╗██║
    ██║   ██║   ██║█████╔╝ ██║██║   ██║    ███████║██║
    ██║   ██║   ██║██╔═██╗ ██║██║   ██║    ██╔══██║██║
    ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝    ██║  ██║██║
    ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝     ╚═╝  ╚═╝╚═╝
  `;
  
  // Gradient de rojo a azul profundo
  console.log(gradient(['#E94560', '#0F3460', '#1A1A2E'])(logo));
  
  // Línea de versión y build
  console.log(
    chalk.gray('  WAF-as-a-Service · AI Security Platform · ') +
    chalk.hex(theme.primary).bold('v2.0') +
    chalk.gray(' · ') +
    chalk.hex(theme.success)(systemStatus.overall === 'healthy' ? '● ONLINE' : '● DEGRADED')
  );
  
  console.log('');
  
  // Status grid compacto
  const statusItems = [
    { label: 'Tenants',   value: String(systemStatus.tenants.active),        color: theme.accent },
    { label: 'Bloqueadas', value: String(systemStatus.blocks.active) + ' IPs', color: theme.primary },
    { label: 'Pipeline',  value: systemStatus.kafka === 'healthy' ? 'OK' : 'ERR', color: theme.success },
    { label: 'Modelo',    value: process.env.LLM_PROVIDER || 'gemini',        color: theme.warning },
  ];
  
  const statusLine = statusItems
    .map(i => chalk.gray(i.label + ': ') + chalk.hex(i.color).bold(i.value))
    .join(chalk.gray('  │  '));
  
  console.log('  ' + statusLine);
  console.log('');
  
  // Tip del día (rotativo)
  const tips = [
    'Usá /new-tool para que el LLM escriba herramientas nuevas en vivo',
    'Modo sandbox activo: los experimentos no tocan producción',
    '/provider claude para cambiar a Claude Sonnet en esta sesión',
    'Probá: "analizá los últimos ataques y bloqueá los más agresivos"',
  ];
  const tip = tips[Math.floor(Date.now() / 86400000) % tips.length];
  console.log(chalk.gray('  💡 ') + chalk.dim(tip));
  console.log('');
  
  // Separador
  console.log(chalk.hex('#1A1F3A')('  ' + '─'.repeat(70)));
  console.log('');
}

/**
 * Obtiene el estado del sistema desde la API (si está disponible)
 */
export async function getSystemStatus(apiBaseUrl?: string): Promise<SystemStatus> {
  // Valores por defecto
  const defaultStatus: SystemStatus = {
    overall: 'healthy',
    tenants: { active: 0, total: 0 },
    blocks: { active: 0, expired_today: 0 },
    kafka: 'unknown',
    database: 'unknown',
    nginx: 'unknown',
    realtime_processor: 'unknown',
    mcp_server: 'healthy',
  };
  
  if (!apiBaseUrl) {
    return defaultStatus;
  }
  
  try {
    const response = await fetch(`${apiBaseUrl}/health/full`);
    if (!response.ok) {
      return defaultStatus;
    }
    
    const health = await response.json() as {
      status?: string;
      tenants?: { active?: number; total?: number };
      blocks?: { active?: number; expired_today?: number };
      services?: {
        kafka?: { status?: string };
        database?: { status?: string };
        nginx?: { status?: string };
        realtime_processor?: { status?: string };
        mcp_server?: { status?: string };
      };
    };
    
    return {
      overall: health.status === 'healthy' ? 'healthy' : 'degraded',
      tenants: {
        active: health.tenants?.active || 0,
        total: health.tenants?.total || 0,
      },
      blocks: {
        active: health.blocks?.active || 0,
        expired_today: health.blocks?.expired_today || 0,
      },
      kafka: (health.services?.kafka?.status as 'healthy' | 'unhealthy' | 'unknown') || 'unknown',
      database: (health.services?.database?.status as 'healthy' | 'unhealthy' | 'unknown') || 'unknown',
      nginx: (health.services?.nginx?.status as 'healthy' | 'unhealthy' | 'unknown') || 'unknown',
      realtime_processor: (health.services?.realtime_processor?.status as 'healthy' | 'unhealthy' | 'unknown') || 'unknown',
      mcp_server: (health.services?.mcp_server?.status as 'healthy' | 'unhealthy' | 'unknown') || 'healthy',
    };
  } catch (error) {
    // Si no se puede conectar, retornar estado por defecto
    return defaultStatus;
  }
}
