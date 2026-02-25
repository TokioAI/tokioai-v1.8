import ora from 'ora';
import chalk from 'chalk';
import { formatTable, formatJSON } from './formatters.js';
import { theme } from './theme.js';

/**
 * Trunca un string a una longitud máxima
 */
function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 3) + '...';
}

/**
 * Clase para mostrar tool calls con animación y formateo
 */
export class ToolCallDisplay {
  private spinner: any;
  
  showToolStart(toolName: string, args: Record<string, any>) {
    // Mostrar la llamada con args resumidos
    const argsStr = Object.entries(args)
      .map(([k, v]) => `${chalk.gray(k)}: ${chalk.white(truncate(String(v), 30))}`)
      .join(chalk.gray(', '));
    
    console.log(
      '\n  ' + 
      chalk.hex(theme.accent)('⟳ ') + 
      chalk.bold(toolName) + 
      chalk.gray(' · ') + 
      argsStr
    );
    
    this.spinner = ora({
      text: chalk.gray('  ejecutando...'),
      indent: 2,
      spinner: 'dots2',
      color: 'blue'
    }).start();
  }
  
  showToolResult(toolName: string, result: any, durationMs: number) {
    this.spinner?.stop();
    
    const duration = chalk.gray(`${durationMs}ms`);
    
    // Header del resultado
    console.log(
      '  ' + 
      chalk.hex(theme.success)('✓ ') + 
      chalk.bold(toolName) + 
      chalk.gray(' → ') + 
      duration
    );
    
    // Renderizar resultado según tipo
    if (Array.isArray(result) && result.length > 0 && typeof result[0] === 'object') {
      // Array de objetos → tabla
      console.log(formatTable(result));
    } else if (typeof result === 'object' && result !== null) {
      // Objeto → JSON coloreado compacto
      console.log(formatJSON(result, { indent: 4, maxDepth: 2 }));
    } else {
      // Texto plano
      console.log(chalk.gray('  ') + String(result));
    }
    
    console.log('');
  }
  
  showToolError(toolName: string, error: string) {
    this.spinner?.stop();
    console.log(
      '  ' + chalk.red('✗ ') + chalk.bold(toolName) + 
      chalk.gray(' → ') + chalk.red(error)
    );
    console.log('');
  }
}
