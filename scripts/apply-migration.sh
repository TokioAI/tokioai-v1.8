#!/bin/bash
# Script para aplicar migración de classification_source a PostgreSQL

echo "🔄 Aplicando migración: agregar columna classification_source..."

# Verificar si PostgreSQL está corriendo
if ! docker ps | grep -q soc-postgres; then
    echo "❌ PostgreSQL no está corriendo. Inicia el contenedor primero."
    exit 1
fi

# Aplicar migración
docker exec -i soc-postgres psql -U soc_user -d soc_ai < scripts/migrate-add-classification-source.sql

if [ $? -eq 0 ]; then
    echo "✅ Migración aplicada exitosamente"
else
    echo "❌ Error aplicando migración"
    exit 1
fi












