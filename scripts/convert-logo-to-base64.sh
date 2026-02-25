#!/bin/bash
# Script para convertir logo a base64 para usar en 403-blocked.html

if [ "$#" -ne 1 ]; then
    echo "Uso: $0 <ruta_al_logo.png>"
    exit 1
fi

LOGO_FILE="$1"

if [ ! -f "$LOGO_FILE" ]; then
    echo "❌ Error: El archivo $LOGO_FILE no existe"
    exit 1
fi

echo "🔄 Convirtiendo $LOGO_FILE a base64..."
BASE64=$(base64 -w 0 "$LOGO_FILE" 2>/dev/null || base64 "$LOGO_FILE")

echo ""
echo "✅ Base64 generado:"
echo ""
echo "$BASE64"
echo ""
echo "📋 Copia el contenido de arriba y reemplázalo en modsecurity/html/403-blocked.html"
echo "   (línea 312, dentro del atributo src=\"data:image/png;base64,...\")"
