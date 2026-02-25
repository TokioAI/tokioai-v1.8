-- Migración 004: Agregar columnas OWASP a waf_logs
-- Agrega campos para clasificación OWASP Top 10

DO $$ 
BEGIN
    -- Agregar owasp_code si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='owasp_code') THEN
        ALTER TABLE waf_logs ADD COLUMN owasp_code VARCHAR(20);
    END IF;
    
    -- Agregar owasp_category si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='owasp_category') THEN
        ALTER TABLE waf_logs ADD COLUMN owasp_category VARCHAR(100);
    END IF;
    
    -- Agregar ml_confidence si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='ml_confidence') THEN
        ALTER TABLE waf_logs ADD COLUMN ml_confidence REAL;
    END IF;
    
    -- Agregar llm_confidence si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='llm_confidence') THEN
        ALTER TABLE waf_logs ADD COLUMN llm_confidence REAL;
    END IF;
END $$;

-- Índices para OWASP
CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_code ON waf_logs(owasp_code) WHERE owasp_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_category ON waf_logs(owasp_category) WHERE owasp_category IS NOT NULL;
