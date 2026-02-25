#!/bin/bash
# Script para configurar Nginx como proxy reverso en la Raspberry
# Expone el dashboard en un puerto local accesible desde la red local

VM_IP="YOUR_IP_ADDRESS"
DASHBOARD_PORT="8000"
LOCAL_PORT="${1:-8080}"

echo "═══════════════════════════════════════════════════════════"
echo "🌐 CONFIGURANDO NGINX PROXY PARA DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Instalar nginx si no está instalado
if ! command -v nginx > /dev/null 2>&1; then
    echo "1. Instalando nginx..."
    sudo apt-get update
    sudo apt-get install -y nginx
    echo "   ✅ Nginx instalado"
else
    echo "1. Nginx ya está instalado"
fi
echo ""

# Crear configuración de nginx
echo "2. Creando configuración de nginx..."
NGINX_CONFIG="/etc/nginx/sites-available/tokio-dashboard"

sudo tee $NGINX_CONFIG > /dev/null << EOF
server {
    listen $LOCAL_PORT;
    server_name localhost;

    location / {
        proxy_pass http://$VM_IP:$DASHBOARD_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

echo "   ✅ Configuración creada"
echo ""

# Habilitar sitio
echo "3. Habilitando sitio..."
sudo ln -sf $NGINX_CONFIG /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "   ✅ Nginx configurado"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "✅ NGINX PROXY CONFIGURADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard disponible en:"
echo "   👉 http://localhost:$LOCAL_PORT/"
echo "   👉 http://$(hostname -I | awk '{print $1}'):$LOCAL_PORT/"
echo ""
echo "📋 Comandos útiles:"
echo "   Ver logs: sudo tail -f /var/log/nginx/error.log"
echo "   Reiniciar: sudo systemctl restart nginx"
echo ""
