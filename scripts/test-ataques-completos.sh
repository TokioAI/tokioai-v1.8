#!/bin/bash

# Script para probar todos los tipos de ataques y tráfico normal
# Verifica que los logs lleguen al dashboard

set -e

TARGET="${1:-localhost:8080}"
TENANT_ID="${2:-1}"

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧪 TEST COMPLETO - ATAQUES Y TRÁFICO NORMAL                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Target: ${BLUE}$TARGET${NC}"
echo -e "${YELLOW}Tenant ID: ${BLUE}$TENANT_ID${NC}"
echo ""

# Estado inicial
echo -e "${YELLOW}[1/6] Obteniendo estado inicial...${NC}"
START_TIME=$(date +%s)
START_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND created_at > NOW() - INTERVAL '5 minutes';" 2>/dev/null | xargs || echo "0")
START_BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true AND created_at > NOW() - INTERVAL '5 minutes';" 2>/dev/null | xargs || echo "0")
echo -e "   Logs últimos 5min: ${BLUE}$START_LOGS${NC}"
echo -e "   Bloqueados últimos 5min: ${BLUE}$START_BLOCKED${NC}"
echo ""

# Función para hacer request
make_request() {
    local method="$1"
    local path="$2"
    local host="$3"
    curl -s -o /dev/null -w "%{http_code}" \
        -X "$method" \
        -H "Host: $host" \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
        --max-time 5 \
        "$TARGET$path" 2>/dev/null || echo "000"
}

# Función para hacer request de ataque
make_attack() {
    local attack_type="$1"
    local path="$2"
    local host="$3"
    local status=$(make_request "GET" "$path" "$host")
    echo -e "   ${YELLOW}$attack_type${NC}: $status ${NC}$(if [ "$status" = "403" ]; then echo "${GREEN}✓ Bloqueado${NC}"; else echo "${RED}⚠ Pasó${NC}"; fi)"
    sleep 0.2
}

echo -e "${YELLOW}[2/6] Enviando tráfico normal...${NC}"
NORMAL_HOST="test.com"
for path in "/" "/home" "/about" "/contact" "/products" "/blog"; do
    status=$(make_request "GET" "$path" "$NORMAL_HOST")
    echo -e "   ${GREEN}GET $path${NC}: $status"
    sleep 0.1
done
echo ""

echo -e "${YELLOW}[3/6] Enviando ataques XSS...${NC}"
XSS_HOST="test.com"
make_attack "XSS - Script tag" "/search?q=<script>alert(document.cookie)</script>" "$XSS_HOST"
make_attack "XSS - Img tag" "/test?q=<img src=x onerror=alert(1)>" "$XSS_HOST"
make_attack "XSS - SVG" "/page?q=<svg onload=alert(1)>" "$XSS_HOST"
make_attack "XSS - JavaScript" "/form?data=javascript:alert('XSS')" "$XSS_HOST"
echo ""

echo -e "${YELLOW}[4/6] Enviando ataques SQL Injection...${NC}"
SQL_HOST="test.com"
make_attack "SQLi - OR 1=1" "/login?id=1 OR 1=1" "$SQL_HOST"
make_attack "SQLi - UNION" "/api/users?id=1 UNION SELECT * FROM users" "$SQL_HOST"
make_attack "SQLi - Comment" "/search?id=1'--" "$SQL_HOST"
make_attack "SQLi - Time-based" "/test?id=1' AND SLEEP(5)--" "$SQL_HOST"
make_attack "SQLi - Boolean" "/admin?id=1' AND '1'='1" "$SQL_HOST"
echo ""

echo -e "${YELLOW}[5/6] Enviando ataques Path Traversal...${NC}"
PATH_HOST="test.com"
make_attack "Path Traversal - etc/passwd" "/../../../../etc/passwd" "$PATH_HOST"
make_attack "Path Traversal - windows" "/../../windows/win.ini" "$PATH_HOST"
make_attack "Path Traversal - config" "/../../../var/www/html/config.php" "$PATH_HOST"
make_attack "Path Traversal - double" "/....//....//etc/passwd" "$PATH_HOST"
echo ""

echo -e "${YELLOW}[6/6] Enviando ataques Command Injection...${NC}"
CMD_HOST="test.com"
make_attack "Command Injection - cat" "/cmd.php?exec=cat /etc/passwd" "$CMD_HOST"
make_attack "Command Injection - ls" "/test.sh?cmd=ls -la" "$CMD_HOST"
make_attack "Command Injection - whoami" "/script?run=whoami" "$CMD_HOST"
make_attack "Command Injection - pipe" "/exec.php?command=id | cat" "$CMD_HOST"
echo ""

