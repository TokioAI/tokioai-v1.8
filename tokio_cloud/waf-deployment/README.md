# 🚀 WAF + Proxy + ModSecurity - Despliegue Automatizado

Sistema completo de despliegue automatizado para WAF (Web Application Firewall) con ModSecurity y Nginx como proxy reverso. Diseñado para desplegarse fácilmente en cualquier VM de GCP con un solo comando.

## 📋 Características

- ✅ **Despliegue con un solo comando**
- ✅ **ModSecurity + OWASP CRS** para protección avanzada
- ✅ **Nginx como proxy reverso** con soporte SSL/TLS
- ✅ **Procesamiento de logs en tiempo real** (Kafka)
- ✅ **Fácil agregar múltiples sitios web**
- ✅ **Health checks automáticos**
- ✅ **Restart automático de contenedores**

## 🚀 Inicio Rápido

### 1. Preparar el entorno

```bash
cd /opt/tokioai/waf

# Copiar y editar configuración
cp .env.example .env
nano .env  # Ajustar valores según tu entorno
```

### 2. Desplegar

```bash
# Opción 1: Usar el script automatizado
./scripts/deploy-waf.sh

# Opción 2: Manual
export VM_NAME="tu-vm"
export VM_ZONE="us-central1-a"
export PROJECT_ID="tu-proyecto"
./scripts/deploy-waf.sh
```

### 3. Verificar

```bash
# Obtener IP de la VM
VM_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$VM_ZONE \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

# Probar HTTP
curl -I http://$VM_IP

# Probar HTTPS
curl -I -k https://$VM_IP
```

## 📁 Estructura del Proyecto

```
waf-deployment/
├── docker-compose.yml          # Configuración de contenedores
├── .env.example                # Plantilla de variables de entorno
├── .env                        # Tu configuración (crear desde .env.example)
├── scripts/
│   ├── deploy-waf.sh          # Script de despliegue principal
│   └── add-website.sh         # Script para agregar sitios web
├── modsecurity/
│   ├── config/                # Configuraciones de nginx
│   ├── rules/                 # Reglas de ModSecurity
│   ├── modsec-logs/           # Logs de ModSecurity
│   ├── html/                  # Archivos estáticos
│   └── log-processor.py       # Procesador de logs
└── ssl/                       # Certificados SSL (opcional)
    ├── fullchain.pem
    └── privkey.pem
```

## ⚙️ Configuración

### Variables de Entorno (.env)

```bash
# Puertos del proxy
NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443

# Backend (sitio web detrás del WAF)
BACKEND_URL=http://YOUR_IP_ADDRESS:80
BACKEND_HOST=your-domain.com
BACKEND_PORT=80
BACKEND_SSL=off

# Configuración del servidor
SERVER_NAME=your-domain.com
NGINX_ALWAYS_TLS_REDIRECT=on

# Kafka (para envío de logs)
KAFKA_BOOTSTRAP_SERVERS=localhost:9093
KAFKA_TOPIC_WAF_LOGS=waf-logs
```

## 🌐 Agregar Múltiples Sitios Web

### Opción 1: Script Automatizado

```bash
./scripts/add-website.sh
```

Seguir las instrucciones para agregar un nuevo dominio.

### Opción 2: Manual

1. Editar `modsecurity/config/gcp-nginx-https.conf`
2. Agregar un nuevo bloque `server`:

```nginx
server {
    listen 8080;
    listen 8443 ssl http2;
    server_name nuevo-dominio.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    location / {
        proxy_pass http://backend-ip:puerto;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

3. Reiniciar contenedor:

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose restart modsecurity-nginx"
```

## 🔧 Comandos Útiles

### Ver logs

```bash
# Logs de ModSecurity
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose logs -f modsecurity-nginx"

# Logs del log-processor
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose logs -f log-processor"
```

### Reiniciar servicios

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose restart"
```

### Detener servicios

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose down"
```

