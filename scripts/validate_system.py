#!/usr/bin/env python3
"""
FASE 6: Script de Validación del Sistema
Verifica que el sistema cumple con el Definition of Done
"""

import os
import sys
import time
import json
import requests
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

# PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Kafka
try:
    from kafka import KafkaConsumer
    from kafka.admin import KafkaAdminClient
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False


class SystemValidator:
    """Valida que el sistema cumple con Definition of Done"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": {},
            "overall_status": "PENDING"
        }
    
    def validate_throughput(self) -> Dict[str, Any]:
        """Valida throughput ≥ 1000 logs/min"""
        print("📊 Validando throughput...")
        
        # TODO: Ejecutar load test y medir throughput
        # Por ahora, retornar placeholder
        return {
            "status": "PENDING",
            "message": "Ejecutar: python scripts/load_test_kafka.py --rate 20 --duration 300",
            "target": "≥ 1000 logs/min"
        }
    
    def validate_consumer_lag(self) -> Dict[str, Any]:
        """Valida consumer lag < 1000 mensajes"""
        print("📊 Validando consumer lag...")
        
        if not KAFKA_AVAILABLE:
            return {
                "status": "SKIPPED",
                "message": "Kafka no disponible"
            }
        
        try:
            kafka_brokers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
            admin_client = KafkaAdminClient(
                bootstrap_servers=kafka_brokers,
                client_id='validator'
            )
            
            # Obtener consumer groups
            # TODO: Implementar obtención de lag real
            return {
                "status": "PENDING",
                "message": "Verificar manualmente: kafka-consumer-groups --describe",
                "target": "< 1000 mensajes"
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Error: {str(e)}"
            }
    
    def validate_latency(self) -> Dict[str, Any]:
        """Valida latencia P95 < 2 segundos"""
        print("📊 Validando latencia end-to-end...")
        
        # TODO: Implementar medición de latencia real
        return {
            "status": "PENDING",
            "message": "Medir latencia desde Kafka hasta PostgreSQL",
            "target": "P95 < 2 segundos"
        }
    
    def validate_ml_metrics(self) -> Dict[str, Any]:
        """Valida métricas ML: F1(ATTACK) ≥ 0.80"""
        print("📊 Validando métricas ML...")
        
        if not POSTGRES_AVAILABLE:
            return {
                "status": "SKIPPED",
                "message": "PostgreSQL no disponible"
            }
        
        try:
            postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
            postgres_port = int(os.getenv('POSTGRES_PORT', '5432'))
            
            if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME'POSTGRES_DB', 'soc_ai'),
                    user=os.getenv('POSTGRES_USER', 'soc_user'),
                    password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")),
                    connect_timeout=10
                )
            
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Obtener modelo activo
            cursor.execute("""
                SELECT model_id, f1_score, recall_per_class, f1_per_class
                FROM ml_model_registry
                WHERE is_active = TRUE
                ORDER BY deployed_at DESC
                LIMIT 1
            """)
            
            model = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if not model:
                return {
                    "status": "WARNING",
                    "message": "No hay modelo activo registrado"
                }
            
            f1_score = float(model['f1_score']) if model['f1_score'] else 0.0
            f1_per_class = model['f1_per_class']
            
            # Parsear f1_per_class si es JSON
            if isinstance(f1_per_class, str):
                f1_per_class = json.loads(f1_per_class)
            
            # F1 para clase ATTACK (índice 1 en clasificación binaria)
            f1_attack = f1_per_class[1] if f1_per_class and len(f1_per_class) > 1 else f1_score
            
            status = "PASS" if f1_attack >= 0.80 else "FAIL"
            
            return {
                "status": status,
                "f1_score": f1_score,
                "f1_attack": f1_attack,
                "target": "≥ 0.80",
                "model_id": model['model_id']
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Error: {str(e)}"
            }
    
    def validate_availability(self) -> Dict[str, Any]:
        """Valida disponibilidad del sistema"""
        print("📊 Validando disponibilidad...")
        
        try:
            api_url = os.getenv('API_URL', 'http://localhost:9000')
            response = requests.get(f"{api_url}/health", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                postgres_ok = data.get('postgres', {}).get('status') == 'ok'
                kafka_ok = data.get('kafka', {}).get('status') == 'ok'
                
                status = "PASS" if (postgres_ok and kafka_ok) else "FAIL"
                
                return {
                    "status": status,
                    "postgres": postgres_ok,
                    "kafka": kafka_ok,
                    "api": True
                }
            else:
                return {
                    "status": "FAIL",
                    "message": f"API returned {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Error: {str(e)}"
            }
    
    def validate_error_rate(self) -> Dict[str, Any]:
        """Valida error rate < 1%"""
        print("📊 Validando error rate...")
        
        try:
            api_url = os.getenv('API_URL', 'http://localhost:9000')
            response = requests.get(f"{api_url}/metrics", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                requests_total = data.get('requests_total', 0)
                errors_total = data.get('errors_total', 0)
                
                if requests_total > 0:
                    error_rate = (errors_total / requests_total) * 100
                    status = "PASS" if error_rate < 1.0 else "FAIL"
                    
                    return {
                        "status": status,
                        "error_rate": f"{error_rate:.2f}%",
                        "requests_total": requests_total,
                        "errors_total": errors_total,
                        "target": "< 1%"
                    }
                else:
                    return {
                        "status": "PENDING",
                        "message": "No hay requests aún"
                    }
            else:
                return {
                    "status": "ERROR",
                    "message": f"API returned {response.status_code}"
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Error: {str(e)}"
            }
    
    def run_all_tests(self):
        """Ejecuta todos los tests de validación"""
        print("=" * 60)
        print("🔍 VALIDACIÓN DEL SISTEMA - DEFINITION OF DONE")
        print("=" * 60)
        print()
        
        self.results["tests"]["throughput"] = self.validate_throughput()
        self.results["tests"]["consumer_lag"] = self.validate_consumer_lag()
        self.results["tests"]["latency"] = self.validate_latency()
        self.results["tests"]["ml_metrics"] = self.validate_ml_metrics()
        self.results["tests"]["availability"] = self.validate_availability()
        self.results["tests"]["error_rate"] = self.validate_error_rate()
        
        # Calcular estado general
        all_statuses = [test.get("status") for test in self.results["tests"].values()]
        
        if "ERROR" in all_statuses:
            self.results["overall_status"] = "ERROR"
        elif "FAIL" in all_statuses:
            self.results["overall_status"] = "FAIL"
        elif all(s in ["PASS", "SKIPPED"] for s in all_statuses):
            self.results["overall_status"] = "PASS"
        else:
            self.results["overall_status"] = "PENDING"
        
        # Imprimir resultados
        print()
        print("=" * 60)
        print("📊 RESULTADOS")
        print("=" * 60)
        print()
        
        for test_name, result in self.results["tests"].items():
            status = result.get("status", "UNKNOWN")
            status_icon = {
                "PASS": "✅",
                "FAIL": "❌",
                "ERROR": "⚠️",
                "PENDING": "⏳",
                "SKIPPED": "⏭️"
            }.get(status, "❓")
            
            print(f"{status_icon} {test_name.upper()}: {status}")
            if "message" in result:
                print(f"   {result['message']}")
            if "target" in result:
                print(f"   Objetivo: {result['target']}")
            print()
        
        print("=" * 60)
        print(f"🎯 ESTADO GENERAL: {self.results['overall_status']}")
        print("=" * 60)
        
        return self.results


def main():
    """Función principal"""
    validator = SystemValidator()
    results = validator.run_all_tests()
    
    # Guardar resultados
    output_file = os.getenv('VALIDATION_OUTPUT', 'validation_results.json')
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📄 Resultados guardados en: {output_file}")
    
    # Exit code basado en estado
    if results["overall_status"] == "PASS":
        sys.exit(0)
    elif results["overall_status"] == "FAIL":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()









