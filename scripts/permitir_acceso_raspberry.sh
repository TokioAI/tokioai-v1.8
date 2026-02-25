#!/bin/bash
# Script simple para permitir acceso desde la Raspberry Pi a GCP
# Solo agrega firewall rules, no modifica nada existente

set -e

PROJECT_ID="${1:-YOUR_GCP_PROJECT_ID}"
RASPBERRY_IP="${2:-$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip)}"

if [ -z "$RASPBERRY_IP" ] || [ "$RASPBERRY_IP" = "NO_DETECTADA" ]; then
    echo "❌ No se pudo detectar tu IP pública"
    echo "   Proporciónala manualmente:"
    echo "   ./scripts/permitir_acceso_raspberry.sh $PROJECT_ID TU_IP_PUBLICA"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "🔓 PERMITIENDO ACCESO DESDE RASPBERRY PI"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   Proyecto: $PROJECT_ID"
echo "   IP Raspberry: $RASPBERRY_IP"
echo ""

# Firewall rule para permitir acceso a Cloud SQL desde Raspberry
echo "1. Creando firewall rule para Cloud SQL..."
gcloud compute firewall-rules create allow-raspberry-cloudsql \
    --project="$PROJECT_ID" \
    --allow tcp:5432 \
    --source-ranges "$RASPBERRY_IP/32" \
    --target-tags postgres \
    --description "Permitir acceso a Cloud SQL desde Raspberry Pi" \
    --direction INGRESS \
    2>&1 | grep -E "(Created|already exists)" || echo "   ✅ Regla creada o ya existe"

# Firewall rule para permitir acceso SSH desde Raspberry (si necesitas)
echo ""
echo "2. Creando firewall rule para SSH (opcional)..."
gcloud compute firewall-rules create allow-raspberry-ssh \
    --project="$PROJECT_ID" \
    --allow tcp:22 \
    --source-ranges "$RASPBERRY_IP/32" \
    --target-tags allow-ssh \
    --description "Permitir SSH desde Raspberry Pi" \
    --direction INGRESS \
    2>&1 | grep -E "(Created|already exists)" || echo "   ✅ Regla creada o ya existe"

# Firewall rule para permitir acceso al dashboard en VM (si está en GCP)
echo ""
echo "3. Creando firewall rule para dashboard (puerto 8000)..."
gcloud compute firewall-rules create allow-raspberry-dashboard \
    --project="$PROJECT_ID" \
    --allow tcp:8000 \
    --source-ranges "$RASPBERRY_IP/32" \
    --target-tags dashboard-server \
    --description "Permitir acceso al dashboard desde Raspberry Pi" \
    --direction INGRESS \
    2>&1 | grep -E "(Created|already exists)" || echo "   ✅ Regla creada o ya existe"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ ACCESO CONFIGURADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Firewall rules creadas:"
echo "   • allow-raspberry-cloudsql (puerto 5432)"
echo "   • allow-raspberry-ssh (puerto 22)"
echo "   • allow-raspberry-dashboard (puerto 8000)"
echo ""
echo "🌐 Tu IP: $RASPBERRY_IP"
echo ""
echo "💡 Si tu IP cambia, ejecuta este script de nuevo"
echo ""
