-- Migración 009: Tabla de audit log para bloqueos
-- Registra todas las acciones de bloqueo/desbloqueo con quién las hizo

CREATE TABLE IF NOT EXISTS block_audit_log (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('block', 'unblock')),
    reason TEXT,
    actor VARCHAR(100) DEFAULT 'automatic',  -- 'automatic', 'manual', o username
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_block_audit_log_ip ON block_audit_log(ip);
CREATE INDEX IF NOT EXISTS idx_block_audit_log_action ON block_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_block_audit_log_created_at ON block_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_block_audit_log_tenant_id ON block_audit_log(tenant_id) WHERE tenant_id IS NOT NULL;

COMMENT ON TABLE block_audit_log IS 'Auditoría de todas las acciones de bloqueo/desbloqueo de IPs';
COMMENT ON COLUMN block_audit_log.actor IS 'Quién realizó la acción: automatic, manual, o username del usuario';
