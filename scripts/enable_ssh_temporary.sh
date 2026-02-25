#!/bin/bash
# Script para habilitar SSH temporalmente solo desde tus IPs

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
FIREWALL_SSH_NAME="allow-ssh-temp-$(date +%s)"
DURATION_HOURS="${1:-1}"  # Duración en horas (default: 1 hora)

echo "═══════════════════════════════════════════════════════════"
echo "🔓 HABILITANDO SSH TEMPORALMENTE"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Obtener IPs
OSBOXES_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "")
ADDITIONAL_IP="YOUR_IP_ADDRESS"

if [ -z "$OSBOXES_IP" ]; then
    echo "⚠️ No se pudo obtener la IP de osboxes"
    OSBOXES_IP=""
fi

IPS=()
if [ -n "$OSBOXES_IP" ]; then
    IPS+=("$OSBOXES_IP/32")
    echo "   IP de osboxes: $OSBOXES_IP"
fi
if [ -n "$ADDITIONAL_IP" ]; then
    IPS+=("$ADDITIONAL_IP/32")
    echo "   IP adicional: $ADDITIONAL_IP"
fi

SOURCE_RANGES=$(IFS=,; echo "${IPS[*]}")

echo ""
echo "🔧 Creando regla de firewall temporal..."
echo "   Nombre: $FIREWALL_SSH_NAME"
echo "   IPs permitidas: ${IPS[*]}"
echo "   Puerto: 22 (SSH)"
echo "   Duración recomendada: $DURATION_HOURS horas"
echo ""

gcloud compute firewall-rules create "$FIREWALL_SSH_NAME" \
    --project="$PROJECT_ID" \
    --allow tcp:22 \
    --source-ranges="$SOURCE_RANGES" \
    --target-tags="tokio-waf" \
    --description="Temporary SSH access from ${IPS[*]} - REMOVE AFTER USE" \
    --quiet

echo "✅ Regla creada exitosamente"
echo ""
echo "⏰ IMPORTANTE: Esta regla expone el puerto 22 solo a tus IPs"
echo "   Eliminá la regla cuando termines:"
echo "   gcloud compute firewall-rules delete $FIREWALL_SSH_NAME --project=$PROJECT_ID"
echo ""
echo "   O usar el script de limpieza:"
echo "   ./scripts/cleanup_temp_firewalls.sh"
echo ""
echo "🔐 Ahora podés acceder por SSH:"
echo "   gcloud compute ssh tokio-waf-tokioia-com --project=$PROJECT_ID --zone=us-central1-a"
echo ""
