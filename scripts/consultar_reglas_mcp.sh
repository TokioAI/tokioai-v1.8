#!/bin/bash
# Script para consultar reglas de ModSecurity usando MCP Host + Server MCP

cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  Consultando Reglas ModSecurity via MCP Host → MCP Server            ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Cargar variables de entorno
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "✅ Configuración cargada desde .env"
else
    echo "⚠️  Archivo .env no encontrado"
    exit 1
fi

# Verificar que el contenedor MCP esté corriendo
if ! docker ps | grep -q soc-mcp-core; then
    echo "⚠️  Contenedor soc-mcp-core no está corriendo"
    echo "   Inicia con: docker-compose up -d soc-mcp-core"
    exit 1
fi

echo "✅ Servidor MCP disponible"
echo ""
echo "🔧 Iniciando MCP Host..."
echo "📋 Usando herramientas del servidor MCP:"
echo "   • get_waf_rules - Obtiene reglas desde PostgreSQL"
echo "   • query_logs - Consulta logs del WAF"
echo "   • get_waf_stats - Estadísticas del WAF"
echo ""

cd mcp-host

# Ejecutar MCP Host con el prompt
PROMPT="usa la herramienta get_waf_rules para obtener y mostrarme todas las reglas activas de ModSecurity. Incluye: 1) número total de reglas, 2) estadísticas (reglas IA vs iniciales), 3) tipos de ataques protegidos, 4) ejemplos de reglas auto-generadas"

echo "📝 Prompt: $PROMPT"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

node dist/index.js chat -- -p "$PROMPT"




