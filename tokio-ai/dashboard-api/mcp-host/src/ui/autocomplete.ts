import * as readline from 'readline';

export interface SlashCommand {
  cmd: string;
  desc: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: '/help',           desc: 'Lista todos los comandos' },
  { cmd: '/tools',          desc: 'Tools MCP disponibles' },
  { cmd: '/new-tool',       desc: 'Crear nueva tool con el LLM' },
  { cmd: '/test',           desc: 'Testear tool en sandbox' },
  { cmd: '/promote',        desc: 'Promover tool a producción' },
  { cmd: '/sandbox',        desc: 'Activar/desactivar modo sandbox' },
  { cmd: '/mode agent',     desc: 'Modo autónomo (default)' },
  { cmd: '/mode plan',      desc: 'Planificar antes de ejecutar' },
  { cmd: '/mode ask',       desc: 'Solo responder preguntas' },
  { cmd: '/provider',       desc: 'Cambiar LLM provider' },
  { cmd: '/model',          desc: 'Cambiar modelo' },
  { cmd: '/history',        desc: 'Ver sesiones anteriores' },
  { cmd: '/export',         desc: 'Exportar conversación' },
  { cmd: '/clear',          desc: 'Limpiar pantalla' },
  { cmd: '/clear-history',  desc: 'Resetear conversación' },
  { cmd: '/status',         desc: 'Estado del sistema en tiempo real' },
];

/**
 * Completer function para readline - autocompletado de slash commands
 */
export function completer(line: string): [string[], string] {
  if (line.startsWith('/')) {
    const hits = SLASH_COMMANDS
      .filter(c => c.cmd.startsWith(line))
      .map(c => c.cmd);
    return [hits.length ? hits : [], line];
  }
  return [[], line];
}

/**
 * Obtiene la descripción de un comando
 */
export function getCommandDescription(cmd: string): string | undefined {
  return SLASH_COMMANDS.find(c => c.cmd === cmd)?.desc;
}
