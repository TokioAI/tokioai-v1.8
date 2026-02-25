import logging
import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

def _get_connection():
    """Obtiene conexión a PostgreSQL para Tokio AI"""
    postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
    postgres_port = os.getenv('POSTGRES_PORT', '5432')
    postgres_db = os.getenv('POSTGRES_DB', 'soc_ai')
    postgres_user = os.getenv('POSTGRES_USER', 'soc_user')
    postgres_password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD"))
    
    # Si es un socket Unix de Cloud SQL, usarlo salvo que se fuerce IP pública
    use_public_ip = os.getenv("TOKIO_POSTGRES_USE_PUBLIC_IP", "false").lower() == "true"
    if postgres_host.startswith('/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME")
    
    return psycopg2.connect(
        host=postgres_host,
        port=int(postgres_port),
        database=postgres_db,
        user=postgres_user,
        password=postgres_password,
        connect_timeout=30  # Timeout aumentado
    )

async def tool_query_data(
    sql_query: str = None, 
    table: str = None, 
    columns: List[str] = None, 
    where: Dict = None, 
    limit: int = 100, 
    order_by: str = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_column: Optional[str] = None
):
    """Consulta datos de PostgreSQL con soporte para rangos de fecha
    
    Args:
        sql_query: Query SQL personalizado (si se proporciona, se usa directamente)
        table: Nombre de la tabla (si no se proporciona sql_query)
        columns: Lista de columnas a seleccionar (si no se proporciona sql_query)
        where: Diccionario con condiciones WHERE
        limit: Límite de resultados
        order_by: Columna para ordenar
        start_date: Fecha de inicio en formato YYYY-MM-DD o timestamp (opcional)
        end_date: Fecha de fin en formato YYYY-MM-DD o timestamp (opcional)
        date_column: Nombre de la columna de fecha para filtrar (por defecto: created_at, updated_at, timestamp, date)
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if sql_query:
            # Validación básica para evitar escrituras (solo lectura)
            forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE']
            if any(cmd in sql_query.upper() for cmd in forbidden):
                return {"success": False, "error": "Solo se permiten consultas SELECT de lectura."}
            
            # Si se proporcionan fechas, intentar agregar condiciones WHERE al query existente
            if (start_date or end_date) and date_column:
                # Intentar agregar condiciones de fecha al query
                date_conditions = []
                params = []
                
                if start_date:
                    try:
                        if len(start_date) == 10:  # Formato YYYY-MM-DD
                            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                            date_conditions.append(f"{date_column} >= %s")
                            params.append(start_dt)
                        else:
                            # Intentar como timestamp
                            start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                            start_dt = datetime.fromtimestamp(start_ts)
                            date_conditions.append(f"{date_column} >= %s")
                            params.append(start_dt)
                    except (ValueError, TypeError):
                        logger.warning(f"Formato de fecha inválido para start_date: {start_date}")
                
                if end_date:
                    try:
                        if len(end_date) == 10:  # Formato YYYY-MM-DD
                            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                            end_dt = end_dt.replace(hour=23, minute=59, second=59)
                            date_conditions.append(f"{date_column} <= %s")
                            params.append(end_dt)
                        else:
                            # Intentar como timestamp
                            end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                            end_dt = datetime.fromtimestamp(end_ts)
                            date_conditions.append(f"{date_column} <= %s")
                            params.append(end_dt)
                    except (ValueError, TypeError):
                        logger.warning(f"Formato de fecha inválido para end_date: {end_date}")
                
                if date_conditions:
                    # Agregar condiciones WHERE al query
                    sql_upper = sql_query.upper()
                    if 'WHERE' in sql_upper:
                        sql_query += " AND " + " AND ".join(date_conditions)
                    else:
                        # Encontrar dónde termina el SELECT y agregar WHERE antes de ORDER BY o LIMIT
                        sql_lower = sql_query.lower()
                        order_idx = sql_lower.find(' order by ')
                        limit_idx = sql_lower.find(' limit ')
                        
                        if order_idx >= 0:
                            sql_query = sql_query[:order_idx] + " WHERE " + " AND ".join(date_conditions) + " " + sql_query[order_idx:]
                        elif limit_idx >= 0:
                            sql_query = sql_query[:limit_idx] + " WHERE " + " AND ".join(date_conditions) + " " + sql_query[limit_idx:]
                        else:
                            sql_query += " WHERE " + " AND ".join(date_conditions)
            
            # Limitar el resultado si no tiene un LIMIT explícito
            if 'LIMIT' not in sql_query.upper():
                sql_query += f" LIMIT {limit}"
            
            if params:
                cursor.execute(sql_query, params)
            else:
                cursor.execute(sql_query)
        else:
            cols = ", ".join(columns) if columns else "*"
            query = f"SELECT {cols} FROM {table}"
            params = []
            conditions = []
            
            # Agregar condiciones WHERE existentes
            if where:
                for k, v in where.items():
                    conditions.append(f"{k} = %s")
                    params.append(v)
            
            # Agregar condiciones de fecha si se proporcionaron
            if (start_date or end_date):
                # Detectar columna de fecha automáticamente si no se especifica
                if not date_column:
                    # Buscar columnas comunes de fecha
                    date_column_candidates = ['created_at', 'updated_at', 'timestamp', 'date', 'created_date', 'updated_date']
                    if columns:
                        # Verificar si alguna de las columnas solicitadas es una fecha
                        for col in date_column_candidates:
                            if col in [c.lower() for c in columns]:
                                date_column = col
                                break
                    
                    # Si no se encontró, usar la primera candidata disponible
                    if not date_column:
                        date_column = date_column_candidates[0]
                
                if start_date:
                    try:
                        if len(start_date) == 10:  # Formato YYYY-MM-DD
                            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                            conditions.append(f"{date_column} >= %s")
                            params.append(start_dt)
                        else:
                            start_ts = float(start_date) if float(start_date) < 1e12 else float(start_date) / 1000
                            start_dt = datetime.fromtimestamp(start_ts)
                            conditions.append(f"{date_column} >= %s")
                            params.append(start_dt)
                    except (ValueError, TypeError):
                        logger.warning(f"Formato de fecha inválido para start_date: {start_date}")
                
                if end_date:
                    try:
                        if len(end_date) == 10:  # Formato YYYY-MM-DD
                            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                            end_dt = end_dt.replace(hour=23, minute=59, second=59)
                            conditions.append(f"{date_column} <= %s")
                            params.append(end_dt)
                        else:
                            end_ts = float(end_date) if float(end_date) < 1e12 else float(end_date) / 1000
                            end_dt = datetime.fromtimestamp(end_ts)
                            conditions.append(f"{date_column} <= %s")
                            params.append(end_dt)
                    except (ValueError, TypeError):
                        logger.warning(f"Formato de fecha inválido para end_date: {end_date}")
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            if order_by: 
                query += f" ORDER BY {order_by}"
            query += f" LIMIT {limit}"
            
            cursor.execute(query, params)
            
        rows = [dict(r) for r in cursor.fetchall()]
        # Serialize datetimes
        for r in rows:
            for k, v in r.items():
                if isinstance(v, datetime): r[k] = v.isoformat()
        cursor.close(); conn.close()
        return {"success": True, "data": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def tool_insert_data(table: str, data: Dict):
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING id"
        cursor.execute(query, list(data.values()))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close(); conn.close()
        return {"success": True, "id": new_id}
    except Exception as e:
        return {"success": False, "error": str(e)}
