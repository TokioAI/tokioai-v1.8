#!/usr/bin/env python3
"""
Sincroniza rate limits desde PostgreSQL a Nginx y ModSecurity.
Similar a sync-blocked-ips-to-nginx.py pero para rate limiting.
"""
import os
import sys
import logging
import psycopg2
from pathlib import Path
from datetime import datetime
import subprocess
import time
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'soc_ai')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'soc_user')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')

# Archivos de configuración
NGINX_RATE_LIMIT_FILE = os.getenv('NGINX_RATE_LIMIT_FILE', 
    '/opt/tokio-ai-waf/modsecurity/rules/auto-rate-limits.conf')
MODSEC_RATE_LIMIT_FILE = os.getenv('MODSEC_RATE_LIMIT_FILE',
    '/opt/tokio-ai-waf/modsecurity/rules/auto-rate-limits-modsec.conf')

NGINX_RELOAD_COMMAND = os.getenv('NGINX_RELOAD_COMMAND', 
    'docker exec tokio-ai-modsecurity nginx -s reload')

NGINX_RELOAD_MIN_INTERVAL = 10  # Segundos entre recargas
NGINX_RELOAD_STATE_FILE = '/tmp/nginx-rate-limit-reload-state.json'


def get_rate_limited_ips_from_postgres():
    """Obtiene IPs con rate limiting activo desde PostgreSQL"""
    try:
        postgres_host = POSTGRES_HOST
        if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME"⚠️ Tabla rate_limited_ips no existe aún")
            cursor.close()
            conn.close()
            return []
        
        cursor.execute("""
            SELECT DISTINCT ip, 
                   rate_limit_level,
                   rate_limit_requests,
                   rate_limit_window,
                   applied_at
            FROM rate_limited_ips
            WHERE active = TRUE
            AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY ip
        """)
        
        results = cursor.fetchall()
        rate_limits = []
        
        for row in results:
            rate_limits.append({
                'ip': row[0],
                'level': row[1] or 'moderate',
                'requests': row[2] or 30,
                'window': row[3] or 60,
                'applied_at': row[4]
            })
        
        cursor.close()
        conn.close()
        
        logger.info(f"✅ Obtenidas {len(rate_limits)} IPs con rate limiting")
        return rate_limits
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo rate limits: {e}", exc_info=True)
        return []


