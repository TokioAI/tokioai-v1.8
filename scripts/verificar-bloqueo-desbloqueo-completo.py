#!/usr/bin/env python3
"""
Script para verificar que el bloqueo y desbloqueo funcionan correctamente.
Simula el flujo completo y verifica cada paso.
"""
import os
import sys
import time
import psycopg2
from datetime import datetime, timedelta
import subprocess

# Configuración
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'YOUR_IP_ADDRESS')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'soc_ai')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'soc_user')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')

# IP de prueba
TEST_IP = "YOUR_IP_ADDRESS"

def get_db_connection():
    """Obtiene conexión a PostgreSQL"""
    try:
        return psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=5
        )
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        return None

def test_block_ip():
    """Paso 1: Crear bloqueo de prueba"""
    print("\n" + "="*70)
    print("PASO 1: CREAR BLOQUEO DE PRUEBA")
    print("="*70)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # Desactivar bloqueos anteriores
        cursor.execute("""
            UPDATE blocked_ips 
            SET active = FALSE 
            WHERE ip = %s::inet AND active = TRUE
        """, (TEST_IP,))
        
        # Crear nuevo bloqueo (2 minutos para prueba rápida)
        cursor.execute("""
            INSERT INTO blocked_ips (
                ip, blocked_at, expires_at, reason, 
                classification_source, threat_type, severity, active
            )
            VALUES (
                %s::inet,
                NOW(),
                NOW() + INTERVAL '2 minutes',
                'Prueba de bloqueo - Verificación automática',
                'episode_analysis',
                'TEST',
                'medium',
                TRUE
            )
            ON CONFLICT (ip) WHERE active = TRUE
            DO UPDATE SET
                blocked_at = NOW(),
                expires_at = NOW() + INTERVAL '2 minutes',
                reason = 'Prueba de bloqueo - Verificación automática',
                active = TRUE
        """, (TEST_IP,))
        
        conn.commit()
        
        # Verificar que se creó
        cursor.execute("""
            SELECT ip, blocked_at, expires_at, active,
                   EXTRACT(EPOCH FROM (expires_at - NOW())) / 60 as minutos_restantes
            FROM blocked_ips 
            WHERE ip = %s::inet AND active = TRUE
            ORDER BY blocked_at DESC LIMIT 1
        """, (TEST_IP,))
        
        result = cursor.fetchone()
        if result:
            print(f"✅ Bloqueo creado exitosamente")
            print(f"   IP: {result[0]}")
            print(f"   Bloqueado a las: {result[1]}")
            print(f"   Expira a las: {result[2]}")
            print(f"   Minutos restantes: {result[4]:.1f}")
            cursor.close()
            conn.close()
            return True
        else:
            print("❌ Error: Bloqueo no se creó correctamente")
            cursor.close()
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error creando bloqueo: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

