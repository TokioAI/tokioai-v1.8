#!/bin/bash
# Script de diagnóstico para ejecutar desde la Raspberry Pi
# Verifica conectividad con la VM de GCP

VM_IP="YOUR_IP_ADDRESS"
PROJECT_ID="YOUR_GCP_PROJECT_ID"

echo "═══════════════════════════════════════════════════════════"
echo "🔍 DIAGNÓSTICO DE ACCESO DESDE RASPBERRY PI"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Obtener IP pública actual
MY_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null || echo "NO_DETECTADA")
echo "1. Tu IP pública actual: $MY_IP"
echo ""

# Verificar conectividad básica
echo "2. Verificando conectividad básica..."
if ping -c 2 -W 2 $VM_IP > /dev/null 2>&1; then
    echo "   ✅ Ping a $VM_IP: OK"
else
    echo "   ❌ Ping a $VM_IP: FALLO"
    echo "   (Esto es normal, GCP puede bloquear ICMP)"
fi
echo ""

# Probar puertos
echo "3. Probando puertos..."
for port in 80 443 8000 22; do
    if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/$port" 2>/dev/null; then
        echo "   ✅ Puerto $port: ABIERTO"
    else
        echo "   ❌ Puerto $port: CERRADO o NO RESPONDE"
    fi
done
echo ""

# Probar HTTP
echo "4. Probando HTTP (puerto 80)..."
HTTP_RESPONSE=$(timeout 5 curl -s -I http://$VM_IP/ 2>&1)
if echo "$HTTP_RESPONSE" | grep -q "HTTP"; then
    echo "   ✅ HTTP responde:"
    echo "$HTTP_RESPONSE" | head -3 | sed 's/^/      /'
else
    echo "   ❌ HTTP no responde"
    echo "   Error: $HTTP_RESPONSE" | head -2 | sed 's/^/      /'
fi
echo ""

# Probar Dashboard
echo "5. Probando Dashboard (puerto 8000)..."
DASH_RESPONSE=$(timeout 5 curl -s -I http://$VM_IP:8000/health 2>&1)
if echo "$DASH_RESPONSE" | grep -q "HTTP"; then
    echo "   ✅ Dashboard responde:"
    echo "$DASH_RESPONSE" | head -3 | sed 's/^/      /'
else
    echo "   ❌ Dashboard no responde"
    echo "   Error: $DASH_RESPONSE" | head -2 | sed 's/^/      /'
fi
echo ""

# Verificar firewall rules en GCP
echo "6. Verificando firewall rules en GCP..."
echo "   (Requiere gcloud configurado)"
if command -v gcloud > /dev/null 2>&1; then
    RULES=$(gcloud compute firewall-rules list --project=$PROJECT_ID --filter="sourceRanges:$MY_IP/32" --format="value(name)" 2>&1)
    if [ -n "$RULES" ]; then
        echo "   ✅ Firewall rules encontradas para tu IP:"
        echo "$RULES" | sed 's/^/      - /'
    else
        echo "   ⚠️  No se encontraron firewall rules para tu IP: $MY_IP"
        echo "      Ejecuta: ./scripts/actualizar_acceso_raspberry.sh"
    fi
else
    echo "   ⚠️  gcloud no está instalado (no se puede verificar)"
fi
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "📋 RESUMEN"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Si los puertos están cerrados:"
echo "   1. Verifica que tu IP sea: $MY_IP"
echo "   2. Ejecuta desde aquí: ./scripts/actualizar_acceso_raspberry.sh"
echo "   3. Espera 30-60 segundos para que se propaguen las reglas"
echo ""
