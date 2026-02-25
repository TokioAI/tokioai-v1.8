-- Migración 003: Sistema de Episodios de Ataque
-- Tablas para agrupar logs relacionados en episodios de ataque

-- Tabla de episodios
CREATE TABLE IF NOT EXISTS episodes (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(45) NOT NULL,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    episode_start TIMESTAMP NOT NULL,
    episode_end TIMESTAMP,
    duration_seconds INTEGER,
    total_requests INTEGER DEFAULT 0,
    unique_uris INTEGER DEFAULT 0,
    risk_score REAL DEFAULT 0.0,
    decision VARCHAR(20) DEFAULT 'PENDIENTE' CHECK (decision IN ('PENDIENTE', 'BLOQUEADO', 'PERMITIDO', 'AUTO')),
    threat_types TEXT[],
    severity VARCHAR(20) DEFAULT 'low',
    ml_prediction REAL,
    llm_analysis JSONB,
    flags_active TEXT[],
    sample_uris TEXT[],
    intelligence_analysis JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_episodes_ip ON episodes(ip);
CREATE INDEX IF NOT EXISTS idx_episodes_tenant_id ON episodes(tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_episodes_episode_start ON episodes(episode_start DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_decision ON episodes(decision);
CREATE INDEX IF NOT EXISTS idx_episodes_risk_score ON episodes(risk_score DESC);
