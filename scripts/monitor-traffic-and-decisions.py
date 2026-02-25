#!/usr/bin/env python3
"""
Script de monitoreo de tráfico y decisiones del Agente IA
"""

import psycopg2
import os
import sys
from datetime import datetime, timedelta
from collections import Counter

# Configuración de PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "YOUR_IP_ADDRESS")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "soc_ai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "soc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

if not POSTGRES_PASSWORD:
    print("⚠️ POSTGRES_PASSWORD no configurado. Usando variable de entorno...")
    # Intentar leer desde archivo o variable de entorno
    try:
        with open("/opt/tokio-ai-waf/.env", "r") as f:
            for line in f:
                if line.startswith("POSTGRES_PASSWORD = "YOUR_POSTGRES_PASSWORD"=", 1)[1].strip().strip('"')
                    break
    except:
        pass

if not POSTGRES_PASSWORD:
    print("❌ Error: POSTGRES_PASSWORD no encontrado")
    sys.exit(1)

try:
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        connect_timeout=10
    )
    cursor = conn.cursor()
    
    print("=" * 100)
    print("📊 MONITOREO DE TRÁFICO Y DECISIONES DEL AGENTE IA")
    print("=" * 100)
    print(f"⏰ Fecha/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. Decisiones del Agente IA (últimas 24 horas)
    print("🤖 DECISIONES DEL AGENTE IA (Últimas 24 horas):")
    print("-" * 100)
    cursor.execute("""
        SELECT 
            bi.ip,
            bi.threat_type,
            bi.severity,
            bi.blocked_at,
            bi.reason,
            COALESCE(classification_source, blocked_by) as source,
            COUNT(DISTINCT wl.id) as total_logs,
            ARRAY_AGG(DISTINCT wl.threat_type) FILTER (WHERE wl.threat_type IS NOT NULL) as threat_types,
            ARRAY_AGG(DISTINCT wl.uri) FILTER (WHERE wl.uri IS NOT NULL AND wl.uri != '' AND wl.uri != '/') as sample_uris
        FROM blocked_ips bi
        LEFT JOIN waf_logs wl ON wl.ip = bi.ip::text 
            AND wl.timestamp > bi.blocked_at - INTERVAL '2 hours'
            AND wl.timestamp < bi.blocked_at + INTERVAL '1 hour'
        WHERE bi.active = TRUE
        AND (bi.expires_at IS NULL OR bi.expires_at > NOW())
        AND (bi.classification_source = 'time_window_soc_analysis' 
             OR bi.blocked_by = 'time_window_soc_analysis'
             OR bi.classification_source = 'immediate_scan_block'
             OR bi.blocked_by = 'immediate_scan_block')
        AND bi.blocked_at > NOW() - INTERVAL '24 hours'
        GROUP BY bi.ip, bi.threat_type, bi.severity, bi.blocked_at, bi.reason, bi.classification_source, bi.blocked_by
        ORDER BY bi.blocked_at DESC
        LIMIT 20
    """)
    
    decisions = cursor.fetchall()
    if decisions:
        print(f"  ✅ Total decisiones: {len(decisions)}")
        print()
        for ip, threat_type, severity, blocked_at, reason, source, total_logs, threat_types, sample_uris in decisions:
            print(f"  🔴 IP: {ip}")
            print(f"     Tipo: {threat_type} | Severidad: {severity} | Fuente: {source}")
            print(f"     Bloqueado: {blocked_at}")
            print(f"     Total logs asociados: {total_logs}")
            if threat_types:
                print(f"     Tipos detectados: {', '.join(threat_types[:5])}")
            if sample_uris:
                print(f"     URIs de ejemplo: {', '.join(sample_uris[:3])}")
            if reason:
                print(f"     Razón: {reason[:100]}")
            print()
    else:
        print("  ⚠️ No hay decisiones del agente en las últimas 24 horas")
    print()
    
    # 2. Estadísticas de tráfico bloqueado vs permitido
    print("📈 ESTADÍSTICAS DE TRÁFICO (Últimas 24 horas):")
    print("-" * 100)
    cursor.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE blocked = TRUE) as blocked,
            COUNT(*) FILTER (WHERE blocked = FALSE) as allowed,
            COUNT(*) FILTER (WHERE threat_type = 'SCAN_PROBE') as scan_probes,
            COUNT(*) FILTER (WHERE threat_type = 'XSS') as xss,
            COUNT(*) FILTER (WHERE threat_type = 'SQL_INJECTION') as sql_injection,
            COUNT(*) FILTER (WHERE threat_type = 'NONE') as none,
            COUNT(*) FILTER (WHERE threat_type = 'MULTIPLE_ATTACKS') as multiple,
            COUNT(DISTINCT ip) FILTER (WHERE blocked = TRUE) as unique_blocked_ips,
            COUNT(DISTINCT ip) as total_unique_ips
        FROM waf_logs
        WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)
    
    stats = cursor.fetchone()
    blocked, allowed, scan_probes, xss, sql_injection, none, multiple, unique_blocked_ips, total_unique_ips = stats
    
    total = blocked + allowed
    if total > 0:
        block_rate = (blocked / total) * 100
        print(f"  📊 Total requests: {total:,}")
        print(f"  ✅ Bloqueados: {blocked:,} ({block_rate:.1f}%)")
        print(f"  ⚪ Permitidos: {allowed:,} ({100-block_rate:.1f}%)")
        print(f"  🔍 SCAN_PROBE: {scan_probes:,}")
        print(f"  ⚠️ XSS: {xss:,}")
        print(f"  🗄️ SQL_INJECTION: {sql_injection:,}")
        print(f"  🔥 MULTIPLE_ATTACKS: {multiple:,}")
        print(f"  ❓ NONE: {none:,}")
        print(f"  🎯 IPs únicas bloqueadas: {unique_blocked_ips}")
        print(f"  🌐 IPs únicas totales: {total_unique_ips}")
    print()
    
    # 3. IPs bloqueadas activas
    print("🛡️ IPs BLOQUEADAS ACTIVAS:")
    print("-" * 100)
    cursor.execute("""
        SELECT ip, threat_type, severity, blocked_at, reason, classification_source, blocked_by
        FROM blocked_ips
        WHERE active = TRUE
        AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY blocked_at DESC
        LIMIT 15
    """)
    
    blocked_ips = cursor.fetchall()
    if blocked_ips:
        print(f"  ✅ Total IPs bloqueadas activas: {len(blocked_ips)}")
        print()
        for ip, threat_type, severity, blocked_at, reason, source, blocked_by in blocked_ips:
            source_info = source or blocked_by or "unknown"
            print(f"  🔴 {ip} | {threat_type} | {severity} | {blocked_at} | {source_info}")
    else:
        print("  ⚠️ No hay IPs bloqueadas activas")
    print()
    
    # 4. Análisis de efectividad del agente
    print("🎯 ANÁLISIS DE EFECTIVIDAD DEL AGENTE:")
    print("-" * 100)
    cursor.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE classification_source = 'time_window_soc_analysis' OR blocked_by = 'time_window_soc_analysis') as soc_decisions,
            COUNT(*) FILTER (WHERE classification_source = 'immediate_scan_block' OR blocked_by = 'immediate_scan_block') as immediate_blocks,
            COUNT(*) FILTER (WHERE classification_source = 'heuristic' OR blocked_by = 'heuristic') as heuristic_blocks,
            COUNT(*) FILTER (WHERE classification_source = 'waf' OR blocked_by = 'waf') as waf_blocks
        FROM blocked_ips
        WHERE active = TRUE
        AND (expires_at IS NULL OR expires_at > NOW())
        AND blocked_at > NOW() - INTERVAL '24 hours'
    """)
    
    effectiveness = cursor.fetchone()
    soc_decisions, immediate_blocks, heuristic_blocks, waf_blocks = effectiveness
    total_blocks = soc_decisions + immediate_blocks + heuristic_blocks + waf_blocks
    
    if total_blocks > 0:
        print(f"  🤖 Decisiones SOC (análisis temporal): {soc_decisions} ({soc_decisions/total_blocks*100:.1f}%)")
        print(f"  ⚡ Bloqueos inmediatos (escaneos): {immediate_blocks} ({immediate_blocks/total_blocks*100:.1f}%)")
        print(f"  🔍 Bloqueos heurísticos: {heuristic_blocks} ({heuristic_blocks/total_blocks*100:.1f}%)")
        print(f"  🛡️ Bloqueos WAF: {waf_blocks} ({waf_blocks/total_blocks*100:.1f}%)")
        print()
        print(f"  ✅ Total bloqueos inteligentes (SOC + Inmediatos): {soc_decisions + immediate_blocks} ({(soc_decisions + immediate_blocks)/total_blocks*100:.1f}%)")
    print()
    
    # 5. Top IPs atacantes
    print("🔥 TOP 10 IPs ATACANTES (Últimas 24 horas):")
    print("-" * 100)
    cursor.execute("""
        SELECT 
            ip,
            COUNT(*) as total_requests,
            COUNT(*) FILTER (WHERE blocked = TRUE) as blocked_requests,
            COUNT(*) FILTER (WHERE threat_type = 'SCAN_PROBE') as scan_count,
            COUNT(DISTINCT threat_type) FILTER (WHERE threat_type IS NOT NULL) as unique_threats,
            MAX(timestamp) as last_seen
        FROM waf_logs
        WHERE timestamp > NOW() - INTERVAL '24 hours'
        GROUP BY ip
        ORDER BY total_requests DESC
        LIMIT 10
    """)
    
    top_ips = cursor.fetchall()
    if top_ips:
        for ip, total_req, blocked_req, scan_count, unique_threats, last_seen in top_ips:
            block_pct = (blocked_req / total_req * 100) if total_req > 0 else 0
            print(f"  🔴 {ip}")
            print(f"     Requests: {total_req} | Bloqueados: {blocked_req} ({block_pct:.1f}%) | Escaneos: {scan_count} | Tipos únicos: {unique_threats}")
            print(f"     Última actividad: {last_seen}")
            print()
    print()
    
    cursor.close()
    conn.close()
    
    print("=" * 100)
    print("✅ Monitoreo completado exitosamente")
    print("=" * 100)
    
except psycopg2.OperationalError as e:
    print(f"❌ Error de conexión a PostgreSQL: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)







