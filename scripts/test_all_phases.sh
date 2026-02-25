#!/bin/bash
# Script de prueba para todas las fases del sistema SOC-AI-LAB

set -e

echo "🧪 Iniciando pruebas del sistema SOC-AI-LAB"
echo "=========================================="
echo ""

BASE_URL="http://localhost:9000"
TENANT_API_URL="http://localhost:8003"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para verificar respuesta
check_response() {
    local name=$1
    local response=$2
    
    if echo "$response" | grep -q '"success":true\|"status":"ok"'; then
        echo -e "${GREEN}✅ $name${NC}"
        return 0
    else
        echo -e "${RED}❌ $name${NC}"
        echo "$response" | head -5
        return 1
    fi
}

# Función para hacer request
make_request() {
    local method=$1
    local url=$2
    local data=$3
    
    if [ -z "$data" ]; then
        curl -s -X "$method" "$url"
    else
        curl -s -X "$method" "$url" -H "Content-Type: application/json" -d "$data"
    fi
}

echo "📊 Fase 1: Log Ingestion Layer"
echo "----------------------------"
echo ""

# Verificar Log Ingestion API
echo "Verificando Log Ingestion API..."
INGESTION_RESPONSE=$(make_request GET "$BASE_URL/health" 2>/dev/null || echo '{"status":"error"}')
check_response "Log Ingestion API" "$INGESTION_RESPONSE"

echo ""
echo "📊 Fase 2: Real-Time Processing"
echo "----------------------------"
echo ""

# Verificar Real-Time Processor (a través de logs en PostgreSQL)
echo "Verificando procesamiento en tiempo real..."
REALTIME_RESPONSE=$(make_request GET "$BASE_URL/api/real-time/stats" 2>/dev/null || echo '{"success":false}')
check_response "Real-Time Processing Stats" "$REALTIME_RESPONSE"

echo ""
echo "📊 Fase 3: Multi-Layer Mitigation"
echo "----------------------------"
echo ""

# Verificar estadísticas de mitigación
echo "Verificando auto-mitigación..."
MITIGATION_RESPONSE=$(make_request GET "$BASE_URL/api/auto-mitigation-stats" 2>/dev/null || echo '{"success":false}')
check_response "Auto-Mitigation Stats" "$MITIGATION_RESPONSE"

echo ""
echo "📊 Fase 4: Red Team Inteligente"
echo "----------------------------"
echo ""

# Verificar Red Team
echo "Verificando Red Team..."
REDTEAM_STATUS=$(make_request GET "$BASE_URL/api/redteam/status" 2>/dev/null || echo '{"status":"error"}')
check_response "Red Team Status" "$REDTEAM_STATUS"

# Verificar análisis inteligente
echo "Verificando análisis inteligente del WAF..."
INTELLIGENT_ANALYSIS=$(make_request GET "$BASE_URL/api/intelligent-redteam/analysis?tenant_id=default" 2>/dev/null || echo '{"success":false}')
check_response "Intelligent Red Team Analysis" "$INTELLIGENT_ANALYSIS"

# Verificar sugerencias
echo "Verificando sugerencias de mejora..."
SUGGESTIONS=$(make_request GET "$BASE_URL/api/intelligent-redteam/suggestions?tenant_id=default" 2>/dev/null || echo '{"success":false}')
check_response "Improvement Suggestions" "$SUGGESTIONS"

echo ""
echo "📊 Fase 5: Tenant Management"
echo "----------------------------"
echo ""

# Verificar Tenant Management API
echo "Verificando Tenant Management API..."
TENANT_HEALTH=$(make_request GET "$TENANT_API_URL/health" 2>/dev/null || echo '{"status":"error"}')
check_response "Tenant Management API" "$TENANT_HEALTH"

# Listar tenants
echo "Verificando listado de tenants..."
TENANTS=$(make_request GET "$BASE_URL/api/tenants" 2>/dev/null || echo '{"success":false}')
check_response "List Tenants" "$TENANTS"

echo ""
echo "📊 Dashboard General"
echo "----------------------------"
echo ""

# Verificar endpoints del dashboard
echo "Verificando estadísticas del dashboard..."
STATS=$(make_request GET "$BASE_URL/api/stats/summary?limit=100" 2>/dev/null || echo '{"success":false}')
check_response "Dashboard Stats" "$STATS"

echo "Verificando ataques recientes..."
ATTACKS=$(make_request GET "$BASE_URL/api/attacks/recent?limit=10" 2>/dev/null || echo '{"success":false}')
check_response "Recent Attacks" "$ATTACKS"

echo "Verificando incidentes..."
INCIDENTS=$(make_request GET "$BASE_URL/api/incidents?limit=10" 2>/dev/null || echo '{"success":false}')
check_response "Incidents" "$INCIDENTS"

echo "Verificando bypasses..."
BYPASSES=$(make_request GET "$BASE_URL/api/bypasses?limit=10" 2>/dev/null || echo '{"success":false}')
check_response "Bypasses" "$BYPASSES"

echo ""
echo "=========================================="
echo "✅ Pruebas completadas!"
echo ""
echo "📋 Resumen:"
echo "  - Fase 1: Log Ingestion ✅"
echo "  - Fase 2: Real-Time Processing ✅"
echo "  - Fase 3: Multi-Layer Mitigation ✅"
echo "  - Fase 4: Red Team Inteligente ✅"
echo "  - Fase 5: Tenant Management ✅"
echo "  - Dashboard: Integrado ✅"
echo ""
echo "🎯 Sistema listo para uso!"



