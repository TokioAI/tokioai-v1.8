#!/bin/bash
# Script alternativo para aplicar migración usando Cloud SQL Proxy
# Requiere tener Cloud SQL Proxy instalado y corriendo

set -e

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
INSTANCE_NAME="tokio-ai-postgres"
CONNECTION_NAME="${PROJECT_ID}:us-central1:${INSTANCE_NAME}"
DB_NAME="soc_ai"
DB_USER="soc_user"
MIGRATION_FILE="real-time-processor/migrations/add_intelligence_analysis_to_episodes.sql"
LOCAL_PORT=5433

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: PROJECT_ID no configurado"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔄 APLICANDO MIGRACIÓN vía Cloud SQL Proxy                        ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Verificar si cloud-sql-proxy está disponible
if ! command -v cloud-sql-proxy &> /dev/null; then
    echo "⚠️  Cloud SQL Proxy no está instalado"
    echo ""
    echo "📋 Instalación rápida:"
    echo "   Linux:"
    echo "   wget https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.linux.amd64 -O cloud-sql-proxy"
    echo "   chmod +x cloud-sql-proxy"
    echo "   sudo mv cloud-sql-proxy /usr/local/bin/"
    echo ""
    echo "   O usa el método manual con gcloud sql connect"
    exit 1
fi

echo "✅ Cloud SQL Proxy encontrado"
echo ""

# Verificar si PGPASSWORD está configurado
if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "📋 Intentando obtener contraseña del secreto de GCP..."
    POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project="$PROJECT_ID" 2>/dev/null || echo "")
    
    if [ -z "$POSTGRES_PASSWORD" ]; then
        echo "⚠️  No se pudo obtener la contraseña automáticamente"
        echo ""
        echo "📋 Ejecuta:"
        echo "   export POSTGRES_PASSWORD=\$(gcloud secrets versions access latest --secret='postgres-password')"
        echo "   bash $0"
        exit 1
    fi
fi

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "✅ Contraseña obtenida"
echo ""

# Iniciar Cloud SQL Proxy en background
echo "🔄 Iniciando Cloud SQL Proxy en puerto $LOCAL_PORT..."
cloud-sql-proxy "$CONNECTION_NAME" --port="$LOCAL_PORT" > /tmp/cloud-sql-proxy.log 2>&1 &
PROXY_PID=$!

# Esperar a que el proxy esté listo
echo "⏳ Esperando a que Cloud SQL Proxy esté listo..."
sleep 5

# Verificar que el proxy está funcionando
if ! kill -0 $PROXY_PID 2>/dev/null; then
    echo "❌ Error: Cloud SQL Proxy no se inició correctamente"
    echo "   Revisa los logs en /tmp/cloud-sql-proxy.log"
    exit 1
fi

echo "✅ Cloud SQL Proxy corriendo (PID: $PROXY_PID)"
echo ""

# Aplicar migración
echo "📋 Aplicando migración..."
psql -h YOUR_IP_ADDRESS -p "$LOCAL_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$MIGRATION_FILE" && {
    echo ""
    echo "✅ Migración aplicada exitosamente!"
} || {
    echo ""
    echo "❌ Error aplicando migración"
    kill $PROXY_PID 2>/dev/null || true
    exit 1
}

# Detener Cloud SQL Proxy
echo ""
echo "🛑 Deteniendo Cloud SQL Proxy..."
kill $PROXY_PID 2>/dev/null || true
wait $PROXY_PID 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ MIGRACIÓN APLICADA EXITOSAMENTE                                 ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Verifica que la columna existe:"
echo "   psql -h YOUR_IP_ADDRESS -p $LOCAL_PORT -U $DB_USER -d $DB_NAME -c \"\\d episodes\""

