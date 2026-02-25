import chalk from 'chalk';

export const theme = {
  // Brand
  primary:    '#E94560',  // rojo tokio — alertas, IPs maliciosas, accent principal
  secondary:  '#0F3460',  // azul profundo — headers, bordes
  accent:     '#4A90E2',  // azul claro — tool names, links
  
  // Semánticos
  success:    '#16C784',  // verde — ok, healthy, permitido
  warning:    '#FF9F43',  // naranja — advertencias, pending
  danger:     '#E94560',  // rojo — bloqueado, crítico
  info:       '#4A90E2',  // azul — información
  
  // Texto
  textPrimary:   '#E2E8F0',  // blanco suave
  textSecondary: '#9CA3AF',  // gris medio
  textMuted:     '#4A5568',  // gris oscuro
  
  // Code
  codeBg:     '#1E1E2E',
  codeGreen:  '#A8FF78',
  codePurple: '#BD93F9',
  codePink:   '#FF79C6',
  codeOrange: '#FF9F43',
  
  // UI
  border:     '#2D3561',
  borderLight:'#3D4571',
};

// Helpers para usar el theme
export const themeChalk = {
  primary: (text: string) => chalk.hex(theme.primary)(text),
  secondary: (text: string) => chalk.hex(theme.secondary)(text),
  accent: (text: string) => chalk.hex(theme.accent)(text),
  success: (text: string) => chalk.hex(theme.success)(text),
  warning: (text: string) => chalk.hex(theme.warning)(text),
  danger: (text: string) => chalk.hex(theme.danger)(text),
  info: (text: string) => chalk.hex(theme.info)(text),
  textPrimary: (text: string) => chalk.hex(theme.textPrimary)(text),
  textSecondary: (text: string) => chalk.hex(theme.textSecondary)(text),
  textMuted: (text: string) => chalk.hex(theme.textMuted)(text),
};
