#!/bin/bash
# Script SIMPLE para arreglar nginx - ejecutar desde Cloud Shell

gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    << 'ENDSSH'
cd /opt/tokio-waf

# Dashboard
docker-compose up -d dashboard-api
sleep 10

# Nginx - método directo
echo "Verificando nginx-site.conf..."
if [ -f nginx-site.conf ]; then
    # Eliminar configuración vieja
    sed -i '/location \/dashboard\/ {/,/^    }$/d' nginx-site.conf
    
    # Agregar nueva configuración - método simple
    # Buscar "location /" y agregar antes
    if grep -q "^    location / {" nginx-site.conf; then
        sed -i '/^    location \/ {/i\
    location /dashboard/ {\
        proxy_pass http://localhost:8000/;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
    }\
' nginx-site.conf
        echo "✅ Configuración agregada antes de location /"
    else
        # Si no hay location /, agregar después de location /health
        sed -i '/location \/health {/,/}/a\
    location /dashboard/ { proxy_pass http://localhost:8000/; proxy_set_header Host $host; }\
' nginx-site.conf
        echo "✅ Configuración agregada después de /health"
    fi
    
    # Verificar
    if grep -q "location /dashboard/" nginx-site.conf; then
        echo "✅ Verificado: /dashboard/ está en nginx-site.conf"
        echo ""
        echo "Configuración:"
        grep -A 3 "location /dashboard/" nginx-site.conf
    else
        echo "❌ Error: No se pudo agregar"
        exit 1
    fi
    
    # Reiniciar nginx
    echo ""
    echo "Reiniciando nginx..."
    docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
    sleep 5
    
    # Verificar
    if curl -s http://localhost/dashboard/health > /dev/null; then
        echo "✅ Dashboard accesible vía nginx"
    else
        echo "⚠️ Verificando configuración de nginx..."
        docker exec tokio-gcp-waf-proxy nginx -t 2>&1 || echo "No se pudo verificar"
    fi
else
    echo "❌ nginx-site.conf no existe"
    exit 1
fi

echo ""
echo "✅ COMPLETADO"
echo "Dashboard: https://tokioia.com/dashboard/"
ENDSSH
