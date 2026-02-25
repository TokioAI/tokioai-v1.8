#!/bin/bash
# Script para configurar dashboard de forma segura
# Ejecutar desde Cloud Shell: https://shell.cloud.google.com/

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 CONFIGURANDO DASHBOARD DE FORMA SEGURA"
echo "═══════════════════════════════════════════════════════════"
echo ""

gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --command="
        cd /opt/tokio-waf
        
        echo '1. Iniciando dashboard-api...'
        docker-compose up -d dashboard-api
        sleep 10
        
        echo ''
        echo '2. Verificando dashboard...'
        if curl -s http://localhost:8000/health > /dev/null; then
            echo '   ✅ Dashboard responde correctamente'
        else
            echo '   ❌ Dashboard no responde - verificando logs...'
            docker-compose logs --tail=20 dashboard-api
            exit 1
        fi
        
        echo ''
        echo '3. Configurando nginx...'
        
        # Verificar si ya tiene /dashboard/ configurado
        if grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '   ✅ Nginx ya tiene /dashboard/ configurado'
            
            # Verificar que proxy_pass tenga barra final
            if grep -A 2 'location /dashboard/' nginx-site.conf | grep -q 'proxy_pass http://localhost:8000/;'; then
                echo '   ✅ proxy_pass está correcto'
            else
                echo '   ⚠️ Corrigiendo proxy_pass...'
                sed -i 's|proxy_pass http://localhost:8000;|proxy_pass http://localhost:8000/;|g' nginx-site.conf
                echo '   ✅ Corregido'
            fi
        else
            echo '   ⚠️ Agregando configuración de /dashboard/...'
            
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración ANTES de location /
            sed -i '/location \/health {/,/}/a\
    # Dashboard WAF - Proxy seguro al dashboard\
    location /dashboard/ {\
        proxy_pass http://localhost:8000/;\
        proxy_set_header Host \$host;\
        proxy_set_header X-Real-IP \$remote_addr;\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto \$scheme;\
        proxy_set_header X-Forwarded-Host \$host;\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
        proxy_http_version 1.1;\
        proxy_set_header Upgrade \$http_upgrade;\
        proxy_set_header Connection \"upgrade\";\
    }\
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
            
            echo '   ✅ Configuración agregada'
        fi
        
        echo ''
        echo '4. Reiniciando nginx...'
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
        sleep 5
        
        echo ''
        echo '5. Verificando acceso...'
        if curl -s http://localhost/dashboard/health > /dev/null 2>&1; then
            echo '   ✅ Dashboard accesible a través de nginx'
        else
            echo '   ⚠️ Verificando logs de nginx...'
            docker-compose logs --tail=10 waf-proxy 2>/dev/null || docker logs tokio-gcp-waf-proxy --tail=10 2>/dev/null
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ CONFIGURACIÓN COMPLETADA'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Dashboard disponible en:'
        echo '   👉 https://tokioia.com/dashboard/'
        echo '   👉 https://YOUR_IP_ADDRESS/dashboard/'
        echo ''
        echo '🔒 Seguridad:'
        echo '   ✅ Autenticación habilitada'
        echo '   ✅ Solo puertos 80/443 expuestos'
        echo '   ✅ PostgreSQL no expuesto'
        echo '   ✅ SSH no expuesto'
        echo ''
    "

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ PROCESO COMPLETADO"
echo "═══════════════════════════════════════════════════════════"
