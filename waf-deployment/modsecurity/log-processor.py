#!/usr/bin/env python3
"""
Log Processor - Lee logs de ModSecurity y los envía a Kafka
Versión que usa Kafka para compatibilidad con realtime-processor
"""

import json
import os
import time
import logging
import datetime as dt
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("kafka-python no está instalado. Instalar con: pip install kafka-python")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ModSecLogHandler(FileSystemEventHandler):
    """Handler para eventos de archivos de log de ModSecurity"""
    
    def __init__(self, log_file_path: str, error_log_path: str, kafka_producer: KafkaProducer, kafka_topic: str):
        self.log_file_path = Path(log_file_path)
        self.error_log_path = Path(error_log_path)
        self.kafka_producer = kafka_producer
        self.kafka_topic = kafka_topic
        self.last_position = 0
        self.last_error_position = 0
        
        # Batching para mejorar performance
        self.batch = []
        self.batch_size = int(os.getenv('LOG_BATCH_SIZE', '10'))  # REDUCIDO: Enviar más frecuentemente para logs en tiempo real
        self.batch_timeout = float(os.getenv('LOG_BATCH_TIMEOUT', '0.5'))  # AUMENTADO: 500ms para balance entre throughput y latencia
        self.last_flush = time.time()
        self.logs_processed = 0
        self.logs_sent = 0
        
        # Si el archivo existe, lee desde el final
        if self.log_file_path.exists():
            self.last_position = self.log_file_path.stat().st_size
        if self.error_log_path.exists():
            self.last_error_position = self.error_log_path.stat().st_size
    
    def on_modified(self, event):
        """Se ejecuta cuando el archivo se modifica"""
        if event.src_path == str(self.log_file_path):
            self.read_new_lines()
        elif event.src_path == str(self.error_log_path):
            self.read_new_error_lines()
    
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
    
    def read_new_error_lines(self):
        """Lee las nuevas líneas del error.log y parsea bloqueos de ModSecurity"""
        try:
            with open(self.error_log_path, 'r', encoding='utf-8') as f:
                f.seek(self.last_error_position)
                new_lines = f.readlines()
                self.last_error_position = f.tell()
                
                for line in new_lines:
                    line = line.strip()
                    if line and 'ModSecurity: Access denied with code 403' in line:
                        self.process_modsec_error_line(line)
        except Exception as e:
            logger.debug(f"Error leyendo error.log: {e}")
    
    def process_modsec_error_line(self, line: str):
        """Parsea una línea de error.log de ModSecurity y crea una entrada de log equivalente"""
        try:
            import re
            # Extraer IP del cliente
            ip_match = re.search(r'client: (\d+\.\d+\.\d+\.\d+)', line)
            client_ip = ip_match.group(1) if ip_match else 'unknown'
            
            # Extraer request
            request_match = re.search(r'request: "([^"]+)"', line)
            request_str = request_match.group(1) if request_match else ''
            
            # Extraer URI
            uri_match = re.search(r'uri: "([^"]+)"', line)
            uri = uri_match.group(1) if uri_match else ''
            if not uri:
                # Intentar extraer URI del request
                uri_match = re.search(r'request: "\w+ ([^ ]+)', line)
                uri = uri_match.group(1) if uri_match else '/'
            
            # Extraer host
            host_match = re.search(r'host: "([^"]+)"', line)
            host = host_match.group(1) if host_match else ''
            
            if request_str:
                parts = request_str.split(' ', 2)
                method = parts[0] if len(parts) > 0 else 'GET'
                # URI ya extraída arriba
            else:
                method = 'GET'
            
            # Crear una entrada de log equivalente en formato nginx combined
            # Formato: IP - - [timestamp] "METHOD URI HTTP/VER" 403 SIZE "REFERER" "USER-AGENT"
            timestamp = dt.datetime.utcnow().strftime('%d/%b/%Y:%H:%M:%S +0000')
            log_line = f'{client_ip} - - [{timestamp}] "{method} {uri} HTTP/1.1" 403 146 "-" "-"'
            
            # Procesar como si fuera un log normal
            self.process_log_line(log_line)
            logger.info(f"📝 Log 403 parseado de ModSecurity: IP={client_ip}, URI={uri}")
        except Exception as e:
            logger.error(f"Error parseando línea de ModSecurity: {e}")
            logger.debug(f"Línea problemática: {line[:200]}")
    
    def process_log_line(self, line: str):
        """Procesa una línea de log y la agrega al batch para envío a Pub/Sub"""
        try:
            # Intenta parsear como JSON (si es el formato modsec_log que definimos)
            try:
                log_data = json.loads(line)
                # Si es JSON, normalizar campos
                if 'status' in log_data and isinstance(log_data['status'], str):
                    try:
                        log_data['status'] = int(log_data['status'])
                    except:
                        log_data['status'] = 200
            except json.JSONDecodeError:
                # Si no es JSON, parsea como log de acceso estándar de nginx
                log_data = self.parse_nginx_log(line)
                # Si el parsing falló (formato unknown), intentar parsear como formato estándar combinado
                if log_data.get('format') == 'unknown':
                    # Intentar parsear formato estándar de nginx combinado
                    log_data = self._parse_nginx_combined(line)
            
            # Asegurar que los campos numéricos son realmente enteros (antes de agregar al batch)
            if 'status' in log_data:
                try:
                    log_data['status'] = int(log_data['status'])
                except (ValueError, TypeError):
                    log_data['status'] = 200  # Default
            
            # Marcar blocked=True si status es 403 (bloqueado por WAF)
            status = log_data.get('status', 200)
            log_data['blocked'] = (status == 403)
            
            if 'size' in log_data:
                try:
                    log_data['size'] = int(log_data['size'])
                except (ValueError, TypeError):
                    log_data['size'] = 0  # Default
            
            # Asegurar que todos los valores son serializables a JSON
            # Convertir cualquier otro campo numérico que pueda ser string
            for key, value in log_data.items():
                if isinstance(value, str) and value.isdigit():
                    # Si es un string que parece número, convertirlo
                    try:
                        log_data[key] = int(value)
                    except (ValueError, TypeError):
                        pass  # Mantener como string si no se puede convertir
            
            # Agregar al batch - ENVIAR TODOS los logs (200, 403, 404, etc.)
            status = log_data.get('status', 200)
            # IMPORTANTE: Log todos los status codes para debug
            if status in (200, 403):
                logger.info(f"📝 Log procesado: status={status}, uri={log_data.get('uri', 'N/A')}, blocked={log_data.get('blocked', False)}")
            
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
            
            logger.debug(f"Log agregado al batch: status={status}, uri={log_data.get('request_uri', log_data.get('uri', 'N/A'))}")
        except Exception as e:
            logger.error(f"Error procesando línea de log: {e}")
    
    def _flush_batch(self, retry_count: int = 0, max_retries: int = 3):
        """Envía el batch completo a Kafka con retry logic y exponential backoff"""
        if not self.batch:
            return
        
        batch_size = len(self.batch)
        base_delay = 1  # 1 segundo base
        
        try:
            # Enviar todos los mensajes del batch a Kafka
            kafka_sent = 0
            
            for log_data in self.batch:
                try:
                    # Asegurar timestamp
                    if 'timestamp' not in log_data and 'date' in log_data:
                        # Convertir date de nginx a ISO format
                        try:
                            nginx_date = log_data['date']
                            # Formato nginx: 22/Jan/2026:18:00:00 +0000
                            parsed_dt = dt.datetime.strptime(nginx_date.split()[0], '%d/%b/%Y:%H:%M:%S')
                            log_data['timestamp'] = parsed_dt.isoformat() + 'Z'
                        except:
                            log_data['timestamp'] = dt.datetime.utcnow().isoformat() + 'Z'
                    elif 'timestamp' not in log_data:
                        log_data['timestamp'] = dt.datetime.utcnow().isoformat() + 'Z'
                    
                    data = json.dumps(log_data).encode('utf-8')
                    # Enviar a Kafka
                    future = self.kafka_producer.send(
                        self.kafka_topic,
                        value=data,
                        key=log_data.get('ip', 'unknown').encode('utf-8')
                    )
                    # Esperar confirmación (con timeout)
                    future.get(timeout=5.0)  # Timeout de 5 segundos
                    kafka_sent += 1
                except Exception as e:
                    logger.warning(f"Error enviando log a Kafka: {e}")
            
            self.logs_sent += kafka_sent
            
            # Log detallado del batch enviado para debug
            status_counts = {}
            for log in self.batch:
                status = log.get('status', 200)
                status_counts[status] = status_counts.get(status, 0) + 1
            
            if kafka_sent > 0:
                logger.info(f"✅ Batch enviado a Kafka: {kafka_sent}/{batch_size} logs (Total procesados: {self.logs_processed}, Total enviados: {self.logs_sent}) | Status: {status_counts}")
            
            # Limpiar batch
            self.batch = []
            self.last_flush = time.time()
            
        except Exception as e:
            logger.error(f"Error enviando batch a Kafka: {e}")
            if retry_count < max_retries:
                delay = base_delay * (2 ** retry_count)  # Exponential backoff
                logger.warning(f"Reintentando batch ({retry_count + 1}/{max_retries}) después de {delay}s...")
                time.sleep(delay)
                return self._flush_batch(retry_count + 1, max_retries)
            else:
                logger.error(f"Falló después de {max_retries} intentos. Descartando batch de {batch_size} logs.")
                self.batch = []  # Descartar batch para evitar acumulación
    
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
                status_int = 200  # Default si no se puede parsear
            
            try:
                size_int = int(size)
            except (ValueError, TypeError):
                size_int = 0  # Default si no se puede parsear
            
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
                'blocked': (status_int == 403),  # Marcar como bloqueado si status es 403
                'format': 'nginx_access'
            }
        else:
            # Si no coincide, intentar formato combinado
            return self._parse_nginx_combined(line)
    
    def _parse_nginx_combined(self, line: str) -> dict:
        """Parsea formato combinado de nginx: IP - - [fecha] "método URI protocolo" status tamaño "referer" "user-agent" """
        import re
        # Formato combinado estándar
        pattern = r'(\S+) - - \[([^\]]+)\] "(\S+) (\S+) ([^"]+)" (\d+) (\d+) "([^"]*)" "([^"]*)"'
        match = re.match(pattern, line)
        
        if match:
            ip, date, method, uri, protocol, status, size, referer, user_agent = match.groups()
            uri_parts = uri.split('?', 1)
            path = uri_parts[0]
            query_string = uri_parts[1] if len(uri_parts) > 1 else ''
            
            try:
                status_int = int(status)
            except:
                status_int = 200
            
            try:
                size_int = int(size)
            except:
                size_int = 0
            
            # Extraer host del log si está disponible (puede estar en formato extendido o en headers)
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
                'blocked': (status_int == 403),
                'format': 'nginx_combined'
            }
        else:
            # Si tampoco coincide, devolver la línea raw pero con status por defecto
            logger.warning(f"No se pudo parsear línea de log: {line[:100]}...")
            return {
                'raw_line': line,
                'format': 'unknown',
                'status': 200,  # Default
                'blocked': False,
                'ip': 'unknown',
                'uri': '',
                'method': 'GET'
            }


