#!/usr/bin/env python3
"""
Script para verificar la retención real de logs en PostgreSQL
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
        password=os.getenv('POSTGRES_PASSWORD', 'soar_password')
    )

def check_logs_retention():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        print("=" * 60)
        print("VERIFICACIÓN DE RETENCIÓN DE LOGS")
        print("=" * 60)
        
        # Verificar FW logs
        print("\n📊 LOGS DE FIREWALL (fw_logs):")
        print("-" * 60)
        
        # Fecha más antigua
        cursor.execute("SELECT MIN(event_time) as min_date, MAX(event_time) as max_date, COUNT(*) as total FROM fw_logs")
        fw_stats = cursor.fetchone()
        if fw_stats and fw_stats['min_date']:
            min_date = fw_stats['min_date']
            max_date = fw_stats['max_date']
            total = fw_stats['total']
            days_diff = (max_date - min_date).days if max_date and min_date else 0
            
            print(f"  Total de registros: {total:,}")
            print(f"  Fecha más antigua: {min_date}")
            print(f"  Fecha más reciente: {max_date}")
            print(f"  Rango de días: {days_diff} días")
            
            # Verificar últimos 7 días
            cursor.execute("SELECT COUNT(*) as count FROM fw_logs WHERE event_time > NOW() - INTERVAL '7 days'")
            last_7_days = cursor.fetchone()['count']
            print(f"  Registros últimos 7 días: {last_7_days:,}")
            
            # Verificar últimos 3 días
            cursor.execute("SELECT COUNT(*) as count FROM fw_logs WHERE event_time > NOW() - INTERVAL '3 days'")
            last_3_days = cursor.fetchone()['count']
            print(f"  Registros últimos 3 días: {last_3_days:,}")
            
            # Verificar últimos 1 día
            cursor.execute("SELECT COUNT(*) as count FROM fw_logs WHERE event_time > NOW() - INTERVAL '1 day'")
            last_1_day = cursor.fetchone()['count']
            print(f"  Registros últimos 1 día: {last_1_day:,}")
        else:
            print("  ⚠️  No hay datos en fw_logs")
        
        # Verificar WAF logs
        print("\n📊 LOGS DE WAF (waf_logs):")
        print("-" * 60)
        
        cursor.execute("SELECT MIN(event_time) as min_date, MAX(event_time) as max_date, COUNT(*) as total FROM waf_logs")
        waf_stats = cursor.fetchone()
        if waf_stats and waf_stats['min_date']:
            min_date = waf_stats['min_date']
            max_date = waf_stats['max_date']
            total = waf_stats['total']
            days_diff = (max_date - min_date).days if max_date and min_date else 0
            
            print(f"  Total de registros: {total:,}")
            print(f"  Fecha más antigua: {min_date}")
            print(f"  Fecha más reciente: {max_date}")
            print(f"  Rango de días: {days_diff} días")
            
            # Verificar últimos 7 días
            cursor.execute("SELECT COUNT(*) as count FROM waf_logs WHERE event_time > NOW() - INTERVAL '7 days'")
            last_7_days = cursor.fetchone()['count']
            print(f"  Registros últimos 7 días: {last_7_days:,}")
            
            # Verificar últimos 3 días
            cursor.execute("SELECT COUNT(*) as count FROM waf_logs WHERE event_time > NOW() - INTERVAL '3 days'")
            last_3_days = cursor.fetchone()['count']
            print(f"  Registros últimos 3 días: {last_3_days:,}")
            
            # Verificar últimos 1 día
            cursor.execute("SELECT COUNT(*) as count FROM waf_logs WHERE event_time > NOW() - INTERVAL '1 day'")
            last_1_day = cursor.fetchone()['count']
            print(f"  Registros últimos 1 día: {last_1_day:,}")
        else:
            print("  ⚠️  No hay datos en waf_logs")
        
        print("\n" + "=" * 60)
        print("CONCLUSIÓN:")
        print("=" * 60)
        
        if fw_stats and fw_stats['min_date']:
            fw_days = (fw_stats['max_date'] - fw_stats['min_date']).days
            if fw_days >= 7:
                print("✅ FW logs: Hay datos de 7+ días disponibles")
            elif fw_days >= 3:
                print("⚠️  FW logs: Solo hay datos de 3-6 días")
            else:
                print("❌ FW logs: Solo hay datos de menos de 3 días")
        
        if waf_stats and waf_stats['min_date']:
            waf_days = (waf_stats['max_date'] - waf_stats['min_date']).days
            if waf_days >= 7:
                print("✅ WAF logs: Hay datos de 7+ días disponibles")
            elif waf_days >= 3:
                print("⚠️  WAF logs: Solo hay datos de 3-6 días")
            else:
                print("❌ WAF logs: Solo hay datos de menos de 3 días")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_logs_retention()
