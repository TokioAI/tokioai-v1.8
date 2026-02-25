-- Agregar columnas OWASP a waf_logs si no existen
-- Estas columnas se usan para almacenar la clasificación OWASP Top 10

ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS owasp_code VARCHAR(20);
ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS owasp_category VARCHAR(100);

-- Crear índice para búsquedas por OWASP
CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_code ON waf_logs (owasp_code);
CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_category ON waf_logs (owasp_category);









