#!/bin/bash
# Script para esperar que todos los servicios estén healthy
# Timeout máximo: 3 minutos

set -e

TIMEOUT=180
ELAPSED=0
INTERVAL=5

echo "⏳ Esperando que los servicios estén listos..."

check_service() {
    local service=$1
    local healthcheck=$2
    
    if docker-compose ps | grep -q "${service}.*healthy"; then
        return 0
    fi
    
    # Si tiene healthcheck específico, ejecutarlo
    if [ -n "$healthcheck" ]; then
        eval "$healthcheck" > /dev/null 2>&1 && return 0
    fi
    
    return 1
}

while [ $ELAPSED -lt $TIMEOUT ]; do
    all_healthy=true
    
    # Verificar PostgreSQL
    if ! check_service "postgres" "docker-compose exec -T postgres pg_isready -U soc_user"; then
        all_healthy=false
        echo "  ⏳ PostgreSQL aún no está listo..."
    fi
    
    # Verificar Kafka
    if ! check_service "kafka" "docker-compose exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092"; then
        all_healthy=false
        echo "  ⏳ Kafka aún no está listo..."
    fi
    
    # Verificar real-time-processor
    if ! check_service "real-time-processor" "curl -sf http://localhost:8081/health > /dev/null"; then
        all_healthy=false
        echo "  ⏳ Real-time-processor aún no está listo..."
    fi
    
    # Verificar dashboard-api
    if ! check_service "dashboard-api" "curl -sf http://localhost:8000/health > /dev/null"; then
        all_healthy=false
        echo "  ⏳ Dashboard API aún no está listo..."
    fi
    
    if [ "$all_healthy" = true ]; then
        echo "✅ Todos los servicios están listos!"
        exit 0
    fi
    
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "❌ Timeout esperando servicios (${TIMEOUT}s)"
echo "📋 Estado actual:"
docker-compose ps
exit 1
