#!/bin/bash
# Script para configurar el servicio de sincronización de bloqueos en el servidor WAF

set -e

NGINX_CONFIG_FILE="/opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf"
SYNC_SCRIPT="/opt/tokio-ai-waf/scripts/sync-blocked-ips-to-nginx.py"
SYNC_LOG="/var/log/block-sync.log"
SYNC_INTERVAL=30  # 30 segundos para procesamiento rápido

echo "🔧 Configurando servicio de sincronización de bloqueos..."

# Crear directorio para scripts si no existe
mkdir -p /opt/tokio-ai-waf/scripts

# Crear archivo de configuración para el servicio
cat > /etc/systemd/system/block-sync.service << EOF
[Unit]
Description=Sync Blocked IPs from PostgreSQL to Nginx
After=network.target postgresql.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/tokio-ai-waf/scripts
ExecStart=/usr/bin/python3 ${SYNC_SCRIPT}
StandardOutput=append:${SYNC_LOG}
StandardError=append:${SYNC_LOG}
Environment="POSTGRES_HOST=YOUR_IP_ADDRESS"
Environment="POSTGRES_IP=YOUR_IP_ADDRESS"
Environment="POSTGRES_PORT=5432"
Environment="POSTGRES_DB=soc_ai"
Environment="POSTGRES_USER=soc_user"
Environment="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}"
Environment="NGINX_BLOCKED_IPS_FILE=${NGINX_CONFIG_FILE}"
Environment="NGINX_RELOAD_COMMAND=docker exec tokio-ai-modsecurity nginx -s reload"
Environment="NGINX_RELOAD_MIN_INTERVAL=10"
Environment="MAX_IPS_PER_BATCH=1000"

[Install]
WantedBy=multi-user.target
EOF

# Crear un timer para ejecutar periódicamente (alternativa al servicio continuo)
cat > /etc/systemd/system/block-sync.timer << EOF
[Unit]
Description=Timer for Block Sync Service
Requires=block-sync.service

[Timer]
OnBootSec=30s
OnUnitActiveSec=${SYNC_INTERVAL}s
Unit=block-sync.service

[Install]
WantedBy=timers.target
EOF

# Recargar systemd
systemctl daemon-reload

# Habilitar y empezar el timer
systemctl enable block-sync.timer
systemctl start block-sync.timer

echo "✅ Servicio de sincronización configurado"
echo "   Timer: cada ${SYNC_INTERVAL} segundos"
echo "   Log: ${SYNC_LOG}"
echo ""
echo "Comandos útiles:"
echo "  sudo systemctl status block-sync.timer"
echo "  sudo journalctl -u block-sync.service -f"
echo "  sudo systemctl restart block-sync.timer"


