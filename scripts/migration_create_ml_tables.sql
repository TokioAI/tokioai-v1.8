-- FASE 5: Crear tablas para Active Learning y Model Registry

-- Tabla para feedback de ML (correcciones de LLM)
CREATE TABLE IF NOT EXISTS ml_feedback_logs (
    id BIGSERIAL PRIMARY KEY,
    waf_log_id BIGINT REFERENCES waf_logs(id) ON DELETE CASCADE,
    original_prediction VARCHAR(50),  -- Predicción original del ML
    original_confidence FLOAT,  -- Confianza original
    corrected_threat_type VARCHAR(50),  -- Corrección del LLM
    corrected_severity VARCHAR(20),  -- Severidad corregida
    llm_analysis TEXT,  -- Análisis completo del LLM
    feedback_source VARCHAR(50) DEFAULT 'llm',  -- 'llm', 'human', 'auto'
    created_at TIMESTAMP DEFAULT NOW(),
    used_for_training BOOLEAN DEFAULT FALSE,  -- Si ya se usó para entrenar
    training_batch_id VARCHAR(100)  -- ID del batch de entrenamiento
);

-- Índices para ml_feedback_logs
CREATE INDEX IF NOT EXISTS idx_ml_feedback_logs_waf_log_id ON ml_feedback_logs (waf_log_id);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_logs_corrected_threat_type ON ml_feedback_logs (corrected_threat_type);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_logs_created_at ON ml_feedback_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_logs_used_for_training ON ml_feedback_logs (used_for_training);

-- Tabla para registro de modelos (model registry)
CREATE TABLE IF NOT EXISTS ml_model_registry (
    id BIGSERIAL PRIMARY KEY,
    model_id VARCHAR(255) UNIQUE NOT NULL,  -- ID único del modelo
    model_type VARCHAR(50) NOT NULL,  -- 'random_forest', 'svm', etc.
    model_path TEXT NOT NULL,  -- Ruta al archivo del modelo
    scaler_path TEXT NOT NULL,  -- Ruta al scaler
    version INTEGER DEFAULT 1,  -- Versión del modelo
    training_samples INTEGER NOT NULL,  -- Número de muestras de entrenamiento
    test_samples INTEGER NOT NULL,  -- Número de muestras de test
    accuracy FLOAT,
    precision FLOAT,
    recall FLOAT,
    f1_score FLOAT,
    roc_auc FLOAT,
    confusion_matrix JSONB,  -- Matriz de confusión como JSON
    precision_per_class JSONB,  -- Precision por clase
    recall_per_class JSONB,  -- Recall por clase
    f1_per_class JSONB,  -- F1 por clase
    parameters JSONB,  -- Parámetros del modelo
    is_calibrated BOOLEAN DEFAULT FALSE,  -- Si está calibrado
    use_char_ngrams BOOLEAN DEFAULT FALSE,  -- Si usa char n-grams
    confidence_threshold FLOAT DEFAULT 0.7,  -- Threshold de confianza
    margin_threshold FLOAT DEFAULT 0.2,  -- Threshold de margen
    is_active BOOLEAN DEFAULT TRUE,  -- Si es el modelo activo
    created_at TIMESTAMP DEFAULT NOW(),
    deployed_at TIMESTAMP,  -- Cuándo se desplegó
    metadata JSONB  -- Metadata adicional
);

-- Índices para ml_model_registry
CREATE INDEX IF NOT EXISTS idx_ml_model_registry_model_id ON ml_model_registry (model_id);
CREATE INDEX IF NOT EXISTS idx_ml_model_registry_model_type ON ml_model_registry (model_type);
CREATE INDEX IF NOT EXISTS idx_ml_model_registry_is_active ON ml_model_registry (is_active);
CREATE INDEX IF NOT EXISTS idx_ml_model_registry_created_at ON ml_model_registry (created_at DESC);

-- Tabla para tracking de re-entrenamientos
CREATE INDEX IF NOT EXISTS idx_ml_model_registry_f1_score ON ml_model_registry (f1_score DESC);

-- Comentarios
COMMENT ON TABLE ml_feedback_logs IS 'FASE 5: Feedback de ML para active learning - correcciones de LLM';
COMMENT ON TABLE ml_model_registry IS 'FASE 5: Registro de modelos ML con versionado y métricas';









