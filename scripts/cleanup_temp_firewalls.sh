#!/bin/bash
# Script para limpiar reglas de firewall temporales

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"

echo "🧹 Limpiando reglas de firewall temporales..."

# Buscar reglas temporales
SSH_RULES=$(gcloud compute firewall-rules list \
    --project="$PROJECT_ID" \
    --filter="name~allow-ssh-temp" \
    --format="value(name)" 2>/dev/null)

DASHBOARD_RULES=$(gcloud compute firewall-rules list \
    --project="$PROJECT_ID" \
    --filter="name~allow-dashboard-temp" \
    --format="value(name)" 2>/dev/null)

ALL_RULES="$SSH_RULES $DASHBOARD_RULES"

if [ -z "$ALL_RULES" ]; then
    echo "✅ No hay reglas temporales para eliminar"
    exit 0
fi

echo ""
echo "Reglas encontradas:"
echo "$ALL_RULES" | grep -v '^$'
echo ""

read -p "¿Eliminar todas estas reglas? (s/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[SsYy]$ ]]; then
    for RULE in $ALL_RULES; do
        if [ -n "$RULE" ]; then
            echo "🗑️ Eliminando: $RULE"
            gcloud compute firewall-rules delete "$RULE" \
                --project="$PROJECT_ID" \
                --quiet 2>/dev/null || true
        fi
    done
    echo ""
    echo "✅ Reglas eliminadas"
else
    echo "❌ Operación cancelada"
fi
