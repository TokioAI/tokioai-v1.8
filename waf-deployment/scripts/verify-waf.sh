#!/bin/bash
# Script de verificación rápida del WAF

VM_NAME="${VM_NAME:-tokio-ai-waf}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"

echo "🔍 Verificando estado del WAF..."
echo ""

# Obtener IP
VM_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)

echo "🌐 IP de la VM: $VM_IP"
echo ""

# Verificar contenedores
echo "📦 Contenedores:"
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E '(modsecurity|log-processor|NAME)'" 2>&1 | tail -5

echo ""
echo "🔌 Puertos:"
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="sudo ss -tlnp | grep -E ':(80|443)'" 2>&1 | tail -3

echo ""
echo "🌐 Conectividad:"
if timeout 3 curl -I http://$VM_IP 2>&1 | grep -q "HTTP"; then
    echo "✅ HTTP: OK"
else
    echo "❌ HTTP: No responde"
fi

if timeout 3 curl -I -k https://$VM_IP 2>&1 | grep -q "HTTP"; then
    echo "✅ HTTPS: OK"
else
    echo "❌ HTTPS: No responde"
fi

echo ""
