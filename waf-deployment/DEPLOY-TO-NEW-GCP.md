# 🚀 Desplegar WAF en Nueva Nube de GCP

Guía paso a paso para desplegar el WAF en una nueva instancia de GCP.

## 📋 Requisitos Previos

1. **VM en GCP** con:
   - Ubuntu 20.04+ o Debian 11+
   - Acceso SSH habilitado
   - Firewall rules para puertos 80 y 443

2. **Certificados SSL** (opcional pero recomendado):
   - `fullchain.pem`
   - `privkey.pem`

## 🚀 Pasos de Despliegue

### Paso 1: Preparar el entorno local

```bash
cd /home/osboxes/SOC-AI-LAB/waf-deployment

# Copiar configuración de ejemplo
cp .env.example .env

# Editar con tus valores
nano .env
```

### Paso 2: Configurar variables

Editar `.env` con tus valores:

```bash
# Información de la VM
VM_NAME="tu-vm-waf"
VM_ZONE="us-central1-a"
PROJECT_ID="tu-proyecto-gcp"

# Backend
BACKEND_URL="http://IP-DEL-BACKEND:80"
BACKEND_HOST="tu-dominio.com"
SERVER_NAME="tu-dominio.com"
```

### Paso 3: Desplegar

```bash
# Opción 1: Usar variables de entorno
export VM_NAME="tu-vm-waf"
export VM_ZONE="us-central1-a"
export PROJECT_ID="tu-proyecto-gcp"
./scripts/deploy-waf.sh

# Opción 2: Editar el script directamente
nano scripts/deploy-waf.sh  # Cambiar valores por defecto
./scripts/deploy-waf.sh
```

### Paso 4: Verificar

```bash
# Obtener IP de la VM
VM_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$VM_ZONE \
    --project=$PROJECT_ID \
    --format="get(networkInterfaces[0].accessConfig[0].natIP)")

# Probar
curl -I http://$VM_IP
curl -I -k https://$VM_IP
```

## 🔥 Configurar Firewall

```bash
# HTTP
gcloud compute firewall-rules create allow-http-waf \
    --allow tcp:80 \
    --source-ranges YOUR_IP_ADDRESS/0 \
    --target-tags http-server \
    --project=$PROJECT_ID

# HTTPS
gcloud compute firewall-rules create allow-https-waf \
    --allow tcp:443 \
    --source-ranges YOUR_IP_ADDRESS/0 \
    --target-tags https-server \
    --project=$PROJECT_ID
```

## 🌐 Agregar Múltiples Sitios

```bash
./scripts/add-website.sh
```

O editar manualmente `modsecurity/config/gcp-nginx-https.conf` y agregar bloques `server`.

## 📦 Backup y Restauración

### Backup

```bash
./scripts/backup-waf.sh
```

### Restaurar

```bash
./scripts/restore-waf.sh /ruta/al/backup.tar.gz
```

## 🔐 Certificados SSL

### Opción 1: Let's Encrypt (Recomendado)

```bash
# En la VM
sudo apt-get update
sudo apt-get install -y certbot

# Obtener certificado
sudo certbot certonly --standalone -d tu-dominio.com

# Copiar a directorio ssl
sudo cp /etc/letsencrypt/live/tu-dominio.com/fullchain.pem /opt/tokio-ai-waf/ssl/
sudo cp /etc/letsencrypt/live/tu-dominio.com/privkey.pem /opt/tokio-ai-waf/ssl/
sudo chown $(whoami):$(whoami) /opt/tokio-ai-waf/ssl/*
```

### Opción 2: Certificados Existentes

Copiar tus certificados a `waf-deployment/ssl/` antes de desplegar.

## ✅ Verificación Final

1. **HTTP funciona**: `curl -I http://IP-VM`
2. **HTTPS funciona**: `curl -I -k https://IP-VM`
3. **Contenedores corriendo**: `docker ps`
4. **Logs funcionando**: `docker logs tokio-ai-modsecurity`

## 🆘 Troubleshooting

Ver `README.md` para troubleshooting detallado.

---

**¡Listo! Tu WAF está desplegado y funcionando.** 🎉
