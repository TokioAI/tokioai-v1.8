-- FASE 2: Migración para agregar idempotencia en waf_logs usando metadata de Kafka
-- Agrega columnas kafka_topic, kafka_partition, kafka_offset y constraint UNIQUE

-- Agregar columnas de Kafka (si no existen)
ALTER TABLE waf_logs 
ADD COLUMN IF NOT EXISTS kafka_topic VARCHAR(255),
ADD COLUMN IF NOT EXISTS kafka_partition INTEGER,
ADD COLUMN IF NOT EXISTS kafka_offset BIGINT;

-- Crear índice para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_waf_logs_kafka_metadata 
ON waf_logs (kafka_topic, kafka_partition, kafka_offset);

-- Crear constraint UNIQUE para idempotencia (evita duplicados)
-- Nota: Solo crear si las columnas tienen valores no-null
-- Primero, hacer las columnas nullable para logs antiguos
-- Luego, agregar constraint solo para nuevos logs

-- Opción 1: Constraint UNIQUE parcial (solo para logs con metadata de Kafka)
-- PostgreSQL no soporta UNIQUE parcial directamente, así que usamos un índice único parcial
CREATE UNIQUE INDEX IF NOT EXISTS idx_waf_logs_kafka_unique 
ON waf_logs (kafka_topic, kafka_partition, kafka_offset)
WHERE kafka_topic IS NOT NULL AND kafka_partition IS NOT NULL AND kafka_offset IS NOT NULL;

-- Opción 2: Si queremos constraint UNIQUE completo (requiere que todos los logs tengan metadata)
-- Primero actualizar logs existentes con valores dummy (opcional)
-- UPDATE waf_logs SET kafka_topic = 'waf-logs', kafka_partition = 0, kafka_offset = -1 
-- WHERE kafka_topic IS NULL;

-- Luego hacer las columnas NOT NULL (solo si actualizamos todos los logs)
-- ALTER TABLE waf_logs 
-- ALTER COLUMN kafka_topic SET NOT NULL,
-- ALTER COLUMN kafka_partition SET NOT NULL,
-- ALTER COLUMN kafka_offset SET NOT NULL;

-- Y finalmente agregar constraint UNIQUE completo
-- ALTER TABLE waf_logs 
-- ADD CONSTRAINT unique_kafka_message 
-- UNIQUE (kafka_topic, kafka_partition, kafka_offset);

-- Comentarios para documentación
COMMENT ON COLUMN waf_logs.kafka_topic IS 'Topic de Kafka de donde vino el mensaje (FASE 2: idempotencia)';
COMMENT ON COLUMN waf_logs.kafka_partition IS 'Partición de Kafka de donde vino el mensaje (FASE 2: idempotencia)';
COMMENT ON COLUMN waf_logs.kafka_offset IS 'Offset de Kafka del mensaje (FASE 2: idempotencia)';









