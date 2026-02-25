#!/bin/bash
# Script para actualizar el threshold del WAF en GCP
# Uso: ./scripts/actualizar_threshold_waf.sh

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables (ajustar según tu entorno)
VM_NAME="${VM_NAME:-tokio-waf-tokioia-com}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
PROJECT_ID="${PROJECT_ID:-tactical-unison-417816}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/tokio-ai-waf}"

echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "🔄 Actualizando Threshold del WAF en GCP"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "📋 Configuración:"
echo "   • VM: $VM_NAME"
echo "   • Zone: $VM_ZONE"
echo "   • Project: $PROJECT_ID"
echo "   • Deploy Dir: $DEPLOY_DIR"
echo ""

# Verificar que el archivo existe localmente
if [ ! -f "modsecurity/crs-config/crs-setup.conf" ]; then
    echo "❌ Error: No se encuentra modsecurity/crs-config/crs-setup.conf"
    echo "   Ejecuta este script desde el directorio waf-deployment"
    exit 1
fi

# Verificar que el threshold está en 3
if ! grep -q "tx.inbound_anomaly_score_threshold=3" modsecurity/crs-config/crs-setup.conf; then
    echo -e "${YELLOW}⚠️  Advertencia: El threshold local no está en 3${NC}"
    echo "   Asegúrate de haber actualizado el archivo antes de ejecutar este script"
    read -p "¿Continuar de todas formas? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "📤 Paso 1/3: Copiando archivo actualizado a GCP..."
gcloud compute scp \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    modsecurity/crs-config/crs-setup.conf \
    $VM_NAME:$DEPLOY_DIR/modsecurity/crs-config/crs-setup.conf

if [ $? -eq 0 ]; then
    echo "✅ Archivo copiado exitosamente"
else
    echo "❌ Error al copiar archivo"
    exit 1
fi

echo ""
echo "🔄 Paso 2/3: Reiniciando contenedor ModSecurity..."
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="cd $DEPLOY_DIR && docker-compose restart modsecurity-nginx"

if [ $? -eq 0 ]; then
    echo "✅ Contenedor reiniciado exitosamente"
else
    echo "❌ Error al reiniciar contenedor"
    exit 1
fi

echo ""
echo "🔍 Paso 3/3: Verificando que el cambio se aplicó..."
sleep 5
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="grep 'inbound_anomaly_score_threshold' $DEPLOY_DIR/modsecurity/crs-config/crs-setup.conf"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "✅ Threshold actualizado exitosamente en GCP"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "📊 El WAF ahora bloqueará ataques con score >= 3 (antes era >= 5)"
echo "   Esto significa que los ataques XSS y otros críticos se bloquearán más agresivamente"
echo ""
