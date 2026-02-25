import chalk from 'chalk';
import { theme } from './theme.js';

export interface CLIState {
  provider: string;
  mode: 'agent' | 'plan' | 'ask';
  sandboxMode: boolean;
  tokensUsed: number;
}

/**
 * Formatea tokens para mostrar (ej: 2400 -> "2.4k")
 */
function formatTokens(tokens: number): string {
  if (tokens < 1000) return String(tokens);
  if (tokens < 1000000) return (tokens / 1000).toFixed(1) + 'k';
  return (tokens / 1000000).toFixed(1) + 'M';
}

/**
 * Construye el prompt dinámico con contexto en tiempo real
 */
export function buildPrompt(state: CLIState): string {
  const provider = chalk.hex(theme.warning)(state.provider);          // naranja
  const mode = chalk.hex(theme.accent)(state.mode);                  // azul
  const sandbox = state.sandboxMode 
    ? chalk.hex(theme.primary).bold(' SANDBOX') 
    : '';
  const tokens = state.tokensUsed > 0 
    ? chalk.gray(` ~${formatTokens(state.tokensUsed)}`) 
    : '';
  
  return `\n  ${provider}${chalk.gray('/')}${mode}${sandbox}${tokens}\n  ${chalk.hex(theme.primary)('❯')} `;
}
