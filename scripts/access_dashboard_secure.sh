#!/bin/bash
# Script para acceder al dashboard del WAF de forma segura mediante SSH tunnel

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
VM_NAME="${1}"
VM_ZONE="${2:-us-central1-a}"
DASHBOARD_PORT="${3:-8000}"
LOCAL_PORT="${4:-18000}"

echo "═══════════════════════════════════════════════════════════"
echo "🔐 ACCESO SEGURO AL DASHBOARD WAF"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Si no se especifica VM, buscar automáticamente
if [ -z "$VM_NAME" ]; then
    echo "🔍 Buscando VM del WAF..."
    VM_NAME=$(gcloud compute instances list \
        --project="$PROJECT_ID" \
        --filter="name~tokio-waf AND status:RUNNING" \
        --format="value(name)" \
        --limit=1 2>/dev/null)
    
    if [ -z "$VM_NAME" ]; then
        echo "❌ No se encontró ninguna VM del WAF en ejecución"
        echo ""
        echo "VMs disponibles:"
        gcloud compute instances list \
            --project="$PROJECT_ID" \
            --filter="name~tokio-waf" \
            --format="table(name,zone,status)"
        exit 1
    fi
    
    # Obtener zona de la VM
    VM_ZONE=$(gcloud compute instances list \
        --project="$PROJECT_ID" \
        --filter="name=$VM_NAME" \
        --format="value(zone)" \
        --limit=1 2>/dev/null)
fi

echo "📋 Configuración:"
echo "   VM: $VM_NAME"
echo "   Zona: $VM_ZONE"
echo "   Dashboard remoto: localhost:$DASHBOARD_PORT"
echo "   Dashboard local: localhost:$LOCAL_PORT"
echo ""

# Verificar si el puerto local ya está en uso
if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️ El puerto local $LOCAL_PORT ya está en uso"
    echo "   Matando proceso existente..."
    kill $(lsof -ti:$LOCAL_PORT) 2>/dev/null || true
    sleep 2
fi

echo "🚀 Creando túnel SSH seguro (GCP IAP)..."
echo ""
echo "   El dashboard estará disponible en:"
echo "   👉 http://localhost:$LOCAL_PORT"
echo ""
echo "   Para detener el túnel, presioná Ctrl+C"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

# Crear túnel SSH con IAP
gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --tunnel-through-iap \
    --ssh-flag="-N -L $LOCAL_PORT:localhost:$DASHBOARD_PORT" \
    --quiet
