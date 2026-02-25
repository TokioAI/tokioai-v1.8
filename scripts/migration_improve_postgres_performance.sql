-- FASE 3: Mejoras de Performance y Optimización de PostgreSQL
-- Agrega índices compuestos, optimiza queries, mejora transacciones

-- ============================================================================
-- 1. ÍNDICES COMPUESTOS PARA QUERIES COMUNES
-- ============================================================================

-- Índice compuesto para queries por tenant + timestamp + threat_type
-- Útil para: "dame todos los ataques XSS del tenant 1 en las últimas 24h"
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_timestamp_threat 
ON waf_logs (tenant_id, timestamp DESC, threat_type)
WHERE tenant_id IS NOT NULL;

-- Índice compuesto para queries por tenant + timestamp + blocked
-- Útil para: "dame todos los ataques bloqueados del tenant 1 en las últimas 24h"
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_timestamp_blocked 
ON waf_logs (tenant_id, timestamp DESC, blocked)
WHERE tenant_id IS NOT NULL;

-- Índice compuesto para queries por threat_type + timestamp
-- Útil para: "dame todos los SQLi de las últimas 24h"
CREATE INDEX IF NOT EXISTS idx_waf_logs_threat_timestamp 
ON waf_logs (threat_type, timestamp DESC)
WHERE threat_type IS NOT NULL;

-- Índice compuesto para queries por classification_source + timestamp
-- Útil para: "dame todos los logs clasificados por LLM en las últimas 24h"
CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_timestamp 
ON waf_logs (classification_source, timestamp DESC)
WHERE classification_source IS NOT NULL;

-- Índice compuesto para queries por IP + threat_type + timestamp
-- Útil para: "dame todos los ataques XSS de esta IP en las últimas 24h"
CREATE INDEX IF NOT EXISTS idx_waf_logs_ip_threat_timestamp 
ON waf_logs (ip, threat_type, timestamp DESC)
WHERE threat_type IS NOT NULL;

-- ============================================================================
-- 2. ÍNDICES PARCIALES PARA QUERIES ESPECÍFICAS
-- ============================================================================

-- Índice parcial para solo logs bloqueados recientes
-- Útil para: "dame los últimos ataques bloqueados"
CREATE INDEX IF NOT EXISTS idx_waf_logs_blocked_recent 
ON waf_logs (timestamp DESC)
WHERE blocked = TRUE AND timestamp > NOW() - INTERVAL '7 days';

-- Índice parcial para solo logs con alta severidad
-- Útil para: "dame los ataques de alta severidad"
CREATE INDEX IF NOT EXISTS idx_waf_logs_high_severity 
ON waf_logs (timestamp DESC, threat_type)
WHERE severity = 'high' OR threat_type IN ('SQLI', 'XSS', 'PATH_TRAVERSAL', 'CMD_INJECTION');

-- ============================================================================
-- 3. OPTIMIZACIONES DE CONFIGURACIÓN
-- ============================================================================

-- Configurar timeouts para evitar queries largas que bloqueen
-- Nota: Esto se puede hacer a nivel de sesión o conexión, no a nivel de tabla
-- Se aplicará en el código Python

-- ============================================================================
-- 4. VACUUM Y ANALYZE PERIÓDICO
-- ============================================================================

-- Función para mantener estadísticas actualizadas
CREATE OR REPLACE FUNCTION analyze_waf_logs()
RETURNS VOID AS $$
BEGIN
    ANALYZE waf_logs;
    ANALYZE waf_metrics_hourly;
    ANALYZE blocked_ips;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 5. MEJORAS EN QUERIES COMUNES
-- ============================================================================

-- Vista materializada para estadísticas rápidas (opcional, para dashboards)
-- Se puede refrescar periódicamente
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_waf_stats_24h AS
SELECT 
    COUNT(*) as total_requests,
    COUNT(*) FILTER (WHERE blocked = TRUE) as blocked_requests,
    COUNT(*) FILTER (WHERE blocked = FALSE) as allowed_requests,
    COUNT(DISTINCT ip) as unique_ips,
    COUNT(*) FILTER (WHERE threat_type = 'SQLI') as sqli_count,
    COUNT(*) FILTER (WHERE threat_type = 'XSS') as xss_count,
    COUNT(*) FILTER (WHERE threat_type = 'PATH_TRAVERSAL') as path_traversal_count,
    COUNT(*) FILTER (WHERE threat_type = 'CMD_INJECTION') as cmd_injection_count,
    COUNT(*) FILTER (WHERE threat_type = 'OTHER') as other_count,
    MAX(timestamp) as last_log_timestamp
FROM waf_logs
WHERE timestamp > NOW() - INTERVAL '24 hours';

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_waf_stats_24h_unique ON mv_waf_stats_24h (last_log_timestamp);

-- Función para refrescar la vista materializada
CREATE OR REPLACE FUNCTION refresh_waf_stats_24h()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_waf_stats_24h;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 6. COMENTARIOS PARA DOCUMENTACIÓN
-- ============================================================================

COMMENT ON INDEX idx_waf_logs_tenant_timestamp_threat IS 'FASE 3: Índice compuesto para queries por tenant + timestamp + threat_type';
COMMENT ON INDEX idx_waf_logs_tenant_timestamp_blocked IS 'FASE 3: Índice compuesto para queries por tenant + timestamp + blocked';
COMMENT ON INDEX idx_waf_logs_threat_timestamp IS 'FASE 3: Índice compuesto para queries por threat_type + timestamp';
COMMENT ON INDEX idx_waf_logs_blocked_recent IS 'FASE 3: Índice parcial para logs bloqueados recientes';
COMMENT ON MATERIALIZED VIEW mv_waf_stats_24h IS 'FASE 3: Vista materializada para estadísticas rápidas de últimas 24h';









