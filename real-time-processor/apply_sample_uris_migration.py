#!/usr/bin/env python3
"""Script para aplicar migración de sample_uris"""
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

host = os.getenv('POSTGRES_HOST', 'localhost')
port = os.getenv('POSTGRES_PORT', '5432')
database = os.getenv('POSTGRES_DB', 'soc_ai')
user = os.getenv('POSTGRES_USER', 'soc_user')
password = os.getenv('POSTGRES_PASSWORD', '')

print("🔧 Aplicando migración add_sample_uris_to_episodes...")

conn = psycopg2.connect(host=host, port=port, database=database, user=user, password=password)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cursor = conn.cursor()

cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'episodes' AND column_name = 'sample_uris'")
if cursor.fetchone():
    print("ℹ️  La columna 'sample_uris' ya existe.")
else:
    cursor.execute("ALTER TABLE episodes ADD COLUMN IF NOT EXISTS sample_uris JSONB DEFAULT '[]'::jsonb;")
    cursor.execute("COMMENT ON COLUMN episodes.sample_uris IS 'Muestra de URIs (hasta 10) para contexto del episodio';")
    print("✅ Migración aplicada exitosamente!")

cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'episodes' AND column_name = 'sample_uris'")
result = cursor.fetchone()
if result:
    print(f"✅ Verificado: {result[0]} ({result[1]})")

cursor.close()
conn.close()
