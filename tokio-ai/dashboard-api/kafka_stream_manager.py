"""
KafkaStreamManager - Consumer Kafka async que distribuye mensajes a todos los WebSocket suscritos
- Thread separado para polling Kafka (kafka-python no es async-native)
- asyncio.Queue como bridge thread-safe
- Subscribers por tenant_id para filtrado eficiente
- Buffer circular de últimos 500 eventos (disponibles al conectarse)
"""
import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from typing import Dict, Set, List, Optional, Any
from fastapi import WebSocket

try:
    from kafka import KafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC_WAF_LOGS = os.getenv("KAFKA_TOPIC_WAF_LOGS", "waf-logs")


class KafkaStreamManager:
    """
    Consumer Kafka async que distribuye mensajes a todos los WebSocket suscritos.
    - Thread separado para polling Kafka (kafka-python no es async-native)
    - asyncio.Queue como bridge thread-safe
    - Subscribers por tenant_id para filtrado eficiente
    - Buffer circular de últimos 500 eventos (disponibles al conectarse)
    """
    
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self._subscribers: Dict[str, Set[WebSocket]] = {}  # tenant_id o "all" -> set de WS
        self._buffer: deque = deque(maxlen=500)  # buffer circular
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
    
    def start(self, loop: asyncio.AbstractEventLoop):
        """Inicia el manager con el event loop"""
        if not KAFKA_AVAILABLE:
            logger.error("kafka-python no está instalado. WebSocket streaming no funcionará.")
            return
        
        self._loop = loop
        self._running = True
        
        # Thread para polling Kafka
        thread = threading.Thread(target=self._kafka_poll_thread, daemon=True)
        thread.start()
        
        # Task async para distribuir mensajes
        asyncio.ensure_future(self._dispatcher_loop(), loop=loop)
        
        logger.info("✅ KafkaStreamManager iniciado")
    
    def _kafka_poll_thread(self):
        """Corre en thread separado, nunca bloquea el event loop"""
        if not KAFKA_AVAILABLE:
            return
        
        consumer = None
        while self._running:
            try:
                if consumer is None:
                    consumer = KafkaConsumer(
                        KAFKA_TOPIC_WAF_LOGS,
                        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                        auto_offset_reset='latest',
                        value_deserializer=lambda m: json.loads(m.decode('utf-8', errors='ignore')),
                        consumer_timeout_ms=1000,
                        enable_auto_commit=True,
                        group_id=None  # No usar consumer group para streaming
                    )
                    logger.info(f"✅ Kafka consumer conectado a {KAFKA_BOOTSTRAP_SERVERS}")
                
                # Poll mensajes
                message_batch = consumer.poll(timeout_ms=1000, max_records=100)
                
                for topic_partition, messages in message_batch.items():
                    for message in messages:
                        try:
                            event = message.value
                            if event and isinstance(event, dict):
                                # Enviar al queue async
                                if self._loop and not self._loop.is_closed():
                                    asyncio.run_coroutine_threadsafe(
                                        self._queue.put(event), self._loop
                                    )
                        except Exception as e:
                            logger.warning(f"Error procesando mensaje Kafka: {e}")
                
            except Exception as e:
                logger.error(f"Error en kafka_poll_thread: {e}")
                if consumer:
                    try:
                        consumer.close()
                    except:
                        pass
                    consumer = None
                time.sleep(2)  # Esperar antes de reconectar
        
        if consumer:
            try:
                consumer.close()
            except:
                pass
    
    async def _dispatcher_loop(self):
        """Distribuye mensajes del queue a todos los WS suscritos"""
        while self._running:
            try:
                # Esperar mensaje con timeout
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Agregar al buffer
                self._buffer.append(event)
                
                # Determinar tenant_id del evento
                tenant_id = str(event.get("tenant_id", "all"))
                
                # Enviar a suscriptores del tenant específico + "all"
                targets = set()
                with self._lock:
                    if tenant_id in self._subscribers:
                        targets.update(self._subscribers[tenant_id])
                    if "all" in self._subscribers:
                        targets.update(self._subscribers["all"])
                
                # Enviar a todos los targets
                dead = set()
                for ws in targets:
                    try:
                        await ws.send_json({"type": "log", "data": event})
                    except Exception as e:
                        logger.debug(f"Error enviando a WebSocket: {e}")
                        dead.add(ws)
                
                # Limpiar suscriptores muertos
                if dead:
                    with self._lock:
                        for subs in self._subscribers.values():
                            subs.difference_update(dead)
                    
            except Exception as e:
                logger.error(f"Error en dispatcher_loop: {e}")
                await asyncio.sleep(0.1)
    
    def subscribe(self, ws: WebSocket, tenant_id: str = "all"):
        """Suscribe un WebSocket a eventos de un tenant"""
        with self._lock:
            self._subscribers.setdefault(tenant_id, set()).add(ws)
        logger.debug(f"WebSocket suscrito a tenant_id={tenant_id}")
    
    def unsubscribe(self, ws: WebSocket):
        """Desuscribe un WebSocket"""
        with self._lock:
            for subs in self._subscribers.values():
                subs.discard(ws)
        logger.debug("WebSocket desuscrito")
    
    def get_buffer(self, tenant_id: str = "all", limit: int = 100) -> List[dict]:
        """Devuelve los últimos N eventos del buffer (para nuevas conexiones WS)"""
        events = list(self._buffer)
        if tenant_id != "all":
            events = [e for e in events if str(e.get("tenant_id", "all")) == tenant_id]
        return events[-limit:]


# Singleton global
kafka_stream = KafkaStreamManager()
