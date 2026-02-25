#!/bin/bash

# Script para generar datos de prueba para múltiples tenants
# Útil para probar el dashboard multi-tenant

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     📊 GENERADOR DE DATOS DE PRUEBA MULTI-TENANT                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Verificar que PostgreSQL está corriendo
if ! docker ps | grep -q "soc-postgres"; then
    echo -e "${RED}❌ PostgreSQL no está corriendo${NC}"
    exit 1
fi

echo -e "${YELLOW}Generando datos de prueba...${NC}"

# Generar logs para tenant 1 (default)
echo -e "${BLUE}Generando logs para tenant 1 (default)...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << 'SQL' 2>/dev/null || true
-- Logs normales para tenant 1
INSERT INTO waf_logs (timestamp, ip, method, uri, status, blocked, threat_type, tenant_id, created_at)
SELECT 
    NOW() - (random() * interval '7 days'),
    ('192.168.1.' || (10 + (random() * 20)::int))::inet,
    (ARRAY['GET', 'POST', 'PUT', 'DELETE'])[floor(random() * 4 + 1)],
    (ARRAY['/index.php', '/login.php', '/api/users', '/admin', '/dashboard'])[floor(random() * 5 + 1)],
    (ARRAY[200, 200, 200, 403, 404])[floor(random() * 5 + 1)],
    CASE WHEN random() > 0.8 THEN true ELSE false END,
    CASE WHEN random() > 0.7 THEN (ARRAY['XSS', 'SQL Injection', 'Path Traversal', 'Command Injection'])[floor(random() * 4 + 1)] ELSE NULL END,
    1,
    NOW() - (random() * interval '7 days')
FROM generate_series(1, 50)
ON CONFLICT DO NOTHING;
SQL

# Generar logs para tenant 2 (airesiliencehub)
echo -e "${BLUE}Generando logs para tenant 2 (airesiliencehub)...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << 'SQL' 2>/dev/null || true
-- Logs normales para tenant 2
INSERT INTO waf_logs (timestamp, ip, method, uri, status, blocked, threat_type, tenant_id, created_at)
SELECT 
    NOW() - (random() * interval '7 days'),
    ('203.0.113.' || (10 + (random() * 20)::int))::inet,
    (ARRAY['GET', 'POST', 'PUT', 'DELETE'])[floor(random() * 4 + 1)],
    (ARRAY['/home', '/about', '/contact', '/products', '/blog'])[floor(random() * 5 + 1)],
    (ARRAY[200, 200, 200, 403, 404])[floor(random() * 5 + 1)],
    CASE WHEN random() > 0.75 THEN true ELSE false END,
    CASE WHEN random() > 0.6 THEN (ARRAY['XSS', 'SQL Injection', 'RFI/LFI', 'CSRF'])[floor(random() * 4 + 1)] ELSE NULL END,
    2,
    NOW() - (random() * interval '7 days')
FROM generate_series(1, 50)
ON CONFLICT DO NOTHING;
SQL

# Generar algunos incidentes
echo -e "${BLUE}Generando incidentes...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << 'SQL' 2>/dev/null || true
-- Incidentes para tenant 1
INSERT INTO incidents (tenant_id, title, description, status, severity, incident_type, source_ip, detected_at)
VALUES 
    (1, 'Multiple XSS attempts detected', 'Multiple XSS attacks from IP YOUR_IP_ADDRESS', 'open', 'high', 'persistent_attack', 'YOUR_IP_ADDRESS', NOW() - interval '2 hours'),
    (1, 'SQL Injection bypass detected', 'SQL Injection attempt bypassed WAF rules', 'open', 'critical', 'bypass', 'YOUR_IP_ADDRESS', NOW() - interval '5 hours')
ON CONFLICT DO NOTHING;

-- Incidentes para tenant 2
INSERT INTO incidents (tenant_id, title, description, status, severity, incident_type, source_ip, detected_at)
VALUES 
    (2, 'Suspicious activity from multiple IPs', 'Multiple attacks from different IPs', 'open', 'medium', 'persistent_attack', 'YOUR_IP_ADDRESS', NOW() - interval '1 hour'),
    (2, 'Path traversal attempt blocked', 'Path traversal attack successfully blocked', 'resolved', 'low', 'attack', 'YOUR_IP_ADDRESS', NOW() - interval '12 hours')
ON CONFLICT DO NOTHING;
SQL

# Generar algunos bypasses
echo -e "${BLUE}Generando bypasses...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << 'SQL' 2>/dev/null || true
-- Bypasses para tenant 1
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at)
VALUES 
    (1, 'YOUR_IP_ADDRESS', 'XSS', 'Encoding bypass', false, NOW() - interval '3 hours'),
    (1, 'YOUR_IP_ADDRESS', 'SQL Injection', 'Comment injection', true, NOW() - interval '6 hours')
ON CONFLICT DO NOTHING;

-- Bypasses para tenant 2
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at)
VALUES 
    (2, 'YOUR_IP_ADDRESS', 'XSS', 'Unicode encoding', false, NOW() - interval '2 hours'),
    (2, 'YOUR_IP_ADDRESS', 'Path Traversal', 'Double encoding', true, NOW() - interval '4 hours')
ON CONFLICT DO NOTHING;
SQL

echo ""
echo -e "${GREEN}✅ Datos de prueba generados exitosamente${NC}"
echo ""
echo -e "${BLUE}Resumen:${NC}"
echo -e "  ${GREEN}•${NC} ~50 logs para tenant 1 (default)"
echo -e "  ${GREEN}•${NC} ~50 logs para tenant 2 (airesiliencehub)"
echo -e "  ${GREEN}•${NC} 2 incidentes para cada tenant"
echo -e "  ${GREEN}•${NC} 2 bypasses para cada tenant"
echo ""
echo -e "${YELLOW}Ahora puedes probar el dashboard cambiando entre tenants${NC}"
echo ""

