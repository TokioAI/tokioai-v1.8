#!/bin/bash
# Script completo para diagnosticar y arreglar el dashboard
# Ejecutar desde Cloud Shell de GCP

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"

echo "═══════════════════════════════════════════════════════════"
echo "🔍 DIAGNÓSTICO Y REPARACIÓN DEL DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""

gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --command="
        cd /opt/tokio-waf
        
        echo '═══════════════════════════════════════════════════════════'
        echo '1. VERIFICANDO CONTENEDORES'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E '(dashboard|nginx|waf-proxy)' || echo '⚠️ No se encontraron contenedores relevantes'
        echo ''
        
        echo '═══════════════════════════════════════════════════════════'
        echo '2. VERIFICANDO DASHBOARD (puerto 8000)'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        
        # Verificar si el dashboard está corriendo
        if docker ps | grep -q dashboard-api; then
            echo '✅ Contenedor dashboard-api está corriendo'
            DASHBOARD_STATUS=\$(docker ps --filter name=dashboard-api --format '{{.Status}}')
            echo \"   Estado: \$DASHBOARD_STATUS\"
        else
            echo '❌ Contenedor dashboard-api NO está corriendo'
            echo '🔄 Iniciando dashboard-api...'
            docker-compose up -d dashboard-api
            sleep 5
        fi
        
        echo ''
        echo '📋 Verificando que el dashboard responda internamente...'
        if curl -s http://localhost:8000/health | grep -q 'healthy\|ok'; then
            echo '✅ Dashboard responde en /health'
            curl -s http://localhost:8000/health
        else
            echo '❌ Dashboard NO responde en /health'
            echo '📋 Logs del dashboard:'
            docker-compose logs --tail=30 dashboard-api
            echo ''
            echo '⚠️ Intentando reiniciar el dashboard...'
            docker-compose restart dashboard-api
            sleep 5
            if curl -s http://localhost:8000/health | grep -q 'healthy\|ok'; then
                echo '✅ Dashboard ahora responde'
            else
                echo '❌ Dashboard sigue sin responder. Verificar logs arriba.'
            fi
        fi
        
        echo ''
        echo '📋 Verificando ruta raíz del dashboard...'
        ROOT_RESPONSE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/)
        echo \"   Código HTTP: \$ROOT_RESPONSE\"
        if [ \"\$ROOT_RESPONSE\" = \"200\" ] || [ \"\$ROOT_RESPONSE\" = \"302\" ]; then
            echo '✅ Dashboard responde en /'
        else
            echo '⚠️ Dashboard no responde correctamente en /'
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '3. VERIFICANDO NGINX'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        
        # Verificar nginx
        if docker ps | grep -q waf-proxy; then
            echo '✅ Contenedor nginx (waf-proxy) está corriendo'
        else
            echo '❌ Contenedor nginx NO está corriendo'
            docker-compose up -d waf-proxy
            sleep 3
        fi
        
        echo ''
        echo '📋 Verificando configuración de nginx...'
        if [ -f nginx-site.conf ]; then
            echo '✅ Archivo nginx-site.conf existe'
            
            # Verificar si tiene la ruta /dashboard/
            if grep -q 'location /dashboard/' nginx-site.conf; then
                echo '✅ Nginx tiene ruta /dashboard/ configurada'
                echo ''
                echo '📋 Configuración actual de /dashboard/:'
                grep -A 15 'location /dashboard/' nginx-site.conf | head -20
            else
                echo '❌ Nginx NO tiene ruta /dashboard/ configurada'
                echo '🔄 Agregando configuración...'
                
                # Crear backup
                cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
                
                # Agregar configuración ANTES de 'location /'
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
                
                echo '✅ Configuración agregada'
                
                # Reiniciar nginx
                echo '🔄 Reiniciando nginx...'
                docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
                sleep 3
            fi
        else
            echo '❌ Archivo nginx-site.conf NO existe'
            echo '⚠️ Verificar estructura del proyecto'
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '4. VERIFICANDO ACCESO A TRAVÉS DE NGINX'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        
        echo '📋 Verificando /dashboard/ a través de nginx...'
        NGINX_RESPONSE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost/dashboard/ 2>/dev/null || echo '000')
        echo \"   Código HTTP: \$NGINX_RESPONSE\"
        
        if [ \"\$NGINX_RESPONSE\" = \"200\" ] || [ \"\$NGINX_RESPONSE\" = \"302\" ]; then
            echo '✅ Dashboard accesible a través de nginx en /dashboard/'
        else
            echo '❌ Dashboard NO accesible a través de nginx'
            echo '📋 Verificando logs de nginx...'
            docker-compose logs --tail=20 waf-proxy 2>/dev/null || docker logs tokio-gcp-waf-proxy --tail=20 2>/dev/null
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '5. VERIFICANDO RUTAS ESPECÍFICAS'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        
        echo '📋 /dashboard/health:'
        curl -s http://localhost/dashboard/health | head -c 100 || echo '❌ No responde'
        echo ''
        echo ''
        echo '📋 /dashboard/login:'
        curl -s -o /dev/null -w '%{http_code}' http://localhost/dashboard/login
        echo ''
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ DIAGNÓSTICO COMPLETADO'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Dashboard debería estar disponible en:'
        echo '   👉 http://YOUR_IP_ADDRESS/dashboard/'
        echo '   👉 https://tokioia.com/dashboard/ (si tenés SSL)'
        echo ''
        echo '📝 Si aún no funciona, verificar:'
        echo '   1. Logs del dashboard: docker-compose logs dashboard-api'
        echo '   2. Logs de nginx: docker-compose logs waf-proxy'
        echo '   3. Configuración de nginx: cat nginx-site.conf | grep -A 10 dashboard'
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
