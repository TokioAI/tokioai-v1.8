"""
Módulo independiente para gestión de conexiones PostgreSQL
Resuelve el import circular entre app.py y endpoints_cli.py
"""
import os
import time
import logging
from contextlib import contextmanager
from typing import Optional
from fastapi import HTTPException, status
from psycopg2.pool import SimpleConnectionPool

logger = logging.getLogger(__name__)

# PostgreSQL configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "soc_ai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "soc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))

_postgres_pool: Optional[SimpleConnectionPool] = None


def _get_postgres_conn():
    """Obtiene una conexión del pool de PostgreSQL"""
    global _postgres_pool
    
    try:
        if _postgres_pool is None:
            # CORREGIDO: Verificar que POSTGRES_HOST no sea None
            if not POSTGRES_HOST:
                raise ValueError("POSTGRES_HOST no está configurado")
            
            # Si POSTGRES_HOST es un socket Unix de Cloud SQL
            if POSTGRES_HOST.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME"SELECT 1")
                        cursor.fetchone()
                        cursor.close()
                        return conn
                    except Exception as e:
                        # Si la conexión está muerta, cerrarla y obtener una nueva
                        logger.warning(f"Conexión muerta detectada (intento {attempt + 1}/{max_retries}), cerrando y obteniendo nueva: {e}")
                        try:
                            conn.close()
                        except:
                            pass
                        # Continuar el loop para obtener una nueva conexión
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Backoff exponencial
                        continue
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error obteniendo conexión del pool (intento {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponencial
                else:
                    logger.error(f"Error obteniendo conexión del pool después de {max_retries} intentos: {e}")
        
        # Si no hay conexión disponible después de los reintentos, lanzar excepción
        raise Exception(f"No hay conexiones disponibles en el pool después de {max_retries} intentos.")
    except Exception as e:
        logger.error(f"Error obteniendo conexión PostgreSQL: {e}")
        # NO crear conexiones directas fuera del pool (causan conexiones huérfanas)
        # En su lugar, lanzar excepción para que se maneje apropiadamente
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error conectando a PostgreSQL: {str(e)}"
        )


def _return_postgres_conn(conn):
    """Devuelve una conexión al pool"""
    global _postgres_pool
    if conn:
        try:
            # Verificar si la conexión está en el pool o es directa
            if _postgres_pool:
                try:
                    # Verificar si la conexión está cerrada
                    if conn.closed == 0:
                        _postgres_pool.putconn(conn)
                    else:
                        # Si está cerrada, no devolverla al pool
                        pass
                except Exception as e:
                    # Si falla al devolver, cerrar la conexión
                    try:
                        if conn.closed == 0:
                            conn.close()
                    except Exception:
                        pass
            else:
                # Si no hay pool, cerrar la conexión directa
                try:
                    if conn.closed == 0:
                        conn.close()
                except Exception:
                    pass
        except Exception:
            # Si falla todo, intentar cerrar
            try:
                if hasattr(conn, 'closed') and conn.closed == 0:
                    conn.close()
            except Exception:
                pass


@contextmanager
def get_postgres_connection():
    """Context manager para obtener y devolver conexiones PostgreSQL del pool"""
    conn = None
    try:
        conn = _get_postgres_conn()
        yield conn
    except Exception as e:
        # Si hay un error, hacer rollback antes de devolver la conexión
        if conn:
            try:
                if not conn.closed:
                    conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            _return_postgres_conn(conn)
