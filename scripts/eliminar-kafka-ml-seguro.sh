#!/bin/bash
# Script para eliminar infraestructura innecesaria (Kafka/ML) de forma segura
# Verifica dependencias antes de eliminar

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="us-central1"
CLUSTER_NAME="tokio-ai-cluster"
NAMESPACE="tokio-ai"

echo "🔍 VERIFICANDO DEPENDENCIAS ANTES DE ELIMINAR"
echo "=============================================="
echo ""

# Función para verificar si un servicio usa Cloud SQL
check_cloud_sql_usage() {
    local service_name=$1
    echo -e "${YELLOW}Verificando si ${service_name} usa Cloud SQL...${NC}"
    
    if gcloud run services describe "${service_name}" \
        --region="${REGION}" \
        --format="value(spec.template.spec.containers[0].env)" 2>/dev/null | grep -qi "cloudsql\|postgres"; then
        echo -e "${RED}⚠️  ${service_name} USA Cloud SQL - NO ELIMINAR Cloud SQL${NC}"
        return 1
    else
        echo -e "${GREEN}✅ ${service_name} NO usa Cloud SQL${NC}"
        return 0
    fi
}

# Función para verificar si un servicio usa Kafka
check_kafka_usage() {
    local service_name=$1
    echo -e "${YELLOW}Verificando si ${service_name} usa Kafka...${NC}"
    
    if gcloud run services describe "${service_name}" \
        --region="${REGION}" \
        --format="value(spec.template.spec.containers[0].env)" 2>/dev/null | grep -qi "kafka"; then
        echo -e "${RED}⚠️  ${service_name} USA Kafka - NO ELIMINAR Kafka${NC}"
        return 1
    else
        echo -e "${GREEN}✅ ${service_name} NO usa Kafka${NC}"
        return 0
    fi
}

# Verificar servicios Cloud Run
echo "📋 Verificando servicios Cloud Run..."
echo ""

SERVICES=("vga-dashboard" "vga-engine")

CLOUD_SQL_USED=false
KAFKA_USED=false

for service in "${SERVICES[@]}"; do
    if check_cloud_sql_usage "${service}"; then
        : # No usa Cloud SQL
    else
        CLOUD_SQL_USED=true
    fi
    
    if check_kafka_usage "${service}"; then
        : # No usa Kafka
    else
        KAFKA_USED=true
    fi
done

echo ""
echo "📊 RESUMEN DE VERIFICACIÓN"
echo "=========================="
echo ""

if [ "$CLOUD_SQL_USED" = true ]; then
    echo -e "${RED}❌ Cloud SQL está en uso - NO ELIMINAR${NC}"
else
    echo -e "${GREEN}✅ Cloud SQL NO está en uso - Se puede eliminar${NC}"
fi

if [ "$KAFKA_USED" = true ]; then
    echo -e "${RED}❌ Kafka está en uso - NO ELIMINAR${NC}"
else
    echo -e "${GREEN}✅ Kafka NO está en uso - Se puede eliminar${NC}"
fi

echo ""
read -p "¿Continuar con la eliminación? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Operación cancelada${NC}"
    exit 0
fi

echo ""
echo "🗑️  INICIANDO ELIMINACIÓN"
echo "=========================="
echo ""

