#!/bin/bash
set -e

# Script completo de testing y verificación de mejoras
# Verifica que todas las mejoras funcionen correctamente

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="us-central1"
DATABASE_NAME="soc_ai"
DB_USER="soc_user"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Contadores
PASSED=0
FAILED=0
WARNINGS=0

# Funciones de utilidad
pass() {
    echo -e "${GREEN}✅ PASS:${NC} $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}❌ FAIL:${NC} $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠️  WARN:${NC} $1"
    ((WARNINGS++))
}

info() {
    echo -e "${BLUE}ℹ️  INFO:${NC} $1"
}

section() {
    echo ""
    echo "=========================================="
    echo "$1"
    echo "=========================================="
    echo ""
}

# Test 1: Verificar migraciones SQL
test_sql_migrations() {
    section "Test 1: Verificar Migraciones SQL"
    
    # Verificar tabla rate_limited_ips
    info "Verificando tabla rate_limited_ips..."
    
    CLOUD_SQL_IP=$(gcloud sql instances describe "tokio-ai-postgres" \
        --project="${PROJECT_ID}" \
        --format="value(ipAddresses[0].ipAddress)" 2>/dev/null || echo "")
    
    if [ -z "$CLOUD_SQL_IP" ]; then
        warn "No se pudo obtener IP de Cloud SQL"
        return
    fi
    
    if command -v psql &> /dev/null; then
        export PGPASSWORD="${DB_PASSWORD:-YOUR_POSTGRES_PASSWORD}"
        
        # Verificar tabla rate_limited_ips
        TABLE_EXISTS=$(psql -h "${CLOUD_SQL_IP}" -U "${DB_USER}" -d "${DATABASE_NAME}" \
            -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'rate_limited_ips');" 2>/dev/null || echo "false")
        
        if [ "$TABLE_EXISTS" = "t" ]; then
            pass "Tabla rate_limited_ips existe"
        else
            fail "Tabla rate_limited_ips NO existe"
        fi
        
        # Verificar columnas en blocked_ips
        BLOCK_STAGE_COL=$(psql -h "${CLOUD_SQL_IP}" -U "${DB_USER}" -d "${DATABASE_NAME}" \
            -tAc "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'blocked_ips' AND column_name = 'block_stage');" 2>/dev/null || echo "false")
        
        if [ "$BLOCK_STAGE_COL" = "t" ]; then
            pass "Columna block_stage existe en blocked_ips"
        else
            fail "Columna block_stage NO existe en blocked_ips"
        fi
        
        RISK_SCORE_COL=$(psql -h "${CLOUD_SQL_IP}" -U "${DB_USER}" -d "${DATABASE_NAME}" \
            -tAc "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'blocked_ips' AND column_name = 'risk_score');" 2>/dev/null || echo "false")
        
        if [ "$RISK_SCORE_COL" = "t" ]; then
            pass "Columna risk_score existe en blocked_ips"
        else
            fail "Columna risk_score NO existe en blocked_ips"
        fi
    else
        warn "psql no disponible, saltando verificación SQL"
    fi
}

# Test 2: Verificar servicios Cloud Run
test_cloud_run_services() {
    section "Test 2: Verificar Servicios Cloud Run"
    
    SERVICES=("realtime-processor" "dashboard-api")
    
    for SERVICE in "${SERVICES[@]}"; do
        info "Verificando ${SERVICE}..."
        
        STATUS=$(gcloud run services describe "${SERVICE}" \
            --region="${REGION}" \
            --project="${PROJECT_ID}" \
            --format="value(status.conditions[0].status)" 2>/dev/null || echo "UNKNOWN")
        
        if [ "$STATUS" = "True" ]; then
            pass "${SERVICE} está activo"
            
            # Verificar variables de entorno
            ENV_VARS=$(gcloud run services describe "${SERVICE}" \
                --region="${REGION}" \
                --project="${PROJECT_ID}" \
                --format="value(spec.template.spec.containers[0].env)" 2>/dev/null || echo "")
            
            if [[ "$ENV_VARS" == *"INTELLIGENT_BLOCKING_ENABLED"* ]]; then
                pass "${SERVICE} tiene variables de entorno de mejoras configuradas"
            else
                warn "${SERVICE} NO tiene variables de entorno de mejoras (puede estar usando valores por defecto)"
            fi
        else
            fail "${SERVICE} NO está activo o no se puede verificar"
        fi
    done
}

