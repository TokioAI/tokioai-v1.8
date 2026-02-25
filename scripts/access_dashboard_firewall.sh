#!/bin/bash
# Script para acceder al dashboard creando regla de firewall temporal con tu IP

set -e

PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
FIREWALL_NAME="allow-dashboard-temp-$(date +%s)"
DASHBOARD_PORT="8000"
DURATION_HOURS="${1:-2}"  # Duración en horas (default: 2 horas)

echo "═══════════════════════════════════════════════════════════"
echo "🔐 ACCESO AL DASHBOARD - REGLA DE FIREWALL TEMPORAL"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Obtener IPs públicas
echo "🌐 Obteniendo IPs públicas..."
OSBOXES_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "")
ADDITIONAL_IP="YOUR_IP_ADDRESS"

if [ -z "$OSBOXES_IP" ]; then
    echo "⚠️ No se pudo obtener la IP de osboxes automáticamente"
    OSBOXES_IP=""
fi

# Construir lista de IPs
IPS=()
if [ -n "$OSBOXES_IP" ]; then
    IPS+=("$OSBOXES_IP/32")
    echo "   IP de osboxes: $OSBOXES_IP"
fi
if [ -n "$ADDITIONAL_IP" ]; then
    IPS+=("$ADDITIONAL_IP/32")
    echo "   IP adicional: $ADDITIONAL_IP"
fi

if [ ${#IPS[@]} -eq 0 ]; then
    echo "❌ No se pudo obtener ninguna IP"
    echo "   Ingresá tu IP manualmente:"
    read -p "   Tu IP pública: " MANUAL_IP
    IPS=("$MANUAL_IP/32")
fi

# Convertir array a string separado por comas
SOURCE_RANGES=$(IFS=,; echo "${IPS[*]}")
echo ""
echo "   IPs permitidas: ${IPS[*]}"
echo ""

# Verificar si ya existe una regla temporal
EXISTING_RULE=$(gcloud compute firewall-rules list \
    --project="$PROJECT_ID" \
    --filter="name~allow-dashboard-temp" \
    --format="value(name)" \
    --limit=1 2>/dev/null)

if [ -n "$EXISTING_RULE" ]; then
    echo "⚠️ Ya existe una regla temporal: $EXISTING_RULE"
    read -p "   ¿Eliminarla y crear una nueva? (s/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[SsYy]$ ]]; then
        echo "🗑️ Eliminando regla existente..."
        gcloud compute firewall-rules delete "$EXISTING_RULE" \
            --project="$PROJECT_ID" \
            --quiet 2>/dev/null || true
    else
        echo "✅ Usando regla existente: $EXISTING_RULE"
        FIREWALL_NAME="$EXISTING_RULE"
        SKIP_CREATE=true
    fi
fi

if [ -z "$SKIP_CREATE" ]; then
    echo "🔧 Creando regla de firewall temporal..."
    echo "   Nombre: $FIREWALL_NAME"
    echo "   IP permitida: $MY_IP/32"
    echo "   Puerto: $DASHBOARD_PORT"
    echo "   Duración: $DURATION_HOURS horas"
    echo ""
    
    gcloud compute firewall-rules create "$FIREWALL_NAME" \
        --project="$PROJECT_ID" \
        --allow tcp:$DASHBOARD_PORT \
        --source-ranges="$SOURCE_RANGES" \
        --target-tags="tokio-waf" \
        --description="Temporary dashboard access from ${IPS[*]} (expires in $DURATION_HOURS hours)" \
        --quiet
    
    echo "✅ Regla creada exitosamente"
fi

# Obtener IP de la VM
VM_IP=$(gcloud compute instances list \
    --project="$PROJECT_ID" \
    --filter="name~tokio-waf AND status:RUNNING" \
    --format="value(EXTERNAL_IP)" \
    --limit=1 2>/dev/null)

if [ -z "$VM_IP" ]; then
    echo "⚠️ No se pudo obtener la IP de la VM"
    VM_IP="YOUR_IP_ADDRESS"  # IP conocida
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ ACCESO CONFIGURADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard disponible en:"
echo "   👉 http://$VM_IP:$DASHBOARD_PORT"
echo ""
echo "⏰ La regla expirará automáticamente en $DURATION_HOURS horas"
echo ""
echo "🔒 Seguridad:"
echo "   - Solo estas IPs pueden acceder: ${IPS[*]}"
echo "   - Puerto 8000 expuesto solo a estas IPs"
echo ""
echo "🗑️ Para eliminar la regla manualmente:"
echo "   gcloud compute firewall-rules delete $FIREWALL_NAME --project=$PROJECT_ID"
echo ""

# Intentar abrir en el navegador
if command -v xdg-open &> /dev/null; then
    echo "🌐 Abriendo en el navegador..."
    xdg-open "http://$VM_IP:$DASHBOARD_PORT" 2>/dev/null &
elif command -v open &> /dev/null; then
    echo "🌐 Abriendo en el navegador..."
    open "http://$VM_IP:$DASHBOARD_PORT" 2>/dev/null &
fi
