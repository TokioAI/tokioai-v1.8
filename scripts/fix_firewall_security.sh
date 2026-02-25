#!/bin/bash
# Script para eliminar puerto 22 del firewall de GCP WAF

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
FIREWALL_NAME="${1:-tokio-waf-allow-tokioia-com}"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 ACTUALIZANDO FIREWALL - ELIMINANDO PUERTO 22"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Proyecto: $PROJECT_ID"
echo "Firewall: $FIREWALL_NAME"
echo ""

# Verificar que gcloud esté instalado
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: gcloud CLI no está instalado"
    echo "   Instalá gcloud CLI o usá el código Python directamente"
    exit 1
fi

# Verificar firewall actual
echo "📋 Verificando firewall actual..."
gcloud compute firewall-rules describe "$FIREWALL_NAME" \
    --project="$PROJECT_ID" \
    --format="value(allowed[].ports)" 2>/dev/null || {
    echo "⚠️ Firewall '$FIREWALL_NAME' no encontrado"
    echo ""
    echo "Buscando firewalls relacionados..."
    gcloud compute firewall-rules list \
        --project="$PROJECT_ID" \
        --filter="name~tokio-waf" \
        --format="table(name,allowed[].ports,sourceRanges.list())"
    exit 1
}

echo ""
echo "🔧 Actualizando firewall para eliminar puerto 22..."
echo "   Manteniendo solo puertos 80 y 443"
echo ""

# Actualizar firewall: eliminar puerto 22, mantener solo 80 y 443
gcloud compute firewall-rules update "$FIREWALL_NAME" \
    --project="$PROJECT_ID" \
    --allow tcp:80,tcp:443 \
    --source-ranges="YOUR_IP_ADDRESS/0,YOUR_IP_ADDRESS/16,YOUR_IP_ADDRESS/22" \
    --target-tags="tokio-waf" \
    --quiet

echo ""
echo "✅ Firewall actualizado exitosamente"
echo ""
echo "📋 Verificando configuración final..."
gcloud compute firewall-rules describe "$FIREWALL_NAME" \
    --project="$PROJECT_ID" \
    --format="table(name,allowed[].ports,sourceRanges.list(),targetTags.list())"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ SEGURIDAD CORREGIDA"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🔒 Puertos públicos permitidos:"
echo "   - 80: HTTP"
echo "   - 443: HTTPS"
echo ""
echo "🚫 Puertos eliminados:"
echo "   - 22: SSH (ya no accesible desde Internet)"
echo "   - 5432: PostgreSQL (solo interno)"
echo "   - 8000: Dashboard (solo interno)"
echo ""
echo "🔐 Para acceder por SSH, usar GCP IAP:"
echo "   gcloud compute ssh VM_NAME --zone=ZONE --tunnel-through-iap"
echo ""
