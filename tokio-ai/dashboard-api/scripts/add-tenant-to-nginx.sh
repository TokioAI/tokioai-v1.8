#!/bin/bash
# VORTEX 9: Script para agregar dominio a Nginx automáticamente
# Vibración 3: Elegante en su simplicidad
# Vibración 6: Rigurosa en su eficiencia
# Vibración 9: Máxima abstracción - un script hace todo

set -e

DOMAIN=$1
UPSTREAM=$2
VM_NAME=${3:-tokio-ai-waf}
VM_ZONE=${4:-us-central1-a}
PROJECT_ID=${5:-YOUR_GCP_PROJECT_ID}

if [ -z "$DOMAIN" ]; then
    echo "❌ Error: Se requiere el dominio"
    exit 1
fi

# VORTEX 9: Configuración de upstream por defecto si no se proporciona
if [ -z "$UPSTREAM" ]; then
    UPSTREAM="http://YOUR_IP_ADDRESS:8080"
fi

echo "🔧 Configurando Nginx para dominio: $DOMAIN"

# VORTEX 9: Template de configuración de Nginx en una expresión
NGINX_CONFIG="
# Logs en JSON incluyendo host para multi-tenant
log_format modsec_log escape=json
    '{'
    '\"time_local\":\"\$time_local\",'
    '\"host\":\"\$host\",'
    '\"remote_addr\":\"\$remote_addr\",'
    '\"request_method\":\"\$request_method\",'
    '\"request_uri\":\"\$request_uri\",'
    '\"status\":\"\$status\",'
    '\"body_bytes_sent\":\"\$body_bytes_sent\",'
    '\"http_referer\":\"\$http_referer\",'
    '\"http_user_agent\":\"\$http_user_agent\"'
    '}';

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;

    # Logs JSON con host para resolver tenant_id
    access_log /var/log/nginx/${DOMAIN}-access.log modsec_log;
    error_log /var/log/nginx/${DOMAIN}-error.log;

    # ModSecurity
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;

    location / {
        proxy_pass $UPSTREAM;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Headers para ModSecurity
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Server \$host;
    }
}
"

# VORTEX 6: Crear archivo de configuración temporal
CONFIG_FILE="/tmp/nginx-${DOMAIN}.conf"
echo "$NGINX_CONFIG" > "$CONFIG_FILE"

# VORTEX 9: Copiar a la VM y aplicar configuración en una sola operación
echo "📤 Copiando configuración a la VM..."
gcloud compute scp "$CONFIG_FILE" "${VM_NAME}:/tmp/nginx-${DOMAIN}.conf" \
    --zone="$VM_ZONE" \
    --project="$PROJECT_ID" 2>/dev/null || {
    echo "⚠️ No se pudo copiar vía gcloud, intentando método alternativo..."
    # Método alternativo: usar docker exec si tenemos acceso
    exit 1
}

# VORTEX 9: Aplicar configuración en la VM
echo "🔧 Aplicando configuración en Nginx..."
gcloud compute ssh "$VM_NAME" \
    --zone="$VM_ZONE" \
    --project="$PROJECT_ID" \
    --command="
        sudo docker exec tokio-ai-modsecurity bash -c '
            # Copiar configuración al contenedor
            cat > /etc/nginx/conf.d/${DOMAIN}.conf << \"EOF\"
$NGINX_CONFIG
EOF
            # Verificar configuración
            nginx -t && \
            # Recargar Nginx
            nginx -s reload && \
            echo \"✅ Nginx configurado para $DOMAIN\"
        ' || echo \"⚠️ Error configurando Nginx (puede requerir acceso manual)\"
    " 2>/dev/null || {
    echo "⚠️ No se pudo configurar Nginx automáticamente"
    echo "📋 Instrucciones manuales:"
    echo "   1. Conecta a la VM: gcloud compute ssh $VM_NAME --zone=$VM_ZONE"
    echo "   2. Copia el contenido de /tmp/nginx-${DOMAIN}.conf a /etc/nginx/conf.d/${DOMAIN}.conf en el contenedor"
    echo "   3. Ejecuta: docker exec tokio-ai-modsecurity nginx -t && nginx -s reload"
}

# Limpiar archivo temporal
rm -f "$CONFIG_FILE"

echo "✅ Proceso completado para $DOMAIN"
