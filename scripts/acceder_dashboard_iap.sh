#!/bin/bash
# Acceso privado al dashboard WAF vía IAP Tunnel
# NO expone el dashboard públicamente, solo tú puedes acceder

VM_NAME="${1:-tokio-dashboard-private}"
ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"
LOCAL_PORT="${4:-8000}"
DASHBOARD_PORT="${5:-8000}"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 ACCESO PRIVADO AL DASHBOARD WAF"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   VM: $VM_NAME"
echo "   Zona: $ZONE"
echo "   Puerto local: $LOCAL_PORT"
echo "   Dashboard interno: $DASHBOARD_PORT"
echo ""
echo "✅ IAP Tunnel es GRATIS y usa tu autenticación de Google"
echo "✅ El dashboard NO está expuesto públicamente"
echo "✅ Solo tú puedes acceder (autenticado con tu cuenta Google)"
echo ""

# Verificar autenticación
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 > /dev/null 2>&1; then
    echo "⚠️  No estás autenticado en gcloud"
    echo "   Ejecuta: gcloud auth login"
    exit 1
fi

ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1)
echo "🔐 Autenticado como: $ACCOUNT"
echo ""

# Verificar si el puerto está en uso
if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Puerto $LOCAL_PORT en uso. Liberando..."
    lsof -ti:$LOCAL_PORT | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "🔌 Creando túnel IAP seguro..."
echo "   Presiona Ctrl+C para detener"
echo ""

# Crear túnel IAP
gcloud compute start-iap-tunnel "$VM_NAME" "$DASHBOARD_PORT" \
    --zone="$ZONE" \
    --project="$PROJECT_ID" \
    --listen-on-stdin \
    --local-host-port="localhost:$LOCAL_PORT"

# El túnel se mantiene activo hasta Ctrl+C
# Una vez activo, abre: http://localhost:8000/
