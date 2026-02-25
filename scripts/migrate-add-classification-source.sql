-- Migración: Agregar columna classification_source a waf_logs
-- Este script se puede ejecutar manualmente si la tabla ya existe

-- Agregar columna si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'waf_logs' 
        AND column_name = 'classification_source'
    ) THEN
        ALTER TABLE waf_logs 
        ADD COLUMN classification_source VARCHAR(50);
        
        -- Crear índice
        CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source 
        ON waf_logs(classification_source);
        
        RAISE NOTICE 'Columna classification_source agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna classification_source ya existe';
    END IF;
END $$;

-- Comentario para documentación
COMMENT ON COLUMN waf_logs.classification_source IS 
'Fuente de clasificación: ml (Random Forest), hybrid_ml (RF+KNN+KMeans), llm (Gemini), heuristic, pending';












