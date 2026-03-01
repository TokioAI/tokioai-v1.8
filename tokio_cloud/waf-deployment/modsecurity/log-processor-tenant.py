#!/usr/bin/env python3
"""
Log Processor con soporte Multi-Tenant
Lee logs de ModSecurity y los envía a Kafka con tenant_id
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from kafka import KafkaProducer
from kafka.errors import KafkaError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Intentar importar psycopg2 para consultar tenant_id
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logging.warning("psycopg2 no disponible, tenant_id será None")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TenantResolver:
    """Resuelve tenant_id basado en el dominio del log"""
    
    def __init__(self):
        self.tenant_cache: Dict[str, int] = {}
        self.cache_ttl = 3600  # 1 hora
        self.last_cache_update: Dict[str, float] = {}
        self.tenant_id_override = os.getenv('TENANT_ID', None)  # Override desde env
        
        # Configuración PostgreSQL
        self.postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
        self.postgres_port = os.getenv('POSTGRES_PORT', '5432')
        self.postgres_db = os.getenv('POSTGRES_DB', 'tokio')
        self.postgres_user = os.getenv('POSTGRES_USER', 'tokio')
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", "")
        
        # Dominio por defecto (si se especifica en env)
        self.default_domain = os.getenv('DEFAULT_DOMAIN', None)
        self.default_tenant_id = None
        
        # Cargar tenant_id por defecto si existe
        if self.default_domain and POSTGRES_AVAILABLE:
            self.default_tenant_id = self._get_tenant_id_from_db(self.default_domain)
    
    def _get_db_connection(self):
        """Crea conexión a PostgreSQL"""
        if not POSTGRES_AVAILABLE:
            return None
        try:
            return psycopg2.connect(
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
                user=self.postgres_user,
                password=self.postgres_password
            )
        except Exception as e:
            logger.warning(f"No se pudo conectar a PostgreSQL: {e}")
            return None
    
    def _get_tenant_id_from_db(self, domain: str) -> Optional[int]:
        """Obtiene tenant_id desde PostgreSQL"""
        if not POSTGRES_AVAILABLE or not domain:
            return None
        
        # Verificar cache primero
        cache_key = domain.lower()
        if cache_key in self.tenant_cache:
            # Verificar si el cache está vencido
            last_update = self.last_cache_update.get(cache_key, 0)
            if time.time() - last_update < self.cache_ttl:
                return self.tenant_cache[cache_key]
        
        conn = self._get_db_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id FROM tenants WHERE domain = %s AND status = 'active'",
                    (domain.lower(),)
                )
                result = cur.fetchone()
                if result:
                    tenant_id = result['id']
                    # Actualizar cache
                    self.tenant_cache[cache_key] = tenant_id
                    self.last_cache_update[cache_key] = time.time()
                    logger.debug(f"Tenant {domain} -> ID {tenant_id}")
                    return tenant_id
        except Exception as e:
            logger.warning(f"Error consultando tenant_id para {domain}: {e}")
        finally:
            conn.close()
        
        return None
    
    def get_tenant_id(self, log_data: Dict[str, Any]) -> Optional[int]:
        """Obtiene tenant_id basado en el log"""
        # Si hay override, usarlo
        if self.tenant_id_override:
            return int(self.tenant_id_override)
        
        # Intentar obtener dominio del log
        domain = None
        
        # Buscar en diferentes campos del log
        if 'host' in log_data:
            domain = log_data['host']
        elif 'server_name' in log_data:
            domain = log_data['server_name']
        elif 'http_host' in log_data:
            domain = log_data['http_host']
        elif 'Host' in log_data:
            domain = log_data['Host']
        
        # Limpiar dominio (remover puerto si existe)
        if domain:
            domain = domain.split(':')[0].lower()
        
        # Si no hay dominio, usar el por defecto
        if not domain and self.default_domain:
            domain = self.default_domain.lower()
            if self.default_tenant_id:
                return self.default_tenant_id
        
        # Buscar tenant_id
        if domain:
            return self._get_tenant_id_from_db(domain)
        
        return None


class ModSecLogHandler(FileSystemEventHandler):
    """Handler para eventos de archivos de log de ModSecurity con soporte multi-tenant"""
    
    def __init__(self, log_file_path: str, kafka_producer: KafkaProducer, topic: str, tenant_resolver: TenantResolver):
        self.log_file_path = Path(log_file_path)
        self.producer = kafka_producer
        self.topic = topic
        self.tenant_resolver = tenant_resolver
        self.last_position = 0
        
        # Batching para mejorar performance
        self.batch = []
        self.batch_size = int(os.getenv('LOG_BATCH_SIZE', '1000'))
        self.batch_timeout = float(os.getenv('LOG_BATCH_TIMEOUT', '0.1'))  # 100ms
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
        """Procesa una línea de log y la agrega al batch para envío a Kafka"""
        try:
            # Intenta parsear como JSON (si es el formato modsec_log que definimos)
            try:
                log_data = json.loads(line)
            except json.JSONDecodeError:
                # Si no es JSON, parsea como log de acceso estándar de nginx
                log_data = self.parse_nginx_log(line)
            
            # Obtener tenant_id
            tenant_id = self.tenant_resolver.get_tenant_id(log_data)
            if tenant_id:
                log_data['tenant_id'] = tenant_id
            
            # Asegurar que los campos numéricos son realmente enteros
            if 'status' in log_data:
                try:
                    log_data['status'] = int(log_data['status'])
                except (ValueError, TypeError):
                    log_data['status'] = 200  # Default
            
            if 'size' in log_data:
                try:
                    log_data['size'] = int(log_data['size'])
                except (ValueError, TypeError):
                    log_data['size'] = 0  # Default
            
            # Agregar timestamp si no existe
            if 'timestamp' not in log_data and 'date' in log_data:
                try:
                    from datetime import datetime
                    # Intentar parsear fecha del log
                    log_data['timestamp'] = log_data['date']
                except:
                    log_data['timestamp'] = datetime.utcnow().isoformat()
            elif 'timestamp' not in log_data:
                from datetime import datetime
                log_data['timestamp'] = datetime.utcnow().isoformat()
            
            # Agregar al batch
            self.batch.append(log_data)
            self.logs_processed += 1
            
            # Enviar batch si alcanza el tamaño o timeout
            current_time = time.time()
            should_flush = (
                len(self.batch) >= self.batch_size or
                (len(self.batch) > 0 and (current_time - self.last_flush) >= self.batch_timeout)
            )
            
            if should_flush:
                self._flush_batch()
            
            logger.debug(f"Log agregado al batch: {log_data.get('request_uri', log_data.get('uri', 'N/A'))} (tenant_id: {tenant_id})")
        except Exception as e:
            logger.error(f"Error procesando línea de log: {e}")
    
    def _flush_batch(self, retry_count: int = 0, max_retries: int = 3):
        """Envía el batch completo a Kafka con retry logic"""
        if not self.batch:
            return
        
        batch_size = len(self.batch)
        base_delay = 1  # 1 segundo base
        
        try:
            # Enviar todos los mensajes del batch
            for log_data in self.batch:
                try:
                    self.producer.send(self.topic, value=log_data)
                except Exception as e:
                    logger.warning(f"Error enviando mensaje individual a Kafka: {e}")
            
            # Flush general
            self.producer.flush(timeout=10)
            
            self.logs_sent += batch_size
            logger.info(f"Batch enviado: {batch_size} logs (Total procesados: {self.logs_processed}, Total enviados: {self.logs_sent})")
            
            # Limpiar batch
            self.batch = []
            self.last_flush = time.time()
            
        except KafkaError as e:
            logger.error(f"Error de Kafka enviando batch: {e}")
            if retry_count < max_retries:
                delay = base_delay * (2 ** retry_count)
                logger.warning(f"Reintentando batch ({retry_count + 1}/{max_retries}) después de {delay}s...")
                time.sleep(delay)
                return self._flush_batch(retry_count + 1, max_retries)
            else:
                logger.error(f"Falló después de {max_retries} intentos. Descartando batch de {batch_size} logs.")
                self.batch = []
        except Exception as e:
            logger.error(f"Error inesperado enviando batch a Kafka: {e}")
            self.batch = []
    
    def parse_nginx_log(self, line: str) -> dict:
        """Parsea un log de acceso de nginx en formato estándar"""
        import re
        
        # Patrón para logs de nginx: IP - - [fecha] "método URI protocolo" status tamaño "referer" "user-agent"
        pattern = r'(\S+) - - \[([^\]]+)\] "(\S+) (\S+) ([^"]+)" (\d+) (\d+) "([^"]*)" "([^"]*)"'
        match = re.match(pattern, line)
        
        if match:
            ip, date, method, uri, protocol, status, size, referer, user_agent = match.groups()
            
            # Extraer query string de la URI
            uri_parts = uri.split('?', 1)
            path = uri_parts[0]
            query_string = uri_parts[1] if len(uri_parts) > 1 else ''
            
            try:
                status_int = int(status)
            except (ValueError, TypeError):
                status_int = 200
            
            try:
                size_int = int(size)
            except (ValueError, TypeError):
                size_int = 0

            # Extraer host si viene en el formato extendido
            host = ''
            host_match = re.search(r'host[=:]"?([^"\s]+)"?', line, re.IGNORECASE)
            if host_match:
                host = host_match.group(1)
            
            return {
                'ip': ip,
                'date': date,
                'method': method,
                'uri': uri,
                'path': path,
                'query_string': query_string,
                'status': status_int,
                'size': size_int,
                'referer': referer,
                'user_agent': user_agent,
                'host': host,
                'format': 'nginx_access'
            }
        else:
            # Si no coincide, devolver la línea raw
            return {'raw_line': line, 'format': 'unknown'}


def main():
    """Función principal del procesador de logs"""
    kafka_bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    kafka_topic = os.getenv('KAFKA_TOPIC_WAF_LOGS', 'waf-logs')
    log_file_path = os.getenv('MODSEC_LOG_PATH', '/logs/access.log')
    
    # Dominio por defecto para este log processor
    default_domain = os.getenv('DEFAULT_DOMAIN', 'your-domain.com')
    
    logger.info(f"Iniciando procesador de logs ModSecurity (Multi-Tenant)...")
    logger.info(f"Kafka: {kafka_bootstrap}")
    logger.info(f"Topic: {kafka_topic}")
    logger.info(f"Log file: {log_file_path}")
    logger.info(f"Default domain: {default_domain}")
    
    # Inicializar resolver de tenants
    tenant_resolver = TenantResolver()
    
    # Inicializa Kafka Producer
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap.split(','),
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        batch_size=16384,
        linger_ms=50,
        compression_type='gzip',
        acks=0,
        retries=2,
        max_in_flight_requests_per_connection=5,
        request_timeout_ms=10000,
        delivery_timeout_ms=30000,
    )
    
    # Configura watchdog para monitorear el archivo de log
    event_handler = ModSecLogHandler(log_file_path, producer, kafka_topic, tenant_resolver)
    observer = Observer()
    observer.schedule(event_handler, str(Path(log_file_path).parent), recursive=False)
    observer.start()
    
    logger.info("Procesador de logs iniciado. Monitoreando archivo...")
    
    try:
        while True:
            time.sleep(1)
            # Flush periódico del batch pendiente
            if event_handler.batch:
                current_time = time.time()
                if (current_time - event_handler.last_flush) >= event_handler.batch_timeout * 2:
                    event_handler._flush_batch()
    except KeyboardInterrupt:
        logger.info("Deteniendo procesador de logs...")
        # Flush final del batch pendiente
        if event_handler.batch:
            logger.info(f"Enviando batch final de {len(event_handler.batch)} logs...")
            event_handler._flush_batch()
        observer.stop()
    
    observer.join()
    producer.close()
    logger.info(f"Procesador de logs detenido. Total procesados: {event_handler.logs_processed}, Total enviados: {event_handler.logs_sent}")


if __name__ == '__main__':
    main()