# Paso 1: Eliminar Kafka y Zookeeper del cluster
if [ "$KAFKA_USED" = false ]; then
    echo -e "${YELLOW}Eliminando Kafka y Zookeeper...${NC}"
    
    # Verificar si el cluster existe
    if gcloud container clusters describe "${CLUSTER_NAME}" \
        --region="${REGION}" \
        --project="${PROJECT_ID}" &>/dev/null; then
        
        # Configurar kubectl
        gcloud container clusters get-credentials "${CLUSTER_NAME}" \
            --region="${REGION}" \
            --project="${PROJECT_ID}"
        
        # Eliminar StatefulSets
        echo "  Eliminando StatefulSets..."
        kubectl delete statefulset kafka -n "${NAMESPACE}" --ignore-not-found=true
        kubectl delete statefulset zookeeper -n "${NAMESPACE}" --ignore-not-found=true
        
        # Eliminar Servicios
        echo "  Eliminando Servicios..."
        kubectl delete service kafka -n "${NAMESPACE}" --ignore-not-found=true
        kubectl delete service kafka-ilb -n "${NAMESPACE}" --ignore-not-found=true
        kubectl delete service kafka-nodeport -n "${NAMESPACE}" --ignore-not-found=true
        kubectl delete service zookeeper -n "${NAMESPACE}" --ignore-not-found=true
        
        # Eliminar Jobs
        echo "  Eliminando Jobs..."
        kubectl delete job kafka-topics-init -n "${NAMESPACE}" --ignore-not-found=true
        
        # Eliminar PVCs
        echo "  Eliminando Persistent Volume Claims..."
        kubectl delete pvc -n "${NAMESPACE}" --all --ignore-not-found=true
        
        echo -e "${GREEN}✅ Kafka y Zookeeper eliminados${NC}"
        
        # Verificar si hay otros recursos en el cluster
        echo ""
        echo "🔍 Verificando otros recursos en el cluster..."
        OTHER_RESOURCES=$(kubectl get all -n "${NAMESPACE}" --ignore-not-found=true | wc -l)
        
        if [ "$OTHER_RESOURCES" -le 1 ]; then
            echo -e "${YELLOW}El cluster parece estar vacío. ¿Eliminar el cluster completo?${NC}"
            read -p "Eliminar cluster ${CLUSTER_NAME}? (yes/no): " delete_cluster
            
            if [ "$delete_cluster" = "yes" ]; then
                echo "  Eliminando cluster GKE..."
                gcloud container clusters delete "${CLUSTER_NAME}" \
                    --region="${REGION}" \
                    --project="${PROJECT_ID}" \
                    --quiet
                echo -e "${GREEN}✅ Cluster eliminado${NC}"
                echo -e "${GREEN}💰 Ahorro estimado: ~\$15/día (~\$450/mes)${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  Hay otros recursos en el cluster. No se eliminará automáticamente.${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Cluster no encontrado o ya eliminado${NC}"
    fi
else
    echo -e "${RED}❌ Kafka está en uso - No se eliminará${NC}"
fi

# Paso 2: Eliminar Cloud SQL (si no se usa)
if [ "$CLOUD_SQL_USED" = false ]; then
    echo ""
    echo -e "${YELLOW}Eliminando Cloud SQL...${NC}"
    
    if gcloud sql instances describe tokio-ai-postgres \
        --project="${PROJECT_ID}" &>/dev/null; then
        gcloud sql instances delete tokio-ai-postgres \
            --project="${PROJECT_ID}" \
            --quiet
        echo -e "${GREEN}✅ Cloud SQL eliminado${NC}"
        echo -e "${GREEN}💰 Ahorro estimado: ~\$1/día (~\$30/mes)${NC}"
    else
        echo -e "${YELLOW}⚠️  Cloud SQL no encontrado o ya eliminado${NC}"
    fi
else
    echo -e "${RED}❌ Cloud SQL está en uso - No se eliminará${NC}"
fi

echo ""
echo "✅ ELIMINACIÓN COMPLETADA"
echo "========================"
echo ""
echo "📊 RESUMEN:"
echo "  - Kafka/Zookeeper: Eliminados (si no se usaban)"
echo "  - Cluster GKE: Eliminado (si estaba vacío)"
echo "  - Cloud SQL: Eliminado (si no se usaba)"
echo ""
echo "💰 Ahorro total estimado: ~\$16.50/día (~\$495/mes)"
echo ""
echo "⚠️  IMPORTANTE: Verifica que vga-dashboard y vga-engine sigan funcionando correctamente"
