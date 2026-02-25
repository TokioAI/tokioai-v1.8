#!/bin/bash
# Comando rápido para ejecutar desde Cloud Shell
# Configura el dashboard en nginx sin exponer SSH ni PostgreSQL

gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        
        # Iniciar dashboard si no está corriendo
        docker-compose up -d dashboard-api
        
        # Verificar que responda
        sleep 3
        curl -s http://localhost:8000/health || echo 'Dashboard no responde'
        
        # Agregar ruta a nginx si no existe
        if ! grep -q 'location /dashboard/' nginx-site.conf; then
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración antes de 'location /'
            sed -i '/location \/health {/,/}/a\
    location /dashboard/ { proxy_pass http://localhost:8000/; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }\
    location /api/ { proxy_pass http://localhost:8000/api/; proxy_set_header Host \$host; }\
' nginx-site.conf
            
            # Reiniciar nginx
            docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
        fi
        
        echo '✅ Dashboard configurado en http://YOUR_IP_ADDRESS/dashboard/'
    "
