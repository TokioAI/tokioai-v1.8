import ora from 'ora';
import chalk from 'chalk';
import { theme } from './theme.js';

/**
 * Muestra el estado del sistema en tiempo real
 */
interface HealthResponse {
  services?: {
    database?: { status?: string; latency_ms?: number };
    kafka?: { status?: string; consumer_lag?: number };
    nginx?: { status?: string; tenants_configured?: number };
    realtime_processor?: { status?: string; events_processed_1m?: number };
    mcp_server?: { status?: string; tools_available?: number };
  };
  tenants?: { active?: number };
  blocks?: { active?: number; expired_today?: number };
}

export async function showStatus(apiBaseUrl: string) {
  const spinner = ora('Consultando sistema...').start();
  
  try {
    const health = await fetch(`${apiBaseUrl}/health/full`).then(r => r.json()) as HealthResponse;
    spinner.stop();
    
    console.log('');
    console.log(chalk.bold('  ESTADO DEL SISTEMA') + chalk.gray(' — ' + new Date().toLocaleTimeString()));
    console.log('  ' + '─'.repeat(60));
    
    // Grid de servicios
    const services = [
      ['Database',        health.services?.database?.status || 'unknown',          (health.services?.database?.latency_ms || 0) + 'ms'],
      ['Kafka',           health.services?.kafka?.status || 'unknown',             'lag: ' + (health.services?.kafka?.consumer_lag || 0)],
      ['Proxy WAF',       health.services?.nginx?.status || 'unknown',             (health.services?.nginx?.tenants_configured || 0) + ' tenants'],
      ['RT Processor',    health.services?.realtime_processor?.status || 'unknown', (health.services?.realtime_processor?.events_processed_1m || 0) + '/min'],
      ['MCP Server',      health.services?.mcp_server?.status || 'unknown',        (health.services?.mcp_server?.tools_available || 0) + ' tools'],
    ];
    
    for (const [name, status, detail] of services) {
      const icon = status === 'healthy' 
        ? chalk.hex(theme.success)('●') 
        : chalk.red('●');
      const nameStr = chalk.white(name.padEnd(18));
      const statusStr = status === 'healthy' 
        ? chalk.hex(theme.success)('healthy') 
        : chalk.red(status);
      const detailStr = chalk.gray(detail);
      
      console.log(`  ${icon} ${nameStr} ${statusStr.padEnd(20)} ${detailStr}`);
    }
    
    console.log('  ' + '─'.repeat(60));
    
    // Stats rápidas
    console.log(
      chalk.gray('  Tenants activos: ') + chalk.white(health.tenants?.active || 0) +
      chalk.gray('   IPs bloqueadas: ') + chalk.hex(theme.primary).bold(health.blocks?.active || 0) +
      chalk.gray('   Liberadas hoy: ') + chalk.white(health.blocks?.expired_today || 0)
    );
    console.log('');
    
  } catch (e: any) {
    spinner.fail('No se pudo conectar a la API');
    console.log(chalk.red('  Error: ') + (e.message || 'Desconocido'));
    console.log('');
  }
}
