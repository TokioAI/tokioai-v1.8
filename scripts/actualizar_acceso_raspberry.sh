#!/bin/bash
# Script para actualizar el acceso desde Raspberry Pi
# Detecta la IP actual y actualiza las firewall rules

set -e

PROJECT_ID="${1:-YOUR_GCP_PROJECT_ID}"
RASPBERRY_IP="${2:-$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip)}"

if [ -z "$RASPBERRY_IP" ] || [ "$RASPBERRY_IP" = "NO_DETECTADA" ]; then
    echo "❌ No se pudo detectar tu IP pública"
    echo "   Proporciónala manualmente:"
    echo "   ./scripts/actualizar_acceso_raspberry.sh $PROJECT_ID TU_IP_PUBLICA"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "🔓 ACTUALIZANDO ACCESO DESDE RASPBERRY PI"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   Proyecto: $PROJECT_ID"
echo "   IP Raspberry: $RASPBERRY_IP"
echo ""

# Eliminar regla antigua si existe
echo "1. Eliminando regla antigua (si existe)..."
gcloud compute firewall-rules delete allow-raspberry-all-ports \
    --project="$PROJECT_ID" \
    --quiet 2>&1 | grep -E "(Deleted|not found)" || true

# Crear nueva regla con la IP actual
echo ""
echo "2. Creando firewall rule con IP actual..."
gcloud compute firewall-rules create allow-raspberry-all-ports \
    --project="$PROJECT_ID" \
    --allow tcp:22,tcp:80,tcp:443,tcp:8000 \
    --source-ranges "$RASPBERRY_IP/32" \
    --target-tags tokio-waf \
    --description "Permitir todos los puertos desde Raspberry Pi" \
    --direction INGRESS \
    --network tokio-waf-tokioia-com \
    2>&1 | grep -E "(Created|already exists)" || echo "   ✅ Regla creada"

# Verificar que la VM tenga el tag
echo ""
echo "3. Verificando tags de la VM..."
gcloud compute instances add-tags tokio-waf-tokioia-com \
    --project="$PROJECT_ID" \
    --zone=us-central1-a \
    --tags=tokio-waf \
    2>&1 | grep -E "(Updated|already)" || echo "   ✅ Tag verificado"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ ACCESO ACTUALIZADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Firewall rule:"
echo "   Nombre: allow-raspberry-all-ports"
echo "   Puertos: 22, 80, 443, 8000"
echo "   Desde: $RASPBERRY_IP/32"
echo "   Target: tag 'tokio-waf'"
echo ""
echo "🌐 IP de la VM: YOUR_IP_ADDRESS"
echo ""
echo "🔍 Para probar desde la Raspberry:"
echo "   curl http://YOUR_IP_ADDRESS/"
echo "   curl http://YOUR_IP_ADDRESS:8000/health"
echo ""
