#!/bin/bash
# Script para copiar el script del túnel a la Raspberry Pi

RASPBERRY_IP="YOUR_IP_ADDRESS"
RASPBERRY_USER="${1:-pi}"  # Usuario por defecto: pi
SCRIPT_NAME="dashboard_tunel_red_local.sh"
SCRIPT_PATH="scripts/$SCRIPT_NAME"

echo "═══════════════════════════════════════════════════════════"
echo "📤 COPIANDO SCRIPT A RASPBERRY PI"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📋 Configuración:"
echo "   Raspberry IP: $RASPBERRY_IP"
echo "   Usuario: $RASPBERRY_USER"
echo "   Script: $SCRIPT_NAME"
echo ""

# Verificar que el script existe
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ Error: No se encuentra el script $SCRIPT_PATH"
    exit 1
fi

echo "1. Copiando script a la Raspberry..."
scp "$SCRIPT_PATH" $RASPBERRY_USER@$RASPBERRY_IP:~/ 2>&1

if [ $? -eq 0 ]; then
    echo "   ✅ Script copiado"
else
    echo "   ❌ Error al copiar el script"
    echo ""
    echo "💡 Alternativa: Copia manualmente el contenido del script"
    echo "   o ejecuta este comando desde la Raspberry:"
    echo ""
    echo "   curl -o dashboard_tunel_red_local.sh https://raw.githubusercontent.com/..."
    exit 1
fi

echo ""
echo "2. Haciendo el script ejecutable..."
ssh $RASPBERRY_USER@$RASPBERRY_IP "chmod +x ~/$SCRIPT_NAME" 2>&1

if [ $? -eq 0 ]; then
    echo "   ✅ Script ahora es ejecutable"
else
    echo "   ⚠️  No se pudo hacer ejecutable (puedes hacerlo manualmente)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ SCRIPT COPIADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🚀 Ahora desde la Raspberry ejecuta:"
echo "   ./dashboard_tunel_red_local.sh"
echo ""
echo "💡 O si prefieres, ejecuta directamente:"
echo "   ssh $RASPBERRY_USER@$RASPBERRY_IP './dashboard_tunel_red_local.sh'"
echo ""
