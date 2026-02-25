# 🔐 Acceso Seguro al Dashboard - Sin Exponer SSH ni PostgreSQL

## ✅ Solución Implementada

El dashboard será accesible **solo a través de nginx** en el puerto 80/443 (que ya está abierto), sin exponer:
- ❌ SSH (puerto 22) - BLOQUEADO
- ❌ PostgreSQL (puerto 5432) - BLOQUEADO
- ✅ Dashboard - Accesible en `/dashboard/` a través de nginx

## 🚀 Configuración Rápida (Desde Cloud Shell)

### Opción 1: Script Completo

1. Ir a: https://shell.cloud.google.com/
2. Subir o copiar el script: `scripts/setup_dashboard_nginx_cloudshell.sh`
3. Ejecutar:
   ```bash
   chmod +x setup_dashboard_nginx_cloudshell.sh
   ./setup_dashboard_nginx_cloudshell.sh
   ```

### Opción 2: Comando Directo

Desde Cloud Shell, ejecutar:

```bash
gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        docker-compose up -d dashboard-api
        if ! grep -q 'location /dashboard/' nginx-site.conf; then
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            sed -i '/location \/health {/,/}/a\
    location /dashboard/ { proxy_pass http://localhost:8000/; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }\
    location /api/ { proxy_pass http://localhost:8000/api/; proxy_set_header Host \$host; }\
' nginx-site.conf
            docker restart tokio-gcp-waf-proxy
        fi
        echo '✅ Dashboard: http://YOUR_IP_ADDRESS/dashboard/'
    "
```

## 🌐 Acceso al Dashboard

Después de configurar:

- **HTTP:** http://YOUR_IP_ADDRESS/dashboard/
- **HTTPS:** https://tokioia.com/dashboard/ (si tenés SSL configurado)

## 🔒 Seguridad

- ✅ SSH (22) - NO expuesto
- ✅ PostgreSQL (5432) - NO expuesto  
- ✅ Dashboard - Solo a través de nginx (puerto 80/443)
- ✅ No se requieren reglas de firewall adicionales

## 🗑️ Limpiar Reglas Temporales

Si creaste reglas temporales de firewall, eliminarlas:

```bash
gcloud compute firewall-rules delete allow-ssh-temp-1771884161 --project=YOUR_GCP_PROJECT_ID --quiet
gcloud compute firewall-rules delete allow-dashboard-1771883416 --project=YOUR_GCP_PROJECT_ID --quiet
```

El dashboard funcionará a través de nginx sin necesidad de estas reglas.