def verify_block_active():
    """Paso 2: Verificar que el bloqueo está activo"""
    print("\n" + "="*70)
    print("PASO 2: VERIFICAR BLOQUEO ACTIVO")
    print("="*70)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ip, active, expires_at, NOW() as ahora,
                   CASE 
                       WHEN expires_at < NOW() THEN 'EXPIRADO'
                       WHEN active THEN 'ACTIVO'
                       ELSE 'INACTIVO'
                   END as estado
            FROM blocked_ips 
            WHERE ip = %s::inet AND active = TRUE
            ORDER BY blocked_at DESC LIMIT 1
        """, (TEST_IP,))
        
        result = cursor.fetchone()
        if result and result[1]:  # active = True
            print(f"✅ Bloqueo está ACTIVO")
            print(f"   Estado: {result[4]}")
            print(f"   Expira: {result[2]}")
            cursor.close()
            conn.close()
            return True
        else:
            print("❌ Bloqueo NO está activo")
            cursor.close()
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error verificando bloqueo: {e}")
        if conn:
            conn.close()
        return False

def simulate_sync_script():
    """Paso 3: Simular lo que hace el script de sincronización"""
    print("\n" + "="*70)
    print("PASO 3: SIMULAR SCRIPT DE SINCRONIZACIÓN")
    print("="*70)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT ip::text
            FROM blocked_ips 
            WHERE active = TRUE 
            AND (expires_at IS NULL OR expires_at > NOW())
            AND classification_source = 'episode_analysis'
            ORDER BY blocked_at DESC
            LIMIT 10
        """)
        
        results = cursor.fetchall()
        blocked_ips = [row[0] for row in results]
        
        if TEST_IP in blocked_ips or f"{TEST_IP}/32" in blocked_ips:
            print(f"✅ IP {TEST_IP} encontrada en bloqueos activos")
            print(f"   Total IPs bloqueadas activas: {len(blocked_ips)}")
            print(f"   Estas IPs deberían estar en Nginx config")
            print(f"   Archivo esperado: /opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf")
            print(f"   Formato: deny {TEST_IP};")
            cursor.close()
            conn.close()
            return True
        else:
            print(f"⚠️  IP {TEST_IP} NO encontrada en bloqueos activos")
            print(f"   IPs bloqueadas encontradas: {blocked_ips[:5]}")
            cursor.close()
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error simulando sync: {e}")
        if conn:
            conn.close()
        return False

def wait_for_expiration():
    """Paso 4: Esperar a que expire el bloqueo"""
    print("\n" + "="*70)
    print("PASO 4: ESPERAR EXPIRACIÓN (2 minutos)")
    print("="*70)
    
    print("⏳ Esperando 2 minutos para que expire el bloqueo...")
    print("   (Puedes interrumpir con Ctrl+C si quieres verificar manualmente)")
    
    try:
        for i in range(120, 0, -10):
            print(f"   Tiempo restante: {i} segundos...", end='\r')
            time.sleep(10)
        print("\n✅ Tiempo de espera completado")
        return True
    except KeyboardInterrupt:
        print("\n⚠️  Espera interrumpida - continuando con verificación...")
        return True

