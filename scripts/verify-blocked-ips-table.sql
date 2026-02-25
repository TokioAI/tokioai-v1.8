-- Verificar si la tabla blocked_ips existe
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name = 'blocked_ips'
) as table_exists;

-- Si no existe, crear la tabla
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

-- Crear índices
CREATE UNIQUE INDEX IF NOT EXISTS idx_blocked_ips_ip_active 
    ON blocked_ips(ip) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires_at 
    ON blocked_ips(expires_at) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_blocked_ips_blocked_at 
    ON blocked_ips(blocked_at);

-- Función para actualizar updated_at
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

SELECT 'Tabla blocked_ips verificada/creada exitosamente' as status;
