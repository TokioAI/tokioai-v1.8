#!/bin/bash
# Comando rápido para diagnosticar y arreglar el dashboard
# Copiar y pegar en Cloud Shell

gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        
        echo '🔍 DIAGNÓSTICO RÁPIDO'
        echo '===================='
        echo ''
        
        # 1. Verificar dashboard
        echo '1. Dashboard (puerto 8000):'
        if docker ps | grep -q dashboard-api; then
            echo '   ✅ Contenedor corriendo'
            curl -s http://localhost:8000/health && echo ' ✅ Responde' || echo ' ❌ No responde'
        else
            echo '   ❌ Contenedor NO corriendo - Iniciando...'
            docker-compose up -d dashboard-api
            sleep 5
            curl -s http://localhost:8000/health && echo ' ✅ Ahora responde' || echo ' ❌ Sigue sin responder'
        fi
        
        echo ''
        echo '2. Nginx:'
        if ! grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '   ❌ Falta configuración - Agregando...'
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            sed -i '/location \/health {/,/}/a\
    location /dashboard/ { proxy_pass http://localhost:8000/; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }\
    location /api/ { proxy_pass http://localhost:8000/api/; proxy_set_header Host \$host; }\
' nginx-site.conf
            docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
            sleep 3
            echo '   ✅ Configuración agregada'
        else
            echo '   ✅ Configuración existe'
        fi
        
        echo ''
        echo '3. Verificando acceso:'
        curl -s -o /dev/null -w '   /dashboard/: HTTP %{http_code}\n' http://localhost/dashboard/
        
        echo ''
        echo '✅ Diagnóstico completo'
        echo '🌐 Acceder: http://YOUR_IP_ADDRESS/dashboard/'
    "
