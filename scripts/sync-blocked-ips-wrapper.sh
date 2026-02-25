#!/bin/bash
# Wrapper script para sync-blocked-ips-to-nginx.py
# Obtiene la contraseña de PostgreSQL desde un archivo seguro y ejecuta el script

set -e

# Archivo donde se almacena la contraseña (creado durante el setup)
POSTGRES_PASSWORD_FILE="/opt/tokio-ai-waf/.postgres-password"

# Obtener contraseña de PostgreSQL desde archivo (más confiable que Secrets Manager desde VM)
if [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    export POSTGRES_PASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
else
    # Fallback: intentar desde Secrets Manager (puede fallar si la VM no tiene permisos)
    export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=YOUR_GCP_PROJECT_ID 2>/dev/null || echo "")
    if [ -z "$POSTGRES_PASSWORD" ]; then
        echo "❌ Error: No se pudo obtener la contraseña de PostgreSQL" >&2
        exit 1
    fi
fi

# Configuración de PostgreSQL
export POSTGRES_HOST=YOUR_IP_ADDRESS
export POSTGRES_PORT=5432
export POSTGRES_DB=soc_ai
export POSTGRES_USER=soc_user

# Configuración de Nginx
export NGINX_BLOCKED_IPS_FILE=/opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf
export NGINX_RELOAD_COMMAND="docker exec tokio-ai-modsecurity nginx -s reload"
export NGINX_RELOAD_MIN_INTERVAL=10
export MAX_IPS_PER_BATCH=1000

# Ejecutar el script de sincronización
cd /opt/tokio-ai-waf/scripts
exec /usr/bin/python3 /opt/tokio-ai-waf/scripts/sync-blocked-ips-to-nginx.py "$@"
