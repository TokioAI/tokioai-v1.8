#!/bin/bash
# Script para asegurar que Kafka esté siempre disponible

cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     Iniciando servicios de Kafka para SOC-AI-LAB                     ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Verificar si ya están corriendo
if docker ps | grep -q soc-kafka && docker ps | grep soc-kafka | grep -q "Up"; then
    echo "✅ Kafka ya está corriendo"
    docker ps --filter "name=kafka" --format "{{.Names}}: {{.Status}}"
else
    echo "🚀 Iniciando servicios de Kafka..."
    docker-compose up -d zookeeper kafka kafka-init log-processor
    
    echo ""
    echo "⏳ Esperando a que Kafka esté listo..."
    sleep 10
    
    # Verificar estado
    if docker ps | grep soc-kafka | grep -q "healthy"; then
        echo "✅ Kafka iniciado correctamente"
    else
        echo "⚠️  Kafka puede tardar un momento en estar completamente listo"
        echo "   Verifica con: docker ps | grep kafka"
    fi
fi

echo ""
echo "📊 Estado de los servicios:"
docker ps --filter "name=kafka" --format "{{.Names}}: {{.Status}}"
docker ps --filter "name=zookeeper" --format "{{.Names}}: {{.Status}}"
docker ps --filter "name=log-processor" --format "{{.Names}}: {{.Status}}"

echo ""
echo "📋 Topics disponibles:"
docker exec soc-kafka kafka-topics --list --bootstrap-server localhost:9093 2>/dev/null || echo "   Kafka aún no está completamente listo"

echo ""
echo "💡 Para verificar logs:"
echo "   docker logs -f soc-log-processor"
echo ""
echo "💡 Para obtener logs desde MCP Host:"
echo "   cd mcp-host && export \$(grep -v '^#' ../.env | xargs)"
echo '   npm start chat -p "usa get_waf_logs_from_kafka con offset earliest para obtener logs"'




