#!/bin/bash
# Script para crear un servicio systemd que expone el dashboard
# Permite acceder al dashboard sin interfaz gráfica

VM_IP="YOUR_IP_ADDRESS"
VM_NAME="tokio-waf-tokioia-com"
VM_ZONE="us-central1-a"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
LOCAL_PORT="8000"
DASHBOARD_PORT="8000"
USER=$(whoami)

echo "═══════════════════════════════════════════════════════════"
echo "🔧 CONFIGURANDO SERVICIO PARA DASHBOARD REMOTO"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Crear servicio systemd
SERVICE_FILE="/etc/systemd/system/tokio-dashboard-tunnel.service"

echo "1. Creando servicio systemd..."

sudo tee $SERVICE_FILE > /dev/null << EOF
[Unit]
Description=Tokio Dashboard SSH Tunnel
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=/usr/bin/gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID --ssh-flag="-N -L $LOCAL_PORT:localhost:$DASHBOARD_PORT" --ssh-flag="-o StrictHostKeyChecking=no" --ssh-flag="-o UserKnownHostsFile=/dev/null" --ssh-flag="-o ServerAliveInterval=60" --ssh-flag="-o ServerAliveCountMax=3"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "   ✅ Servicio creado"
echo ""

# Habilitar y iniciar servicio
echo "2. Habilitando servicio..."
sudo systemctl daemon-reload
sudo systemctl enable tokio-dashboard-tunnel.service
sudo systemctl start tokio-dashboard-tunnel.service

echo "   ✅ Servicio habilitado e iniciado"
echo ""

# Verificar estado
echo "3. Verificando estado..."
sleep 3
sudo systemctl status tokio-dashboard-tunnel.service --no-pager | head -10

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ SERVICIO CONFIGURADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard disponible en:"
echo "   👉 http://localhost:$LOCAL_PORT/"
echo ""
echo "📋 Comandos útiles:"
echo "   Ver estado: sudo systemctl status tokio-dashboard-tunnel"
echo "   Ver logs: sudo journalctl -u tokio-dashboard-tunnel -f"
echo "   Reiniciar: sudo systemctl restart tokio-dashboard-tunnel"
echo "   Detener: sudo systemctl stop tokio-dashboard-tunnel"
echo ""
