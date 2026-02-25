#!/usr/bin/env python3
"""
Script para aplicar la migración de sample_uris a la tabla episodes.
Se puede ejecutar desde Cloud Run o localmente.
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def apply_migration():
    """Aplica la migración de sample_uris"""
    
    # Obtener variables de entorno
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    database = os.getenv('POSTGRES_DB', 'soc_ai')
    user = os.getenv('POSTGRES_USER', 'soc_user')
    password = os.getenv('POSTGRES_PASSWORD', '')
    
    print(f"🔧 Aplicando migración add_sample_uris_to_episodes...")
    print(f"Host: {host}")
    print(f"Database: {database}")
    print(f"User: {user}")
    print("")
    
    try:
        # Conectar a la base de datos
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        print("✅ Conexión exitosa a PostgreSQL")
        
        # Verificar si la columna ya existe
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'episodes' 
            AND column_name = 'sample_uris'
        """)
        
        if cursor.fetchone():
            print("ℹ️  La columna 'sample_uris' ya existe. No es necesario aplicar la migración.")
        else:
            print("📝 Aplicando migración...")
            
            # Aplicar la migración
            cursor.execute("""
                ALTER TABLE episodes 
                ADD COLUMN IF NOT EXISTS sample_uris JSONB DEFAULT '[]'::jsonb;
            """)
            
            cursor.execute("""
                COMMENT ON COLUMN episodes.sample_uris IS 'Muestra de URIs (hasta 10) para contexto del episodio';
            """)
            
            print("✅ Migración aplicada exitosamente!")
        
        # Verificar que la columna existe
        cursor.execute("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns 
            WHERE table_name = 'episodes' 
            AND column_name = 'sample_uris'
        """)
        
        result = cursor.fetchone()
        if result:
            print(f"✅ Columna verificada:")
            print(f"   - Nombre: {result[0]}")
            print(f"   - Tipo: {result[1]}")
            print(f"   - Default: {result[2]}")
        else:
            print("❌ Error: La columna no se encontró después de la migración")
            sys.exit(1)
        
        cursor.close()
        conn.close()
        
        print("\n✅ Proceso completado exitosamente")
        return True
        
    except Exception as e:
        print(f"❌ Error al aplicar migración: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    apply_migration()


