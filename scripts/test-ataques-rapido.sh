#!/bin/bash

# Test rápido de ataques y capacidad del sistema

set -e

TENANT_ID="${1:-1}"
ATTACKS="${2:-50}"

echo "🧪 TEST RÁPIDO DE DETECCIÓN DE ATAQUES"
echo ""
echo "⚡ Generando $ATTACKS ataques simultáneos..."
echo ""

START_TIME=$(date +%s)
START_COUNT=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID;" 2>/dev/null | xargs || echo "0")

# Generar ataques directamente en PostgreSQL (simulando llegada desde Kafka)
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL
-- Generar múltiples ataques simultáneos
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '5 seconds'),
    '203.0.113.' || (100 + (random() * 50)::int),
    'GET',
    CASE floor(random() * 5)::int
        WHEN 0 THEN '/search?q=<script>alert(1)</script>'
        WHEN 1 THEN '/api?id=1 OR 1=1 UNION SELECT * FROM users'
        WHEN 2 THEN '/admin/../../../etc/passwd'
        WHEN 3 THEN '/cmd.php?exec=cat /etc/passwd'
        ELSE '/test?q=<img src=x onerror=alert(1)>'
    END,
    403,
    146,
    true,
    CASE floor(random() * 4)::int
        WHEN 0 THEN 'XSS'
        WHEN 1 THEN 'SQL Injection'
        WHEN 2 THEN 'Path Traversal'
        ELSE 'Command Injection'
    END,
    $TENANT_ID,
    NOW() - (random() * interval '5 seconds'),
    jsonb_build_object('host', 'test.com', 'blocked', true),
    'python-requests/2.31.0',
    '-',
    'high'
FROM generate_series(1, $ATTACKS) i;
SQL

END_TIME=$(date +%s)
END_COUNT=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID;" 2>/dev/null | xargs || echo "0")

ELAPSED=$((END_TIME - START_TIME))
NEW_LOGS=$((END_COUNT - START_COUNT))

if [ $ELAPSED -gt 0 ]; then
    RATE=$((NEW_LOGS / ELAPSED))
else
    RATE=$NEW_LOGS
fi

echo "✅ Ataques generados: $ATTACKS"
echo "📊 Resultados:"
echo "   • Tiempo de inserción: ${ELAPSED}s"
echo "   • Logs nuevos: $NEW_LOGS"
echo "   • Velocidad: ${RATE} logs/segundo"
echo ""

# Verificar en dashboard
sleep 2
STATS=$(curl -s "http://localhost:9000/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$STATS" | grep -q "total_requests"; then
    TOTAL=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null || echo "0")
    BLOCKED=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('blocked', 0))" 2>/dev/null || echo "0")
    echo "📈 Dashboard:"
    echo "   • Total requests: $TOTAL"
    echo "   • Blocked: $BLOCKED"
    echo ""
fi

echo "🌐 Ver en dashboard: http://localhost:9000"
echo ""

