-- Migración 002: Sistema Multi-Tenant
-- Agrega tablas y campos para soporte multi-tenant

-- Tabla de tenants (sitios web protegidos)
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    backend_url VARCHAR(500) NOT NULL,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    config JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Índices para tenants
CREATE INDEX IF NOT EXISTS idx_tenants_domain ON tenants (domain);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants (status);

-- Agregar tenant_id a waf_logs si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='tenant_id') THEN
        ALTER TABLE waf_logs ADD COLUMN tenant_id INTEGER REFERENCES tenants(id);
        CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_id ON waf_logs (tenant_id);
    END IF;
END $$;

-- Tabla de reglas dinámicas por tenant
CREATE TABLE IF NOT EXISTS tenant_rules (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(50) NOT NULL CHECK (rule_type IN ('block', 'allow', 'rate_limit', 'custom')),
    pattern TEXT NOT NULL,
    action VARCHAR(50) NOT NULL,
    priority INTEGER DEFAULT 100,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'system',
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tenant_rules_tenant_id ON tenant_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_rules_enabled ON tenant_rules (enabled);
