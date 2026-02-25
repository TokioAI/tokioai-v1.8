#!/bin/bash
# Script para ejecutar desde GCP Console (Cloud Shell) o desde una máquina con acceso SSH
# Verifica y arregla el acceso al dashboard

set -e

VM_NAME="${1:-tokio-waf-tokioia-com}"
VM_ZONE="${2:-us-central1-a}"
PROJECT_ID="${3:-YOUR_GCP_PROJECT_ID}"

echo "═══════════════════════════════════════════════════════════"
echo "🔧 DIAGNÓSTICO Y REPARACIÓN DEL DASHBOARD"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Ejecutar diagnóstico y reparación en la VM
gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --tunnel-through-iap \
    --command="
        cd /opt/tokio-waf
        
        echo '📋 1. Verificando contenedores...'
        docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'NAME|dashboard|postgres' || echo '⚠️ No se encontraron contenedores relacionados'
        
        echo ''
        echo '📋 2. Verificando si el dashboard está corriendo...'
        if docker ps | grep -q dashboard-api; then
            echo '✅ Contenedor dashboard-api está corriendo'
            docker ps | grep dashboard-api
        else
            echo '❌ Contenedor dashboard-api NO está corriendo'
            echo ''
            echo '🔄 Intentando iniciar el contenedor...'
            docker-compose up -d dashboard-api 2>&1 || docker compose up -d dashboard-api 2>&1
            sleep 5
            if docker ps | grep -q dashboard-api; then
                echo '✅ Dashboard iniciado exitosamente'
            else
                echo '❌ Error al iniciar el dashboard'
                echo '   Ver logs: docker-compose logs dashboard-api'
            fi
        fi
        
        echo ''
        echo '📋 3. Verificando puerto 8000...'
        if netstat -tlnp 2>/dev/null | grep -q ':8000' || ss -tlnp 2>/dev/null | grep -q ':8000'; then
            echo '✅ Puerto 8000 está escuchando'
            netstat -tlnp 2>/dev/null | grep ':8000' || ss -tlnp 2>/dev/null | grep ':8000'
        else
            echo '⚠️ Puerto 8000 NO está escuchando'
            echo '   El dashboard puede no estar iniciado correctamente'
        fi
        
        echo ''
        echo '📋 4. Verificando acceso local al dashboard...'
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo '✅ Dashboard responde en localhost:8000'
            curl -s http://localhost:8000/health
        else
            echo '❌ Dashboard NO responde en localhost:8000'
            echo '   Ver logs: docker-compose logs dashboard-api'
        fi
        
        echo ''
        echo '📋 5. Verificando configuración de nginx...'
        if grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '✅ Nginx tiene ruta /dashboard/ configurada'
        else
            echo '⚠️ Nginx NO tiene ruta /dashboard/ configurada'
            echo '   Ejecutar: ./scripts/add_dashboard_to_nginx_vm.sh'
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ DIAGNÓSTICO COMPLETADO'
        echo '═══════════════════════════════════════════════════════════'
    " 2>&1 || {
    echo ""
    echo "❌ Error: No se pudo acceder a la VM por SSH"
    echo ""
    echo "💡 INSTRUCCIONES MANUALES:"
    echo ""
    echo "1. Ir a GCP Console:"
    echo "   https://console.cloud.google.com/compute/instances?project=$PROJECT_ID"
    echo ""
    echo "2. Hacer clic en 'SSH' en la VM: $VM_NAME"
    echo ""
    echo "3. Ejecutar estos comandos:"
    echo ""
    echo "   cd /opt/tokio-waf"
    echo "   docker ps | grep dashboard"
    echo "   docker-compose up -d dashboard-api"
    echo "   curl http://localhost:8000/health"
    echo ""
    echo "4. Si el dashboard responde, verificar firewall:"
    echo "   La regla ya está creada: allow-dashboard-1771883416"
    echo ""
    echo "5. Acceder a: http://YOUR_IP_ADDRESS:8000"
    echo ""
    exit 1
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ PROCESO COMPLETADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Intentar acceder al dashboard:"
echo "   http://YOUR_IP_ADDRESS:8000"
echo ""
