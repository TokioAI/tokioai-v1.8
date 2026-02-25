"""
Persistencia del baseline de URLs válidas en PostgreSQL
"""
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Set, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

def get_postgres_connection():
    """Obtiene conexión a PostgreSQL"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', 5432)),
        database=os.getenv('POSTGRES_DB', 'soc_ai'),
        user=os.getenv('POSTGRES_USER', 'soc_user'),
        password=os.getenv('POSTGRES_PASSWORD', '')
    )

def create_baseline_table_if_not_exists():
    """Crea la tabla de baseline si no existe"""
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS site_baseline_urls (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER,
                    base_url TEXT NOT NULL,
                    url TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER,
                    method TEXT DEFAULT 'GET',
                    first_seen TIMESTAMP DEFAULT NOW(),
                    last_seen TIMESTAMP DEFAULT NOW(),
                    scan_timestamp TIMESTAMP,
                    UNIQUE(tenant_id, url)
                );
                
                CREATE INDEX IF NOT EXISTS idx_baseline_tenant_path 
                    ON site_baseline_urls(tenant_id, path);
                
                CREATE INDEX IF NOT EXISTS idx_baseline_url 
                    ON site_baseline_urls(url);
            """)
            conn.commit()
            logger.info("✅ Tabla site_baseline_urls creada/verificada")
    except Exception as e:
        logger.error(f"Error creando tabla baseline: {e}", exc_info=True)

def save_baseline_scan(scan_result: Dict, tenant_id: Optional[int] = None):
    """Guarda el resultado de un escaneo de baseline"""
    create_baseline_table_if_not_exists()
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor()
            
            base_url = scan_result.get('base_url')
            scan_timestamp = scan_result.get('scan_timestamp')
            valid_urls = scan_result.get('valid_urls', [])
            
            # Actualizar o insertar URLs
            for url_data in valid_urls:
                url = url_data.get('url')
                path = url_data.get('path')
                status = url_data.get('status')
                method = url_data.get('method', 'GET')
                last_seen = url_data.get('last_seen', datetime.now().isoformat())
                
                cursor.execute("""
                    INSERT INTO site_baseline_urls 
                        (tenant_id, base_url, url, path, status_code, method, last_seen, scan_timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, url) 
                    DO UPDATE SET
                        last_seen = EXCLUDED.last_seen,
                        scan_timestamp = EXCLUDED.scan_timestamp,
                        status_code = EXCLUDED.status_code
                """, (tenant_id, base_url, url, path, status, method, last_seen, scan_timestamp))
            
            conn.commit()
            logger.info(f"✅ Baseline guardado: {len(valid_urls)} URLs para tenant {tenant_id}")
            
    except Exception as e:
        logger.error(f"Error guardando baseline: {e}", exc_info=True)

def get_valid_urls(tenant_id: Optional[int] = None, base_url: Optional[str] = None) -> Set[str]:
    """Obtiene todas las URLs válidas del baseline"""
    create_baseline_table_if_not_exists()
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT DISTINCT url FROM site_baseline_urls WHERE 1=1"
            params = []
            
            if tenant_id is not None:
                query += " AND tenant_id = %s"
                params.append(tenant_id)
            
            if base_url:
                query += " AND base_url = %s"
                params.append(base_url)
            
            cursor.execute(query, params)
            urls = {row[0] for row in cursor.fetchall()}
            
            return urls
            
    except Exception as e:
        logger.error(f"Error obteniendo URLs válidas: {e}", exc_info=True)
        return set()

def get_valid_paths(tenant_id: Optional[int] = None, base_url: Optional[str] = None) -> Set[str]:
    """Obtiene todos los paths válidos del baseline"""
    create_baseline_table_if_not_exists()
    
    try:
        with get_postgres_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT DISTINCT path FROM site_baseline_urls WHERE 1=1"
            params = []
            
            if tenant_id is not None:
                query += " AND tenant_id = %s"
                params.append(tenant_id)
            
            if base_url:
                query += " AND base_url = %s"
                params.append(base_url)
            
            cursor.execute(query, params)
            paths = {row[0] for row in cursor.fetchall()}
            
            return paths
            
    except Exception as e:
        logger.error(f"Error obteniendo paths válidos: {e}", exc_info=True)
        return set()

def is_url_valid(url: str, tenant_id: Optional[int] = None, base_url: Optional[str] = None) -> bool:
    """Verifica si una URL está en el baseline"""
    valid_urls = get_valid_urls(tenant_id, base_url)
    return url in valid_urls

def is_path_valid(path: str, tenant_id: Optional[int] = None) -> bool:
    """Verifica si un path está en el baseline"""
    valid_paths = get_valid_paths(tenant_id)
    return path in valid_paths








