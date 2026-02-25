#!/usr/bin/env python3
"""
Script para verificar que los logs están en la DB y que la limpieza automática funciona
"""

import os
import psycopg2
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'soar_db'),
        user=os.getenv('POSTGRES_USER', 'soar_user'),
        password=os.getenv('POSTGRES_PASSWORD', 'YOUR_POSTGRES_PASSWORD')
    )

def verify_db_logs():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        print("=" * 70)
        print("VERIFICACIÓN DE LOGS EN BASE DE DATOS")
        print("=" * 70)
        
        # Verificar que las tablas existen
        print("\n📋 VERIFICACIÓN DE TABLAS:")
        print("-" * 70)
        cursor.execute("""
            SELECT table_name, 
                   pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
            FROM pg_tables 
            WHERE tablename IN ('fw_logs', 'waf_logs')
            ORDER BY tablename
        """)
        tables = cursor.fetchall()
        if tables:
            for table in tables:
                print(f"  ✅ Tabla '{table['table_name']}' existe - Tamaño: {table['size']}")
        else:
            print("  ❌ Las tablas no existen. Ejecuta init_db.py primero.")
            return
        
        # Verificar FW logs
        print("\n📊 LOGS DE FIREWALL (fw_logs):")
        print("-" * 70)
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                MIN(event_time) as min_date,
                MAX(event_time) as max_date,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '7 days') as last_7_days,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '3 days') as last_3_days,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '1 day') as last_1_day,
                COUNT(*) FILTER (WHERE event_time < NOW() - INTERVAL '7 days') as older_than_7_days
            FROM fw_logs
        """)
        fw_stats = cursor.fetchone()
        
        if fw_stats and fw_stats['total'] > 0:
            print(f"  ✅ Total de registros: {fw_stats['total']:,}")
            print(f"  📅 Fecha más antigua: {fw_stats['min_date']}")
            print(f"  📅 Fecha más reciente: {fw_stats['max_date']}")
            
            if fw_stats['min_date'] and fw_stats['max_date']:
                days_diff = (fw_stats['max_date'] - fw_stats['min_date']).days
                print(f"  📊 Rango de días: {days_diff} días")
            
            print(f"  📈 Últimos 7 días: {fw_stats['last_7_days']:,} registros")
            print(f"  📈 Últimos 3 días: {fw_stats['last_3_days']:,} registros")
            print(f"  📈 Último día: {fw_stats['last_1_day']:,} registros")
            
            if fw_stats['older_than_7_days'] > 0:
                print(f"  ⚠️  Registros más antiguos que 7 días: {fw_stats['older_than_7_days']:,}")
                print(f"     (Deberían ser eliminados por cleanup_worker)")
            else:
                print(f"  ✅ No hay registros más antiguos que 7 días (limpieza funcionando)")
        else:
            print("  ⚠️  No hay datos en fw_logs")
            print("     Verifica que el consumer de Kafka esté corriendo")
        
        # Verificar WAF logs
        print("\n📊 LOGS DE WAF (waf_logs):")
        print("-" * 70)
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                MIN(event_time) as min_date,
                MAX(event_time) as max_date,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '7 days') as last_7_days,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '3 days') as last_3_days,
                COUNT(*) FILTER (WHERE event_time > NOW() - INTERVAL '1 day') as last_1_day,
                COUNT(*) FILTER (WHERE event_time < NOW() - INTERVAL '7 days') as older_than_7_days
            FROM waf_logs
        """)
        waf_stats = cursor.fetchall()[0]
        
        if waf_stats and waf_stats['total'] > 0:
            print(f"  ✅ Total de registros: {waf_stats['total']:,}")
            print(f"  📅 Fecha más antigua: {waf_stats['min_date']}")
            print(f"  📅 Fecha más reciente: {waf_stats['max_date']}")
            
            if waf_stats['min_date'] and waf_stats['max_date']:
                days_diff = (waf_stats['max_date'] - waf_stats['min_date']).days
                print(f"  📊 Rango de días: {days_diff} días")
            
            print(f"  📈 Últimos 7 días: {waf_stats['last_7_days']:,} registros")
            print(f"  📈 Últimos 3 días: {waf_stats['last_3_days']:,} registros")
            print(f"  📈 Último día: {waf_stats['last_1_day']:,} registros")
            
            if waf_stats['older_than_7_days'] > 0:
                print(f"  ⚠️  Registros más antiguos que 7 días: {waf_stats['older_than_7_days']:,}")
                print(f"     (Deberían ser eliminados por cleanup_worker)")
            else:
                print(f"  ✅ No hay registros más antiguos que 7 días (limpieza funcionando)")
        else:
            print("  ⚠️  No hay datos en waf_logs")
            print("     Verifica que el consumer de Kafka esté corriendo")
        
        # Verificar índices
        print("\n🔍 VERIFICACIÓN DE ÍNDICES:")
        print("-" * 70)
        cursor.execute("""
            SELECT indexname, tablename 
            FROM pg_indexes 
            WHERE tablename IN ('fw_logs', 'waf_logs')
            ORDER BY tablename, indexname
        """)
        indexes = cursor.fetchall()
        if indexes:
            for idx in indexes:
                print(f"  ✅ Índice '{idx['indexname']}' en '{idx['tablename']}'")
        else:
            print("  ⚠️  No se encontraron índices (puede afectar rendimiento)")
        
        # Verificar configuración de limpieza
        print("\n🧹 CONFIGURACIÓN DE LIMPIEZA AUTOMÁTICA:")
        print("-" * 70)
        cleanup_days = os.getenv('DB_CLEANUP_DAYS', '7')
        print(f"  📌 DB_CLEANUP_DAYS: {cleanup_days} días")
        print(f"  ⏰ Frecuencia: Cada 1 hora (3600 segundos)")
        print(f"  🔄 Proceso: cleanup_worker() en kafka_consumer_service.py")
        print(f"  ✅ Ejecuta VACUUM después de limpiar para optimizar espacio")
        
        # Verificar tamaño total de la base de datos
        print("\n💾 TAMAÑO DE LA BASE DE DATOS:")
        print("-" * 70)
        cursor.execute("""
            SELECT 
                pg_size_pretty(pg_database_size(current_database())) as db_size,
                pg_size_pretty(SUM(pg_total_relation_size(schemaname||'.'||tablename))) as tables_size
            FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        size_info = cursor.fetchone()
        if size_info:
            print(f"  📊 Tamaño total de la DB: {size_info['db_size']}")
            print(f"  📊 Tamaño de tablas: {size_info['tables_size']}")
        
        print("\n" + "=" * 70)
        print("CONCLUSIÓN:")
        print("=" * 70)
        
        if fw_stats and fw_stats['total'] > 0:
            if fw_stats['older_than_7_days'] == 0:
                print("✅ FW logs: Limpieza automática funcionando correctamente")
            else:
                print(f"⚠️  FW logs: Hay {fw_stats['older_than_7_days']:,} registros antiguos")
                print("   Verifica que cleanup_worker esté corriendo")
        
        if waf_stats and waf_stats['total'] > 0:
            if waf_stats['older_than_7_days'] == 0:
                print("✅ WAF logs: Limpieza automática funcionando correctamente")
            else:
                print(f"⚠️  WAF logs: Hay {waf_stats['older_than_7_days']:,} registros antiguos")
                print("   Verifica que cleanup_worker esté corriendo")
        
        if (fw_stats and fw_stats['total'] == 0) or (waf_stats and waf_stats['total'] == 0):
            print("⚠️  No hay datos en las tablas")
            print("   Verifica que kafka_consumer_service.py esté corriendo")
        
        cursor.close()
        conn.close()
        
    except psycopg2.OperationalError as e:
        print(f"❌ Error de conexión a la base de datos: {e}")
        print("   Verifica las variables de entorno:")
        print("   - POSTGRES_HOST")
        print("   - POSTGRES_PORT")
        print("   - POSTGRES_DB")
        print("   - POSTGRES_USER")
        print("   - POSTGRES_PASSWORD")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_db_logs()
