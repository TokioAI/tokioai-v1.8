#!/bin/bash
# Script para aplicar migración de episodios a PostgreSQL
# Sin romper el flujo actual

set -e

echo "📋 Aplicando migración de episodios..."
echo ""

# Variables de entorno (usar defaults si no están definidas)
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-soc_ai}"
POSTGRES_USER="${POSTGRES_USER:-soc_user}"
POSTGRES_PASSWORD = "YOUR_POSTGRES_PASSWORD"

MIGRATION_FILE="real-time-processor/migrations/create_episodes_tables.sql"

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: No se encuentra el archivo de migración: $MIGRATION_FILE"
    exit 1
fi

echo "🔍 Verificando conexión a PostgreSQL..."
echo "   Host: $POSTGRES_HOST"
echo "   Port: $POSTGRES_PORT"
echo "   Database: $POSTGRES_DB"
echo "   User: $POSTGRES_USER"
echo ""

# Exportar password para psql
export PGPASSWORD="$POSTGRES_PASSWORD"

# Verificar conexión
if ! psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" > /dev/null 2>&1; then
    echo "❌ Error: No se puede conectar a PostgreSQL"
    echo "   Verifica las credenciales y que el servidor esté corriendo"
    exit 1
fi

echo "✅ Conexión exitosa"
echo ""

# Verificar si las tablas ya existen
if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'episodes');" | grep -q t; then
    echo "⚠️  Advertencia: La tabla 'episodes' ya existe"
    read -p "¿Deseas continuar? Las tablas existentes NO serán modificadas (CREATE IF NOT EXISTS) [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Migración cancelada"
        exit 0
    fi
fi

echo "📦 Aplicando migración..."
echo ""

# Aplicar migración
if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$MIGRATION_FILE"; then
    echo ""
    echo "✅ Migración aplicada exitosamente"
    echo ""
    
    # Verificar que las tablas se crearon
    echo "🔍 Verificando tablas creadas..."
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
        SELECT 
            table_name,
            (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as columns
        FROM information_schema.tables t
        WHERE table_schema = 'public' 
        AND table_name IN ('episodes', 'analyst_labels', 'episode_similarity_cache')
        ORDER BY table_name;
    "
    
    echo ""
    echo "✅ Migración completa"
    echo ""
    echo "📊 Tablas creadas:"
    echo "   • episodes - Almacena episodios agrupados"
    echo "   • analyst_labels - Etiquetas humanas para entrenamiento"
    echo "   • episode_similarity_cache - Cache de similitud entre episodios"
    echo ""
    echo "🎯 Próximo paso: Desplegar el código actualizado"
    
else
    echo ""
    echo "❌ Error aplicando migración"
    exit 1
fi