### Ver estado

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose ps"
```

## 🔐 Certificados SSL

### Opción 1: Let's Encrypt (Recomendado)

```bash
# Instalar certbot en la VM
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="sudo apt-get update && sudo apt-get install -y certbot"

# Obtener certificado
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="sudo certbot certonly --standalone -d your-domain.com"

# Copiar certificados al directorio ssl
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /opt/tokio-ai-waf/ssl/ && sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem /opt/tokio-ai-waf/ssl/ && sudo chown \$(whoami):\$(whoami) /opt/tokio-ai-waf/ssl/*"
```

### Opción 2: Certificados Existentes

Copiar tus certificados a `waf-deployment/ssl/`:
- `fullchain.pem`
- `privkey.pem`

El script de despliegue los copiará automáticamente a la VM.

## 📊 Monitoreo

### Ver logs de acceso

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="tail -f /opt/tokio-ai-waf/modsecurity/modsec-logs/access.log"
```

### Ver logs de errores

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="tail -f /opt/tokio-ai-waf/modsecurity/modsec-logs/error.log"
```

### Ver logs de ModSecurity

```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="tail -f /opt/tokio-ai-waf/modsecurity/modsec-logs/modsec_audit.log"
```

## 🔥 Firewall Rules

Asegúrate de tener estas reglas de firewall en GCP:

```bash
# HTTP
gcloud compute firewall-rules create allow-http \
    --allow tcp:80 \
    --source-ranges YOUR_IP_ADDRESS/0 \
    --target-tags http-server

# HTTPS
gcloud compute firewall-rules create allow-https \
    --allow tcp:443 \
    --source-ranges YOUR_IP_ADDRESS/0 \
    --target-tags https-server
```

## 🚨 Troubleshooting

### El sitio no responde

1. Verificar que los contenedores estén corriendo:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="docker ps"
```

2. Verificar puertos:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="sudo ss -tlnp | grep -E ':(80|443)'"
```

3. Verificar logs:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="cd /opt/tokio-ai-waf && docker-compose logs modsecurity-nginx"
```

### Error de certificados SSL

1. Verificar que los certificados existan:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="ls -la /opt/tokio-ai-waf/ssl/"
```

2. Verificar permisos:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="sudo chmod 644 /opt/tokio-ai-waf/ssl/*.pem"
```

### Contenedor en estado "unhealthy"

1. Verificar health check:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="docker exec tokio-ai-modsecurity wget -q -O- http://localhost:8080/health"
```

2. Verificar que el backend esté accesible:
```bash
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --tunnel-through-iap \
    --command="curl -I $BACKEND_URL"
```

## 📦 Backup

Para hacer backup de la configuración:

```bash
# Backup completo
tar -czf waf-backup-$(date +%Y%m%d).tar.gz \
    waf-deployment/ \
    --exclude='*.log' \
    --exclude='modsec-logs/*'

# Restaurar
tar -xzf waf-backup-YYYYMMDD.tar.gz
```

## 🔄 Actualizar

Para actualizar el WAF:

```bash
# 1. Hacer backup
tar -czf waf-backup-$(date +%Y%m%d).tar.gz waf-deployment/

# 2. Actualizar archivos
# (copiar nuevos archivos a waf-deployment/)

# 3. Redesplegar
./scripts/deploy-waf.sh
```

## 📝 Notas

- El script detiene automáticamente nginx del sistema si está corriendo
- Los logs se guardan en `modsecurity/modsec-logs/`
- El log-processor envía logs a Kafka (configurable)
- Los contenedores se reinician automáticamente si fallan

## 🆘 Soporte

Si tienes problemas:
1. Revisar logs: `docker-compose logs`
2. Verificar configuración: `cat .env`
3. Verificar firewall rules en GCP
4. Verificar que el backend esté accesible

---

**Última actualización:** $(date +%Y-%m-%d)
