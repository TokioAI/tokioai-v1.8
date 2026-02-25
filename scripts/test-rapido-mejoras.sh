#!/bin/bash
# Test rápido sin conexión a BD (verifica archivos y código)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0

pass() { echo -e "${GREEN}✅ PASS:${NC} $1"; ((PASSED++)); }
fail() { echo -e "${RED}❌ FAIL:${NC} $1"; ((FAILED++)); }
info() { echo -e "${BLUE}ℹ️  INFO:${NC} $1"; }

echo ""
echo "🧪 TEST RÁPIDO - VERIFICACIÓN DE ARCHIVOS Y CÓDIGO"
echo "=================================================="
echo ""

# Test 1: Verificar módulos Python
echo "Test 1: Verificar Módulos Python"
echo "--------------------------------"

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
        
        if command -v python3 &> /dev/null; then
            if python3 -m py_compile "${MODULE}" 2>/dev/null; then
                pass "Sintaxis válida: ${MODULE}"
            else
                fail "Error de sintaxis: ${MODULE}"
            fi
        fi
    else
        fail "Módulo NO existe: ${MODULE}"
    fi
done

echo ""
echo "Test 2: Verificar Scripts"
echo "-------------------------"

SCRIPTS=(
    "scripts/sync-blocked-ips-to-nginx-optimized.py"
    "scripts/sync-rate-limits-to-nginx.py"
    "scripts/migration_improvements_weekend.sql"
)

for SCRIPT in "${SCRIPTS[@]}"; do
    if [ -f "${SCRIPT}" ]; then
        pass "Script existe: ${SCRIPT}"
        
        if [[ "$SCRIPT" == *.py ]] && command -v python3 &> /dev/null; then
            if python3 -m py_compile "${SCRIPT}" 2>/dev/null; then
                pass "Sintaxis válida: ${SCRIPT}"
            else
                fail "Error de sintaxis: ${SCRIPT}"
            fi
        fi
    else
        fail "Script NO existe: ${SCRIPT}"
    fi
done

echo ""
echo "Test 3: Verificar Integración en Procesador"
echo "-------------------------------------------"

PROCESSOR_FILE="real-time-processor/kafka_streams_processor.py"

if [ -f "$PROCESSOR_FILE" ]; then
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
        pass "Procesador verifica feature flag"
    else
        warn "Procesador NO verifica feature flag"
    fi
else
    fail "Archivo del procesador no encontrado"
fi

echo ""
echo "Test 4: Verificar Dashboard API"
echo "-------------------------------"

if [ -f "dashboard-api/app.py" ]; then
    if grep -q "/api/intelligent-stats" "dashboard-api/app.py"; then
        pass "Dashboard tiene endpoint /api/intelligent-stats"
    else
        fail "Dashboard NO tiene endpoint /api/intelligent-stats"
    fi
    
    if grep -q "/api/rate-limited-ips" "dashboard-api/app.py"; then
        pass "Dashboard tiene endpoint /api/rate-limited-ips"
    else
        fail "Dashboard NO tiene endpoint /api/rate-limited-ips"
    fi
else
    fail "dashboard-api/app.py no encontrado"
fi

echo ""
echo "Test 5: Verificar Dashboard Frontend"
echo "------------------------------------"

if [ -f "dashboard-api/static/index.html" ]; then
    if grep -q "tab-intelligent" "dashboard-api/static/index.html"; then
        pass "Dashboard tiene pestaña 'Sistema Inteligente'"
    else
        fail "Dashboard NO tiene pestaña 'Sistema Inteligente'"
    fi
    
    if grep -q "renderIntelligentStats" "dashboard-api/static/index.html"; then
        pass "Dashboard tiene función renderIntelligentStats"
    else
        fail "Dashboard NO tiene función renderIntelligentStats"
    fi
else
    fail "dashboard-api/static/index.html no encontrado"
fi

echo ""
echo "=========================================="
echo "RESUMEN"
echo "=========================================="
echo -e "${GREEN}✅ PASSED:${NC} ${PASSED}"
echo -e "${RED}❌ FAILED:${NC} ${FAILED}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ TODOS LOS TESTS PASARON${NC}"
    echo ""
    echo "📋 Próximos pasos:"
    echo "1. Ejecutar migraciones SQL manualmente si es necesario"
    echo "2. Verificar que los builds de Cloud Build completen"
    echo "3. Verificar dashboard cuando esté desplegado"
    exit 0
else
    echo -e "${RED}❌ ALGUNOS TESTS FALLARON${NC}"
    exit 1
fi
