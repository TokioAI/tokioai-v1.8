#!/usr/bin/env python3
"""
Script para corregir las queries del dashboard
"""
import re

file_path = '/home/osboxes/SOC-AI-LAB/dashboard-api/app.py'

with open(file_path, 'r') as f:
    content = f.read()

# Reemplazar la sección de stats_summary para que busque en todos los logs
old_stats = '''            # Estadísticas rápidas usando agregaciones SQL
            # Buscar en todos los logs (no filtrar por tiempo para mostrar datos históricos)
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN blocked THEN 1 ELSE 0 END) as blocked_count,
                    SUM(CASE WHEN NOT blocked THEN 1 ELSE 0 END) as allowed_count,
                    COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
            """)
            
            stats_row = cursor.fetchone()
            total = stats_row[0] if stats_row else 0
            blocked_count = stats_row[1] if stats_row and stats_row[1] is not None else 0
            allowed_count = stats_row[2] if stats_row and stats_row[2] is not None else 0
            unique_ips = stats_row[3] if stats_row and stats_row[3] is not None else 0
            
            # Top threats - buscar en el mismo rango de tiempo que usamos para stats
            if total > 0:
                # Usar el mismo filtro de tiempo que usamos para stats
                if total > 0:  # Ya tenemos datos, usar el mismo rango
                    time_filter = "created_at > NOW() - INTERVAL '24 hours'"
                    cursor.execute("""
                        SELECT threat_type, COUNT(*) as count
                        FROM waf_logs
                        WHERE threat_type IS NOT NULL 
                          AND created_at > NOW() - INTERVAL '24 hours'
                        GROUP BY threat_type
                        ORDER BY count DESC
                        LIMIT 5
                    """)
                else:
                    cursor.execute("""
                        SELECT threat_type, COUNT(*) as count
                        FROM waf_logs
                        WHERE threat_type IS NOT NULL
                        GROUP BY threat_type
                        ORDER BY count DESC
                        LIMIT 5
                    """)
            else:
                # Si no hay datos en 24h, buscar en todos los logs
                cursor.execute("""
                    SELECT threat_type, COUNT(*) as count
                    FROM waf_logs
                    WHERE threat_type IS NOT NULL
                    GROUP BY threat_type
                    ORDER BY count DESC
                    LIMIT 5
                """)'''

new_stats = '''            # Estadísticas rápidas usando agregaciones SQL
            # Buscar en TODOS los logs (sin filtro de tiempo para mostrar datos históricos)
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN blocked THEN 1 ELSE 0 END) as blocked_count,
                    SUM(CASE WHEN NOT blocked THEN 1 ELSE 0 END) as allowed_count,
                    COUNT(DISTINCT ip) as unique_ips
                FROM waf_logs
            """)
            
            stats_row = cursor.fetchone()
            total = int(stats_row[0]) if stats_row and stats_row[0] is not None else 0
            blocked_count = int(stats_row[1]) if stats_row and stats_row[1] is not None else 0
            allowed_count = int(stats_row[2]) if stats_row and stats_row[2] is not None else 0
            unique_ips = int(stats_row[3]) if stats_row and stats_row[3] is not None else 0
            
            # Top threats - buscar en todos los logs
            cursor.execute("""
                SELECT threat_type, COUNT(*) as count
                FROM waf_logs
                WHERE threat_type IS NOT NULL
                GROUP BY threat_type
                ORDER BY count DESC
                LIMIT 5
            """)'''

if old_stats in content:
    content = content.replace(old_stats, new_stats)
    with open(file_path, 'w') as f:
        f.write(content)
    print("✅ Queries corregidas")
else:
    print("⚠️  No se encontró el patrón exacto, buscando variaciones...")
    # Buscar y reemplazar de forma más flexible
    pattern = r'# Top threats - buscar en el mismo rango de tiempo.*?LIMIT 5\s*"""\)'
    replacement = '''# Top threats - buscar en todos los logs
            cursor.execute("""
                SELECT threat_type, COUNT(*) as count
                FROM waf_logs
                WHERE threat_type IS NOT NULL
                GROUP BY threat_type
                ORDER BY count DESC
                LIMIT 5
            """)'''
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    if new_content != content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        print("✅ Queries corregidas (patrón flexible)")
    else:
        print("❌ No se pudo corregir automáticamente")



