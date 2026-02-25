-- Migración: Agregar sample_uris a episodes para mostrar URIs de ejemplo
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS sample_uris JSONB DEFAULT '[]'::jsonb;

-- Comentario
COMMENT ON COLUMN episodes.sample_uris IS 'Muestra de URIs (hasta 10) para contexto del episodio';


