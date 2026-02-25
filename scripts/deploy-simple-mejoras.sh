#!/bin/bash
# Script simplificado de despliegue - Sin bloquearse

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="us-central1"
ARTIFACT_REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/tokio-ai"

echo "🚀 Despliegue Simplificado de Mejoras"
echo "======================================"
echo ""

# Paso 1: Construir realtime-processor usando cloudbuild-realtime.yaml
echo "📦 Paso 1/3: Construyendo realtime-processor..."
gcloud builds submit \
    --config=cloudbuild-realtime.yaml \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --async \
    . 2>&1 | tee /tmp/build-realtime.log

BUILD_ID=$(grep -oP 'builds/\K[^ ]+' /tmp/build-realtime.log | head -1 || echo "")

if [ -n "$BUILD_ID" ]; then
    echo "✅ Build iniciado: $BUILD_ID"
    echo "   Monitorea con: gcloud builds describe $BUILD_ID --region=${REGION} --project=${PROJECT_ID}"
else
    echo "⚠️  Verifica el build manualmente"
fi

# Paso 2: Construir dashboard-api
echo ""
echo "📦 Paso 2/3: Construyendo dashboard-api..."
gcloud builds submit \
    --config=cloudbuild-dashboard.yaml \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --async \
    . 2>&1 | tee /tmp/build-dashboard.log

BUILD_ID2=$(grep -oP 'builds/\K[^ ]+' /tmp/build-dashboard.log | head -1 || echo "")

if [ -n "$BUILD_ID2" ]; then
    echo "✅ Build iniciado: $BUILD_ID2"
else
    echo "⚠️  Verifica el build manualmente"
fi

# Paso 3: Actualizar variables de entorno (sin esperar builds)
echo ""
echo "📋 Paso 3/3: Actualizando variables de entorno de realtime-processor..."
gcloud run services update realtime-processor \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-env-vars \
        "INTELLIGENT_BLOCKING_ENABLED=true,INTELLIGENT_BLOCKING_SHADOW_MODE=true,RATE_LIMITING_ENABLED=true,AUTO_CLEANUP_ENABLED=true,EARLY_PREDICTION_ENABLED=true" \
    --quiet 2>&1 | head -20

echo ""
echo "✅ Proceso iniciado"
echo ""
echo "📋 Para verificar builds:"
echo "   gcloud builds list --limit=5 --region=${REGION} --project=${PROJECT_ID}"
echo ""
echo "📋 Para monitorear logs:"
echo "   gcloud logging read \"resource.type=cloud_run_revision AND resource.labels.service_name=realtime-processor\" --limit=20 --project=${PROJECT_ID}"
echo ""
echo "📋 Para ejecutar tests después:"
echo "   ./scripts/test-mejoras-finde-semana.sh"
