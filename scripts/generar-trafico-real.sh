#!/bin/bash

# Script para generar tráfico real y verificar todo el sistema
# Incluye: logs, ataques, bypasses, incidentes, mitigación automática

set -e

TENANT_ID=2
DOMAIN="airesiliencehub.space"
DASHBOARD_URL="http://localhost:9000"

echo "🧪 Generando tráfico completo para $DOMAIN..."

# Generar muchos logs de prueba
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
-- Limpiar datos anteriores de prueba
DELETE FROM waf_logs WHERE tenant_id = $TENANT_ID AND ip LIKE '203.0.113.%';

-- Generar tráfico normal (50 requests)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, tenant_id, created_at, raw_log, user_agent, referer)
SELECT 
    NOW() - (random() * interval '1 hour'),
    '203.0.113.' || (100 + i),
    (ARRAY['GET', 'POST'])[floor(random() * 2 + 1)],
    (ARRAY['/', '/home', '/about', '/contact', '/products', '/blog', '/api/users', '/api/data', '/dashboard', '/settings'])[floor(random() * 10 + 1)],
    200,
    (500 + (random() * 10000)::int),
    false,
    $TENANT_ID,
    NOW() - (random() * interval '1 hour'),
    jsonb_build_object('host', '$DOMAIN'),
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    '-'
FROM generate_series(1, 50) i;

-- Generar ataques XSS (15)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '30 minutes'),
    '203.0.113.' || (150 + i),
    'GET',
    '/search?q=<script>alert(document.cookie)</script>',
    403,
    146,
    true,
    'XSS',
    $TENANT_ID,
    NOW() - (random() * interval '30 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true),
    'python-requests/2.31.0',
    '-',
    'high'
FROM generate_series(1, 15) i;

-- Generar ataques SQL Injection (12)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '25 minutes'),
    '203.0.113.' || (165 + i),
    'GET',
    '/api/users?id=1 OR 1=1 UNION SELECT * FROM users',
    403,
    146,
    true,
    'SQL Injection',
    $TENANT_ID,
    NOW() - (random() * interval '25 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true),
    'sqlmap/1.7',
    '-',
    'critical'
FROM generate_series(1, 12) i;

-- Generar ataques Path Traversal (8)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '20 minutes'),
    '203.0.113.' || (177 + i),
    'GET',
    '/../../../../etc/passwd',
    403,
    146,
    true,
    'Path Traversal',
    $TENANT_ID,
    NOW() - (random() * interval '20 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true),
    'curl/7.68.0',
    '-',
    'high'
FROM generate_series(1, 8) i;

-- Generar ataques Command Injection (5)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '15 minutes'),
    '203.0.113.' || (185 + i),
    'GET',
    '/cmd.php?exec=cat /etc/passwd',
    403,
    146,
    true,
    'Command Injection',
    $TENANT_ID,
    NOW() - (random() * interval '15 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true),
    'python-requests/2.31.0',
    '-',
    'critical'
FROM generate_series(1, 5) i;
SQL

# Crear bypasses e incidentes
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
-- Bypasses
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at, request_data, response_data)
VALUES 
    ($TENANT_ID, 'YOUR_IP_ADDRESS', 'XSS', 'Unicode encoding', false, NOW(), '{"uri": "/test?q=<script>alert(1)</script>", "host": "$DOMAIN"}'::jsonb, '{"uri": "/test?q=%u003Cscript%u003E", "status": 200, "host": "$DOMAIN"}'::jsonb),
    ($TENANT_ID, 'YOUR_IP_ADDRESS', 'SQL Injection', 'Comment injection', true, NOW() - INTERVAL '1 hour', '{"uri": "/api?id=1--", "host": "$DOMAIN"}'::jsonb, '{"uri": "/api?id=1 OR 1=1--", "status": 200, "host": "$DOMAIN"}'::jsonb)
ON CONFLICT DO NOTHING;

-- Incidentes
INSERT INTO incidents (tenant_id, title, description, status, severity, incident_type, source_ip, detected_at)
VALUES 
    ($TENANT_ID, 'Múltiples intentos de XSS desde IP YOUR_IP_ADDRESS', 'Se detectaron múltiples ataques XSS desde la misma IP', 'open', 'high', 'persistent_attack', 'YOUR_IP_ADDRESS', NOW() - INTERVAL '30 minutes'),
    ($TENANT_ID, 'Bypass de SQL Injection detectado', 'Se detectó un bypass de SQL Injection usando encoding', 'open', 'critical', 'bypass', 'YOUR_IP_ADDRESS', NOW() - INTERVAL '1 hour')
ON CONFLICT DO NOTHING;
SQL

# Verificar
TOTAL=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID;" 2>/dev/null | xargs)
BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true;" 2>/dev/null | xargs)

echo "✅ Tráfico generado:"
echo "   Total logs: $TOTAL"
echo "   Bloqueados: $BLOCKED"
echo ""
echo "🌐 Ahora abre el dashboard:"
echo "   $DASHBOARD_URL"
echo ""
echo "   Selecciona: 🏢 AI Resilience Hub (airesiliencehub.space)"
echo "   Y verifica que veas todos los datos!"

