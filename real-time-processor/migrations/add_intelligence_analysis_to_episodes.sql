-- Migración: Agregar campo intelligence_analysis a la tabla episodes
-- Este campo almacena las detecciones avanzadas (zero-day, ofuscación, DDoS)

-- Agregar columna intelligence_analysis como JSONB
ALTER TABLE episodes 
ADD COLUMN IF NOT EXISTS intelligence_analysis JSONB;

-- Índice GIN para búsqueda rápida en JSONB
CREATE INDEX IF NOT EXISTS idx_episodes_intelligence_analysis 
ON episodes USING GIN(intelligence_analysis);

-- Índices adicionales para búsqueda específica
CREATE INDEX IF NOT EXISTS idx_episodes_zero_day_risk 
ON episodes((intelligence_analysis->>'zero_day_risk'));

CREATE INDEX IF NOT EXISTS idx_episodes_obfuscation_detected 
ON episodes((intelligence_analysis->>'obfuscation_detected'));

CREATE INDEX IF NOT EXISTS idx_episodes_ddos_risk 
ON episodes((intelligence_analysis->>'ddos_risk'));

-- Comentario para documentación
COMMENT ON COLUMN episodes.intelligence_analysis IS 'Análisis de inteligencia: zero-day, ofuscación, DDoS. Estructura: {"zero_day_risk": bool, "obfuscation_detected": bool, "ddos_risk": bool, "enhanced_risk_score": float, "analysis_details": {...}}';

