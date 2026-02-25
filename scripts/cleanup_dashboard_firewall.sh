#!/bin/bash
# Script para limpiar reglas de firewall temporales del dashboard

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"

echo "🧹 Limpiando reglas de firewall temporales del dashboard..."

RULES=$(gcloud compute firewall-rules list \
    --project="$PROJECT_ID" \
    --filter="name~allow-dashboard-temp" \
    --format="value(name)" 2>/dev/null)

if [ -z "$RULES" ]; then
    echo "✅ No hay reglas temporales para eliminar"
    exit 0
fi

echo ""
echo "Reglas encontradas:"
echo "$RULES"
echo ""

read -p "¿Eliminar todas estas reglas? (s/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[SsYy]$ ]]; then
    for RULE in $RULES; do
        echo "🗑️ Eliminando: $RULE"
        gcloud compute firewall-rules delete "$RULE" \
            --project="$PROJECT_ID" \
            --quiet 2>/dev/null || true
    done
    echo ""
    echo "✅ Reglas eliminadas"
else
    echo "❌ Operación cancelada"
fi
