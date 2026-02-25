#!/bin/bash
# Script para actualizar log-processor en la VM de GCP
# Elimina Kafka y configura solo Pub/Sub

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
VM_NAME="tokio-ai-waf"
VM_ZONE="us-central1-a"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 ACTUALIZANDO LOG-PROCESSOR EN VM"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "VM: $VM_NAME"
echo "Zona: $VM_ZONE"
echo "Proyecto: $PROJECT_ID"
echo ""

# Copiar archivos actualizados
echo "📤 Copiando archivos actualizados..."
gcloud compute scp modsecurity/log-processor.py ${VM_NAME}:/tmp/log-processor.py \
    --zone=${VM_ZONE} --project=$PROJECT_ID --tunnel-through-iap

gcloud compute scp gcp-deployment/docker-compose.gcp.yml ${VM_NAME}:/tmp/docker-compose.gcp.yml \
    --zone=${VM_ZONE} --project=$PROJECT_ID --tunnel-through-iap

echo "✅ Archivos copiados"
echo ""

# Ejecutar actualización en la VM
echo "🔧 Actualizando en la VM..."
gcloud compute ssh ${VM_NAME} --zone=${VM_ZONE} --project=$PROJECT_ID --tunnel-through-iap << 'ENDSSH'
cd /opt/tokio-ai-waf

# Detener y eliminar contenedor viejo
echo "Deteniendo log-processor..."
docker stop tokio-ai-log-processor 2>/dev/null || true
docker rm tokio-ai-log-processor 2>/dev/null || true

# Copiar archivos actualizados
echo "Copiando archivos..."
sudo cp /tmp/log-processor.py modsecurity/log-processor.py
sudo cp /tmp/docker-compose.gcp.yml gcp-deployment/docker-compose.gcp.yml
sudo chown -R $(whoami):$(whoami) modsecurity/ gcp-deployment/

# Configurar variables de entorno
export GCP_PROJECT_ID=YOUR_GCP_PROJECT_ID
export PUBSUB_TOPIC_ID=waf-logs

# Iniciar nuevo contenedor
echo "Iniciando nuevo log-processor..."
cd gcp-deployment
docker compose -f docker-compose.gcp.yml up -d log-processor

# Verificar estado
sleep 3
echo ""
echo "Estado del contenedor:"
docker ps --filter 'name=tokio-ai-log-processor' --format 'table {{.Names}}\t{{.Status}}'

echo ""
echo "Últimos logs:"
docker logs tokio-ai-log-processor --tail 10 2>&1 | tail -10
ENDSSH

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ACTUALIZACIÓN COMPLETADA"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Verifica que en los logs aparezca:"
echo "  ✅ Topic Pub/Sub existe: waf-logs"
echo "  ✅ Batch enviado a Pub/Sub: X/Y logs"
