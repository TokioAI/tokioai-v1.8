#!/usr/bin/env python3
"""
Script para sincronizar IPs bloqueadas desde PostgreSQL a nginx.
Este script se ejecuta en el servidor WAF y actualiza el archivo auto-blocked-ips.conf
con las IPs que están bloqueadas activamente en PostgreSQL.

OPTIMIZADO para:
- Procesamiento rápido (consultas eficientes)
- Rate limiting inteligente (no sobrecargar Nginx)
- Batch processing (procesar cambios en lotes)
"""

import os
import sys
import logging
import psycopg2
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import time
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'soc_ai')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'soc_user')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')

# Ruta del archivo de configuración de nginx
NGINX_BLOCKED_IPS_FILE = os.getenv('NGINX_BLOCKED_IPS_FILE', '/opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf')
NGINX_RELOAD_COMMAND = os.getenv('NGINX_RELOAD_COMMAND', 'docker exec tokio-ai-modsecurity-nginx nginx -s reload')

# Configuración de rate limiting para recargas de Nginx
NGINX_RELOAD_MIN_INTERVAL = int(os.getenv('NGINX_RELOAD_MIN_INTERVAL', '10'))  # Mínimo 10 segundos entre recargas
NGINX_RELOAD_STATE_FILE = '/tmp/nginx-reload-state.json'  # Archivo para trackear última recarga
MAX_IPS_PER_BATCH = int(os.getenv('MAX_IPS_PER_BATCH', '1000'))  # Máximo de IPs a procesar por vez


