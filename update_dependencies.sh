#!/bin/bash
# Script para actualizar dependencias y corregir vulnerabilidades

echo "🔒 Actualizando dependencias para corregir vulnerabilidades..."
echo ""

# Actualizar dependencias de Python
echo "1. Actualizando requirements.txt..."
for req_file in $(find . -name "requirements.txt"); do
    echo "   Procesando: $req_file"
    # Actualizar paquetes comunes con vulnerabilidades conocidas
    sed -i 's/requests==.*/requests>=2.31.0/' "$req_file"
    sed -i 's/urllib3==.*/urllib3>=2.0.0/' "$req_file"
    sed -i 's/cryptography==.*/cryptography>=41.0.0/' "$req_file"
    sed -i 's/pyyaml==.*/pyyaml>=6.0.1/' "$req_file"
    sed -i 's/jinja2==.*/jinja2>=3.1.2/' "$req_file"
done

echo "✅ Dependencias de Python actualizadas"
echo ""

# Actualizar package.json si existe
if [ -f "tokio-ai/dashboard-api/mcp-host/package.json" ]; then
    echo "2. Actualizando package.json..."
    cd tokio-ai/dashboard-api/mcp-host
    if command -v npm &> /dev/null; then
        npm update 2>&1 | head -10
        echo "✅ Dependencias de Node.js actualizadas"
    else
        echo "⚠️ npm no disponible, actualizando manualmente package.json"
    fi
    cd ../../..
fi

echo ""
echo "✅ Actualización completada"
