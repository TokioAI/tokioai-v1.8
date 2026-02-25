#!/usr/bin/env python3
"""
Sistema de migraciones automático para Tokio AI
Lee todos los archivos .sql en scripts/db/migrations/ con prefijo numérico
y los aplica en orden, registrando cada migración en schema_migrations
"""
import os
import sys
import logging
import psycopg2
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# PostgreSQL configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "soc_ai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "soc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))


def get_migration_files(migrations_dir: Path) -> List[Tuple[str, Path]]:
    """
    Obtiene todos los archivos de migración ordenados por prefijo numérico
    Formato esperado: 001_nombre.sql, 002_otro.sql, etc.
    """
    migrations = []
    for file in sorted(migrations_dir.glob("*.sql")):
        name = file.name
        # Extraer el número del prefijo
        if '_' in name:
            prefix = name.split('_')[0]
            try:
                num = int(prefix)
                migrations.append((num, file))
            except ValueError:
                logger.warning(f"⚠️  Archivo de migración sin prefijo numérico válido: {name}")
        else:
            logger.warning(f"⚠️  Archivo de migración sin formato correcto (NNN_nombre.sql): {name}")
    
    # Ordenar por número
    migrations.sort(key=lambda x: x[0])
    return migrations


def ensure_schema_migrations_table(conn):
    """Crea la tabla schema_migrations si no existe"""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    conn.commit()
    cursor.close()


def get_applied_migrations(conn) -> set:
    """Obtiene el conjunto de versiones ya aplicadas"""
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_migrations")
    applied = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return applied


def apply_migration(conn, version: str, file_path: Path) -> bool:
    """
    Aplica una migración SQL
    Retorna True si fue exitosa, False en caso contrario
    """
    try:
        cursor = conn.cursor()
        
        # Leer el contenido del archivo
        with open(file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Ejecutar el SQL
        cursor.execute(sql_content)
        conn.commit()
        
        # Registrar la migración
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at)
            VALUES (%s, %s, %s)
        """, (version, file_path.name, datetime.now()))
        conn.commit()
        
        cursor.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error aplicando migración {version} ({file_path.name}): {e}")
        return False


def main():
    """Función principal"""
    # Determinar el directorio de migraciones
    script_dir = Path(__file__).parent
    migrations_dir = script_dir / "migrations"
    
    if not migrations_dir.exists():
        logger.warning(f"⚠️  Directorio de migraciones no existe: {migrations_dir}")
        logger.info("📁 Creando directorio...")
        migrations_dir.mkdir(parents=True, exist_ok=True)
        logger.info("✅ Directorio creado. Agrega archivos de migración con formato: 001_nombre.sql")
        return
    
    # Conectar a PostgreSQL
    try:
        logger.info(f"🔌 Conectando a PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=10
        )
        logger.info("✅ Conectado a PostgreSQL")
    except Exception as e:
        logger.error(f"❌ Error conectando a PostgreSQL: {e}")
        sys.exit(1)
    
    try:
        # Asegurar que existe la tabla de migraciones
        ensure_schema_migrations_table(conn)
        
        # Obtener migraciones aplicadas
        applied = get_applied_migrations(conn)
        logger.info(f"📊 Migraciones ya aplicadas: {len(applied)}")
        
        # Obtener todas las migraciones disponibles
        migrations = get_migration_files(migrations_dir)
        
        if not migrations:
            logger.info("ℹ️  No hay archivos de migración en el directorio")
            return
        
        logger.info(f"📋 Migraciones encontradas: {len(migrations)}")
        
        # Aplicar migraciones pendientes
        applied_count = 0
        failed_count = 0
        
        for num, file_path in migrations:
            version = f"{num:03d}"  # Formato 001, 002, etc.
            
            if version in applied:
                logger.info(f"⏭️  Migración {version} ({file_path.name}) ya aplicada, saltando...")
                continue
            
            logger.info(f"🔄 Aplicando migración {version}: {file_path.name}...")
            
            if apply_migration(conn, version, file_path):
                logger.info(f"✅ Migración {version} aplicada exitosamente")
                applied_count += 1
            else:
                logger.error(f"❌ Migración {version} falló. Deteniendo ejecución.")
                failed_count += 1
                break  # Detener en caso de error
        
        # Resumen
        logger.info(f"\n📊 Resumen:")
        logger.info(f"   ✅ Aplicadas: {applied_count}")
        if failed_count > 0:
            logger.error(f"   ❌ Fallidas: {failed_count}")
            sys.exit(1)
        else:
            logger.info("✅ Todas las migraciones aplicadas correctamente")
    
    finally:
        conn.close()


if __name__ == "__main__":
    main()
