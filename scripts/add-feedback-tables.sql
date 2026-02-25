-- Tabla para almacenar retroalimentación ML ← LLM
-- Ejecutar en Cloud SQL PostgreSQL

CREATE TABLE IF NOT EXISTS ml_feedback_logs (
    id SERIAL PRIMARY KEY,
    waf_log_id INTEGER REFERENCES waf_logs(id) ON DELETE CASCADE,
    original_ml_prediction VARCHAR(50),
    original_ml_confidence REAL,
    corrected_threat_type VARCHAR(50) NOT NULL,
    llm_confidence REAL NOT NULL,
    ml_model_id VARCHAR(100),
    feedback_date TIMESTAMP DEFAULT NOW(),
    used_for_training BOOLEAN DEFAULT FALSE,
    training_batch_id VARCHAR(50),
    notes TEXT
);

-- Índices para optimizar queries de retroalimentación
CREATE INDEX IF NOT EXISTS idx_ml_feedback_used ON ml_feedback_logs(used_for_training) WHERE used_for_training = false;
CREATE INDEX IF NOT EXISTS idx_ml_feedback_date ON ml_feedback_logs(feedback_date DESC);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_llm_confidence ON ml_feedback_logs(llm_confidence DESC) WHERE llm_confidence >= 0.8;
CREATE INDEX IF NOT EXISTS idx_ml_feedback_waf_log_id ON ml_feedback_logs(waf_log_id);

-- Tabla para tracking de reentrenamientos automáticos
CREATE TABLE IF NOT EXISTS ml_retraining_history (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(100) NOT NULL,
    previous_model_id VARCHAR(100),
    training_date TIMESTAMP DEFAULT NOW(),
    feedback_samples_used INTEGER DEFAULT 0,
    original_samples_used INTEGER DEFAULT 0,
    accuracy_before REAL,
    accuracy_after REAL,
    improvement REAL,
    status VARCHAR(20) DEFAULT 'pending', -- pending, completed, failed, rejected
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_ml_retraining_date ON ml_retraining_history(training_date DESC);
CREATE INDEX IF NOT EXISTS idx_ml_retraining_status ON ml_retraining_history(status);

-- Verificar tablas creadas
SELECT table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('ml_feedback_logs', 'ml_retraining_history')
ORDER BY table_name, ordinal_position;

