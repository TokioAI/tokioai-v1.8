#!/bin/bash
# Script para agregar un nuevo sitio web detrás del WAF

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VM_NAME="${VM_NAME:-tokio-ai-waf}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/tokio-ai-waf}"

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     🌐 AGREGAR NUEVO SITIO WEB AL WAF                               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Solicitar información del nuevo sitio
read -p "Nombre del dominio (ej: ejemplo.com): " DOMAIN
read -p "URL del backend (ej: http://YOUR_IP_ADDRESS:80): " BACKEND_URL
read -p "¿Usar SSL? (s/n): " USE_SSL

if [ -z "$DOMAIN" ] || [ -z "$BACKEND_URL" ]; then
    echo "❌ Error: Dominio y backend son requeridos"
    exit 1
fi

echo ""
echo "📝 Agregando sitio: $DOMAIN -> $BACKEND_URL"

# Crear configuración del nuevo sitio
SERVER_BLOCK=$(cat <<EOF
    # Servidor para $DOMAIN
    server {
        listen 8080;
        listen 8443 ssl http2;
        server_name $DOMAIN;

        # SSL Configuration
        ssl_certificate /etc/nginx/ssl/fullchain.pem;
        ssl_certificate_key /etc/nginx/ssl/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # ModSecurity
        modsecurity on;
        modsecurity_rules_file /etc/modsecurity/modsecurity.conf;

        # Logs
        access_log /var/log/nginx/${DOMAIN//./_}_access.log;
        error_log /var/log/nginx/${DOMAIN//./_}_error.log;

        # Proxy al backend
        location / {
            proxy_pass $BACKEND_URL;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }

        # Health check
        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
EOF
)

# Agregar al archivo de configuración
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="
        cd $DEPLOY_DIR
        echo '$SERVER_BLOCK' >> modsecurity/config/gcp-nginx-https.conf
        echo '✅ Configuración agregada'
    " 2>&1 | tail -5

# Reiniciar contenedor para aplicar cambios
echo ""
echo "🔄 Reiniciando contenedor para aplicar cambios..."
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="
        cd $DEPLOY_DIR
        docker-compose restart modsecurity-nginx 2>/dev/null || docker compose restart modsecurity-nginx
    " 2>&1 | tail -5

echo ""
echo -e "${GREEN}✅ Sitio $DOMAIN agregado exitosamente${NC}"
echo ""
echo "📋 Próximos pasos:"
echo "   1. Configurar DNS para que $DOMAIN apunte a la IP de la VM"
echo "   2. Si usas SSL, asegúrate de tener certificados válidos"
echo "   3. Verificar que el backend $BACKEND_URL esté accesible"
echo ""
