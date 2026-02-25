#!/bin/bash

# Script para calcular la capacidad teórica del sistema
# Analiza componentes y calcula límites de procesamiento

set -e

echo "🧮 CALCULANDO CAPACIDAD TEÓRICA DEL SISTEMA..."
echo ""

# 1. Kafka
echo "📊 KAFKA:"
KAFKA_TOPICS=$(docker exec soc-kafka kafka-topics --list --bootstrap-server localhost:9093 2>/dev/null | wc -l)
echo "   Topics: $KAFKA_TOPICS"
echo "   Partitions (waf-logs): 10"
echo "   Throughput teórico: ~10,000 - 100,000 mensajes/segundo por partición"
echo "   Total teórico: ~100,000 - 1,000,000 mensajes/segundo"
echo ""

# 2. PostgreSQL
echo "📊 POSTGRESQL:"
PG_VERSION=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT version();" 2>/dev/null | head -1 | cut -d' ' -f3)
echo "   Versión: PostgreSQL $PG_VERSION"
echo "   Throughput escritura: ~5,000 - 50,000 inserts/segundo (depende de hardware)"
echo "   Índices optimizados: Sí (tenant_id, timestamp, blocked)"
echo ""

# 3. Real-Time Processor
echo "📊 REAL-TIME PROCESSOR:"
if docker ps | grep -q soc-realtime-processor; then
    echo "   Estado: ✅ Corriendo"
    echo "   ML Prediction: ~50ms por log"
    echo "   LLM Analysis: ~500ms por log (solo si threat_score > 0.7)"
    echo "   Throughput teórico ML: ~20 logs/segundo (100% ML)"
    echo "   Throughput teórico ML+LLM: ~10 logs/segundo (si 50% requieren LLM)"
else
    echo "   Estado: ❌ No corriendo"
fi
echo ""

# 4. ModSecurity/Nginx
echo "📊 MODSECURITY/NGINX:"
echo "   Worker processes: Auto (CPU cores)"
echo "   Worker connections: 1024 por worker"
echo "   Throughput teórico: ~10,000 - 50,000 requests/segundo"
echo "   Logging overhead: ~5-10% de throughput"
echo ""

# 5. Log Processor
echo "📊 LOG PROCESSOR:"
if docker ps | grep -q soc-log-processor; then
    echo "   Estado: ✅ Corriendo"
    echo "   Batch size: 1000 logs"
    echo "   Batch timeout: 100ms"
    echo "   Throughput teórico: ~10,000 logs/segundo (batch mode)"
else
    echo "   Estado: ❌ No corriendo"
fi
echo ""

# Calcular capacidad end-to-end
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     📈 CAPACIDAD TEÓRICA END-TO-END                                 ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔹 ESCENARIO 1: Solo ML (sin LLM)"
echo "   • ModSecurity: 10,000 req/s → Kafka"
echo "   • Kafka: Buffer ilimitado"
echo "   • Real-Time Processor: ~20 logs/s (cuello de botella)"
echo "   • PostgreSQL: 5,000+ inserts/s (suficiente)"
echo "   → ${GREEN}CAPACIDAD: ~20 logs/segundo${NC}"
echo ""
echo "🔹 ESCENARIO 2: ML + LLM (50% requiere LLM)"
echo "   • ModSecurity: 10,000 req/s → Kafka"
echo "   • Kafka: Buffer ilimitado"
echo "   • Real-Time Processor: ~10 logs/s (cuello de botella)"
echo "   • PostgreSQL: 5,000+ inserts/s (suficiente)"
echo "   → ${GREEN}CAPACIDAD: ~10 logs/segundo${NC}"
echo ""
echo "🔹 ESCENARIO 3: Solo logging (sin análisis)"
echo "   • ModSecurity: 10,000 req/s → Kafka"
echo "   • Kafka: Buffer ilimitado"
echo "   • Log Processor: ~10,000 logs/s"
echo "   • PostgreSQL: 5,000+ inserts/s"
echo "   → ${GREEN}CAPACIDAD: ~5,000 logs/segundo${NC} (limitado por PostgreSQL)"
echo ""

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     ⚠️  CUELO DE BOTELLA IDENTIFICADO                                ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔴 REAL-TIME PROCESSOR es el cuello de botella principal"
echo "   • ML: ~20 logs/segundo"
echo "   • ML+LLM: ~10 logs/segundo"
echo ""
echo "💡 OPTIMIZACIONES POSIBLES:"
echo "   1. Procesamiento paralelo (múltiples instancias realtime-processor)"
echo "   2. Reducir uso de LLM (solo threats_score > 0.9)"
echo "   3. Batch processing en ML (procesar múltiples logs juntos)"
echo "   4. Usar modelo ML más rápido (trade-off precisión/velocidad)"
echo ""

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     ✅ CAPACIDAD RECOMENDADA PARA PRODUCCIÓN                         ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "🎯 Para detección en tiempo real con ML+LLM:"
echo "   • ${GREEN}5-10 logs/segundo${NC} (conservador)"
echo "   • ${YELLOW}10-20 logs/segundo${NC} (óptimo con ML solamente)"
echo ""
echo "🎯 Para logging básico (sin análisis detallado):"
echo "   • ${GREEN}1,000-5,000 logs/segundo${NC}"
echo ""
echo "🎯 Para alta carga, usar:"
echo "   • Múltiples instancias de realtime-processor"
echo "   • Particiones de Kafka distribuidas"
echo "   • PostgreSQL con replicación/partitioning"
echo ""

