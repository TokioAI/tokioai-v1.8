#!/bin/bash
# Script para agregar ruta del dashboard a nginx en la VM
# Ejecutar desde Cloud Shell o desde una máquina con acceso a la VM

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"

echo "═══════════════════════════════════════════════════════════"
echo "🔧 AGREGANDO RUTA DEL DASHBOARD A NGINX"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Configuración a agregar
DASHBOARD_CONFIG='
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

echo "📋 Ejecutando en la VM: $VM_NAME"
echo ""

# Ejecutar en la VM
gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --tunnel-through-iap \
    --command="
        cd /opt/tokio-waf
        
        # Verificar si ya existe la ruta del dashboard
        if grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '⚠️ La ruta /dashboard/ ya existe en nginx-site.conf'
            echo '   Verificando configuración...'
            grep -A 10 'location /dashboard/' nginx-site.conf
        else
            echo '📝 Agregando ruta del dashboard a nginx-site.conf...'
            
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración antes de 'location /'
            # Buscar el bloque server y agregar antes de location /
            sed -i '/location \/health {/,/}/a\
'"$DASHBOARD_CONFIG"'
            ' nginx-site.conf
            
            echo '✅ Configuración agregada'
        fi
        
        # Reiniciar nginx
        echo ''
        echo '🔄 Reiniciando contenedor nginx...'
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy 2>/dev/null || echo '⚠️ No se pudo reiniciar (verificar nombre del contenedor)'
        
        echo ''
        echo '✅ Proceso completado'
        echo ''
        echo '📋 Verificar que funcione:'
        echo '   curl http://localhost/dashboard/'
    " 2>&1 || {
    echo ""
    echo "❌ Error: No se pudo acceder a la VM por SSH"
    echo ""
    echo "💡 ALTERNATIVAS:"
    echo ""
    echo "1. Usar GCP Console (Compute Engine > SSH):"
    echo "   - Ir a: https://console.cloud.google.com/compute/instances"
    echo "   - Hacer clic en 'SSH' en la VM"
    echo "   - Ejecutar los comandos manualmente"
    echo ""
    echo "2. O acceder directamente al puerto 8000:"
    echo "   http://YOUR_IP_ADDRESS:8000"
    echo "   (La regla de firewall ya está creada)"
    echo ""
    exit 1
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ NGINX ACTUALIZADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard disponible en:"
echo "   👉 http://YOUR_IP_ADDRESS/dashboard/"
echo "   👉 https://tokioia.com/dashboard/ (si tenés SSL)"
echo ""
echo "🔍 Verificar:"
echo "   curl -I http://YOUR_IP_ADDRESS/dashboard/"
echo ""
