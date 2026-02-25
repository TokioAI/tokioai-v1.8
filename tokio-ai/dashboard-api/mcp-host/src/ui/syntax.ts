import chalk from 'chalk';
import { theme } from './theme.js';

/**
 * Syntax highlighting básico para Python
 */
export function highlightPython(code: string): string {
  const keywords = /\b(def|class|import|from|return|if|else|elif|for|while|try|except|with|as|async|await|True|False|None|and|or|not|in|is)\b/g;
  const strings = /(["'])(?:(?=(\\?))\2.)*?\1/g;
  const comments = /(#.*$)/gm;
  const numbers = /\b(\d+\.?\d*)\b/g;
  const funcNames = /\b([a-z_][a-z0-9_]*)\s*(?=\()/g;
  const decorators = /(@[a-zA-Z_][a-zA-Z0-9_]*)/g;
  
  return code
    .replace(comments,   chalk.gray('$1'))
    .replace(strings,    chalk.hex(theme.codeGreen)('$&'))
    .replace(keywords,   chalk.hex(theme.codePink).bold('$1'))
    .replace(numbers,    chalk.hex(theme.codePurple)('$1'))
    .replace(decorators, chalk.hex(theme.codeOrange)('$1'))
    .replace(funcNames,  chalk.hex('#50FA7B')('$1'));
}

/**
 * Syntax highlighting básico para TypeScript/JavaScript
 */
export function highlightTypeScript(code: string): string {
  const keywords = /\b(const|let|var|function|class|interface|type|export|import|from|return|if|else|for|while|try|catch|async|await|true|false|null|undefined|and|or|not|in|of|extends|implements)\b/g;
  const strings = /(["'`])(?:(?=(\\?))\2.)*?\1/g;
  const comments = /(\/\/.*$|\/\*[\s\S]*?\*\/)/gm;
  const numbers = /\b(\d+\.?\d*)\b/g;
  const funcNames = /\b([a-z_$][a-z0-9_$]*)\s*(?=\()/g;
  
  return code
    .replace(comments,   chalk.gray('$1'))
    .replace(strings,    chalk.hex(theme.codeGreen)('$&'))
    .replace(keywords,   chalk.hex(theme.codePink).bold('$1'))
    .replace(numbers,    chalk.hex(theme.codePurple)('$1'))
    .replace(funcNames,  chalk.hex('#50FA7B')('$1'));
}

/**
 * Highlight genérico de código (detecta lenguaje automáticamente)
 */
export function highlightCode(code: string, language?: string): string {
  if (language === 'python' || code.includes('def ') || code.includes('import ')) {
    return highlightPython(code);
  } else if (language === 'typescript' || language === 'javascript' || code.includes('function ') || code.includes('const ')) {
    return highlightTypeScript(code);
  }
  return code; // Sin highlight si no se detecta
}
