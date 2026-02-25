#!/bin/bash
# Script para acceder al dashboard en background y abrir en el navegador

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
VM_NAME="${1}"
VM_ZONE="${2:-us-central1-a}"
DASHBOARD_PORT="${3:-8000}"
LOCAL_PORT="${4:-18000}"

# Si no se especifica VM, buscar automáticamente
if [ -z "$VM_NAME" ]; then
    VM_NAME=$(gcloud compute instances list \
        --project="$PROJECT_ID" \
        --filter="name~tokio-waf AND status:RUNNING" \
        --format="value(name)" \
        --limit=1 2>/dev/null)
    
    if [ -z "$VM_NAME" ]; then
        echo "❌ No se encontró ninguna VM del WAF"
        exit 1
    fi
    
    VM_ZONE=$(gcloud compute instances list \
        --project="$PROJECT_ID" \
        --filter="name=$VM_NAME" \
        --format="value(zone)" \
        --limit=1 2>/dev/null)
fi

# Verificar si ya hay un túnel corriendo
if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    PID=$(lsof -ti:$LOCAL_PORT)
    echo "✅ Túnel ya está corriendo (PID: $PID)"
    echo "   Dashboard: http://localhost:$LOCAL_PORT"
    exit 0
fi

echo "🚀 Iniciando túnel SSH en background..."
echo "   Dashboard: http://localhost:$LOCAL_PORT"
echo ""

# Crear túnel en background
nohup gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --tunnel-through-iap \
    --ssh-flag="-N -L $LOCAL_PORT:localhost:$DASHBOARD_PORT" \
    --quiet > /tmp/dashboard-tunnel.log 2>&1 &

TUNNEL_PID=$!
sleep 3

# Verificar que el túnel esté funcionando
if kill -0 $TUNNEL_PID 2>/dev/null; then
    echo "✅ Túnel iniciado (PID: $TUNNEL_PID)"
    echo "   Dashboard: http://localhost:$LOCAL_PORT"
    echo "   Logs: /tmp/dashboard-tunnel.log"
    echo ""
    echo "Para detener: kill $TUNNEL_PID"
    
    # Intentar abrir en el navegador
    if command -v xdg-open &> /dev/null; then
        xdg-open "http://localhost:$LOCAL_PORT" 2>/dev/null &
    elif command -v open &> /dev/null; then
        open "http://localhost:$LOCAL_PORT" 2>/dev/null &
    fi
else
    echo "❌ Error iniciando túnel. Ver logs: /tmp/dashboard-tunnel.log"
    exit 1
fi
