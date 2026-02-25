#!/bin/bash

# Script para lanzar ataques de prueba y medir capacidad del sistema
# Prueba detección en tiempo real y calcula logs/ataques por segundo

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

DOMAIN="${1:-localhost:8080}"
TENANT_ID="${2:-1}"
CONCURRENT="${3:-10}"
REQUESTS_PER_SEC="${4:-100}"
DURATION="${5:-30}"  # segundos

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧪 BENCHMARK DE CAPACIDAD - TEST DE ATAQUES                     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Configuración:${NC}"
echo -e "   Target: ${BLUE}$DOMAIN${NC}"
echo -e "   Tenant ID: ${BLUE}$TENANT_ID${NC}"
echo -e "   Concurrentes: ${BLUE}$CONCURRENT${NC}"
echo -e "   Requests/segundo: ${BLUE}$REQUESTS_PER_SEC${NC}"
echo -e "   Duración: ${BLUE}${DURATION}s${NC}"
echo ""

# Obtener timestamp inicial
START_TIME=$(date +%s)
START_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")
START_BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true AND created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")

echo -e "${YELLOW}[1/5] Estado inicial...${NC}"
echo -e "   Logs en últimos 60s: ${BLUE}$START_LOGS${NC}"
echo -e "   Bloqueados en últimos 60s: ${BLUE}$START_BLOCKED${NC}"
echo ""

# Patrones de ataque
declare -a ATTACKS=(
    "/test?id=1 OR 1=1 UNION SELECT * FROM users"
    "/search?q=<script>alert(document.cookie)</script>"
    "/admin/../../../etc/passwd"
    "/cmd.php?exec=cat /etc/passwd"
    "/api/users?id=1' UNION SELECT username, password FROM users--"
    "/test?q=<img src=x onerror=alert(1)>"
    "/login?id=1 OR '1'='1"
    "/file.php?file=../../../../windows/win.ini"
    "/eval.php?code=system('ls -la')"
    "/include.php?page=php://filter/read=string.rot13/resource=index.php"
)

# Función para enviar ataque
send_attack() {
    local url="$1"
    local attack="$2"
    curl -s -o /dev/null -w "%{http_code}" \
        -H "Host: $DOMAIN" \
        -H "User-Agent: python-requests/2.31.0" \
        --max-time 2 \
        "$url$attack" 2>/dev/null || echo "000"
}

echo -e "${YELLOW}[2/5] Lanzando ataques...${NC}"
echo -e "${BLUE}⏳ Ejecutando por ${DURATION}s...${NC}"

# Calcular total de requests
TOTAL_REQUESTS=$((REQUESTS_PER_SEC * DURATION))
REQUESTS_SENT=0
ATTACK_INDEX=0

# Lanzar ataques en paralelo
(
    while [ $(($(date +%s) - START_TIME)) -lt $DURATION ]; do
        # Lanzar CONCURRENT requests simultáneamente
        for i in $(seq 1 $CONCURRENT); do
            if [ $(($(date +%s) - START_TIME)) -ge $DURATION ]; then
                break
            fi
            
            ATTACK=${ATTACKS[$((ATTACK_INDEX % ${#ATTACKS[@]}))]}
            send_attack "http://$DOMAIN" "$ATTACK" > /dev/null &
            ((ATTACK_INDEX++))
            ((REQUESTS_SENT++))
        done
        
        # Controlar tasa de requests por segundo
        sleep $(echo "scale=3; 1/$REQUESTS_PER_SEC * $CONCURRENT" | bc 2>/dev/null || echo "0.1")
    done
    
    wait
) &

ATTACK_PID=$!

# Monitorear progreso
while kill -0 $ATTACK_PID 2>/dev/null; do
    ELAPSED=$(($(date +%s) - START_TIME))
    if [ $ELAPSED -gt 0 ]; then
        CURRENT_RATE=$((REQUESTS_SENT / ELAPSED))
        echo -ne "\r   ⚡ Enviados: $REQUESTS_SENT (~${CURRENT_RATE}/s) - Tiempo: ${ELAPSED}s/${DURATION}s"
    fi
    sleep 1
done

wait $ATTACK_PID
echo ""
echo -e "${GREEN}✅ Ataques completados${NC}"
echo ""

# Esperar a que se procesen
echo -e "${YELLOW}[3/5] Esperando procesamiento (5s)...${NC}"
sleep 5

# Obtener estado final
END_TIME=$(date +%s)
END_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")
END_BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true AND created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")

NEW_LOGS=$((END_LOGS - START_LOGS))
NEW_BLOCKED=$((END_BLOCKED - START_BLOCKED))
ELAPSED_TIME=$((END_TIME - START_TIME))

if [ $ELAPSED_TIME -gt 0 ]; then
    LOGS_PER_SEC=$((NEW_LOGS / ELAPSED_TIME))
    ATTACKS_PER_SEC=$((NEW_BLOCKED / ELAPSED_TIME))
else
    LOGS_PER_SEC=0
    ATTACKS_PER_SEC=0
fi

echo ""
echo -e "${YELLOW}[4/5] Resultados...${NC}"
echo -e "   Tiempo total: ${BLUE}${ELAPSED_TIME}s${NC}"
echo -e "   Requests enviados: ${BLUE}$REQUESTS_SENT${NC}"
echo -e "   Logs nuevos detectados: ${BLUE}$NEW_LOGS${NC}"
echo -e "   Ataques bloqueados: ${BLUE}$NEW_BLOCKED${NC}"
echo -e "   Logs procesados/segundo: ${GREEN}$LOGS_PER_SEC${NC}"
echo -e "   Ataques detectados/segundo: ${GREEN}$ATTACKS_PER_SEC${NC}"
echo ""

# Verificar en dashboard
echo -e "${YELLOW}[5/5] Verificando en dashboard...${NC}"
DASHBOARD_STATS=$(curl -s "http://localhost:9000/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$DASHBOARD_STATS" | grep -q "total_requests"; then
    TOTAL_REQUESTS_API=$(echo "$DASHBOARD_STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null || echo "0")
    BLOCKED_API=$(echo "$DASHBOARD_STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('blocked', 0))" 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ Dashboard actualizado${NC}"
    echo -e "   Total requests (API): ${BLUE}$TOTAL_REQUESTS_API${NC}"
    echo -e "   Blocked (API): ${BLUE}$BLOCKED_API${NC}"
else
    echo -e "${RED}❌ Error consultando dashboard${NC}"
fi

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     📊 RESUMEN DEL BENCHMARK                                        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}✅ Capacidad medida:${NC}"
echo -e "   • ${LOGS_PER_SEC} logs/segundo procesados"
echo -e "   • ${ATTACKS_PER_SEC} ataques/segundo detectados"
echo ""
echo -e "${YELLOW}💡 Para probar con más carga:${NC}"
echo -e "   ./scripts/test-ataques-benchmark.sh localhost:8080 1 50 500 60"
echo -e "   (50 concurrentes, 500 req/s, 60 segundos)"
echo ""
echo -e "${BLUE}🌐 Ver resultados en: http://localhost:9000${NC}"
echo ""

