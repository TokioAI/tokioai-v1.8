import chalk from 'chalk';
import { highlightCode } from './syntax.js';
import { theme } from './theme.js';

/**
 * Renderiza respuestas del LLM en streaming con markdown básico
 */
export class StreamingResponseRenderer {
  private buffer = '';
  private inCodeBlock = false;
  private codeLanguage = '';
  
  // Llamar con cada chunk de texto del LLM
  write(chunk: string) {
    process.stdout.write(this.renderChunk(chunk));
    this.buffer += chunk;
  }
  
  private renderChunk(chunk: string): string {
    // Detectar bloques de código
    if (chunk.includes('```')) {
      this.inCodeBlock = !this.inCodeBlock;
      if (this.inCodeBlock) {
        // Extraer lenguaje si está especificado
        const langMatch = chunk.match(/```(\w+)?/);
        this.codeLanguage = langMatch?.[1] || '';
        return chalk.gray('\n  ┌─ código ─────────────────────\n');
      } else {
        return chalk.gray('\n  └──────────────────────────────\n');
      }
    }
    
    if (this.inCodeBlock) {
      // Código con syntax highlight básico
      return '  ' + highlightCode(chunk, this.codeLanguage);
    }
    
    // Texto normal: aplicar markdown básico inline
    return '  ' + applyInlineMarkdown(chunk);
  }
  
  /**
   * Obtiene el buffer completo
   */
  getBuffer(): string {
    return this.buffer;
  }
  
  /**
   * Limpia el buffer
   */
  clear() {
    this.buffer = '';
    this.inCodeBlock = false;
    this.codeLanguage = '';
  }
}

/**
 * Aplica estilos markdown inline al texto
 */
function applyInlineMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, chalk.bold.white('$1'))
    .replace(/`(.+?)`/g, chalk.bgHex(theme.codeBg).hex(theme.codeGreen)(' $1 '))
    .replace(/\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g, chalk.hex(theme.primary).bold('$1'))
    .replace(/\b(BLOQUEADO|BLOCKED|CRITICAL|ERROR)\b/g, chalk.red.bold('$1'))
    .replace(/\b(OK|PERMITIDO|HEALTHY|SUCCESS)\b/g, chalk.hex(theme.success).bold('$1'))
    .replace(/\b(ADVERTENCIA|WARNING|DETECTED)\b/g, chalk.hex(theme.warning).bold('$1'));
}
