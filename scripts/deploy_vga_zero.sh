#!/bin/bash
# Script de despliegue completo de Tokio AI - VGA-Zero
# Reemplaza Kafka por Pub/Sub y elimina dependencias de ML/LLM

set -e

PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
REDIS_ADDRESS="${REDIS_ADDRESS:-YOUR_IP_ADDRESS:6379}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌀 Desplegando Tokio AI - VGA-Zero"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Verificar que PROJECT_ID esté configurado
if [ "$PROJECT_ID" == "your-project-id" ]; then
    echo "❌ Error: GCP_PROJECT_ID no configurado"
    echo "   Exporta la variable: export GCP_PROJECT_ID=tu-proyecto"
    exit 1
fi

echo "📋 Configuración:"
echo "   Project ID: $PROJECT_ID"
echo "   Region: $REGION"
echo "   Redis Address: $REDIS_ADDRESS"
echo ""

# 1. Crear Pub/Sub topics y subscriptions
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📡 Paso 1: Configurando Pub/Sub..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Topic para logs del WAF
echo "   Creando topic: waf-logs"
gcloud pubsub topics create waf-logs --project=$PROJECT_ID 2>/dev/null || echo "   Topic waf-logs ya existe"

# Subscription para VGA Engine
echo "   Creando subscription: waf-logs-sub"
gcloud pubsub subscriptions create waf-logs-sub \
    --topic=waf-logs \
    --ack-deadline=60 \
    --message-retention-duration=10m \
    --project=$PROJECT_ID 2>/dev/null || echo "   Subscription waf-logs-sub ya existe"

# Topic para mitigaciones
echo "   Creando topic: mitigation-stream"
gcloud pubsub topics create mitigation-stream --project=$PROJECT_ID 2>/dev/null || echo "   Topic mitigation-stream ya existe"

echo "✅ Pub/Sub configurado"
echo ""

# 2. Crear Memorystore (Redis) para Cuckoo Filter
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔴 Paso 2: Configurando Memorystore (Redis)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Verificar si Redis ya existe
if gcloud redis instances describe tokio-vga-redis --region=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "   Redis instance tokio-vga-redis ya existe"
    REDIS_IP=$(gcloud redis instances describe tokio-vga-redis --region=$REGION --project=$PROJECT_ID --format="value(host)" 2>/dev/null || echo "")
    if [ -n "$REDIS_IP" ]; then
        echo "   Redis IP: $REDIS_IP:6379"
        REDIS_ADDRESS="$REDIS_IP:6379"
    fi
else
    echo "   Creando Redis instance: tokio-vga-redis"
    echo "   ⚠️  Esto puede tardar varios minutos..."
    gcloud redis instances create tokio-vga-redis \
        --size=1 \
        --region=$REGION \
        --redis-version=redis_7_0 \
        --tier=basic \
        --project=$PROJECT_ID || echo "   Error creando Redis (puede que ya exista)"
    
    # Obtener IP de Redis
    sleep 5
    REDIS_IP=$(gcloud redis instances describe tokio-vga-redis --region=$REGION --project=$PROJECT_ID --format="value(host)" 2>/dev/null || echo "")
    if [ -n "$REDIS_IP" ]; then
        REDIS_ADDRESS="$REDIS_IP:6379"
        echo "   Redis IP: $REDIS_ADDRESS"
    fi
fi

echo "✅ Redis configurado"
echo ""

# 3. Crear Service Account para VGA Engine
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 Paso 3: Configurando Service Accounts..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Service Account para VGA Engine
SA_EMAIL="vga-engine@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe $SA_EMAIL --project=$PROJECT_ID &>/dev/null; then
    echo "   Creando service account: vga-engine"
    gcloud iam service-accounts create vga-engine \
        --display-name="VGA Engine Service Account" \
        --project=$PROJECT_ID
    
    # Otorgar permisos necesarios
    echo "   Otorgando permisos..."
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/pubsub.subscriber" \
        --condition=None
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/pubsub.publisher" \
        --condition=None
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/redis.editor" \
        --condition=None
