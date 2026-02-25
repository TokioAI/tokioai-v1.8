#!/bin/bash
# Script para inicializar topics de Kafka con configuración optimizada

set -e

KAFKA_CONTAINER="${KAFKA_CONTAINER:-soc-kafka}"
BOOTSTRAP_SERVER="${BOOTSTRAP_SERVER:-localhost:9092}"
TOPIC_NAME="${TOPIC_NAME:-waf-logs}"
PARTITIONS="${PARTITIONS:-10}"
REPLICATION_FACTOR="${REPLICATION_FACTOR:-1}"

echo "🚀 Inicializando topic de Kafka: $TOPIC_NAME"
echo "   Partitions: $PARTITIONS"
echo "   Replication Factor: $REPLICATION_FACTOR"
echo ""

# Esperar a que Kafka esté listo
echo "⏳ Esperando a que Kafka esté listo..."
for i in {1..30}; do
    if docker exec "$KAFKA_CONTAINER" kafka-broker-api-versions --bootstrap-server "$BOOTSTRAP_SERVER" > /dev/null 2>&1; then
        echo "✅ Kafka está listo"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Error: Kafka no está disponible después de 30 intentos"
        exit 1
    fi
    sleep 2
done

# Crear topic si no existe
echo "📝 Creando topic: $TOPIC_NAME"
docker exec "$KAFKA_CONTAINER" kafka-topics --create \
    --if-not-exists \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --topic "$TOPIC_NAME" \
    --partitions "$PARTITIONS" \
    --replication-factor "$REPLICATION_FACTOR" \
    --config retention.ms=604800000 \
    --config segment.ms=3600000 \
    --config compression.type=producer

echo "✅ Topic creado exitosamente"

# Verificar configuración
echo ""
echo "📊 Configuración del topic:"
docker exec "$KAFKA_CONTAINER" kafka-topics --describe \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --topic "$TOPIC_NAME"

echo ""
echo "✅ Inicialización completada"