# Esperar a que se procesen
echo -e "${YELLOW}Esperando 5 segundos para procesamiento...${NC}"
sleep 5

# Estado final
END_TIME=$(date +%s)
END_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND created_at > NOW() - INTERVAL '5 minutes';" 2>/dev/null | xargs || echo "0")
END_BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true AND created_at > NOW() - INTERVAL '5 minutes';" 2>/dev/null | xargs || echo "0")

NEW_LOGS=$((END_LOGS - START_LOGS))
NEW_BLOCKED=$((END_BLOCKED - START_BLOCKED))
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     📊 RESULTADOS                                                  ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}✅ Logs generados:${NC}"
echo -e "   • Total nuevos: ${BLUE}$NEW_LOGS${NC}"
echo -e "   • Bloqueados: ${BLUE}$NEW_BLOCKED${NC}"
echo -e "   • Permitidos: ${BLUE}$((NEW_LOGS - NEW_BLOCKED))${NC}"
echo ""

# Verificar en dashboard API
echo -e "${YELLOW}[7/7] Verificando en dashboard API...${NC}"
STATS=$(curl -s "http://localhost:9000/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$STATS" | grep -q "total_requests"; then
    TOTAL_API=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null || echo "0")
    BLOCKED_API=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('blocked', 0))" 2>/dev/null || echo "0")
    ALLOWED_API=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('allowed', 0))" 2>/dev/null || echo "0")
    THREATS=$(echo "$STATS" | python3 -c "import sys, json; threats=json.load(sys.stdin).get('by_threat_type', {}); print(', '.join([f'{k}: {v}' for k, v in threats.items()]))" 2>/dev/null || echo "N/A")
    
    echo -e "${GREEN}✅ Dashboard API:${NC}"
    echo -e "   • Total requests: ${BLUE}$TOTAL_API${NC}"
    echo -e "   • Blocked: ${BLUE}$BLOCKED_API${NC}"
    echo -e "   • Allowed: ${BLUE}$ALLOWED_API${NC}"
    if [ "$THREATS" != "N/A" ] && [ -n "$THREATS" ]; then
        echo -e "   • Por tipo de amenaza: ${BLUE}$THREATS${NC}"
    fi
else
    echo -e "${RED}❌ Error consultando dashboard API${NC}"
fi

# Obtener ataques recientes
ATTACKS=$(curl -s "http://localhost:9000/api/attacks/recent?tenant_id=$TENANT_ID&limit=10" 2>/dev/null)
if echo "$ATTACKS" | grep -q "items"; then
    ATTACK_COUNT=$(echo "$ATTACKS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null || echo "0")
    echo -e "   • Ataques visibles: ${BLUE}$ATTACK_COUNT${NC}"
    
    # Mostrar tipos de ataques detectados
    ATTACK_TYPES=$(echo "$ATTACKS" | python3 -c "import sys, json; items=json.load(sys.stdin).get('items', []); types=[item.get('threat_type', 'Unknown') for item in items]; print(', '.join(set(types)) if types else 'Ninguno')" 2>/dev/null || echo "N/A")
    if [ "$ATTACK_TYPES" != "N/A" ] && [ "$ATTACK_TYPES" != "Ninguno" ]; then
        echo -e "   • Tipos detectados: ${BLUE}$ATTACK_TYPES${NC}"
    fi
fi

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🌐 VERIFICAR EN DASHBOARD                                        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "1. Abre: ${BLUE}http://localhost:9000${NC}"
echo ""
echo -e "2. Selecciona tenant ID: ${BLUE}$TENANT_ID${NC}"
echo ""
echo -e "3. Verifica que veas:"
echo -e "   ${GREEN}✅${NC} Tráfico normal (requests permitidos)"
echo -e "   ${GREEN}✅${NC} Ataques bloqueados (status 403)"
echo -e "   ${GREEN}✅${NC} Diferentes tipos de amenazas: XSS, SQL Injection, Path Traversal, Command Injection"
echo -e "   ${GREEN}✅${NC} Tabla 'Recent Attacks' con los ataques"
echo ""
echo -e "4. Abre pestañas del dashboard:"
echo -e "   ${GREEN}✅${NC} Recent Attacks → Ver ataques bloqueados"
echo -e "   ${GREEN}✅${NC} Stats → Ver métricas por tipo"
echo ""

