#!/usr/bin/env python3
"""
Log Processor HTTP - Lee logs de ModSecurity y los envía a Kafka vía HTTP Proxy
"""

import json
import os
import time
import logging
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ModSecLogHandler(FileSystemEventHandler):
    """Handler para eventos de archivos de log de ModSecurity"""
    
    def __init__(self, log_file_path: str, proxy_url: str):
        self.log_file_path = Path(log_file_path)
        self.proxy_url = proxy_url.rstrip('/') + '/logs'
        self.last_position = 0
        
        # Batching para mejorar performance
        self.batch = []
        self.batch_size = int(os.getenv('LOG_BATCH_SIZE', '100'))
        self.batch_timeout = float(os.getenv('LOG_BATCH_TIMEOUT', '5.0'))  # 5 segundos
        self.last_flush = time.time()
        self.logs_processed = 0
        self.logs_sent = 0
        
        # Si el archivo existe, lee desde el final
        if self.log_file_path.exists():
            self.last_position = self.log_file_path.stat().st_size
    
    def on_modified(self, event):
        """Se ejecuta cuando el archivo se modifica"""
        if event.src_path == str(self.log_file_path):
            self.read_new_lines()
    
    def read_new_lines(self):
        """Lee las nuevas líneas del archivo de log"""
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                
                for line in new_lines:
                    line = line.strip()
                    if line:
                        self.process_log_line(line)
        except Exception as e:
            logger.error(f"Error leyendo archivo de log: {e}")
    
    def process_log_line(self, line: str):
        """Procesa una línea de log y la agrega al batch"""
        try:
            # Intenta parsear como JSON
            try:
                log_data = json.loads(line)
            except json.JSONDecodeError:
                # Si no es JSON, parsea como log de acceso estándar de nginx
                log_data = self.parse_nginx_log(line)
            
            # Normalizar campos numéricos
            if 'status' in log_data:
                try:
                    log_data['status'] = int(log_data['status'])
                except (ValueError, TypeError):
                    log_data['status'] = 200
            
            if 'size' in log_data:
                try:
                    log_data['size'] = int(log_data['size'])
                except (ValueError, TypeError):
                    log_data['size'] = 0
            
            # Agregar timestamp si no existe
            if 'timestamp' not in log_data or not log_data['timestamp']:
                log_data['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            
            # Agregar al batch
            self.batch.append(log_data)
            self.logs_processed += 1
            
            # Flush si alcanza el tamaño o timeout
            current_time = time.time()
            should_flush = (
                len(self.batch) >= self.batch_size or
                (len(self.batch) > 0 and (current_time - self.last_flush) >= self.batch_timeout)
            )
            
            if should_flush:
                self.flush_batch()
                
        except Exception as e:
            logger.error(f"Error procesando línea de log: {e}")
    
    def flush_batch(self):
        """Envía el batch al proxy HTTP"""
        if not self.batch:
            return
        
        try:
            response = requests.post(
                self.proxy_url,
                json=self.batch,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                result = response.json()
                batch_size = len(self.batch)
                self.logs_sent += batch_size
                logger.info(f"✅ Enviados {batch_size} logs al proxy (total: {self.logs_sent})")
                self.batch.clear()
                self.last_flush = time.time()
            else:
                logger.error(f"❌ Error enviando batch: HTTP {response.status_code} - {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de conexión al proxy: {e}")
        except Exception as e:
            logger.error(f"❌ Error enviando batch: {e}")
    
    def parse_nginx_log(self, line: str) -> dict:
        """Parsea una línea de log de nginx/modsecurity"""
        # Intentar parsear como JSON primero
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass
        
        # Si no es JSON, parsear como log estándar de nginx
        parts = line.split('"')
        if len(parts) >= 3:
            request_part = parts[1] if len(parts) > 1 else ""
            method_uri = request_part.split()
            method = method_uri[0] if len(method_uri) > 0 else "GET"
            uri = method_uri[1] if len(method_uri) > 1 else ""
            
            status_size = parts[2].strip().split() if len(parts) > 2 else []
            status = int(status_size[0]) if len(status_size) > 0 else 200
            size = int(status_size[1]) if len(status_size) > 1 else 0
            
            referer = parts[3] if len(parts) > 3 else ""
            user_agent = parts[5] if len(parts) > 5 else ""
            
            ip = parts[0].split()[0] if parts[0].strip() else "unknown"
            
            return {
                "ip": ip,
                "method": method,
                "uri": uri,
                "status": status,
                "size": size,
                "referer": referer,
                "user_agent": user_agent,
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
        
        # Si no se puede parsear, retornar estructura básica
        return {
            "raw_log": line,
            "status": 200,
            "size": 0,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }


def main():
    """Función principal"""
    log_path = os.getenv('MODSEC_LOG_PATH', '/logs/access.log')
    proxy_url = os.getenv('KAFKA_PROXY_URL', 'http://localhost:8080')
    
    if not proxy_url:
        logger.error("❌ KAFKA_PROXY_URL no está configurado")
        return
    
    logger.info(f"🚀 Iniciando Log Processor HTTP...")
    logger.info(f"   Log path: {log_path}")
    logger.info(f"   Proxy URL: {proxy_url}")
    
    # Verificar que el archivo existe
    log_file = Path(log_path)
    if not log_file.exists():
        logger.warning(f"⚠️  Archivo de log no existe: {log_path}")
        logger.info("   Esperando a que se cree el archivo...")
    
    # Crear handler y observer
    handler = ModSecLogHandler(log_path, proxy_url)
    observer = Observer()
    observer.schedule(handler, str(log_file.parent), recursive=False)
    observer.start()
    
    logger.info("✅ Observer iniciado, monitoreando cambios en el archivo de log...")
    
    try:
        while True:
            time.sleep(1)
            # Flush periódico si hay logs pendientes
            if handler.batch and (time.time() - handler.last_flush) >= handler.batch_timeout:
                handler.flush_batch()
    except KeyboardInterrupt:
        logger.info("🛑 Deteniendo observer...")
        observer.stop()
        # Flush final
        if handler.batch:
            handler.flush_batch()
    
    observer.join()
    logger.info(f"✅ Log Processor detenido. Total procesados: {handler.logs_processed}, enviados: {handler.logs_sent}")


if __name__ == "__main__":
    main()

