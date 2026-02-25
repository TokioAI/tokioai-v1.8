#!/bin/bash
# Script para desplegar sistema de episodios a GCP
# 1. Aplica migración SQL
# 2. Construye y despliega realtime-processor

set -e

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo 'YOUR_GCP_PROJECT_ID')}"
INSTANCE_NAME="tokio-ai-postgres"
DB_NAME="soc_ai"
DB_USER="soc_user"
SERVICE_NAME="realtime-processor"
REGION="us-central1"

echo "🚀 Desplegando sistema de episodios a GCP"
echo "   Proyecto: $PROJECT_ID"
echo "   Región: $REGION"
echo ""

# Paso 1: Aplicar migración SQL
echo "📋 Paso 1: Aplicar migración SQL a Cloud SQL"
echo ""

MIGRATION_FILE="real-time-processor/migrations/create_episodes_tables.sql"

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: No se encuentra el archivo de migración: $MIGRATION_FILE"
    exit 1
fi

# Intentar aplicar migración usando gcloud sql connect
echo "💾 Aplicando migración SQL..."
echo "   Instancia: $INSTANCE_NAME"
echo "   Base de datos: $DB_NAME"
echo ""

# Crear archivo temporal con la migración
TEMP_SQL=$(mktemp)
cat "$MIGRATION_FILE" > "$TEMP_SQL"

# Intentar aplicar usando gcloud sql execute (si está disponible)
if gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT_ID" > /dev/null 2>&1; then
    echo "✅ Instancia Cloud SQL encontrada"
    echo ""
    echo "⚠️  Para aplicar la migración SQL, ejecuta manualmente:"
    echo ""
    echo "   gcloud sql connect $INSTANCE_NAME --user=$DB_USER --database=$DB_NAME"
    echo ""
    echo "   Luego copia y pega el contenido de:"
    echo "   $MIGRATION_FILE"
    echo ""
    echo "   O ejecuta:"
    echo "   cat $MIGRATION_FILE | gcloud sql connect $INSTANCE_NAME --user=$DB_USER --database=$DB_NAME"
    echo ""
    read -p "¿Ya aplicaste la migración SQL? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "⚠️  Migración SQL pendiente. Continuando con el despliegue..."
        echo "   Puedes aplicar la migración después."
    fi
else
    echo "⚠️  No se puede verificar la instancia Cloud SQL"
    echo "   Continuando con el despliegue..."
fi

rm -f "$TEMP_SQL"

# Paso 2: Construir y desplegar realtime-processor
echo ""
echo "📦 Paso 2: Construir y desplegar realtime-processor"
echo ""

# Verificar que existe el Dockerfile
DOCKERFILE="real-time-processor/Dockerfile"
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ Error: No se encuentra el Dockerfile: $DOCKERFILE"
    exit 1
fi

# Verificar que existe el cloudbuild yaml
CLOUDBUILD="gcp-deployment/cloud-run/realtime-processor/cloudbuild-realtime.yaml"
if [ ! -f "$CLOUDBUILD" ]; then
    echo "❌ Error: No se encuentra el archivo cloudbuild: $CLOUDBUILD"
    exit 1
fi

echo "🔨 Construyendo imagen Docker..."
echo ""

# Construir usando Cloud Build
gcloud builds submit \
    --config="$CLOUDBUILD" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    .

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Build completado exitosamente"
    echo ""
    echo "🚀 Desplegando a Cloud Run..."
    echo ""
    
    # Obtener la última imagen construida
    IMAGE_NAME="gcr.io/$PROJECT_ID/realtime-processor"
    
    # Desplegar usando service.yaml
    SERVICE_YAML="gcp-deployment/cloud-run/realtime-processor/service.yaml"
    if [ -f "$SERVICE_YAML" ]; then
        gcloud run services replace "$SERVICE_YAML" \
            --project="$PROJECT_ID" \
            --region="$REGION"
        
        if [ $? -eq 0 ]; then
            echo ""
            echo "✅ Despliegue completado exitosamente"
            echo ""
            echo "📊 Verifica el servicio:"
            echo "   gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
            echo ""
            echo "📋 Ver logs:"
            echo "   gcloud logging read \"resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME\" --limit=50 --project=$PROJECT_ID"
        else
            echo "❌ Error al desplegar el servicio"
            exit 1
        fi
    else
        echo "⚠️  No se encuentra service.yaml, usando gcloud run deploy directamente"
        gcloud run deploy "$SERVICE_NAME" \
            --image="$IMAGE_NAME:latest" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --allow-unauthenticated
    fi
else
    echo "❌ Error al construir la imagen"
    exit 1
fi

echo ""
echo "✅ Despliegue completo"
echo ""
echo "📋 Próximos pasos:"
echo "   1. Aplicar migración SQL si aún no se aplicó"
echo "   2. Verificar logs del servicio"
echo "   3. Probar el sistema con tráfico real"




