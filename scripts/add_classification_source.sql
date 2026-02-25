-- Agregar campo classification_source a waf_logs
ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS classification_source VARCHAR(50);

-- Crear índice para consultas rápidas
CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source ON waf_logs(classification_source);

-- Comentario para documentación
COMMENT ON COLUMN waf_logs.classification_source IS 'Fuente de clasificación: waf_local, ml_llm, ml_only, llm_only';

