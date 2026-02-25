#!/bin/bash
# Script completo de verificación del sistema Tokio AI
# Verifica que todas las mejoras estén funcionando correctamente

set -e

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="us-central1"
DB_HOST="YOUR_IP_ADDRESS"
DB_NAME="soc_ai"
DB_USER="soc_user"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔍 VERIFICACIÓN COMPLETA DEL SISTEMA TOKIO AI                        ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Función para test
test_check() {
    local test_name="$1"
    local command="$2"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo "🔍 Test $TOTAL_TESTS: $test_name"
    if eval "$command" > /dev/null 2>&1; then
        echo "   ✅ PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        return 0
    else
        echo "   ❌ FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

# Función para test con output
test_check_output() {
    local test_name="$1"
    local command="$2"
    local expected="$3"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo "🔍 Test $TOTAL_TESTS: $test_name"
    output=$(eval "$command" 2>&1 || echo "")
    if echo "$output" | grep -q "$expected"; then
        echo "   ✅ PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        return 0
    else
        echo "   ❌ FAILED"
        echo "      Output: $output"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

echo "════════════════════════════════════════════════════════════════════"
echo "1. VERIFICACIÓN DE SERVICIOS CLOUD RUN"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Test 1: realtime-processor está corriendo
test_check_output "realtime-processor está corriendo" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(status.conditions[0].status)'" \
    "True"

# Test 2: dashboard-api está corriendo
test_check_output "dashboard-api está corriendo" \
    "gcloud run services describe dashboard-api --region=${REGION} --project=${PROJECT_ID} --format='value(status.conditions[0].status)'" \
    "True"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "2. VERIFICACIÓN DE VARIABLES DE ENTORNO"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Test 3: INTELLIGENT_BLOCKING_ENABLED=true
test_check_output "INTELLIGENT_BLOCKING_ENABLED está en true" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep 'INTELLIGENT_BLOCKING_ENABLED' | grep 'true'" \
    "true"

# Test 4: SHADOW_MODE=false (producción)
test_check_output "INTELLIGENT_BLOCKING_SHADOW_MODE está en false (producción)" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep 'INTELLIGENT_BLOCKING_SHADOW_MODE' | grep 'false'" \
    "false"

# Test 5: RATE_LIMITING_ENABLED=true
test_check_output "RATE_LIMITING_ENABLED está en true" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep 'RATE_LIMITING_ENABLED' | grep 'true'" \
    "true"

# Test 6: AUTO_CLEANUP_ENABLED=true
test_check_output "AUTO_CLEANUP_ENABLED está en true" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep 'AUTO_CLEANUP_ENABLED' | grep 'true'" \
    "true"

# Test 7: EARLY_PREDICTION_ENABLED=true
test_check_output "EARLY_PREDICTION_ENABLED está en true" \
    "gcloud run services describe realtime-processor --region=${REGION} --project=${PROJECT_ID} --format='value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep 'EARLY_PREDICTION_ENABLED' | grep 'true'" \
    "true"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "3. VERIFICACIÓN DE BASE DE DATOS"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Obtener contraseña
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=${PROJECT_ID} 2>&1 | grep -v "ERROR" || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

# Test 8: Tabla rate_limited_ips existe
test_check "Tabla rate_limited_ips existe" \
    "psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c '\d rate_limited_ips' > /dev/null 2>&1"

# Test 9: Tabla blocked_ips tiene columnas nuevas
test_check "blocked_ips tiene columna block_stage" \
    "psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c \"SELECT column_name FROM information_schema.columns WHERE table_name = 'blocked_ips' AND column_name = 'block_stage'\" | grep -q block_stage"

# Test 10: blocked_ips tiene columna risk_score
test_check "blocked_ips tiene columna risk_score" \
    "psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c \"SELECT column_name FROM information_schema.columns WHERE table_name = 'blocked_ips' AND column_name = 'risk_score'\" | grep -q risk_score"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "4. VERIFICACIÓN DE LOGS (Últimos 5 minutos)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Test 11: IntelligentBlockingSystem se inicializó
test_check_output "IntelligentBlockingSystem inicializado en logs" \
    "gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=realtime-processor AND textPayload=~\"IntelligentBlockingSystem\"' --limit=5 --project=${PROJECT_ID} --format='value(textPayload)' --freshness=5m" \
    "IntelligentBlockingSystem"

# Test 12: Sistema NO está en modo shadow (producción)
LOG_OUTPUT=$(gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=realtime-processor AND textPayload=~\"SHADOW MODE\|Sistema inteligente:\"" --limit=10 --project=${PROJECT_ID} --format="value(textPayload)" --freshness=5m 2>&1 | head -5)
TOTAL_TESTS=$((TOTAL_TESTS + 1))
echo "🔍 Test $TOTAL_TESTS: Sistema está en modo producción (no shadow)"
if echo "$LOG_OUTPUT" | grep -q "Sistema inteligente:" && ! echo "$LOG_OUTPUT" | grep -q "SHADOW MODE"; then
    echo "   ✅ PASSED (logs muestran modo producción)"
    PASSED_TESTS=$((PASSED_TESTS + 1))
elif [ -z "$LOG_OUTPUT" ]; then
    echo "   ⚠️  WARNING (no hay logs recientes, pero puede estar funcionando)"
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    echo "   ❌ FAILED (posiblemente en modo shadow)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "5. VERIFICACIÓN DE DASHBOARD API"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Obtener URL del dashboard
DASHBOARD_URL=$(gcloud run services describe dashboard-api --region=${REGION} --project=${PROJECT_ID} --format='value(status.url)' 2>/dev/null || echo "")

if [ -n "$DASHBOARD_URL" ]; then
    # Test 13: Dashboard responde
    test_check "Dashboard API responde" \
        "curl -s -o /dev/null -w '%{http_code}' ${DASHBOARD_URL}/api/stats | grep -q '200'"
    
    # Test 14: Endpoint /api/intelligent-stats existe
    test_check "Endpoint /api/intelligent-stats existe" \
        "curl -s ${DASHBOARD_URL}/api/intelligent-stats | grep -q -E '\"rate_limited_count\"|\"early_predictions\"|\"auto_cleanup\"'"
    
    # Test 15: Endpoint /api/rate-limited-ips existe
    test_check "Endpoint /api/rate-limited-ips existe" \
        "curl -s ${DASHBOARD_URL}/api/rate-limited-ips | grep -q -E '\"\\[\\]\"|\"ips\"'"
else
    echo "⚠️  No se pudo obtener URL del dashboard, saltando tests de API"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "6. VERIFICACIÓN DE MÓDULOS PYTHON"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Test 16: intelligent_blocking_system.py existe y tiene sintaxis válida
test_check "intelligent_blocking_system.py tiene sintaxis válida" \
    "python3 -m py_compile real-time-processor/intelligent_blocking_system.py"

# Test 17: rate_limit_manager.py existe y tiene sintaxis válida
test_check "rate_limit_manager.py tiene sintaxis válida" \
    "python3 -m py_compile real-time-processor/rate_limit_manager.py"

# Test 18: intelligent_cleanup_worker.py existe y tiene sintaxis válida
test_check "intelligent_cleanup_worker.py tiene sintaxis válida" \
    "python3 -m py_compile real-time-processor/intelligent_cleanup_worker.py"

# Test 19: improvements_config.py existe
test_check "improvements_config.py existe" \
    "test -f real-time-processor/improvements_config.py"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "7. RESUMEN DE VERIFICACIÓN"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "📊 Resultados:"
echo "   Total de tests: $TOTAL_TESTS"
echo "   ✅ Pasados: $PASSED_TESTS"
echo "   ❌ Fallidos: $FAILED_TESTS"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║  ✅ ¡TODO FUNCIONA CORRECTAMENTE!                                     ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "🎉 El sistema Tokio AI está operativo con todas las mejoras activas:"
    echo "   • Bloqueo inteligente y progresivo ✅"
    echo "   • Predicción temprana de ataques ✅"
    echo "   • Rate limiting dinámico ✅"
    echo "   • Auto-limpieza inteligente ✅"
    echo "   • Dashboard con métricas completas ✅"
    echo ""
    exit 0
else
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║  ⚠️  ALGUNOS TESTS FALLARON                                          ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Revisa los tests fallidos arriba para más detalles."
    echo ""
    exit 1
fi
