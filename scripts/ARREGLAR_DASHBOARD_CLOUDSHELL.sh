#!/bin/bash
# EJECUTAR DESDE CLOUD SHELL: https://shell.cloud.google.com/

gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        
        echo '=== ARREGLANDO DASHBOARD ==='
        
        # 1. Iniciar dashboard
        docker-compose up -d dashboard-api
        sleep 10
        
        # 2. Verificar dashboard
        curl -s http://localhost:8000/health && echo ' ✅ Dashboard OK' || echo ' ❌ Dashboard no responde'
        
        # 3. Arreglar nginx
        echo ''
        echo 'Configurando nginx...'
        
        # Eliminar configuración vieja
        sed -i '/location \/dashboard\/ {/,/^    }$/d' nginx-site.conf
        
        # Agregar configuración correcta
        sed -i '/location \/health {/,/}/a\
    location /dashboard/ { proxy_pass http://localhost:8000/; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }\
' nginx-site.conf
        
        # Reiniciar nginx
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
        
        sleep 5
        
        # Verificar
        curl -s http://localhost/dashboard/health && echo ' ✅ Nginx OK' || echo ' ❌ Nginx no funciona'
        
        echo ''
        echo '✅ COMPLETADO'
        echo 'Dashboard: https://YOUR_IP_ADDRESS/dashboard/'
    "
