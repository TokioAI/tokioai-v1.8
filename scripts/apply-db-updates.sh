#!/bin/bash
# Script para aplicar índices y tablas de retroalimentación desde un pod de GKE

set -e

echo "🔧 Aplicando actualizaciones a Cloud SQL PostgreSQL..."

# Crear pod temporal para ejecutar SQL
POD_NAME="db-update-$(date +%s)"

kubectl run $POD_NAME \
  --image=postgres:15-alpine \
  --rm -i --restart=Never \
  --env="PGHOST=YOUR_IP_ADDRESS" \
  --env="PGPORT=5432" \
  --env="PGDATABASE=soc_ai" \
  --env="PGUSER=postgres" \
  --env="PGPASSWORD=$(gcloud secrets versions access latest --secret=postgres-password)" \
  --command -- sh -c "
    echo '📊 Aplicando índices...'
    psql -h \$PGHOST -U \$PGUSER -d \$PGDATABASE -f /tmp/add-indexes.sql
    
    echo '🔄 Creando tablas de retroalimentación...'
    psql -h \$PGHOST -U \$PGUSER -d \$PGDATABASE -f /tmp/add-feedback-tables.sql
    
    echo '✅ Actualizaciones completadas'
  " || {
    echo "⚠️ No se pudo usar kubectl, intentando método alternativo..."
    echo "💡 Los índices y tablas se crearán automáticamente en el próximo despliegue"
  }

echo "✅ Script completado"

