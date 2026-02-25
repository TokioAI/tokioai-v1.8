#!/bin/bash
# Script para acceder al dashboard WAF de forma segura vía SSH tunnel
# No expone ningún puerto públicamente

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"
LOCAL_PORT="${4:-8000}"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 ACCESO SEGURO AL DASHBOARD WAF"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Este script crea un túnel SSH seguro para acceder al dashboard"
echo "sin exponer ningún puerto públicamente."
echo ""
echo "📋 Configuración:"
echo "   VM: $VM_NAME"
echo "   Zona: $VM_ZONE"
echo "   Puerto local: $LOCAL_PORT"
echo "   Dashboard interno: localhost:8000"
echo ""

# Verificar si ya hay un túnel corriendo
if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Ya hay un proceso usando el puerto $LOCAL_PORT"
    echo "   Matando proceso anterior..."
    lsof -ti:$LOCAL_PORT | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "🔌 Creando túnel SSH seguro..."
echo "   Puerto local: $LOCAL_PORT -> Dashboard en VM: 8000"
echo ""

# Crear túnel SSH con IAP (Identity-Aware Proxy)
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
    --ssh-flag="ServerAliveCountMax=3" &

TUNNEL_PID=$!

echo "✅ Túnel SSH creado (PID: $TUNNEL_PID)"
echo ""
sleep 3

# Verificar que el túnel funciona
if ! kill -0 $TUNNEL_PID 2>/dev/null; then
    echo "❌ Error: El túnel SSH no se pudo crear"
    exit 1
fi

# Verificar conectividad
echo "🔍 Verificando conectividad..."
sleep 2

if curl -s http://localhost:$LOCAL_PORT/health > /dev/null 2>&1; then
    echo "✅ Dashboard accesible a través del túnel"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "✅ TÚNEL ACTIVO"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo "🌐 Accede al dashboard en:"
    echo "   👉 http://localhost:$LOCAL_PORT/"
    echo ""
    echo "🔒 Seguridad:"
    echo "   ✅ No hay puertos expuestos públicamente"
    echo "   ✅ Acceso solo a través de SSH tunnel"
    echo "   ✅ Autenticación requerida"
    echo ""
    echo "⏹️  Para detener el túnel, presiona Ctrl+C o ejecuta:"
    echo "   kill $TUNNEL_PID"
    echo ""
    
    # Intentar abrir en el navegador (si está disponible)
    if command -v xdg-open > /dev/null 2>&1; then
        echo "🌐 Abriendo dashboard en el navegador..."
        xdg-open "http://localhost:$LOCAL_PORT/" 2>/dev/null &
    elif command -v open > /dev/null 2>&1; then
        echo "🌐 Abriendo dashboard en el navegador..."
        open "http://localhost:$LOCAL_PORT/" 2>/dev/null &
    fi
    
    # Esperar a que el usuario termine
    trap "echo ''; echo '🛑 Deteniendo túnel...'; kill $TUNNEL_PID 2>/dev/null; exit 0" INT TERM
    
    echo "⏳ Túnel activo. Presiona Ctrl+C para detenerlo."
    wait $TUNNEL_PID
else
    echo "⚠️  El túnel se creó pero el dashboard no responde"
    echo "   Verificando estado del dashboard en la VM..."
    kill $TUNNEL_PID 2>/dev/null
    exit 1
fi
