#!/bin/bash
# Script para aplicar la migración de intelligence_analysis a la tabla episodes

set -e

POSTGRES_HOST="${POSTGRES_HOST:-postgres-persistence}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-soc_ai}"
POSTGRES_USER="${POSTGRES_USER:-soc_user}"
POSTGRES_PASSWORD = "YOUR_POSTGRES_PASSWORD"

echo "🔄 Aplicando migración: intelligence_analysis a episodes..."

export PGPASSWORD="$POSTGRES_PASSWORD"

psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f add_intelligence_analysis_to_episodes.sql

echo "✅ Migración aplicada exitosamente!"

