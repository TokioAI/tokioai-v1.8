#!/bin/bash
# Script para optimizar costos de Cloud Run
# Reduce recursos (CPU/memoria) y permite escalar a cero

set -e

echo "💰 OPTIMIZANDO COSTOS DE CLOUD RUN"
echo "=================================="
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

REGION="us-central1"

# Función para actualizar servicio
update_service() {
    local SERVICE_NAME=$1
    local CPU=$2
    local MEMORY=$3
    local MIN_INSTANCES=${4:-0}
    local MAX_INSTANCES=${5:-10}
    
    echo -e "${YELLOW}Actualizando ${SERVICE_NAME}...${NC}"
    echo "  CPU: ${CPU}"
    echo "  Memoria: ${MEMORY}"
    echo "  Min Instances: ${MIN_INSTANCES}"
    echo "  Max Instances: ${MAX_INSTANCES}"
    
    gcloud run services update "${SERVICE_NAME}" \
        --region="${REGION}" \
        --cpu="${CPU}" \
        --memory="${MEMORY}" \
        --min-instances="${MIN_INSTANCES}" \
        --max-instances="${MAX_INSTANCES}" \
        --quiet
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ ${SERVICE_NAME} actualizado correctamente${NC}"
    else
        echo -e "${RED}❌ Error actualizando ${SERVICE_NAME}${NC}"
        return 1
    fi
    echo ""
}

# Dashboard API - Optimizado (servicio simple, no necesita muchos recursos)
echo "📊 OPTIMIZANDO DASHBOARD-API"
update_service "dashboard-api" "1" "512Mi" "0" "5"

# Real-time Processor - Reducido (pero más que dashboard porque procesa logs)
echo "⚙️  OPTIMIZANDO REAL-TIME-PROCESSOR"
update_service "realtime-processor" "1" "2Gi" "0" "5"

echo -e "${GREEN}✅ Optimización completada${NC}"
echo ""
echo "💰 AHORRO ESPERADO:"
echo "  • Antes: ~\$80/día (~\$2,400/mes)"
echo "  • Después: ~\$10-20/día (~\$300-600/mes)"
echo "  • Reducción: ~75-87%"
echo ""
echo "📊 CAMBIOS APLICADOS:"
echo "  • CPU reducido: 2 → 1 (50% menos)"
echo "  • Memoria reducida: 2-4GB → 512MB-2GB (50-87% menos)"
echo "  • Min Instances: 1 → 0 (escalar a cero cuando no hay tráfico)"
echo "  • Max Instances: 10 → 5 (limitar picos de costo)"
echo ""
echo "⚠️  NOTA: Los servicios ahora escalarán a cero cuando no haya tráfico."
echo "   El primer request después de estar inactivo puede tardar unos segundos más."







