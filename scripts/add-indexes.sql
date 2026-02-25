-- Índices para optimizar queries del dashboard
-- Ejecutar en Cloud SQL PostgreSQL

-- Índice para queries por fecha (más usado en dashboard)
CREATE INDEX IF NOT EXISTS idx_waf_logs_created_at ON waf_logs(created_at DESC);

-- Índice para queries por threat_type
CREATE INDEX IF NOT EXISTS idx_waf_logs_threat_type ON waf_logs(threat_type) WHERE threat_type IS NOT NULL;

-- Índice para queries por blocked
CREATE INDEX IF NOT EXISTS idx_waf_logs_blocked ON waf_logs(blocked) WHERE blocked = true;

-- Índice compuesto para queries más comunes (created_at + blocked)
CREATE INDEX IF NOT EXISTS idx_waf_logs_created_at_blocked ON waf_logs(created_at DESC, blocked);

-- Índice para tenant_id (multitenancy)
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_id ON waf_logs(tenant_id) WHERE tenant_id IS NOT NULL;

-- Índice compuesto para queries de ataques recientes (tenant + fecha + bloqueado)
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_created_blocked ON waf_logs(tenant_id, created_at DESC, blocked) WHERE blocked = true;

-- Índice para classification_source (para estadísticas)
CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source ON waf_logs(classification_source) WHERE classification_source IS NOT NULL;

-- Índice para ml_confidence (para filtrar predicciones ML)
CREATE INDEX IF NOT EXISTS idx_waf_logs_ml_confidence ON waf_logs(ml_confidence) WHERE ml_confidence IS NOT NULL;

-- Índice para llm_confidence (para filtrar predicciones LLM)
CREATE INDEX IF NOT EXISTS idx_waf_logs_llm_confidence ON waf_logs(llm_confidence) WHERE llm_confidence IS NOT NULL;

-- Verificar índices creados
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'waf_logs'
ORDER BY indexname;