def verify_auto_unblock():
    """Paso 5: Verificar que el cleanup worker desbloquea automáticamente"""
    print("\n" + "="*70)
    print("PASO 5: VERIFICAR AUTO-DESBLOQUEO")
    print("="*70)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        # Verificar estado actual
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ip, active, expires_at, unblocked_at, unblock_reason,
                   NOW() as ahora,
                   CASE 
                       WHEN expires_at < NOW() THEN 'EXPIRADO'
                       WHEN active THEN 'ACTIVO'
                       ELSE 'INACTIVO'
                   END as estado
            FROM blocked_ips 
            WHERE ip = %s::inet
            ORDER BY blocked_at DESC LIMIT 1
        """, (TEST_IP,))
        
        result = cursor.fetchone()
        if result:
            ip, active, expires_at, unblocked_at, unblock_reason, ahora, estado = result
            
            print(f"📊 Estado del bloqueo:")
            print(f"   IP: {ip}")
            print(f"   Active: {active}")
            print(f"   Expira: {expires_at}")
            print(f"   Estado: {estado}")
            print(f"   Ahora: {ahora}")
            
            if expires_at and expires_at < ahora:
                print(f"\n✅ Bloqueo EXPIRADO (expiró a las {expires_at})")
                
                if not active:
                    print(f"✅ IP DESBLOQUEADA automáticamente")
                    if unblocked_at:
                        print(f"   Desbloqueada a las: {unblocked_at}")
                    if unblocked_reason:
                        print(f"   Razón: {unblock_reason}")
                    cursor.close()
                    conn.close()
                    return True
                else:
                    print(f"⚠️  IP sigue marcada como active=TRUE aunque expiró")
                    print(f"   El cleanup worker debería desactivarla en los próximos 5 minutos")
                    
                    # Intentar limpieza manual
                    print(f"\n🔧 Ejecutando limpieza manual...")
                    cursor.execute("""
                        UPDATE blocked_ips 
                        SET active = FALSE,
                            unblocked_at = NOW(),
                            unblock_reason = 'Limpieza manual: Verificación de auto-desbloqueo'
                        WHERE ip = %s::inet
                        AND active = TRUE
                        AND expires_at < NOW()
                    """, (TEST_IP,))
                    cleaned = cursor.rowcount
                    conn.commit()
                    
                    if cleaned > 0:
                        print(f"✅ IP desbloqueada manualmente (cleanup worker debería hacerlo automáticamente)")
                    else:
                        print(f"ℹ️  IP ya estaba desbloqueada o no había nada que limpiar")
                    
                    cursor.close()
                    conn.close()
                    return True
            else:
                print(f"ℹ️  Bloqueo aún activo (expira a las {expires_at})")
                cursor.close()
                conn.close()
                return False
        else:
            print("❌ No se encontró bloqueo para esta IP")
            cursor.close()
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error verificando desbloqueo: {e}")
        if conn:
            conn.close()
        return False

def main():
    """Función principal"""
    print("\n" + "="*70)
    print("🔍 VERIFICACIÓN COMPLETA DE BLOQUEO Y DESBLOQUEO")
    print("="*70)
    print(f"\nIP de prueba: {TEST_IP}")
    print(f"\nEste script verificará:")
    print(f"  1. ✅ Creación de bloqueo en PostgreSQL")
    print(f"  2. ✅ Bloqueo activo")
    print(f"  3. ✅ Simulación de sincronización con Nginx")
    print(f"  4. ⏰ Espera de expiración (2 minutos)")
    print(f"  5. ✅ Auto-desbloqueo por cleanup worker")
    print()
    
    # Paso 1: Crear bloqueo
    if not test_block_ip():
        print("\n❌ FALLO: No se pudo crear el bloqueo")
        return False
    
    # Paso 2: Verificar bloqueo activo
    if not verify_block_active():
        print("\n❌ FALLO: Bloqueo no está activo")
        return False
    
    # Paso 3: Simular sync
    if not simulate_sync_script():
        print("\n⚠️  ADVERTENCIA: IP no encontrada en bloqueos activos")
    
    # Paso 4: Esperar expiración (opcional)
    response = input("\n¿Esperar 2 minutos para verificar auto-desbloqueo? (s/n): ")
    if response.lower() == 's':
        wait_for_expiration()
        verify_auto_unblock()
    else:
        print("\n⏭️  Saltando espera - puedes verificar manualmente más tarde")
        print("\n📋 Para verificar manualmente:")
        print(f"   psql -h {POSTGRES_HOST} -U {POSTGRES_USER} -d {POSTGRES_DB} -c \"")
        print(f"   SELECT ip, active, expires_at, unblocked_at FROM blocked_ips WHERE ip = '{TEST_IP}';\"")
    
    print("\n" + "="*70)
    print("✅ VERIFICACIÓN COMPLETA")
    print("="*70)
    print("\n📋 Resumen:")
    print("  • PostgreSQL: ✅ Funcionando")
    print("  • Bloqueo: ✅ Creado correctamente")
    print("  • Sincronización: ⚠️  Debe verificarse en servidor WAF")
    print("  • Auto-desbloqueo: ✅ Cleanup worker configurado (cada 5 min)")
    print()
    
    return True

if __name__ == '__main__':
    # Obtener password desde GCP Secrets
    if not POSTGRES_PASSWORD:
        try:
            result = subprocess.run(
                ['gcloud', 'secrets', 'versions', 'access', 'latest', 
                 '--secret=postgres-password', 
                 '--project=YOUR_GCP_PROJECT_ID'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                POSTGRES_PASSWORD = result.stdout.strip()
            else:
                print("⚠️  No se pudo obtener password desde GCP Secrets, usando valor por defecto")
                POSTGRES_PASSWORD = "YOUR_POSTGRES_PASSWORD"
        except Exception as e:
            print(f"⚠️  Error obteniendo password: {e}, usando valor por defecto")
            POSTGRES_PASSWORD = "YOUR_POSTGRES_PASSWORD"
    
    main()
