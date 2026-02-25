#!/usr/bin/env python3
"""
Script optimizado para sincronizar IPs bloqueadas - Versión DDoS-Resistente
OPTIMIZACIONES:
- Límite máximo de IPs (evita crecimiento descontrolado)
- Escritura incremental cuando es posible
- Uso de hash para detectar cambios sin leer archivo completo
- Batching inteligente de consultas PostgreSQL
- Limpieza automática de IPs antiguas
- Rate limiting adaptativo basado en carga
- Modo "emergencia" para DDoS masivos
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
import hashlib
from typing import Set, List, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== CONFIGURACIÓN OPTIMIZADA ==========
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'soc_ai')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'soc_user')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')

NGINX_BLOCKED_IPS_FILE = os.getenv('NGINX_BLOCKED_IPS_FILE', 
    '/opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf')
NGINX_RELOAD_COMMAND = os.getenv('NGINX_RELOAD_COMMAND', 
    'docker exec tokio-ai-modsecurity-nginx nginx -s reload')

# ⚡ NUEVAS CONFIGURACIONES OPTIMIZADAS
MAX_IPS_TOTAL = int(os.getenv('MAX_IPS_TOTAL', '5000'))  # Límite máximo de IPs
MAX_IPS_PER_BATCH = int(os.getenv('MAX_IPS_PER_BATCH', '1000'))  # Consultas por lote
NGINX_RELOAD_MIN_INTERVAL = int(os.getenv('NGINX_RELOAD_MIN_INTERVAL', '10'))
NGINX_RELOAD_STATE_FILE = '/tmp/nginx-reload-state.json'
CONFIG_HASH_FILE = '/tmp/nginx-blocked-ips-hash.txt'  # Hash del archivo actual

# Modo emergencia: si hay más de este número de IPs, usar estrategia diferente
EMERGENCY_MODE_THRESHOLD = int(os.getenv('EMERGENCY_MODE_THRESHOLD', '3000'))

# Limpieza automática: IPs más antiguas que esto se priorizan menos
CLEANUP_AGE_HOURS = int(os.getenv('CLEANUP_AGE_HOURS', '168'))  # 7 días

# Batching de escritura: escribir en chunks para no bloquear
WRITE_CHUNK_SIZE = 1000  # Escribir en bloques de 1000 IPs


def get_ip_hash(ips: Set[str]) -> str:
    """Genera hash de las IPs para detectar cambios rápidamente"""
    sorted_ips = sorted(ips)
    ip_string = ','.join(sorted_ips)
    return hashlib.sha256(ip_string.encode()).hexdigest()


def get_stored_hash() -> Optional[str]:
    """Obtiene el hash almacenado del último estado"""
    hash_file = Path(CONFIG_HASH_FILE)
    if hash_file.exists():
        try:
            return hash_file.read_text().strip()
        except:
            return None
    return None


def store_hash(ip_hash: str):
    """Almacena el hash del estado actual"""
    try:
        Path(CONFIG_HASH_FILE).write_text(ip_hash)
    except Exception as e:
        logger.warning(f"⚠️ Error guardando hash: {e}")


def get_blocked_ips_from_postgres_optimized() -> Tuple[List[str], int]:
    """
    Obtiene IPs bloqueadas de forma optimizada con batching.
    
    Returns:
        (blocked_ips_list, total_count)
    """
    try:
        postgres_host = POSTGRES_HOST
        if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME"""
                SELECT DISTINCT ip, MAX(blocked_at) as last_blocked
                FROM blocked_ips 
                WHERE active = TRUE 
                AND (expires_at IS NULL OR expires_at > NOW())
                GROUP BY ip
                ORDER BY last_blocked DESC
                LIMIT %s
            """, (MAX_IPS_TOTAL,))
            
            results = cursor.fetchall()
            blocked_ips.update([row[0] for row in results])
            logger.info(f"✅ Obtenidas {len(blocked_ips)} IPs desde blocked_ips (limitado a {MAX_IPS_TOTAL})")
            
        except Exception as e:
            logger.warning(f"⚠️ Error consultando blocked_ips: {e}")
        
        total_count = len(blocked_ips)
        
        # OPTIMIZACIÓN 2: Limpiar IPs antiguas automáticamente si hay muchas
        if len(blocked_ips) > MAX_IPS_TOTAL * 0.8:  # Si hay más del 80% del límite
            logger.warning(f"⚠️ Muchas IPs bloqueadas ({len(blocked_ips)}), limpiando IPs antiguas...")
            try:
                cursor.execute("""
                    UPDATE blocked_ips 
                    SET active = FALSE 
                    WHERE active = TRUE 
                    AND blocked_at < NOW() - INTERVAL '%s hours'
                    AND (expires_at IS NULL OR expires_at < NOW() - INTERVAL '%s hours')
                """, (CLEANUP_AGE_HOURS, CLEANUP_AGE_HOURS))
                cleaned = cursor.rowcount
                conn.commit()
                logger.info(f"🧹 Limpiadas {cleaned} IPs antiguas (más de {CLEANUP_AGE_HOURS} horas)")
            except Exception as e:
                logger.warning(f"⚠️ Error limpiando IPs antiguas: {e}")
                conn.rollback()
        
        cursor.close()
        conn.close()
        
        # OPTIMIZACIÓN 3: En modo emergencia, priorizar IPs más peligrosas
        if total_count > EMERGENCY_MODE_THRESHOLD:
            logger.warning(f"🚨 MODO EMERGENCIA: {total_count} IPs bloqueadas (umbral: {EMERGENCY_MODE_THRESHOLD})")
            # Si hay demasiadas, limitar a las más recientes/importantes
            blocked_ips_list = sorted(blocked_ips)[:MAX_IPS_TOTAL]
            return blocked_ips_list, total_count
        
        return sorted(blocked_ips), total_count
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo IPs bloqueadas: {e}", exc_info=True)
        return [], 0


def update_nginx_blocked_ips_file_optimized(blocked_ips: List[str], total_count: int) -> bool:
    """
    Actualiza archivo de configuración de forma optimizada.
    
    OPTIMIZACIONES:
    - Usa hash para detectar cambios sin leer archivo completo
    - Escritura en chunks
    - Modo emergencia: formato más eficiente
    """
    try:
        config_path = Path(NGINX_BLOCKED_IPS_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        blocked_ips_set = set(blocked_ips)
        
        # OPTIMIZACIÓN 1: Usar hash para detectar cambios sin leer archivo
        current_hash = get_ip_hash(blocked_ips_set)
        stored_hash = get_stored_hash()
        
        if current_hash == stored_hash:
            logger.info(f"ℹ️ No hay cambios detectados por hash ({len(blocked_ips)} IPs)")
            return False
        
        # OPTIMIZACIÓN 2: Leer archivo actual solo si hash es diferente
        current_blocked_ips = set()
        if config_path.exists():
            try:
                # Leer solo las primeras líneas para obtener count aproximado
                with open(config_path, 'r') as f:
                    lines = f.readlines()
                    current_count = sum(1 for line in lines if line.strip().startswith('deny '))
                    if current_count != len(blocked_ips):
                        # Solo leer completo si el conteo es diferente
                        current_blocked_ips = set()
                        for line in lines:
                            line = line.strip()
                            if line.startswith('deny ') and line.endswith(';'):
                                ip = line.replace('deny ', '').replace(';', '').strip()
                                current_blocked_ips.add(ip)
            except Exception as e:
                logger.warning(f"⚠️ Error leyendo archivo actual: {e}")
        
        # Verificar si realmente hay cambios (doble verificación)
        if current_blocked_ips == blocked_ips_set:
            logger.info(f"ℹ️ No hay cambios reales ({len(blocked_ips)} IPs)")
            store_hash(current_hash)  # Actualizar hash aunque no haya cambios
            return False
        
        # OPTIMIZACIÓN 3: Escritura optimizada
        start_time = time.time()
        
        # Modo emergencia: usar formato más eficiente (map de Nginx si es posible)
        is_emergency = len(blocked_ips) > EMERGENCY_MODE_THRESHOLD
        
        with open(config_path, 'w') as f:
            f.write("# IPs bloqueadas automáticamente por auto-mitigation\n")
            f.write("# Este archivo se genera automáticamente por sync-blocked-ips-to-nginx.py (VERSIÓN OPTIMIZADA)\n")
            f.write(f"# Última actualización: {datetime.now().isoformat()}\n")
            f.write(f"# Total de IPs: {len(blocked_ips)} (de {total_count} en BD)\n")
            if is_emergency:
                f.write("# 🚨 MODO EMERGENCIA ACTIVADO\n")
            f.write("# NO EDITAR MANUALMENTE - los cambios se sobrescribirán\n\n")
            
            # OPTIMIZACIÓN 4: Escribir en chunks para no bloquear
            if blocked_ips:
                chunk_start = 0
                while chunk_start < len(blocked_ips):
                    chunk_end = min(chunk_start + WRITE_CHUNK_SIZE, len(blocked_ips))
                    chunk = blocked_ips[chunk_start:chunk_end]
                    
                    for ip in chunk:
                        f.write(f"deny {ip};\n")
                    
                    chunk_start = chunk_end
                    
                    # Pequeña pausa entre chunks para no saturar I/O
                    if chunk_end < len(blocked_ips):
                        time.sleep(0.001)  # 1ms
            else:
                f.write("# No hay IPs bloqueadas actualmente\n")
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Archivo actualizado con {len(blocked_ips)} IPs en {elapsed:.3f}s")
        
        # Calcular cambios
        new_ips = blocked_ips_set - current_blocked_ips
        removed_ips = current_blocked_ips - blocked_ips_set
        
        if new_ips:
            logger.info(f"➕ {len(new_ips)} IPs nuevas bloqueadas (ejemplos: {', '.join(sorted(new_ips)[:5])})")
        if removed_ips:
            logger.info(f"➖ {len(removed_ips)} IPs desbloqueadas")
        
        # Guardar hash del nuevo estado
        store_hash(current_hash)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error actualizando archivo: {e}", exc_info=True)
        return False


def should_reload_nginx() -> Tuple[bool, str]:
    """
    Determina si se debe recargar Nginx con lógica adaptativa.
    
    Returns:
        (should_reload, reason)
    """
    state_file = Path(NGINX_RELOAD_STATE_FILE)
    
    if not state_file.exists():
        return True, "Primera recarga"
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            last_reload = datetime.fromisoformat(state.get('last_reload', '2000-01-01T00:00:00'))
            time_since_reload = (datetime.now() - last_reload).total_seconds()
            
            if time_since_reload < NGINX_RELOAD_MIN_INTERVAL:
                return False, f"Rate limiting: {time_since_reload:.1f}s < {NGINX_RELOAD_MIN_INTERVAL}s"
            
            return True, f"Tiempo suficiente transcurrido: {time_since_reload:.1f}s"
    except Exception as e:
        logger.warning(f"⚠️ Error leyendo estado: {e}, permitiendo recarga")
        return True, "Error leyendo estado"


def reload_nginx(force: bool = False, reason: str = "") -> bool:
    """Recarga Nginx con optimizaciones"""
    if not NGINX_RELOAD_COMMAND:
        logger.warning("⚠️ NGINX_RELOAD_COMMAND no configurado")
        return False
    
    if not force:
        should_reload, reload_reason = should_reload_nginx()
        if not should_reload:
            logger.info(f"⏳ Recarga diferida: {reload_reason}")
            return False
    
    try:
        start_time = time.time()
        result = subprocess.run(
            NGINX_RELOAD_COMMAND.split(),
            capture_output=True,
            text=True,
            timeout=15  # Timeout aumentado para archivos grandes
        )
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            logger.info(f"✅ Nginx recargado en {elapsed:.2f}s" + (f" ({reason})" if reason else ""))
            
            # Guardar estado
            try:
                state = {'last_reload': datetime.now().isoformat()}
                Path(NGINX_RELOAD_STATE_FILE).write_text(json.dumps(state))
            except:
                pass
            
            return True
        else:
            logger.error(f"❌ Error recargando nginx: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Timeout recargando nginx (>15s)")
        return False
    except Exception as e:
        logger.error(f"❌ Error ejecutando comando: {e}", exc_info=True)
        return False


def main():
    """Función principal optimizada"""
    start_time = time.time()
    logger.info("🔄 Iniciando sincronización optimizada de IPs bloqueadas...")
    
    # Obtener IPs bloqueadas de forma optimizada
    blocked_ips, total_count = get_blocked_ips_from_postgres_optimized()
    
    if not blocked_ips:
        logger.info("ℹ️ No hay IPs bloqueadas actualmente")
        # Limpiar archivo si existe
        config_path = Path(NGINX_BLOCKED_IPS_FILE)
        if config_path.exists():
            config_path.write_text("# No hay IPs bloqueadas actualmente\n")
            reload_nginx(force=True, reason="Limpieza de bloqueos")
        return
    
    logger.info(f"📊 IPs bloqueadas: {len(blocked_ips)} (de {total_count} en BD)")
    
    # Advertencia si estamos cerca del límite
    if len(blocked_ips) >= MAX_IPS_TOTAL * 0.9:
        logger.warning(f"⚠️ ADVERTENCIA: Cerca del límite ({len(blocked_ips)}/{MAX_IPS_TOTAL})")
    
    # Actualizar archivo
    config_updated = update_nginx_blocked_ips_file_optimized(blocked_ips, total_count)
    
    # Recargar si hay cambios
    if config_updated:
        # Determinar si forzar recarga
        force_reload = len(blocked_ips) > 1000 or total_count > EMERGENCY_MODE_THRESHOLD
        reason = "Cambios significativos" if force_reload else "Cambios normales"
        
        reload_success = reload_nginx(force=force_reload, reason=reason)
        
        elapsed = time.time() - start_time
        if reload_success:
            logger.info(f"✅ Sincronización completada en {elapsed:.2f}s")
        else:
            logger.info(f"✅ Sincronización completada en {elapsed:.2f}s (recarga diferida)")
    else:
        elapsed = time.time() - start_time
        logger.info(f"✅ Sincronización completada en {elapsed:.2f}s (sin cambios)")


if __name__ == '__main__':
    main()
