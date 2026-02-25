#!/usr/bin/env python3
"""Script para aplicar migraciones SQL"""
import os
import psycopg2
import sys

PG_HOST = os.getenv('POSTGRES_HOST', '/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME')
PG_DB = os.getenv('POSTGRES_DB', 'soc_ai')
PG_USER = os.getenv('POSTGRES_USER', 'soc_user')
PG_PASSWORD = os.getenv('POSTGRES_PASSWORD')

if not PG_PASSWORD:
    print("❌ Error: POSTGRES_PASSWORD no configurado")
    sys.exit(1)

try:
    print("🔌 Conectando a PostgreSQL...")
    conn = psycopg2.connect(
        host=PG_HOST,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD
    )
    cursor = conn.cursor()
    print("✅ Conectado")
    
    print("\n📋 Aplicando migraciones...")
    
    # Migración 1: Kafka columns
    print("1️⃣  Agregando columnas de Kafka...")
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
    
    # Migración 2: OWASP columns
    print("2️⃣  Agregando columnas OWASP...")
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
    
    # Verificar
    print("\n3️⃣  Verificando columnas...")
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'waf_logs' 
        AND column_name IN ('kafka_topic', 'kafka_partition', 'kafka_offset', 'owasp_code', 'owasp_category')
        ORDER BY column_name;
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print(f"   ✅ Columnas encontradas: {', '.join(columns)}")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n✅ Todas las migraciones aplicadas correctamente!")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)









