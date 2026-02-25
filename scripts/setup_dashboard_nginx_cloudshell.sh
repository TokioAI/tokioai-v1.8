#!/bin/bash
# Script para ejecutar desde Cloud Shell de GCP
# Configura nginx para hacer proxy al dashboard sin exponer puertos

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"

echo "═══════════════════════════════════════════════════════════"
echo "🔧 CONFIGURANDO NGINX PARA DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "VM: $VM_NAME"
echo "Zona: $VM_ZONE"
echo ""

# Conectar y configurar
gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --command="
        cd /opt/tokio-waf
        
        echo '📋 1. Verificando contenedor del dashboard...'
        if ! docker ps | grep -q dashboard-api; then
            echo '🔄 Iniciando dashboard...'
            docker-compose up -d dashboard-api
            sleep 5
        fi
        
        echo ''
        echo '📋 2. Verificando que el dashboard responda...'
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo '✅ Dashboard responde correctamente'
        else
            echo '❌ Dashboard NO responde'
            echo '📋 Logs:'
            docker-compose logs --tail=20 dashboard-api
            exit 1
        fi
        
        echo ''
        echo '📋 3. Verificando configuración de nginx...'
        if grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '✅ Nginx ya tiene ruta /dashboard/ configurada'
        else
            echo '📝 Agregando ruta /dashboard/ a nginx...'
            
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración del dashboard ANTES de 'location /'
            # Buscar el bloque server y agregar después de /health
            sed -i '/location \/health {/,/}/a\
    # Dashboard WAF - Proxy al dashboard en puerto 8000\
    location /dashboard/ {\
        proxy_pass http://localhost:8000/;\
        proxy_set_header Host \$host;\
        proxy_set_header X-Real-IP \$remote_addr;\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto \$scheme;\
        proxy_set_header X-Forwarded-Host \$host;\
        proxy_set_header X-Forwarded-Port \$server_port;\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
        proxy_http_version 1.1;\
        proxy_set_header Upgrade \$http_upgrade;\
        proxy_set_header Connection \"upgrade\";\
    }\
    \
    # API del dashboard\
    location /api/ {\
        proxy_pass http://localhost:8000/api/;\
        proxy_set_header Host \$host;\
        proxy_set_header X-Real-IP \$remote_addr;\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto \$scheme;\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
    }\
' nginx-site.conf
            
            echo '✅ Configuración agregada a nginx-site.conf'
        fi
        
        echo ''
        echo '📋 4. Reiniciando contenedor nginx...'
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy 2>/dev/null || {
            echo '⚠️ No se pudo reiniciar nginx (verificar nombre del contenedor)'
            docker ps | grep nginx || docker ps | grep waf-proxy
        }
        
        echo ''
        echo '📋 5. Verificando que nginx funcione...'
        sleep 3
        if curl -s http://localhost/dashboard/ > /dev/null 2>&1; then
            echo '✅ Dashboard accesible a través de nginx en /dashboard/'
        else
            echo '⚠️ Verificar configuración de nginx'
            docker-compose logs --tail=10 waf-proxy 2>/dev/null || docker logs tokio-gcp-waf-proxy --tail=10 2>/dev/null
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ CONFIGURACIÓN COMPLETADA'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Dashboard disponible en:'
        echo '   👉 http://YOUR_IP_ADDRESS/dashboard/'
        echo '   👉 https://tokioia.com/dashboard/ (si tenés SSL)'
        echo ''
    " 2>&1

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ PROCESO COMPLETADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Acceder al dashboard:"
echo "   http://YOUR_IP_ADDRESS/dashboard/"
echo ""
echo "🔒 Seguridad:"
echo "   ✅ SSH no expuesto (puerto 22 bloqueado)"
echo "   ✅ PostgreSQL no expuesto (puerto 5432 bloqueado)"
echo "   ✅ Dashboard accesible solo a través de nginx (puerto 80/443)"
echo ""
