#!/usr/bin/env python3.11
"""
Tools para operaciones con archivos
"""

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

async def tool_write_file(
    content: str,
    filename: Optional[str] = None,
    directory: Optional[str] = None,
    append: bool = False
) -> Dict[str, Any]:
    """
    Guarda contenido en un archivo de texto.
    
    Args:
        content: Contenido a guardar en el archivo
        filename: Nombre del archivo (opcional, se genera automáticamente si no se proporciona)
        directory: Directorio donde guardar (opcional, por defecto usa /irt/proyectos/soar-mcp-server/exports)
        append: Si es True, agrega al final del archivo. Si es False, sobrescribe el archivo.
    
    Returns:
        Dict con resultado de la operación
    """
    try:
        # Directorio por defecto
        if not directory:
            directory = "/irt/proyectos/soar-mcp-server/exports"
        
        # Crear directorio si no existe
        os.makedirs(directory, exist_ok=True)
        
        # Generar nombre de archivo si no se proporciona
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"output_{timestamp}.txt"
        
        # Asegurar que el archivo tenga extensión .txt si no la tiene
        if not filename.endswith('.txt'):
            filename = f"{filename}.txt"
        
        # Ruta completa del archivo
        filepath = os.path.join(directory, filename)
        
        # Verificar que el directorio es seguro (no permitir rutas absolutas peligrosas)
        if not os.path.abspath(filepath).startswith(os.path.abspath(directory)):
            return {
                "success": False,
                "error": f"Ruta de archivo no permitida: {filepath}"
            }
        
        # Escribir o agregar contenido
        mode = 'a' if append else 'w'
        encoding = 'utf-8'
        
        with open(filepath, mode, encoding=encoding) as f:
            if append:
                f.write("\n" + "="*60 + "\n")
                f.write(f"Agregado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*60 + "\n\n")
            f.write(content)
            if not content.endswith('\n'):
                f.write('\n')
        
        # Obtener tamaño del archivo
        file_size = os.path.getsize(filepath)
        
        logger.info(f"Archivo guardado: {filepath} ({file_size} bytes)")
        
        return {
            "success": True,
            "filepath": filepath,
            "filename": filename,
            "directory": directory,
            "size_bytes": file_size,
            "size_kb": round(file_size / 1024, 2),
            "mode": "append" if append else "write",
            "message": f"Contenido guardado exitosamente en {filepath}"
        }
        
    except PermissionError:
        return {
            "success": False,
            "error": f"No tienes permisos para escribir en {directory}"
        }
    except Exception as e:
        logger.error(f"Error guardando archivo: {e}")
        return {
            "success": False,
            "error": str(e)
        }

async def tool_read_file(
    filepath: str
) -> Dict[str, Any]:
    """
    Lee el contenido de un archivo de texto.
    
    Args:
        filepath: Ruta completa del archivo a leer
    
    Returns:
        Dict con el contenido del archivo
    """
    try:
        # Verificar que el archivo existe
        if not os.path.exists(filepath):
            return {
                "success": False,
                "error": f"El archivo no existe: {filepath}"
            }
        
        # Verificar que es un archivo (no un directorio)
        if not os.path.isfile(filepath):
            return {
                "success": False,
                "error": f"La ruta no es un archivo: {filepath}"
            }
        
        # Leer archivo
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        file_size = os.path.getsize(filepath)
        
        return {
            "success": True,
            "filepath": filepath,
            "content": content,
            "size_bytes": file_size,
            "size_kb": round(file_size / 1024, 2),
            "lines": len(content.split('\n'))
        }
        
    except PermissionError:
        return {
            "success": False,
            "error": f"No tienes permisos para leer el archivo: {filepath}"
        }
    except UnicodeDecodeError:
        return {
            "success": False,
            "error": f"El archivo no es un archivo de texto válido (UTF-8): {filepath}"
        }
    except Exception as e:
        logger.error(f"Error leyendo archivo: {e}")
        return {
            "success": False,
            "error": str(e)
        }
