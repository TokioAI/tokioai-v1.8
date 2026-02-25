#!/bin/bash
# Script para reemplazar el logo de TOKIO AI en dashboard y página 403

if [ "$#" -ne 1 ]; then
    echo "Uso: $0 <ruta_al_logo_nuevo.png>"
    echo ""
    echo "Este script reemplazará el logo en:"
    echo "  - dashboard-api/static/logo.png"
    echo "  - modsecurity/html/logo.png"
    exit 1
fi

LOGO_FILE="$1"

if [ ! -f "$LOGO_FILE" ]; then
    echo "❌ Error: El archivo $LOGO_FILE no existe"
    exit 1
fi

echo "🔄 Reemplazando logos..."
echo ""

# Reemplazar en dashboard
cp "$LOGO_FILE" dashboard-api/static/logo.png
echo "✅ Logo reemplazado en: dashboard-api/static/logo.png"

# Reemplazar en modsecurity
cp "$LOGO_FILE" modsecurity/html/logo.png
echo "✅ Logo reemplazado en: modsecurity/html/logo.png"

echo ""
echo "✅ Logos reemplazados exitosamente!"
echo ""
echo "📝 Próximos pasos:"
echo "  1. Desplegar dashboard-api a GCP"
echo "  2. Reiniciar el contenedor de Nginx/ModSecurity para que cargue el nuevo logo"