def update_nginx_rate_limit_file(rate_limits: list):
    """Actualiza archivo de configuración de rate limiting para Nginx"""
    try:
        config_path = Path(NGINX_RATE_LIMIT_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Agrupar por nivel de límite para crear zonas eficientes
        limits_by_config = {}
        for rl in rate_limits:
            key = f"{rl['requests']}/{rl['window']}"
            if key not in limits_by_config:
                limits_by_config[key] = []
            limits_by_config[key].append(rl['ip'])
        
        with open(config_path, 'w') as f:
            f.write("# Rate limiting automático por IP - Generado por Tokio AI\n")
            f.write(f"# Última actualización: {datetime.now().isoformat()}\n")
            f.write("# NO EDITAR MANUALMENTE\n\n")
            
            # Crear map de rate limits
            f.write("# Map de IPs a niveles de rate limiting\n")
            f.write("map $remote_addr $rate_limit_key {\n")
            f.write("    default \"none\";\n")
            
            for rl in rate_limits:
                requests = rl['requests']
                window = rl['window']
                key = f"{requests}_{window}"
                f.write(f"    {rl['ip']} \"{key}\";\n")
            
            f.write("}\n\n")
            
            # Crear zonas de rate limiting
            f.write("# Zonas de rate limiting\n")
            for key, ips in limits_by_config.items():
                requests, window = key.split('/')
                zone_name = f"tokio_ratelimit_{requests}_{window}"
                # Convertir requests/60s a requests/min
                rate_per_min = requests if window == 60 else int(requests * 60 / window)
                f.write(f"limit_req_zone $rate_limit_key zone={zone_name}:10m rate={rate_per_min}r/m;\n")
            
            f.write("\n")
            
            # Aplicar rate limiting en server block (se incluye en nginx.conf)
            f.write("# Aplicar rate limiting en server block\n")
            f.write("# Agregar en server {}:\n")
            f.write("#   limit_req zone=tokio_ratelimit_30_60 burst=5 nodelay if $rate_limit_key != \"none\";\n")
            
        logger.info(f"✅ Archivo Nginx actualizado con {len(rate_limits)} rate limits")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error actualizando archivo Nginx: {e}", exc_info=True)
        return False


def update_modsecurity_rate_limit_file(rate_limits: list):
    """Actualiza archivo de reglas ModSecurity para rate limiting"""
    try:
        config_path = Path(MODSEC_RATE_LIMIT_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            f.write("# Rate limiting ModSecurity - Generado por Tokio AI\n")
            f.write(f"# Última actualización: {datetime.now().isoformat()}\n")
            f.write("# NO EDITAR MANUALMENTE\n\n")
            
            for rl in rate_limits:
                ip = rl['ip']
                requests = rl['requests']
                window = rl['window']
                rule_id = 990000 + abs(hash(ip)) % 9999  # ID único pero determinístico
                
                # Crear regla ModSecurity con colección para rate limiting
                f.write(f"""
# Rate limit para IP: {ip}
# Nivel: {rl['level']}
SecRule REMOTE_ADDR "@ipMatch {ip}" \\
    "id:{rule_id}, \\
    phase:1, \\
    nolog, \\
    pass, \\
    initcol:ip={ip}, \\
    setvar:ip.rate_limit_counter=+1"
""")
                
                # Regla para bloquear si excede límite
                f.write(f"""
SecRule &ip:rate_limit_counter "@gt {requests}" \\
    "id:{rule_id + 1}, \\
    phase:2, \\
    deny, \\
    status:429, \\
    msg:'Rate limit excedido para IP {ip} ({requests} req/{window}s)', \\
    tag:'rate-limit', \\
    expirevar:ip.rate_limit_counter={window}"
""")
        
        logger.info(f"✅ Archivo ModSecurity actualizado con {len(rate_limits)} rate limits")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error actualizando archivo ModSecurity: {e}", exc_info=True)
        return False


def should_reload_nginx() -> bool:
    """Verifica si se debe recargar Nginx"""
    state_file = Path(NGINX_RELOAD_STATE_FILE)
    
    if not state_file.exists():
        return True
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            last_reload = datetime.fromisoformat(state.get('last_reload', '2000-01-01T00:00:00'))
            time_since_reload = (datetime.now() - last_reload).total_seconds()
            
            return time_since_reload >= NGINX_RELOAD_MIN_INTERVAL
    except:
        return True


def reload_nginx():
    """Recarga configuración de Nginx"""
    if not should_reload_nginx():
        logger.info("⏳ Recarga diferida por rate limiting")
        return False
    
    try:
        result = subprocess.run(
            NGINX_RELOAD_COMMAND.split(),
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Guardar estado
            state = {'last_reload': datetime.now().isoformat()}
            Path(NGINX_RELOAD_STATE_FILE).write_text(json.dumps(state))
            logger.info("✅ Nginx recargado exitosamente")
            return True
        else:
            logger.error(f"❌ Error recargando Nginx: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ Error ejecutando comando: {e}")
        return False


def main():
    """Función principal"""
    logger.info("🔄 Sincronizando rate limits...")
    
    rate_limits = get_rate_limited_ips_from_postgres()
    
    if not rate_limits:
        logger.info("ℹ️ No hay rate limits activos")
        # Limpiar archivos si existen
        for file_path in [NGINX_RATE_LIMIT_FILE, MODSEC_RATE_LIMIT_FILE]:
            path = Path(file_path)
            if path.exists():
                path.write_text("# No hay rate limits activos actualmente\n")
        return
    
    # Actualizar archivos
    nginx_updated = update_nginx_rate_limit_file(rate_limits)
    modsec_updated = update_modsecurity_rate_limit_file(rate_limits)
    
    if nginx_updated or modsec_updated:
        reload_nginx()
    
    logger.info("✅ Sincronización completada")


if __name__ == '__main__':
    main()
