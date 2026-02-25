#!/bin/bash
# Script para ejecutar migración SQL usando Cloud SQL Proxy o conexión directa

PROJECT_ID="YOUR_GCP_PROJECT_ID"
INSTANCE_NAME="tokio-ai-postgres"
DATABASE_NAME="soc_ai"
DB_USER="soc_user"
MIGRATION_FILE="scripts/migration_improvements_weekend.sql"

echo "🔄 Ejecutando migración SQL..."
echo ""

# Opción 1: Intentar con Cloud SQL Proxy (si está corriendo)
if pg_isready -h YOUR_IP_ADDRESS -p 5432 -U ${DB_USER} -d ${DATABASE_NAME} 2>/dev/null; then
    echo "✅ Cloud SQL Proxy detectado en localhost:5432"
    export PGPASSWORD="${POSTGRES_PASSWORD:-}"
    psql -h YOUR_IP_ADDRESS -p 5432 -U ${DB_USER} -d ${DATABASE_NAME} -f ${MIGRATION_FILE} && \
        echo "✅ Migración ejecutada exitosamente" || \
        echo "❌ Error ejecutando migración"
    exit $?
fi

# Opción 2: Usar gcloud sql connect (interactivo)
echo "ℹ️  Cloud SQL Proxy no detectado"
echo ""
echo "📋 Para ejecutar la migración, usa uno de estos métodos:"
echo ""
echo "Método 1: Cloud SQL Proxy (recomendado)"
echo "----------------------------------------"
echo "1. Inicia Cloud SQL Proxy:"
echo "   cloud_sql_proxy -instances=${PROJECT_ID}:${REGION}:${INSTANCE_NAME}=tcp:5432"
echo ""
echo "2. En otra terminal, ejecuta:"
echo "   psql -h YOUR_IP_ADDRESS -U ${DB_USER} -d ${DATABASE_NAME} -f ${MIGRATION_FILE}"
echo ""
echo "Método 2: gcloud sql connect (interactivo)"
echo "------------------------------------------"
echo "   gcloud sql connect ${INSTANCE_NAME} --user=${DB_USER} --database=${DATABASE_NAME} --project=${PROJECT_ID}"
echo "   # Luego ejecuta: \\i ${MIGRATION_FILE}"
echo ""
echo "Método 3: Desde Cloud Run (si tienes servicio con acceso)"
echo "----------------------------------------------------------"
echo "   # Ejecutar SQL directamente desde un servicio con acceso a Cloud SQL"
echo ""
echo "📄 Contenido de la migración:"
echo "   cat ${MIGRATION_FILE}"
echo ""

# Mostrar el contenido de la migración para que puedas ejecutarlo manualmente
echo "═══════════════════════════════════════════════════════════════"
echo "CONTENIDO DE LA MIGRACIÓN (para copiar/pegar):"
echo "═══════════════════════════════════════════════════════════════"
cat ${MIGRATION_FILE}
echo ""
echo "═══════════════════════════════════════════════════════════════"
