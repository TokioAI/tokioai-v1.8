"""
IPBlockSyncWorker - Worker async que:
1. Escucha topic Kafka 'ip-blocks' para bloqueos nuevos
2. Escribe en PostgreSQL tabla blocked_ips
3. Regenera /etc/nginx/conf.d/auto-blocked-ips.conf
4. Recarga Nginx sin downtime
5. Monitorea TTLs expirados y libera automáticamente
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional
from nginx_manager import NginxTenantManager

try:
    from kafka import KafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

try:
    from db import _get_postgres_conn, _return_postgres_conn
    from psycopg2.extras import RealDictCursor
except ImportError:
    _get_postgres_conn = None
    _return_postgres_conn = None

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC_IP_BLOCKS = os.getenv("KAFKA_TOPIC_IP_BLOCKS", "ip-blocks")


class IPBlockSyncWorker:
    """
    Worker async que gestiona bloqueos y desbloqueos de IPs automáticamente.
    """
    
    def __init__(self):
        self.nginx_manager = NginxTenantManager()
        self.running = False
    
    async def run(self):
        """Ejecuta el worker con todas sus tareas"""
        self.running = True
        await asyncio.gather(
            self._kafka_block_listener(),
            self._ttl_expiry_monitor(),
        )
    
    async def _kafka_block_listener(self):
        """Escucha topic 'ip-blocks' y procesa bloqueos nuevos"""
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka no disponible, bloqueos automáticos deshabilitados")
            return
        
        consumer = None
        while self.running:
            try:
                if consumer is None:
                    consumer = KafkaConsumer(
                        KAFKA_TOPIC_IP_BLOCKS,
                        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                        auto_offset_reset='latest',
                        value_deserializer=lambda m: json.loads(m.decode('utf-8', errors='ignore')),
                        consumer_timeout_ms=5000,
                        enable_auto_commit=True,
                        group_id='ip-block-sync-worker'
                    )
                    logger.info(f"✅ IPBlockSyncWorker conectado a Kafka")
                
                # Poll mensajes
                message_batch = consumer.poll(timeout_ms=5000, max_records=100)
                
                for topic_partition, messages in message_batch.items():
                    for message in messages:
                        try:
                            event = message.value
                            if event and isinstance(event, dict):
                                action = event.get("action", "block")
                                
                                if action == "block":
                                    await self._block_ip(
                                        ip=event.get("ip"),
                                        tenant_id=event.get("tenant_id"),
                                        reason=event.get("reason", "automatic"),
                                        ttl_seconds=event.get("ttl_seconds", 86400)  # 24h por defecto
                                    )
                                elif action == "unblock":
                                    await self._unblock_ip(
                                        ip=event.get("ip"),
                                        reason=event.get("reason", "manual")
                                    )
                        except Exception as e:
                            logger.error(f"Error procesando evento de bloqueo: {e}")
                
            except Exception as e:
                logger.error(f"Error en kafka_block_listener: {e}")
                if consumer:
                    try:
                        consumer.close()
                    except:
                        pass
                    consumer = None
                await asyncio.sleep(5)  # Esperar antes de reconectar
        
        if consumer:
            try:
                consumer.close()
            except:
                pass
    
    async def _ttl_expiry_monitor(self):
        """Cada 60 segundos revisa IPs expiradas y las libera"""
        while self.running:
            try:
                await asyncio.sleep(60)
                
                expired = await self._get_expired_ips()
                for ip_data in expired:
                    await self._unblock_ip(
                        ip=ip_data['ip'],
                        reason="ttl_expired"
                    )
                    
            except Exception as e:
                logger.error(f"Error en ttl_expiry_monitor: {e}")
                await asyncio.sleep(60)
    
    async def _get_expired_ips(self) -> List[dict]:
        """Obtiene IPs con TTL expirado"""
        if not _get_postgres_conn:
            return []
        
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT ip, tenant_id
                FROM blocked_ips
                WHERE active = TRUE
                AND expires_at IS NOT NULL
                AND expires_at < NOW()
            """)
            
            expired = [dict(row) for row in cursor.fetchall()]
            cursor.close()
            _return_postgres_conn(conn)
            
            return expired
        except Exception as e:
            logger.error(f"Error obteniendo IPs expiradas: {e}")
            return []
    
    async def _block_ip(
        self,
        ip: str,
        tenant_id: Optional[int],
        reason: str,
        ttl_seconds: int
    ):
        """Bloquea una IP y actualiza Nginx"""
        if not _get_postgres_conn:
            logger.error("PostgreSQL no disponible para bloquear IP")
            return
        
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor()
            
            # Calcular expires_at
            expires_at = None
            if ttl_seconds > 0:
                expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
            
            # Insertar o actualizar en blocked_ips
            cursor.execute("""
                INSERT INTO blocked_ips (ip, tenant_id, blocked_at, expires_at, reason, active, created_at)
                VALUES (%s, %s, NOW(), %s, %s, TRUE, NOW())
                ON CONFLICT (ip) WHERE active = TRUE
                DO UPDATE SET
                    expires_at = EXCLUDED.expires_at,
                    reason = EXCLUDED.reason,
                    updated_at = NOW()
            """, (ip, tenant_id, expires_at, reason))
            
            conn.commit()
            cursor.close()
            _return_postgres_conn(conn)
            
            # Regenerar configuración de Nginx
            await self._regenerate_nginx_blocklist()
            
            # Registrar en audit log
            await self._log_block_action(ip, "block", reason, tenant_id)
            
            logger.info(f"✅ IP {ip} bloqueada (TTL: {ttl_seconds}s)")
            
        except Exception as e:
            logger.error(f"Error bloqueando IP {ip}: {e}")
    
    async def _unblock_ip(self, ip: str, reason: str):
        """Desbloquea una IP y actualiza Nginx"""
        if not _get_postgres_conn:
            logger.error("PostgreSQL no disponible para desbloquear IP")
            return
        
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor()
            
            # Marcar como inactivo
            cursor.execute("""
                UPDATE blocked_ips
                SET active = FALSE,
                    unblocked_at = NOW(),
                    unblock_reason = %s,
                    updated_at = NOW()
                WHERE ip = %s AND active = TRUE
            """, (reason, ip))
            
            conn.commit()
            cursor.close()
            _return_postgres_conn(conn)
            
            # Regenerar configuración de Nginx
            await self._regenerate_nginx_blocklist()
            
            # Registrar en audit log
            await self._log_block_action(ip, "unblock", reason, None)
            
            logger.info(f"✅ IP {ip} desbloqueada")
            
        except Exception as e:
            logger.error(f"Error desbloqueando IP {ip}: {e}")
    
    async def _regenerate_nginx_blocklist(self):
        """Regenera el archivo de bloqueos de Nginx"""
        if not _get_postgres_conn:
            return
        
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor()
            
            # Obtener todas las IPs bloqueadas activas
            cursor.execute("""
                SELECT DISTINCT ip
                FROM blocked_ips
                WHERE active = TRUE
                ORDER BY ip
            """)
            
            active_ips = [row[0] for row in cursor.fetchall()]
            cursor.close()
            _return_postgres_conn(conn)
            
            # Generar contenido del archivo
            config_content = self._generate_nginx_blocklist(active_ips)
            
            # Escribir al volumen compartido de Nginx (solo en local)
            # En GCP, esto se haría vía agente HTTP
            if os.getenv("DEPLOY_MODE") == "local":
                try:
                    import docker
                    client = docker.from_env()
                    container = client.containers.get("tokio-ai-modsecurity")
                    
                    container.exec_run(
                        f"sh -c 'echo \"{config_content}\" > /etc/nginx/conf.d/auto-blocked-ips.conf'",
                        user="root"
                    )
                    
                    # Recargar Nginx
                    container.exec_run("nginx -s reload", user="root")
                    logger.info(f"✅ Nginx blocklist actualizado ({len(active_ips)} IPs)")
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo actualizar Nginx blocklist: {e}")
            
        except Exception as e:
            logger.error(f"Error regenerando Nginx blocklist: {e}")
    
    def _generate_nginx_blocklist(self, active_ips: List[str]) -> str:
        """Genera el contenido del archivo de bloqueos de Nginx"""
        lines = ["# Auto-generated by Tokio AI — DO NOT EDIT MANUALLY", ""]
        for ip in active_ips:
            lines.append(f"deny {ip};")
        return "\n".join(lines)
    
    async def _log_block_action(
        self,
        ip: str,
        action: str,
        reason: str,
        tenant_id: Optional[int]
    ):
        """Registra acción en audit log"""
        if not _get_postgres_conn:
            return
        
        try:
            conn = _get_postgres_conn()
            cursor = conn.cursor()
            
            # Verificar si existe la tabla block_audit_log
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'block_audit_log'
                )
            """)
            
            if cursor.fetchone()[0]:
                cursor.execute("""
                    INSERT INTO block_audit_log (ip, action, reason, actor, tenant_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (ip, action, reason, "automatic", tenant_id))
                conn.commit()
            
            cursor.close()
            _return_postgres_conn(conn)
            
        except Exception as e:
            logger.debug(f"No se pudo registrar en audit log: {e}")


# Singleton global
ip_block_worker = IPBlockSyncWorker()
