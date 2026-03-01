#!/bin/bash
# Script de despliegue automatizado del WAF y Proxy
# Despliega ModSecurity + Nginx en una VM de GCP con un solo comando

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuración por defecto
VM_NAME="${VM_NAME:-tokio-ai-waf}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/tokio-ai-waf}"

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     🚀 DESPLIEGUE AUTOMATIZADO WAF + PROXY + MODSECURITY           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "VM: $VM_NAME"
echo "Zona: $VM_ZONE"
echo "Proyecto: $PROJECT_ID"
echo "Directorio: $DEPLOY_DIR"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Error: Ejecutar desde el directorio waf-deployment${NC}"
    echo "   cd /opt/tokioai/waf/waf-deployment"
    exit 1
fi

# Verificar que existe .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  No se encontró archivo .env${NC}"
    echo "   Creando desde .env.example..."
    cp .env.example .env
    echo -e "${YELLOW}   Por favor, edita .env con tus configuraciones antes de continuar${NC}"
    echo ""
    read -p "¿Continuar con valores por defecto? (s/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        exit 1
    fi
fi

# Cargar variables de entorno
set -a
source .env
set +a

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "📦 Paso 1/5: Preparando archivos en la VM"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Crear directorio en la VM
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="sudo mkdir -p $DEPLOY_DIR && sudo chown -R \$(whoami):\$(whoami) $DEPLOY_DIR" 2>&1 | tail -5

# Copiar archivos a la VM
echo "📤 Copiando archivos a la VM..."
gcloud compute scp \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --recurse \
    docker-compose.yml \
    .env \
    modsecurity/ \
    $VM_NAME:$DEPLOY_DIR/ 2>&1 | tail -10

# Copiar SSL si existe
if [ -d "ssl" ] && [ "$(ls -A ssl)" ]; then
    echo "📤 Copiando certificados SSL..."
    gcloud compute scp \
        --zone=$VM_ZONE \
        --project=$PROJECT_ID \
        --tunnel-through-iap \
        --recurse \
        ssl/ \
        $VM_NAME:$DEPLOY_DIR/ssl/ 2>&1 | tail -5
else
    echo -e "${YELLOW}⚠️  No se encontraron certificados SSL en ./ssl/${NC}"
    echo "   El WAF funcionará pero HTTPS puede no funcionar sin certificados"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "🔧 Paso 2/5: Configurando la VM"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Instalar Docker y Docker Compose si no están instalados
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="
        if ! command -v docker &> /dev/null; then
            echo '📦 Instalando Docker...'
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            sudo usermod -aG docker \$(whoami)
        fi
        
        if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
            echo '📦 Instalando Docker Compose...'
            sudo curl -L \"https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)\" -o /usr/local/bin/docker-compose
            sudo chmod +x /usr/local/bin/docker-compose
        fi
        
        # Detener nginx del sistema si está corriendo
        sudo systemctl stop nginx 2>/dev/null || true
        sudo systemctl disable nginx 2>/dev/null || true
        
        echo '✅ VM configurada'
    " 2>&1 | tail -20

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "🚀 Paso 3/5: Iniciando contenedores"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Iniciar contenedores
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="
        cd $DEPLOY_DIR
        echo '🛑 Deteniendo contenedores existentes...'
        docker-compose down 2>/dev/null || docker compose down 2>/dev/null || true
        
        echo '🚀 Iniciando contenedores...'
        docker-compose up -d 2>/dev/null || docker compose up -d
        
        echo '⏳ Esperando 10 segundos...'
        sleep 10
        
        echo '📊 Estado de los contenedores:'
        docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E '(modsecurity|log-processor|NAME)'
    " 2>&1 | tail -20

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "🔍 Paso 4/5: Verificando despliegue"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Obtener IP de la VM
VM_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)

echo "🌐 IP de la VM: $VM_IP"
echo ""

# Verificar puertos
echo "🔍 Verificando puertos..."
gcloud compute ssh $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --tunnel-through-iap \
    --command="sudo ss -tlnp | grep -E ':(80|443)'" 2>&1 | tail -5

echo ""
echo "🔍 Verificando conectividad..."
sleep 5

if timeout 5 curl -I http://$VM_IP 2>&1 | grep -q "HTTP"; then
    echo -e "${GREEN}✅ HTTP funcionando${NC}"
else
    echo -e "${YELLOW}⚠️  HTTP no responde aún (puede tardar unos minutos)${NC}"
fi

if timeout 5 curl -I -k https://$VM_IP 2>&1 | grep -q "HTTP"; then
    echo -e "${GREEN}✅ HTTPS funcionando${NC}"
else
    echo -e "${YELLOW}⚠️  HTTPS no responde (verificar certificados SSL)${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "✅ Paso 5/5: Despliegue completado"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${GREEN}✅ WAF y Proxy desplegados exitosamente${NC}"
echo ""
echo "📋 Información:"
echo "   • VM: $VM_NAME"
echo "   • IP: $VM_IP"
echo "   • HTTP: http://$VM_IP"
echo "   • HTTPS: https://$VM_IP"
echo ""
echo "📋 Comandos útiles:"
echo "   Ver logs: gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap --command='cd $DEPLOY_DIR && docker-compose logs -f'"
echo "   Reiniciar: gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap --command='cd $DEPLOY_DIR && docker-compose restart'"
echo "   Detener: gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap --command='cd $DEPLOY_DIR && docker-compose down'"
echo ""
echo -e "${GREEN}💡 Para agregar más sitios web, edita modsecurity/config/gcp-nginx-https.conf${NC}"
echo ""
