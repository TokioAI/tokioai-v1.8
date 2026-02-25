#!/usr/bin/env python3
"""
Script para aplicar migraciones SQL a PostgreSQL
Se ejecuta desde Cloud Run o localmente con acceso a Cloud SQL
"""
import os
import psycopg2
from psycopg2 import sql

# Configuración de PostgreSQL
PG_HOST = os.getenv('POSTGRES_HOST', '/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME')
PG_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
PG_DB = os.getenv('POSTGRES_DB', 'soc_ai')
PG_USER = os.getenv('POSTGRES_USER', 'soc_user')
PG_PASSWORD = os.getenv('POSTGRES_PASSWORD')

def apply_migrations():
    """Aplica todas las migraciones SQL necesarias"""
    try:
        # Conectar a PostgreSQL
        if PG_HOST.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME"✅ Conectado a PostgreSQL")
        print("📋 Aplicando migraciones...")
        
        # Migración 1: Columnas de Kafka
        print("\n1️⃣  Aplicando migración de Kafka idempotency...")
        cursor.execute("""
            ALTER TABLE waf_logs 
            ADD COLUMN IF NOT EXISTS kafka_topic VARCHAR(255),
            ADD COLUMN IF NOT EXISTS kafka_partition INTEGER,
            ADD COLUMN IF NOT EXISTS kafka_offset BIGINT;
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_waf_logs_kafka_metadata 
            ON waf_logs (kafka_topic, kafka_partition, kafka_offset);
        """)
        
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_waf_logs_kafka_unique 
            ON waf_logs (kafka_topic, kafka_partition, kafka_offset)
            WHERE kafka_topic IS NOT NULL AND kafka_partition IS NOT NULL AND kafka_offset IS NOT NULL;
        """)
        
        print("   ✅ Columnas de Kafka agregadas")
        
        # Migración 2: Columnas OWASP
        print("\n2️⃣  Aplicando migración de columnas OWASP...")
        cursor.execute("""
            ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS owasp_code VARCHAR(20);
        """)
        
        cursor.execute("""
            ALTER TABLE waf_logs ADD COLUMN IF NOT EXISTS owasp_category VARCHAR(100);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_code ON waf_logs (owasp_code);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_waf_logs_owasp_category ON waf_logs (owasp_category);
        """)
        
        print("   ✅ Columnas OWASP agregadas")
        
        # Verificar que las columnas existen
        print("\n3️⃣  Verificando columnas...")
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'waf_logs' 
            AND column_name IN ('kafka_topic', 'kafka_partition', 'kafka_offset', 'owasp_code', 'owasp_category')
            ORDER BY column_name;
        """)
        
        columns = cursor.fetchall()
        print(f"   ✅ Columnas encontradas: {[col[0] for col in columns]}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("\n✅ Todas las migraciones aplicadas correctamente!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error aplicando migraciones: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if not PG_PASSWORD:
        print("❌ Error: POSTGRES_PASSWORD no está configurado")
        exit(1)
    
    success = apply_migrations()
    exit(0 if success else 1)









