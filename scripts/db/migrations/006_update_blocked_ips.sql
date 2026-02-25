-- Migración 006: Actualizar tabla blocked_ips con campos adicionales
-- Agrega campos para TTL y gestión automática de bloqueos

DO $$ 
BEGIN
    -- Agregar active si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='blocked_ips' AND column_name='active') THEN
        ALTER TABLE blocked_ips ADD COLUMN active BOOLEAN DEFAULT TRUE;
    END IF;
    
    -- Agregar expires_at si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='blocked_ips' AND column_name='expires_at') THEN
        ALTER TABLE blocked_ips ADD COLUMN expires_at TIMESTAMP;
    END IF;
    
    -- Agregar tenant_id si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='blocked_ips' AND column_name='tenant_id') THEN
        ALTER TABLE blocked_ips ADD COLUMN tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Índices adicionales
CREATE INDEX IF NOT EXISTS idx_blocked_ips_active ON blocked_ips(active) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires_at ON blocked_ips(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blocked_ips_tenant_id ON blocked_ips(tenant_id) WHERE tenant_id IS NOT NULL;