# Test 3: Verificar módulos Python
test_python_modules() {
    section "Test 3: Verificar Módulos Python"
    
    MODULES=(
        "real-time-processor/intelligent_blocking_system.py"
        "real-time-processor/intelligent_cleanup_worker.py"
        "real-time-processor/rate_limit_manager.py"
        "real-time-processor/behavior_fingerprinter.py"
        "real-time-processor/distributed_attack_correlator.py"
        "real-time-processor/dynamic_whitelist.py"
        "real-time-processor/improvements_config.py"
    )
    
    for MODULE in "${MODULES[@]}"; do
        if [ -f "${MODULE}" ]; then
            pass "Módulo existe: ${MODULE}"
            
            # Verificar sintaxis Python básica
            if command -v python3 &> /dev/null; then
                python3 -m py_compile "${MODULE}" 2>/dev/null && \
                    pass "Sintaxis válida: ${MODULE}" || \
                    fail "Error de sintaxis: ${MODULE}"
            fi
        else
            fail "Módulo NO existe: ${MODULE}"
        fi
    done
}

# Test 4: Verificar scripts de sincronización
test_sync_scripts() {
    section "Test 4: Verificar Scripts de Sincronización"
    
    SCRIPTS=(
        "scripts/sync-blocked-ips-to-nginx-optimized.py"
        "scripts/sync-rate-limits-to-nginx.py"
    )
    
    for SCRIPT in "${SCRIPTS[@]}"; do
        if [ -f "${SCRIPT}" ]; then
            pass "Script existe: ${SCRIPT}"
            
            # Verificar que es ejecutable
            if [ -x "${SCRIPT}" ]; then
                pass "Script es ejecutable: ${SCRIPT}"
            else
                warn "Script NO es ejecutable: ${SCRIPT}"
                info "Ejecuta: chmod +x ${SCRIPT}"
            fi
            
            # Verificar sintaxis Python
            if command -v python3 &> /dev/null; then
                python3 -m py_compile "${SCRIPT}" 2>/dev/null && \
                    pass "Sintaxis válida: ${SCRIPT}" || \
                    fail "Error de sintaxis: ${SCRIPT}"
            fi
        else
            fail "Script NO existe: ${SCRIPT}"
        fi
    done
}

# Test 5: Verificar endpoints del Dashboard API
test_dashboard_endpoints() {
    section "Test 5: Verificar Endpoints del Dashboard API"
    
    DASHBOARD_URL=$(gcloud run services describe dashboard-api \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --format="value(status.url)" 2>/dev/null || echo "")
    
    if [ -z "$DASHBOARD_URL" ]; then
        warn "No se pudo obtener URL del dashboard"
        return
    fi
    
    info "Dashboard URL: ${DASHBOARD_URL}"
    
    # Test endpoint de health
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${DASHBOARD_URL}/health" 2>/dev/null || echo "000")
    
    if [ "$HTTP_CODE" = "200" ]; then
        pass "Endpoint /health responde correctamente"
    else
        fail "Endpoint /health NO responde (HTTP ${HTTP_CODE})"
    fi
    
    # Test endpoint intelligent-stats (puede requerir auth)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${DASHBOARD_URL}/api/intelligent-stats" 2>/dev/null || echo "000")
    
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
        pass "Endpoint /api/intelligent-stats existe (HTTP ${HTTP_CODE})"
    else
        fail "Endpoint /api/intelligent-stats NO responde (HTTP ${HTTP_CODE})"
    fi
    
    # Test endpoint rate-limited-ips
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${DASHBOARD_URL}/api/rate-limited-ips" 2>/dev/null || echo "000")
    
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
        pass "Endpoint /api/rate-limited-ips existe (HTTP ${HTTP_CODE})"
    else
        fail "Endpoint /api/rate-limited-ips NO responde (HTTP ${HTTP_CODE})"
    fi
}