def main():
    """Función principal del procesador de logs - Usa Kafka"""
    kafka_bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9093')
    kafka_topic = os.getenv('KAFKA_TOPIC_WAF_LOGS', 'waf-logs')
    log_file_path = os.getenv('MODSEC_LOG_PATH', '/var/log/nginx/access.log')
    error_log_path = os.getenv('MODSEC_ERROR_LOG_PATH', '/var/log/nginx/error.log')
    
    if not KAFKA_AVAILABLE:
        logger.error("❌ kafka-python no está instalado")
        logger.error("   Instalar con: pip install kafka-python")
        return
    
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🚀 Iniciando procesador de logs ModSecurity (Kafka)")
    logger.info(f"   Kafka Bootstrap Servers: {kafka_bootstrap_servers}")
    logger.info(f"   Kafka Topic: {kafka_topic}")
    logger.info(f"   Log file: {log_file_path}")
    logger.info(f"   Error log file: {error_log_path}")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Inicializar Kafka Producer
    try:
        kafka_producer = KafkaProducer(
            bootstrap_servers=kafka_bootstrap_servers.split(','),
            value_serializer=lambda v: v,  # Ya viene como bytes
            key_serializer=lambda k: k if k else None,  # Ya viene como bytes
            acks='all',  # Esperar confirmación de todos los replicas
            retries=3,
            max_in_flight_requests_per_connection=1,
            request_timeout_ms=30000,
            delivery_timeout_ms=60000
        )
        logger.info(f"✅ Kafka Producer inicializado: {kafka_bootstrap_servers}")
    except Exception as e:
        logger.error(f"❌ Error inicializando Kafka Producer: {e}")
        return
    
    # Configura watchdog para monitorear los archivos de log
    event_handler = ModSecLogHandler(log_file_path, error_log_path, kafka_producer, kafka_topic)
    observer = Observer()
    log_dir = Path(log_file_path).parent
    
    if not log_dir.exists():
        logger.warning(f"⚠️ Directorio de logs no existe: {log_dir}. Creando...")
        log_dir.mkdir(parents=True, exist_ok=True)
    
    observer.schedule(event_handler, str(log_dir), recursive=False)
    observer.start()
    
    logger.info("✅ Procesador de logs iniciado. Monitoreando archivos...")
    
    try:
        while True:
            time.sleep(0.5)  # Polling más frecuente
            # Leer nuevos logs periódicamente además de watchdog (para no perder logs)
            try:
                event_handler.read_new_lines()
                event_handler.read_new_error_lines()  # También leer error.log para capturar 403 bloqueados
            except Exception as e:
                logger.debug(f"Error en polling periódico: {e}")
            # Flush periódico del batch pendiente (por si acaso)
            if event_handler.batch:
                current_time = time.time()
                if (current_time - event_handler.last_flush) >= event_handler.batch_timeout * 2:
                    event_handler._flush_batch()
    except KeyboardInterrupt:
        logger.info("🛑 Deteniendo procesador de logs...")
        # Flush final del batch pendiente
        if event_handler.batch:
            logger.info(f"Enviando batch final de {len(event_handler.batch)} logs...")
            event_handler._flush_batch()
        observer.stop()
    
    observer.join()
    kafka_producer.close()
    logger.info(f"👋 Procesador de logs detenido. Total procesados: {event_handler.logs_processed}, Total enviados: {event_handler.logs_sent}")


if __name__ == '__main__':
    main()

