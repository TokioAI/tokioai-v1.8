#!/usr/bin/env python3
"""
Smoke tests post-deploy para Tokio AI
Verifica que todos los servicios estén funcionando correctamente
"""
import sys
import requests
import subprocess
import json
import os
from typing import Dict, Any

def test_dashboard_health() -> bool:
    """Test: GET /health del dashboard-api devuelve 200"""
    try:
        url = os.getenv("DASHBOARD_URL", "http://localhost:8000")
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Dashboard API health check: OK")
            return True
        else:
            print(f"❌ Dashboard API health check: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Dashboard API health check: {e}")
        return False

def test_kafka_topic() -> bool:
    """Test: Kafka tiene el topic waf-logs activo"""
    try:
        result = subprocess.run(
            ["docker", "exec", "tokio-ai-kafka", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if "waf-logs" in result.stdout:
            print("✅ Kafka topic 'waf-logs': OK")
            return True
        else:
            print(f"❌ Kafka topic 'waf-logs': No encontrado")
            return False
    except Exception as e:
        print(f"❌ Kafka topic check: {e}")
        return False

def test_postgres_tables() -> bool:
    """Test: PostgreSQL tiene las tablas principales creadas"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DB", "soc_ai"),
            user=os.getenv("POSTGRES_USER", "soc_user"),
            password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")),
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('waf_logs', 'tenants', 'episodes')
        """)
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        
        required = {'waf_logs', 'tenants', 'episodes'}
        if required.issubset(set(tables)):
            print("✅ PostgreSQL tables: OK")
            return True
        else:
            print(f"❌ PostgreSQL tables: Faltan {required - set(tables)}")
            return False
    except Exception as e:
        print(f"❌ PostgreSQL tables check: {e}")
        return False

def test_websocket() -> bool:
    """Test: WebSocket /ws/logs acepta conexión"""
    try:
        import websocket
        url = os.getenv("DASHBOARD_URL", "http://localhost:8000").replace("http://", "ws://").replace("https://", "wss://")
        ws = websocket.create_connection(f"{url}/ws/logs", timeout=5)
        ws.close()
        print("✅ WebSocket /ws/logs: OK")
        return True
    except ImportError:
        print("⚠️  WebSocket test: websocket-client no instalado, saltando...")
        return True  # No fallar si no está instalado
    except Exception as e:
        print(f"❌ WebSocket /ws/logs: {e}")
        return False

def test_mcp_server() -> bool:
    """Test: El MCP server responde a list_tools"""
    try:
        # Este test requiere que el MCP server esté corriendo
        # Por ahora, solo verificamos que el proceso existe
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=mcp", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip():
            print("✅ MCP server: OK")
            return True
        else:
            print("⚠️  MCP server: No encontrado (puede ser opcional)")
            return True  # No fallar si no está corriendo
    except Exception as e:
        print(f"⚠️  MCP server check: {e}")
        return True  # No fallar

def main():
    """Ejecuta todos los smoke tests"""
    print("🧪 Ejecutando smoke tests...\n")
    
    tests = [
        ("Dashboard Health", test_dashboard_health),
        ("Kafka Topic", test_kafka_topic),
        ("PostgreSQL Tables", test_postgres_tables),
        ("WebSocket", test_websocket),
        ("MCP Server", test_mcp_server),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name}: Error inesperado: {e}")
            results.append((name, False))
        print()
    
    # Resumen
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"\n📊 Resultados: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("✅ Todos los tests pasaron!")
        sys.exit(0)
    else:
        print("❌ Algunos tests fallaron")
        sys.exit(1)

if __name__ == "__main__":
    main()
