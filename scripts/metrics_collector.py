#!/usr/bin/env python3
"""
Colector de Métricas - Recolecta métricas del sistema end-to-end
Métricas: throughput, consumer lag, DB latency, LLM latency, error rate
"""

import json
import os
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from kafka import KafkaConsumer, KafkaAdminClient
from kafka.admin import ConfigResource, ConfigResourceType
from kafka.errors import KafkaError
import psycopg2
from psycopg2.extras import RealDictCursor
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MetricsCollector:
    """Colector de métricas del sistema"""
    
    def __init__(
        self,
        kafka_bootstrap: str,
        kafka_topic: str,
        postgres_config: Dict[str, str],
        output_file: Optional[str] = None
    ):
        self.kafka_bootstrap = kafka_bootstrap
        self.kafka_topic = kafka_topic
        self.postgres_config = postgres_config
        self.output_file = output_file or f"metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.metrics_history: List[Dict[str, Any]] = []
    
    def collect_kafka_metrics(self) -> Dict[str, Any]:
        """Recolecta métricas de Kafka"""
        metrics = {
            "kafka": {
                "topic": self.kafka_topic,
                "timestamp": datetime.utcnow().isoformat(),
            }
        }
        
        try:
            # Admin client para obtener metadata del topic
            admin_client = KafkaAdminClient(
                bootstrap_servers=self.kafka_bootstrap.split(','),
                client_id='metrics-collector'
            )
            
            # Obtener metadata del topic
            metadata = admin_client.describe_topics([self.kafka_topic])
            if self.kafka_topic in metadata:
                topic_metadata = metadata[self.kafka_topic]
                metrics["kafka"]["partitions"] = len(topic_metadata.partitions)
            
            admin_client.close()
        except Exception as e:
            logger.warning(f"Error obteniendo metadata de Kafka: {e}")
            metrics["kafka"]["error"] = str(e)
        
        # Consumer lag por consumer group
        consumer_groups = [
            "postgres-persistence-group",
            "realtime-processor-group",
            "mcp-core-group",
        ]
        
        metrics["kafka"]["consumer_groups"] = {}
        
        for group_id in consumer_groups:
            try:
                consumer = KafkaConsumer(
                    self.kafka_topic,
                    bootstrap_servers=self.kafka_bootstrap.split(','),
                    group_id=group_id,
                    enable_auto_commit=False,
                    consumer_timeout_ms=1000
                )
                
                # Obtener particiones asignadas
                partitions = consumer.assignment()
                
                total_lag = 0
                partition_lags = {}
                
                for partition in partitions:
                    try:
                        # Obtener high watermark (último offset disponible)
                        high_watermark = consumer.get_partition_metadata(partition).high
                        
                        # Obtener committed offset del consumer group
                        committed = consumer.committed(partition)
                        committed_offset = committed if committed is not None else 0
                        
                        # Calcular lag
                        lag = max(0, high_watermark - committed_offset)
                        total_lag += lag
                        partition_lags[str(partition)] = {
                            "high_watermark": high_watermark,
                            "committed_offset": committed_offset,
                            "lag": lag
                        }
                    except Exception as e:
                        logger.warning(f"Error calculando lag para {partition}: {e}")
                
                consumer.close()
                
                metrics["kafka"]["consumer_groups"][group_id] = {
                    "total_lag": total_lag,
                    "partition_lags": partition_lags
                }
                
            except Exception as e:
                logger.warning(f"Error obteniendo lag para {group_id}: {e}")
                metrics["kafka"]["consumer_groups"][group_id] = {"error": str(e)}
        
        return metrics
    
    def collect_postgres_metrics(self) -> Dict[str, Any]:
        """Recolecta métricas de PostgreSQL"""
        metrics = {
            "postgres": {
                "timestamp": datetime.utcnow().isoformat(),
            }
        }
        
        try:
            conn = psycopg2.connect(
                host=self.postgres_config["host"],
                port=self.postgres_config["port"],
                database=self.postgres_config["database"],
                user=self.postgres_config["user"],
                password=self.postgres_config["password"],
                connect_timeout=5
            )
            
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Latencia de query simple
            start = time.time()
            cursor.execute("SELECT COUNT(*) FROM waf_logs")
            count = cursor.fetchone()[0]
            query_latency_ms = (time.time() - start) * 1000
            metrics["postgres"]["query_latency_ms"] = round(query_latency_ms, 2)
            metrics["postgres"]["total_logs"] = count
            
            # Latencia de query con JOIN
            start = time.time()
            cursor.execute("""
                SELECT threat_type, COUNT(*) as cnt 
                FROM waf_logs 
                WHERE timestamp > NOW() - INTERVAL '1 hour'
                GROUP BY threat_type
                LIMIT 10
            """)
            cursor.fetchall()
            join_latency_ms = (time.time() - start) * 1000
            metrics["postgres"]["join_query_latency_ms"] = round(join_latency_ms, 2)
            
            # Estadísticas de conexiones
            cursor.execute("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity
                WHERE datname = %s
            """, (self.postgres_config["database"],))
            conn_stats = cursor.fetchone()
            metrics["postgres"]["connections"] = {
                "total": conn_stats["total_connections"],
                "active": conn_stats["active_connections"],
                "idle": conn_stats["idle_connections"]
            }
            
            # Tamaño de tablas
            cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                LIMIT 5
            """)
            tables = cursor.fetchall()
            metrics["postgres"]["table_sizes"] = [
                {"table": t["tablename"], "size": t["size"]} for t in tables
            ]
            
            cursor.close()
            conn.close()
            
            metrics["postgres"]["status"] = "ok"
            
        except Exception as e:
            logger.error(f"Error recolectando métricas de Postgres: {e}", exc_info=True)
            metrics["postgres"]["status"] = "error"
            metrics["postgres"]["error"] = str(e)
        
        return metrics
    
    def collect_throughput_metrics(self, window_seconds: int = 60) -> Dict[str, Any]:
        """Recolecta métricas de throughput"""
        metrics = {
            "throughput": {
                "timestamp": datetime.utcnow().isoformat(),
                "window_seconds": window_seconds,
            }
        }
        
        try:
            conn = psycopg2.connect(
                host=self.postgres_config["host"],
                port=self.postgres_config["port"],
                database=self.postgres_config["database"],
                user=self.postgres_config["user"],
                password=self.postgres_config["password"],
                connect_timeout=5
            )
            
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Logs en la última ventana de tiempo
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE blocked = true) as blocked,
                    COUNT(*) FILTER (WHERE blocked = false) as allowed
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '%s seconds'
            """, (window_seconds,))
            
            result = cursor.fetchone()
            total = result["total"] if result else 0
            blocked = result["blocked"] if result else 0
            allowed = result["allowed"] if result else 0
            
            metrics["throughput"]["logs_per_second"] = round(total / window_seconds, 2) if window_seconds > 0 else 0
            metrics["throughput"]["logs_per_minute"] = round(total * 60 / window_seconds, 2) if window_seconds > 0 else 0
            metrics["throughput"]["total_logs"] = total
            metrics["throughput"]["blocked"] = blocked
            metrics["throughput"]["allowed"] = allowed
            
            cursor.close()
            conn.close()
            
            metrics["throughput"]["status"] = "ok"
            
        except Exception as e:
            logger.error(f"Error recolectando métricas de throughput: {e}", exc_info=True)
            metrics["throughput"]["status"] = "error"
            metrics["throughput"]["error"] = str(e)
        
        return metrics
    
    def collect_all_metrics(self) -> Dict[str, Any]:
        """Recolecta todas las métricas"""
        logger.info("📊 Recolectando métricas del sistema...")
        
        all_metrics = {
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Kafka
        logger.info("  - Kafka...")
        all_metrics.update(self.collect_kafka_metrics())
        
        # Postgres
        logger.info("  - PostgreSQL...")
        all_metrics.update(self.collect_postgres_metrics())
        
        # Throughput
        logger.info("  - Throughput...")
        all_metrics.update(self.collect_throughput_metrics())
        
        # Guardar en historial
        self.metrics_history.append(all_metrics)
        
        # Guardar en archivo
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(all_metrics) + '\n')
        except Exception as e:
            logger.error(f"Error guardando métricas: {e}")
        
        return all_metrics
    
    def print_metrics_summary(self, metrics: Dict[str, Any]):
        """Imprime resumen de métricas"""
        print("=" * 60)
        print("📊 MÉTRICAS DEL SISTEMA")
        print("=" * 60)
        
        # Kafka
        if "kafka" in metrics:
            kafka = metrics["kafka"]
            print(f"\n🔵 Kafka:")
            print(f"   Topic: {kafka.get('topic', 'N/A')}")
            if "consumer_groups" in kafka:
                for group_id, group_metrics in kafka["consumer_groups"].items():
                    if "total_lag" in group_metrics:
                        print(f"   {group_id}: Lag = {group_metrics['total_lag']} mensajes")
        
        # Postgres
        if "postgres" in metrics:
            pg = metrics["postgres"]
            if pg.get("status") == "ok":
                print(f"\n🟢 PostgreSQL:")
                print(f"   Total logs: {pg.get('total_logs', 0):,}")
                print(f"   Query latency: {pg.get('query_latency_ms', 0):.2f}ms")
                print(f"   Join query latency: {pg.get('join_query_latency_ms', 0):.2f}ms")
                if "connections" in pg:
                    conns = pg["connections"]
                    print(f"   Conexiones: {conns.get('active', 0)} activas, {conns.get('idle', 0)} idle")
        
        # Throughput
        if "throughput" in metrics:
            tp = metrics["throughput"]
            if tp.get("status") == "ok":
                print(f"\n⚡ Throughput:")
                print(f"   {tp.get('logs_per_second', 0):.2f} logs/s ({tp.get('logs_per_minute', 0):.0f} logs/min)")
                print(f"   Total (últimos {tp.get('window_seconds', 0)}s): {tp.get('total_logs', 0)}")
                print(f"   Bloqueados: {tp.get('blocked', 0)}, Permitidos: {tp.get('allowed', 0)}")
        
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Colector de métricas del sistema")
    parser.add_argument(
        "--kafka-bootstrap",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Bootstrap servers de Kafka"
    )
    parser.add_argument(
        "--kafka-topic",
        default=os.getenv("KAFKA_TOPIC_WAF_LOGS", "waf-logs"),
        help="Topic de Kafka"
    )
    parser.add_argument(
        "--postgres-host",
        default=os.getenv("POSTGRES_HOST", "localhost"),
        help="Host de PostgreSQL"
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=int(os.getenv("POSTGRES_PORT", "5432")),
        help="Puerto de PostgreSQL"
    )
    parser.add_argument(
        "--postgres-db",
        default=os.getenv("POSTGRES_DB", "soc_ai"),
        help="Base de datos"
    )
    parser.add_argument(
        "--postgres-user",
        default=os.getenv("POSTGRES_USER", "soc_user"),
        help="Usuario de PostgreSQL"
    )
    parser.add_argument(
        "--postgres-password",
        default=os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"),
        help="Contraseña de PostgreSQL"
    )
    parser.add_argument(
        "--output",
        help="Archivo de salida (default: metrics_TIMESTAMP.json)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Intervalo en segundos para recolectar métricas continuamente (0 = una vez)"
    )
    
    args = parser.parse_args()
    
    postgres_config = {
        "host": args.postgres_host,
        "port": args.postgres_port,
        "database": args.postgres_db,
        "user": args.postgres_user,
        "password": args.postgres_password,
    }
    
    collector = MetricsCollector(
        kafka_bootstrap=args.kafka_bootstrap,
        kafka_topic=args.kafka_topic,
        postgres_config=postgres_config,
        output_file=args.output
    )
    
    if args.interval > 0:
        # Recolección continua
        logger.info(f"🔄 Recolectando métricas cada {args.interval}s...")
        try:
            while True:
                metrics = collector.collect_all_metrics()
                collector.print_metrics_summary(metrics)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("⏹️  Deteniendo recolector...")
    else:
        # Recolección única
        metrics = collector.collect_all_metrics()
        collector.print_metrics_summary(metrics)


if __name__ == "__main__":
    main()









