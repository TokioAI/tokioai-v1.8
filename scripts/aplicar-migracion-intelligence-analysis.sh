#!/bin/bash
# Script para aplicar migración de intelligence_analysis a Cloud SQL
# Este script requiere que tengas acceso a Cloud SQL con la contraseña

set -e

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
INSTANCE_NAME="tokio-ai-postgres"
DB_NAME="soc_ai"
DB_USER="soc_user"
MIGRATION_FILE="real-time-processor/migrations/add_intelligence_analysis_to_episodes.sql"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: PROJECT_ID no configurado"
    echo "   Ejecuta: gcloud config set project PROJECT_ID"
    exit 1
fi

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: No se encuentra el archivo de migración: $MIGRATION_FILE"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔄 APLICANDO MIGRACIÓN: intelligence_analysis a episodes          ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "PROJECT_ID: $PROJECT_ID"
echo "INSTANCE: $INSTANCE_NAME"
echo "DATABASE: $DB_NAME"
echo "USER: $DB_USER"
echo ""

# Verificar que la instancia existe
echo "📋 Verificando instancia Cloud SQL..."
if ! gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT_ID" > /dev/null 2>&1; then
    echo "❌ Error: Instancia Cloud SQL '$INSTANCE_NAME' no encontrada"
    exit 1
fi

echo "✅ Instancia encontrada"
echo ""

# Obtener la IP pública de la instancia
echo "📋 Obteniendo IP de la instancia..."
INSTANCE_IP=$(gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT_ID" --format="value(ipAddresses[0].ipAddress)" 2>/dev/null || echo "")

if [ -z "$INSTANCE_IP" ]; then
    echo "⚠️  No se pudo obtener IP automáticamente"
    echo ""
    echo "📋 Aplicando migración usando gcloud sql connect..."
    echo "   (Necesitarás ingresar la contraseña cuando se solicite)"
    echo ""
    
    # Intentar con gcloud sql connect (requiere contraseña interactiva)
    gcloud sql connect "$INSTANCE_NAME" \
        --user="$DB_USER" \
        --database="$DB_NAME" \
        --project="$PROJECT_ID" < "$MIGRATION_FILE" || {
        echo ""
        echo "❌ Error aplicando migración"
        echo ""
        echo "📋 Alternativa: Aplicar manualmente"
        echo ""
        echo "1. Conéctate manualmente:"
        echo "   gcloud sql connect $INSTANCE_NAME --user=$DB_USER --database=$DB_NAME"
        echo ""
        echo "2. Copia y pega el contenido de: $MIGRATION_FILE"
        echo ""
        echo "3. O ejecuta directamente:"
        echo "   psql -h $INSTANCE_IP -U $DB_USER -d $DB_NAME -f $MIGRATION_FILE"
        exit 1
    }
else
    echo "✅ IP encontrada: $INSTANCE_IP"
    echo ""
    
    # Intentar con PGPASSWORD si está disponible
    if [ -n "$POSTGRES_PASSWORD" ]; then
        echo "📋 Aplicando migración usando PGPASSWORD..."
        export PGPASSWORD="$POSTGRES_PASSWORD"
        psql -h "$INSTANCE_IP" -U "$DB_USER" -d "$DB_NAME" -f "$MIGRATION_FILE" && {
            echo ""
            echo "✅ Migración aplicada exitosamente!"
        } || {
            echo ""
            echo "⚠️  Error con PGPASSWORD, intentando método alternativo..."
            unset PGPASSWORD
        }
    fi
    
    # Si PGPASSWORD no funcionó, intentar con gcloud sql connect
    if [ -z "$POSTGRES_PASSWORD" ] || [ $? -ne 0 ]; then
        echo "📋 Aplicando migración usando gcloud sql connect..."
        echo "   (Necesitarás ingresar la contraseña cuando se solicite)"
        echo ""
        
        gcloud sql connect "$INSTANCE_NAME" \
            --user="$DB_USER" \
            --database="$DB_NAME" \
            --project="$PROJECT_ID" < "$MIGRATION_FILE" || {
            echo ""
            echo "❌ Error aplicando migración"
            echo ""
            echo "📋 Aplicar manualmente:"
            echo ""
            echo "Opción 1: Con gcloud sql connect"
            echo "   gcloud sql connect $INSTANCE_NAME --user=$DB_USER --database=$DB_NAME"
            echo "   Luego copia y pega el contenido de: $MIGRATION_FILE"
            echo ""
            echo "Opción 2: Con psql directo (si tienes acceso de red)"
            echo "   export PGPASSWORD='tu_contraseña'"
            echo "   psql -h $INSTANCE_IP -U $DB_USER -d $DB_NAME -f $MIGRATION_FILE"
            exit 1
        }
    fi
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ MIGRACIÓN APLICADA EXITOSAMENTE                                 ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Verifica que la columna existe:"
echo "   gcloud sql connect $INSTANCE_NAME --user=$DB_USER --database=$DB_NAME"
echo "   \\d episodes"
echo ""

