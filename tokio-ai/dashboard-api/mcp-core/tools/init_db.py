import sqlite3
import os

DB_PATH = '/irt/proyectos/soar-mcp-server/data/cyborg_sentinel.db'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla para logs de FW
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fw_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            topic TEXT,
            source_ip TEXT,
            dest_ip TEXT,
            source_port INTEGER,
            dest_port INTEGER,
            action TEXT,
            raw_log TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Tabla para logs de WAF
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waf_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT,
            host TEXT,
            url TEXT,
            method TEXT,
            status_code INTEGER,
            signature_id TEXT,
            action TEXT,
            raw_log TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabla para persistencia de incidentes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS persisted_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id TEXT UNIQUE,
            status TEXT,
            severity TEXT,
            incident_type TEXT,
            owner TEXT,
            description TEXT,
            raw_data TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabla para monitoreo silencioso
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS silent_watch_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_ip TEXT,
            status TEXT,
            last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details TEXT
        )
    """)
    
    # Índices para búsqueda rápida
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fw_source_ip ON fw_logs (source_ip)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fw_dest_ip ON fw_logs (dest_ip)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_waf_client_ip ON waf_logs (client_ip)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fw_event_time ON fw_logs (event_time)")
    
    conn.commit()
    conn.close()
    print(f"Base de datos SQLite inicializada en {DB_PATH}")

if __name__ == "__main__":
    init_db()
