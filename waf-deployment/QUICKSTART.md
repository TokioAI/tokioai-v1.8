# 🚀 Inicio Rápido - WAF Deployment

## Desplegar en 3 pasos

### 1. Configurar

```bash
cd /home/osboxes/SOC-AI-LAB/waf-deployment
cp .env.example .env
nano .env  # Editar con tus valores
```

### 2. Desplegar

```bash
./scripts/deploy-waf.sh
```

### 3. Verificar

```bash
# Obtener IP de la VM
VM_IP=$(gcloud compute instances describe tokio-ai-waf \
    --zone=us-central1-a \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

# Probar
curl -I http://$VM_IP
curl -I -k https://$VM_IP
```

## Agregar más sitios web

```bash
./scripts/add-website.sh
```

## Backup

```bash
./scripts/backup-waf.sh
```

¡Listo! 🎉
