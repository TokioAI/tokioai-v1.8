-- Migración: Tabla para historial de reentrenamientos del Learning Loop
-- Permite rastrear el aprendizaje del sistema y mejoras del modelo

CREATE TABLE IF NOT EXISTS learning_history (
    id SERIAL PRIMARY KEY,
    retrain_timestamp TIMESTAMP DEFAULT NOW(),
    labels_used INTEGER NOT NULL,
    labels_since_last INTEGER NOT NULL,
    retrain_threshold INTEGER NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    accuracy_before REAL,
    accuracy_after REAL,
    improvement REAL,
    error_message TEXT,
    model_version VARCHAR(50),
    training_duration_seconds REAL
);

CREATE INDEX IF NOT EXISTS idx_learning_history_timestamp ON learning_history(retrain_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_learning_history_success ON learning_history(success, retrain_timestamp DESC);


