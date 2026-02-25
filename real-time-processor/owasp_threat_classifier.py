"""
OWASP Top 10 Threat Classifier
Clasifica amenazas según OWASP Top 10 2021/2024 para estandarización y compliance
"""
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# OWASP Top 10 2021 Mapping
OWASP_TOP10_2021 = {
    "A01": {
        "name": "Broken Access Control",
        "description": "Restricciones de acceso no implementadas correctamente",
        "threat_types": ["SCAN_PROBE", "UNAUTHORIZED_ACCESS", "DIRECTORY_TRAVERSAL", "PATH_TRAVERSAL", 
                        "FORCED_BROWSING", "INSUFFICIENT_AUTHORIZATION"]
    },
    "A02": {
        "name": "Cryptographic Failures",
        "description": "Fallos criptográficos y exposición de datos sensibles",
        "threat_types": ["WEAK_ENCRYPTION", "SENSITIVE_DATA_EXPOSURE", "INSUFFICIENT_CRYPTOGRAPHY"]
    },
    "A03": {
        "name": "Injection",
        "description": "Vulnerabilidades de inyección (SQL, NoSQL, OS Command, LDAP, etc.)",
        "threat_types": ["SQLI", "SQL_INJECTION", "NO_SQL_INJECTION", "OS_COMMAND_INJECTION", 
                        "CMD_INJECTION", "LDAP_INJECTION", "SCRIPT_INJECTION", "XSS", 
                        "RFI_LFI", "RFI", "LFI", "XXE", "XPATH_INJECTION"]
    },
    "A05": {
        "name": "Security Misconfiguration",
        "description": "Configuración de seguridad incorrecta o por defecto",
        "threat_types": ["EXPOSED_ENDPOINTS", "DEFAULT_CREDENTIALS", "DEBUG_ENABLED", 
                        "MISCONFIGURATION", "INSECURE_CONFIGURATION"]
    },
    "A07": {
        "name": "Identification and Authentication Failures",
        "description": "Fallos en identificación y autenticación",
        "threat_types": ["BRUTE_FORCE", "CREDENTIAL_STUFFING", "SESSION_HIJACKING", 
                        "WEAK_AUTHENTICATION", "BROKEN_AUTHENTICATION"]
    },
    "A08": {
        "name": "Software and Data Integrity Failures",
        "description": "Fallos en integridad de software y datos",
        "threat_types": ["DESERIALIZATION", "INSECURE_DESERIALIZATION", "INTEGRITY_FAILURE"]
    },
    "A10": {
        "name": "Server-Side Request Forgery (SSRF)",
        "description": "Falsificación de solicitudes del lado del servidor",
        "threat_types": ["SSRF", "SERVER_SIDE_REQUEST_FORGERY"]
    }
}

# Mapeo directo de threat_types comunes a códigos OWASP
THREAT_TYPE_TO_OWASP = {
    # A01: Broken Access Control
    "PATH_TRAVERSAL": "A01",
    "DIRECTORY_TRAVERSAL": "A01",
    "SCAN_PROBE": "A01",
    "UNAUTHORIZED_ACCESS": "A01",
    "FORCED_BROWSING": "A01",
    "SCANNING": "A01",
    
    # A02: Cryptographic Failures (limitado desde logs)
    "SENSITIVE_DATA_EXPOSURE": "A02",
    "WEAK_ENCRYPTION": "A02",
    
    # A03: Injection
    "SQLI": "A03",
    "SQL_INJECTION": "A03",
    "XSS": "A03",
    "SCRIPT_INJECTION": "A03",
    "CMD_INJECTION": "A03",
    "OS_COMMAND_INJECTION": "A03",
    "COMMAND_INJECTION": "A03",
    "RFI_LFI": "A03",
    "RFI": "A03",
    "LFI": "A03",
    "XXE": "A03",
    "XPATH_INJECTION": "A03",
    "NO_SQL_INJECTION": "A03",
    "LDAP_INJECTION": "A03",
    
    # A05: Security Misconfiguration
    "EXPOSED_ENDPOINTS": "A05",
    "DEFAULT_CREDENTIALS": "A05",
    "DEBUG_ENABLED": "A05",
    "MISCONFIGURATION": "A05",
    
    # A07: Authentication Failures
    "BRUTE_FORCE": "A07",
    "CREDENTIAL_STUFFING": "A07",
    "SESSION_HIJACKING": "A07",
    "WEAK_AUTHENTICATION": "A07",
    
    # A08: Data Integrity Failures
    "DESERIALIZATION": "A08",
    "INSECURE_DESERIALIZATION": "A08",
    
    # A10: SSRF
    "SSRF": "A10",
    "SERVER_SIDE_REQUEST_FORGERY": "A10",
    
    # Otros comunes que no encajan perfectamente
    "CSRF": "A01",  # Puede ser A01 (access control) o A07 (authentication)
    "OTHER": None,
    "NONE": None,
}


def classify_by_owasp_top10(threat_type: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Clasifica un threat_type según OWASP Top 10 2021.
    
    Args:
        threat_type: Tipo de amenaza detectada (ej: "SQLI", "XSS", "PATH_TRAVERSAL")
    
    Returns:
        Dict con:
            - owasp_code: Código OWASP (ej: "A03") o None
            - owasp_category: Nombre de la categoría (ej: "Injection") o None
            - owasp_description: Descripción de la categoría o None
    """
    if not threat_type:
        return {
            "owasp_code": None,
            "owasp_category": None,
            "owasp_description": None
        }
    
    threat_type_upper = threat_type.upper().strip()
    
    # Buscar en mapeo directo
    owasp_code = THREAT_TYPE_TO_OWASP.get(threat_type_upper)
    
    if owasp_code:
        category_info = OWASP_TOP10_2021.get(owasp_code)
        return {
            "owasp_code": owasp_code,
            "owasp_category": category_info["name"] if category_info else None,
            "owasp_description": category_info["description"] if category_info else None
        }
    
    # Si no está en el mapeo directo, buscar en las listas de threat_types
    for code, info in OWASP_TOP10_2021.items():
        if threat_type_upper in [t.upper() for t in info["threat_types"]]:
            return {
                "owasp_code": code,
                "owasp_category": info["name"],
                "owasp_description": info["description"]
            }
    
    # No encontrado
    logger.debug(f"Threat type '{threat_type}' no mapeado a OWASP Top 10")
    return {
        "owasp_code": None,
        "owasp_category": None,
        "owasp_description": None
    }


def get_owasp_description(code: str) -> Optional[str]:
    """
    Obtiene la descripción de un código OWASP.
    
    Args:
        code: Código OWASP (ej: "A03")
    
    Returns:
        Descripción o None
    """
    category_info = OWASP_TOP10_2021.get(code.upper())
    return category_info["description"] if category_info else None


def get_owasp_name(code: str) -> Optional[str]:
    """
    Obtiene el nombre de una categoría OWASP.
    
    Args:
        code: Código OWASP (ej: "A03")
    
    Returns:
        Nombre de la categoría o None
    """
    category_info = OWASP_TOP10_2021.get(code.upper())
    return category_info["name"] if category_info else None


def get_all_owasp_codes() -> list:
    """Retorna lista de todos los códigos OWASP Top 10 disponibles"""
    return list(OWASP_TOP10_2021.keys())


def is_valid_owasp_code(code: str) -> bool:
    """Verifica si un código OWASP es válido"""
    return code.upper() in OWASP_TOP10_2021

