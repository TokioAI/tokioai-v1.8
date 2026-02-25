-- Migración: Tablas para análisis por episodios
-- Permite agrupar logs en episodios y aprendizaje incremental supervisado

-- Tabla de episodios
CREATE TABLE IF NOT EXISTS episodes (
    episode_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255),
    src_ip INET NOT NULL,
    user_agent_hash VARCHAR(64) NOT NULL,
    episode_start TIMESTAMP NOT NULL,
    episode_end TIMESTAMP,
    total_requests INTEGER DEFAULT 0,
    unique_uris INTEGER DEFAULT 0,
    methods_count JSONB,
    status_code_ratio JSONB,  -- {"2xx": 0.8, "3xx": 0.1, "4xx": 0.1, "5xx": 0.0}
    presence_flags JSONB,  -- {".env": true, "../": true, "wp-": false}
    path_entropy_avg FLOAT,
    request_rate FLOAT,  -- requests per second
    risk_score FLOAT,
    decision VARCHAR(20),  -- ALLOW, BLOCK, UNCERTAIN
    llm_consulted BOOLEAN DEFAULT FALSE,
    llm_label VARCHAR(50),  -- Label del LLM si fue consultado
    llm_confidence FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT episodes_decision_check CHECK (decision IN ('ALLOW', 'BLOCK', 'UNCERTAIN'))
);

-- Índices para búsqueda rápida
CREATE INDEX IF NOT EXISTS idx_episode_lookup ON episodes(tenant_id, src_ip, user_agent_hash, episode_start);
CREATE INDEX IF NOT EXISTS idx_episode_decision ON episodes(decision, created_at);
CREATE INDEX IF NOT EXISTS idx_episode_ip_time ON episodes(src_ip, episode_start DESC);
CREATE INDEX IF NOT EXISTS idx_episode_risk_score ON episodes(risk_score DESC) WHERE risk_score IS NOT NULL;

-- Tabla de etiquetas humanas (human-in-the-loop)
CREATE TABLE IF NOT EXISTS analyst_labels (
    label_id SERIAL PRIMARY KEY,
    episode_id INTEGER REFERENCES episodes(episode_id) ON DELETE CASCADE,
    episode_features_json JSONB NOT NULL,
    analyst_label VARCHAR(50) NOT NULL,  -- ALLOW, PATH_TRAVERSAL, XSS, SQLI, SCAN_PROBE, etc.
    analyst_notes TEXT,
    analyst_id VARCHAR(255),  -- Usuario que etiquetó
    confidence FLOAT CHECK (confidence >= 0.0 AND confidence <= 1.0),
    timestamp TIMESTAMP DEFAULT NOW(),
    CONSTRAINT analyst_label_check CHECK (analyst_label IN (
        'ALLOW', 'PATH_TRAVERSAL', 'XSS', 'SQLI', 'SCAN_PROBE', 
        'CMD_INJECTION', 'SSRF', 'MULTIPLE_ATTACKS', 'UNAUTHORIZED_ACCESS'
    ))
);

-- Índices para búsqueda de etiquetas
CREATE INDEX IF NOT EXISTS idx_episode_label ON analyst_labels(episode_id);
CREATE INDEX IF NOT EXISTS idx_analyst_label ON analyst_labels(analyst_label, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_features ON analyst_labels USING GIN(episode_features_json);

-- Tabla de similitud de episodios (cache para búsqueda rápida)
CREATE TABLE IF NOT EXISTS episode_similarity_cache (
    episode_id INTEGER REFERENCES episodes(episode_id) ON DELETE CASCADE,
    similar_episode_id INTEGER REFERENCES episodes(episode_id) ON DELETE CASCADE,
    similarity_score FLOAT CHECK (similarity_score >= 0.0 AND similarity_score <= 1.0),
    cached_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (episode_id, similar_episode_id)
);

-- Índice para búsqueda de similitud
CREATE INDEX IF NOT EXISTS idx_similarity ON episode_similarity_cache(episode_id, similarity_score DESC);

-- Comentarios para documentación
COMMENT ON TABLE episodes IS 'Episodios de tráfico agrupados por (tenant_id, src_ip, user_agent_hash, time_window=5min)';
COMMENT ON TABLE analyst_labels IS 'Etiquetas humanas para aprendizaje supervisado';
COMMENT ON TABLE episode_similarity_cache IS 'Cache de similitud entre episodios para búsqueda rápida';