# Test 6: Verificar integración en kafka_streams_processor
test_processor_integration() {
    section "Test 6: Verificar Integración en Procesador"
    
    PROCESSOR_FILE="real-time-processor/kafka_streams_processor.py"
    
    if [ -f "$PROCESSOR_FILE" ]; then
        # Verificar que importa los módulos nuevos
        if grep -q "from intelligent_blocking_system import" "$PROCESSOR_FILE"; then
            pass "Procesador importa IntelligentBlockingSystem"
        else
            fail "Procesador NO importa IntelligentBlockingSystem"
        fi
        
        if grep -q "from rate_limit_manager import" "$PROCESSOR_FILE"; then
            pass "Procesador importa RateLimitManager"
        else
            fail "Procesador NO importa RateLimitManager"
        fi
        
        if grep -q "ENABLE_INTELLIGENT_BLOCKING" "$PROCESSOR_FILE"; then
            pass "Procesador verifica feature flag INTELLIGENT_BLOCKING_ENABLED"
        else
            warn "Procesador NO verifica feature flag (puede estar hardcodeado)"
        fi
    else
        fail "Archivo del procesador no encontrado: ${PROCESSOR_FILE}"
    fi
}

# Test 7: Verificar logs recientes
test_recent_logs() {
    section "Test 7: Verificar Logs Recientes"
    
    info "Buscando logs de realtime-processor (últimos 10 minutos)..."
    
    LOG_COUNT=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=realtime-processor AND timestamp>=\"$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit=10 \
        --project="${PROJECT_ID}" \
        --format="value(textPayload)" 2>/dev/null | wc -l)
    
    if [ "$LOG_COUNT" -gt 0 ]; then
        pass "Se encontraron ${LOG_COUNT} logs recientes del procesador"
        
        # Buscar logs específicos de mejoras
        if gcloud logging read \
            "resource.type=cloud_run_revision AND resource.labels.service_name=realtime-processor AND (textPayload=~\"IntelligentBlockingSystem\" OR textPayload=~\"RateLimitManager\")" \
            --limit=5 \
            --project="${PROJECT_ID}" \
            --format="value(textPayload)" 2>/dev/null | grep -q .; then
            pass "Se encontraron logs relacionados con mejoras inteligentes"
        else
            warn "NO se encontraron logs relacionados con mejoras (puede que aún no se hayan activado)"
        fi
    else
        warn "NO se encontraron logs recientes del procesador"
    fi
}

# Ejecutar todos los tests
main() {
    echo ""
    echo "🧪 TESTING Y VERIFICACIÓN DE MEJORAS"
    echo "====================================="
    echo ""
    
    test_sql_migrations
    test_cloud_run_services
    test_python_modules
    test_sync_scripts
    test_dashboard_endpoints
    test_processor_integration
    test_recent_logs
    
    # Resumen
    echo ""
    echo "=========================================="
    echo "RESUMEN DE TESTS"
    echo "=========================================="
    echo -e "${GREEN}✅ PASSED:${NC} ${PASSED}"
    echo -e "${RED}❌ FAILED:${NC} ${FAILED}"
    echo -e "${YELLOW}⚠️  WARNINGS:${NC} ${WARNINGS}"
    echo ""
    
    if [ $FAILED -eq 0 ]; then
        echo -e "${GREEN}✅ TODOS LOS TESTS CRÍTICOS PASARON${NC}"
        echo ""
        echo "📋 Próximos pasos:"
        echo "1. Verificar dashboard manualmente"
        echo "2. Monitorear logs en modo shadow"
        echo "3. Activar modo producción cuando estés listo"
        exit 0
    else
        echo -e "${RED}❌ ALGUNOS TESTS FALLARON${NC}"
        echo ""
        echo "Revisa los errores arriba y corrige antes de continuar"
        exit 1
    fi
}

# Ejecutar
main
