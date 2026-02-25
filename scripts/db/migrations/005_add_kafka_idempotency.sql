-- Migración 005: Agregar campos de Kafka para idempotencia
-- Permite evitar duplicados usando metadata de Kafka

DO $$ 
BEGIN
    -- Agregar kafka_topic si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='kafka_topic') THEN
        ALTER TABLE waf_logs ADD COLUMN kafka_topic VARCHAR(100);
    END IF;
    
    -- Agregar kafka_partition si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='kafka_partition') THEN
        ALTER TABLE waf_logs ADD COLUMN kafka_partition INTEGER;
    END IF;
    
    -- Agregar kafka_offset si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='waf_logs' AND column_name='kafka_offset') THEN
        ALTER TABLE waf_logs ADD COLUMN kafka_offset BIGINT;
    END IF;
END $$;

-- Índice único compuesto para evitar duplicados de Kafka
CREATE UNIQUE INDEX IF NOT EXISTS idx_waf_logs_kafka_unique 
ON waf_logs(kafka_topic, kafka_partition, kafka_offset) 
WHERE kafka_topic IS NOT NULL AND kafka_partition IS NOT NULL AND kafka_offset IS NOT NULL;
