import Table from 'cli-table3';
import chalk from 'chalk';
import { theme } from './theme.js';

/**
 * Trunca un string a una longitud máxima
 */
function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 3) + '...';
}

/**
 * Formatea un array de objetos como tabla
 */
export function formatTable(data: Record<string, any>[], maxRows = 20): string {
  if (!data || data.length === 0) return chalk.gray('  (sin resultados)');
  
  const keys = Object.keys(data[0]).slice(0, 6); // máx 6 columnas
  
  const table = new Table({
    head: keys.map(k => chalk.hex(theme.accent).bold(k)),
    style: {
      head: [],
      border: ['hex', theme.border],
      compact: true
    },
    chars: {
      'top': '─', 'top-mid': '┬', 'top-left': '┌', 'top-right': '┐',
      'bottom': '─', 'bottom-mid': '┴', 'bottom-left': '└', 'bottom-right': '┘',
      'left': '│', 'left-mid': '├', 'right': '│', 'right-mid': '┤',
      'mid': '─', 'mid-mid': '┼', 'middle': '│'
    }
  });
  
  const rows = data.slice(0, maxRows);
  
  for (const row of rows) {
    table.push(
      keys.map(k => {
        const val = String(row[k] ?? '-');
        // Color por tipo de valor
        if (val === 'BLOQUEADO' || val === 'true') return chalk.red(val);
        if (val === 'PERMITIDO' || val === 'false') return chalk.hex(theme.success)(val);
        if (val.match(/^\d+\.\d+\.\d+\.\d+$/)) return chalk.hex(theme.primary).bold(val); // IP
        if (val.match(/^(XSS|SQLI|CMD|LFI|RFI)/)) return chalk.hex(theme.warning)(val);  // threat
        return chalk.white(truncate(val, 40));
      })
    );
  }
  
  let output = '\n' + table.toString()
    .split('\n')
    .map(l => '  ' + l)
    .join('\n');
  
  if (data.length > maxRows) {
    output += chalk.gray(`\n  ... y ${data.length - maxRows} resultados más`);
  }
  
  return output + '\n';
}

/**
 * Formatea JSON con colores y profundidad limitada
 */
export function formatJSON(obj: any, options: { indent?: number; maxDepth?: number } = {}): string {
  const indent = options.indent || 2;
  const maxDepth = options.maxDepth || 2;
  
  function formatValue(value: any, depth: number): string {
    if (depth > maxDepth) {
      return chalk.gray('...');
    }
    
    if (value === null) return chalk.gray('null');
    if (value === undefined) return chalk.gray('undefined');
    
    if (typeof value === 'string') {
      // IPs en rojo
      if (value.match(/^\d+\.\d+\.\d+\.\d+$/)) {
        return chalk.hex(theme.primary).bold(`"${value}"`);
      }
      // Estados en colores
      if (value === 'BLOQUEADO' || value === 'BLOCKED') return chalk.red(`"${value}"`);
      if (value === 'PERMITIDO' || value === 'OK' || value === 'HEALTHY') return chalk.hex(theme.success)(`"${value}"`);
      return chalk.hex(theme.codeGreen)(`"${value}"`);
    }
    
    if (typeof value === 'number') {
      return chalk.hex(theme.codePurple)(String(value));
    }
    
    if (typeof value === 'boolean') {
      return value ? chalk.hex(theme.success)('true') : chalk.red('false');
    }
    
    if (Array.isArray(value)) {
      if (value.length === 0) return chalk.gray('[]');
      const items = value.slice(0, 3).map(item => formatValue(item, depth + 1));
      const more = value.length > 3 ? chalk.gray(` ... y ${value.length - 3} más`) : '';
      return `[ ${items.join(', ')}${more} ]`;
    }
    
    if (typeof value === 'object') {
      const keys = Object.keys(value).slice(0, 5);
      const pairs = keys.map(k => {
        const v = formatValue(value[k], depth + 1);
        return `${chalk.hex(theme.accent)(k)}: ${v}`;
      });
      const more = Object.keys(value).length > 5 ? chalk.gray(', ...') : '';
      return `{ ${pairs.join(', ')}${more} }`;
    }
    
    return String(value);
  }
  
  return formatValue(obj, 0);
}
