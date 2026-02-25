-- Esquema Multi-Tenant para Tokio AI ACIS
-- Permite gestionar múltiples sitios web protegidos

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

-- Modificar tabla waf_logs para incluir tenant_id
ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id);
CREATE INDEX IF NOT EXISTS idx_waf_logs_tenant_id ON waf_logs (tenant_id);

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

-- Tabla de incidentes
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'investigating', 'resolved', 'closed', 'false_positive')),
    incident_type VARCHAR(50) NOT NULL CHECK (incident_type IN ('bypass', 'persistent_attack', 'scan', 'exploit', 'anomaly', 'other')),
    source_ip VARCHAR(45),
    affected_urls TEXT[],
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    assigned_to VARCHAR(100),
    resolution_notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_incidents_tenant_id ON incidents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents (severity);
CREATE INDEX IF NOT EXISTS idx_incidents_detected_at ON incidents (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_source_ip ON incidents (source_ip);

-- Tabla de bypasses detectados
CREATE TABLE IF NOT EXISTS detected_bypasses (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
    source_ip VARCHAR(45) NOT NULL,
    attack_type VARCHAR(50) NOT NULL,
    original_rule_id VARCHAR(255),
    bypass_method TEXT,
    request_data JSONB,
    response_data JSONB,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    mitigated BOOLEAN DEFAULT FALSE,
    mitigation_rule_id INTEGER REFERENCES tenant_rules(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_bypasses_tenant_id ON detected_bypasses (tenant_id);
CREATE INDEX IF NOT EXISTS idx_bypasses_source_ip ON detected_bypasses (source_ip);
CREATE INDEX IF NOT EXISTS idx_bypasses_detected_at ON detected_bypasses (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_bypasses_mitigated ON detected_bypasses (mitigated);

-- Tabla de escaneos detectados
CREATE TABLE IF NOT EXISTS detected_scans (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    source_ip VARCHAR(45) NOT NULL,
    scan_type VARCHAR(50) NOT NULL CHECK (scan_type IN ('port_scan', 'dir_scan', 'vuln_scan', 'crawler', 'other')),
    target_paths TEXT[],
    requests_count INTEGER DEFAULT 0,
    time_window_start TIMESTAMP WITH TIME ZONE,
    time_window_end TIMESTAMP WITH TIME ZONE,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    blocked BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_scans_tenant_id ON detected_scans (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scans_source_ip ON detected_scans (source_ip);
CREATE INDEX IF NOT EXISTS idx_scans_detected_at ON detected_scans (detected_at DESC);

-- Tabla de ataques en progreso
CREATE TABLE IF NOT EXISTS attacks_in_progress (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    source_ip VARCHAR(45) NOT NULL,
    attack_type VARCHAR(50) NOT NULL,
    target_url TEXT,
    attack_stage VARCHAR(50) DEFAULT 'reconnaissance' CHECK (attack_stage IN ('reconnaissance', 'exploitation', 'persistence', 'lateral_movement', 'data_exfiltration')),
    steps_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_attacks_tenant_id ON attacks_in_progress (tenant_id);
CREATE INDEX IF NOT EXISTS idx_attacks_source_ip ON attacks_in_progress (source_ip);
CREATE INDEX IF NOT EXISTS idx_attacks_is_active ON attacks_in_progress (is_active);
CREATE INDEX IF NOT EXISTS idx_attacks_last_seen ON attacks_in_progress (last_seen DESC);

-- Tabla de pruebas de Red Team
CREATE TABLE IF NOT EXISTS redteam_tests (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    test_name VARCHAR(255) NOT NULL,
    test_type VARCHAR(50) NOT NULL CHECK (test_type IN ('sqli', 'xss', 'path_traversal', 'cmd_injection', 'auth_bypass', 'other')),
    target_url TEXT NOT NULL,
    payload TEXT,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    blocked BOOLEAN,
    response_status INTEGER,
    response_time_ms INTEGER,
    detected_by VARCHAR(255),
    rule_matched VARCHAR(255),
    result JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_redteam_tenant_id ON redteam_tests (tenant_id);
CREATE INDEX IF NOT EXISTS idx_redteam_test_type ON redteam_tests (test_type);
CREATE INDEX IF NOT EXISTS idx_redteam_executed_at ON redteam_tests (executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_redteam_blocked ON redteam_tests (blocked);

-- Tabla de historial de pruebas del Red Team Inteligente (para aprendizaje continuo)
CREATE TABLE IF NOT EXISTS redteam_test_history (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    attack_type VARCHAR(50) NOT NULL CHECK (attack_type IN ('SQLI', 'XSS', 'PATH_TRAVERSAL', 'CMD_INJECTION', 'RFI_LFI', 'XXE', 'OTHER')),
    payload TEXT NOT NULL,
    bypass_technique VARCHAR(100),
    success BOOLEAN NOT NULL,
    blocked BOOLEAN NOT NULL,
    response_status INTEGER,
    response_time_ms INTEGER,
    waf_signatures JSONB DEFAULT '[]'::jsonb,
    waf_rules_count INTEGER DEFAULT 0,
    protected_types TEXT[],
    tested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    campaign_id VARCHAR(100),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_redteam_history_tenant_id ON redteam_test_history (tenant_id);
CREATE INDEX IF NOT EXISTS idx_redteam_history_attack_type ON redteam_test_history (attack_type);
CREATE INDEX IF NOT EXISTS idx_redteam_history_tested_at ON redteam_test_history (tested_at DESC);
CREATE INDEX IF NOT EXISTS idx_redteam_history_success ON redteam_test_history (success);
CREATE INDEX IF NOT EXISTS idx_redteam_history_blocked ON redteam_test_history (blocked);
CREATE INDEX IF NOT EXISTS idx_redteam_history_campaign_id ON redteam_test_history (campaign_id);
-- Índice compuesto para consultas de tipos no probados recientemente
CREATE INDEX IF NOT EXISTS idx_redteam_history_tenant_attack_tested ON redteam_test_history (tenant_id, attack_type, tested_at DESC);

-- Tabla de métricas por tenant
CREATE TABLE IF NOT EXISTS tenant_metrics (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    metric_date DATE NOT NULL,
    total_requests BIGINT DEFAULT 0,
    blocked_requests BIGINT DEFAULT 0,
    allowed_requests BIGINT DEFAULT 0,
    xss_attacks BIGINT DEFAULT 0,
    sqli_attacks BIGINT DEFAULT 0,
    path_traversal_attacks BIGINT DEFAULT 0,
    cmd_injection_attacks BIGINT DEFAULT 0,
    unique_ips BIGINT DEFAULT 0,
    bypasses_detected BIGINT DEFAULT 0,
    scans_detected BIGINT DEFAULT 0,
    incidents_created BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_metrics_tenant_id ON tenant_metrics (tenant_id);
CREATE INDEX IF NOT EXISTS idx_metrics_metric_date ON tenant_metrics (metric_date DESC);

-- Insertar tenant por defecto (para migración)
INSERT INTO tenants (name, domain, backend_url, status) 
VALUES ('Default Site', 'localhost', 'http://backend:80', 'active')
ON CONFLICT (domain) DO NOTHING;


