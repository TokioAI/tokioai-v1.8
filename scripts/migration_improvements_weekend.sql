-- Migration: Tablas para mejoras de fin de semana
-- Fecha: 2025-01-06
-- Sistema: Tokio AI - Mejoras de Excelencia

-- 1. Tabla para rate limiting
CREATE TABLE IF NOT EXISTS rate_limited_ips (
    id BIGSERIAL PRIMARY KEY,
    ip INET NOT NULL,
    rate_limit_level VARCHAR(20) NOT NULL,
    rate_limit_requests INT NOT NULL,
    rate_limit_window INT NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    risk_score FLOAT,
    reason TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rate_limited_ips_ip_active 
    ON rate_limited_ips(ip) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_rate_limited_ips_expires_at 
    ON rate_limited_ips(expires_at) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_rate_limited_ips_applied_at 
    ON rate_limited_ips(applied_at);

-- 2. Actualizar blocked_ips para soportar mejoras
ALTER TABLE blocked_ips 
    ADD COLUMN IF NOT EXISTS block_stage VARCHAR(20),
    ADD COLUMN IF NOT EXISTS risk_score FLOAT,
    ADD COLUMN IF NOT EXISTS auto_unblock_attempts INT DEFAULT 0;

-- Índices adicionales para mejoras
CREATE INDEX IF NOT EXISTS idx_blocked_ips_block_stage 
    ON blocked_ips(block_stage) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_blocked_ips_risk_score 
    ON blocked_ips(risk_score) WHERE active = TRUE;

-- Comentarios para documentación
COMMENT ON TABLE rate_limited_ips IS 'IPs con rate limiting activo desde sistema inteligente';
COMMENT ON COLUMN blocked_ips.block_stage IS 'Etapa de bloqueo: monitor, warning, rate_limit, soft_block, hard_block';
COMMENT ON COLUMN blocked_ips.risk_score IS 'Score de riesgo calculado por sistema inteligente (0.0-1.0)';
COMMENT ON COLUMN blocked_ips.auto_unblock_attempts IS 'Número de intentos de auto-desbloqueo realizados';

-- Función para actualizar updated_at automáticamente en rate_limited_ips
CREATE OR REPLACE FUNCTION update_rate_limited_ips_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para actualizar updated_at
DROP TRIGGER IF EXISTS trigger_update_rate_limited_ips_updated_at ON rate_limited_ips;
CREATE TRIGGER trigger_update_rate_limited_ips_updated_at
    BEFORE UPDATE ON rate_limited_ips
    FOR EACH ROW
    EXECUTE FUNCTION update_rate_limited_ips_updated_at();
