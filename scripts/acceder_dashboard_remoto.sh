#!/bin/bash
# Script para acceder al dashboard remotamente sin interfaz gráfica
# Crea un túnel SSH desde la Raspberry hacia la VM de GCP

VM_IP="YOUR_IP_ADDRESS"
VM_NAME="tokio-waf-tokioia-com"
VM_ZONE="us-central1-a"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
LOCAL_PORT="${1:-8000}"
DASHBOARD_PORT="${2:-8000}"

echo "═══════════════════════════════════════════════════════════"
echo "🌐 ACCESO REMOTO AL DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   VM: $VM_NAME ($VM_IP)"
echo "   Puerto local: $LOCAL_PORT"
echo "   Dashboard en VM: $DASHBOARD_PORT"
echo ""

# Verificar si el puerto está en uso
if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Puerto $LOCAL_PORT en uso. Liberando..."
    lsof -ti:$LOCAL_PORT | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "🔌 Creando túnel SSH..."
echo "   Puerto local $LOCAL_PORT -> $VM_IP:$DASHBOARD_PORT"
echo ""

# Crear túnel SSH
ssh -N -L $LOCAL_PORT:localhost:$DASHBOARD_PORT \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    $VM_NAME.$VM_ZONE.$PROJECT_ID@$VM_IP \
    -p 22 &

TUNNEL_PID=$!

echo "✅ Túnel SSH creado (PID: $TUNNEL_PID)"
echo ""
sleep 3

# Verificar que el túnel funciona
if ! kill -0 $TUNNEL_PID 2>/dev/null; then
    echo "❌ Error: El túnel SSH no se pudo crear"
    echo "   Verifica que puedas conectarte por SSH a la VM"
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
    echo "⏹️  Para detener el túnel, presiona Ctrl+C o ejecuta:"
    echo "   kill $TUNNEL_PID"
    echo ""
    
    # Esperar
    trap "echo ''; echo '🛑 Deteniendo túnel...'; kill $TUNNEL_PID 2>/dev/null; exit 0" INT TERM
    
    echo "⏳ Túnel activo. Presiona Ctrl+C para detenerlo."
    wait $TUNNEL_PID
else
    echo "⚠️  El túnel se creó pero el dashboard no responde"
    echo "   Verificando estado del dashboard en la VM..."
    kill $TUNNEL_PID 2>/dev/null
    exit 1
fi
