-- Migración 007: Índices adicionales para optimización de performance
-- Mejora las consultas del dashboard y búsquedas

-- Índices compuestos para queries comunes
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_timestamp_threat 
ON waf_logs (tenant_id, timestamp DESC, threat_type)
WHERE tenant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_timestamp_blocked 
ON waf_logs (tenant_id, timestamp DESC, blocked)
WHERE tenant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_waf_logs_threat_timestamp 
ON waf_logs (threat_type, timestamp DESC)
WHERE threat_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_timestamp 
ON waf_logs (classification_source, timestamp DESC)
WHERE classification_source IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_waf_logs_ip_threat_timestamp 
ON waf_logs (ip, threat_type, timestamp DESC)
WHERE threat_type IS NOT NULL;

-- Índice parcial para solo logs bloqueados recientes
CREATE INDEX IF NOT EXISTS idx_waf_logs_blocked_recent 
ON waf_logs (timestamp DESC, ip, threat_type)
WHERE blocked = TRUE AND timestamp > NOW() - INTERVAL '7 days';

-- Índice compuesto para queries de ataques recientes (tenant + fecha + bloqueado)
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_created_blocked 
ON waf_logs (tenant_id, created_at DESC, blocked) 
WHERE blocked = TRUE;
