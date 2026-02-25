#!/bin/bash
# Script para actualizar nginx en la VM y agregar ruta del dashboard

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"

echo "═══════════════════════════════════════════════════════════"
echo "🔧 ACTUALIZANDO NGINX PARA DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Verificar que la VM existe
echo "Verificando VM..."
gcloud compute instances describe "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --format="value(name,status)" > /dev/null 2>&1 || {
    echo "❌ VM no encontrada: $VM_NAME"
    exit 1
}

echo "✅ VM encontrada: $VM_NAME"
echo ""

# Crear configuración de nginx para dashboard
NGINX_DASHBOARD_CONFIG='
    # Dashboard WAF - Proxy al dashboard en puerto 8000
    location /dashboard/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # API del dashboard
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
'

echo "📝 Configuración del dashboard:"
echo "$NGINX_DASHBOARD_CONFIG"
echo ""

echo "⚠️ NOTA: Este script requiere acceso SSH a la VM."
echo "   Como el puerto 22 está bloqueado, necesitás:"
echo "   1. Habilitar IAP en GCP Console"
echo "   2. O usar Cloud Console para editar el archivo manualmente"
echo ""
echo "📋 Archivo a editar en la VM:"
echo "   /opt/tokio-waf/nginx-site.conf"
echo ""
echo "💡 ALTERNATIVA: Acceder directamente al puerto 8000"
echo "   La regla de firewall ya está creada."
echo "   Accedé a: http://YOUR_IP_ADDRESS:8000"
echo ""
