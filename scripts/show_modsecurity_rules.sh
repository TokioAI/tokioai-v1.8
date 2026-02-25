#!/bin/bash
# Script para mostrar las reglas de ModSecurity usando el MCP Host

cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     Mostrando Reglas ModSecurity usando MCP Host + LLM              ║"
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

echo ""
echo "🔧 Iniciando MCP Host..."
echo ""

# Ejecutar MCP Host con el prompt
cd mcp-host
node dist/index.js chat -- -p "muéstrame las reglas activas de ModSecurity que tenemos configuradas en el sistema. Incluye: 1) ubicación de archivos de reglas, 2) número total de reglas activas, 3) tipos de ataques protegidos (SQL Injection, XSS, Path Traversal, etc.), 4) métodos de bypass detectados, y 5) un ejemplo de regla auto-generada con su explicación"




