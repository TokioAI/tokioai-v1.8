#!/bin/bash
# Script para acceder al dashboard desde Cloud Shell
# Ejecutar desde: https://shell.cloud.google.com/

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"
LOCAL_PORT="${4:-8000}"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 ACCESO SEGURO AL DASHBOARD DESDE CLOUD SHELL"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Este script crea un túnel SSH seguro desde Cloud Shell"
echo "y abre el dashboard en una ventana del navegador."
echo ""
echo "📋 Configuración:"
echo "   VM: $VM_NAME"
echo "   Zona: $VM_ZONE"
echo "   Puerto local: $LOCAL_PORT"
echo ""

# Verificar que estamos en Cloud Shell
if [ -z "$CLOUD_SHELL" ] && [ -z "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "⚠️  Advertencia: No parece que estés en Cloud Shell"
    echo "   Este script está optimizado para Cloud Shell"
    echo ""
fi

echo "🔌 Creando túnel SSH seguro..."
echo ""

# Crear túnel SSH en background
gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --ssh-flag="-N" \
    --ssh-flag="-L" \
    --ssh-flag="$LOCAL_PORT:localhost:8000" \
    --ssh-flag="-o" \
    --ssh-flag="ExitOnForwardFailure=yes" \
    --ssh-flag="-o" \
    --ssh-flag="ServerAliveInterval=60" \
    --ssh-flag="-o" \
    --ssh-flag="ServerAliveCountMax=3" > /dev/null 2>&1 &

TUNNEL_PID=$!

echo "✅ Túnel SSH creado (PID: $TUNNEL_PID)"
echo ""
sleep 3

# Verificar conectividad
echo "🔍 Verificando conectividad..."
if curl -s http://localhost:$LOCAL_PORT/health > /dev/null 2>&1; then
    echo "✅ Dashboard accesible"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "✅ TÚNEL ACTIVO"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo "🌐 Accede al dashboard en:"
    echo "   👉 http://localhost:$LOCAL_PORT/"
    echo ""
    echo "💡 En Cloud Shell, puedes usar 'Cloud Shell Web Preview'"
    echo "   para abrir el dashboard en una nueva ventana."
    echo ""
    echo "⏹️  Para detener el túnel, ejecuta:"
    echo "   kill $TUNNEL_PID"
    echo ""
    
    # En Cloud Shell, usar el web preview
    if command -v cloudshell > /dev/null 2>&1; then
        echo "🌐 Abriendo dashboard en Cloud Shell Web Preview..."
        cloudshell open http://localhost:$LOCAL_PORT/ 2>/dev/null || echo "   Usa el botón 'Web Preview' en Cloud Shell"
    fi
    
    # Esperar
    trap "echo ''; echo '🛑 Deteniendo túnel...'; kill $TUNNEL_PID 2>/dev/null; exit 0" INT TERM
    
    echo "⏳ Túnel activo. Presiona Ctrl+C para detenerlo."
    wait $TUNNEL_PID
else
    echo "❌ El túnel se creó pero el dashboard no responde"
    kill $TUNNEL_PID 2>/dev/null
    exit 1
fi
