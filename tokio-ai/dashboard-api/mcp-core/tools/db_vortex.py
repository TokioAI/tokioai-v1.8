"""
DatabaseVortex - Conexión unificada a PostgreSQL
VORTEX 9: Un solo punto de acceso que abstrae toda la complejidad
Vibración 3: Elegante en su simplicidad
Vibración 6: Rigurosa en su eficiencia
Vibración 9: Máxima abstracción - un método hace todo
"""
import os
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional
import time

logger = logging.getLogger(__name__)

class DatabaseVortex:
    """
    VORTEX 9: Conexión unificada que se auto-repara y optimiza
    Vibración 3: Elegante en su simplicidad
    Vibración 6: Rigurosa en su eficiencia
    Vibración 9: Máxima abstracción - un método hace todo
    """
    
    _session: Optional[aiohttp.ClientSession] = None
    _base_url: str = None
    _last_health_check: float = 0
    _health_check_interval: float = 60.0  # Verificar salud cada 60s
    
    @classmethod
    def _get_base_url(cls) -> str:
        """VORTEX 9: Un cálculo hace el trabajo de múltiples ifs"""
        if cls._base_url:
            return cls._base_url
        
        # VORTEX 6: En Cloud Run, usar la URL del servicio o localhost según el contexto
        dashboard_url = os.getenv('DASHBOARD_API_BASE_URL')
        if dashboard_url:
            cls._base_url = dashboard_url.rstrip('/')
            logger.info(f"🔧 DatabaseVortex usando URL externa: {cls._base_url}")
        else:
            # Fallback: localhost (para desarrollo local o mismo contenedor)
            port = os.getenv('PORT', '8080')
            cls._base_url = f'http://YOUR_IP_ADDRESS:{port}'
            logger.info(f"🔧 DatabaseVortex usando localhost: {cls._base_url}")
        
        return cls._base_url
    
    @classmethod
    async def _ensure_session(cls):
        """VORTEX 6: Pool de conexiones HTTP reutilizable"""
        if cls._session is None or cls._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=150,  # Más margen para queries pesadas y picos
                connect=15,
                sock_read=120
            )
            cls._session = aiohttp.ClientSession(timeout=timeout)
    
    @classmethod
    async def _health_check(cls) -> bool:
        """VORTEX 6: Verificación proactiva de salud"""
        now = time.time()
        if now - cls._last_health_check < cls._health_check_interval:
            return True  # Asumir salud si check reciente
        
        try:
            await cls._ensure_session()
            async with cls._session.get(f"{cls._get_base_url()}/health") as resp:
                cls._last_health_check = now
                return resp.status == 200
        except:
            cls._last_health_check = now
            return False
    
    @classmethod
    async def query(
        cls,
        endpoint: str,
        params: Dict[str, Any],
        max_retries: int = 4,
        retry_delay: float = 1.5
    ) -> Dict[str, Any]:
        """
        VORTEX 9: Un solo método que hace todo - query con auto-recuperación
        Vibración 3: Elegante en su simplicidad
        Vibración 6: Retry exponencial, timeouts adaptativos
        Vibración 9: Máxima abstracción
        """
        await cls._ensure_session()
        
        url = f"{cls._get_base_url()}{endpoint}"
        token = os.getenv("AUTOMATION_API_TOKEN", "").strip()
        headers = {"X-Automation-Token": token} if token else None
        
        # VORTEX 6: Retry exponencial con backoff
        for attempt in range(max_retries):
            try:
                async with cls._session.post(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"✅ Query exitosa: {endpoint} (intento {attempt + 1})")
                        return result
                    else:
                        error_text = await response.text()
                        logger.warning(f"⚠️ Status {response.status}: {error_text[:200]}")
                        
                        # VORTEX 6: No retry en errores 4xx (client error)
                        if 400 <= response.status < 500:
                            return {
                                "success": False,
                                "error": f"Error del cliente: {response.status} - {error_text[:200]}",
                                "logs": []
                            }
                        
                        # VORTEX 6: Retry en errores 5xx (server error)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (2 ** attempt))
                            continue
                        
                        return {
                            "success": False,
                            "error": f"Error del servidor: {response.status} - {error_text[:200]}",
                            "logs": []
                        }
            
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
                logger.warning(f"⏱️ Timeout en intento {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    # VORTEX 6: Backoff exponencial
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                return {
                    "success": False,
                    "error": "Timeout: La consulta tardó demasiado después de múltiples intentos",
                    "logs": []
                }
            
            except aiohttp.ClientError as e:
                logger.warning(f"🔌 Error de conexión en intento {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    # VORTEX 6: Recrear sesión si hay error de conexión
                    if cls._session:
                        await cls._session.close()
                        cls._session = None
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                return {
                    "success": False,
                    "error": f"Error de conexión después de {max_retries} intentos: {str(e)}",
                    "logs": []
                }
        
        return {
            "success": False,
            "error": "Error desconocido después de múltiples intentos",
            "logs": []
        }
    
    @classmethod
    async def close(cls):
        """VORTEX 6: Limpieza elegante de recursos"""
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None
