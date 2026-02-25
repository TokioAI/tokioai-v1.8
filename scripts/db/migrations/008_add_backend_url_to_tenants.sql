-- Migración 008: Agregar backend_url a tabla tenants
-- Permite especificar la URL del backend para cada tenant

DO $$ 
BEGIN
    -- Agregar backend_url si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='tenants' AND column_name='backend_url') THEN
        ALTER TABLE tenants ADD COLUMN backend_url VARCHAR(500);
    END IF;
END $$;

-- Actualizar tenants existentes sin backend_url con un valor por defecto
UPDATE tenants 
SET backend_url = 'http://localhost:3000' 
WHERE backend_url IS NULL;

-- Hacer backend_url NOT NULL después de actualizar
DO $$ 
BEGIN
    ALTER TABLE tenants ALTER COLUMN backend_url SET NOT NULL;
EXCEPTION
    WHEN OTHERS THEN
        -- Si falla, puede ser que ya sea NOT NULL
        NULL;
END $$;