def get_blocked_ips_from_postgres():
    """Obtiene las IPs bloqueadas activas desde PostgreSQL"""
    try:
        # Conectar a PostgreSQL
        # En el servidor WAF, usar conexión TCP (no socket Unix)
        # Si POSTGRES_HOST es un socket de Cloud SQL, intentar obtener IP desde variable de entorno
        postgres_host = POSTGRES_HOST
        
        # Si es un socket de Cloud SQL, intentar usar IP directa o variable de entorno
        if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME")
        
        conn = psycopg2.connect(
            host=postgres_host,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=10
        )
        
        cursor = conn.cursor()
        
        # Obtener IPs bloqueadas activas
        # Primero intentar desde tabla blocked_ips, luego desde waf_logs
        blocked_ips = set()
        
        # Verificar si la tabla blocked_ips existe
        try:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'blocked_ips'
                )
            """)
            blocked_ips_table_exists = cursor.fetchone()[0]
            
            if blocked_ips_table_exists:
                cursor.execute("""
                    SELECT DISTINCT ip 
                    FROM blocked_ips 
                    WHERE active = TRUE 
                    AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY ip
                """)
                results = cursor.fetchall()
                blocked_ips.update([row[0] for row in results])
                logger.info(f"✅ Obtenidas {len(blocked_ips)} IPs desde tabla blocked_ips")
            else:
                logger.info("ℹ️ Tabla blocked_ips no existe, usando solo waf_logs")
        except Exception as e:
            logger.warning(f"⚠️ Error verificando tabla blocked_ips: {e}")
        
        # NOTA: Ya no consultamos waf_logs directamente porque blocked_ips es la fuente de verdad
        # Todos los bloqueos (incluyendo los de time_window_soc_analysis) se guardan en blocked_ips
        # y respetan el estado active y expires_at
        logger.info(f"✅ Obtenidas {len(blocked_ips)} IPs bloqueadas desde tabla blocked_ips (fuente única de verdad)")
        
        cursor.close()
        conn.close()
        
        return sorted(blocked_ips)
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo IPs bloqueadas desde PostgreSQL: {e}", exc_info=True)
        return []


def update_nginx_blocked_ips_file(blocked_ips):
    """Actualiza el archivo de configuración de nginx con las IPs bloqueadas"""
    try:
        config_path = Path(NGINX_BLOCKED_IPS_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Leer IPs actualmente bloqueadas en el archivo
        current_blocked_ips = set()
        if config_path.exists():
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('deny ') and line.endswith(';'):
                        blocked_ip = line.replace('deny ', '').replace(';', '').strip()
                        current_blocked_ips.add(blocked_ip)
        
        # Verificar si hay cambios
        blocked_ips_set = set(blocked_ips)
        if current_blocked_ips == blocked_ips_set:
            logger.info(f"ℹ️ No hay cambios en las IPs bloqueadas ({len(blocked_ips)} IPs)")
            return False
        
        # Escribir nuevo archivo
        with open(config_path, 'w') as f:
            f.write("# IPs bloqueadas automáticamente por auto-mitigation\n")
            f.write("# Este archivo se genera automáticamente por sync-blocked-ips-to-nginx.py\n")
            f.write(f"# Última actualización: {datetime.now().isoformat()}\n")
            f.write("# NO EDITAR MANUALMENTE - los cambios se sobrescribirán\n\n")
            
            if blocked_ips:
                for ip in blocked_ips:
                    f.write(f"deny {ip};\n")
            else:
                f.write("# No hay IPs bloqueadas actualmente\n")
        
        logger.info(f"✅ Archivo {config_path} actualizado con {len(blocked_ips)} IPs bloqueadas")
        
        # Listar IPs nuevas y removidas
        new_ips = blocked_ips_set - current_blocked_ips
        removed_ips = current_blocked_ips - blocked_ips_set
        
        if new_ips:
            logger.info(f"➕ IPs nuevas bloqueadas: {', '.join(sorted(new_ips))}")
        if removed_ips:
            logger.info(f"➖ IPs desbloqueadas: {', '.join(sorted(removed_ips))}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error actualizando archivo de configuración de nginx: {e}", exc_info=True)
        return False


def should_reload_nginx():
    """Determina si se debe recargar Nginx basado en rate limiting"""
    state_file = Path(NGINX_RELOAD_STATE_FILE)
    
    if not state_file.exists():
        return True
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            last_reload = datetime.fromisoformat(state.get('last_reload', '2000-01-01T00:00:00'))
            time_since_reload = (datetime.now() - last_reload).total_seconds()
            
            if time_since_reload < NGINX_RELOAD_MIN_INTERVAL:
                logger.debug(f"⏳ Rate limiting: {time_since_reload:.1f}s desde última recarga (mínimo: {NGINX_RELOAD_MIN_INTERVAL}s)")
                return False
            
            return True
    except Exception as e:
        logger.warning(f"⚠️ Error leyendo estado de recarga: {e}, permitiendo recarga")
        return True


def save_reload_state():
    """Guarda el estado de la última recarga de Nginx"""
    try:
        state = {
            'last_reload': datetime.now().isoformat()
        }
        with open(NGINX_RELOAD_STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        logger.warning(f"⚠️ Error guardando estado de recarga: {e}")


def reload_nginx(force=False):
    """Recarga la configuración de nginx con rate limiting inteligente"""
    if not NGINX_RELOAD_COMMAND:
        logger.warning("⚠️ NGINX_RELOAD_COMMAND no configurado, nginx no se recargará automáticamente")
        return False
    
    # Verificar rate limiting (a menos que sea forzado)
    if not force and not should_reload_nginx():
        logger.info("⏳ Recarga de Nginx diferida por rate limiting (cambios se aplicarán en la próxima recarga)")
        return False
    
    try:
        start_time = time.time()
        result = subprocess.run(
            NGINX_RELOAD_COMMAND.split(),
            capture_output=True,
            text=True,
            timeout=10
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            logger.info(f"✅ Nginx recargado exitosamente en {elapsed:.2f}s")
            save_reload_state()
            return True
        else:
            logger.error(f"❌ Error recargando nginx: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Timeout recargando nginx (más de 10s)")
        return False
    except Exception as e:
        logger.error(f"❌ Error ejecutando comando de recarga de nginx: {e}", exc_info=True)
        return False


def get_current_blocked_ips():
    """Obtiene las IPs actualmente bloqueadas en el archivo de configuración"""
    config_path = Path(NGINX_BLOCKED_IPS_FILE)
    current_blocked_ips = set()
    
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('deny ') and line.endswith(';'):
                        blocked_ip = line.replace('deny ', '').replace(';', '').strip()
                        current_blocked_ips.add(blocked_ip)
        except Exception as e:
            logger.warning(f"⚠️ Error leyendo archivo de configuración actual: {e}")
    
    return current_blocked_ips


def main():
    """Función principal"""
    start_time = time.time()
    logger.info("🔄 Iniciando sincronización de IPs bloqueadas...")
    
    # Obtener IPs actualmente bloqueadas en el archivo (para comparación)
    current_blocked_ips = get_current_blocked_ips()
    
    # Obtener IPs bloqueadas desde PostgreSQL
    blocked_ips = get_blocked_ips_from_postgres()
    
    if not blocked_ips:
        logger.info("ℹ️ No hay IPs bloqueadas actualmente")
        # Aún así actualizar el archivo (para limpiar IPs expiradas)
        if current_blocked_ips:
            update_nginx_blocked_ips_file([])
            reload_nginx(force=True)  # Forzar recarga para limpiar
        return
    
    logger.info(f"📊 IPs bloqueadas encontradas: {len(blocked_ips)}")
    
    # Actualizar archivo de configuración de nginx
    config_updated = update_nginx_blocked_ips_file(blocked_ips)
    
    # Recargar nginx si hubo cambios (con rate limiting inteligente)
    if config_updated:
        # Calcular IPs nuevas y removidas
        blocked_ips_set = set(blocked_ips)
        new_ips = blocked_ips_set - current_blocked_ips
        removed_ips = current_blocked_ips - blocked_ips_set
        new_ips_count = len(new_ips)
        
        # Forzar recarga si hay muchas IPs nuevas o removidas (cambio significativo)
        force_reload = (new_ips_count > 10) or (len(removed_ips) > 10)
        
        if force_reload:
            logger.info(f"🚨 Cambio significativo detectado ({new_ips_count} nuevas, {len(removed_ips)} removidas), forzando recarga de Nginx")
        
        reload_success = reload_nginx(force=force_reload)
        
        elapsed = time.time() - start_time
        if reload_success:
            logger.info(f"✅ Sincronización completada exitosamente en {elapsed:.2f}s")
        else:
            logger.info(f"✅ Sincronización completada en {elapsed:.2f}s (configuración actualizada, recarga diferida por rate limiting)")
    else:
        elapsed = time.time() - start_time
        logger.info(f"✅ Sincronización completada en {elapsed:.2f}s (sin cambios)")


if __name__ == '__main__':
    main()

