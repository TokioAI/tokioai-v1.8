-- Inicialización de la base de datos SOC AI
-- Este script se ejecuta automáticamente al crear el contenedor PostgreSQL

-- Tabla principal para logs históricos
CREATE TABLE IF NOT EXISTS waf_logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    ip VARCHAR(45) NOT NULL,
    method VARCHAR(100),
    uri TEXT,
    status INTEGER,
    size INTEGER,
    user_agent TEXT,
    referer TEXT,
    blocked BOOLEAN DEFAULT FALSE,
    threat_type VARCHAR(100),
    severity VARCHAR(20),
    raw_log JSONB,
    classification_source VARCHAR(50),  -- ml, hybrid_ml, llm, heuristic, pending
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para consultas rápidas
CREATE INDEX IF NOT EXISTS idx_waf_logs_timestamp ON waf_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_waf_logs_ip ON waf_logs(ip);
CREATE INDEX IF NOT EXISTS idx_waf_logs_status ON waf_logs(status);
CREATE INDEX IF NOT EXISTS idx_waf_logs_blocked ON waf_logs(blocked);
CREATE INDEX IF NOT EXISTS idx_waf_logs_threat_type ON waf_logs(threat_type);
CREATE INDEX IF NOT EXISTS idx_waf_logs_severity ON waf_logs(severity);
CREATE INDEX IF NOT EXISTS idx_waf_logs_created_at ON waf_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source ON waf_logs(classification_source);

-- Índice compuesto para consultas comunes (IP + fecha)
CREATE INDEX IF NOT EXISTS idx_waf_logs_ip_timestamp ON waf_logs(ip, timestamp DESC);

-- Índice GIN para búsquedas en JSONB
CREATE INDEX IF NOT EXISTS idx_waf_logs_raw_log_gin ON waf_logs USING GIN(raw_log);

-- Tabla para métricas agregadas (opcional, para optimizar consultas frecuentes)
CREATE TABLE IF NOT EXISTS waf_metrics_hourly (
    id BIGSERIAL PRIMARY KEY,
    hour_start TIMESTAMP NOT NULL,
    total_requests BIGINT DEFAULT 0,
    blocked_requests BIGINT DEFAULT 0,
    allowed_requests BIGINT DEFAULT 0,
    xss_count BIGINT DEFAULT 0,
    sqli_count BIGINT DEFAULT 0,
    path_traversal_count BIGINT DEFAULT 0,
    cmd_injection_count BIGINT DEFAULT 0,
    other_threats BIGINT DEFAULT 0,
    unique_ips BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hour_start)
);

CREATE INDEX IF NOT EXISTS idx_waf_metrics_hourly_hour_start ON waf_metrics_hourly(hour_start DESC);

-- Tabla para IPs bloqueadas (histórico)
CREATE TABLE IF NOT EXISTS blocked_ips (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    blocked_at TIMESTAMP NOT NULL,
    unblocked_at TIMESTAMP,
    reason TEXT,
    threat_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_blocked_ips_ip ON blocked_ips(ip);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_blocked_at ON blocked_ips(blocked_at DESC);

-- Función para limpiar logs antiguos (retention policy)
CREATE OR REPLACE FUNCTION cleanup_old_logs(retention_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM waf_logs
    WHERE timestamp < NOW() - (retention_days || ' days')::INTERVAL;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Comentarios para documentación
COMMENT ON TABLE waf_logs IS 'Logs históricos del WAF con toda la información de requests';
COMMENT ON TABLE waf_metrics_hourly IS 'Métricas agregadas por hora para optimizar consultas';
COMMENT ON TABLE blocked_ips IS 'Historial de IPs bloqueadas';

COMMENT ON COLUMN waf_logs.blocked IS 'Indica si la request fue bloqueada (status >= 400)';
COMMENT ON COLUMN waf_logs.threat_type IS 'Tipo de amenaza detectada: XSS, SQLI, PATH_TRAVERSAL, CMD_INJECTION, etc.';
COMMENT ON COLUMN waf_logs.raw_log IS 'Log completo en formato JSON para consultas avanzadas';