else
    echo "   Service account vga-engine ya existe"
fi

echo "✅ Service Accounts configurados"
echo ""

# 4. Desplegar VGA Engine (Cloud Run)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚙️  Paso 4: Desplegando VGA Engine..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd vga-engine

# Actualizar cloudbuild.yaml con Redis address
sed -i.bak "s|_REDIS_ADDRESS:.*|_REDIS_ADDRESS: '$REDIS_ADDRESS'|" cloudbuild.yaml

echo "   Construyendo y desplegando VGA Engine..."
gcloud builds submit --config=cloudbuild.yaml --project=$PROJECT_ID

cd ..

echo "✅ VGA Engine desplegado"
echo ""

# 5. Desplegar Dashboard API
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Paso 5: Desplegando Dashboard API..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd vga-dashboard-api

# Crear cloudbuild.yaml para dashboard
cat > cloudbuild.yaml <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/\$PROJECT_ID/vga-dashboard', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/\$PROJECT_ID/vga-dashboard']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'vga-dashboard'
      - '--image'
      - 'gcr.io/\$PROJECT_ID/vga-dashboard'
      - '--region'
      - 'us-central1'
      - '--platform'
      - 'managed'
      - '--min-instances'
      - '0'
      - '--max-instances'
      - '10'
      - '--cpu'
      - '2'
      - '--memory'
      - '2Gi'
      - '--timeout'
      - '300'
      - '--port'
      - '8080'
      - '--set-env-vars'
      - 'GCP_PROJECT_ID=\$PROJECT_ID,REDIS_ADDRESS=${REDIS_ADDRESS},VORTEX_COLLAPSE_THRESHOLD=0.75'
      - '--allow-unauthenticated'
EOF

echo "   Construyendo y desplegando Dashboard..."
gcloud builds submit --config=cloudbuild.yaml --project=$PROJECT_ID

cd ..

echo "✅ Dashboard API desplegado"
echo ""

# 6. Desplegar Cloud Function (Atomic Blocker)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🛡️  Paso 6: Desplegando Atomic Blocker (Cloud Function)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd vga-cloud-function

echo "   Desplegando Cloud Function..."
gcloud functions deploy atomic-blocker \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=. \
    --entry-point=atomic_block \
    --trigger-topic=mitigation-stream \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,CLOUD_ARMOR_POLICY_NAME=tokio-vga-policy,REDIS_ADDRESS=$REDIS_ADDRESS" \
    --project=$PROJECT_ID \
    --timeout=540s \
    --memory=512MB \
    --max-instances=10

cd ..

echo "✅ Atomic Blocker desplegado"
echo ""

# 7. Resumen final
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ DESPLIEGUE COMPLETADO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 Servicios desplegados:"
echo ""
echo "   🌀 VGA Engine (Cloud Run):"
VGA_URL=$(gcloud run services describe vga-engine --region=$REGION --project=$PROJECT_ID --format="value(status.url)" 2>/dev/null || echo "N/A")
echo "      URL: $VGA_URL"
echo ""
echo "   📊 Dashboard (Cloud Run):"
DASHBOARD_URL=$(gcloud run services describe vga-dashboard --region=$REGION --project=$PROJECT_ID --format="value(status.url)" 2>/dev/null || echo "N/A")
echo "      URL: $DASHBOARD_URL"
echo ""
echo "   🛡️  Atomic Blocker (Cloud Function):"
echo "      Trigger: mitigation-stream topic"
echo ""
echo "   🔴 Redis (Memorystore):"
echo "      Address: $REDIS_ADDRESS"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Próximos pasos:"
echo ""
echo "   1. Configurar ModSecurity para enviar logs a Pub/Sub (usar vga-log-ingestion)"
echo "   2. Acceder al Dashboard: $DASHBOARD_URL"
echo "   3. Verificar que VGA Engine esté procesando mensajes"
echo "   4. Probar comandos CLI en el dashboard: /vortex-status"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
