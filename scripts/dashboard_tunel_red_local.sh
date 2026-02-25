#!/bin/bash
# Script para crear un túnel que expone el dashboard de GCP en la IP local de la Raspberry
# Permite acceder a YOUR_IP_ADDRESS:8000 y ver el dashboard de GCP

VM_IP="YOUR_IP_ADDRESS"
VM_NAME="tokio-waf-tokioia-com"
VM_ZONE="us-central1-a"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
LOCAL_PORT="8000"
DASHBOARD_PORT="8000"
USER=$(whoami)

echo "═══════════════════════════════════════════════════════════"
echo "🌐 CONFIGURANDO TÚNEL PARA DASHBOARD EN RED LOCAL"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   Dashboard GCP: $VM_IP:$DASHBOARD_PORT"
echo "   Acceso local: YOUR_IP_ADDRESS:$LOCAL_PORT"
echo ""

# Verificar que gcloud está configurado
if ! command -v gcloud > /dev/null 2>&1; then
    echo "❌ Error: gcloud no está instalado"
    echo "   Instala: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Verificar que podemos conectarnos a la VM
echo "1. Verificando conectividad con la VM..."
if ! gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --command="echo 'OK'" 2>&1 | grep -q "OK"; then
    echo "   ⚠️  No se pudo conectar a la VM"
    echo "   Verifica que tengas acceso SSH configurado"
    echo "   Prueba: gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID"
    exit 1
fi
echo "   ✅ Conectividad OK"
echo ""

# Crear servicio systemd
SERVICE_FILE="/etc/systemd/system/tokio-dashboard-tunnel.service"

echo "2. Creando servicio systemd..."

# Crear script wrapper para el túnel SSH
WRAPPER_SCRIPT="/usr/local/bin/tokio-dashboard-tunnel.sh"
sudo tee $WRAPPER_SCRIPT > /dev/null << 'EOFSCRIPT'
#!/bin/bash
# Wrapper para el túnel SSH del dashboard
# Escucha en YOUR_IP_ADDRESS para ser accesible desde la red local

VM_IP="YOUR_IP_ADDRESS"
VM_NAME="tokio-waf-tokioia-com"
VM_ZONE="us-central1-a"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
LOCAL_PORT="8000"
DASHBOARD_PORT="8000"

# Usar socat o ssh con bind a todas las interfaces
# Opción 1: Usar ssh con GatewayPorts (requiere configuración SSH)
# Opción 2: Usar socat como proxy
# Opción 3: Usar ssh + redirigir con iptables

# Usar gcloud compute ssh con port forwarding
# Necesitamos que escuche en YOUR_IP_ADDRESS para ser accesible desde la red local
# Usamos socat como proxy para exponer el túnel SSH en todas las interfaces

# Crear túnel SSH en background usando gcloud (escucha en localhost:18000)
# Usamos un puerto intermedio para evitar conflictos
INTERMEDIATE_PORT=18000

# Crear túnel SSH en background
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --ssh-flag="-N -L YOUR_IP_ADDRESS:$INTERMEDIATE_PORT:localhost:$DASHBOARD_PORT" \
    --ssh-flag="-o StrictHostKeyChecking=no" \
    --ssh-flag="-o UserKnownHostsFile=/dev/null" \
    --ssh-flag="-o ServerAliveInterval=60" \
    --ssh-flag="-o ServerAliveCountMax=3" \
    --ssh-flag="-o ExitOnForwardFailure=yes" \
    --quiet > /dev/null 2>&1 &
SSH_PID=$!

# Esperar a que el túnel SSH esté listo
sleep 5

# Verificar que el túnel SSH funciona
if ! kill -0 $SSH_PID 2>/dev/null; then
    echo "Error: No se pudo crear el túnel SSH" >&2
    exit 1
fi

# Verificar que el puerto intermedio está escuchando
if ! ss -tlnp 2>/dev/null | grep -q ":$INTERMEDIATE_PORT"; then
    echo "Error: El túnel SSH no está escuchando en el puerto intermedio" >&2
    kill $SSH_PID 2>/dev/null
    exit 1
fi

# Usar socat para exponer en todas las interfaces (YOUR_IP_ADDRESS)
# fork permite múltiples conexiones simultáneas
socat TCP-LISTEN:$LOCAL_PORT,bind=YOUR_IP_ADDRESS,reuseaddr,fork TCP:YOUR_IP_ADDRESS:$INTERMEDIATE_PORT

# Si socat termina, matar SSH
kill $SSH_PID 2>/dev/null
EOFSCRIPT

sudo chmod +x $WRAPPER_SCRIPT

# Crear servicio systemd
sudo tee $SERVICE_FILE > /dev/null << EOF
[Unit]
Description=Tokio Dashboard Tunnel - Expone dashboard GCP en red local
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=$WRAPPER_SCRIPT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "   ✅ Servicio creado"
echo ""

# Instalar socat si no está instalado (mejor para proxy en todas las interfaces)
echo "3. Verificando dependencias..."
if ! command -v socat > /dev/null 2>&1; then
    echo "   Instalando socat (necesario para proxy en red local)..."
    sudo apt-get update -qq
    sudo apt-get install -y socat
    echo "   ✅ socat instalado"
else
    echo "   ✅ socat ya está instalado"
fi
echo ""

# Habilitar y iniciar servicio
echo "4. Habilitando servicio..."
sudo systemctl daemon-reload
sudo systemctl enable tokio-dashboard-tunnel.service
sudo systemctl start tokio-dashboard-tunnel.service

echo "   ✅ Servicio habilitado e iniciado"
echo ""

# Verificar estado
echo "5. Verificando estado..."
sleep 5
if sudo systemctl is-active --quiet tokio-dashboard-tunnel.service; then
    echo "   ✅ Servicio activo"
else
    echo "   ⚠️  Servicio no está activo, revisando logs..."
    sudo journalctl -u tokio-dashboard-tunnel.service -n 20 --no-pager
    exit 1
fi
echo ""

# Verificar que el puerto está escuchando
echo "6. Verificando que el puerto está escuchando..."
sleep 2
if sudo ss -tlnp | grep -q ":$LOCAL_PORT"; then
    echo "   ✅ Puerto $LOCAL_PORT está escuchando"
    sudo ss -tlnp | grep ":$LOCAL_PORT" | head -1
else
    echo "   ⚠️  Puerto $LOCAL_PORT no está escuchando"
    echo "   Revisando logs..."
    sudo journalctl -u tokio-dashboard-tunnel.service -n 30 --no-pager
fi
echo ""

# Obtener IP local
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo "═══════════════════════════════════════════════════════════"
echo "✅ TÚNEL CONFIGURADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard disponible en:"
echo "   👉 http://$LOCAL_IP:$LOCAL_PORT/"
echo "   👉 http://YOUR_IP_ADDRESS:$LOCAL_PORT/"
echo ""
echo "📋 Comandos útiles:"
echo "   Ver estado: sudo systemctl status tokio-dashboard-tunnel"
echo "   Ver logs: sudo journalctl -u tokio-dashboard-tunnel -f"
echo "   Reiniciar: sudo systemctl restart tokio-dashboard-tunnel"
echo "   Detener: sudo systemctl stop tokio-dashboard-tunnel"
echo ""
echo "🔍 Para probar:"
echo "   curl http://$LOCAL_IP:$LOCAL_PORT/health"
echo ""
