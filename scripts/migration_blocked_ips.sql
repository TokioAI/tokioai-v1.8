-- Migration: Tabla para IPs bloqueadas automáticamente
-- Fecha: 2025-12-26

-- Tabla para almacenar IPs bloqueadas por auto-mitigación
CREATE TABLE IF NOT EXISTS blocked_ips (
    id BIGSERIAL PRIMARY KEY,
    ip INET NOT NULL,
    blocked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    reason TEXT,
    blocked_by VARCHAR(50) DEFAULT 'auto-mitigation',
    threat_type VARCHAR(50),
    severity VARCHAR(20),
    classification_source VARCHAR(50),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    unblocked_at TIMESTAMP,
    unblock_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Índice único en IP activa (solo una IP bloqueada activa a la vez)
CREATE UNIQUE INDEX IF NOT EXISTS idx_blocked_ips_ip_active 
    ON blocked_ips(ip) WHERE active = TRUE;

-- Índice en expires_at para limpiar IPs expiradas
CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires_at 
    ON blocked_ips(expires_at) WHERE active = TRUE;

-- Índice en blocked_at para queries temporales
CREATE INDEX IF NOT EXISTS idx_blocked_ips_blocked_at 
    ON blocked_ips(blocked_at);

-- Función para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_blocked_ips_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para actualizar updated_at
DROP TRIGGER IF EXISTS trigger_update_blocked_ips_updated_at ON blocked_ips;
CREATE TRIGGER trigger_update_blocked_ips_updated_at
    BEFORE UPDATE ON blocked_ips
    FOR EACH ROW
    EXECUTE FUNCTION update_blocked_ips_updated_at();

-- Comentarios para documentación
COMMENT ON TABLE blocked_ips IS 'IPs bloqueadas automáticamente por el sistema de mitigación';
COMMENT ON COLUMN blocked_ips.ip IS 'Dirección IP bloqueada';
COMMENT ON COLUMN blocked_ips.blocked_at IS 'Fecha/hora cuando se bloqueó la IP';
COMMENT ON COLUMN blocked_ips.expires_at IS 'Fecha/hora cuando expira el bloqueo (NULL = permanente)';
COMMENT ON COLUMN blocked_ips.reason IS 'Razón del bloqueo';
COMMENT ON COLUMN blocked_ips.blocked_by IS 'Sistema que bloqueó (auto-mitigation, manual, etc.)';
COMMENT ON COLUMN blocked_ips.threat_type IS 'Tipo de amenaza detectada';
COMMENT ON COLUMN blocked_ips.severity IS 'Severidad de la amenaza';
COMMENT ON COLUMN blocked_ips.classification_source IS 'Fuente de clasificación (heuristic, ml, transformer, llm)';
COMMENT ON COLUMN blocked_ips.active IS 'Si el bloqueo está activo';
COMMENT ON COLUMN blocked_ips.unblocked_at IS 'Fecha/hora cuando se desbloqueó';
COMMENT ON COLUMN blocked_ips.unblock_reason IS 'Razón del desbloqueo';









