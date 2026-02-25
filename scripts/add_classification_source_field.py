#!/usr/bin/env python3
"""
Script para agregar el campo classification_source a la tabla waf_logs
"""
import psycopg2
import os

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "soc_ai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "soc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))

try:
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    cursor = conn.cursor()
    
    # Agregar columna si no existe
    cursor.execute("""
        ALTER TABLE waf_logs 
        ADD COLUMN IF NOT EXISTS classification_source VARCHAR(50);
    """)
    
    # Crear índice
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_waf_logs_classification_source 
        ON waf_logs(classification_source);
    """)
    
    # Agregar comentario
    cursor.execute("""
        COMMENT ON COLUMN waf_logs.classification_source IS 
        'Fuente de clasificación: waf_local, ml_llm, ml_only, llm_only';
    """)
    
    conn.commit()
    print("✅ Campo classification_source agregado exitosamente")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

